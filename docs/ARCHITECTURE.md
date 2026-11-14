# 结构与接口

浏览器 → WeWe 应用 → 自建中转 → 微信读书。

app/apps/web 为 React 界面，app/apps/server 为 NestJS/Prisma；relay 为 Python HTTP 服务。部署后 data/wewe 存应用数据，data/platform 存加密会话库，均不属于公开源码。

WR 标识按需解析：只查询本库文章，提取官方 HTML 元数据原文，验证 HTTPS 和微信域名后跳转；有成功缓存、并发合并，失败不缓存，不从推荐链接猜原文。
SQLite 模式同步防重复匹配同公众号、标题、有效日期、封面一致的别名，保留原主键，不粗暴合并同标题文章。

| 中转接口 | 用途 |
| --- | --- |
| GET /health | 本地健康，不代表上游可读 |
| GET /api/v2/login/platform | 创建扫码 |
| GET /api/v2/login/platform/:uuid | 等待结果 |
| POST /api/v2/platform/wxs2mp | 识别公众号 |
| GET /api/v2/platform/mps/:mpId/articles?page=1 | 列表 |
| GET /api/v2/platform/mps/:mpId/article-url | 真实原文地址 |
| GET /api/v2/platform/mps/:mpId/article-content | 单篇正文，参数及响应以代码为准 |

文章接口使用 Bearer 会话令牌，复用续期、串行请求、验证及限流暂停。扫码接口不是独立管理员入口，中转只能部署在可信内网。

RSS 按需全文、单篇正文接口与永久归档是不同能力。本版不含原环境的 SSH、周度批量归档、采集全文或 AI 报告。
