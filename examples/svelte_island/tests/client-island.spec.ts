import { expect, test } from "@playwright/test";

test("Svelte island saves, unmounts for boosted navigation, and remounts", async ({
  page,
}) => {
  const externalRequests: string[] = [];
  page.on("request", (request) => {
    if (new URL(request.url()).origin !== "http://127.0.0.1:8766") {
      externalRequests.push(request.url());
    }
  });
  await page.addInitScript(() => {
    const state = window as typeof window & {
      islandAbortCount?: number;
      islandEvents?: string[];
    };
    state.islandEvents = [];
    state.islandAbortCount = 0;
    const abort = AbortController.prototype.abort;
    AbortController.prototype.abort = function (reason?: unknown) {
      state.islandAbortCount = (state.islandAbortCount ?? 0) + 1;
      return abort.call(this, reason);
    };
    document.addEventListener("client-island:mount", () =>
      state.islandEvents?.push("mount"),
    );
    document.addEventListener("client-island:unmount", () =>
      state.islandEvents?.push("unmount"),
    );
  });
  await page.goto("/");
  await expect(
    page.getByRole("region", { name: "Project editor" }),
  ).toBeVisible();
  await page.getByLabel("Project name").fill("   ");
  await page.getByRole("button", { name: "Save" }).click();
  await expect(page.getByRole("alert")).toHaveText("Enter a project name.");
  await page.getByLabel("Project name").fill("Calm Svelte editor");
  await page.getByLabel("Pin this project").check();
  await expect(page.getByTestId("dirty-state")).toHaveText("Unsaved changes");
  await page.getByRole("button", { name: "Save" }).click();
  await expect(page.getByRole("status")).toHaveText("Saved");
  await expect(page.getByTestId("dirty-state")).toHaveText(
    "No unsaved changes",
  );
  let markPendingSaveStarted: () => void = () => {};
  let releasePendingSave: () => void = () => {};
  let markPendingSaveCompleted: () => void = () => {};
  const pendingSaveStarted = new Promise<void>((resolve) => {
    markPendingSaveStarted = resolve;
  });
  const pendingSaveRelease = new Promise<void>((resolve) => {
    releasePendingSave = resolve;
  });
  const pendingSaveCompleted = new Promise<void>((resolve) => {
    markPendingSaveCompleted = resolve;
  });
  await page.route("**/save", async (route) => {
    markPendingSaveStarted();
    await pendingSaveRelease;
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        project: { name: "Should not persist", pinned: false },
      }),
    });
    markPendingSaveCompleted();
  });
  await page.getByLabel("Project name").fill("Pending Svelte editor");
  await page.getByRole("button", { name: "Save" }).click();
  await pendingSaveStarted;
  await page.evaluate(() => {
    (window as typeof window & { shellMarker?: string }).shellMarker =
      "same-document";
  });
  await page.getByRole("link", { name: "Cancel" }).click();
  await expect(
    page.getByRole("heading", { name: "About the Svelte island" }),
  ).toBeVisible();
  expect(
    await page.evaluate(
      () => (window as typeof window & { shellMarker?: string }).shellMarker,
    ),
  ).toBe("same-document");
  expect(
    await page.evaluate(
      () => (window as typeof window & { islandEvents?: string[] }).islandEvents,
    ),
  ).toEqual(["mount", "unmount"]);
  expect(
    await page.evaluate(
      () =>
        (window as typeof window & { islandAbortCount?: number })
          .islandAbortCount,
    ),
  ).toBe(1);
  releasePendingSave();
  await pendingSaveCompleted;
  await page.goBack();
  await expect(page.getByLabel("Project name")).toHaveValue(
    "Calm Svelte editor",
  );
  await expect(page.getByLabel("Pin this project")).toBeChecked();
  expect(
    await page.evaluate(
      () => (window as typeof window & { islandEvents?: string[] }).islandEvents,
    ),
  ).toEqual(["mount", "unmount", "mount"]);
  expect(externalRequests).toEqual([]);
});
