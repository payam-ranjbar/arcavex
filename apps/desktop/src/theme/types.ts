/** Theme and branding contracts. A theme colours the workbench; branding names the product. */

/**
 * Every colour the workbench can ask for.
 *
 * Components never name a colour, only a role, so a theme can repaint the whole application
 * without any component knowing a theme exists.
 */
export const THEME_COLOR_TOKENS = [
  /** The darkroom around the work. */
  "surface",
  /** Panels and bars sitting on the surface. */
  "surfaceRaised",
  /** Wells: the canvas bed, inputs, code. */
  "surfaceSunken",
  /** Hairlines between regions. */
  "border",
  "textPrimary",
  "textSecondary",
  /** The one accent: selection, active state, registration marks. */
  "accent",
  /** Text and glyphs drawn on top of the accent. */
  "accentContrast",
  /** A proof that no longer matches its source. */
  "stale",
  /** A render or validation that failed. */
  "danger",
  /** The keyboard focus ring, never removed and never the accent alone. */
  "focus",
] as const;

export type ThemeColorToken = (typeof THEME_COLOR_TOKENS)[number];

export interface ThemeManifest {
  readonly version: 1;
  readonly id: string;
  readonly name: string;
  /** Drives the WebView's own form controls and scrollbars. */
  readonly appearance: "dark" | "light";
  readonly contrast: "standard" | "high";
  readonly colors: Readonly<Record<ThemeColorToken, string>>;
}

/**
 * Product identity, versioned separately from any theme.
 *
 * A rebuild for another product name changes this and nothing else; changing the theme never
 * changes what the application calls itself.
 */
export interface BrandingProfile {
  readonly version: 1;
  readonly id: string;
  readonly productName: string;
  /** A short mark drawn in the command bar; two characters at most. */
  readonly mark: string;
  readonly about: {
    readonly tagline: string;
    readonly url: string;
  };
}

/** Turn a token name into the CSS custom property components read. */
export function cssVariableName(token: ThemeColorToken): string {
  return `--arcavex-${token.replace(/[A-Z]/gu, (letter) => `-${letter.toLowerCase()}`)}`;
}
