import { expect, test, type Page } from "@playwright/test";

/**
 * Direct manipulation against the built bundle.
 *
 * The reducer tests prove what a gesture *means*; these prove the gesture reaches it — pointer
 * capture, a handle that is actually clickable at its drawn position, and an overlay that follows
 * the cursor. Those are exactly the parts a jsdom test cannot see.
 */

test.beforeEach(async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/");
  await expect(page.getByTestId("workbench")).toBeVisible();
});

/** Select a layer through the Layers panel, which needs no canvas geometry. */
async function selectFirstLayer(page: Page): Promise<void> {
  const tree = page.getByRole("tree", { name: "Layers" });
  // The row button, not the twisty beside it, whose name starts with Expand or Collapse.
  await tree.getByRole("button", { name: /^Title/ }).click();
}

test("shows resize and rotate handles once a layer is selected", async ({ page }) => {
  await selectFirstLayer(page);

  await expect(page.getByRole("button", { name: "Resize se" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Rotate selection" })).toBeVisible();
  // Eight resize handles, one per compass point.
  await expect(page.getByRole("button", { name: /^Resize / })).toHaveCount(8);
});

test("a handle sits where the overlay draws the selection", async ({ page }) => {
  await selectFirstLayer(page);

  const selection = page.locator(".overlay__selection");
  const handle = page.getByRole("button", { name: "Resize se" });
  const box = await selection.boundingBox();
  const handleBox = await handle.boundingBox();

  expect(box).not.toBeNull();
  expect(handleBox).not.toBeNull();
  // The south-east handle is centred on the box's bottom-right corner, within a pixel or two.
  expect(Math.abs(handleBox!.x + handleBox!.width / 2 - (box!.x + box!.width))).toBeLessThan(3);
  expect(Math.abs(handleBox!.y + handleBox!.height / 2 - (box!.y + box!.height))).toBeLessThan(3);
});

test("dragging the selection moves the overlay with the pointer", async ({ page }) => {
  await selectFirstLayer(page);

  const selection = page.locator(".overlay__selection");
  const before = await selection.boundingBox();
  expect(before).not.toBeNull();

  await page.mouse.move(before!.x + before!.width / 2, before!.y + before!.height / 2);
  await page.mouse.down();
  await page.mouse.move(before!.x + before!.width / 2 + 80, before!.y + before!.height / 2 + 40, {
    steps: 8,
  });

  const during = await selection.boundingBox();
  expect(during!.x).toBeGreaterThan(before!.x + 40);

  await page.mouse.up();
});

test("Escape abandons a drag and leaves the selection where the engine put it", async ({
  page,
}) => {
  await selectFirstLayer(page);

  const selection = page.locator(".overlay__selection");
  const before = await selection.boundingBox();

  await page.mouse.move(before!.x + before!.width / 2, before!.y + before!.height / 2);
  await page.mouse.down();
  await page.mouse.move(before!.x + before!.width / 2 + 120, before!.y + before!.height / 2, {
    steps: 6,
  });
  await page.keyboard.press("Escape");
  await page.mouse.up();

  const after = await selection.boundingBox();
  expect(Math.abs(after!.x - before!.x)).toBeLessThan(3);
});

test("the canvas never scrolls the page while dragging", async ({ page }) => {
  await selectFirstLayer(page);

  const selection = page.locator(".overlay__selection");
  const box = await selection.boundingBox();
  await page.mouse.move(box!.x + 5, box!.y + 5);
  await page.mouse.down();
  await page.mouse.move(box!.x + 400, box!.y + 400, { steps: 10 });
  await page.mouse.up();

  const overflowed = await page.evaluate(
    () => document.scrollingElement!.scrollHeight > window.innerHeight + 1,
  );
  expect(overflowed).toBe(false);
});
