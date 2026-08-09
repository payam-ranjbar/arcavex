/** What the workbench shows before a project is open: a way in, and the bench's own identity. */

import type { ReactNode } from "react";

import { useTheme } from "../../theme/ThemeProvider.tsx";

import "./welcome.css";

export interface WelcomeScreenProps {
  readonly recentProjects: ReadonlyArray<string>;
  /** Opens the directory chooser. */
  readonly onBrowse: () => void;
  readonly onOpen: (path: string) => void;
  /** Shown when the engine is not usable; opening a project would only fail. */
  readonly engineMessage?: string | null;
}

/** The last path segment is what a person recognizes; the rest is where it lives. */
function splitPath(path: string): { readonly name: string; readonly parent: string } {
  const parts = path.split(/[\\/]/u).filter(Boolean);
  return {
    name: parts.at(-1) ?? path,
    parent: parts.slice(0, -1).join("/"),
  };
}

export function WelcomeScreen({
  recentProjects,
  onBrowse,
  onOpen,
  engineMessage,
}: WelcomeScreenProps): ReactNode {
  const { branding } = useTheme();

  return (
    <div className="welcome">
      <div className="welcome__sheet">
        <p className="eyebrow">{branding.productName} desktop</p>
        <h2 className="welcome__headline">Open a project to put it on the bench.</h2>
        <p className="welcome__tagline">{branding.about.tagline}</p>

        {engineMessage ? (
          <p className="welcome__engine" role="alert">
            {engineMessage}
          </p>
        ) : null}

        <button type="button" className="welcome__browse" onClick={onBrowse}>
          Choose a project folder
        </button>

        {recentProjects.length > 0 ? (
          <section className="welcome__recents" aria-labelledby="welcome-recents">
            <h3 className="eyebrow" id="welcome-recents">
              Recent
            </h3>
            <ul>
              {recentProjects.map((path) => {
                const { name, parent } = splitPath(path);
                return (
                  <li key={path}>
                    <button type="button" onClick={() => onOpen(path)}>
                      <span className="welcome__name">{name}</span>
                      <span className="welcome__parent measure">{parent}</span>
                    </button>
                  </li>
                );
              })}
            </ul>
          </section>
        ) : (
          <p className="welcome__empty">
            Nothing opened yet. Arcavex reads the folder in place and never copies it.
          </p>
        )}
      </div>
    </div>
  );
}
