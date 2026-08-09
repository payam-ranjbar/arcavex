/** Choose a bundled theme, or import one. An invalid file is explained, never applied. */

import { useId, useState, type ChangeEvent, type ReactNode } from "react";

import { useTheme } from "../../theme/ThemeProvider.tsx";

export function AppearanceSettings(): ReactNode {
  const { theme, themes, branding, selectTheme, importTheme } = useTheme();
  const [errors, setErrors] = useState<ReadonlyArray<string>>([]);
  const selectId = useId();
  const fileId = useId();

  function onSelect(event: ChangeEvent<HTMLSelectElement>): void {
    selectTheme(event.target.value);
    setErrors([]);
  }

  async function onImport(event: ChangeEvent<HTMLInputElement>): Promise<void> {
    const file = event.target.files?.[0];
    if (!file) return;
    const result = importTheme(await file.text());
    setErrors(result.ok ? [] : result.errors);
  }

  return (
    <div>
      <p>
        {branding.productName} paints the workbench from one theme. Themes never change what the
        product is called.
      </p>

      <label htmlFor={selectId}>Theme</label>
      <select id={selectId} value={theme.id} onChange={onSelect}>
        {themes.map((candidate) => (
          <option key={candidate.id} value={candidate.id}>
            {candidate.name}
          </option>
        ))}
      </select>

      <label htmlFor={fileId}>Import a theme</label>
      <input
        id={fileId}
        type="file"
        accept="application/json,.json"
        onChange={(event) => void onImport(event)}
      />

      {errors.length > 0 ? (
        <div role="alert">
          <p>That theme was not applied. {theme.name} is still in use.</p>
          <ul>
            {errors.map((error) => (
              <li key={error}>{error}</li>
            ))}
          </ul>
        </div>
      ) : null}
    </div>
  );
}
