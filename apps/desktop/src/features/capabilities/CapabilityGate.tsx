/**
 * Disables what the connected engine cannot do, and says so.
 *
 * The engine reports named capabilities. Guessing from a version string would be wrong the
 * moment a build ships a capability out of order, so nothing here reads a version.
 */

import { createContext, useContext, useMemo, type ReactNode } from "react";

const CapabilityContext = createContext<ReadonlySet<string>>(new Set());

export interface CapabilityProviderProps {
  readonly capabilities: ReadonlyArray<string>;
  readonly children: ReactNode;
}

export function CapabilityProvider({ capabilities, children }: CapabilityProviderProps): ReactNode {
  const value = useMemo(() => new Set(capabilities), [capabilities]);
  return <CapabilityContext.Provider value={value}>{children}</CapabilityContext.Provider>;
}

/** Whether the connected engine advertises a capability. */
export function useCapability(capability: string | undefined): boolean {
  const capabilities = useContext(CapabilityContext);
  return capability === undefined || capabilities.has(capability);
}

export interface CapabilityGateProps {
  /** Undefined means the control needs nothing the engine might lack. */
  readonly capability: string | undefined;
  /** What the user is told when the capability is missing. */
  readonly unavailableLabel?: string;
  readonly children: ReactNode;
}

/**
 * Render children, or an explained placeholder when the engine cannot support them.
 *
 * The control is not hidden: a missing capability is information about the engine, and hiding
 * it would leave the user hunting for a feature the documentation says exists.
 */
export function CapabilityGate({
  capability,
  unavailableLabel,
  children,
}: CapabilityGateProps): ReactNode {
  const available = useCapability(capability);
  if (available) {
    return children;
  }
  return (
    <p role="note" data-testid="capability-unavailable">
      {unavailableLabel ?? `The connected engine does not support ${capability ?? "this"}.`}
    </p>
  );
}
