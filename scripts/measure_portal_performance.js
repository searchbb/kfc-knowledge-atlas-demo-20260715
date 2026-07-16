#!/usr/bin/env node
const { chromium } = require("@playwright/test");
const fs = require("node:fs");
const path = require("node:path");
const { performance } = require("node:perf_hooks");

const siteRoot = path.resolve(__dirname, "..");
const baseURL = (process.env.PORTAL_BASE_URL || "https://searchbb.github.io/ai-signals-observer/").replace(/\/?$/, "/");
const outputPath = process.env.PORTAL_PERF_OUTPUT || path.join(siteRoot, "output/playwright/online-performance.json");
const profiles = [
  { name: "normal_4g", latency: 150, download: 200 * 1024, upload: 80 * 1024, limits: { post_ttfb: 300, detail: 2000 } },
  { name: "slow_mobile", latency: 300, download: 100 * 1024, upload: 40 * 1024, limits: { post_ttfb: 300, detail: 4000 } },
];

async function runAttempt(browser, profile, attempt) {
  const context = await browser.newContext({ viewport: { width: 390, height: 844 } });
  const page = await context.newPage();
  const session = await context.newCDPSession(page);
  await session.send("Network.enable");
  await session.send("Network.setCacheDisabled", { cacheDisabled: true });
  await session.send("Network.emulateNetworkConditions", {
    offline: false,
    latency: profile.latency,
    downloadThroughput: profile.download,
    uploadThroughput: profile.upload,
    connectionType: "cellular4g",
  });
  const requests = [];
  page.on("request", (request) => requests.push(request.url()));
  const started = performance.now();
  await page.goto(`${baseURL}#home`, { waitUntil: "domcontentloaded", timeout: 20000 });
  const skeletonMs = Math.round(performance.now() - started);
  const bootstrapVisible = await page.locator("[data-home-bootstrap] .lead-story").isVisible().catch(() => false);
  const navigationInteractive = await page.locator(".nav a").first().isVisible().catch(() => false);
  await page.locator("#content h3").first().waitFor({ state: "visible", timeout: 15000 });
  const homeMs = Math.round(performance.now() - started);
  const responseStartMs = await page.evaluate(() => Math.round(performance.getEntriesByType("navigation")[0]?.responseStart || 0));
  const postTtfbMs = Math.max(0, homeMs - responseStartMs);

  const detailStarted = performance.now();
  await page.locator(".lead-story").click();
  await page.locator(".report-body article").waitFor({ state: "visible", timeout: 12000 });
  const detailMs = Math.round(performance.now() - detailStarted);
  const siteDataRequests = requests.filter((url) => url.includes("/data/site-data.json"));
  const indexRequests = requests.filter((url) => url.includes("/data/site-index.json"));
  const routeHomeRequests = requests.filter((url) => url.includes("/data/route-home.json"));
  const detailRequests = requests.filter((url) => url.includes("/data/details/"));
  const passed = postTtfbMs <= profile.limits.post_ttfb
    && detailMs <= profile.limits.detail
    && bootstrapVisible
    && navigationInteractive
    && siteDataRequests.length === 0
    && indexRequests.length === 0
    // 静态首页不依赖 route-home；app 尚未启动时可以是 0，后台刷新最多 1 次。
    && routeHomeRequests.length <= 1
    && detailRequests.length >= 1;
  await page.screenshot({
    path: path.join(siteRoot, `output/playwright/performance-${profile.name}-${attempt}.png`),
    fullPage: false,
  });
  await context.close();
  return {
    attempt,
    skeleton_ms: skeletonMs,
    home_content_ms: homeMs,
    detail_content_ms: detailMs,
    bootstrap_visible_at_domcontentloaded: bootstrapVisible,
    response_start_ms: responseStartMs,
    post_ttfb_content_ms: postTtfbMs,
    navigation_interactive: navigationInteractive,
    site_data_requests: siteDataRequests,
    site_index_request_count: indexRequests.length,
    route_home_request_count: routeHomeRequests.length,
    detail_request_count: detailRequests.length,
    passed,
  };
}

(async () => {
  const browser = await chromium.launch({ headless: true });
  const results = [];
  try {
    for (const profile of profiles) {
      const attempts = [];
      for (let attempt = 1; attempt <= 2; attempt += 1) {
        try {
          attempts.push(await runAttempt(browser, profile, attempt));
        } catch (error) {
          attempts.push({ attempt, passed: false, error: error.message });
        }
      }
      results.push({
        profile: profile.name,
        latency_ms: profile.latency,
        download_bytes_per_second: profile.download,
        limits_ms: profile.limits,
        attempts,
        passed: attempts.some((item) => item.passed),
      });
    }
  } finally {
    await browser.close();
  }
  const payload = {
    status: results.every((item) => item.passed) ? "passed" : "failed",
    generated_at: new Date().toISOString(),
    base_url: baseURL,
    results,
  };
  fs.mkdirSync(path.dirname(outputPath), { recursive: true });
  fs.writeFileSync(outputPath, `${JSON.stringify(payload, null, 2)}\n`);
  process.stdout.write(`${JSON.stringify(payload, null, 2)}\n`);
  process.exitCode = payload.status === "passed" ? 0 : 1;
})();
