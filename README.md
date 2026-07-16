# AI 资讯观察

这是一个基于公开信息生成的 AI 新闻与趋势分析站点。GitHub Pages 只保存经过筛选的静态页面、近期新闻窗口和正式研究成品；本地数据库、工作路径、草稿、提示词、素材账本与审阅过程不会发布。

公网地址：`https://searchbb.github.io/ai-signals-observer/`

## 内容范围

- 新闻资讯：最近 500 条公开来源资讯，同时显示本地累计数量。
- 深度研究：由 `scripts/research_publication_manifest.json` 明确选择的正式成品。
- 专题观察、分析卡片与综合研判：结构化的长期观察内容。
- 文章解读：已经进入整理流程的公开文章。

## 发布流程

```bash
/Users/mac/.pyenv/versions/3.10.14/bin/python3 \
  scripts/publish_portal_site.py \
  --repo-root /path/to/local/workspace
```

发布程序依次完成：

1. 从本地来源重建 `data/site-data.json`，并复制研究正文引用的静态图片。
2. 校验数量、必填字段、关系、时间线、研究清单和本地路径泄漏。
3. 仅在内容变化时提交，并在发布锁内推送。
4. 校验公网 `index.html`、`app.js`、`styles.css`、`site-data.json` 和研究图片的 SHA-256。
5. 保留上一版在线内容，失败构建不会覆盖已验证版本。

## 同步边界

本地 SQLite 保存完整新闻历史，数据库文件不会上传。静态站点仅生成最近 500 条新闻窗口；未来若需要几十万或百万条历史在线检索，应采用独立远端查询服务，而不是扩大静态 JSON。

内容成功写入后可触发同一套受保护发布流程；没有新增内容时不会重复提交。

## 新环境复现

```bash
git clone https://github.com/searchbb/ai-signals-observer.git
cd ai-signals-observer
python3 scripts/publish_portal_site.py \
  --repo-root /path/to/local/workspace \
  --skip-push \
  --skip-verify
```

详细路由、回滚和运行检查见 `PRODUCTION_RUNBOOK.md`。
