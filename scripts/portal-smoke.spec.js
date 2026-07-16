const { test, expect } = require("@playwright/test");
const fs = require("node:fs");
const path = require("node:path");

const siteRoot = path.resolve(__dirname, "..");
const payload = JSON.parse(fs.readFileSync(path.join(siteRoot, "data/site-data.json"), "utf8"));
const data = payload.collections;
const baseURL = process.env.PORTAL_BASE_URL || "http://127.0.0.1:8765/";

test.beforeEach(async ({ page }) => {
  const failures = [];
  page.on("pageerror", (error) => failures.push(error.message));
  page.on("console", (message) => {
    if (message.type() === "error") failures.push(message.text());
  });
  page.__portalFailures = failures;
});

test.afterEach(async ({ page }) => {
  expect(page.__portalFailures, "browser console/page errors").toEqual([]);
});

test("all production entrances render real data", async ({ page }) => {
  for (const route of ["home", "topics", "issues", "cards", "research", "articles", "news", "timeline"]) {
    await page.goto(`${baseURL}#${route}`);
    await expect(page.locator("#content h3").first()).toBeVisible();
    await expect(page.locator("#content")).not.toContainText("站点初始化失败");
  }
  await page.goto(`${baseURL}#news`);
  await expect(page.locator("#content h3").first()).toContainText("最近 500 / 总计");
  await expect(page.locator(".list-link")).toHaveCount(500);
});

test("all seven detail protocols open the expected asset", async ({ page }) => {
  const cases = [["topic", data.topics[0]], ["issue", data.issues[0]], ["card", data.cards[0]], ["research", data.research[0]], ["article", data.articles[0]], ["news", data.news[0]]];
  for (const [type, item] of cases) {
    await page.goto(`${baseURL}#${type}/${encodeURIComponent(item.id)}`);
    await expect(page.locator("#content h3").first()).toHaveText(item.title);
    await expect(page.locator("button.copy-link")).toBeVisible();
  }
});

test("search ranking, relation navigation, and timeline filters work", async ({ page }) => {
  await page.goto(baseURL);
  await page.locator("#search-input").fill("git");
  await expect(page.locator(".search-hit").first()).toContainText("Git 纪律");
  const relation = payload.relations.find((item) => item.fromType === "topic" && item.toType === "issue");
  expect(relation).toBeTruthy();
  await page.goto(`${baseURL}#topic/${relation.fromId}`);
  await expect(page.locator(".relation-node").first()).toBeVisible();
  await page.locator(`.relation-node[href="#issue/${relation.toId}"]`).first().click();
  await expect(page).toHaveURL(new RegExp(`#issue/${relation.toId}$`));
  await expect(page.locator("#content h3").first()).toHaveText(data.issues.find((item) => item.id === relation.toId).title);
  await page.goto(`${baseURL}#timeline`);
  await page.locator('[data-type="news"]').click();
  await expect(page.locator(".timeline-row").first()).toBeVisible();
  const labels = await page.locator(".timeline-row .type-badge").allTextContents();
  expect(labels.every((label) => label === "新闻")).toBeTruthy();
});

test("mobile layout remains readable", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto(baseURL);
  await expect(page.locator("h2")).toContainText("知识资产门户");
  await expect(page.locator(".entry-card")).toHaveCount(3);
  await page.screenshot({ path: path.join(siteRoot, "portal-mobile-smoke.png"), fullPage: true });
});
