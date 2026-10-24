import { SkipContext, type SkipPlan } from "./run/SkipContext";
import { WorkspaceLink } from "./cards/WorkspaceLink";
import {
  allowNavigation,
  blockNavigation,
  readRoute,
  navigate,
} from "./navigation/location";
import { useEditorLocation } from "./navigation/useEditorLocation";
import { useRunState } from "./run/useRunState";
import { EditorToolbar } from "./editor/EditorToolbar";
import { assertFormValidity } from "./components/validation";
import { configuredCard, resultType } from "./shared/cards";
import { useEffect, useRef, useState } from "react";
import { ReactFlowProvider, type Connection } from "@xyflow/react";
import { GitBranch } from "lucide-react";
import { api, ApiError } from "./shared/api";
import {
  VALUE_TYPES,
  type Card,
  type Catalog,
  type RunState,
  type SavedDocument,
  type Workflow,
  type ValidationIssue,
} from "./shared/types";
import { setCardConfiguration } from "./editor/cardCommands";
import { useEditor } from "./editor/useEditor";
import {
  addCard,
  addFunction,
  arrange,
  clone,
  connect,
  duplicateCard,
  removeCard,
  orderedCards,
  ownershipDepth,
} from "./editor/model";
import { FlowCanvas } from "./editor/FlowCanvas";
import {
  ContextMenu,
  type MenuState,
  type MenuAction,
} from "./editor/ContextMenu";
import { CardInspector } from "./cards/CardInspector";
import { RunInputs } from "./run/RunInputs";
import { ManualDialog } from "./run/ManualDialog";
import { WorkflowSettings } from "./editor/WorkflowSettings";
import { RunPanel } from "./run/RunPanel";
import { Dialog } from "./components/Dialog";
import { Choice } from "./components/Choice";
import { Declarations } from "./components/Declarations";
export function EditorLoader({
  id,
  catalog,
  onHome,
}: {
  id: string;
  catalog: Catalog;
  onHome: () => void;
}) {
  const [record, setRecord] = useState<SavedDocument | null>(null),
    [error, setError] = useState("");
  useEffect(() => {
    api<SavedDocument>("config", undefined, id)
      .then(setRecord)
      .catch((e) => setError(e.message));
  }, [id]);
  return record ? (
    <ReactFlowProvider>
      <Editor id={id} catalog={catalog} initial={record} onHome={onHome} />
    </ReactFlowProvider>
  ) : (
    <main className="loading">
      <h1>Workflow Workbench</h1>
      <p>{error || "Opening workflow…"}</p>
      <button onClick={onHome}>Home</button>
    </main>
  );
}
function Editor({
  id,
  catalog,
  initial,
  onHome,
}: {
  id: string;
  catalog: Catalog;
  initial: SavedDocument;
  onHome: () => void;
}) {
  const { workflow, commit, reset, undo, redo, canUndo, canRedo } = useEditor(
    initial.recovery?.workflow ?? initial.workflow,
  );
  const [saved, setSaved] = useState(initial),
    [overall, setOverall] = useState(!readRoute(location.href).card),
    [following, setFollowing] = useState(!readRoute(location.href).card),
    [reveal, setReveal] = useState<{
      card: string;
      graph: string;
      key: string;
    } | null>(() => {
      const route = readRoute(location.href);
      return route.card
        ? {
            card: route.card,
            graph: route.graph ?? "main",
            key: "open:" + (route.run ?? route.card),
          }
        : null;
    }),
    [error, setError] = useState(""),
    [notice, setNotice] = useState(
      initial.recovery ? "Recovered your unsaved draft. Save to keep it." : "",
    ),
    [working, setWorking] = useState(false),
    [yaml, setYaml] = useState(initial.recovery?.yaml ?? initial.yaml),
    [yamlDirty, setYamlDirty] = useState(false),
    [review, setReview] = useState(""),
    [menu, setMenu] = useState<MenuState | null>(null),
    [newFunction, setNewFunction] = useState<{ returns: string } | null>(null),
    [functionName, setFunctionName] = useState("New function"),
    [hidden, setHidden] = useState(false),
    [panelWidth, setPanelWidth] = useState(360),
    [leave, setLeave] = useState(false),
    [confirmDelete, setConfirmDelete] = useState<string | null>(null),
    [runInputs, setRunInputs] = useState<Record<string, unknown> | null>(null),
    [runSelection, setRunSelection] = useState<{
      graph: string;
      card: string;
    } | null>(null),
    [manualId, setManualId] = useState<string | null>(null);
  const {
    graphId,
    setGraphId,
    view,
    setView,
    representation,
    setRepresentation,
    selected,
    setSelected,
    settings,
    setSettings,
  } = useEditorLocation(workflow, !!initial.recovery);
  const leaveTarget = useRef<(() => void) | null>(null);
  const { state, setState } = useRunState(id, setError);
  const [skipPlan, setSkipPlan] = useState<SkipPlan | null>(null);
  const [skipPreview, setSkipPreview] = useState<SkipPlan | null>(null);
  const [skipReviewExpanded, setSkipReviewExpanded] = useState(false);
  const skipReviewHeading = useRef<HTMLHeadingElement>(null);
  useEffect(() => {
    if (!skipPreview) return;
    const previous = document.activeElement;
    skipReviewHeading.current?.focus({ preventScroll: true });
    const cancel = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !event.defaultPrevented)
        setSkipPreview(null);
    };
    document.addEventListener("keydown", cancel);
    return () => {
      document.removeEventListener("keydown", cancel);
      if (previous instanceof HTMLElement && previous.isConnected)
        previous.focus({ preventScroll: true });
    };
  }, [skipPreview]);
  const [skipRequest, setSkipRequest] = useState<{
    graph: string;
    card: string;
    unmark?: boolean;
  } | null>(null);
  const [issues, setIssues] = useState<ValidationIssue[]>([]);
  const [validatedKey, setValidatedKey] = useState<string | null>(null);
  const draftKey = JSON.stringify(yamlDirty ? { yaml } : workflow);
  const showValidation = validatedKey === draftKey;
  const [checking, setChecking] = useState(false);
  const [breadcrumbs, setBreadcrumbs] = useState<
    { graph: string; card: string | null; name: string }[]
  >([]);
  const seenManual = useRef(new Set<string>()),
    list = useRef<HTMLDivElement>(null),
    panel = useRef<HTMLElement>(null),
    graphRef = useRef<HTMLDivElement>(null),
    autoScroll = useRef(false);
  const graph = workflow.graphs[graphId],
    rawCard = graph.cards.find((c) => c.id === selected),
    card = rawCard
      ? configuredCard(
          rawCard,
          catalog.cards.find((m) => m.kind === rawCard.kind)!,
        )
      : undefined,
    dirty =
      yamlDirty || JSON.stringify(workflow) !== JSON.stringify(saved.workflow),
    locked = state.busy || working || !!initial.inspection,
    editing = view === "edit" && !locked;
  useEffect(
    () =>
      blockNavigation((next, proceed) => {
        if (next.workflow !== id && dirty) {
          leaveTarget.current = proceed;
          setLeave(true);
          return false;
        }
        return true;
      }),
    [dirty, id],
  );
  const currentFunction = Object.entries(workflow.functions ?? {}).find(
    ([, f]) => f.graph === graphId,
  );
  const executions = Object.values(state.executions);
  const statuses: Record<string, string> = {};
  for (const e of executions)
    if (e.graph === graphId) statuses[e.card] = e.status;
  const active = [...executions]
    .sort((a, b) => b.path.length - a.path.length)
    .find((e) => ["running", "manual"].includes(e.status));
  const seenFailures = useRef(new Set<string>());
  const failureSignature = JSON.stringify(
    executions
      .filter((e) => e.status === "failed")
      .map((e) => [e.path, e.started, e.attempts.length]),
  );
  useEffect(() => {
    if (view !== "run") return;
    const failed = Object.values(state.executions)
      .filter(
        (e) =>
          e.status === "failed" &&
          workflow.graphs[e.graph]?.cards.some((c) => c.id === e.card),
      )
      .sort((a, b) => b.path.split("/").length - a.path.split("/").length);
    const newlyFailed: typeof failed = [];
    for (const execution of failed) {
      const key = JSON.stringify([
        state.run_id,
        execution.path,
        execution.started,
        execution.attempts.length,
      ]);
      if (!seenFailures.current.has(key)) {
        seenFailures.current.add(key);
        newlyFailed.push(execution);
      }
    }
    if (!newlyFailed.length) return;
    const newest = newlyFailed[0];
    const failure =
      failed.find((e) => e.path.startsWith(newest.path + "/")) ?? newest;
    setFollowing(false);
    setOverall(false);
    setHidden(false);
    setSettings(false);
    setGraphId(failure.graph, true);
    setSelected(failure.card);
    setReveal({
      graph: failure.graph,
      card: failure.card,
      key: "failure:" + state.run_id + ":" + failureSignature,
    });
  }, [state.run_id, failureSignature, view]);
  const signature = JSON.stringify(state.manual);
  useEffect(() => {
    seenManual.current.clear();
    setManualId(null);
  }, [state.run_id]);

  useEffect(() => {
    const next = Object.keys(state.manual).find(
      (path) => !seenManual.current.has(path),
    );
    if (next && !manualId) {
      seenManual.current.add(next);
      setManualId(next);
      setView("run");
    }
  }, [signature, manualId]);
  useEffect(() => {
    if (!following || view !== "run" || !active) return;
    setGraphId(active.graph, true);
    setSelected(active.card);
    if (representation === "list")
      requestAnimationFrame(() => {
        autoScroll.current = true;
        list.current
          ?.querySelector(`[data-card-id="${CSS.escape(active.card)}"]`)
          ?.scrollIntoView({ block: "nearest" });
      });
  }, [active?.path, following, view, representation]);
  useEffect(() => {
    if (!reveal || representation !== "list") return;
    const frame = requestAnimationFrame(() => {
      autoScroll.current = true;
      list.current
        ?.querySelector(`[data-card-id="${CSS.escape(reveal.card)}"]`)
        ?.scrollIntoView({ block: "nearest" });
    });
    return () => cancelAnimationFrame(frame);
  }, [reveal?.key, representation, graphId]);
  useEffect(() => {
    const media = matchMedia("(max-width:700px)");
    const update = () => {
      if (media.matches) setRepresentation("list");
    };
    media.addEventListener("change", update);
    return () => media.removeEventListener("change", update);
  }, []);
  async function act<T>(
    fn: () => Promise<T>,
    validateDraft = false,
  ): Promise<T | undefined> {
    setWorking(true);
    setError("");
    if (validateDraft) {
      setValidatedKey(draftKey);
      setChecking(true);
      setIssues([]);
    }
    try {
      return await fn();
    } catch (e) {
      setError(
        e instanceof ApiError && e.issues.length
          ? ""
          : e instanceof Error
            ? e.message
            : String(e),
      );
      if (e instanceof ApiError && e.issues.length) {
        if (validateDraft) setIssues(e.issues);
        else
          setNotice(
            "Run not started. Click Save or Validate & review to see what needs fixing.",
          );
      } else if (validateDraft) setValidatedKey(null);
      return undefined;
    } finally {
      setWorking(false);
      if (validateDraft) setChecking(false);
    }
  }
  function patchCard(id: string, changes: Partial<Card>) {
    if (!editing) return;
    const next = clone(workflow);
    next.graphs[graphId].cards = next.graphs[graphId].cards.map((c) =>
      c.id === id ? { ...c, ...changes } : c,
    );
    commit(next);
  }
  function config(id: string, key: string, value: unknown) {
    if (editing)
      commit(
        setCardConfiguration(workflow, graphId, id, key, value, catalog.cards),
      );
  }
  function select(id: string) {
    setSelected(id);
    setOverall(false);
    setFollowing(false);
    setHidden(false);
    setSettings(false);
    requestAnimationFrame(() => {
      panel.current?.scrollTo({ top: 0 });
      if (innerWidth <= 700)
        panel.current?.scrollIntoView({
          block: "start",
          behavior: matchMedia("(prefers-reduced-motion:reduce)").matches
            ? "instant"
            : "smooth",
        });
    });
  }
  function inspect() {
    if (view === "run" && overall) {
      setOverall(false);
      setFollowing(false);
      if (active) {
        setSelected(active.card);
        setGraphId(active.graph, true);
      }
    }
  }
  function showOverall() {
    setOverall(true);
    setFollowing(true);
    setHidden(false);
    setSettings(false);
  }
  function openFunction(id: string) {
    const f = workflow.functions?.[id];
    if (!f) return;
    if (!workflow.graphs[f.graph]) {
      setError(
        "This function has no graph yet. Create it in YAML or choose Create function.",
      );
      return;
    }
    setBreadcrumbs((old) => [
      ...old,
      {
        graph: graphId,
        card: selected,
        name: currentFunction?.[1].name ?? workflow.name,
      },
    ]);
    setGraphId(f.graph);
    setSelected(null);
    setOverall(false);
    setFollowing(false);
  }
  function context(
    event: Pick<MouseEvent, "preventDefault" | "clientX" | "clientY">,
    target: {
      kind: "canvas" | "card" | "edge" | "area";
      id?: string;
      point?: { x: number; y: number };
    },
  ) {
    if (!editing && !(view === "run" && target.kind === "card")) return;
    event.preventDefault();
    setMenu({ ...target, x: event.clientX, y: event.clientY });
  }
  useEffect(() => {
    let cancelled = false;
    api<SkipPlan>("skip-plan", {}, id)
      .then((p) => {
        if (!cancelled) setSkipPlan(p);
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [id, saved.revision, state.busy]);
  function skipReason(cardId?: string) {
    const card = graph.cards.find((c) => c.id === cardId);
    if (
      !card ||
      ["start", "finish", "return", "break", "continue"].includes(card.kind)
    )
      return "This control card cannot be marked to skip.";
    if (initial.inspection && !state.busy)
      return "Historical executions are read-only. Open the definition.";
    if (dirty) return "Save your changes before reviewing skips.";
    return "";
  }
  async function previewSkip(request: {
    graph: string;
    card: string;
    unmark?: boolean;
  }) {
    setMenu(null);
    if (dirty) {
      setError("Save your changes before reviewing skips.");
      return;
    }
    const result = await act(() =>
      api<SkipPlan>(
        "skip-preview",
        {
          ...request,
          revision: initial.inspection ? undefined : saved.revision,
        },
        id,
      ),
    );
    if (result) {
      setSkipRequest(request);
      setSkipPreview(result);
      setFollowing(false);
      setReveal({
        graph: request.graph,
        card: request.card,
        key: "skip-preview:" + result.token,
      });
    }
  }
  async function confirmSkip() {
    if (!skipPreview) return;
    const result = await act(() =>
      api<{ document: SavedDocument; plan: SkipPlan; state: RunState }>(
        "skip-confirm",
        { token: skipPreview.token },
        id,
      ),
    );
    if (result) {
      setSaved(result.document);
      reset(result.document.workflow);
      setYaml(result.document.yaml);
      setSkipPlan(result.plan);
      setState(result.state);
      setSkipPreview(null);
      setSkipRequest(null);
      setNotice("Skip marks saved. Completed work is retained.");
    } else {
      setSkipPreview(null);
    }
  }
  function createCard(kind: string) {
    const meta = catalog.cards.find((c) => c.kind === kind);
    if (!meta) return;
    const next = addCard(workflow, graphId, meta, menu?.point);
    commit(next.workflow);
    setSelected(next.id);
    setOverall(false);
    setHidden(false);
    setMenu(null);
    setNotice(
      "Card added. Connect its execution ports to place it in the flowchart.",
    );
  }
  function wire(connection: Connection) {
    if (!editing || !connection.source || !connection.target) return;
    try {
      const next = connect(
        workflow,
        graphId,
        connection.source,
        connection.target,
        connection.sourceHandle ?? "flow:next",
        connection.targetHandle ?? "flow:entry",
      );
      if (
        connection.sourceHandle === "value" &&
        connection.targetHandle === "value:config:value"
      ) {
        const target = next.graphs[graphId].cards.find(
          (c) => c.id === connection.target,
        )!;
        if (["finish", "return"].includes(target.kind)) {
          const source = graph.cards.find((c) => c.id === connection.source)!;
          target.config = {
            ...target.config,
            value: null,
            returns: resultType(
              source,
              catalog.cards.find((m) => m.kind === source.kind)!,
              workflow,
            ),
          };
        }
      }
      commit(next);
      setError("");
      setNotice("Connection added. Validate the flowchart before running.");
    } catch (e) {
      setError((e as Error).message);
    }
  }
  function changeArea(
    id: string,
    changes: { width?: number; height?: number; collapsed?: boolean },
  ) {
    const next = clone(workflow);
    Object.assign(
      next.layout![graphId].areas!.find((a) => a.id === id)!,
      changes,
    );
    commit(next);
  }
  function move(id: string, position: { x: number; y: number }) {
    if (!editing) return;
    const next = clone(workflow);
    next.layout ??= {};
    next.layout[graphId] ??= { positions: {}, areas: [] };
    next.layout[graphId].positions ??= {};
    const area = next.layout[graphId].areas?.find((a) => a.id === id);
    if (area) {
      const dx = position.x - area.position.x,
        dy = position.y - area.position.y;
      for (const member of area.members ?? []) {
        const p = next.layout[graphId].positions![member];
        if (p)
          next.layout[graphId].positions![member] = {
            x: p.x + dx,
            y: p.y + dy,
          };
      }
      area.position = position;
    } else next.layout[graphId].positions![id] = position;
    commit(next);
  }
  async function checked() {
    assertFormValidity();
    return api<{ workflow: Workflow; yaml: string; diff: string }>(
      "validate",
      yamlDirty ? { yaml } : { workflow },
      id,
    );
  }
  async function validate() {
    await act(async () => {
      const result = await checked();
      if (yamlDirty) commit(result.workflow);
      setYaml(result.yaml);
      setYamlDirty(false);
      setReview(result.diff || "Workflow is valid. No configuration changes.");
      setNotice("Validation passed.");
      setValidatedKey(JSON.stringify(result.workflow));
    }, true);
  }
  async function save(andRun = false) {
    await act(async () => {
      assertFormValidity();
      const record = await api<SavedDocument>(
        "save",
        { ...(yamlDirty ? { yaml } : { workflow }), revision: saved.revision },
        id,
      );
      setValidatedKey(JSON.stringify(record.workflow));
      setSaved(record);
      reset(record.workflow);
      setYaml(record.yaml);
      setYamlDirty(false);
      setNotice(record.runnable === false ? "Draft saved." : "Workflow saved.");
      setIssues(record.issues ?? []);
      setReview("");
      if (andRun && record.runnable !== false) prepareRun(record);
    }, true);
  }
  function prepareRun(
    record = saved,
    selection: { graph: string; card: string } | null = null,
  ) {
    setRunSelection(selection);
    const definitions =
      selection && selection.graph !== "main"
        ? (Object.values(record.workflow.functions ?? {}).find(
            (f) => f.graph === selection.graph,
          )?.inputs ?? {})
        : (record.workflow.inputs ?? {});
    const values = Object.fromEntries(
      Object.entries(definitions).map(([k, v]) => [k, v.default ?? null]),
    );
    if (Object.keys(values).length) {
      setRunInputs(values);
      return;
    }
    void start(record, {}, selection);
  }
  async function start(
    record: SavedDocument,
    inputs: Record<string, unknown>,
    selection = runSelection,
  ) {
    await act(async () => {
      assertFormValidity();
      const result = await api<RunState>(
        "run",
        { revision: record.revision, inputs, selection },
        id,
      );
      if (initial.inspection && selection) {
        navigate({
          run: result.run_id,
          view: "run",
          graph: selection.graph === "main" ? undefined : selection.graph,
          card: selection.card,
          panel: undefined,
        });
        return;
      }
      setState(result);
      setView("run");
      if (selection) {
        setGraphId(selection.graph);
        setSelected(selection.card);
        setFollowing(false);
        setReveal({
          card: selection.card,
          graph: selection.graph,
          key: result.run_id ?? String(Date.now()),
        });
        setOverall(false);
        setHidden(false);
      } else showOverall();
      setRunInputs(null);
    });
  }
  async function mode(next: "canvas" | "list" | "yaml") {
    if (yamlDirty && next !== "yaml") {
      const result = await act(() =>
        api<{ workflow: Workflow; yaml: string; diff: string }>(
          "draft",
          { yaml },
          id,
        ),
      );
      if (!result) return;
      commit(result.workflow);
      setYaml(result.yaml);
      setYamlDirty(false);
    }
    if (next === "yaml" && !yamlDirty && !initial.inspection)
      setYaml(
        (await act(() => api<{ yaml: string }>("draft", { workflow }, id)))
          ?.yaml ?? yaml,
      );
    setRepresentation(next);
  }
  const addItems: MenuAction[] = [
    ...["area", "collapsible", "annotation"].map((kind) => ({
      id: "layout:" + kind,
      label:
        kind === "area"
          ? "Dotted area"
          : kind === "collapsible"
            ? "Collapsible area"
            : "Annotation",
      category: "Layout",
    })),
    ...catalog.cards
      .filter(
        (c) => c.kind !== "start" && !(currentFunction && c.kind === "finish"),
      )
      .map((c) => ({ id: c.kind, label: c.label, category: c.category })),
  ];
  function chooseMenu(action: string) {
    if (action === "skip" && menu?.id) {
      if (!skipReason(menu.id))
        void previewSkip({
          graph: graphId,
          card: menu.id,
          unmark: !!workflow.skip_cards?.some(
            (x) => x.graph === graphId && x.card === menu.id,
          ),
        });
    } else if (action.startsWith("layout:")) {
      const next = clone(workflow);
      next.layout ??= {};
      next.layout[graphId] ??= { positions: {}, areas: [] };
      next.layout[graphId].areas ??= [];
      const areaId = "area-" + Date.now();
      next.layout[graphId].areas!.push({
        id: areaId,
        kind: action.slice(7) as "area" | "collapsible" | "annotation",
        name: "Organize this area",
        position: menu?.point ?? { x: 0, y: 0 },
        width: 600,
        height: 300,
        members: [],
      });
      commit(next);
      setSelected(areaId);
    } else if (action === "delete") {
      if (menu?.kind === "edge") {
        const next = clone(workflow);
        next.graphs[graphId].edges = graph.edges.filter(
          (e) => e.id !== menu.id,
        );
        commit(next);
      } else setConfirmDelete(menu?.id ?? null);
    } else if (action === "duplicate" && menu?.id) {
      const next = duplicateCard(workflow, graphId, menu.id);
      commit(next.workflow);
      setSelected(next.id);
    } else if (action === "disconnect" && menu?.id) {
      const next = clone(workflow);
      next.graphs[graphId].edges = graph.edges.filter(
        (e) => e.source !== menu.id && e.target !== menu.id,
      );
      commit(next);
    } else createCard(action);
    setMenu(null);
  }
  const area = workflow.layout?.[graphId]?.areas?.find(
    (a) => a.id === selected,
  );
  const currentManual = manualId ? state.manual[manualId] : undefined;
  return (
    <div className="workbench">
      <header>
        <div className="brand">
          <GitBranch size={26} />
          <div>
            <h1>Workflow Workbench</h1>
            <p>
              {workflow.name} ·{" "}
              {dirty ? "Unsaved draft" : "Saved configuration"}
            </p>
          </div>
        </div>
        <div className="actions">
          <a
            className="documentation-link"
            href="/docs/"
            target="_blank"
            rel="noopener noreferrer"
          >
            Documentation
          </a>
          <button onClick={() => (dirty ? setLeave(true) : onHome())}>
            Home
          </button>
          <button
            aria-pressed={settings}
            onClick={() => {
              setSettings(!settings);
              setOverall(false);
              setHidden(false);
            }}
          >
            Workflow settings
          </button>
          <button
            aria-pressed={view === "edit"}
            disabled={locked}
            onClick={() => setView("edit")}
          >
            Edit
          </button>
          <button aria-pressed={view === "run"} onClick={() => setView("run")}>
            Run
          </button>
        </div>
      </header>
      {state.selection && (
        <div className="alert" role="status">
          <span>
            Run from here: {state.selection.name}. Follows connected cards to
            Finish or Return. Compatible earlier results are reused when
            available; earlier commands are not rerun.
          </span>
        </div>
      )}
      {initial.inspection && (
        <div className="alert" role="status">
          <span>
            {state.busy
              ? "Execution view · Live logs and results. Stop all stops this execution; Pause scheduling affects its shared run."
              : state.can_run_from_here
                ? "Execution finished · Select a card and choose Run from here to start a fresh run. Original evidence is preserved."
                : "Execution view · Waiting for other running work to stop before a fresh run from here can start."}
          </span>
          <a
            href={"/workflows/" + encodeURIComponent(id) + "/edit"}
            target="_blank"
            rel="noopener noreferrer"
          >
            Open definition
          </a>
        </div>
      )}
      {error && (
        <div className="alert error" role="alert">
          <span>{error}</span>
          <button onClick={() => setError("")}>Dismiss error</button>
        </div>
      )}
      {notice && (
        <div className="alert" role="status">
          <span>{notice}</span>
          <button onClick={() => setNotice("")}>Dismiss</button>
        </div>
      )}
      {showValidation && (
        <section
          className="validation-issues"
          aria-label="Workflow validation"
          aria-busy={checking}
        >
          <p className="validation-summary" aria-live="polite">
            {checking
              ? "Checking workflow…"
              : issues.length
                ? `${issues.length} ${issues.length === 1 ? "issue prevents" : "issues prevent"} running. Select an issue to fix it.`
                : "Ready to run · Validation passed."}
          </p>
          {!checking && issues.length > 0 && (
            <ul>
              {issues.map((issue, index) => (
                <li key={`${issue.graph}:${issue.card}:${issue.port}:${index}`}>
                  <button
                    onClick={() => {
                      setView("edit");
                      if (!issue.card || !workflow.graphs[issue.graph]) {
                        setSettings(true);
                        return;
                      }
                      setGraphId(issue.graph);
                      setSettings(false);
                      select(issue.card);
                      setRepresentation("canvas");
                    }}
                  >
                    <strong>
                      {issue.label ??
                        workflow.graphs[issue.graph]?.cards.find(
                          (c) => c.id === issue.card,
                        )?.name ??
                        "Workflow settings"}
                      {issue.port ? ` · ${issue.port}` : ""}
                    </strong>
                    <span>{issue.message}</span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </section>
      )}
      <EditorToolbar
        view={view}
        representation={representation}
        state={state}
        editing={editing}
        locked={locked}
        dirty={dirty}
        selectedName={card?.name}
        selectedLocked={
          working ||
          state.busy ||
          (!!initial.inspection && !state.can_run_from_here)
        }
        canUndo={canUndo}
        canRedo={canRedo}
        hidden={hidden}
        actions={{
          add: (e) => setMenu({ kind: "canvas", x: e.clientX, y: e.clientY }),
          save: (andRun) => void save(andRun),
          undo,
          redo,
          arrange: () => commit(arrange(workflow, graphId)),
          validate: () => void validate(),
          run: () => prepareRun(),
          runFromHere: () => {
            if (card) prepareRun(saved, { graph: graphId, card: card.id });
          },
          stop: () => void act(() => api("stop", {}, id)),
          pause: () =>
            void act(() => api("pause", { paused: !state.paused }, id)),
          overall: showOverall,
          manual: () => setManualId(Object.keys(state.manual)[0]),
          toggleDetails: () => setHidden(!hidden),
          representation: (v) => void mode(v),
        }}
      />
      <nav className="breadcrumbs" aria-label="Function navigation">
        <button
          onClick={() => {
            setGraphId("main");
            setBreadcrumbs([]);
            setSelected(null);
          }}
        >
          {workflow.name}
        </button>
        {breadcrumbs
          .filter((b) => b.graph !== "main")
          .map((b, i) => (
            <button
              key={i}
              onClick={() => {
                setGraphId(b.graph);
                setSelected(b.card);
                setBreadcrumbs(breadcrumbs.slice(0, i));
              }}
            >
              {b.name}
            </button>
          ))}
        {currentFunction && (
          <>
            <span>
              / {currentFunction[1].name ?? currentFunction[0]} · returns{" "}
              {currentFunction[1].returns}
            </span>
            <button
              onClick={() => {
                const b = breadcrumbs.at(-1);
                setGraphId(b?.graph ?? "main");
                setSelected(b?.card ?? null);
                setBreadcrumbs((old) => old.slice(0, -1));
              }}
            >
              Back to caller
            </button>
          </>
        )}
      </nav>
      <div
        className={`workspace ${hidden && !skipPreview ? "panel-hidden" : ""} ${skipPreview ? "skip-reviewing" : ""}`}
        style={{ "--panel-width": panelWidth + "px" } as React.CSSProperties}
      >
        {(!hidden || !!skipPreview) && (
          <>
            <aside
              ref={panel}
              aria-label={
                view === "run"
                  ? overall
                    ? "Overall run"
                    : "Card execution"
                  : "Card settings"
              }
            >
              {skipPreview ? (
                <section
                  className={`skip-review ${skipReviewExpanded ? "review-expanded" : ""}`}
                  role="region"
                  aria-label={
                    skipRequest?.unmark ? "Review unmark" : "Review card skip"
                  }
                >
                  <h2 tabIndex={-1} ref={skipReviewHeading}>
                    {skipRequest?.unmark ? "Review unmark" : "Review card skip"}
                  </h2>
                  <button
                    className="skip-review-toggle"
                    aria-expanded={skipReviewExpanded}
                    onClick={() => setSkipReviewExpanded((x) => !x)}
                  >
                    {skipReviewExpanded
                      ? "Hide details"
                      : "Review affected cards"}
                  </button>
                  <div className="skip-review-content">
                    <p>
                      {skipRequest?.unmark
                        ? "Remove the explicit mark. Remaining inherited marks are listed below."
                        : "These cards will be bypassed. Completed work is retained."}
                    </p>
                    <div className="skip-review-list">
                      {[...skipPreview.affected, ...skipPreview.children].map(
                        (x, i) => (
                          <p key={i}>
                            <strong>
                              {x.scope ?? x.graph} / {x.name}
                            </strong>
                            <br />
                            {x.reasons
                              .map((r) => r.reason + ": " + r.source)
                              .join("; ")}
                          </p>
                        ),
                      )}
                    </div>
                    {skipPreview.continuations.map((x) => (
                      <p key={x.graph + x.card}>
                        Continue after {x.card} at {x.next}.
                      </p>
                    ))}
                    {!!skipPreview.consumed.length && (
                      <p>
                        Already completed or skipped work will not run again.
                      </p>
                    )}
                    {skipPreview.blockers.map((x) => (
                      <p role="alert" key={x}>
                        {x}
                      </p>
                    ))}
                  </div>
                  <div className="actions skip-review-actions">
                    <button onClick={() => setSkipPreview(null)}>Cancel</button>
                    <button
                      disabled={working || !!skipPreview.blockers.length}
                      onClick={() => void confirmSkip()}
                    >
                      {skipRequest?.unmark ? "Confirm unmark" : "Confirm skip"}
                    </button>
                  </div>
                </section>
              ) : settings ? (
                <WorkflowSettings
                  workflow={workflow}
                  editing={editing}
                  commit={commit}
                  openFunction={openFunction}
                  onNewFunction={() => setNewFunction({ returns: "void" })}
                />
              ) : view === "run" ? (
                <>
                  {!overall && card?.kind === "workspace" && (
                    <WorkspaceLink
                      workflow={workflow}
                      graphId={graphId}
                      cardId={card.id}
                      view="run"
                      execution={
                        Object.values(state.executions)
                          .filter(
                            (e) => e.card === card.id && e.graph === graphId,
                          )
                          .at(-1)?.path
                      }
                    />
                  )}
                  <RunPanel
                    state={state}
                    selected={selected}
                    graphId={graphId}
                    overall={overall}
                    onOverall={showOverall}
                    onSelect={(id, g) => {
                      setGraphId(g);
                      select(id);
                    }}
                    onStop={(path) =>
                      void act(() => api("stop", { execution: path }, id))
                    }
                    onSkip={(execution) =>
                      void previewSkip({
                        graph: execution.graph,
                        card: execution.card,
                      })
                    }
                  />
                </>
              ) : area ? (
                <>
                  <h2>Layout area</h2>
                  <p>
                    Only canvas arrangement changes. Execution and scope stay
                    the same.
                  </p>
                  <label>
                    Name
                    <input
                      value={area.name}
                      onChange={(e) => {
                        const next = clone(workflow);
                        const target = next.layout![graphId].areas!.find(
                          (a) => a.id === area.id,
                        )!;
                        target.name = e.target.value;
                        commit(next);
                      }}
                    />
                  </label>
                  <fieldset>
                    <legend>Cards in this layout area</legend>
                    {graph.cards.map((c) => (
                      <label className="check" key={c.id}>
                        <input
                          type="checkbox"
                          checked={area.members?.includes(c.id) ?? false}
                          onChange={(e) => {
                            const next = clone(workflow);
                            const target = next.layout![graphId].areas!.find(
                              (a) => a.id === area.id,
                            )!;
                            target.members = e.target.checked
                              ? [...(target.members ?? []), c.id]
                              : (target.members ?? []).filter(
                                  (id) => id !== c.id,
                                );
                            commit(next);
                          }}
                        />
                        {c.name}
                      </label>
                    ))}
                  </fieldset>
                </>
              ) : card ? (
                <CardInspector
                  card={card}
                  workflow={workflow}
                  graphId={graphId}
                  catalog={catalog}
                  editing={editing}
                  currentFunction={currentFunction}
                  onPatch={(changes) => patchCard(card.id, changes)}
                  onConfig={(key, value) => config(card.id, key, value)}
                  onOpenFunction={openFunction}
                  onNewFunction={(returns) => setNewFunction({ returns })}
                  onOpenGlobals={() => {
                    setSettings(true);
                    requestAnimationFrame(() => {
                      const field =
                        panel.current?.querySelector<HTMLInputElement>(
                          'input[aria-label="New global variable name"]',
                        );
                      field?.focus();
                      field?.scrollIntoView({ block: "center" });
                    });
                  }}
                  onConnect={wire}
                  onDeleteEdge={(edge) => {
                    const next = clone(workflow);
                    next.graphs[graphId].edges = graph.edges.filter(
                      (e) => e.id !== edge,
                    );
                    commit(next);
                  }}
                  onDuplicate={() => {
                    const next = duplicateCard(workflow, graphId, card.id);
                    commit(next.workflow);
                    setSelected(next.id);
                  }}
                  onDelete={() => setConfirmDelete(card.id)}
                />
              ) : (
                <>
                  <h2>
                    {currentFunction
                      ? "Function flowchart"
                      : "Build your flowchart"}
                  </h2>
                  {currentFunction && (
                    <>
                      <p>
                        Returns {currentFunction[1].returns}. Every successful
                        path must reach Return.
                      </p>
                      <h3>Function inputs</h3>
                      <Declarations
                        values={currentFunction[1].inputs ?? {}}
                        disabled={!editing}
                        onChange={(v) => {
                          const next = clone(workflow);
                          next.functions![currentFunction[0]].inputs =
                            v as NonNullable<
                              Workflow["functions"]
                            >[string]["inputs"];
                          commit(next);
                        }}
                      />
                    </>
                  )}
                  <p>
                    Select a card to configure it, or right-click the canvas to
                    add one. Round ports run cards; square ports carry values.
                  </p>
                </>
              )}
            </aside>
            <div
              className="resize-panel"
              role="separator"
              aria-label="Resize details panel"
              aria-orientation="vertical"
              tabIndex={0}
              onKeyDown={(e) => {
                if (["ArrowLeft", "ArrowRight"].includes(e.key))
                  setPanelWidth((w) =>
                    Math.max(
                      280,
                      Math.min(650, w + (e.key === "ArrowRight" ? 20 : -20)),
                    ),
                  );
              }}
              onPointerDown={(e) => {
                e.currentTarget.setPointerCapture(e.pointerId);
                const start = e.clientX,
                  width = panelWidth;
                const target = e.currentTarget;
                const move = (event: PointerEvent) =>
                  setPanelWidth(
                    Math.max(
                      280,
                      Math.min(
                        650,
                        innerWidth - 350,
                        width + event.clientX - start,
                      ),
                    ),
                  );
                const stop = () => {
                  target.removeEventListener("pointermove", move);
                  target.removeEventListener("pointerup", stop);
                };
                target.addEventListener("pointermove", move);
                target.addEventListener("pointerup", stop);
              }}
            />
          </>
        )}
        <div className={"graph " + representation} ref={graphRef}>
          {representation === "canvas" ? (
            <SkipContext.Provider
              value={{ plan: skipPlan, preview: skipPreview }}
            >
              <FlowCanvas
                workflow={workflow}
                graphId={graphId}
                catalog={catalog.cards}
                editing={editing}
                selected={selected}
                statuses={statuses}
                focus={
                  view === "edit"
                    ? selected
                    : following && active?.graph === graphId
                      ? active.card
                      : null
                }
                following={view === "edit" || following}
                reveal={reveal}
                onInspect={inspect}
                onSelect={select}
                onConnect={wire}
                onMove={move}
                onArea={changeArea}
                onMenu={context}
                onConfig={config}
                onOpenFunction={openFunction}
                onNewFunction={(returns) =>
                  setNewFunction({ returns: returns ?? "json" })
                }
                onDetails={select}
              />
            </SkipContext.Provider>
          ) : representation === "list" ? (
            <div
              className="card-list"
              ref={list}
              role="region"
              aria-label="Flowchart cards"
              tabIndex={0}
              onScroll={() => {
                if (autoScroll.current) {
                  autoScroll.current = false;
                  return;
                }
                inspect();
              }}
            >
              <h2>{currentFunction?.[1].name ?? "Workflow cards"}</h2>
              {orderedCards(graph).map((c) => (
                <button
                  key={c.id}
                  data-card-id={c.id}
                  style={{
                    marginLeft: ownershipDepth(graph, c) * 14,
                    flexShrink: 0,
                  }}
                  className={`list-card state-${statuses[c.id] ?? "pending"} ${skipPreview?.affected.some((x) => x.graph === graphId && x.card === c.id) ? "skip-preview" : ""}`}
                  aria-pressed={selected === c.id}
                  aria-current={
                    statuses[c.id] === "running" ? "step" : undefined
                  }
                  onClick={() => select(c.id)}
                  onContextMenu={(e) => context(e, { kind: "card", id: c.id })}
                  onKeyDown={(e) => {
                    if (e.shiftKey && e.key === "F10") {
                      e.preventDefault();
                      context(
                        { preventDefault() {}, clientX: 100, clientY: 200 },
                        { kind: "card", id: c.id },
                      );
                    }
                  }}
                >
                  <strong>{c.name}</strong>
                  {skipPlan?.affected.some(
                    (x) => x.graph === graphId && x.card === c.id,
                  ) && <small className="skip-badge">Marked to skip</small>}
                  <span>
                    {catalog.cards.find((m) => m.kind === c.kind)?.label} ·{" "}
                    {statuses[c.id] ?? "pending"}
                  </span>
                  {c.owner && (
                    <small>
                      {c.owner.card} / {c.owner.region}
                    </small>
                  )}
                </button>
              ))}
              {editing && (
                <button
                  onClick={(e) =>
                    setMenu({ kind: "canvas", x: e.clientX, y: e.clientY })
                  }
                >
                  Add card
                </button>
              )}
            </div>
          ) : (
            <div className="yaml-editor">
              <h2>Workflow YAML</h2>
              <p>One schema powers the flowchart, forms and CLI.</p>
              <textarea
                aria-label="Workflow YAML"
                className="code"
                disabled={locked}
                value={yaml}
                onChange={(e) => {
                  setYaml(e.target.value);
                  setYamlDirty(true);
                }}
              />
              <button disabled={locked} onClick={() => void validate()}>
                Validate and apply YAML
              </button>
            </div>
          )}
        </div>
      </div>
      {review && (
        <Dialog
          title="Validation and configuration changes"
          onClose={() => setReview("")}
        >
          <pre>{review}</pre>
          <button onClick={() => setReview("")}>Close review</button>
        </Dialog>
      )}
      {!!skipPlan?.affected.length && view === "run" && (
        <details className="skip-summary">
          <summary>
            {skipPlan.affected.length}{" "}
            {skipPlan.affected.length === 1 ? "card" : "cards"} marked to skip
          </summary>
          {skipPlan.affected.map((x) => (
            <p key={x.graph + x.card}>
              {x.graph} / {x.name}:{" "}
              {x.reasons
                .map((r) => r.reason + " (" + r.source + ")")
                .join("; ")}
            </p>
          ))}
        </details>
      )}
      {skipRequest && !skipPreview && error && (
        <button onClick={() => void previewSkip(skipRequest)}>
          Refresh skip preview
        </button>
      )}
      {menu && (
        <ContextMenu
          menu={menu}
          items={
            view === "run"
              ? [
                  {
                    id: "skip",
                    label: workflow.skip_cards?.some(
                      (x) => x.graph === graphId && x.card === menu.id,
                    )
                      ? [
                          "passed",
                          "recorded",
                          "skipped",
                          "cancelled",
                          "failed",
                        ].includes(statuses[menu.id ?? ""] ?? "")
                        ? "Unmark for future runs"
                        : "Unmark"
                      : state.busy
                        ? "Skip this card"
                        : "Mark to skip",
                    disabled: !!skipReason(menu.id),
                    description:
                      skipReason(menu.id) ||
                      "Continue without a result from this card.",
                  },
                ]
              : menu.kind === "canvas"
                ? addItems
                : menu.kind === "edge"
                  ? [{ id: "delete", label: "Delete connection" }]
                  : menu.kind === "area"
                    ? [{ id: "delete", label: "Remove layout area" }]
                    : graph.cards.find((c) => c.id === menu.id)?.kind ===
                        "start"
                      ? [{ id: "disconnect", label: "Disconnect all" }]
                      : [
                          { id: "duplicate", label: "Duplicate card" },
                          { id: "disconnect", label: "Disconnect all" },
                          { id: "delete", label: "Delete card" },
                        ]
          }
          onChoose={chooseMenu}
          onClose={() => setMenu(null)}
        />
      )}
      {newFunction && (
        <Dialog title="Create function" onClose={() => setNewFunction(null)}>
          <label>
            Function name
            <input
              value={functionName}
              onChange={(e) => setFunctionName(e.target.value)}
            />
          </label>
          <label>
            Returns
            <Choice
              label="Function return type"
              value={newFunction.returns}
              disabled={newFunction.returns === "boolean"}
              onChange={(returns) => setNewFunction({ returns })}
              options={VALUE_TYPES.map((value) => ({ value, label: value }))}
            />
          </label>
          <div className="actions">
            <button onClick={() => setNewFunction(null)}>Cancel</button>
            <button
              className="primary"
              onClick={() => {
                const next = addFunction(
                  workflow,
                  functionName,
                  newFunction.returns,
                );
                if (card && ["if", "loop", "call", "poll"].includes(card.kind))
                  next.workflow.graphs[graphId].cards.find(
                    (c) => c.id === card.id,
                  )!.config = { ...card.config, function: next.id };
                commit(next.workflow);
                const f = next.workflow.functions![next.id];
                setBreadcrumbs((old) => [
                  ...old,
                  {
                    graph: graphId,
                    card: selected,
                    name: currentFunction?.[1].name ?? workflow.name,
                  },
                ]);
                setGraphId(f.graph);
                setSelected(null);
                setNewFunction(null);
              }}
            >
              Create and open
            </button>
          </div>
        </Dialog>
      )}
      {runInputs && (
        <RunInputs
          id={id}
          workflow={
            runSelection && runSelection.graph !== "main"
              ? {
                  ...saved.workflow,
                  inputs:
                    Object.values(saved.workflow.functions ?? {}).find(
                      (f) => f.graph === runSelection.graph,
                    )?.inputs ?? {},
                  input_detection: undefined,
                }
              : saved.workflow
          }
          values={runInputs}
          onChange={setRunInputs}
          onClose={() => setRunInputs(null)}
          onRun={() => void start(saved, runInputs)}
        />
      )}
      {currentManual && manualId && (
        <ManualDialog
          key={manualId}
          path={manualId}
          request={currentManual}
          disabled={working}
          onClose={() => setManualId(null)}
          onSubmit={(note, decision) =>
            void act(async () => {
              setState(
                await api<RunState>(
                  "record",
                  { execution: manualId, note, decision },
                  id,
                ),
              );
              setManualId(null);
            })
          }
        />
      )}
      {leave && (
        <Dialog
          title="Leave unsaved changes?"
          onClose={() => {
            leaveTarget.current = null;
            setLeave(false);
          }}
        >
          <p>
            Your saved configuration and reports stay available. This browser
            draft will be discarded.
          </p>
          <button
            onClick={() => {
              leaveTarget.current = null;
              setLeave(false);
            }}
          >
            Keep editing
          </button>
          <button
            onClick={() => {
              const destination = leaveTarget.current ?? onHome;
              leaveTarget.current = null;
              setLeave(false);
              allowNavigation(destination);
            }}
          >
            Discard draft and continue
          </button>
        </Dialog>
      )}
      {confirmDelete && (
        <Dialog title="Delete card?" onClose={() => setConfirmDelete(null)}>
          <p>
            Its owned Body/Catch/Finally branches will also be removed. Undo
            restores this change.
          </p>
          <button onClick={() => setConfirmDelete(null)}>Cancel</button>
          <button
            onClick={() => {
              try {
                if (
                  workflow.layout?.[graphId]?.areas?.some(
                    (a) => a.id === confirmDelete,
                  )
                ) {
                  const next = clone(workflow);
                  next.layout![graphId].areas = next.layout![
                    graphId
                  ].areas!.filter((a) => a.id !== confirmDelete);
                  commit(next);
                } else commit(removeCard(workflow, graphId, confirmDelete));
                setConfirmDelete(null);
                setSelected(null);
              } catch (e) {
                setError((e as Error).message);
                setConfirmDelete(null);
              }
            }}
          >
            Delete card
          </button>
        </Dialog>
      )}
      <footer>
        Local automation ·{" "}
        {currentFunction ? "Function scope" : "Workflow scope"} · Execution
        connections run cards; value connections supply data.
      </footer>
    </div>
  );
}
