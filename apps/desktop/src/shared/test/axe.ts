/** Accessibility assertions shared by every surface test. */

import { axe } from "vitest-axe";

/**
 * Run axe and return only the findings that gate the build.
 *
 * Serious and critical violations block a real person from using the workbench. Minor and
 * moderate advisories are worth reading but are not failures, and treating them as failures
 * would train everyone to ignore the check.
 */
export async function seriousViolations(container: Element): Promise<ReadonlyArray<string>> {
  // jsdom has no canvas, so axe cannot sample rendered pixels and its colour-contrast rule
  // would silently pass. Contrast is checked directly against the theme tokens instead.
  const results = await axe(container, { rules: { "color-contrast": { enabled: false } } });
  return results.violations
    .filter((violation) => violation.impact === "serious" || violation.impact === "critical")
    .map((violation) => `${violation.id}: ${violation.help}`);
}
