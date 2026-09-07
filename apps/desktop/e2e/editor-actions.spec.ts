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
  // A button that saves through the host, not a link: a WebView treats a download link as a
  // navigation, replacing the whole application with a bare image and writing nothing.
  await expect(page.getByRole("button", { name: "Save image…" })).toBeVisible();
});

test("the inspector scrolls with the wheel, not only by dragging its bar", async ({ page }) => {
  // A grid item defaults to min-height:auto, so the column grew instead of scrolling and the
  // wheel did nothing at all — everything below the first section was unreachable in practice.
  await page
    .getByRole("tree", { name: "Layers" })
    .getByRole("button", { name: /^Title/ })
    .click();

  const inspector = page.getByRole("complementary", { name: "Inspector" });
  const before = await inspector.evaluate((element) => element.scrollTop);
  await inspector.hover();
  await page.mouse.wheel(0, 400);

  await expect
    .poll(async () => inspector.evaluate((element) => element.scrollTop))
    .toBeGreaterThan(before);
});

test("no control is wider than the panel holding it", async ({ page }) => {
  const inspector = page.getByRole("complementary", { name: "Inspector" });
  const overflowing = await inspector.evaluate((panel) => {
    const wide: string[] = [];
    for (const control of panel.querySelectorAll("select, input, button")) {
      if (control.getBoundingClientRect().width > panel.getBoundingClientRect().width + 1) {
        wide.push(control.getAttribute("aria-label") ?? control.tagName);
      }
    }
    return wide;
  });

  expect(overflowing).toEqual([]);
});

test("the canvas pans with the wheel and zooms with Ctrl held", async ({ page }) => {
  // Panning was on the middle mouse button alone and nothing said so, so past Fit you were
  // stuck looking at one slice of the poster — zoom was useless exactly when it was wanted.
  const canvas = page.getByRole("application", { name: "Canvas" });
  const readout = page.locator(".proof-strip__zoom");
  const zoomBefore = await readout.textContent();

  await canvas.hover();
  await page.mouse.wheel(0, 300);
  await expect(readout).toHaveText(zoomBefore ?? "");

  await page.keyboard.down("Control");
  await page.mouse.wheel(0, -300);
  await page.keyboard.up("Control");
  await expect(readout).not.toHaveText(zoomBefore ?? "");
});
