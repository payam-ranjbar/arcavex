import { expect, test, type Page } from "@playwright/test";

/**
 * One editing session, end to end, through the built bundle.
 *
 * The unit suites prove each gesture composes the right command; these prove the whole path holds
 * together in a real browser — selection reaching the inspector, a drag reaching the bus, one
 * transaction per gesture, and undo/redo reaching the engine.
 *
 * What is deliberately *not* here: the multi-process half of the workflow — an external CLI edit,
 * the conflict it causes, and the rollback that follows. Those need two operating-system
 * processes over one project, which a browser cannot stage; they live in
 * `tests/e2e/test_editor_external_collaboration.py` against the real engine. This spec covers
 * how the window behaves; that suite covers what the files do.
 */

interface RecordedCall {
  readonly method: string;
  readonly argument?: unknown;
}

test.beforeEach(async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/");
  await expect(page.getByTestId("workbench")).toBeVisible();
});

/** Every call the UI made to the engine, in order. */
async function calls(page: Page): Promise<ReadonlyArray<RecordedCall>> {
  return page.evaluate(
    () => (window as unknown as { arcavexFake: { calls: RecordedCall[] } }).arcavexFake.calls,
  );
}

async function transactions(page: Page): Promise<ReadonlyArray<Record<string, unknown>>> {
  const recorded = await calls(page);
  return recorded
    .filter((call) => call.method === "editorApply")
    .map((call) => call.argument as Record<string, unknown>);
}

/** Commands across every transaction submitted so far. */
async function submittedCommands(page: Page): Promise<ReadonlyArray<Record<string, unknown>>> {
  const applied = await transactions(page);
  return applied.flatMap((t) => (t.commands ?? []) as ReadonlyArray<Record<string, unknown>>);
}

/** Definition mode: the fixture's layers are instances of a repeated definition. */
async function useDefinitionMode(page: Page): Promise<void> {
  await page.getByRole("button", { name: "Definition" }).click();
}

async function selectTitle(page: Page): Promise<void> {
  await page
    .getByRole("tree", { name: "Layers" })
    .getByRole("button", { name: /^Title/ })
    .click();
}

test("a selection flows from the layer tree into the inspector and the canvas", async ({
  page,
}) => {
  await selectTitle(page);

  // The inspector shows the engine's own measurements for what was selected...
  await expect(page.getByRole("complementary", { name: "Inspector" })).toContainText("Title");
  // ...and the canvas draws a selection box with handles around it.
  await expect(page.locator(".overlay__selection")).toBeVisible();
  await expect(page.getByRole("button", { name: "Rotate selection" })).toBeVisible();
});

test("editing a text field submits exactly one transaction", async ({ page }) => {
  await useDefinitionMode(page);
  await selectTitle(page);

  const field = page.getByRole("textbox", { name: "Content" });
  await field.fill("A brand new headline");
  await field.blur();

  await expect.poll(() => transactions(page).then((t) => t.length)).toBe(1);
  const [command] = await submittedCommands(page);
  expect(command).toMatchObject({ kind: "set_text", text: "A brand new headline" });
});

test("a canvas drag becomes one translate, not one per pointer move", async ({ page }) => {
  await selectTitle(page);

  const box = await page.locator(".overlay__selection").boundingBox();
  await page.mouse.move(box!.x + box!.width / 2, box!.y + box!.height / 2);
  await page.mouse.down();
  // Many intermediate moves: a gesture that submitted per-move would be uncoalescable in history.
  await page.mouse.move(box!.x + box!.width / 2 + 60, box!.y + box!.height / 2 + 30, { steps: 12 });
  await page.mouse.up();

  await expect.poll(() => transactions(page).then((t) => t.length)).toBe(1);
  const [command] = await submittedCommands(page);
  expect(command).toMatchObject({ kind: "translate" });
});

test("a resize handle submits a resize", async ({ page }) => {
  await selectTitle(page);

  const handle = page.getByRole("button", { name: "Resize se" });
  const box = await handle.boundingBox();
  await page.mouse.move(box!.x + box!.width / 2, box!.y + box!.height / 2);
  await page.mouse.down();
  await page.mouse.move(box!.x + 70, box!.y + 50, { steps: 10 });
  await page.mouse.up();

  const commands = await submittedCommands(page);
  expect(commands.some((command) => command.kind === "resize")).toBe(true);
});

test("a structural layer action submits its command", async ({ page }) => {
  await useDefinitionMode(page);
  await selectTitle(page);

  await page
    .getByRole("group", { name: "Layer actions" })
    .getByRole("button", { name: "Duplicate" })
    .click();

  await expect
    .poll(() => submittedCommands(page))
    .toContainEqual(expect.objectContaining({ kind: "duplicate" }));
});

test("every transaction carries the revision the window was showing", async ({ page }) => {
  await useDefinitionMode(page);
  await selectTitle(page);
  const field = page.getByRole("textbox", { name: "Content" });
  await field.fill("Revision check");
  await field.blur();

  await expect.poll(() => transactions(page).then((t) => t.length)).toBe(1);
  const [transaction] = await transactions(page);
  // A guessed or absent revision would defeat the conflict guard entirely.
  expect(transaction?.base_project_revision).toMatch(/^[0-9a-f]{64}$/);
  expect(transaction?.project_path).toBeTruthy();
});

test("undo reaches the engine by button and by chord", async ({ page }) => {
  const edits = page.getByRole("group", { name: "Edit history" });

  await edits.getByRole("button", { name: "Undo" }).click();
  await expect
    .poll(() => calls(page).then((c) => c.filter((x) => x.method === "editorUndo").length))
    .toBe(1);

  await page.locator("body").click();
  await page.keyboard.press("Control+z");
  await expect
    .poll(() => calls(page).then((c) => c.filter((x) => x.method === "editorUndo").length))
    .toBe(2);
});

test("a redo someone else's edit ended is disabled with the reason said out loud", async ({
  page,
}) => {
  // The fixture is a branched history: an external edit closed the redo line. Greying the button
  // without saying why is the failure mode this asserts against.
  const edits = page.getByRole("group", { name: "Edit history" });

  await expect(edits.getByRole("button", { name: "Redo" })).toBeDisabled();
  await expect(page.getByText(/edit from outside this window/i)).toBeVisible();
});

test("the whole session is drivable from the keyboard alone", async ({ page }) => {
  await page.keyboard.press("Tab");

  // Walk the tab ring until the layer tree has focus, then move the selection with the arrows.
  for (let step = 0; step < 40; step += 1) {
    const onTree = await page.evaluate(
      () => document.activeElement?.closest('[role="tree"]') !== null,
    );
    if (onTree) break;
    await page.keyboard.press("Tab");
  }

  await page.keyboard.press("ArrowDown");
  await expect(page.getByRole("treeitem", { selected: true })).toHaveCount(1);
});

test("rendering after an edit is still one click away", async ({ page }) => {
  await useDefinitionMode(page);
  await selectTitle(page);
  const field = page.getByRole("textbox", { name: "Content" });
  await field.fill("Then render");
  await field.blur();

  await page
    .getByRole("navigation", { name: "Commands" })
    .getByRole("button", { name: "Render" })
    .click();

  await expect
    .poll(() => calls(page).then((c) => c.some((x) => x.method === "requestRender")))
    .toBe(true);
});
