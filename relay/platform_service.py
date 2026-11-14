from __future__ import annotations

import hashlib
import json
import logging
import os
import secrets
import sqlite3
import threading
import time
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

from cryptography.fernet import Fernet, InvalidToken

from article_identity import ArticleIdentityError, resolve_article_identity
from weread_client import (
    AuthExpiredError, ArticleValidationError, Credentials, QRDeclinedError, QRExpiredError,
    RiskControlError, WeReadClient, WeReadError,
)

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"), format="%(asctime)s %(levelname)s %(message)s")
LOG = logging.getLogger("wewe-platform-local")


class Store:
    def __init__(self, path: str, secret: str):
        self.path = path
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        try: self.cipher = Fernet(secret.encode())
        except Exception as exc: raise RuntimeError("PLATFORM_SECRET 必须是有效的 Fernet 密钥") from exc
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=15)
        conn.row_factory = sqlite3.Row
        return conn

    def _initialize(self) -> None:
        with self._connect() as conn:
            conn.executescript("""
              PRAGMA journal_mode=WAL;
              CREATE TABLE IF NOT EXISTS sessions (
                token_hash TEXT PRIMARY KEY,
                vid TEXT NOT NULL,
                username TEXT NOT NULL DEFAULT '',
                encrypted_credentials BLOB NOT NULL,
                created_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL,
                blocked_until INTEGER NOT NULL DEFAULT 0,
                last_error TEXT NOT NULL DEFAULT ''
              );
              CREATE INDEX IF NOT EXISTS sessions_vid ON sessions(vid);
              CREATE TABLE IF NOT EXISTS feed_failures (
                token_hash TEXT NOT NULL, mp_id TEXT NOT NULL,
                blocked_until INTEGER NOT NULL, kind TEXT NOT NULL,
                message TEXT NOT NULL,
                PRIMARY KEY(token_hash, mp_id)
              );
            """)

    @staticmethod
    def _hash(token: str) -> str: return hashlib.sha256(token.encode()).hexdigest()

    def create(self, credentials: Credentials) -> str:
        token = secrets.token_urlsafe(36); now = int(time.time())
        encrypted = self.cipher.encrypt(json.dumps(credentials.to_dict(), ensure_ascii=False, separators=(",", ":")).encode())
        with self._connect() as conn:
            conn.execute("INSERT INTO sessions VALUES(?,?,?,?,?,?,0,'')", (self._hash(token), credentials.vid, credentials.name, encrypted, now, now))
        return token

    def load(self, token: str) -> tuple[Credentials, sqlite3.Row]:
        if not token: raise PermissionError("缺少登录令牌")
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM sessions WHERE token_hash=?", (self._hash(token),)).fetchone()
        if row is None: raise PermissionError("登录令牌无效，请重新扫码")
        try: payload = json.loads(self.cipher.decrypt(row["encrypted_credentials"]).decode())
        except (InvalidToken, ValueError, json.JSONDecodeError) as exc: raise PermissionError("本地登录凭证无法解密，请重新扫码") from exc
        return Credentials.from_dict(payload), row

    def update_credentials(self, token: str, credentials: Credentials) -> None:
        encrypted = self.cipher.encrypt(json.dumps(credentials.to_dict(), ensure_ascii=False, separators=(",", ":")).encode())
        with self._connect() as conn:
            conn.execute("UPDATE sessions SET encrypted_credentials=?, username=?, updated_at=? WHERE token_hash=?", (encrypted, credentials.name, int(time.time()), self._hash(token)))

    def block(self, token: str, seconds: int, message: str) -> int:
        until = int(time.time()) + max(60, seconds)
        with self._connect() as conn:
            conn.execute("UPDATE sessions SET blocked_until=?, last_error=?, updated_at=? WHERE token_hash=?", (until, message[:500], int(time.time()), self._hash(token)))
        return until

    def stats(self) -> dict[str, int]:
        now = int(time.time())
        with self._connect() as conn:
            return {
                "sessions": int(conn.execute("SELECT count(*) FROM sessions").fetchone()[0]),
                "blockedSessions": int(conn.execute("SELECT count(*) FROM sessions WHERE blocked_until>?", (now,)).fetchone()[0]),
            }

    def feed_failure(self, token: str, mp_id: str):
        with self._connect() as conn:
            return conn.execute('SELECT * FROM feed_failures WHERE token_hash=? AND mp_id=? AND blocked_until>?',
                                (self._hash(token), mp_id, int(time.time()))).fetchone()

    def fail_feed(self, token: str, mp_id: str, kind: str, message: str, seconds: int) -> None:
        with self._connect() as conn:
            conn.execute('INSERT OR REPLACE INTO feed_failures VALUES(?,?,?,?,?)',
                         (self._hash(token), mp_id, int(time.time()) + seconds, kind, message))


@dataclass
class LoginJob:
    uuid: str
    scan_url: str
    expires_at: float
    condition: threading.Condition = field(default_factory=threading.Condition)
    state: str = "waiting"
    result: dict | None = None
    cookies: dict[str, str] = field(default_factory=dict)


class Application:
    def __init__(self):
        secret = os.environ.get("PLATFORM_SECRET", "")
        if not secret: raise RuntimeError("缺少 PLATFORM_SECRET")
        self.store = Store(os.getenv("PLATFORM_DB", "/data/platform.db"), secret)
        self.client = WeReadClient(min_interval=float(os.getenv("MIN_REQUEST_INTERVAL", "3")))
        self.risk_block_seconds = int(os.getenv("RISK_BLOCK_SECONDS", "21600"))
        self.jobs: dict[str, LoginJob] = {}
        self.jobs_lock = threading.Lock()
        self.article_lock = threading.Lock()

    def start_login(self) -> dict:
        uuid, scan_url, cookies = self.client.request_web_qr()
        job = LoginJob(uuid, scan_url, time.time() + 90, cookies=cookies)
        with self.jobs_lock:
            self.jobs[uuid] = job
            self._prune_jobs()
        threading.Thread(target=self._poll_login, args=(job,), daemon=True, name="qr-login").start()
        return {"uuid": uuid, "scanUrl": scan_url}

    def _prune_jobs(self) -> None:
        now = time.time()
        expired = [key for key, job in self.jobs.items() if job.expires_at + 300 < now]
        for key in expired: self.jobs.pop(key, None)

    def _finish_job(self, job: LoginJob, result: dict) -> None:
        with job.condition:
            job.result = result; job.state = "done"; job.condition.notify_all()

    def _poll_login(self, job: LoginJob) -> None:
        try:
            while time.time() < job.expires_at:
                state, credentials, job.cookies = self.client.poll_web_qr(job.uuid, job.cookies)
                job.state = state
                if state == "confirmed":
                    if credentials is None: raise WeReadError("扫码确认后没有收到登录凭证")
                    credentials = self.client.renew_web(credentials)
                    token = self.store.create(credentials)
                    self._finish_job(job, {"message": "", "vid": int(credentials.vid), "token": token, "username": credentials.name or f"微信读书用户{credentials.vid[-4:]}"})
                    return
                time.sleep(0.5)
            raise QRExpiredError("二维码已过期，请重新生成")
        except (QRExpiredError, QRDeclinedError, WeReadError) as exc:
            LOG.warning("QR login ended: %s", type(exc).__name__)
            self._finish_job(job, {"message": str(exc)})
        except Exception:
            LOG.exception("Unexpected QR login failure")
            self._finish_job(job, {"message": "登录服务暂时异常，请稍后重试"})

    def login_result(self, uuid: str) -> dict:
        with self.jobs_lock: job = self.jobs.get(uuid)
        if job is None: return {"message": "二维码不存在或已过期，请重新生成"}
        with job.condition:
            if job.result is None: job.condition.wait(timeout=max(1.0, min(88.0, job.expires_at - time.time())))
            return job.result or {"message": "二维码已过期，请重新生成"}

    def authenticate(self, headers) -> tuple[str, Credentials, sqlite3.Row]:
        authorization = str(headers.get("Authorization") or "")
        token = authorization[7:].strip() if authorization.lower().startswith("bearer ") else ""
        credentials, row = self.store.load(token)
        xid = str(headers.get("xid") or "").strip()
        if xid and xid != credentials.vid: raise PermissionError("账号与登录令牌不匹配")
        return token, credentials, row

    def articles(self, headers, mp_id: str, page: int) -> list[dict]:
        # Serialize checking state, fetching and persisting credentials. Frontend
        # retries must see the cooldown installed by the first failed request.
        with self.article_lock:
            return self._articles(headers, mp_id, page)

    def article_url(self, headers, mp_id: str, article_id: str) -> dict:
        with self.article_lock:
            return self._articles(headers, mp_id, 1, article_id=article_id)

    def article_content(self, headers, mp_id: str, article_id: str) -> dict:
        with self.article_lock:
            return self._articles(headers, mp_id, 1, article_id=article_id, include_content=True)

    def _articles(self, headers, mp_id: str, page: int, article_id=None, include_content=False):
        token, credentials, row = self.authenticate(headers)
        now = int(time.time())
        if int(row["blocked_until"]) > now:
            wait_minutes = max(1, (int(row["blocked_until"]) - now + 59) // 60)
            raise RiskControlError(f"请求已暂停，约 {wait_minutes} 分钟后再试")
        failure = self.store.feed_failure(token, mp_id)
        if failure:
            error_type = AuthExpiredError if failure['kind'] == 'auth' else ArticleValidationError
            raise error_type(failure['message'])
        try:
            def fetch(credentials):
                if article_id is not None:
                    return self.client.web_article_url(credentials, mp_id, article_id, include_content=True) if include_content else self.client.web_article_url(credentials, mp_id, article_id)
                return self.client.web_articles(credentials, mp_id, page)
            try:
                items, credentials = fetch(credentials)
            except AuthExpiredError:
                # Web credentials must be renewed on the web channel, once only.
                credentials = self.client.renew_web(credentials)
                self.store.update_credentials(token, credentials)
                items, credentials = fetch(credentials)
            self.store.update_credentials(token, credentials)
        except RiskControlError as exc:
            self.store.block(token, self.risk_block_seconds, str(exc))
            raise RiskControlError("微信读书返回限流，已暂停该账号请求，请稍后再试") from exc
        except ArticleValidationError as exc:
            message = f"{exc}；此公众号暂缓6小时，其他公众号可分别尝试；请先在微信读书确认是否可阅读"
            self.store.fail_feed(token, mp_id, 'validation', message, self.risk_block_seconds)
            raise ArticleValidationError(message) from exc
        except AuthExpiredError as exc:
            message = "微信读书登录状态已失效，续期未成功，请重新扫码"
            self.store.fail_feed(token, mp_id, 'auth', message, 300)
            raise AuthExpiredError(message) from exc
        if article_id is not None:
            return items if include_content else {"url": items}
        return [{"id": item.article_id, "title": item.title, "picUrl": item.pic_url, "publishTime": item.publish_time} for item in items]

    def url_to_mp(self, headers, url: str) -> list[dict]:
        self.authenticate(headers)
        identity = resolve_article_identity(url)
        return [{"id": identity.book_id, "cover": identity.cover, "name": identity.account_name or identity.title or identity.book_id, "intro": identity.intro, "updateTime": identity.update_time or int(time.time())}]


APP = Application()


class Handler(BaseHTTPRequestHandler):
    server_version = "WeWePlatformLocal/1.0"

    def log_message(self, fmt: str, *args) -> None:
        LOG.info("%s %s", self.address_string(), fmt % args)

    def send_json(self, status: int, payload) -> None:
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
        self.send_response(status); self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body))); self.send_header("Cache-Control", "no-store")
        self.end_headers(); self.wfile.write(body)

    def do_GET(self) -> None:
        path = unquote(urlparse(self.path).path)
        try:
            if path == "/health": return self.send_json(200, {"ok": True, **APP.store.stats()})
            if path == "/api/v2/login/platform": return self.send_json(200, APP.start_login())
            prefix = "/api/v2/login/platform/"
            if path.startswith(prefix): return self.send_json(200, APP.login_result(path[len(prefix):]))
            marker = "/api/v2/platform/mps/"
            if path.startswith(marker) and path.endswith('/article-content'):
                mp_id = path[len(marker):-len('/article-content')].strip('/')
                query = __import__('urllib.parse', fromlist=['parse_qs']).parse_qs(urlparse(self.path).query)
                return self.send_json(200, APP.article_content(self.headers, mp_id, (query.get('id') or [''])[0]))
            if path.startswith(marker) and path.endswith('/article-url'):
                mp_id = path[len(marker):-len('/article-url')].strip('/')
                query = __import__('urllib.parse', fromlist=['parse_qs']).parse_qs(urlparse(self.path).query)
                return self.send_json(200, APP.article_url(self.headers, mp_id, (query.get('id') or [''])[0]))
            suffix = "/articles"
            if path.startswith(marker) and path.endswith(suffix):
                mp_id = path[len(marker):-len(suffix)].strip("/")
                query = __import__("urllib.parse", fromlist=["parse_qs"]).parse_qs(urlparse(self.path).query)
                page = max(1, int((query.get("page") or ["1"])[0]))
                return self.send_json(200, APP.articles(self.headers, mp_id, page))
            return self.send_json(404, {"message": "接口不存在"})
        except PermissionError as exc: self.send_json(401, {"message": str(exc)})
        except AuthExpiredError as exc: self.send_json(401, {"message": str(exc), "code": "AUTH_EXPIRED"})
        except ArticleValidationError as exc: self.send_json(422, {"message": str(exc), "code": "ARTICLE_VALIDATION_FAILED"})
        except RiskControlError as exc: self.send_json(429, {"message": str(exc)})
        except (WeReadError, ArticleIdentityError, ValueError) as exc: self.send_json(400, {"message": str(exc)})
        except Exception:
            LOG.exception("GET request failed: %s", path); self.send_json(500, {"message": "本地中转服务异常"})

    def do_POST(self) -> None:
        path = unquote(urlparse(self.path).path)
        try:
            length = min(int(self.headers.get("Content-Length") or 0), 64 * 1024)
            payload = json.loads(self.rfile.read(length) or b"{}")
            if path == "/api/v2/platform/wxs2mp": return self.send_json(200, APP.url_to_mp(self.headers, str(payload.get("url") or "")))
            return self.send_json(404, {"message": "接口不存在"})
        except PermissionError as exc: self.send_json(401, {"message": str(exc)})
        except (WeReadError, ArticleIdentityError, ValueError, json.JSONDecodeError) as exc: self.send_json(400, {"message": str(exc)})
        except Exception:
            LOG.exception("POST request failed: %s", path); self.send_json(500, {"message": "本地中转服务异常"})


if __name__ == "__main__":
    port = int(os.getenv("PORT", "8090"))
    LOG.info("Starting local WeWe platform compatibility service on 0.0.0.0:%d", port)
    ThreadingHTTPServer(("0.0.0.0", port), Handler).serve_forever()
