#!/usr/bin/env node
/**
 * Compiles schema/*.schema.json into standalone, dependency-free JavaScript
 * validators for the extension.
 *
 * SS15.4 asks for "generated Zod client-side". Zod is the wrong tool here for a
 * concrete reason rather than a stylistic one: json-schema-to-zod silently
 * emits `z.any()` for every `$ref` it cannot resolve, which is most of ours --
 * SemanticNode is recursive and FidelityFlag lives in common.schema.json. A
 * validator that accepts anything is worse than no validator, because it
 * reports success.
 *
 * Ajv consumes the JSON Schema directly, so drift between the source of truth
 * and the runtime check is impossible by construction, and standalone mode
 * precompiles to plain JS -- no Ajv in the extension bundle.
 */
import { mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

import Ajv from 'ajv/dist/2020.js';
import standaloneCode from 'ajv/dist/standalone/index.js';

const HERE = dirname(fileURLToPath(import.meta.url));
const SCHEMA_DIR = resolve(HERE, '..');

/** Root schemas that get an exported validator. `common` is defs-only. */
const ROOTS = {
  validateRecording: 'recording',
  validateIRDocument: 'ir',
  validateAgentTrace: 'trace',
  validateSegmentsDocument: 'segments',
};

const ALL = ['common', 'recording', 'ir', 'trace', 'segments'];

const outDir = resolve(process.argv[2] ?? join(SCHEMA_DIR, '..', 'extension/src/schemas'));

const ajv = new Ajv({
  strict: false,
  allErrors: true,
  code: { source: true, esm: true },
});

// `date-time` is the only format the schemas use. ajv-formats would cover it,
// but standalone mode emits a bare `require('ajv-formats/...')` for it, which
// throws in an ES module and would drag a runtime dependency into the
// extension bundle. An inlined RFC 3339 regex has neither problem.
ajv.addFormat(
  'date-time',
  /^\d{4}-\d{2}-\d{2}[Tt]\d{2}:\d{2}:\d{2}(\.\d+)?([Zz]|[+-]\d{2}:\d{2})$/,
);

const loaded = {};
for (const name of ALL) {
  const schema = JSON.parse(readFileSync(join(SCHEMA_DIR, `${name}.schema.json`), 'utf8'));
  loaded[name] = schema;
  ajv.addSchema(schema, schema.$id);
}

// Map exported function name -> the $id Ajv knows the schema by.
const exports_ = Object.fromEntries(
  Object.entries(ROOTS).map(([fn, name]) => [fn, loaded[name].$id]),
);

mkdirSync(outDir, { recursive: true });

const code = standaloneCode(ajv, exports_);
writeFileSync(
  join(outDir, 'validators.js'),
  `/* Generated from schema/*.schema.json by schema/tools/gen-validators.mjs. Do not edit. */\n${code}`,
  'utf8',
);

// Hand-written ambient types for the generated module: the validators are
// plain predicates carrying an `errors` array, which Ajv does not describe.
const dts = `/* Generated from schema/*.schema.json by schema/tools/gen-validators.mjs. Do not edit. */
import type { Recording } from '../types/recording.js';
import type { IRDocument } from '../types/ir.js';
import type { AgentTrace } from '../types/trace.js';
import type { SegmentsDocument } from '../types/segments.js';

export interface ValidationError {
  instancePath: string;
  schemaPath: string;
  keyword: string;
  params: Record<string, unknown>;
  message?: string;
}

export interface ValidateFunction<T> {
  (data: unknown): data is T;
  errors?: ValidationError[] | null;
}

${Object.entries(ROOTS)
  .map(([fn, name]) => {
    const type = {
      recording: 'Recording',
      ir: 'IRDocument',
      trace: 'AgentTrace',
      segments: 'SegmentsDocument',
    }[name];
    return `export declare const ${fn}: ValidateFunction<${type}>;`;
  })
  .join('\n')}
`;
writeFileSync(join(outDir, 'validators.d.ts'), dts, 'utf8');

console.log(`  validators -> ${outDir}/validators.js (${Object.keys(ROOTS).length} roots)`);
