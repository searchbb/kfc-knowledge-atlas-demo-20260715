const { test, expect } = require("@playwright/test");
const path = require("node:path");

const siteRoot = path.resolve(__dirname, "..");
const homeIndexPath = path.join(siteRoot, "data/route-home.json");
const newsIndexPath = path.join(siteRoot, "data/route-news.json");
const baseURL = process.env.PORTAL_BASE_URL || "http://127.0.0.1:8765/";

test("static home remains readable while the fresh home route is delayed", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.route("**/data/route-home.json", async (route) => {
    await new Promise((resolve) => setTimeout(resolve, 3000));
    await route.fulfill({ path: homeIndexPath, contentType: "application/json" });
  });
  await page.goto(`${baseURL}#home`, { waitUntil: "domcontentloaded" });
  await expect(page.locator("[data-home-bootstrap] .lead-story")).toBeVisible();
  await expect(page.locator(".portal-loading")).toBeHidden();
  await page.waitForTimeout(2600);
  await expect(page.locator("#content h3").first()).toContainText("最新 AI 资讯", { timeout: 5000 });
});

test("home is readable even when both app and fresh home data are unavailable", async ({ page }) => {
  await page.route("**/app.js*", (route) => route.abort("failed"));
  await page.route("**/data/route-home.json", (route) => route.abort("failed"));
  await page.goto(`${baseURL}#home`, { waitUntil: "domcontentloaded" });
  await expect(page.locator("[data-home-bootstrap] .lead-story")).toBeVisible();
  await expect(page.locator("#content h3").first()).toContainText("最新 AI 资讯");
  await expect(page.locator(".load-error")).toHaveCount(0);
});

test("a failed non-home route load offers a working retry", async ({ page }) => {
  let requests = 0;
  await page.route("**/data/route-news.json", async (route) => {
    requests += 1;
    if (requests === 1) return route.fulfill({ status: 503, body: "unavailable" });
    return route.fulfill({ path: newsIndexPath, contentType: "application/json" });
  });
  await page.goto(`${baseURL}#news`, { waitUntil: "domcontentloaded" });
  await expect(page.locator(".load-error h3")).toHaveText("内容加载失败");
  await page.locator(".retry-button").click();
  await expect(page.locator("#content h3").first()).toContainText("新闻资讯");
  expect(requests).toBe(2);
});

test("all tabs load only their route index and details load only their shard", async ({ page }) => {
  const requests = [];
  page.on("request", (request) => requests.push(request.url()));
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto(`${baseURL}#home`, { waitUntil: "networkidle" });
  for (const route of ["news", "research", "topics", "issues", "cards", "articles", "timeline", "home"]) {
    await page.evaluate((value) => { window.location.hash = value; }, route);
    await expect(page.locator("#content h3").first()).toBeVisible();
  }
  expect(requests.filter((url) => url.includes("/data/site-index.json"))).toHaveLength(0);
  for (const route of ["home", "news", "research", "topics", "issues", "cards", "articles", "timeline"]) {
    expect(requests.filter((url) => url.includes(`/data/route-${route}.json`))).toHaveLength(1);
  }
  expect(requests.filter((url) => url.includes("/data/site-data.json"))).toHaveLength(0);

  await page.locator(".lead-story").click();
  await expect(page.locator(".detail-header h3")).toBeVisible();
  await expect(page.locator(".report-body article")).toBeVisible();
  expect(requests.filter((url) => url.includes("/data/details/news/"))).toHaveLength(1);
  expect(requests.filter((url) => url.includes("/data/site-data.json"))).toHaveLength(0);
  const layout = await page.evaluate(() => ({
    scrollWidth: document.documentElement.scrollWidth,
    viewportWidth: innerWidth,
  }));
  expect(layout.scrollWidth).toBe(layout.viewportWidth);
});
