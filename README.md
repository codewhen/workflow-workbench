# Workflow Workbench

A free, MIT-licensed local automation workbench. Build flowcharts in the browser, keep them in YAML, execute them with Python, and inspect live output and saved HTML/JSON evidence.

**Stable release 0.18.2 uses workflow schema v3.** Earlier workflow schemas are not converted automatically. Keep their files and historical evidence separate.

## Install and run

Install with npm (Node.js 18+ and Python 3.11+ required):

```bash
npm install -g @codewhen/workbench
workbench create
```

Or run without a global installation:

```bash
npx @codewhen/workbench create
```

For a Python-only installation, download a wheel and its checksum from [GitHub Releases](https://github.com/codewhen/release-workbench/releases). Node is not required for this method. With the chosen wheel copied into your current directory and its SHA-256 verified:

```bash
python3 -m venv .venv-workbench
.venv-workbench/bin/python -m pip install ./release_workbench-0.18.2-py3-none-any.whl
.venv-workbench/bin/workbench create --port 3105
```

On Windows use `.venv-workbench\Scripts\python.exe` and `.venv-workbench\Scripts\workbench.exe`. Native Windows acceptance is **unverified**. Bash cards additionally require Bash on any platform.

Open `http://127.0.0.1:3105/`. Add projects or existing v3 YAML files to Home. Opening a workflow shows Run view; commands execute only after Run all. Change to Edit to configure cards. Saving configuration does not run commands.

Adding or importing a workflow also adds available External workspace dependencies
to the library, recursively. Child YAML paths resolve from the parent workflow's
`workspace` folder, relative to its YAML file, just as they do during execution.
Existing files stay in place; shared dependencies are listed once and cycles do
not repeat imports. Missing, invalid or runtime-resolved child paths are skipped;
re-add the parent after those files become available.

Workflow YAML can declare `library.folder` (for example, `AirDeck/Test`) to
suggest a Home folder when first added. `library.imports` lists additional YAML
paths relative to the execution workspace, so a root workflow can import a whole
project without executing those workflows. Missing folders are created
automatically; re-importing preserves entries already moved to another folder.

## Read the complete manual

Open **Documentation** from Home or the editor to read the bundled manual at
`/docs/` on your running dashboard. It includes offline search, screenshots,
per-card instructions and complete downloadable workflows. The inspector also
links directly to the selected card's guide.

The same Markdown is readable here:

- [Manual home and learning paths](docs/index.md)
- [Install and create a project](docs/user/installation.md)
- [Build your first workflow](docs/user/first-workflow.md)
- [All 25 cards and three layout tools](docs/user/cards/index.md)
- [Start, Finish and Return](docs/user/tutorials/completion.md)
- [Functions](docs/user/tutorials/functions.md), [variables](docs/user/tutorials/variables.md) and [loops](docs/user/tutorials/loops.md)
- [Running, logs and results](docs/user/running.md)
- [Troubleshooting](docs/user/troubleshooting.md)
- [Developer guide](docs/developer/index.md)

For a first operation, create a blank workflow, choose Edit, insert Python between
Start and Finish, set its return type to object and enter:

```python
print("Preparing greeting")
return {"message": "Hello workflow"}
```

Connect Start → Python → Finish. On Finish choose Python under **Result source**,
then Save, Validate & review and Run all. Its log contains Preparing greeting;
its typed result contains the object. The [illustrated walkthrough](docs/user/first-workflow.md)
explains each action.

The same Markdown also builds as a searchable documentation site for GitHub Pages.

## CLI

```bash
workbench                  # Open the dashboard for the current folder
workbench serve            # Same dashboard
workbench run              # Same dashboard; does not execute cards automatically
workbench create           # Wizard: blank YAML here, then open it in the dashboard
workbench create --name "My project" --config my-workflow.yaml
```

`create` asks for a project name and YAML filename, writes a Start → Finish
workflow in the current directory, and opens that workflow. Existing files are
never overwritten. The default shared library is
`~/.workbench-preview-v3`, so projects opened from different terminal folders
appear together. Use `--storage PATH` to keep a separate library. `--port 3105`
and `--no-open` are available for dashboard commands. If a matching dashboard is
already running on that port, the CLI registers the project and reuses it.

Examples live in **Starter**, a separate project under
`<storage>/projects/starter`, and a Starter folder on Home. Startup installs
missing examples without replacing edited examples or writing sample YAML into
your project directory.

Advanced terminal tools remain available:

```bash
workbench init --template python --name "Write a result" # Create an example without serving
workbench validate --config workflow-workbench.yaml
workbench run --config workflow-workbench.yaml --non-interactive --input 'message="Hello"'
workbench report --storage ~/.workbench-preview-v3 --run RUN_ID
workbench run --resume RUN_ID --retry-interrupted --non-interactive
```

`workflow-workbench` and `release-workbench` remain aliases. **`run` opens the UI;
`run --non-interactive` executes YAML in the terminal.** Manual decisions require
the browser. Exit codes: **0** passed; **1** failed; **2** invalid or waiting for
evidence; **130** cancelled. A returned Boolean `false` is successful data.

### npm / npx

Install the [npm launcher](npm/workbench/README.md) globally or use npx:

```bash
npm install -g @codewhen/workbench
workbench
# Or without a global install:
npx @codewhen/workbench
```

Node.js 18+ and Python 3.11+ are required. The launcher bundles the engine wheel,
verifies its checksum and sets up an isolated Python environment on first launch.
See the [installation guide](docs/user/installation.md) for version pinning,
updates, removal and troubleshooting.

For a Python-only tool installation from a downloaded wheel:

```bash
uv tool install ./release_workbench-0.18.2-py3-none-any.whl
workbench
```

See [npm exec documentation](https://docs.npmjs.com/cli/commands/npm-exec/)
and [uv tool installation](https://docs.astral.sh/uv/guides/tools/).

## Build from source

Run this checkout locally with one command (Python 3.11+, Node.js 22+ and npm):

```bash
python3 run_local.py
```

On Windows use `python run_local.py`. The script creates/reuses `.venv`, installs
Python and npm dependencies when their manifests change, builds the frontend and
offline manual, and opens [localhost:3110](http://127.0.0.1:3110/). The first run
needs internet access for dependencies. Local library/run data stays in the
ignored `.workbench/` directory. Stop with Ctrl+C; rerun to rebuild source changes.

To open another project or choose a port:

```bash
python3 run_local.py --project ../air_mouse --port 3111 --no-open
```

For manual setup, development checks, or distribution builds:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'
npm --prefix frontend ci
npm --prefix frontend run build
npm --prefix docs-site ci
npm --prefix docs-site run check
npm --prefix docs-site run build
.venv/bin/python -m unittest discover -v
.venv/bin/python -m build
```

See the testing runbook for Ruff, mypy, Vitest, Playwright and clean-wheel verification. Frontend tools are developer dependencies only; the wheel includes built assets. Seven generic starters cover blank flows, Python returns, While, Parallel/Join, manual decisions, polling and recovery.

## Scope

Round ports carry **execution**. Square ports carry **typed values** and never start a card. Explicit Parallel/Join controls concurrency. Functions isolate inputs and intermediate values; declared globals are shared within one run. Layout areas never change execution scope. Commands, scripts and HTTP requests run with the local user's permissions as trusted local configuration; this is not an untrusted-code sandbox.

No paid services, hosted server, remote agents, schedules or multiplayer editing are required. Repeat-until, For-each, Switch and arbitrary Go To are outside this initial catalog. Use functions, While/Repeat count and Python for those automation cases.
