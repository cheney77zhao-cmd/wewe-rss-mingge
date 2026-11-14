# 部署与回退

## 全新安装

需要 Docker Engine/Desktop 的 Linux 容器、Compose v2、镜像和依赖源以及微信读书网络访问。模板为 SQLite，从随附源码构建，不能用旧官方镜像代替修正版。

在仓库根目录运行 python init_env.py。没有 Python 时：

~~~sh
docker run --rm -v "$(pwd):/work" -w /work python:3.12-slim python init_env.py
~~~

Windows PowerShell：

~~~powershell
docker run --rm -v "${PWD}:/work" -w /work python:3.12-slim python init_env.py
~~~

脚本不覆盖已有 .env、不打印密码。AUTH_CODE 为管理密码；PLATFORM_SECRET 必须与数据库一同备份，丢失后不能解密旧登录态。

~~~sh
docker compose config --quiet
docker compose up -d --build
docker compose ps
~~~

本机访问 http://localhost:8088/dash 。首次构建需下载依赖。
远程服务器可在自己电脑建立隧道：

~~~sh
ssh -L 8088:127.0.0.1:8088 user@YOUR_SERVER
~~~

使用域名时另配 HTTPS 和访问控制，将 SERVER_ORIGIN_URL 改为最终地址。禁止公开中转 8090。AUTH_CODE 不保护 /feeds，请明确 RSS 的可访问范围。

## 已有部署

不要用全新安装模板覆盖旧项目。

1. 备份原 Compose、环境、数据库。SQLite 用一致性备份或停止写入后复制完整目录。
2. 独立解压并生成 .env，确认旧 WeWe 所在 Docker 网络，填 WEWE_NETWORK，检查服务名冲突。
3. 只接入中转：

~~~sh
docker compose -p wewe-relay -f docker-compose.relay.yml config --quiet
docker compose -p wewe-relay -f docker-compose.relay.yml up -d --build
~~~

4. 原 WeWe 配置设置 PLATFORM_URL=http://wewe-platform-local:8090，保留原密码、端口、数据库及挂载，按原方式重新创建容器，只有 restart 不会应用环境变化。
5. 需要本版链接、防重复与手机修复时，仍须构建部署 app 源码。SQLite 目标 app-sqlite；MySQL 目标 app，保持旧 DATABASE_URL、数据库类型和迁移方式，不能直接套用 SQLite 模板。
6. 旧中转令牌不自动迁移，通过界面重新登录本人账号，不清空公众号库。
7. 回退恢复旧镜像、PLATFORM_URL 和启动配置，保留数据与密钥。不提供自动清理旧重复记录的破坏性脚本。

## 验收和限制

- 服务健康、页面打开；本人扫码成功。
- 一个可阅读公众号列表更新，核对标题与时间。
- 普通链接、WR 链接及另一公众号原文都核对标题与目标。
- 重复更新不重复增加同篇记录，重启保留订阅和登录数据。
- 全文需求另核对完整性，不能以列表成功代替。

默认北京时间凌晨 2 点更新列表，可设 CRON_EXPRESSION。列表更新不等于正文永久入库。
扫码等待约 88 秒，反向代理读取超时建议至少 120 秒。
401 为登录失效；422 通常为文章验证；429 为限流，保留暂停。四位验证码暂无输入界面。不要清暂停、换号或密集重试规避。
日志脱敏再反馈，不能上传 .env、完整日志、会话库或 Cookie。
