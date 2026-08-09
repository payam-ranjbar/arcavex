/** The bundled themes and the product identity they are painted onto. */

import type { BrandingProfile, ThemeManifest } from "./types.ts";

/**
 * The default: a darkroom around a lit proof.
 *
 * The accent is registration cyan, the process colour of alignment marks, rather than a
 * decorative brand hue. Amber is never decoration; it means the proof no longer matches source.
 */
export const DARK_THEME: ThemeManifest = {
  version: 1,
  id: "arcavex-dark",
  name: "Darkroom",
  appearance: "dark",
  contrast: "standard",
  colors: {
    surface: "#0B0D10",
    surfaceRaised: "#14181D",
    surfaceSunken: "#07090B",
    border: "#232A32",
    textPrimary: "#E8EBEE",
    textSecondary: "#8A949F",
    accent: "#2FA8D8",
    accentContrast: "#04222E",
    stale: "#D8A22F",
    danger: "#E0603F",
    focus: "#7FD3F5",
  },
};

/** The same bench under room light, for working beside a physical print. */
export const LIGHT_THEME: ThemeManifest = {
  version: 1,
  id: "arcavex-light",
  name: "Daylight",
  appearance: "light",
  contrast: "standard",
  colors: {
    surface: "#EDEFF2",
    surfaceRaised: "#FFFFFF",
    surfaceSunken: "#E3E6EA",
    border: "#C9CFD6",
    textPrimary: "#12171C",
    textSecondary: "#55606B",
    accent: "#146C93",
    accentContrast: "#FFFFFF",
    stale: "#8A5A00",
    danger: "#A32B12",
    focus: "#0B4E6C",
  },
};

/** Maximum separation for low vision, and the only theme that draws pure black on white. */
export const HIGH_CONTRAST_THEME: ThemeManifest = {
  version: 1,
  id: "arcavex-high-contrast",
  name: "High contrast",
  appearance: "dark",
  contrast: "high",
  colors: {
    surface: "#000000",
    surfaceRaised: "#000000",
    surfaceSunken: "#000000",
    border: "#FFFFFF",
    textPrimary: "#FFFFFF",
    textSecondary: "#FFFFFF",
    accent: "#4FC3F7",
    accentContrast: "#000000",
    stale: "#FFD54F",
    danger: "#FF8A80",
    focus: "#FFFFFF",
  },
};

export const BUILT_IN_THEMES: ReadonlyArray<ThemeManifest> = [
  DARK_THEME,
  LIGHT_THEME,
  HIGH_CONTRAST_THEME,
];

export const DEFAULT_THEME_ID = DARK_THEME.id;

export const ARCAVEX_BRANDING: BrandingProfile = {
  version: 1,
  id: "arcavex",
  productName: "Arcavex",
  mark: "AX",
  about: {
    tagline: "A proofing bench for engine-rendered posters.",
    url: "https://github.com/payam-ranjbar/arcavex",
  },
};

export const BUILT_IN_BRANDING: ReadonlyArray<BrandingProfile> = [ARCAVEX_BRANDING];
