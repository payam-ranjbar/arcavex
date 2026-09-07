/** Applies one theme to the document and offers the rest, including imported ones. */

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";

import { ARCAVEX_BRANDING, BUILT_IN_THEMES, DEFAULT_THEME_ID } from "./builtins.ts";
import {
  cssVariableName,
  THEME_COLOR_TOKENS,
  type BrandingProfile,
  type ThemeManifest,
} from "./types.ts";
import { parseThemeJson, type ThemeValidation } from "./validate.ts";

import "./tokens.css";

export interface ThemeContextValue {
  readonly theme: ThemeManifest;
  readonly themes: ReadonlyArray<ThemeManifest>;
  readonly branding: BrandingProfile;
  readonly selectTheme: (id: string) => void;
  /** Import theme JSON. On failure the current theme is untouched and the errors are returned. */
  readonly importTheme: (text: string) => ThemeValidation;
}

const ThemeContext = createContext<ThemeContextValue | null>(null);

/** Write a theme's colours onto an element as the custom properties components read. */
export function applyTheme(theme: ThemeManifest, element: HTMLElement): void {
  for (const token of THEME_COLOR_TOKENS) {
    element.style.setProperty(cssVariableName(token), theme.colors[token]);
  }
  element.style.setProperty("--arcavex-color-scheme", theme.appearance);
  element.dataset.theme = theme.id;
  element.dataset.contrast = theme.contrast;
}

export interface ThemeProviderProps {
  readonly initialThemeId?: string;
  readonly branding?: BrandingProfile;
  readonly children: ReactNode;
}

export function ThemeProvider({
  initialThemeId,
  branding = ARCAVEX_BRANDING,
  children,
}: ThemeProviderProps): ReactNode {
  const [imported, setImported] = useState<ReadonlyArray<ThemeManifest>>([]);
  const [selectedId, setSelectedId] = useState(initialThemeId ?? DEFAULT_THEME_ID);

  const themes = useMemo(() => [...BUILT_IN_THEMES, ...imported], [imported]);
  // An id naming a theme that is no longer installed falls back rather than leaving the
  // workbench unpainted.
  const theme = themes.find((candidate) => candidate.id === selectedId) ?? BUILT_IN_THEMES[0]!;

  useEffect(() => {
    applyTheme(theme, document.documentElement);
  }, [theme]);

  const importTheme = useCallback((text: string): ThemeValidation => {
    const result = parseThemeJson(text);
    if (result.ok) {
      setImported((current) => [
        ...current.filter((candidate) => candidate.id !== result.theme.id),
        result.theme,
      ]);
      setSelectedId(result.theme.id);
    }
    return result;
  }, []);

  const value = useMemo<ThemeContextValue>(
    () => ({ theme, themes, branding, selectTheme: setSelectedId, importTheme }),
    [theme, themes, branding, importTheme],
  );

  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>;
}

export function useTheme(): ThemeContextValue {
  const value = useContext(ThemeContext);
  if (value === null) {
    throw new Error("useTheme must be used inside <ThemeProvider>");
  }
  return value;
}
