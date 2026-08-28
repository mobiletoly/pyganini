import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "tests",
  use: {
    baseURL: "http://127.0.0.1:8766",
    browserName: "chromium",
  },
  webServer: {
    command: "uv run uvicorn app.main:app --host 127.0.0.1 --port 8766",
    url: "http://127.0.0.1:8766/",
    reuseExistingServer: false,
  },
});
