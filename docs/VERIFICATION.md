# 验证记录

这是源码发布，不代表接收者真实账号已通过扫码验收。实际测试结果和 CI 链接将在发布记录中补充。

~~~sh
python -m pip install -r relay/requirements.txt
python scripts/test_relay.py
node app/tests/article-url-regression.cjs
python scripts/check_public.py
~~~

链接回归使用 Node 24 原生 TypeScript，应用容器使用 Node 22。Python 测试仅用临时库、模拟上游，不携带真实账号。

CI 检查 Compose、镜像构建和空数据启动。
未验证：接收者扫码、全部文章可读和全文完整性、长期稳定性、所有架构、公网多用户安全与完整依赖安全审计。AI 分析和批量正文归档不在本版范围。
