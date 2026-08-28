import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "tests",
  use: {
    baseURL: "http://127.0.0.1:8765",
    browserName: "chromium",
  },
  webServer: {
    command: "uv run uvicorn app.main:app --host 127.0.0.1 --port 8765",
    url: "http://127.0.0.1:8765/",
    reuseExistingServer: false,
  },
});
