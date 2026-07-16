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
  await expect(page.locator("#content h3").first()).toContainText("最近 500 条 / 累计");
  await expect(page.locator(".list-link")).toHaveCount(500);
});

test("public framing, Chinese navigation, and news-first ordering are correct", async ({ page }) => {
  await page.goto(baseURL);
  await expect(page).toHaveTitle("AI 资讯观察");
  await expect(page.locator(".nav a").first()).toHaveText("新闻资讯");
  await expect(page.locator(".nav a").first()).toHaveAttribute("href", "#news");
  await expect(page.locator(".nav")).toContainText("深度研究");
  await expect(page.locator(".nav")).toContainText("专题观察");
  await expect(page.locator(".nav")).toContainText("分析卡片");
  await expect(page.locator(".nav")).toContainText("综合研判");
  await expect(page.locator("body")).not.toContainText("知识资产门户");
  await expect(page.locator("body")).not.toContainText("公开可访问");
  await expect(page.locator(".lead-story")).toBeVisible();
});

test("navigation has one primary path and a mobile-safe overview", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto(`${baseURL}#home`);
  await expect(page.locator(".nav a")).toHaveCount(8);
  await expect(page.locator(".nav a").first()).toHaveText("新闻资讯");
  await expect(page.locator("#stats")).toBeVisible();
  await expect(page.locator(".stats-title")).toHaveText("内容规模");
  await expect(page.locator("#stats .stat")).toHaveCount(6);
  await expect(page.locator("#stats a")).toHaveCount(0);
  await page.screenshot({ path: path.join(siteRoot, "output/playwright/navigation-desktop-final.png"), fullPage: true });

  await page.goto(`${baseURL}#news`);
  await expect(page.locator("#stats")).toBeHidden();
  await expect(page.locator('.nav a[href="#news"]')).toHaveClass(/active/);

  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto(`${baseURL}#home`);
  await expect(page.locator(".sidebar > section")).toBeHidden();
  const mobileLayout = await page.evaluate(() => {
    const nav = document.querySelector(".nav");
    const first = document.querySelector(".nav a").getBoundingClientRect();
    const sidebar = document.querySelector(".sidebar").getBoundingClientRect();
    return {
      navScrollLeft: nav.scrollLeft,
      firstLeft: first.left,
      firstRight: first.right,
      sidebarHeight: sidebar.height,
      viewportWidth: window.innerWidth,
      scrollWidth: document.documentElement.scrollWidth,
    };
  });
  expect(mobileLayout.navScrollLeft).toBeLessThanOrEqual(1);
  expect(mobileLayout.firstLeft).toBeGreaterThanOrEqual(0);
  expect(mobileLayout.firstRight).toBeLessThanOrEqual(mobileLayout.viewportWidth);
  expect(mobileLayout.sidebarHeight).toBeLessThan(220);
  expect(mobileLayout.scrollWidth).toBe(mobileLayout.viewportWidth);
  await page.screenshot({ path: path.join(siteRoot, "output/playwright/navigation-mobile-final.png"), fullPage: true });
});

test("all seven detail protocols open the expected asset", async ({ page }) => {
  const cases = [["topic", data.topics[0]], ["issue", data.issues[0]], ["card", data.cards[0]], ["research", data.research[0]], ["article", data.articles[0]], ["news", data.news[0]]];
  for (const [type, item] of cases) {
    await page.goto(`${baseURL}#${type}/${encodeURIComponent(item.id)}`);
    await expect(page.locator("#content h3").first()).toHaveText(item.title);
    await expect(page.locator("button.copy-link")).toBeVisible();
  }
});

test("analysis cards are fully localized and visually structured", async ({ page }) => {
  const item = data.issues.find((row) => row.id === "ic_code_graph_change_risk_governance")
    || data.issues.find((row) => row.status === "active")
    || data.issues[0];
  await page.goto(`${baseURL}#issue/${encodeURIComponent(item.id)}`);
  await expect(page.locator(".analysis-card-body")).toBeVisible();
  await expect(page.locator(".analysis-section.analysis-question")).toBeVisible();
  await expect(page.locator(".analysis-section.analysis-evidence")).toBeVisible();
  await expect(page.locator(".analysis-section.analysis-risks")).toBeVisible();
  const body = page.locator(".analysis-card-body");
  await expect(body).toContainText("核心问题");
  await expect(body).toContainText("关键证据");
  await expect(body).not.toContainText("Canonical Question");
  await expect(body).not.toContainText("Key Evidence");
  await expect(body).not.toContainText("representative_claims");
  await expect(body).not.toContainText("why_important");
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
  expect(labels.every((label) => label === "新闻资讯")).toBeTruthy();
});

test("all curated research reports open and Mermaid diagrams render as SVG", async ({ page }) => {
  expect(data.research).toHaveLength(19);
  const reportsWithDiagrams = data.research.filter((item) => Number(item.diagramCount || 0) > 0);
  expect(reportsWithDiagrams.length).toBeGreaterThan(0);
  for (const item of data.research) {
    await page.goto(`${baseURL}#research/${encodeURIComponent(item.id)}`);
    await expect(page.locator("#content h3").first()).toHaveText(item.title);
    await expect(page.locator(".report-body article")).toBeVisible();
    if (item.diagramCount) {
      await expect(page.locator(".mermaid-chart svg")).toHaveCount(item.diagramCount, { timeout: 20000 });
      await expect(page.locator(".diagram-fallback")).toHaveCount(0);
    }
  }
});

test("mobile layout remains readable", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto(baseURL);
  await expect(page.locator("h2")).toContainText("AI 资讯观察");
  await expect(page.locator(".nav a").first()).toHaveText("新闻资讯");
  await expect(page.locator(".lead-story")).toBeVisible();
  await page.screenshot({ path: path.join(siteRoot, "output/playwright/portal-mobile-smoke.png"), fullPage: true });
});
