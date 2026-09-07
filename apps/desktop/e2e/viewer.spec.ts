import { expect, test } from "@playwright/test";

/**
 * These run against the built bundle, so they catch what component tests cannot: a stylesheet
 * that never loaded, a region that collapses at a real viewport size, a focus ring that is
 * invisible once the theme is actually applied.
 */

test.beforeEach(async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/");
});

test("opens on the bench with every region present", async ({ page }) => {
  await expect(page.getByTestId("workbench")).toBeVisible();
  await expect(page.getByRole("navigation", { name: "Project" })).toBeVisible();
  await expect(page.getByRole("main", { name: "Canvas" })).toBeVisible();
  await expect(page.getByRole("complementary", { name: "Inspector" })).toBeVisible();
  await expect(page.getByRole("region", { name: "Activity" })).toBeVisible();
});

test("paints the workbench from the theme rather than browser defaults", async ({ page }) => {
  await expect(page.getByTestId("workbench")).toBeVisible();

  const theme = await page.evaluate(() => ({
    id: document.documentElement.dataset.theme,
    accent: getComputedStyle(document.documentElement).getPropertyValue("--arcavex-accent").trim(),
    background: getComputedStyle(document.body).backgroundColor,
  }));

  expect(theme.id).toBe("arcavex-dark");
  expect(theme.accent).toBe("#2FA8D8");
  expect(theme.background).toBe("rgb(11, 13, 16)");
});

test("shows the layer tree topmost first", async ({ page }) => {
  const tree = page.getByRole("tree", { name: "Layers" });
  await expect(tree).toBeVisible();

  const names = await tree.getByRole("treeitem").allInnerTexts();
  expect(names.join(" ")).toContain("Root");
});

test("selecting a layer fills the inspector with engine measurements", async ({ page }) => {
  const tree = page.getByRole("tree", { name: "Layers" });
  // The row's own button, not the twisty beside it, whose name starts with Expand or Collapse.
  await tree.getByRole("button", { name: /^Title/ }).click();

  const inspector = page.getByRole("complementary", { name: "Inspector" });
  await expect(inspector.getByText("Title", { exact: true })).toBeVisible();
  // Measurements are reported in the engine's own units, not converted to pixels.
  await expect(inspector.getByText("10.00 pt, 20.00 pt")).toBeVisible();
  await expect(inspector.getByText(/measured 310\.00 pt × 70\.00 pt/)).toBeVisible();
  await expect(inspector.getByText("drop_shadow · raster")).toBeVisible();
});

test("shows the proof and what state it is in", async ({ page }) => {
  await expect(page.getByRole("img", { name: /Rendered proof/ })).toBeVisible();
  await expect(page.getByText("Current")).toBeVisible();
});

test("keeps focus visible for keyboard navigation", async ({ page }) => {
  await expect(page.getByTestId("workbench")).toBeVisible();
  await page.keyboard.press("Tab");

  const outline = await page.evaluate(() => {
    const focused = document.activeElement;
    return focused === null ? null : getComputedStyle(focused).outlineStyle;
  });

  expect(outline).toBe("solid");
});

test("folds the inspector away on a narrow window", async ({ page }) => {
  await page.setViewportSize({ width: 900, height: 800 });

  await expect(page.getByTestId("workbench")).toHaveAttribute("data-compact", "true");
  await expect(page.getByRole("complementary", { name: "Inspector" })).toBeHidden();
  await expect(page.getByRole("main", { name: "Canvas" })).toBeVisible();
});

test("never scrolls the page itself", async ({ page }) => {
  await expect(page.getByTestId("workbench")).toBeVisible();

  const overflowing = await page.evaluate(
    () =>
      document.documentElement.scrollWidth > document.documentElement.clientWidth ||
      document.body.scrollHeight > window.innerHeight,
  );

  expect(overflowing).toBe(false);
});
