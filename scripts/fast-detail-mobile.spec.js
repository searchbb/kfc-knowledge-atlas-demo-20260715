const { test, expect } = require('@playwright/test');
const fs = require('node:fs');
const path = require('node:path');

const siteRoot = path.resolve(__dirname, '..');
const baseURL = process.env.PORTAL_BASE_URL || 'http://127.0.0.1:8765/';
const mailReportPath = path.resolve(
  siteRoot,
  '../../../../../data/semantic_pipeline_v2/investment/loop_engineering/digest_cycles/digest_cycle_20260716T121523+0800/final/digest_briefing.json',
);
const mailReport = JSON.parse(fs.readFileSync(mailReportPath, 'utf8'));
const mailLinks = [
  ...mailReport.digested_articles_24h.map((item) => ({ type: 'article', id: item.article_id })),
  ...[...mailReport.selected_for_digest, ...mailReport.watch_only]
    .map((item) => ({ type: 'news', id: item.article_id })),
];

async function blockFullIndex(page) {
  await page.route('**/data/site-data.json', (route) => route.abort('failed'));
}

test('email article deep link renders title and summary without the full site index', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await blockFullIndex(page);
  const startedAt = Date.now();
  await page.goto(`${baseURL}#article/news_1dadf276c5fb0ff4ead6`, { waitUntil: 'domcontentloaded' });
  await expect(page.locator('.summary')).toBeVisible({ timeout: 5000 });
  await expect(page.locator('.summary')).toContainText('Jetson');
  await expect(page.locator('#content')).not.toContainText('页面加载失败');
  const metrics = await page.evaluate(() => {
    const title = document.querySelector('.detail-title h3');
    const summary = document.querySelector('.summary');
    return {
      titleTop: Math.round(title.getBoundingClientRect().top),
      summaryTop: Math.round(summary.getBoundingClientRect().top),
      summaryTextLength: summary.textContent.trim().length,
      documentWidth: document.documentElement.scrollWidth,
      viewportWidth: innerWidth,
      directDetailMode: document.documentElement.classList.contains('direct-detail'),
    };
  });
  expect(Date.now() - startedAt).toBeLessThan(8000);
  expect(metrics.titleTop).toBeLessThan(260);
  expect(metrics.summaryTop).toBeLessThan(600);
  expect(metrics.summaryTextLength).toBeGreaterThan(100);
  expect(metrics.documentWidth).toBeLessThanOrEqual(metrics.viewportWidth);
  expect(metrics.directDetailMode).toBeTruthy();
  await page.screenshot({ path: path.join(siteRoot, 'output/playwright/email-fast-detail-mobile.png'), fullPage: false });
});

test('inline bootstrap renders the summary even when the main application is unavailable', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.route('**/app.js*', (route) => route.abort('failed'));
  await page.goto(`${baseURL}#article/news_1dadf276c5fb0ff4ead6`, { waitUntil: 'domcontentloaded' });
  await expect(page.locator('.bootstrap-detail .summary')).toContainText('Jetson', { timeout: 8000 });
  await expect(page.locator('.loading-copy')).toHaveCount(0);
});

test('all links in the sent mobile email have non-empty fast detail shards', async ({ request }) => {
  expect(mailLinks).toHaveLength(54);
  const checks = await Promise.all(mailLinks.map(async (item) => {
    const response = await request.get(
      `${baseURL}data/details/${item.type}/${encodeURIComponent(item.id)}.json`,
    );
    expect(response.ok()).toBeTruthy();
    const payload = await response.json();
    expect(payload.type).toBe(item.type);
    expect(payload.id).toBe(item.id);
    expect(payload.item.title.trim().length).toBeGreaterThan(0);
    expect(payload.item.summary.trim().length).toBeGreaterThan(20);
    return item.id;
  }));
  expect(checks).toHaveLength(54);
});

test('analysis-card list no longer overflows at phone widths', async ({ page }) => {
  for (const width of [320, 360, 390, 430]) {
    await page.setViewportSize({ width, height: 844 });
    await page.goto('about:blank');
    await page.goto(`${baseURL}#issues`, { waitUntil: 'domcontentloaded' });
    await expect(page.locator('#content h3').first()).toContainText('分析卡片');
    const documentWidth = await page.evaluate(() => document.documentElement.scrollWidth);
    expect(documentWidth).toBeLessThanOrEqual(width);
  }
});
