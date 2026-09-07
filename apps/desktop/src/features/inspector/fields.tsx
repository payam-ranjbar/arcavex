/**
 * The field primitives every inspector is built from.
 *
 * Three behaviours matter more than their appearance, and all three exist because the field is
 * editing a document another process can also change:
 *
 * - **Local while typing, committed on purpose.** A keystroke is not a transaction. The field
 *   holds a draft, commits on Enter or blur, and reverts on Escape — so one deliberate gesture
 *   becomes one undo step rather than one per character.
 * - **A rerender must not steal the caret.** Renders, watcher events, and snapshot refreshes all
 *   arrive mid-typing; a field that reset itself from props on every render would delete what the
 *   user was writing. The draft wins while focused; the authoritative value wins the moment it
 *   is not.
 * - **Mixed values are shown, not invented.** With a multi-selection whose values differ, the
 *   field says so and leaves them alone until the user types something definite.
 */

import { useEffect, useRef, useState, type ReactNode } from "react";

/** The sentinel a multi-selection uses when its members disagree. */
export const MIXED = Symbol("mixed");
export type FieldValue<T> = T | typeof MIXED;

export interface FieldProps<T> {
  readonly id: string;
  readonly label: string;
  readonly value: FieldValue<T>;
  readonly disabled?: boolean;
  /** Shown instead of the control when editing is not allowed. */
  readonly disabledReason?: string | null;
  readonly onCommit: (value: T) => void;
}

function useDraft<T>(value: FieldValue<T>, format: (value: T) => string) {
  const [draft, setDraft] = useState<string | null>(null);
  const focusedRef = useRef(false);
  // Escape blurs the control, and blur is what commits — so cancelling has to say "not this
  // one" explicitly, or the discarded text would be committed on the way out.
  const cancelledRef = useRef(false);

  // Adopt the authoritative value whenever the user is not mid-edit. Guarding on focus is what
  // keeps an engine event from overwriting a half-typed headline.
  useEffect(() => {
    if (!focusedRef.current) setDraft(null);
  }, [value]);

  const text = draft ?? (value === MIXED ? "" : format(value));
  return { text, draft, setDraft, focusedRef, cancelledRef };
}

export function TextField({
  id,
  label,
  value,
  disabled,
  disabledReason,
  onCommit,
  multiline,
}: FieldProps<string> & { readonly multiline?: boolean }): ReactNode {
  const { text, setDraft, focusedRef, cancelledRef } = useDraft<string>(value, (raw) => raw);
  const mixed = value === MIXED;

  const commit = (next: string) => {
    setDraft(null);
    if (next !== (mixed ? "" : value)) onCommit(next);
  };

  const shared = {
    id,
    value: text,
    disabled,
    placeholder: mixed ? "Mixed" : undefined,
    "aria-describedby": disabledReason ? `${id}-reason` : undefined,
    onFocus: () => {
      focusedRef.current = true;
    },
    onChange: (event: { target: { value: string } }) => setDraft(event.target.value),
    onBlur: (event: { target: { value: string } }) => {
      focusedRef.current = false;
      if (cancelledRef.current) {
        cancelledRef.current = false;
        setDraft(null);
        return;
      }
      commit(event.target.value);
    },
    onKeyDown: (event: React.KeyboardEvent) => {
      if (event.key === "Enter" && !multiline) {
        event.preventDefault();
        commit((event.target as HTMLInputElement).value);
        (event.target as HTMLElement).blur();
      }
      if (event.key === "Escape") {
        event.preventDefault();
        cancelledRef.current = true;
        setDraft(null);
        (event.target as HTMLElement).blur();
      }
    },
  };

  return (
    <div className="field">
      <label className="field__label" htmlFor={id}>
        {label}
      </label>
      {multiline ? (
        <textarea className="field__control" rows={3} {...shared} />
      ) : (
        <input className="field__control" type="text" {...shared} />
      )}
      {disabledReason ? (
        <p className="field__reason" id={`${id}-reason`}>
          {disabledReason}
        </p>
      ) : null}
    </div>
  );
}

export function NumberField({
  id,
  label,
  value,
  disabled,
  disabledReason,
  onCommit,
  step = 1,
  suffix,
}: FieldProps<number> & { readonly step?: number; readonly suffix?: string }): ReactNode {
  const { text, setDraft, focusedRef, cancelledRef } = useDraft<number>(value, (raw) =>
    String(round(raw)),
  );
  const mixed = value === MIXED;

  const commit = (raw: string) => {
    setDraft(null);
    const parsed = Number(raw);
    // A field that silently accepts junk would send NaN geometry the engine must reject; a field
    // that reverts says "that was not a number" without a dialog.
    if (raw.trim() === "" || !Number.isFinite(parsed)) return;
    if (mixed || parsed !== value) onCommit(parsed);
  };

  return (
    <div className="field">
      <label className="field__label" htmlFor={id}>
        {label}
        {suffix ? <span className="field__suffix"> ({suffix})</span> : null}
      </label>
      <input
        id={id}
        className="field__control"
        type="number"
        step={step}
        value={text}
        disabled={disabled}
        placeholder={mixed ? "Mixed" : undefined}
        aria-describedby={disabledReason ? `${id}-reason` : undefined}
        onFocus={() => {
          focusedRef.current = true;
        }}
        onChange={(event) => setDraft(event.target.value)}
        onBlur={(event) => {
          focusedRef.current = false;
          if (cancelledRef.current) {
            cancelledRef.current = false;
            setDraft(null);
            return;
          }
          commit(event.target.value);
        }}
        onKeyDown={(event) => {
          if (event.key === "Enter") {
            event.preventDefault();
            commit((event.target as HTMLInputElement).value);
            (event.target as HTMLElement).blur();
          }
          if (event.key === "Escape") {
            event.preventDefault();
            cancelledRef.current = true;
            setDraft(null);
            (event.target as HTMLElement).blur();
          }
        }}
      />
      {disabledReason ? (
        <p className="field__reason" id={`${id}-reason`}>
          {disabledReason}
        </p>
      ) : null}
    </div>
  );
}

export function ToggleField({
  id,
  label,
  value,
  disabled,
  disabledReason,
  onCommit,
}: FieldProps<boolean>): ReactNode {
  const mixed = value === MIXED;
  return (
    <div className="field field--inline">
      <input
        id={id}
        className="field__checkbox"
        type="checkbox"
        checked={mixed ? false : value}
        ref={(node) => {
          if (node) node.indeterminate = mixed;
        }}
        disabled={disabled}
        aria-describedby={disabledReason ? `${id}-reason` : undefined}
        onChange={(event) => onCommit(event.target.checked)}
      />
      <label className="field__label" htmlFor={id}>
        {label}
      </label>
      {disabledReason ? (
        <p className="field__reason" id={`${id}-reason`}>
          {disabledReason}
        </p>
      ) : null}
    </div>
  );
}

/** Two decimals: the engine lays out in points, and more digits are noise a user cannot act on. */
export function round(value: number): number {
  return Math.round(value * 100) / 100;
}

/** Collapse one property across a selection into a value or the mixed sentinel. */
export function shared<T>(values: ReadonlyArray<T>): FieldValue<T> {
  if (values.length === 0) return MIXED;
  const [first, ...rest] = values;
  return rest.every((value) => value === first) ? (first as T) : MIXED;
}
