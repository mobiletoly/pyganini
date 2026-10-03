import { defineConfig } from "@playwright/test";

const port = process.env.PYGANINI_ISLAND_PORT ?? "8765";
const baseURL = `http://127.0.0.1:${port}`;

export default defineConfig({
  testDir: "tests",
  use: {
    baseURL,
    browserName: "chromium",
  },
  webServer: {
    command: `uv run uvicorn app.main:app --host 127.0.0.1 --port ${port}`,
    url: `${baseURL}/`,
    reuseExistingServer: false,
  },
});
