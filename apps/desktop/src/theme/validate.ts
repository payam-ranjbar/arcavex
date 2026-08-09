/** Validation for imported theme JSON. An invalid theme is reported, never partially applied. */

import { THEME_COLOR_TOKENS, type ThemeManifest } from "./types.ts";

const HEX_COLOR = /^#[0-9A-Fa-f]{6}$/u;
const APPEARANCES = ["dark", "light"] as const;
const CONTRASTS = ["standard", "high"] as const;

export type ThemeValidation =
  | { readonly ok: true; readonly theme: ThemeManifest }
  | { readonly ok: false; readonly errors: ReadonlyArray<string> };

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function readString(
  source: Record<string, unknown>,
  key: string,
  errors: string[],
): string | undefined {
  const value = source[key];
  if (typeof value !== "string" || value.trim() === "") {
    errors.push(`${key} must be a non-empty string`);
    return undefined;
  }
  return value;
}

/**
 * Parse a theme manifest, collecting every problem rather than stopping at the first.
 *
 * A partially applied theme is worse than a rejected one: half the workbench would repaint and
 * the rest would not, leaving colours that were never designed to sit together.
 */
export function parseThemeManifest(value: unknown): ThemeValidation {
  const errors: string[] = [];
  if (!isRecord(value)) {
    return { ok: false, errors: ["a theme must be a JSON object"] };
  }

  if (value.version !== 1) {
    errors.push("version must be 1");
  }
  const id = readString(value, "id", errors);
  const name = readString(value, "name", errors);

  const appearance = value.appearance;
  if (!APPEARANCES.includes(appearance as (typeof APPEARANCES)[number])) {
    errors.push(`appearance must be one of ${APPEARANCES.join(", ")}`);
  }
  const contrast = value.contrast ?? "standard";
  if (!CONTRASTS.includes(contrast as (typeof CONTRASTS)[number])) {
    errors.push(`contrast must be one of ${CONTRASTS.join(", ")}`);
  }

  const colors = value.colors;
  const parsedColors: Record<string, string> = {};
  if (!isRecord(colors)) {
    errors.push("colors must be an object");
  } else {
    for (const token of THEME_COLOR_TOKENS) {
      const color = colors[token];
      if (typeof color !== "string" || !HEX_COLOR.test(color)) {
        errors.push(`colors.${token} must be a #rrggbb value`);
        continue;
      }
      parsedColors[token] = color;
    }
    const unknown = Object.keys(colors).filter(
      (token) => !THEME_COLOR_TOKENS.includes(token as (typeof THEME_COLOR_TOKENS)[number]),
    );
    for (const token of unknown) {
      errors.push(`colors.${token} is not a theme colour`);
    }
  }

  if (errors.length > 0 || id === undefined || name === undefined) {
    return { ok: false, errors };
  }
  return {
    ok: true,
    theme: {
      version: 1,
      id,
      name,
      appearance: appearance as ThemeManifest["appearance"],
      contrast: contrast as ThemeManifest["contrast"],
      colors: parsedColors as ThemeManifest["colors"],
    },
  };
}

/** Parse theme JSON text, reporting a syntax error the same way as a schema error. */
export function parseThemeJson(text: string): ThemeValidation {
  try {
    return parseThemeManifest(JSON.parse(text));
  } catch (error) {
    return {
      ok: false,
      errors: [`the file is not valid JSON: ${(error as Error).message}`],
    };
  }
}
