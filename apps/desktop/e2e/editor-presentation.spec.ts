import { expect, test, type Page } from "@playwright/test";

/**
 * The editing controls under the conditions a person actually runs them in.
 *
 * Phase 1 verified the viewer in light, dark, and high contrast. The editing surfaces — layer
 * actions, inspector fields, selection handles, the Edits panel — arrived after that, and a
 * control that vanishes in forced-colors mode or sits under the fold at 200% scaling is broken
 * for the people who need it most.
 */

async function selectTitle(page: Page): Promise<void> {
  await page
    .getByRole("tree", { name: "Layers" })
    .getByRole("button", { name: /^Title/ })
    .click();
}

/** Every editing control a person needs is on screen and hit-testable. */
async function expectEditingUsable(page: Page): Promise<void> {
  await expect(page.getByTestId("workbench")).toBeVisible();
  await selectTitle(page);

  await expect(page.getByRole("group", { name: "Layer actions" })).toBeVisible();
  await expect(page.getByRole("group", { name: "Edit history" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Rotate selection" })).toBeVisible();

  // Visible is not the same as reachable: a handle drawn under a panel cannot be dragged.
  const handle = page.getByRole("button", { name: "Resize se" });
  await expect(handle).toBeVisible();
  const box = await handle.boundingBox();
  const viewport = page.viewportSize()!;
  expect(box!.x).toBeGreaterThanOrEqual(0);
  expect(box!.y).toBeGreaterThanOrEqual(0);
  expect(box!.x + box!.width).toBeLessThanOrEqual(viewport.width);
  expect(box!.y + box!.height).toBeLessThanOrEqual(viewport.height);
}

for (const scheme of ["light", "dark"] as const) {
  test(`editing controls hold up in ${scheme} mode`, async ({ page }) => {
    await page.emulateMedia({ colorScheme: scheme });
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto("/");

    await expectEditingUsable(page);
  });
}

test("editing controls survive forced-colors (Windows high contrast)", async ({ page }) => {
  await page.emulateMedia({ forcedColors: "active" });
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/");

  await expectEditingUsable(page);

  // A control the system repaints must still announce its state through ARIA, not colour alone.
  await page.getByRole("button", { name: "Definition" }).click();
  await expect(page.getByRole("button", { name: /^(Hide|Show) Title/ })).toHaveAttribute(
    "aria-pressed",
    /true|false/,
  );
});

/**
 * Windows display scaling: 100%, 150%, 200%.
 *
 * The WebView reports scaling as a smaller CSS viewport at a higher device pixel ratio, so a
 * 1920×1080 screen at 200% is a 960×540 page. That is the case where an editing control ends up
 * off-screen or overlapping, and it is reproducible here exactly.
 */
for (const [label, width, height] of [
  ["100%", 1920, 1080],
  ["150%", 1280, 720],
  ["200%", 960, 540],
] as const) {
  test(`editing controls fit at ${label} Windows scaling`, async ({ page }) => {
    await page.setViewportSize({ width, height });
    await page.goto("/");

    await expectEditingUsable(page);
    const overflowed = await page.evaluate(
      () => document.scrollingElement!.scrollWidth > window.innerWidth + 1,
    );
    expect(overflowed).toBe(false);
  });
}
