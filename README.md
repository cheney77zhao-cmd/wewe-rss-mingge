# WeWe RSS 明歌版

订阅公众号、定时更新文章列表、打开正确原文，通过 RSS 集中阅读。

基于 [WeWe RSS](https://github.com/cooderl/wewe-rss) 的社区衍生版本，附自建微信读书中转。可交给 Codex、WorkBuddy 等工具协助部署；需要 Docker，不是双击安装包。

## 这版整理了什么

- 保留订阅、扫码登录、列表更新和 RSS。
- 自建登录与列表中转，登录凭据加密存入部署者自己的服务器。
- 修正 WR 文章标识直接拼成微信链接造成的“参数错误”，按需解析真实原文。
- SQLite 模式避免同步时同公众号相同标题、日期、封面的别名文章重复入库；不自动删除旧记录。
- 手机侧栏可收起，标题全宽、日期另行显示。
- 头像请求使用 no-referrer 策略。
- 区分登录过期、人工验证和限流，保留暂停保护。

## 全新安装

安装 Docker Engine/Desktop、Compose v2 后：

~~~sh
git clone https://github.com/cheney77zhao-cmd/wewe-rss-mingge.git
cd wewe-rss-mingge
python init_env.py
docker compose config --quiet
docker compose up -d --build
~~~

没有 Python 的容器配置生成方法见 [部署说明](docs/DEPLOY.md)。

本机打开 http://localhost:8088/dash ，使用生成的 .env 中 AUTH_CODE 登录。用自己的微信/微信读书扫码，通过一篇公众号文章链接添加订阅。

**已有 WeWe 请先看 [已有部署接入](docs/DEPLOY.md#已有部署)**，不要覆盖旧 Compose、数据库、数据卷或密钥。仅替换中转不会自动获得应用侧的链接、防重复和手机修复。

## 功能边界

| 环节 | 本版提供什么 |
| --- | --- |
| 扫码与会话 | 本人扫码、加密保存登录态、尝试续期，过期需重登 |
| 列表更新 | 标题、日期、封面、文章标识；受上游可读范围限制 |
| 原文链接 | 按需解析 WR 标识对应的真实微信原文 |
| RSS 全文 | 按需读取与缓存，不等于完整正文永久入库 |
| 正文归档 | 中转有受会话保护的单篇正文接口；未附开箱即用的全量/周度归档器 |
| AI 周报和分析 | 本版不包含，需自行接入工作流 |

列表成功不代表全文已下载。验证码、账号验证和限流仍需本人按平台要求处理，当前没有四位验证码输入界面。

## 交给 AI 部署

> 请先读 README、AGENTS.md 和 docs/DEPLOY.md。确认全新安装还是已有部署，不覆盖旧配置、不删除数据卷。生成独立密钥，让我本人扫码。分别验证服务健康、扫码登录、列表更新、WR 原文跳转和重启保留。未实现的正文归档、AI 分析不能写成已经支持。

[部署与回退](docs/DEPLOY.md) · [结构与接口](docs/ARCHITECTURE.md) · [验证边界](docs/VERIFICATION.md) · [变更](docs/CHANGELOG.md) · [许可与出处](THIRD_PARTY_NOTICES.md)

默认管理入口只绑定本机，中转不开放公网。仅处理有权访问和保存的内容，遵守平台限制；不公开分发采集全文。本项目未经全面安全审计。
