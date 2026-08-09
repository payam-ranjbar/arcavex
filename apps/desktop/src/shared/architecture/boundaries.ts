/** The dependency rules that keep feature modules independent of Tauri and of each other. */

export type BoundaryRule = "tauri-outside-gateway" | "cross-feature-deep-import";

export interface SourceFile {
  /** Path relative to `apps/desktop`, using forward slashes. */
  readonly path: string;
  readonly source: string;
}

export interface BoundaryViolation {
  readonly path: string;
  readonly specifier: string;
  readonly rule: BoundaryRule;
}

const GATEWAY_PREFIX = "src/gateway/";
const FEATURE_PREFIX = "src/features/";
const TAURI_PREFIX = "@tauri-apps/";

const IMPORT_EXPRESSIONS = [
  /(?:^|[\s;}])(?:import|export)\s[^'"]*?from\s*["']([^"']+)["']/gmu,
  /(?:^|[\s;}])import\s*["']([^"']+)["']/gmu,
  /\bimport\s*\(\s*["']([^"']+)["']\s*\)/gmu,
];

/** Collect every module specifier a source file depends on, in source order. */
export function importedSpecifiers(source: string): string[] {
  const specifiers = new Set<string>();
  for (const expression of IMPORT_EXPRESSIONS) {
    for (const match of source.matchAll(expression)) {
      if (match[1]) specifiers.add(match[1]);
    }
  }
  return [...specifiers];
}

/** Return the feature a path belongs to, or undefined when it is not feature code. */
function featureOf(path: string): string | undefined {
  if (!path.startsWith(FEATURE_PREFIX)) return undefined;
  return path.slice(FEATURE_PREFIX.length).split("/")[0];
}

/** Resolve a relative specifier against the importing file, keeping POSIX separators. */
function resolveSpecifier(fromPath: string, specifier: string): string | undefined {
  if (!specifier.startsWith(".")) return undefined;
  const segments = fromPath.split("/").slice(0, -1);
  for (const segment of specifier.split("/")) {
    if (segment === "." || segment === "") continue;
    if (segment === "..") segments.pop();
    else segments.push(segment);
  }
  return segments.join("/");
}

/** Whether a resolved path names a feature's public entry point rather than its internals. */
function isFeatureEntryPoint(resolved: string, feature: string): boolean {
  const root = `${FEATURE_PREFIX}${feature}`;
  return resolved === root || resolved === `${root}/index` || resolved === `${root}/index.ts`;
}

/** Find every import that breaks a desktop module boundary. */
export function findBoundaryViolations(files: Iterable<SourceFile>): BoundaryViolation[] {
  const violations: BoundaryViolation[] = [];
  for (const { path, source } of files) {
    const owningFeature = featureOf(path);
    for (const specifier of importedSpecifiers(source)) {
      if (specifier.startsWith(TAURI_PREFIX) && !path.startsWith(GATEWAY_PREFIX)) {
        violations.push({ path, specifier, rule: "tauri-outside-gateway" });
        continue;
      }
      const resolved = resolveSpecifier(path, specifier);
      if (resolved === undefined) continue;
      const targetFeature = featureOf(resolved);
      if (targetFeature === undefined || targetFeature === owningFeature) continue;
      if (isFeatureEntryPoint(resolved, targetFeature)) continue;
      violations.push({ path, specifier, rule: "cross-feature-deep-import" });
    }
  }
  return violations;
}
