const { test, expect } = require("@playwright/test");

const baseURL = process.env.PORTAL_BASE_URL || "http://127.0.0.1:8765/";

test("research page has a native submission form with privacy rules", async ({ page }) => {
  await page.goto(`${baseURL}#research`);
  const form = page.locator("#research-intake-form");
  await expect(form).toBeVisible();
  await expect(page.locator("#research-intake-title")).toHaveText("提交一个深度研究课题");
  await expect(page.locator(".research-submit")).toBeEnabled();
  await expect(page.locator("#research-intake-status")).toContainText("请保存回执编号");
  await expect(page.locator("body")).not.toContainText("GitHub Issue");
  await page.locator('input[name="visibility"][value="private"]').check();
  await expect(page.locator('input[name="requester_email"]')).toHaveAttribute("required", "");
  await expect(page.locator("#visibility-help")).toContainText("不会出现在网站");
  await page.locator('input[name="visibility"][value="public"]').check();
  await expect(page.locator('input[name="requester_email"]')).not.toHaveAttribute("required", "");
});

test("public form submits through the remote queue API and shows a receipt", async ({ page }) => {
  let submitted = null;
  await page.route("**/research-intake-config.js*", async (route) => {
    await route.fulfill({
      contentType: "application/javascript",
      body: 'window.KFC_RESEARCH_INTAKE={endpoint:"https://intake.example",targetMinutes:60};',
    });
  });
  await page.route("https://intake.example/v1/challenge", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        ok: true,
        challenge_id: "CH-1234567890ABCDEF",
        nonce: "browser-e2e",
        difficulty: 8,
      }),
    });
  });
  await page.route("https://intake.example/v1/submissions", async (route) => {
    submitted = route.request().postDataJSON();
    await route.fulfill({
      status: 201,
      contentType: "application/json",
      body: JSON.stringify({
        ok: true,
        status: "queued",
        receipt_id: "RQ-ABCDEF1234567890",
        visibility: "public",
        target_minutes: 60,
      }),
    });
  });

  await page.goto(`${baseURL}#research`);
  await page.locator('input[name="title"]').fill("AI 云推理成本结构研究");
  await page.locator('textarea[name="research_question"]').fill("请系统研究 AI 云推理成本结构、竞争壁垒、反例和未来三年的变化。 ");
  await page.locator('textarea[name="reference_notes"]').fill("优先参考公开财报和产业数据。");
  await page.locator('input[name="consent"]').check();
  await page.locator(".research-submit").click();

  await expect(page.locator("#research-intake-status")).toContainText("RQ-ABCDEF1234567890");
  await expect(page.locator("#research-intake-status")).toContainText("已进入研究队列");
  expect(submitted.title).toBe("AI 云推理成本结构研究");
  expect(submitted.visibility).toBe("public");
  expect(submitted.requester_email).toBe("");
  expect(submitted.challenge_id).toBe("CH-1234567890ABCDEF");
  expect(Number.isSafeInteger(submitted.challenge_counter)).toBeTruthy();
});

test("research form remains readable on mobile", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto(`${baseURL}#research`);
  await expect(page.locator("#research-intake-form")).toBeVisible();
  const layout = await page.evaluate(() => ({
    viewport: window.innerWidth,
    scrollWidth: document.documentElement.scrollWidth,
    buttonWidth: document.querySelector(".research-submit").getBoundingClientRect().width,
  }));
  expect(layout.scrollWidth).toBe(layout.viewport);
  expect(layout.buttonWidth).toBeGreaterThan(300);
});
