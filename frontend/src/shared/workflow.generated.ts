/* Generated from the public v3 JSON Schema. Do not edit by hand. */

export interface WorkflowDocument {
  /**
   * Import-only Home organization; does not schedule execution.
   */
  library?: {
    folder?: string;
    /**
     * Additional workflow YAML paths relative to the execution workspace.
     */
    imports?: string[];
  };
  version: 3;
  name: string;
  concurrency?: number;
  inputs?: {
    [k: string]: Parameter;
  };
  globals?: {
    [k: string]: Global;
  };
  functions?: {
    [k: string]: Function;
  };
  graphs: {
    [k: string]: Graph;
  };
  layout?: {
    [k: string]: Layout;
  };
  environment?: {
    [k: string]: string;
  };
  secrets?: string[];
  source_paths?: string[];
  /**
   * Execution root relative to the workflow YAML directory.
   */
  workspace?: string;
  report_paths?: string[];
  input_detection?: {
    /**
     * @minItems 1
     */
    argv: [
      (
        | string
        | {
            $ref: "runtime:python";
          }
      ),
      ...(
        | string
        | {
            $ref: "runtime:python";
          }
      )[]
    ];
    timeout?: number;
  };
  skip_cards?: {
    graph: string;
    card: string;
  }[];
}
export interface Parameter {
  type: "void" | "null" | "boolean" | "number" | "string" | "array" | "object" | "json";
  default?: unknown;
  description?: string;
}
export interface Global {
  type: "null" | "boolean" | "number" | "string" | "array" | "object" | "json";
  initial: unknown;
}
export interface Function {
  name?: string;
  graph: string;
  inputs?: {
    [k: string]: Parameter;
  };
  returns: "void" | "null" | "boolean" | "number" | "string" | "array" | "object" | "json";
}
export interface Graph {
  cards: Card[];
  edges: Edge[];
}
export interface Card {
  id: string;
  kind:
    | "start"
    | "finish"
    | "return"
    | "if"
    | "loop"
    | "variable"
    | "calculate"
    | "break"
    | "continue"
    | "parallel"
    | "join"
    | "try"
    | "python"
    | "bash"
    | "script"
    | "program"
    | "check_path"
    | "read_file"
    | "write_file"
    | "http"
    | "wait"
    | "poll"
    | "manual"
    | "call"
    | "workspace";
  name: string;
  config?: {
    [k: string]: unknown;
  };
  inputs?: {
    [k: string]: unknown;
  };
  owner?: Owner;
  settings?: {
    timeout?: number;
    resources?: string[];
    exclusive?: boolean;
    interactive?: boolean;
    retry?: {
      attempts: number;
      delay?: number;
      backoff?: number;
      /**
       * @minItems 1
       */
      errors_contain?: [string, ...string[]];
    };
    cwd?: string;
    environment?: {
      [k: string]: string;
    };
    expected_seconds?: number;
  };
}
export interface Owner {
  card: string;
  region: string;
}
export interface Edge {
  id: string;
  source: string;
  target: string;
  source_port?: string;
  target_port?: string;
  kind: "flow" | "value";
  path?: string;
}
export interface Layout {
  positions?: {
    [k: string]: Point;
  };
  areas?: Area[];
}
export interface Point {
  x: number;
  y: number;
}
export interface Area {
  id: string;
  kind: "area" | "collapsible" | "annotation";
  name: string;
  position: Point;
  width?: number;
  height?: number;
  collapsed?: boolean;
  members?: string[];
}
