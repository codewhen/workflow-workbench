import type {
  Card,
  CardMeta,
  Edge,
  Graph,
  Owner,
  Workflow,
} from "../shared/types";
export const clone = <T>(value: T): T => structuredClone(value);
export const nextId = (cards: Card[], prefix = "card"): string => {
  let n = 1;
  while (cards.some((c) => c.id === `${prefix}-${n}`)) n++;
  return `${prefix}-${n}`;
};
export function graphOf(workflow: Workflow, id: string): Graph {
  const graph = workflow.graphs[id];
  if (!graph) throw Error("Graph does not exist.");
  return graph;
}
export function descendants(graph: Graph, id: string): Set<string> {
  const ids = new Set<string>();
  let changed = true;
  while (changed) {
    changed = false;
    for (const c of graph.cards)
      if (
        c.owner &&
        (c.owner.card === id || ids.has(c.owner.card)) &&
        !ids.has(c.id)
      ) {
        ids.add(c.id);
        changed = true;
      }
  }
  return ids;
}
const sameOwner = (a?: Owner, b?: Owner) =>
  a?.card === b?.card && a?.region === b?.region;
function adopt(graph: Graph, id: string, owner: Owner): void {
  const first = graph.cards.find((c) => c.id === id)!;
  const ids = new Set([id]);
  let changed = true;
  while (changed) {
    changed = false;
    for (const edge of graph.edges.filter(
      (e) => e.kind === "flow" && e.target_port !== "next_iteration",
    ))
      if (
        ids.has(edge.source) &&
        !ids.has(edge.target) &&
        sameOwner(
          first.owner,
          graph.cards.find((c) => c.id === edge.target)?.owner,
        )
      ) {
        ids.add(edge.target);
        changed = true;
      }
  }
  if (ids.has(owner.card) || descendants(graph, id).has(owner.card))
    throw Error("This connection would create cyclic ownership.");
  if (
    graph.edges.some(
      (e) => e.kind === "flow" && ids.has(e.target) && !ids.has(e.source),
    )
  )
    throw Error(
      "The branch has outside prerequisites. Disconnect them before assigning it to a control card.",
    );
  for (const card of graph.cards)
    if (ids.has(card.id)) card.owner = clone(owner);
}
export function connect(
  workflow: Workflow,
  graphId: string,
  source: string,
  target: string,
  sourcePort = "flow:next",
  targetPort = "flow:entry",
): Workflow {
  const next = clone(workflow),
    graph = graphOf(next, graphId),
    a = graph.cards.find((c) => c.id === source),
    b = graph.cards.find((c) => c.id === target);
  if (!a || !b || a.id === b.id) throw Error("Connect two existing cards.");
  const isValue = sourcePort === "value";
  if (isValue !== targetPort.startsWith("value:"))
    throw Error(
      "Connect execution ports to execution ports, or Value to a value input.",
    );
  const sp = isValue ? "value" : sourcePort.replace("flow:", ""),
    tp = targetPort.replace(/^(flow|value):/, "");
  if (!isValue) {
    const region =
      (a.kind === "loop" && sp === "body") ||
      (a.kind === "try" && ["body", "catch", "finally"].includes(sp)) ||
      (a.kind === "parallel" && sp !== "done");
    if (tp === "next_iteration") {
      if (
        b.kind !== "loop" ||
        a.owner?.card !== b.id ||
        a.owner.region !== "body"
      )
        throw Error("Next iteration accepts only this loop’s Body completion.");
    } else if (region) {
      if (b.owner && !sameOwner(b.owner, { card: a.id, region: sp }))
        throw Error("This card already belongs to another branch.");
      adopt(graph, target, { card: a.id, region: sp });
    } else if (a.owner && !b.owner) adopt(graph, target, a.owner);
    else if (!sameOwner(a.owner, b.owner))
      throw Error("Connect through the control card’s labelled branch ports.");
    const seen = new Set<string>();
    const visit = (id: string): boolean => {
      if (id === source) return true;
      if (seen.has(id)) return false;
      seen.add(id);
      return graph.edges
        .filter(
          (e) =>
            e.kind === "flow" &&
            e.source === id &&
            e.target_port !== "next_iteration",
        )
        .some((e) => visit(e.target));
    };
    if (tp !== "next_iteration" && visit(target))
      throw Error(
        "Execution cycles require a Loop and its Next iteration input.",
      );
  }
  graph.edges = graph.edges.filter((e) =>
    isValue
      ? !(e.kind === "value" && e.target === target && e.target_port === tp)
      : !(
          e.kind === "flow" &&
          e.source === source &&
          (e.source_port || "next") === sp
        ),
  );
  const edge: Edge = {
    id: `${isValue ? "value" : "flow"}:${source}:${sp}:${target}:${tp}`,
    kind: isValue ? "value" : "flow",
    source,
    target,
    source_port: sp,
    target_port: tp,
  };
  graph.edges.push(edge);
  return next;
}
export function addCard(
  workflow: Workflow,
  graphId: string,
  meta: CardMeta,
  position?: { x: number; y: number },
): { workflow: Workflow; id: string } {
  const next = clone(workflow),
    graph = graphOf(next, graphId),
    id = nextId(graph.cards);
  graph.cards.push({
    id,
    kind: meta.kind,
    name: meta.label,
    config: clone(meta.defaults),
    inputs: {},
  });
  next.layout ??= {};
  const layout = (next.layout[graphId] ??= { positions: {}, areas: [] });
  layout.positions ??= {};
  layout.positions[id] = position ?? {
    x: (graph.cards.length % 4) * 340,
    y: Math.floor(graph.cards.length / 4) * 320,
  };
  if (meta.kind === "parallel") {
    const join = nextId(graph.cards, "join");
    graph.cards.push({
      id: join,
      kind: "join",
      name: "Join",
      config: { parallel: id },
    });
    layout.positions[join] = {
      x: layout.positions[id].x + 340,
      y: layout.positions[id].y,
    };
    graph.edges.push({
      id: `${id}:done:${join}`,
      kind: "flow",
      source: id,
      target: join,
      source_port: "done",
      target_port: "entry",
    });
  }
  return { workflow: next, id };
}
export function removeCard(
  workflow: Workflow,
  graphId: string,
  id: string,
): Workflow {
  const next = clone(workflow),
    graph = graphOf(next, graphId);
  if (graph.cards.find((c) => c.id === id)?.kind === "start")
    throw Error("The graph needs its Start marker.");
  const ids = new Set([
    id,
    ...descendants(graph, id),
    ...graph.cards
      .filter((c) => c.kind === "join" && c.config?.parallel === id)
      .map((c) => c.id),
  ]);
  next.skip_cards = next.skip_cards?.filter(
    (x) => x.graph !== graphId || !ids.has(x.card),
  );
  graph.cards = graph.cards.filter((c) => !ids.has(c.id));
  graph.edges = graph.edges.filter(
    (e) => !ids.has(e.source) && !ids.has(e.target),
  );
  return next;
}
export function duplicateCard(
  workflow: Workflow,
  graphId: string,
  id: string,
): { workflow: Workflow; id: string } {
  const next = clone(workflow),
    graph = graphOf(next, graphId),
    original = graph.cards.find((c) => c.id === id)!;
  if (original.kind === "start") throw Error("A graph has one Start marker.");
  const ids = new Set([
      id,
      ...descendants(graph, id),
      ...graph.cards
        .filter((c) => c.kind === "join" && c.config?.parallel === id)
        .map((c) => c.id),
    ]),
    mapping = new Map<string, string>();
  for (const old of ids) {
    const newId = nextId([
      ...graph.cards,
      ...[...mapping.values()].map((id) => ({ id }) as Card),
    ]);
    mapping.set(old, newId);
  }
  const replaceRefs = (value: unknown): unknown => {
    if (Array.isArray(value)) return value.map(replaceRefs);
    if (value && typeof value === "object")
      return Object.fromEntries(
        Object.entries(value).map(([k, v]) => [
          k,
          k === "$ref" && typeof v === "string" && v.startsWith("card:")
            ? "card:" + (mapping.get(v.slice(5)) ?? v.slice(5))
            : replaceRefs(v),
        ]),
      );
    return value;
  };
  const copies = graph.cards
    .filter((c) => ids.has(c.id))
    .map((c) => {
      const v = replaceRefs(clone(c)) as Card;
      v.id = mapping.get(c.id)!;
      v.name += " copy";
      if (v.owner && mapping.has(v.owner.card))
        v.owner.card = mapping.get(v.owner.card)!;
      if (v.kind === "join" && typeof v.config?.parallel === "string")
        v.config.parallel = mapping.get(v.config.parallel) ?? v.config.parallel;
      return v;
    });
  graph.cards.push(...copies);
  graph.edges.push(
    ...graph.edges
      .filter((e) => ids.has(e.source) && ids.has(e.target))
      .map((e) => ({
        ...e,
        id: e.id + ":copy:" + mapping.get(id),
        source: mapping.get(e.source)!,
        target: mapping.get(e.target)!,
      })),
  );
  next.layout ??= {};
  const layout = (next.layout[graphId] ??= { positions: {}, areas: [] });
  layout.positions ??= {};
  for (const old of ids) {
    const p = layout.positions[old] ?? { x: 0, y: 0 };
    layout.positions[mapping.get(old)!] = { x: p.x + 40, y: p.y + 180 };
  }
  return { workflow: next, id: mapping.get(id)! };
}
export function addFunction(
  workflow: Workflow,
  name: string,
  returns: string,
): { workflow: Workflow; id: string } {
  const next = clone(workflow);
  next.functions ??= {};
  let id =
    name
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "-")
      .replace(/^-|-$/g, "") || "function";
  let n = 1;
  while (next.functions[id]) id = "function-" + n++;
  const graph = "function-" + id;
  next.functions[id] = {
    name,
    graph,
    inputs: {},
    returns: returns as NonNullable<Workflow["functions"]>[string]["returns"],
  };
  const value: unknown =
    returns === "boolean"
      ? true
      : returns === "number"
        ? 0
        : returns === "string"
          ? ""
          : returns === "array"
            ? []
            : returns === "object"
              ? {}
              : null;
  next.graphs[graph] = {
    cards: [
      { id: "start", kind: "start", name: "Start" },
      {
        id: "return",
        kind: "return",
        name: "Return",
        config: { value, returns: returns === "void" ? "void" : "json" },
      },
    ],
    edges: [
      {
        id: "start-return",
        kind: "flow",
        source: "start",
        target: "return",
        source_port: "next",
        target_port: "entry",
      },
    ],
  };
  next.layout ??= {};
  next.layout[graph] = {
    positions: { start: { x: 0, y: 0 }, return: { x: 340, y: 0 } },
    areas: [],
  };
  return { workflow: next, id };
}
export function arrange(workflow: Workflow, graphId: string): Workflow {
  const next = clone(workflow),
    graph = graphOf(next, graphId),
    levels = new Map<string, number>(),
    rows = new Map<number, number>();
  const level = (id: string, seen = new Set<string>()): number => {
    if (levels.has(id)) return levels.get(id)!;
    if (seen.has(id)) return 0;
    seen.add(id);
    const incoming = graph.edges.filter(
      (e) =>
        e.kind === "flow" &&
        e.target === id &&
        e.target_port !== "next_iteration",
    );
    const n =
      Math.max(-1, ...incoming.map((e) => level(e.source, new Set(seen)))) + 1;
    levels.set(id, n);
    return n;
  };
  const positions: Record<string, { x: number; y: number }> = {};
  for (const card of graph.cards) {
    const x = level(card.id),
      row = rows.get(x) ?? 0;
    rows.set(x, row + 1);
    positions[card.id] = { x: x * 360, y: row * 380 };
  }
  next.layout ??= {};
  next.layout[graphId] = { ...next.layout[graphId], positions };
  return next;
}
export function visibleCards(workflow: Workflow, graphId: string): Card[] {
  const hidden = new Set(
    (workflow.layout?.[graphId]?.areas ?? [])
      .filter((a) => a.collapsed)
      .flatMap((a) => a.members ?? []),
  );
  return graphOf(workflow, graphId).cards.filter((c) => !hidden.has(c.id));
}

/** Stable structural order for the accessible List; value wires do not affect order. */
export function orderedCards(graph: Graph): Card[] {
  const seen = new Set<string>(),
    result: Card[] = [];
  const visit = (id: string) => {
    if (seen.has(id)) return;
    seen.add(id);
    const card = graph.cards.find((c) => c.id === id);
    if (!card) return;
    result.push(card);
    const outputs = graph.edges
      .filter(
        (e) =>
          e.kind === "flow" &&
          e.source === id &&
          e.target_port !== "next_iteration",
      )
      .sort(
        (a, b) =>
          Number(a.source_port === "done") - Number(b.source_port === "done"),
      );
    for (const edge of outputs) visit(edge.target);
  };
  const start = graph.cards.find((c) => c.kind === "start");
  if (start) visit(start.id);
  for (const card of graph.cards) visit(card.id);
  return result;
}
export function ownershipDepth(graph: Graph, card: Card): number {
  let owner = card.owner,
    depth = 0;
  const seen = new Set<string>();
  while (owner && !seen.has(owner.card)) {
    seen.add(owner.card);
    depth++;
    owner = graph.cards.find((c) => c.id === owner!.card)?.owner;
  }
  return depth;
}
