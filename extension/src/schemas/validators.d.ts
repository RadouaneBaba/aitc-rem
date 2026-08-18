/* Generated from schema/*.schema.json by schema/tools/gen-validators.mjs. Do not edit. */
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

export declare const validateRecording: ValidateFunction<Recording>;
export declare const validateIRDocument: ValidateFunction<IRDocument>;
export declare const validateAgentTrace: ValidateFunction<AgentTrace>;
export declare const validateSegmentsDocument: ValidateFunction<SegmentsDocument>;
