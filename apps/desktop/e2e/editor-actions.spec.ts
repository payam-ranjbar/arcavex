import { expect, test } from "@playwright/test";

/**
 * The actions a designer needs before the application is usable without a terminal beside it.
 *
 * Each of these was missing entirely: a text layer could be moved and resized but not styled,
 * the proof could be looked at but not saved, and the zoom was whatever "Fit" chose.
 */

test.beforeEach(async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/");
  await expect(page.getByTestId("workbench")).toBeVisible();
});

test("a text layer can be restyled, not only moved", async ({ page }) => {
  await page.getByRole("button", { name: "Definition" }).click();
  await page
    .getByRole("tree", { name: "Layers" })
    .getByRole("button", { name: /^Title/ })
    .click();

  const inspector = page.getByRole("complementary", { name: "Inspector" });
  await expect(inspector.getByLabel("Font")).toBeVisible();
  await expect(inspector.getByLabel("Size")).toBeVisible();
  await expect(inspector.getByLabel("Weight")).toBeVisible();
  await expect(inspector.getByLabel("Letter spacing")).toBeVisible();
  await expect(inspector.getByRole("group", { name: "Alignment" })).toBeVisible();
});

test("the proof can be zoomed and returned to actual size", async ({ page }) => {
  const zoom = page.getByRole("group", { name: "Zoom" });
  const readout = page.locator(".proof-strip__zoom");
  const before = await readout.textContent();

  await zoom.getByRole("button", { name: "Zoom in" }).click();

  await expect(readout).not.toHaveText(before ?? "");
  await zoom.getByRole("button", { name: "Actual size" }).click();
  await expect(readout).toHaveText("100%");
});

test("a rendered proof can be saved out of the application", async ({ page }) => {
  await expect(page.getByRole("link", { name: "Save image" })).toBeVisible();
});
