# AI 资讯观察发布手册

## 数据与同步约定

- 本地结构化文件和新闻 SQLite 是内容来源；公网只读快照不反向写入。
- 正式内容写入成功后，才执行重建、校验、提交、推送和远端哈希验证。
- 来源摘要阻止无变化发布；数量异常下降、孤儿关系、必填字段缺失或本地路径泄漏都会中止发布。
- 新闻只同步最近窗口，不导出完整 SQLite；并发更新通过文件锁串行化。
- 深度研究通过明确清单发布，只允许正式成品，禁止自动扫描并公开过程材料。

## 稳定链接

站点使用以下 hash 路由：

- `#topic/<id>`：专题观察
- `#issue/<id>`：议题追踪
- `#card/<id>`：分析卡片
- `#research/<id>`：深度研究
- `#article/<id>`：文章解读
- `#news/<id>`：新闻资讯

统一地址为 `https://searchbb.github.io/ai-signals-observer/`。邮件只渲染同一套链接，不改变内容状态。

## 发布与回滚

1. 运行 `python3 scripts/sync_portal_data.py --repo-root /path/to/workspace`。
2. 运行 `python3 scripts/validate_portal_data.py` 和真实浏览器测试。
3. 运行 `python3 scripts/publish_portal_site.py --repo-root /path/to/workspace`。
4. 保存 release commit、站点文件 SHA 和公网浏览器证据。
5. 若发现回归，在临时 clone 中先验证 revert，再推送回滚提交。

仓库改名的回滚命令只保存在本地发布证据包中，不写入公开说明。代码版本回滚不会修改本地数据来源。
