import { expect, test, type Page } from "@playwright/test";

/**
 * Layer editing against the built bundle.
 *
 * The unit tests prove what each control emits. These prove the controls exist where a person can
 * reach them, and — importantly — that the panel refuses to restructure a rendered instance of a
 * repeated definition. That refusal is the fixture's own shape and the case most likely to be
 * silently wrong, so it is asserted first.
 */

test.beforeEach(async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/");
  await expect(page.getByTestId("workbench")).toBeVisible();
});

function layers(page: Page) {
  return page.getByRole("tree", { name: "Layers" });
}

function title(page: Page) {
  return layers(page).getByRole("button", { name: /^Title/ });
}

/** Definition mode is where a repeated layer's authored definition can be restructured. */
async function useDefinitionMode(page: Page): Promise<void> {
  await page.getByRole("button", { name: "Definition" }).click();
}

test("refuses to restructure a rendered instance, and says where to do it", async ({ page }) => {
  await title(page).click();

  const actions = page.getByRole("group", { name: "Layer actions" });
  await expect(actions.getByRole("button", { name: "Delete" })).toBeDisabled();
  await expect(page.getByText(/Definition mode/i)).toBeVisible();
});

test("enables layer actions in Definition mode", async ({ page }) => {
  await useDefinitionMode(page);
  await title(page).click();

  const actions = page.getByRole("group", { name: "Layer actions" });
  await expect(actions.getByRole("button", { name: "Delete" })).toBeEnabled();
  await expect(actions.getByRole("button", { name: "Duplicate" })).toBeEnabled();
  // Grouping needs more than one layer.
  await expect(actions.getByRole("button", { name: "Group" })).toBeDisabled();
});

test("every editable row exposes a visibility toggle", async ({ page }) => {
  await useDefinitionMode(page);

  await expect(layers(page).getByRole("button", { name: /^(Hide|Show) Title/ })).toBeVisible();
});

test("renaming a layer is reachable by double-click", async ({ page }) => {
  await useDefinitionMode(page);
  await title(page).dblclick();

  await expect(page.getByRole("textbox", { name: /^Rename Title/ })).toBeFocused();
});

test("structural changes are announced politely rather than silently", async ({ page }) => {
  await useDefinitionMode(page);

  const status = page.locator(".layers__status");
  await expect(status).toHaveAttribute("aria-live", "polite");

  await layers(page)
    .getByRole("button", { name: /^Hide Title/ })
    .click();
  await expect(status).toHaveText(/Hid Title/);
});

test("editable layer rows are draggable for reordering", async ({ page }) => {
  await useDefinitionMode(page);
  await title(page).click();

  const row = layers(page).getByRole("treeitem").filter({ hasText: "Title" }).first();
  await expect(row).toHaveAttribute("draggable", "true");
});

test("keyboard navigation moves the selection through the tree", async ({ page }) => {
  await useDefinitionMode(page);
  await layers(page).focus();
  await page.keyboard.press("ArrowDown");

  await expect(layers(page).getByRole("treeitem", { selected: true })).toHaveCount(1);
});
