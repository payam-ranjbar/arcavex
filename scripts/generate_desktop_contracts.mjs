/** Generate strict TypeScript desktop contracts from canonical Pydantic JSON schemas. */

import { mkdir, mkdtemp, readFile, readdir, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const REPOSITORY_ROOT = dirname(dirname(fileURLToPath(import.meta.url)));
const SCHEMA_DIRECTORY = join(REPOSITORY_ROOT, "schemas", "desktop");
const DEFAULT_OUTPUT_DIRECTORY = join(
  REPOSITORY_ROOT,
  "apps",
  "desktop",
  "src",
  "contracts",
);
const FIXTURE_FILENAME = "desktop-contract-fixtures.json";
const GENERATED_FILENAMES = ["generated.ts", "index.ts", "generated.test.ts"];

function readArguments(argumentsList) {
  const argumentsSet = new Set(argumentsList);
  const outputIndex = argumentsList.indexOf("--output");
  if (outputIndex !== -1 && !argumentsList[outputIndex + 1]) {
    throw new Error("--output requires a directory");
  }
  return {
    check: argumentsSet.has("--check"),
    outputDirectory:
      outputIndex === -1 ? DEFAULT_OUTPUT_DIRECTORY : argumentsList[outputIndex + 1],
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
    const properties = Object.entries(schema.properties ?? {}).map(([name, property]) => {
      const optional = required.has(name) ? "" : "?";
      return `readonly ${propertyName(name)}${optional}: ${schemaType(property)};`;
    });
    if (schema.additionalProperties && typeof schema.additionalProperties === "object") {
      properties.push("readonly [key: string]: unknown;");
    }
    return properties.length ? `{ ${properties.join(" ")} }` : "Readonly<Record<string, never>>";
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
  const rootTypes = schemas
    .map((schema) => [schema.title, schema] )
    .sort(([left], [right]) => left.localeCompare(right))
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
    if (schema.prefixItems && !schema.prefixItems.every((item, index) => {
      const tupleValue = value[index];
      return tupleValue !== undefined && matchesSchema(tupleValue, item, root);
    })) return false;
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
    } else {
      const additionalProperties = schema.additionalProperties;
      if (!additionalProperties || typeof additionalProperties !== "object") return true;
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
  const guardFunctions = contracts
    .map(({ name }) => `export function is${pascalCase(name)}(value: unknown): value is ${name} {
  return isVersionedDesktopReport(value) && matchesSchema(value, desktopContractSchemas[${JSON.stringify(name)}], desktopContractSchemas[${JSON.stringify(name)}]);
}`)
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

function renderTests() {
  return `// Generated by scripts/generate_desktop_contracts.mjs. Do not edit.

import assert from "node:assert/strict";
import test from "node:test";

import {
  desktopContractFixtures,
  desktopContractGuards,
  desktopContractNames,
} from "./generated.ts";

test("Pydantic-serialized fixtures satisfy every generated desktop guard", () => {
  for (const name of desktopContractNames) {
    assert.equal(desktopContractGuards[name](desktopContractFixtures[name]), true, name);
  }
});

test("generated desktop guards reject malformed and version-wrong reports", () => {
  for (const name of desktopContractNames) {
    const fixture = desktopContractFixtures[name];
    const malformed = { ...fixture };
    delete malformed.ok;

    assert.equal(desktopContractGuards[name](malformed), false, \`${"${name}"} malformed\`);
    assert.equal(
      desktopContractGuards[name]({ ...fixture, response_version: 2 }),
      false,
      \`${"${name}"} version\`,
    );
  }
});
`;
}

async function loadContracts() {
  const filenames = (await readdir(SCHEMA_DIRECTORY))
    .filter((filename) => filename.endsWith(".schema.json"))
    .sort((left, right) => left.localeCompare(right));
  const schemas = await Promise.all(
    filenames.map(async (filename) => ({
      ...(JSON.parse(await readFile(join(SCHEMA_DIRECTORY, filename), "utf8"))),
      __filename: filename,
    })),
  );
  const fixtures = JSON.parse(await readFile(join(SCHEMA_DIRECTORY, FIXTURE_FILENAME), "utf8"));
  return { schemas, fixtures };
}

async function renderedFiles() {
  const { schemas, fixtures } = await loadContracts();
  return new Map([
    ["generated.ts", renderGenerated(schemas, fixtures)],
    ["index.ts", renderIndex()],
    ["generated.test.ts", renderTests()],
  ]);
}

async function writeGeneratedFiles(directory, files) {
  await mkdir(directory, { recursive: true });
  await Promise.all([...files].map(([filename, content]) => writeFile(join(directory, filename), `${content.trimEnd()}\n`, "utf8")));
}

async function checkGeneratedFiles() {
  const temporaryDirectory = await mkdtemp(join(tmpdir(), "arcavex-desktop-contracts-"));
  try {
    const files = await renderedFiles();
    await writeGeneratedFiles(temporaryDirectory, files);
    const actualFilenames = (await readdir(DEFAULT_OUTPUT_DIRECTORY)).sort((left, right) => left.localeCompare(right));
    const expectedFilenames = [...GENERATED_FILENAMES].sort((left, right) => left.localeCompare(right));
    if (JSON.stringify(actualFilenames) !== JSON.stringify(expectedFilenames)) {
      throw new Error(`Generated contract files differ: expected ${GENERATED_FILENAMES.join(", ")}, found ${actualFilenames.join(", ")}`);
    }
    for (const filename of GENERATED_FILENAMES) {
      const [expected, actual] = await Promise.all([
        readFile(join(temporaryDirectory, filename)),
        readFile(join(DEFAULT_OUTPUT_DIRECTORY, filename)),
      ]);
      if (!expected.equals(actual)) throw new Error(`Generated contract drift: ${filename}`);
    }
  } finally {
    await rm(temporaryDirectory, { force: true, recursive: true });
  }
}

async function main() {
  const { check, outputDirectory } = readArguments(process.argv.slice(2));
  if (check) {
    await checkGeneratedFiles();
    return;
  }
  await writeGeneratedFiles(outputDirectory, await renderedFiles());
}

await main();
