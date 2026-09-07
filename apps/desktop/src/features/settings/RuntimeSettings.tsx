/**
 * The three modes that are always visible and always changeable.
 *
 * Automation and extensions default to unrestricted and live render to every change. None of
 * them is ever imposed silently: a mode the user cannot see is a mode they cannot trust.
 */

import type { ReactNode } from "react";

import type { AutomationMode, ExtensionMode, LiveRenderMode } from "../../gateway/index.ts";
import { usePolicy, useSetPolicy, useSettings, useUpdateSettings } from "../projects/index.ts";

const AUTOMATION_LABEL: Record<AutomationMode, string> = {
  unrestricted: "Unrestricted — AI and CLI edits apply immediately",
  review: "Review — edits queue as proposals for approval",
  read_only: "Read only — the project is never written",
};

const EXTENSION_LABEL: Record<ExtensionMode, string> = {
  unrestricted: "Unrestricted — project extensions load and run",
  disabled: "Disabled — only built-in components load",
};

const LIVE_RENDER_LABEL: Record<LiveRenderMode, string> = {
  "every-change": "Every change — re-render the active target as source changes",
  manual: "Manual — render only when asked",
};

export function RuntimeSettings(): ReactNode {
  const settings = useSettings();
  const updateSettings = useUpdateSettings();
  const policy = usePolicy();
  const setPolicy = useSetPolicy();

  const current = policy.data?.policy;
  const liveRender = settings.data?.liveRender ?? "every-change";

  return (
    <div className="runtime">
      <fieldset>
        <legend>Automation</legend>
        <select
          aria-label="Automation mode"
          value={current?.mode ?? "unrestricted"}
          disabled={policy.isError || !current}
          onChange={(event) =>
            setPolicy.mutate({
              version: 1,
              extensions: current?.extensions ?? "unrestricted",
              mode: event.target.value as AutomationMode,
            })
          }
        >
          {Object.entries(AUTOMATION_LABEL).map(([mode, label]) => (
            <option key={mode} value={mode}>
              {label}
            </option>
          ))}
        </select>
      </fieldset>

      <fieldset>
        <legend>Extensions</legend>
        <select
          aria-label="Extension mode"
          value={current?.extensions ?? "unrestricted"}
          disabled={policy.isError || !current}
          onChange={(event) =>
            setPolicy.mutate({
              version: 1,
              mode: current?.mode ?? "unrestricted",
              extensions: event.target.value as ExtensionMode,
            })
          }
        >
          {Object.entries(EXTENSION_LABEL).map(([mode, label]) => (
            <option key={mode} value={mode}>
              {label}
            </option>
          ))}
        </select>
      </fieldset>

      <fieldset>
        <legend>Live render</legend>
        <select
          aria-label="Live render mode"
          value={liveRender}
          onChange={(event) =>
            updateSettings.mutate({ liveRender: event.target.value as LiveRenderMode })
          }
        >
          {Object.entries(LIVE_RENDER_LABEL).map(([mode, label]) => (
            <option key={mode} value={mode}>
              {label}
            </option>
          ))}
        </select>
      </fieldset>
    </div>
  );
}
