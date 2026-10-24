# Install and create a project

## Install with npm

Prerequisites: **Node.js 18+**, npm and **Python 3.11+** on the computer running Workbench. The npm package supplies the `workbench` executable; Python runs the workflow engine.

Install globally so you can use Workbench from any project folder:

```bash
npm install -g @codewhen/workbench
workbench --version
workbench
```

Open a terminal in your project directory before running `workbench`. It opens the dashboard and registers that directory. To create a blank workflow YAML in the current folder:

```bash
workbench create
```

The package name is `@codewhen/workbench`; the installed command is `workbench`.

## Run with npx

Use npx when you do not want a global installation:

```bash
npx @codewhen/workbench
```

Pass Workbench commands after the package name:

```bash
npx @codewhen/workbench serve
npx @codewhen/workbench run
npx @codewhen/workbench create
npx @codewhen/workbench --version
```

The first invocation may ask permission to download the npm package. `serve`, `run` without `--non-interactive`, and no subcommand all open the dashboard; they do not execute workflow cards automatically. `create` starts the project wizard.

To deliberately execute a saved workflow in the terminal:

```bash
npx @codewhen/workbench run --non-interactive --config checks.yaml
```

## Versions, updates and removal

The commands above install the stable `latest` release. To install version 0.18.1 exactly:

```bash
npm install -g @codewhen/workbench@0.18.1
npx @codewhen/workbench@0.18.1 serve
```

Unversioned npm and npx commands select `latest`. Pin an exact version when you need reproducible installations.

Update a global installation to the current stable version, or remove it:

```bash
npm install -g @codewhen/workbench
npm uninstall -g @codewhen/workbench
```

Uninstalling the npm package does not intentionally delete project YAML or library/run storage. The isolated Python runtime cache is separate; do not remove it while a dashboard is running.

## First-launch Python setup

The launcher verifies its bundled wheel, creates an isolated Python environment under `~/.cache/codewhen-workbench/`, and installs its Python dependencies. It does not replace global Python packages. Network access is needed for initial setup; subsequent launches reuse the environment. The installed manual and local search work offline.

If Python discovery chooses the wrong interpreter, set `WORKBENCH_PYTHON` to the full Python executable path in your shell before launching. Check `python3 --version` or `python --version`; the selected interpreter must be at least 3.11. Native Windows acceptance remains unverified.

## If registry installation fails

- **ETARGET / No matching version found:** the requested version or distribution tag cannot be resolved. Check the available versions and tags with the command below, and confirm your npm registry with `npm config get registry`.
- **E404:** the package is not available to your account in the selected registry, or the package/scope name is wrong.
- **workbench: command not found after global install:** check `npm prefix -g` and ensure npm's global executable directory is on PATH, then reopen your terminal. You can use npx instead.

List available releases and distribution tags:

```bash
npm view @codewhen/workbench dist-tags versions --json
```

You do not need to run `npm login` to install this public package. Maintainers can find release procedures in [Packaging and release](../developer/packaging.md).

## Install the Python package

Use Python 3.11 or newer. Download the actual wheel artifact for the version you intend to install and verify its published SHA-256 when available. The following assumes that wheel is in your current directory; replace its version with your downloaded artifact.

```bash
python3 -m venv .venv-workbench
.venv-workbench/bin/python -m pip install ./release_workbench-0.18.1-py3-none-any.whl
.venv-workbench/bin/workbench --version
```

On Windows, use `python` if that is your Python command, and the corresponding `.venv-workbench\Scripts\python.exe` and `.venv-workbench\Scripts\workbench.exe`. Native Windows execution remains unverified. Activate the environment, use its explicit executable path, or install the wheel with a Python tool manager to expose `workbench` on PATH.

## Create a blank project here

1. Make a dedicated folder for your workflow and scripts.
2. Open a terminal in that folder and run `workbench create`.
3. Enter a project name and YAML filename, or accept `workflow-workbench.yaml`.
4. The wizard creates a blank Start → Finish workflow in the current directory and opens it in the dashboard.
5. Existing files are never overwritten. Choose another filename if the default already exists.

```bash
mkdir workflow-demo
cd workflow-demo
workbench create
# Or skip wizard questions:
workbench create --name "Workflow demo" --config demo.yaml
```

![A blank project open in Workbench before adding operations](../assets/screenshots/project-create.png)

*The project wizard opens the real blank workflow. It does not run any card.*

## Open an existing project

```bash
workbench
workbench serve
workbench run
```

All three open the dashboard for the current directory. `run` without `--non-interactive` does not execute YAML automatically. A matching dashboard on the chosen port is reused and the project is registered there. A different library occupying that port requires another port.

```bash
workbench serve --port 3105
workbench serve --storage ~/Documents/WorkbenchLibrary --no-open
```

Default port is 3104; use the URL printed by your command rather than assuming the development dashboard's port. Default storage is `~/.workbench-preview-v3`. Stop the serving terminal with Ctrl+C; active work is cancelled and the server waits briefly for cleanup. A second CLI invocation that only reuses the server exits without stopping the original server.

Next: [your first workflow](first-workflow.md), [Home and projects](projects.md), or [CLI reference](cli.md).
