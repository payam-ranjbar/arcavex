/** Themes repaint the workbench; an invalid one is reported and never partially applied. */

import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { AppearanceSettings } from "../features/settings/index.ts";
import { WelcomeScreen } from "../features/projects/index.ts";
import { seriousViolations } from "../shared/test/axe.ts";
import { BUILT_IN_THEMES, DARK_THEME, HIGH_CONTRAST_THEME, LIGHT_THEME } from "./builtins.ts";
import { ThemeProvider } from "./ThemeProvider.tsx";
import { cssVariableName, THEME_COLOR_TOKENS } from "./types.ts";
import { parseThemeJson, parseThemeManifest } from "./validate.ts";

function themeJson(overrides: Record<string, unknown> = {}): string {
  return JSON.stringify({ ...DARK_THEME, id: "imported", name: "Imported", ...overrides });
}

describe("built-in themes", () => {
  it("define every colour the workbench can ask for", () => {
    for (const theme of BUILT_IN_THEMES) {
      const missing = THEME_COLOR_TOKENS.filter((token) => !theme.colors[token]);
      expect(missing, theme.id).toEqual([]);
    }
  });

  it("ship one standard dark, one standard light, and one high contrast", () => {
    expect(BUILT_IN_THEMES.map((theme) => theme.id)).toEqual([
      DARK_THEME.id,
      LIGHT_THEME.id,
      HIGH_CONTRAST_THEME.id,
    ]);
    expect(HIGH_CONTRAST_THEME.contrast).toBe("high");
  });

  it("are themselves valid manifests", () => {
    for (const theme of BUILT_IN_THEMES) {
      expect(parseThemeManifest(theme).ok, theme.id).toBe(true);
    }
  });

  // axe cannot check contrast under jsdom, so the tokens are checked directly. This is the
  // stronger test anyway: it reads the palette rather than whatever happened to be rendered.
  it("keeps every text pairing readable at WCAG AA", () => {
    for (const theme of BUILT_IN_THEMES) {
      const { colors } = theme;
      for (const [foreground, background, label] of [
        [colors.textPrimary, colors.surface, "textPrimary on surface"],
        [colors.textPrimary, colors.surfaceRaised, "textPrimary on surfaceRaised"],
        [colors.textPrimary, colors.surfaceSunken, "textPrimary on surfaceSunken"],
        [colors.textSecondary, colors.surfaceRaised, "textSecondary on surfaceRaised"],
        [colors.accentContrast, colors.accent, "accentContrast on accent"],
        [colors.accent, colors.surfaceRaised, "accent on surfaceRaised"],
      ] as const) {
        expect(
          contrastRatio(foreground, background),
          `${theme.id}: ${label}`,
        ).toBeGreaterThanOrEqual(4.5);
      }
    }
  });

  it("keeps the focus ring visible against every surface it lands on", () => {
    for (const theme of BUILT_IN_THEMES) {
      for (const surface of [
        theme.colors.surface,
        theme.colors.surfaceRaised,
        theme.colors.surfaceSunken,
      ]) {
        // 1.4.11 non-text contrast: a focus indicator is a UI component boundary, not text.
        expect(contrastRatio(theme.colors.focus, surface), theme.id).toBeGreaterThanOrEqual(3);
      }
    }
  });
});

/** WCAG 2.x relative luminance for an #rrggbb colour. */
function relativeLuminance(hex: string): number {
  const channels = [1, 3, 5].map((offset) => {
    const value = Number.parseInt(hex.slice(offset, offset + 2), 16) / 255;
    return value <= 0.03928 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4;
  }) as [number, number, number];
  return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2];
}

function contrastRatio(foreground: string, background: string): number {
  const first = relativeLuminance(foreground);
  const second = relativeLuminance(background);
  const [lighter, darker] = first > second ? [first, second] : [second, first];
  return (lighter + 0.05) / (darker + 0.05);
}

describe("theme validation", () => {
  it("rejects a colour that is not a six-digit hex value", () => {
    const result = parseThemeJson(themeJson({ colors: { ...DARK_THEME.colors, accent: "blue" } }));

    expect(result.ok).toBe(false);
    expect(result.ok ? [] : result.errors).toContain("colors.accent must be a #rrggbb value");
  });

  it("reports every missing colour at once rather than one at a time", () => {
    const result = parseThemeJson(themeJson({ colors: { accent: "#2FA8D8" } }));

    expect(result.ok).toBe(false);
    expect((result.ok ? [] : result.errors).length).toBe(THEME_COLOR_TOKENS.length - 1);
  });

  it("rejects a colour name the workbench never reads", () => {
    const result = parseThemeJson(
      themeJson({ colors: { ...DARK_THEME.colors, sidebarGlow: "#FFFFFF" } }),
    );

    expect(result.ok ? [] : result.errors).toContain("colors.sidebarGlow is not a theme colour");
  });

  it("rejects an unsupported manifest version", () => {
    const result = parseThemeJson(themeJson({ version: 2 }));

    expect(result.ok ? [] : result.errors).toContain("version must be 1");
  });

  it("treats a syntax error the same way as a schema error", () => {
    const result = parseThemeJson("{ not json");

    expect(result.ok).toBe(false);
    expect(result.ok ? "" : result.errors[0]).toMatch(/not valid JSON/u);
  });

  it("accepts a manifest that omits contrast and defaults it to standard", () => {
    const { contrast: _dropped, ...withoutContrast } = DARK_THEME;
    const result = parseThemeManifest({ ...withoutContrast, id: "x", name: "X" });

    expect(result.ok && result.theme.contrast).toBe("standard");
  });
});

describe("ThemeProvider", () => {
  it("paints the document with the selected theme's colours", () => {
    render(
      <ThemeProvider>
        <p>bench</p>
      </ThemeProvider>,
    );

    const root = document.documentElement;
    expect(root.dataset.theme).toBe(DARK_THEME.id);
    expect(root.style.getPropertyValue(cssVariableName("accent"))).toBe(DARK_THEME.colors.accent);
    expect(root.style.getPropertyValue(cssVariableName("surfaceRaised"))).toBe(
      DARK_THEME.colors.surfaceRaised,
    );
  });

  it("falls back to the bundled default when the remembered theme is gone", () => {
    render(
      <ThemeProvider initialThemeId="a-theme-that-was-uninstalled">
        <p>bench</p>
      </ThemeProvider>,
    );

    expect(document.documentElement.dataset.theme).toBe(DARK_THEME.id);
  });

  it("switches the whole document when another theme is chosen", async () => {
    render(
      <ThemeProvider>
        <AppearanceSettings />
      </ThemeProvider>,
    );

    await userEvent.selectOptions(screen.getByLabelText("Theme"), HIGH_CONTRAST_THEME.id);

    expect(document.documentElement.dataset.contrast).toBe("high");
    expect(document.documentElement.style.getPropertyValue(cssVariableName("textPrimary"))).toBe(
      HIGH_CONTRAST_THEME.colors.textPrimary,
    );
  });

  it("keeps the current theme when an imported one is invalid, and lists why", async () => {
    render(
      <ThemeProvider>
        <AppearanceSettings />
      </ThemeProvider>,
    );
    const file = new File([themeJson({ colors: { accent: "nope" } })], "broken.json", {
      type: "application/json",
    });

    await userEvent.upload(screen.getByLabelText("Import a theme"), file);

    expect(await screen.findByRole("alert")).toHaveTextContent("Darkroom is still in use");
    expect(document.documentElement.dataset.theme).toBe(DARK_THEME.id);
  });

  it("applies and selects a valid imported theme", async () => {
    render(
      <ThemeProvider>
        <AppearanceSettings />
      </ThemeProvider>,
    );
    const file = new File([themeJson()], "imported.json", { type: "application/json" });

    await userEvent.upload(screen.getByLabelText("Import a theme"), file);

    expect(await screen.findByRole("option", { name: "Imported" })).toBeInTheDocument();
    expect(document.documentElement.dataset.theme).toBe("imported");
  });
});

describe("accessibility", () => {
  it("finds no serious violations on the welcome screen", async () => {
    const { container } = render(
      <ThemeProvider>
        <WelcomeScreen
          recentProjects={["/workspace/poster-one", "/workspace/poster-two"]}
          onBrowse={() => {}}
          onOpen={() => {}}
        />
      </ThemeProvider>,
    );

    expect(await seriousViolations(container)).toEqual([]);
  });

  it("finds no serious violations on appearance settings", async () => {
    const { container } = render(
      <ThemeProvider>
        <AppearanceSettings />
      </ThemeProvider>,
    );

    expect(await seriousViolations(container)).toEqual([]);
  });
});
