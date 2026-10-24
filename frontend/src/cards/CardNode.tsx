import { useSkipCard } from "../run/SkipContext";
import { WorkspaceLink } from "./WorkspaceLink";
import { useUpdateNodeInternals } from "@xyflow/react";
import { useLayoutEffect } from "react";
import { configuredCard, resultType } from "../shared/cards";
import { Handle, Position, type Node, type NodeProps } from "@xyflow/react";
import {
  Code,
  GitBranch,
  Repeat,
  FileText,
  Hand,
  Braces,
  Play,
  Square,
  Layers,
  ShieldCheck,
  Timer,
  Terminal,
  ExternalLink,
} from "lucide-react";
import type { Card, CardMeta, Workflow } from "../shared/types";
import { FieldEditor, fieldVisible } from "./Fields";
export interface CardNodeData extends Record<string, unknown> {
  card: Card;
  graphId: string;
  catalog: CardMeta[];
  meta: CardMeta;
  workflow: Workflow;
  editing: boolean;
  status: string;
  selected: boolean;
  onConfig: (id: string, key: string, value: unknown) => void;
  onOpenFunction: (id: string) => void;
  onNewFunction: (returns?: string) => void;
  onDetails: (id: string) => void;
  onInvalid?: (id: string, error: string) => void;
}
export type FlowNode = Node<CardNodeData, "card">;
const icons: Record<string, typeof Code> = {
  if: GitBranch,
  loop: Repeat,
  python: Code,
  bash: Terminal,
  program: Terminal,
  script: FileText,
  manual: Hand,
  call: Layers,
  workspace: ExternalLink,
  try: ShieldCheck,
  wait: Timer,
  poll: Timer,
  start: Play,
  finish: Square,
  return: Braces,
};
export function flowOutputs(card: Card, meta?: CardMeta): string[] {
  if (card.kind === "parallel")
    return [
      ...(Array.isArray(card.config?.branches)
        ? card.config.branches.filter(
            (value): value is string => typeof value === "string",
          )
        : ["first", "second"]),
      "done",
    ];
  return meta?.ports ?? [];
}
export function CardNode({ data }: NodeProps<FlowNode>) {
  const { meta, editing } = data,
    card = configuredCard(data.card, meta),
    Icon = icons[card.kind] ?? Braces;
  const fields = meta.fields.filter(
    (f) => !f.advanced && fieldVisible(f, card.config ?? {}),
  );
  const inputs = new Set([
    ...Object.keys(card.inputs ?? {}),
    ...Object.keys(
      data.workflow.functions?.[String(card.config?.function)]?.inputs ?? {},
    ),
  ]);
  const returnedType = resultType(card, meta, data.workflow);
  const updateNode = useUpdateNodeInternals();
  useLayoutEffect(() => {
    updateNode(card.id);
  }, [
    editing,
    JSON.stringify(card.config),
    JSON.stringify([...inputs]),
    updateNode,
    card.id,
  ]);
  const skip = useSkipCard(data.graphId, card.id);
  return (
    <div
      data-card-id={card.id}
      className={`flow-card ${skip.previewing ? "skip-preview" : ""} kind-${card.kind} state-${data.status} ${data.selected ? "chosen" : ""}`}
    >
      {data.status === "running" && (
        <span className="running-border" aria-hidden="true" />
      )}
      {card.kind !== "start" && (
        <Handle
          type="target"
          id="flow:entry"
          position={Position.Left}
          style={{ top: card.kind === "if" ? "50%" : 28 }}
          aria-label={`Entry for ${card.name}`}
        />
      )}
      {returnedType !== "void" && (
        <Handle
          type="source"
          id="value"
          position={Position.Top}
          className="value-handle"
          aria-label={`Value output for ${card.name}`}
        />
      )}
      <span className="value-label">Value · {returnedType}</span>
      <div className="card-heading">
        <Icon size={17} />
        <span>{meta.label}</span>
      </div>
      <strong className="card-name">{card.name}</strong>
      {skip.marked && (
        <small
          className="skip-badge"
          title={skip.marked.reasons
            .map((x) => x.reason + ": " + x.source)
            .join("; ")}
        >
          Marked to skip
        </small>
      )}
      {card.owner && (
        <small className="owner-label">
          {card.owner.card} · {card.owner.region}
        </small>
      )}
      {editing ? (
        <div className="primary-fields">
          {fields.map((field) => (
            <div className="field-port" key={field.key}>
              {["json", "number", "text", "textarea"].includes(
                field.widget,
              ) && (
                <Handle
                  type="target"
                  id={"value:config:" + field.key}
                  position={Position.Left}
                  className="value-handle"
                  aria-label={`${field.label} value input for ${card.name}`}
                />
              )}
              <FieldEditor
                field={field}
                graphId={data.graphId}
                catalog={data.catalog}
                card={card}
                workflow={data.workflow}
                disabled={!editing}
                onChange={(k, v) => data.onConfig(card.id, k, v)}
                onOpenFunction={data.onOpenFunction}
                onNewFunction={data.onNewFunction}
                onInvalid={(e) =>
                  data.onInvalid?.(card.id + ":" + field.key, e)
                }
              />
            </div>
          ))}
          {meta.fields.some((f) => f.widget === "code") && (
            <button
              className="nodrag code-button"
              onClick={() => data.onDetails(card.id)}
            >
              Edit code
            </button>
          )}
        </div>
      ) : (
        <p className="card-summary">
          {card.kind === "loop"
            ? card.config?.mode === "count"
              ? `Repeat ${card.config.count} times`
              : "While " + String(card.config?.function)
            : card.kind === "call" || card.kind === "if" || card.kind === "poll"
              ? String(card.config?.function ?? "Choose a function")
              : card.kind === "python"
                ? String(card.config?.code ?? "").split("\n")[0]
                : card.kind === "wait"
                  ? `${card.config?.seconds ?? 1} seconds`
                  : String(
                      card.config?.path ??
                        card.config?.url ??
                        card.config?.name ??
                        "",
                    )}
        </p>
      )}
      {!editing && card.kind === "workspace" && (
        <WorkspaceLink
          workflow={data.workflow}
          graphId={data.graphId}
          cardId={card.id}
          view="run"
        />
      )}
      <div className="card-state">
        {data.status === "pending" ? "Ready" : data.status}
      </div>
      {card.kind === "loop" && (
        <>
          <Handle
            type="target"
            id="flow:next_iteration"
            position={Position.Bottom}
            style={{ left: "78%" }}
            aria-label={`Next iteration input for ${card.name}`}
          />
          <span className="iteration-label">Next iteration</span>
        </>
      )}
      {flowOutputs(card, meta).map((port, i, all) => {
        const bottom = !["next", "done", "true"].includes(port);
        return (
          <div key={port}>
            <Handle
              type="source"
              id={"flow:" + port}
              position={bottom ? Position.Bottom : Position.Right}
              style={
                bottom
                  ? {
                      left:
                        card.kind === "loop"
                          ? "25%"
                          : `${((i + 1) * 100) / (all.length + 1)}%`,
                    }
                  : { top: card.kind === "if" ? "50%" : 28 }
              }
              aria-label={`${port} output for ${card.name}`}
            />
            {port !== "next" && (
              <span
                className={bottom ? "bottom-port-label" : "right-port-label"}
                style={
                  bottom
                    ? {
                        left:
                          card.kind === "loop"
                            ? "25%"
                            : `${((i + 1) * 100) / (all.length + 1)}%`,
                      }
                    : undefined
                }
              >
                {port}
              </span>
            )}
          </div>
        );
      })}
      <div className="card-inputs">
        {meta.fields
          .filter(
            (f) =>
              fieldVisible(f, card.config ?? {}) &&
              (!editing || f.advanced) &&
              ["json", "number", "text", "textarea"].includes(f.widget),
          )
          .map((f) => (
            <div key={f.key} className="field-port">
              <Handle
                type="target"
                id={"value:config:" + f.key}
                position={Position.Left}
                className="value-handle"
                aria-label={`${f.label} value input for ${card.name}`}
              />
              <small>{f.label}</small>
            </div>
          ))}
      </div>
      {inputs.size > 0 && (
        <div className="card-inputs">
          {[...inputs].map((name) => (
            <div key={name} className="field-port">
              <Handle
                type="target"
                id={"value:input:" + name}
                position={Position.Left}
                className="value-handle"
                aria-label={`${name} argument for ${card.name}`}
              />
              <small>Input · {name}</small>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
