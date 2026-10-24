import { describe, it, expect } from "vitest";
import {
  addCard,
  addFunction,
  connect,
  removeCard,
  duplicateCard,
  visibleCards,
  arrange,
} from "./model";
import type { Workflow, CardMeta } from "../shared/types";
const blank = (): Workflow => ({
  version: 3,
  name: "Test",
  graphs: {
    main: {
      cards: [
        { id: "start", kind: "start", name: "Start" },
        { id: "finish", kind: "finish", name: "Finish" },
      ],
      edges: [
        {
          id: "initial",
          kind: "flow",
          source: "start",
          target: "finish",
          source_port: "next",
          target_port: "entry",
        },
      ],
    },
  },
});
const meta = (
  kind: CardMeta["kind"],
  defaults: Record<string, unknown> = {},
): CardMeta => ({
  kind,
  defaults,
  label: kind,
  category: "test",
  fields: [],
  output: "json",
  ports: ["next"],
});
describe("immutable flowchart commands", () => {
  it("adds, wires and removes cards without changing the original", () => {
    const original = blank();
    let result = addCard(original, "main", meta("wait", { seconds: 0 }));
    let next = connect(result.workflow, "main", "start", result.id);
    next = connect(next, "main", result.id, "finish");
    expect(next.graphs.main.edges).toHaveLength(2);
    expect(original.graphs.main.cards).toHaveLength(2);
    expect(removeCard(next, "main", result.id).graphs.main.cards).toHaveLength(
      2,
    );
  });
  it("rejects arbitrary cycles and mixed port kinds", () => {
    const result = addCard(blank(), "main", meta("wait"));
    const next = connect(result.workflow, "main", "start", result.id);
    expect(() => connect(next, "main", result.id, "start")).toThrow();
    expect(() =>
      connect(next, "main", "start", result.id, "value", "flow:entry"),
    ).toThrow();
  });
  it("adopts main-canvas body cards and validates loop closure", () => {
    let loop = addCard(
      blank(),
      "main",
      meta("loop", { mode: "count", count: 3 }),
    );
    let body = addCard(loop.workflow, "main", meta("wait"));
    let next = connect(body.workflow, "main", loop.id, body.id, "flow:body");
    expect(next.graphs.main.cards.find((c) => c.id === body.id)?.owner).toEqual(
      { card: loop.id, region: "body" },
    );
    expect(() =>
      connect(
        next,
        "main",
        "start",
        loop.id,
        "flow:next",
        "flow:next_iteration",
      ),
    ).toThrow();
    next = connect(
      next,
      "main",
      body.id,
      loop.id,
      "flow:next",
      "flow:next_iteration",
    );
    expect(next.graphs.main.edges.at(-1)?.target_port).toBe("next_iteration");
  });
  it("creates Boolean functions with dedicated graphs", () => {
    const result = addFunction(blank(), "Is ready", "boolean");
    expect(result.workflow.functions?.[result.id].returns).toBe("boolean");
    expect(
      result.workflow.graphs["function-" + result.id].cards.at(-1)?.config
        ?.value,
    ).toBe(true);
  });
  it("keeps Void function returns distinct from null", () => {
    const result = addFunction(blank(), "Cleanup", "void");
    expect(
      result.workflow.graphs["function-" + result.id].cards.at(-1)?.config
        ?.returns,
    ).toBe("void");
  });
  it("creates a matching Join for Parallel", () => {
    const result = addCard(
      blank(),
      "main",
      meta("parallel", { branches: ["a", "b"] }),
    );
    expect(
      result.workflow.graphs.main.cards.find((c) => c.kind === "join")?.config
        ?.parallel,
    ).toBe(result.id);
  });
  it("duplicates ownership and internal value references", () => {
    let loop = addCard(blank(), "main", meta("loop", { count: 2 }));
    let body = addCard(loop.workflow, "main", meta("wait"));
    let next = connect(body.workflow, "main", loop.id, body.id, "flow:body");
    const copy = duplicateCard(next, "main", loop.id);
    expect(
      copy.workflow.graphs.main.cards.filter((c) => c.owner?.card === copy.id),
    ).toHaveLength(1);
  });
  it("layout areas hide members without changing executable graphs", () => {
    const original = blank();
    original.layout = {
      main: {
        areas: [
          {
            id: "area",
            kind: "collapsible",
            name: "Group",
            position: { x: 0, y: 0 },
            collapsed: true,
            members: ["finish"],
          },
        ],
      },
    };
    expect(visibleCards(original, "main").map((c) => c.id)).toEqual(["start"]);
    expect(arrange(original, "main").graphs).toEqual(original.graphs);
  });
  it("stores typed value wiring separately from execution", () => {
    const result = addCard(blank(), "main", meta("calculate"));
    const next = connect(
      result.workflow,
      "main",
      "start",
      result.id,
      "value",
      "value:config:left",
    );
    expect(next.graphs.main.edges.at(-1)?.kind).toBe("value");
    expect(next.graphs.main.edges[0].kind).toBe("flow");
  });
  it("removes the generated Join with its Parallel card", () => {
    const result = addCard(
      blank(),
      "main",
      meta("parallel", { branches: ["a", "b"] }),
    );
    const removed = removeCard(result.workflow, "main", result.id);
    expect(removed.graphs.main.cards.some((c) => c.kind === "join")).toBe(
      false,
    );
  });
});

describe("persisted skip marks", () => {
  it("removes deleted roots and leaves duplicated cards unmarked", () => {
    const result = addCard(blank(), "main", meta("wait", { seconds: 0 }));
    result.workflow.skip_cards = [{ graph: "main", card: result.id }];
    const copy = duplicateCard(result.workflow, "main", result.id);
    expect(copy.workflow.skip_cards).toEqual([
      { graph: "main", card: result.id },
    ]);
    expect(copy.workflow.skip_cards?.some((x) => x.card === copy.id)).toBe(
      false,
    );
    expect(removeCard(copy.workflow, "main", result.id).skip_cards).toEqual([]);
  });
});
