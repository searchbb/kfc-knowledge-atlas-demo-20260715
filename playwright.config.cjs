const { defineConfig } = require("@playwright/test");

module.exports = defineConfig({
  testDir: "./scripts",
  testMatch: /portal-smoke\.spec\.js/,
  timeout: 30000,
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
