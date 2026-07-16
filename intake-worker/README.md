# 深度研究公网提交接收器

公开站点仍是 GitHub Pages 静态站；本 Worker 只负责接收用户在站内表单提交的研究课题，并写入私有 D1 队列。浏览器没有队列读取权限，Mac 接收器使用 Bearer secret 拉取并回写幂等导入结果。

中国网络会拦截 `workers.dev`。生产页面因此访问同仓库的 Cloudflare Pages 轻量代理；代理不保存数据，只把受限请求转发到本 Worker。`PROXY_SHARED_SECRET` 用于证明转发来源并恢复真实客户端限流键。

## 安全边界

- CORS 只允许 `https://searchbb.github.io`。
- 私密课题强制合法 Email；公开课题 Email 可选。
- Email、课题正文和参考资料只存在 D1 与本地队列，不进入 GitHub Pages 数据文件。
- 每次提交需要服务端签发、单次使用、五分钟过期的轻量工作量证明；同时按 HMAC 后的 IP 做限流，不保存原始 IP。
- Mac 拉取、确认、失败回写和测试清理均需要 `MAC_PULL_TOKEN`。

## 首次部署

```bash
npx wrangler login
npx wrangler d1 create kfc-research-intake
```

把返回的 `database_id` 写入 `wrangler.toml`，然后：

```bash
npx wrangler d1 migrations apply kfc-research-intake --remote
npx wrangler secret put MAC_PULL_TOKEN
npx wrangler secret put RATE_SALT
npx wrangler deploy
```

两个 secret 都应使用密码管理器生成的高熵随机值；不得提交到 Git。部署后，把可达的 Pages 代理 URL 写入站点根目录的 `research-intake-config.js`，再运行公开页面端到端测试。
