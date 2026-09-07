/** Generate strict TypeScript desktop contracts from canonical Pydantic JSON schemas. */

import { mkdir, mkdtemp, readFile, readdir, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const REPOSITORY_ROOT = dirname(dirname(fileURLToPath(import.meta.url)));
const DEFAULT_SCHEMA_DIRECTORY = join(REPOSITORY_ROOT, "schemas", "desktop");
const DEFAULT_OUTPUT_DIRECTORY = join(
  REPOSITORY_ROOT,
  "apps",
  "desktop",
  "src",
  "contracts",
);
const FIXTURE_FILENAME = "desktop-contract-fixtures.json";
const GENERATED_FILENAMES = ["generated.ts", "index.ts", "generated.test.ts"];
const UNEXPECTED_KEY = "__arcavex_unexpected__";

function readArguments(argumentsList) {
  const argumentsSet = new Set(argumentsList);
  const directoryOption = (flag, fallback) => {
    const index = argumentsList.indexOf(flag);
    if (index === -1) return fallback;
    if (!argumentsList[index + 1]) throw new Error(`${flag} requires a directory`);
    return argumentsList[index + 1];
  };
  return {
    check: argumentsSet.has("--check"),
    outputDirectory: directoryOption("--output", DEFAULT_OUTPUT_DIRECTORY),
    schemaDirectory: directoryOption("--schema-dir", DEFAULT_SCHEMA_DIRECTORY),
  };
}

function pascalCase(value) {
  return value
    .replace(/[^A-Za-z0-9]+/g, " ")
    .split(" ")
    .filter(Boolean)
    .map((part) => `${part[0].toUpperCase()}${part.slice(1)}`)
    .join("");
}

function propertyName(name) {
  return /^[A-Za-z_$][A-Za-z0-9_$]*$/u.test(name) ? name : JSON.stringify(name);
}

/** Return the value type of an open map, or undefined when the object is closed. */
function additionalValueType(schema) {
  const additional = schema.additionalProperties;
  if (additional === false) return undefined;
  if (additional === undefined) return schema.properties ? undefined : "unknown";
  if (additional === true) return "unknown";
  return schemaType(additional);
}

function schemaType(schema) {
  if (schema === true || schema === false || !schema || typeof schema !== "object") {
    return "unknown";
  }
  if (typeof schema.$ref === "string") {
    return schema.$ref.split("/").at(-1) ?? "unknown";
  }
  if (Object.hasOwn(schema, "const")) {
    return JSON.stringify(schema.const);
  }
  if (Array.isArray(schema.enum)) {
    return schema.enum.map((value) => JSON.stringify(value)).join(" | ");
  }
  for (const unionName of ["anyOf", "oneOf"]) {
    if (Array.isArray(schema[unionName])) {
      return schema[unionName].map(schemaType).join(" | ");
    }
  }
  if (Array.isArray(schema.allOf)) {
    return schema.allOf.map(schemaType).join(" & ");
  }
  if (Array.isArray(schema.prefixItems)) {
    return `readonly [${schema.prefixItems.map(schemaType).join(", ")}]`;
  }
  const type = Array.isArray(schema.type) ? schema.type : [schema.type];
  if (type.includes("null") && type.length > 1) {
    return type.filter((item) => item !== "null").map((item) => schemaType({ ...schema, type: item })).join(" | ") + " | null";
  }
  if (type.includes("array")) {
    return `ReadonlyArray<${schemaType(schema.items ?? {})}>`;
  }
  if (type.includes("object") || schema.properties) {
    const required = new Set(schema.required ?? []);
    const declared = Object.entries(schema.properties ?? {});
    const valueType = additionalValueType(schema);
    if (!declared.length) {
      return `Readonly<Record<string, ${valueType ?? "never"}>>`;
    }
    const properties = declared.map(([name, property]) => {
      const optional = required.has(name) ? "" : "?";
      return `readonly ${propertyName(name)}${optional}: ${schemaType(property)};`;
    });
    if (valueType !== undefined) {
      // An index signature must accept every declared property type, so widen it to their union.
      const declaredTypes = declared.map(([, property]) => schemaType(property));
      const indexType = valueType === "unknown"
        ? "unknown"
        : [...new Set([valueType, ...declaredTypes])].join(" | ");
      properties.push(`readonly [key: string]: ${indexType};`);
    }
    return `{ ${properties.join(" ")} }`;
  }
  if (type.includes("string")) return "string";
  if (type.includes("number") || type.includes("integer")) return "number";
  if (type.includes("boolean")) return "boolean";
  if (type.includes("null")) return "null";
  return "unknown";
}

function collectDefinitions(schemas) {
  const definitions = new Map();
  for (const schema of schemas) {
    for (const [name, definition] of Object.entries(schema.$defs ?? {})) {
      const serialized = JSON.stringify(definition);
      const existing = definitions.get(name);
      if (existing && existing.serialized !== serialized) {
        throw new Error(`Conflicting desktop schema definition: ${name}`);
      }
      definitions.set(name, { definition, serialized });
    }
  }
  return definitions;
}

function renderTypes(schemas) {
  const definitions = collectDefinitions(schemas);
  const definitionTypes = [...definitions.entries()]
    .sort(([left], [right]) => left.localeCompare(right))
    .map(([name, { definition }]) => `export type ${name} = ${schemaType(definition)};`);
  // A contract can also appear as a definition inside another one: an editor transaction is a
  // schema in its own right and the shape a transaction report returns as its inverse. Emitting
  // both would declare the same TypeScript type twice, so the shared definition wins — and a real
  // divergence between the two spellings fails loudly instead of silently picking one.
  const rootTypes = schemas
    .map((schema) => [schema.title, schema])
    .sort(([left], [right]) => left.localeCompare(right))
    .filter(([name, schema]) => {
      const shared = definitions.get(name);
      if (!shared) return true;
      const inlined = { ...schema };
      delete inlined.$defs;
      if (schemaType(inlined) !== schemaType(shared.definition)) {
        throw new Error(`Desktop schema ${name} differs between its root and definition forms`);
      }
      return false;
    })
    .map(([name, schema]) => `export type ${name} = ${schemaType(schema)};`);
  return [...definitionTypes, ...rootTypes].join("\n\n");
}

function renderRuntime() {
  return `
type JsonSchema = boolean | {
  readonly $defs?: Readonly<Record<string, JsonSchema>>;
  readonly $ref?: string;
  readonly allOf?: ReadonlyArray<JsonSchema>;
  readonly anyOf?: ReadonlyArray<JsonSchema>;
  readonly oneOf?: ReadonlyArray<JsonSchema>;
  readonly const?: unknown;
  readonly enum?: ReadonlyArray<unknown>;
  readonly type?: string | ReadonlyArray<string>;
  readonly required?: ReadonlyArray<string>;
  readonly properties?: Readonly<Record<string, JsonSchema>>;
  readonly additionalProperties?: JsonSchema;
  readonly items?: JsonSchema;
  readonly prefixItems?: ReadonlyArray<JsonSchema>;
  readonly pattern?: string;
  readonly format?: string;
  readonly minLength?: number;
  readonly maxLength?: number;
  readonly minimum?: number;
  readonly maximum?: number;
  readonly exclusiveMinimum?: number;
  readonly exclusiveMaximum?: number;
  readonly minItems?: number;
  readonly maxItems?: number;
};

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

const compiledPatterns = new Map<string, RegExp>();

function matchesPattern(value: string, pattern: string): boolean {
  let expression = compiledPatterns.get(pattern);
  if (expression === undefined) {
    expression = new RegExp(pattern);
    compiledPatterns.set(pattern, expression);
  }
  return expression.test(value);
}

const UUID4 = /^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-4[0-9a-fA-F]{3}-[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}$/;
const UUID = /^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$/;
const DATE_TIME = /^\\d{4}-\\d{2}-\\d{2}[Tt]\\d{2}:\\d{2}:\\d{2}(?:\\.\\d+)?(?:[Zz]|[+-]\\d{2}:\\d{2})$/;
const DATE = /^\\d{4}-\\d{2}-\\d{2}$/;

/** Enforce the string formats these contracts actually declare; ignore any other annotation. */
function matchesFormat(value: string, format: string): boolean {
  switch (format) {
    case "uuid4": return UUID4.test(value);
    case "uuid": return UUID.test(value);
    case "date-time": return DATE_TIME.test(value);
    case "date": return DATE.test(value);
    default: return true;
  }
}

function resolveReference(reference: string, root: JsonSchema): JsonSchema | undefined {
  const prefix = "#/$defs/";
  if (!reference.startsWith(prefix) || typeof root === "boolean") return undefined;
  return root.$defs?.[reference.slice(prefix.length)];
}

function matchesSchema(value: unknown, schema: JsonSchema, root: JsonSchema): boolean {
  if (schema === true) return true;
  if (schema === false) return false;
  if (schema.$ref) {
    const reference = resolveReference(schema.$ref, root);
    return reference !== undefined && matchesSchema(value, reference, root);
  }
  if (schema.const !== undefined && !Object.is(value, schema.const)) return false;
  if (schema.enum && !schema.enum.some((candidate) => Object.is(value, candidate))) return false;
  if (schema.allOf && !schema.allOf.every((item) => matchesSchema(value, item, root))) return false;
  if (schema.anyOf && !schema.anyOf.some((item) => matchesSchema(value, item, root))) return false;
  if (schema.oneOf && schema.oneOf.filter((item) => matchesSchema(value, item, root)).length !== 1) return false;

  const types = schema.type === undefined ? [] : Array.isArray(schema.type) ? schema.type : [schema.type];
  if (types.length && !types.some((type) => matchesType(value, type))) return false;

  if (typeof value === "string") {
    if (schema.minLength !== undefined && value.length < schema.minLength) return false;
    if (schema.maxLength !== undefined && value.length > schema.maxLength) return false;
    if (schema.pattern !== undefined && !matchesPattern(value, schema.pattern)) return false;
    if (schema.format !== undefined && !matchesFormat(value, schema.format)) return false;
  }
  if (typeof value === "number") {
    if (!Number.isFinite(value)) return false;
    if (schema.minimum !== undefined && value < schema.minimum) return false;
    if (schema.maximum !== undefined && value > schema.maximum) return false;
    if (schema.exclusiveMinimum !== undefined && value <= schema.exclusiveMinimum) return false;
    if (schema.exclusiveMaximum !== undefined && value >= schema.exclusiveMaximum) return false;
  }
  if (Array.isArray(value)) {
    if (schema.minItems !== undefined && value.length < schema.minItems) return false;
    if (schema.maxItems !== undefined && value.length > schema.maxItems) return false;
    if (schema.prefixItems) {
      if (value.length < schema.prefixItems.length) return false;
      if (!schema.prefixItems.every((item, index) => matchesSchema(value[index], item, root))) return false;
    }
    const itemSchema = schema.items;
    if (itemSchema && !value.every((item) => matchesSchema(item, itemSchema, root))) return false;
  }
  if (isRecord(value)) {
    if (schema.required?.some((key) => !Object.hasOwn(value, key))) return false;
    for (const [key, propertySchema] of Object.entries(schema.properties ?? {})) {
      if (Object.hasOwn(value, key) && !matchesSchema(value[key], propertySchema, root)) return false;
    }
    if (schema.additionalProperties === false) {
      const properties = schema.properties ?? {};
      if (Object.keys(value).some((key) => !Object.hasOwn(properties, key))) return false;
    } else if (schema.additionalProperties && typeof schema.additionalProperties === "object") {
      const additionalProperties = schema.additionalProperties;
      const properties = schema.properties ?? {};
      if (Object.entries(value).some(([key, item]) => !Object.hasOwn(properties, key) && !matchesSchema(item, additionalProperties, root))) return false;
    }
  }
  return true;
}

function matchesType(value: unknown, type: string): boolean {
  switch (type) {
    case "array": return Array.isArray(value);
    case "object": return isRecord(value);
    case "string": return typeof value === "string";
    case "number": return typeof value === "number" && Number.isFinite(value);
    case "integer": return typeof value === "number" && Number.isInteger(value);
    case "boolean": return typeof value === "boolean";
    case "null": return value === null;
    default: return true;
  }
}
`.trim();
}

// --------------------------------------------------------------- malformed fixture mutations

function dereference(schema, root) {
  let current = schema;
  const visited = new Set();
  while (current && typeof current === "object" && typeof current.$ref === "string") {
    if (visited.has(current.$ref)) return true;
    visited.add(current.$ref);
    current = root.$defs?.[current.$ref.slice("#/$defs/".length)];
  }
  return current ?? true;
}

function declaredTypes(schema) {
  if (schema === true || schema === false || !schema || schema.type === undefined) return undefined;
  return Array.isArray(schema.type) ? schema.type : [schema.type];
}

/** Whether a value could plausibly satisfy a branch, used to pick a single union member. */
function branchAcceptsValue(schema, value) {
  const types = declaredTypes(schema);
  if (types === undefined) return true;
  return types.some((type) => {
    switch (type) {
      case "array": return Array.isArray(value);
      case "object": return typeof value === "object" && value !== null && !Array.isArray(value);
      case "string": return typeof value === "string";
      case "number": case "integer": return typeof value === "number";
      case "boolean": return typeof value === "boolean";
      case "null": return value === null;
      default: return true;
    }
  });
}

function scalarMutation(schema, value) {
  if (Object.hasOwn(schema, "const")) return `${UNEXPECTED_KEY}-const`;
  if (Array.isArray(schema.enum)) return `${UNEXPECTED_KEY}-enum`;
  const types = declaredTypes(schema) ?? [];
  if (types.includes("string") && typeof value === "string") {
    if (schema.format !== undefined) return `${UNEXPECTED_KEY}-format`;
    if (schema.pattern !== undefined) return `${value}!`;
    return undefined;
  }
  if ((types.includes("number") || types.includes("integer")) && typeof value === "number") {
    return `${UNEXPECTED_KEY}-number`;
  }
  if (types.includes("boolean") && typeof value === "boolean") return `${UNEXPECTED_KEY}-boolean`;
  return undefined;
}

/** Walk a fixture beside its schema and collect edits every guard must reject. */
function collectMutations(schema, value, root, path, mutations) {
  const resolved = dereference(schema, root);
  if (resolved === true || resolved === false || !resolved) return;

  for (const unionName of ["anyOf", "oneOf"]) {
    const branches = resolved[unionName];
    if (!Array.isArray(branches)) continue;
    // Only descend when exactly one branch could accept the value; otherwise a mutation
    // rejected by one branch might still be accepted by a sibling branch.
    const candidates = branches
      .map((branch) => dereference(branch, root))
      .filter((branch) => branchAcceptsValue(branch, value));
    if (candidates.length === 1) {
      collectMutations(candidates[0], value, root, path, mutations);
    }
    return;
  }
  if (Array.isArray(resolved.allOf)) {
    for (const branch of resolved.allOf) collectMutations(branch, value, root, path, mutations);
    return;
  }

  const replacement = scalarMutation(resolved, value);
  if (replacement !== undefined) {
    mutations.push({ path, operation: "set", value: replacement });
  }

  if (Array.isArray(value)) {
    if (Array.isArray(resolved.prefixItems)) {
      mutations.push({ path, operation: "set", value: value.slice(0, -1) });
      resolved.prefixItems.forEach((item, index) => {
        if (index < value.length) {
          collectMutations(item, value[index], root, [...path, index], mutations);
        }
      });
    } else if (resolved.items) {
      value.forEach((item, index) => {
        collectMutations(resolved.items, item, root, [...path, index], mutations);
      });
    }
    return;
  }

  if (typeof value === "object" && value !== null) {
    if (resolved.additionalProperties === false) {
      mutations.push({ path, operation: "addKey" });
    }
    const required = new Set(resolved.required ?? []);
    for (const key of Object.keys(value)) {
      if (required.has(key)) {
        mutations.push({ path: [...path, key], operation: "delete" });
      }
      const propertySchema = resolved.properties?.[key]
        ?? (typeof resolved.additionalProperties === "object" ? resolved.additionalProperties : undefined);
      if (propertySchema) {
        collectMutations(propertySchema, value[key], root, [...path, key], mutations);
      }
    }
  }
}

function mutationsFor(schema, fixture) {
  const mutations = [];
  collectMutations(schema, fixture, schema, [], mutations);
  return mutations;
}

// ------------------------------------------------------------------------------- rendering

function renderGenerated(schemas, fixturesByFilename) {
  const contracts = schemas
    .map((schema) => ({ name: schema.title, schema, fixture: fixturesByFilename[schema.__filename] }))
    .sort((left, right) => left.name.localeCompare(right.name));
  if (contracts.some((contract) => contract.fixture === undefined)) {
    throw new Error("Every desktop schema must have a Pydantic-serialized fixture");
  }
  const names = contracts.map(({ name }) => JSON.stringify(name)).join(" | ");
  const schemasLiteral = JSON.stringify(
    Object.fromEntries(contracts.map(({ name, schema }) => [name, schema])),
    null,
    2,
  );
  const fixturesLiteral = JSON.stringify(
    Object.fromEntries(contracts.map(({ name, fixture }) => [name, fixture])),
    null,
    2,
  );
  const guards = contracts
    .map(({ name }) => `  ${JSON.stringify(name)}: is${pascalCase(name)},`)
    .join("\n");
  // Most contracts are reports the engine emits, and each carries `response_version`. A request
  // the desktop composes — an editor transaction, or the inverse it re-submits to undo — has no
  // response to version, so its guard checks the schema alone instead of demanding a field the
  // contract does not define.
  const guardFunctions = contracts
    .map(({ name, schema }) => {
      const versioned = Boolean(schema?.properties?.response_version);
      const precondition = versioned ? "isVersionedDesktopReport(value)" : "isRecord(value)";
      return `export function is${pascalCase(name)}(value: unknown): value is ${name} {
  return ${precondition} && matchesSchema(value, desktopContractSchemas[${JSON.stringify(name)}], desktopContractSchemas[${JSON.stringify(name)}]);
}`;
    })
    .join("\n\n");

  return `// Generated by scripts/generate_desktop_contracts.mjs. Do not edit.

${renderTypes(schemas)}

export type DesktopContractName = ${names};
export type DesktopContractGuard = (value: unknown) => boolean;

const desktopContractSchemas: Readonly<Record<DesktopContractName, JsonSchema>> = ${schemasLiteral} as unknown as Readonly<Record<DesktopContractName, JsonSchema>>;

export const desktopContractNames = [${contracts.map(({ name }) => JSON.stringify(name)).join(", ")}] as const satisfies ReadonlyArray<DesktopContractName>;

export const desktopContractFixtures: Readonly<Record<DesktopContractName, Readonly<Record<string, unknown>>>> = ${fixturesLiteral} as Readonly<Record<DesktopContractName, Readonly<Record<string, unknown>>>>;

${renderRuntime()}

function isVersionedDesktopReport(value: unknown): value is Record<string, unknown> {
  return isRecord(value) && value.response_version === 1;
}

${guardFunctions}

export const desktopContractGuards: Readonly<Record<DesktopContractName, DesktopContractGuard>> = {
${guards}
};
`;
}

function renderIndex() {
  return "// Generated by scripts/generate_desktop_contracts.mjs. Do not edit.\n\nexport * from \"./generated.ts\";\n";
}

function renderTests(schemas, fixturesByFilename) {
  const contracts = schemas
    .map((schema) => ({ name: schema.title, schema, fixture: fixturesByFilename[schema.__filename] }))
    .sort((left, right) => left.name.localeCompare(right.name));
  const mutationsLiteral = JSON.stringify(
    Object.fromEntries(
      contracts.map(({ name, schema, fixture }) => [name, mutationsFor(schema, fixture)]),
    ),
    null,
    2,
  );

  return `// Generated by scripts/generate_desktop_contracts.mjs. Do not edit.

import assert from "node:assert/strict";
import test from "node:test";

import {
  desktopContractFixtures,
  desktopContractGuards,
  desktopContractNames,
  type DesktopContractName,
} from "./generated.ts";

type Mutation = {
  readonly path: ReadonlyArray<string | number>;
  readonly operation: "set" | "delete" | "addKey";
  readonly value?: unknown;
};

const desktopContractMutations: Readonly<Record<DesktopContractName, ReadonlyArray<Mutation>>> = ${mutationsLiteral} as Readonly<Record<DesktopContractName, ReadonlyArray<Mutation>>>;

function container(root: unknown, path: ReadonlyArray<string | number>): Record<string, unknown> | unknown[] {
  let current = root;
  for (const step of path) {
    current = (current as Record<string, unknown>)[step as string];
  }
  return current as Record<string, unknown> | unknown[];
}

function applyMutation(fixture: unknown, mutation: Mutation): unknown {
  const clone = structuredClone(fixture);
  if (mutation.operation === "addKey") {
    (container(clone, mutation.path) as Record<string, unknown>)[${JSON.stringify(UNEXPECTED_KEY)}] = true;
    return clone;
  }
  const parent = container(clone, mutation.path.slice(0, -1));
  const key = mutation.path.at(-1)!;
  if (mutation.operation === "delete") {
    delete (parent as Record<string, unknown>)[key as string];
    return clone;
  }
  (parent as Record<string, unknown>)[key as string] = mutation.value;
  return clone;
}

test("Pydantic-serialized fixtures satisfy every generated desktop guard", () => {
  for (const name of desktopContractNames) {
    assert.equal(desktopContractGuards[name](desktopContractFixtures[name]), true, name);
  }
});

test("every desktop contract carries populated fixtures worth mutating", () => {
  for (const name of desktopContractNames) {
    assert.ok(
      desktopContractMutations[name].length > 0,
      \`${"${name}"} has no schema-derived mutations\`,
    );
  }
});

test("generated desktop guards reject every schema-derived mutation", () => {
  for (const name of desktopContractNames) {
    for (const mutation of desktopContractMutations[name]) {
      const malformed = applyMutation(desktopContractFixtures[name], mutation);
      assert.equal(
        desktopContractGuards[name](malformed),
        false,
        \`${"${name}"}: \${mutation.operation} at \${JSON.stringify(mutation.path)}\`,
      );
    }
  }
});

test("generated desktop guards reject version-wrong and non-object reports", () => {
  for (const name of desktopContractNames) {
    const fixture = desktopContractFixtures[name];
    assert.equal(
      desktopContractGuards[name]({ ...fixture, response_version: 2 }),
      false,
      \`${"${name}"} version\`,
    );
    assert.equal(desktopContractGuards[name](null), false, \`${"${name}"} null\`);
    assert.equal(desktopContractGuards[name]([fixture]), false, \`${"${name}"} array\`);
  }
});
`;
}

async function loadContracts(schemaDirectory) {
  const filenames = (await readdir(schemaDirectory))
    .filter((filename) => filename.endsWith(".schema.json"))
    .sort((left, right) => left.localeCompare(right));
  const schemas = await Promise.all(
    filenames.map(async (filename) => ({
      ...(JSON.parse(await readFile(join(schemaDirectory, filename), "utf8"))),
      __filename: filename,
    })),
  );
  const fixtures = JSON.parse(await readFile(join(schemaDirectory, FIXTURE_FILENAME), "utf8"));
  return { schemas, fixtures };
}

async function renderedFiles(schemaDirectory) {
  const { schemas, fixtures } = await loadContracts(schemaDirectory);
  return new Map([
    ["generated.ts", renderGenerated(schemas, fixtures)],
    ["index.ts", renderIndex()],
    ["generated.test.ts", renderTests(schemas, fixtures)],
  ]);
}

async function writeGeneratedFiles(directory, files) {
  await mkdir(directory, { recursive: true });
  await Promise.all([...files].map(([filename, content]) => writeFile(join(directory, filename), `${content.trimEnd()}\n`, "utf8")));
}

async function checkGeneratedFiles(schemaDirectory, outputDirectory) {
  const temporaryDirectory = await mkdtemp(join(tmpdir(), "arcavex-desktop-contracts-"));
  try {
    await writeGeneratedFiles(temporaryDirectory, await renderedFiles(schemaDirectory));
    const actualFilenames = (await readdir(outputDirectory)).sort((left, right) => left.localeCompare(right));
    const expectedFilenames = [...GENERATED_FILENAMES].sort((left, right) => left.localeCompare(right));
    if (JSON.stringify(actualFilenames) !== JSON.stringify(expectedFilenames)) {
      throw new Error(`Generated contract files differ: expected ${GENERATED_FILENAMES.join(", ")}, found ${actualFilenames.join(", ")}`);
    }
    for (const filename of GENERATED_FILENAMES) {
      const [expected, actual] = await Promise.all([
        readFile(join(temporaryDirectory, filename)),
        readFile(join(outputDirectory, filename)),
      ]);
      if (!expected.equals(actual)) throw new Error(`Generated contract drift: ${filename}`);
    }
  } finally {
    await rm(temporaryDirectory, { force: true, recursive: true });
  }
}

async function main() {
  const { check, outputDirectory, schemaDirectory } = readArguments(process.argv.slice(2));
  if (check) {
    await checkGeneratedFiles(schemaDirectory, outputDirectory);
    return;
  }
  await writeGeneratedFiles(outputDirectory, await renderedFiles(schemaDirectory));
}

await main();
