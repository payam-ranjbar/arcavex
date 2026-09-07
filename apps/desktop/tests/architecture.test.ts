// @vitest-environment node
/** The dependency inversion the desktop rests on, enforced as a test rather than a convention. */

import { readdir, readFile } from "node:fs/promises";
import { dirname, join, relative, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

import { findBoundaryViolations, type SourceFile } from "../src/shared/architecture/boundaries.ts";

const APPLICATION_ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");

function file(path: string, source: string): SourceFile {
  return { path, source };
}

describe("frontend dependency boundaries", () => {
  it("rejects Tauri imports from anywhere outside the gateway adapter", () => {
    const violations = findBoundaryViolations([
      file(
        "src/features/canvas/CanvasViewport.tsx",
        'import { invoke } from "@tauri-apps/api/core";',
      ),
      file("src/app/App.tsx", 'import { listen } from "@tauri-apps/api/event";'),
    ]);

    expect(violations.map((violation) => violation.rule)).toEqual([
      "tauri-outside-gateway",
      "tauri-outside-gateway",
    ]);
  });

  it("allows the gateway adapter to be the one module that speaks Tauri", () => {
    const violations = findBoundaryViolations([
      file("src/gateway/TauriArcavexGateway.ts", 'import { invoke } from "@tauri-apps/api/core";'),
      file("src/gateway/events.ts", 'export { listen } from "@tauri-apps/api/event";'),
    ]);

    expect(violations).toEqual([]);
  });

  it("rejects reaching into another feature past its public entry point", () => {
    const violations = findBoundaryViolations([
      file("src/features/canvas/selection.ts", 'import { flatten } from "../layers/layerTree";'),
      file("src/app/App.tsx", 'import { LayersPanel } from "../features/layers/LayersPanel";'),
    ]);

    expect(violations.map((violation) => violation.rule)).toEqual([
      "cross-feature-deep-import",
      "cross-feature-deep-import",
    ]);
  });

  it("allows a feature's own internals and another feature's public entry point", () => {
    const violations = findBoundaryViolations([
      file("src/features/canvas/CanvasViewport.tsx", 'import { hit } from "./selection";'),
      file("src/features/canvas/CanvasViewport.tsx", 'import { useLayers } from "../layers";'),
      file("src/app/App.tsx", 'import { LayersPanel } from "../features/layers/index.ts";'),
      file("src/features/canvas/deep/nested.ts", 'import { hit } from "../selection";'),
    ]);

    expect(violations).toEqual([]);
  });

  it("reports the offending specifier so a failure names what to fix", () => {
    const [violation] = findBoundaryViolations([
      file("src/features/layers/LayersPanel.tsx", 'import { invoke } from "@tauri-apps/api/core";'),
    ]);

    expect(violation).toMatchObject({
      path: "src/features/layers/LayersPanel.tsx",
      specifier: "@tauri-apps/api/core",
    });
  });

  it("finds no violation anywhere in the checked-in frontend source", async () => {
    const sources = await readSourceTree(join(APPLICATION_ROOT, "src"));

    expect(findBoundaryViolations(sources)).toEqual([]);
  });
});

async function readSourceTree(directory: string): Promise<SourceFile[]> {
  const entries = await readdir(directory, { withFileTypes: true });
  const sources = await Promise.all(
    entries.map(async (entry): Promise<SourceFile[]> => {
      const absolute = join(directory, entry.name);
      if (entry.isDirectory()) return readSourceTree(absolute);
      if (!/\.tsx?$/u.test(entry.name)) return [];
      return [
        {
          path: relative(APPLICATION_ROOT, absolute).replaceAll("\\", "/"),
          source: await readFile(absolute, "utf8"),
        },
      ];
    }),
  );
  return sources.flat();
}
