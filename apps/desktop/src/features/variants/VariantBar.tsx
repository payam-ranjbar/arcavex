/** Which format and locale the bench is looking at. Switching one marks the proof stale. */

import type { ReactNode } from "react";

import { useActiveTarget, useProjectSnapshot, useSetActiveTarget } from "../projects/index.ts";

export function VariantBar(): ReactNode {
  const snapshot = useProjectSnapshot();
  const target = useActiveTarget();
  const setTarget = useSetActiveTarget();

  const formats = snapshot.data?.formats ?? [];
  const locales = snapshot.data?.locales ?? [];
  if (formats.length === 0 && locales.length === 0) {
    return <p role="note">This project declares no targets.</p>;
  }

  const current = target.data ?? { format: null, locale: null };

  return (
    <div className="variants">
      <label htmlFor="variant-format">Format</label>
      <select
        id="variant-format"
        value={current.format ?? ""}
        onChange={(event) => setTarget.mutate({ ...current, format: event.target.value || null })}
      >
        {formats.map((format) => (
          <option key={format} value={format}>
            {format}
          </option>
        ))}
      </select>

      <label htmlFor="variant-locale">Locale</label>
      <select
        id="variant-locale"
        value={current.locale ?? ""}
        onChange={(event) => setTarget.mutate({ ...current, locale: event.target.value || null })}
      >
        <option value="">No locale</option>
        {locales.map((locale) => (
          <option key={locale} value={locale}>
            {locale}
          </option>
        ))}
      </select>
    </div>
  );
}
