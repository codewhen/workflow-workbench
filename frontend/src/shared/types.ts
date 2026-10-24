import type { WorkflowDocument } from "./workflow.generated";
export type Workflow = WorkflowDocument;
export type Card = Workflow["graphs"][string]["cards"][number];
export type Edge = Workflow["graphs"][string]["edges"][number];
export type Graph = Workflow["graphs"][string];
export type Owner = NonNullable<Card["owner"]>;
export type ValueType =
  | "void"
  | "null"
  | "boolean"
  | "number"
  | "string"
  | "array"
  | "object"
  | "json";
export const VALUE_TYPES: ValueType[] = [
  "void",
  "null",
  "boolean",
  "number",
  "string",
  "array",
  "object",
  "json",
];
export interface Field {
  key: string;
  label: string;
  widget: string;
  options?: string[];
  returns?: string;
  advanced?: boolean;
  when?: Record<string, unknown>;
  unless?: Record<string, unknown>;
}
export interface CardMeta {
  kind: Card["kind"];
  category: string;
  label: string;
  defaults: Record<string, unknown>;
  fields: Field[];
  output: string;
  ports: string[];
}
export interface Catalog {
  cards: CardMeta[];
  templates: Record<string, string>;
  schema: unknown;
}
export interface ValidationIssue {
  label?: string;
  graph: string;
  card: string;
  port: string;
  message: string;
}
export interface SavedDocument {
  inspection?: string;
  runnable?: boolean;
  validation_errors?: string[];
  issues?: ValidationIssue[];
  recovery?: { workflow: Workflow; yaml: string } | null;
  workflow: Workflow;
  yaml: string;
  revision: string;
  path: string;
}
export interface LibraryEntry {
  id: string;
  path: string;
  folder: string;
  name: string;
  supported: boolean;
  error?: string;
}
export interface Library {
  projects: string[];
  folders: string[];
  entries: LibraryEntry[];
}
export interface Execution {
  user_skip?: boolean;
  reason?: string;
  child_report?: string;
  child_status?: string;
  child_active?: string[];
  child_progress?: { done: number; total: number; stage: string };
  card: string;
  graph: string;
  name: string;
  kind: string;
  path: string;
  status: string;
  error?: string;
  seconds?: number;
  expected_seconds?: number;
  started: number;
  tail?: string;
  log?: string;
  progress?: { done: number; total: number; stage: string; measured: boolean };
  outcome?: { value: { type: ValueType; value?: unknown }; signal?: string };
  attempts: { status: string; number: number; error?: string }[];
}
export interface ManualRequest {
  card: string;
  name: string;
  instructions: string;
  mode: string;
}
export interface RunState {
  user_skips?: { graph: string; card: string }[];
  input_context?: {
    source_run: string;
    results: Record<string, { type: string; value?: unknown }>;
  };
  selection?: { graph: string; card: string; name: string; mode?: string };
  attachments?: { path: string; url: string }[];
  run_id?: string;
  report_base?: string;
  can_run_from_here?: boolean;
  status: string;
  busy: boolean;
  paused: boolean;
  error?: string;
  executions: Record<string, Execution>;
  manual: Record<string, ManualRequest>;
  events: { kind: string; execution: string; [key: string]: unknown }[];
  globals?: Record<string, unknown>;
}
export const EMPTY_STATE: RunState = {
  status: "pending",
  busy: false,
  paused: false,
  executions: {},
  manual: {},
  events: [],
};
