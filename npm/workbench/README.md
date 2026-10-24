# Workflow Workbench

A free, MIT-licensed visual automation workbench. Build workflows in your browser, save them as YAML, and inspect live logs, typed results and run reports. Everything runs locally; no hosted service or subscription is required.

## Requirements

- **Node.js 18+** and npm (which includes npx).
- **Python 3.11+**, available on PATH. Python runs the bundled workflow engine.
- Internet access for the first installation and Python dependency setup.
- Bash installed separately if your workflow uses Bash cards.

Native Windows acceptance remains unverified.

## Install globally with npm

```bash
npm install -g @codewhen/workbench
workbench --version
workbench
```

Run `workbench` from your project directory. It opens the local dashboard and registers that folder. The package is named `@codewhen/workbench`; the command is `workbench`.

Create your first workflow in the current directory:

```bash
mkdir workflow-demo
cd workflow-demo
workbench create
```

The wizard asks for a project name and YAML filename, creates a blank Start → Finish flowchart and opens it in the dashboard. Existing files are never overwritten.

## Run with npx

Use npx without installing a global command:

```bash
npx @codewhen/workbench
```

Pass commands and options after the package name:

```bash
npx @codewhen/workbench serve
npx @codewhen/workbench create
npx @codewhen/workbench --version
```

The first invocation may ask permission to download the package. No subcommand, `serve`, and `run` all open the dashboard. They do not execute workflow cards automatically.

To execute a saved workflow directly in the terminal:

```bash
npx @codewhen/workbench run --non-interactive --config checks.yaml
```

## Common commands

```bash
workbench                          # Open or reuse the local dashboard
workbench serve --port 3105         # Choose a dashboard port
workbench run                       # Open the dashboard
workbench create                    # Create a workflow in this directory
workbench validate --config checks.yaml
workbench run --non-interactive --config checks.yaml
```

The default dashboard port is 3104. Follow the URL printed in your terminal. Use Ctrl+C in the serving terminal to stop the server and cancel active work. Manual decisions require the browser.

## Versions, updates and removal

An untagged package name installs the stable `latest` release. To pin version 0.18.2:

```bash
npm install -g @codewhen/workbench@0.18.2
npx @codewhen/workbench@0.18.2 serve
```

Update to the current stable release or uninstall the global command:

```bash
npm install -g @codewhen/workbench
npm uninstall -g @codewhen/workbench
```

Uninstalling the npm command leaves your project files and Workbench library/run storage in place.

## First-launch setup

The launcher verifies its bundled wheel SHA-256, creates an isolated Python environment under `~/.cache/codewhen-workbench/<wheel checksum>/`, and installs the engine and its Python dependencies. Later launches reuse that environment. Global Python packages are not changed, and there is no npm install/postinstall script.

Set `WORKBENCH_PYTHON` to a Python executable's full path if you need to choose a specific interpreter. Updating the bundled engine creates a separate runtime cache. Do not delete a runtime while its dashboard is running.

Workflow commands run with your local user's permissions. Only run configurations you trust. The bundled manual and search are available offline at **Documentation** in the dashboard after setup.

## Troubleshooting installation

- **ETARGET:** check available versions and tags, then select the intended release.
- **E404:** confirm the package name and npm registry with `npm config get registry`.
- **Python not found:** install Python 3.11+ or set `WORKBENCH_PYTHON`.
- **workbench: command not found:** check `npm prefix -g` and add npm's global executable directory to PATH, reopen your terminal, or use npx.

```bash
npm view @codewhen/workbench dist-tags versions --json
```

## Documentation and source

- [Installation and first project](https://github.com/codewhen/release-workbench/blob/main/docs/user/installation.md)
- [Complete user manual](https://github.com/codewhen/release-workbench/blob/main/docs/index.md)
- [Packaging and contributor instructions](https://github.com/codewhen/release-workbench/blob/main/docs/developer/packaging.md)
- [Source code and issues](https://github.com/codewhen/release-workbench)

You can also open **Documentation** from Home or the editor without leaving your workflow.
