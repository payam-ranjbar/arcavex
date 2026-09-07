/** Global test setup: DOM matchers, cleanup, and the browser APIs jsdom leaves out. */

import "@testing-library/jest-dom/vitest";

import { cleanup } from "@testing-library/react";
import { afterEach, beforeEach } from "vitest";

/** A desktop window wide enough for the full three-column bench. */
export const DEFAULT_TEST_WIDTH = 1440;

/** Whether this file's tests run against a DOM; architecture tests deliberately do not. */
const HAS_DOM = typeof window !== "undefined";

/** Resize the simulated window; the workbench reads this through `matchMedia`. */
export function setViewportWidth(width: number): void {
  Object.defineProperty(window, "innerWidth", { value: width, configurable: true });
}

// jsdom implements no media queries at all, and the workbench asks whether the window is
// narrow enough to fold the inspector away. Answering from innerWidth keeps that one question
// truthful without a component ever knowing it is under test.
if (HAS_DOM) {
  Object.defineProperty(window, "matchMedia", {
    configurable: true,
    writable: true,
    value: (query: string): MediaQueryList => {
      const maxWidth = /max-width:\s*(\d+)px/u.exec(query);
      return {
        matches: maxWidth ? window.innerWidth <= Number(maxWidth[1]) : false,
        media: query,
        onchange: null,
        addEventListener: () => {},
        removeEventListener: () => {},
        addListener: () => {},
        removeListener: () => {},
        dispatchEvent: () => false,
      } as MediaQueryList;
    },
  });
}

beforeEach(() => {
  if (HAS_DOM) setViewportWidth(DEFAULT_TEST_WIDTH);
});

afterEach(() => {
  if (HAS_DOM) cleanup();
});
