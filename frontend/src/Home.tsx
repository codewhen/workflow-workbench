import { navigate, useLocation } from "./navigation/location";
import { LibraryBrowser } from "./home/LibraryBrowser";
import {
  folderName as leafName,
  parentFolder,
  withinFolder,
} from "./home/folders";
import { useEffect, useRef, useState } from "react";
import { Folder, Plus, Upload, GitBranch } from "lucide-react";
import { api } from "./shared/api";
import type { Catalog, Library, LibraryEntry } from "./shared/types";
import { Choice } from "./components/Choice";
import { Dialog } from "./components/Dialog";
import { ContextMenu, type MenuState } from "./editor/ContextMenu";
export function Home({
  catalog,
  onOpen,
}: {
  catalog: Catalog;
  onOpen: (id: string) => void;
}) {
  const [library, setLibrary] = useState<Library>({
      projects: [],
      folders: [],
      entries: [],
    }),
    [error, setError] = useState(""),
    [create, setCreate] = useState(false),
    [register, setRegister] = useState(false),
    [path, setPath] = useState(""),
    [name, setName] = useState("My workflow"),
    [filename, setFilename] = useState("workflow-workbench.yaml"),
    [template, setTemplate] = useState("blank"),
    [newProject, setNewProject] = useState(""),
    [menu, setMenu] = useState<MenuState | null>(null),
    [organize, setOrganize] = useState<{
      action: string;
      id?: string;
      old?: string;
      parent?: string;
    } | null>(null),
    [folderName, setFolderName] = useState(""),
    [folderParent, setFolderParent] = useState(""),
    [importFile, setImportFile] = useState<{
      filename: string;
      yaml: string;
    } | null>(null),
    [removal, setRemoval] = useState<{
      id?: string;
      project?: string;
      name: string;
    } | null>(null),
    [working, setWorking] = useState(false),
    [pickingFolder, setPickingFolder] = useState(false);
  const { folder, project, query } = useLocation();
  const setFolder = (folder: string) => navigate({ folder });
  const setProject = (project: string) => navigate({ project });
  const setQuery = (query: string) => navigate({ query }, true);
  const input = useRef<HTMLInputElement>(null);
  const [history, setHistory] = useState<
    { run_id: string; name: string; status: string }[]
  >([]);
  useEffect(() => {
    api<typeof history>("history")
      .then(setHistory)
      .catch(() => {});
  }, []);
  const load = () =>
    api<Library>("library")
      .then((value) => {
        setLibrary(value);
        setNewProject((old) => old || value.projects[0] || "");
      })
      .catch((e) => setError(String(e.message)));
  useEffect(() => {
    void load();
  }, []);
  async function act(task: () => Promise<void>) {
    setWorking(true);
    setError("");
    try {
      await task();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setWorking(false);
    }
  }
  return (
    <main className="home">
      <header className="home-header">
        <div className="brand">
          <GitBranch size={28} />
          <div>
            <h1>Workflow Workbench</h1>
            <p>Build a flowchart. Automate the work.</p>
          </div>
        </div>
      </header>
      <div className="home-title">
        <div>
          <h2>Your workflows</h2>
          <p>
            Local automation across your projects. Opening a workflow does not
            run it.
          </p>
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
          <button
            disabled={working}
            onClick={() =>
              void act(async () => {
                const selected = await api<{ path: string | null }>(
                  "pick-file",
                  {},
                );
                if (!selected.path) return;
                const entry = await api<LibraryEntry>("register", {
                  path: selected.path,
                });
                onOpen(entry.id);
              })
            }
          >
            <Upload size={17} />
            Open YAML
          </button>
          <button onClick={() => input.current?.click()}>
            <Upload size={17} />
            Import a copy
          </button>
          <button onClick={() => setRegister(!register)}>
            Add project or file
          </button>
          <button className="primary" onClick={() => setCreate(!create)}>
            <Plus size={17} />
            New workflow
          </button>
        </div>
      </div>
      <input
        ref={input}
        type="file"
        accept=".yaml,.yml"
        hidden
        aria-label="Workflow YAML file"
        onChange={(e) => {
          const file = e.target.files?.[0];
          if (file)
            void file
              .text()
              .then((yaml) => setImportFile({ filename: file.name, yaml }));
          e.currentTarget.value = "";
        }}
      />
      {error && (
        <p className="alert error" role="alert">
          {error}
        </p>
      )}
      {register && (
        <form
          className="inline-form"
          onSubmit={(e) => {
            e.preventDefault();
            void act(async () => {
              const result = await api<LibraryEntry | Library>("register", {
                path,
              });
              if ("id" in result) onOpen(result.id);
              else setLibrary(result);
              setRegister(false);
            });
          }}
        >
          <h3>Add an existing project or workflow</h3>
          <button
            type="button"
            disabled={working || pickingFolder}
            onClick={() => {
              setPickingFolder(true);
              setError("");
              void api<{ path: string | null }>("pick-folder", {})
                .then((result) => {
                  if (result.path) setPath(result.path);
                })
                .catch((e) =>
                  setError(e instanceof Error ? e.message : String(e)),
                )
                .finally(() => setPickingFolder(false));
            }}
          >
            <Folder size={17} />
            {pickingFolder ? "Folder picker open…" : "Choose project folder…"}
          </button>
          <p role="status">
            {pickingFolder
              ? "Choose a folder or cancel in the system window on the computer running Workbench."
              : "Choose a folder on this computer, or enter an absolute path below."}
          </p>
          <label>
            Absolute folder or YAML path
            <input
              value={path}
              onChange={(e) => setPath(e.target.value)}
              required
            />
          </label>
          <button disabled={working || pickingFolder} className="primary">
            Add to library
          </button>
        </form>
      )}
      {create && (
        <form
          className="inline-form"
          onSubmit={(e) => {
            e.preventDefault();
            void act(async () => {
              const entry = await api<LibraryEntry>("create", {
                name,
                filename,
                project: newProject,
                template,
              });
              if (folder && folder !== "*")
                await api("organize", { action: "move", folder }, entry.id);
              onOpen(entry.id);
            });
          }}
        >
          <h3>New workflow</h3>
          <div className="form-grid">
            <label>
              Name
              <input
                value={name}
                onChange={(e) => setName(e.target.value)}
                required
              />
            </label>
            <label>
              Filename
              <input
                value={filename}
                onChange={(e) => setFilename(e.target.value)}
                required
              />
            </label>
            <label>
              Project folder
              <input
                value={newProject}
                onChange={(e) => setNewProject(e.target.value)}
                required
              />
            </label>
            <label>
              Starter
              <Choice
                label="Starter"
                value={template}
                onChange={setTemplate}
                options={Object.entries(catalog.templates).map(
                  ([value, label]) => ({ value, label }),
                )}
              />
            </label>
          </div>
          <button
            disabled={
              working || !name.trim() || !filename.trim() || !newProject.trim()
            }
            className="primary"
          >
            Create workflow
          </button>
        </form>
      )}
      <LibraryBrowser
        library={library}
        folder={folder}
        project={project}
        query={query}
        onFolder={setFolder}
        onProject={setProject}
        onQuery={setQuery}
        onOpen={onOpen}
        onMenu={setMenu}
        onRefresh={() => void load()}
        onCreate={() => setCreate(true)}
        onRemoveProject={() => setRemoval({ project, name: project })}
        onNewFolder={(parent) => {
          setFolderName("");
          setFolderParent(parent);
          setOrganize({ action: "new_folder", parent });
        }}
      />
      {removal && (
        <Dialog
          title={
            removal.project
              ? "Remove project from Home?"
              : "Remove workflow from Home?"
          }
          onClose={() => {
            if (!working) setRemoval(null);
          }}
        >
          <p className="path">{removal.name}</p>
          <p>
            {removal.project
              ? "This removes the project and its workflow entries from Home."
              : "This removes the workflow entry from Home."}{" "}
            Files on disk, saved drafts and previous run reports are kept. You
            can add them again using Add project or file.
          </p>
          {error && (
            <p role="alert" className="error">
              {error}
            </p>
          )}
          <div className="actions">
            <button disabled={working} onClick={() => setRemoval(null)}>
              Cancel
            </button>
            <button
              disabled={working}
              onClick={() =>
                void act(async () => {
                  const value = await api<Library>(
                    "remove",
                    { project: removal.project },
                    removal.id,
                  );
                  setLibrary(value);
                  if (removal.project) {
                    setProject("*");
                    setNewProject(value.projects[0] || "");
                  }
                  setRemoval(null);
                })
              }
            >
              {working ? "Removing…" : "Remove from Home"}
            </button>
          </div>
        </Dialog>
      )}
      {importFile && (
        <Dialog title="Import a YAML copy" onClose={() => setImportFile(null)}>
          {error && (
            <p role="alert" className="error">
              {error}
            </p>
          )}
          <p>
            Choose where to save this copy. For workflows with relative child
            paths, use Open YAML to keep the original project location and
            import its dependencies. Existing files are never overwritten.
          </p>
          <label>
            Filename
            <input
              value={importFile.filename}
              onChange={(e) =>
                setImportFile({ ...importFile, filename: e.target.value })
              }
            />
          </label>
          <label>
            Project folder
            <input
              value={newProject}
              onChange={(e) => setNewProject(e.target.value)}
            />
          </label>
          <div className="actions">
            <button onClick={() => setImportFile(null)}>Cancel</button>
            <button
              className="primary"
              disabled={working}
              onClick={() =>
                void act(async () => {
                  const entry = await api<LibraryEntry>("import", {
                    ...importFile,
                    project: newProject,
                  });
                  if (folder && folder !== "*")
                    await api("organize", { action: "move", folder }, entry.id);
                  onOpen(entry.id);
                })
              }
            >
              Validate and open
            </button>
          </div>
        </Dialog>
      )}
      {menu && (
        <ContextMenu
          menu={menu}
          items={
            menu.kind === "area"
              ? [
                  { id: "new_subfolder", label: "New subfolder" },
                  { id: "rename_folder", label: "Rename folder" },
                  { id: "move_folder", label: "Move folder" },
                  {
                    id: "remove_folder",
                    label: "Remove folder",
                    description: "Keep workflows in the parent folder",
                  },
                ]
              : [
                  { id: "move", label: "Move to folder" },
                  {
                    id: "remove_entry",
                    label: "Remove from Home",
                    description: "Keep the YAML file and reports on disk",
                  },
                ]
          }
          onClose={() => setMenu(null)}
          onChoose={(action) => {
            if (action === "remove_entry") {
              const entry = library.entries.find((item) => item.id === menu.id);
              if (entry) setRemoval({ id: entry.id, name: entry.name });
              setMenu(null);
              return;
            }
            const selected = menu.id ?? "";
            const parent =
              action === "new_subfolder" ? selected : parentFolder(selected);
            setFolderParent(parent);
            setOrganize({
              action: action === "new_subfolder" ? "new_folder" : action,
              id: selected,
              old: selected,
              parent,
            });
            setFolderName(action === "rename_folder" ? leafName(selected) : "");
            setMenu(null);
          }}
        />
      )}
      {organize && (
        <Dialog
          title={organize.action.replaceAll("_", " ")}
          onClose={() => setOrganize(null)}
        >
          {error && (
            <p role="alert" className="error">
              {error}
            </p>
          )}
          {organize.action === "move" || organize.action === "move_folder" ? (
            <label>
              Folder
              <Choice
                label="Move to folder"
                value={
                  organize.action === "move_folder" ? folderParent : folderName
                }
                onChange={
                  organize.action === "move_folder"
                    ? setFolderParent
                    : setFolderName
                }
                options={[
                  { value: "", label: "My workspace" },
                  ...library.folders
                    .filter(
                      (path) =>
                        organize.action !== "move_folder" ||
                        !withinFolder(path, organize.old ?? ""),
                    )
                    .map((value) => ({ value, label: value })),
                ]}
              />
            </label>
          ) : organize.action === "remove_folder" ? (
            <p>
              This removes this folder and its subfolders from the library.
              Their workflows stay in the parent folder. Files on disk are kept.
            </p>
          ) : (
            <label>
              Folder name
              <input
                value={folderName}
                onChange={(e) => setFolderName(e.target.value)}
              />
            </label>
          )}
          {organize.action === "new_folder" && (
            <label>
              Parent folder
              <Choice
                label="Parent folder"
                value={folderParent}
                onChange={setFolderParent}
                options={[
                  { value: "", label: "My workspace" },
                  ...library.folders.map((value) => ({ value, label: value })),
                ]}
              />
            </label>
          )}
          <div className="actions">
            <button onClick={() => setOrganize(null)}>Cancel</button>
            <button
              disabled={working}
              onClick={() =>
                void act(async () => {
                  const result = await api<Library>(
                    "organize",
                    {
                      action: organize.action,
                      old: organize.old,
                      name:
                        organize.action === "remove_folder"
                          ? organize.old
                          : folderName,
                      folder: folderName,
                      parent: folderParent,
                    },
                    organize.id,
                  );
                  setLibrary(result);
                  if (
                    organize.action === "rename_folder" &&
                    organize.old &&
                    withinFolder(folder, organize.old)
                  ) {
                    const renamed =
                      (parentFolder(organize.old)
                        ? parentFolder(organize.old) + "/"
                        : "") + folderName.trim();
                    setFolder(renamed + folder.slice(organize.old.length));
                  } else if (
                    organize.action === "move_folder" &&
                    organize.old &&
                    withinFolder(folder, organize.old)
                  ) {
                    const moved =
                      (folderParent ? folderParent + "/" : "") +
                      leafName(organize.old);
                    setFolder(moved + folder.slice(organize.old.length));
                  } else if (
                    organize.action === "remove_folder" &&
                    organize.old &&
                    withinFolder(folder, organize.old)
                  )
                    setFolder(parentFolder(organize.old));
                  setOrganize(null);
                })
              }
            >
              Save
            </button>
          </div>
        </Dialog>
      )}
      {history.length > 0 && (
        <details>
          <summary>Previous preview runs ({history.length})</summary>
          {history.slice(0, 30).map((run) => (
            <p key={run.run_id}>
              <a
                href={`/reports/${run.run_id}/report.html`}
                target="_blank"
                rel="noreferrer"
              >
                {run.name}
              </a>{" "}
              · {run.status} · <small>{run.run_id}</small>
            </p>
          ))}
        </details>
      )}
      <footer>
        Local execution · MIT licensed · Preview workflows and evidence use
        separate storage.
      </footer>
    </main>
  );
}
