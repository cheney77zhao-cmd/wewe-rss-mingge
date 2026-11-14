# 验证记录

更新：2026-11-14。这是源码发布，不代表接收者真实账号已通过扫码验收。

本次已通过：
- Windows 本地：33 项中转离线测试、20 个链接断言、115 个公开文件检查。
- GitHub Ubuntu：相同回归、Compose 配置解析、前后端编译、应用与中转 Docker 镜像构建、空数据迁移和页面就绪启动检查。
- 匿名访问：公开仓库、默认分支 README、源码 ZIP 与 Git 克隆端点均返回成功。

[完整 CI 记录](https://github.com/cheney77zhao-cmd/wewe-rss-mingge/actions/runs/43590438207)。
验证代码提交：1ef6e6f91d33e8df8f2dcf48ec94c071ead2d86a。其后的本次发布提交仅更新文档，运行源码一致。

基础镜像采用版本标签，传递依赖未全部逐项锁定；这不是镜像逐字节复现或全面依赖安全审计。保留了上游 Prisma 客户端与工具补丁版本不同的警告，本次构建及启动已通过，后续依赖升级仍需回归验证。

~~~sh
python -m pip install -r relay/requirements.txt
python scripts/test_relay.py
node app/tests/article-url-regression.cjs
python scripts/check_public.py
~~~

链接回归使用 Node 24 原生 TypeScript，应用容器使用 Node 22。Python 测试仅用临时库、模拟上游，不携带真实账号。

CI 检查 Compose、镜像构建和空数据启动。
未验证：接收者扫码、全部文章可读和全文完整性、长期稳定性、所有架构、公网多用户安全与完整依赖安全审计。AI 分析和批量正文归档不在本版范围。
