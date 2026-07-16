const { defineConfig } = require("@playwright/test");

module.exports = defineConfig({
  testDir: "./scripts",
  testMatch: /(?:portal-smoke|fast-detail-mobile|fast-index-performance)\.spec\.js/,
  timeout: 120000,
  retries: process.env.PORTAL_BASE_URL ? 1 : 0,
  expect: {
    timeout: 15000,
  },
  use: {
    browserName: "chromium",
    headless: true,
  },
  webServer: process.env.PORTAL_BASE_URL ? undefined : {
    command: "python3 -m http.server 8765 --bind 127.0.0.1",
    port: 8765,
    reuseExistingServer: true,
  },
});
