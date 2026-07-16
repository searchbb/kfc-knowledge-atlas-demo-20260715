const { defineConfig } = require("@playwright/test");

module.exports = defineConfig({
  testDir: "./scripts",
  testMatch: /portal-smoke\.spec\.js/,
  timeout: 30000,
  use: {
    browserName: "chromium",
    headless: true,
  },
});
