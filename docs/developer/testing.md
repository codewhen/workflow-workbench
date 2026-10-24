# Test and preview release runbook

## Development setup

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'
npm --prefix frontend ci
npx --prefix frontend playwright install chromium
```

Use equivalent `.venv\Scripts\` executable paths on Windows. Those commands are reviewed instructions; native Windows acceptance remains unverified.

## Required checks

```bash
.venv/bin/python -m unittest discover -v
.venv/bin/ruff check src tests
.venv/bin/ruff format --check src tests
.venv/bin/mypy src
npm --prefix frontend run typecheck
npm --prefix frontend test
npm --prefix frontend run build
npm --prefix docs-site ci
npm --prefix docs-site run check
npm --prefix docs-site run examples
npm --prefix docs-site run build
npm --prefix docs-site run build:pages
npm --prefix docs-site run test:browser
PATH="$PWD/.venv/bin:$PATH" npm --prefix frontend run test:browser
```

Playwright's disposable fixture server binds localhost:3115 and stores its projects/evidence in a temporary folder. It never opens an application or uses devices. Its Python runtime must have the package dependencies installed (`PATH` selects that environment). Browser reports are under frontend/playwright-report; retained failure traces under frontend/test-results. Neither belongs in source control.

Python tests cover contracts, compiler rejection, Boolean returns, loop bounds, nested control flow, globals, functions, parallel conflicts/scheduling, input serialization, I/O/HTTP, retries, manual prompts, cancellation, process-tree cleanup, protected saves, evidence masking and report boundaries. Vitest covers immutable graph commands and metadata separation. Playwright builds ten cards entirely through the UI, edits functions, records evidence, stops polling and verifies responsive List/custom-dropdown behavior.

## Build and independently verify the wheel

```bash
.venv/bin/python -m build
python3 -m venv /tmp/workbench-wheel-check
/tmp/workbench-wheel-check/bin/python -m pip install ./dist/release_workbench-0.18.2-py3-none-any.whl
mkdir /tmp/workbench-wheel-project
cd /tmp/workbench-wheel-project
/tmp/workbench-wheel-check/bin/workflow-workbench init --template python --name "Installed wheel"
/tmp/workbench-wheel-check/bin/workflow-workbench validate
/tmp/workbench-wheel-check/bin/workflow-workbench run --non-interactive
```

Run from outside the source checkout with PYTHONPATH unset. Verify output/result.json, report.html, bundled UI assets and schema availability. Also test While, Parallel and recovery starters. The installed wheel does not need Node. Build the frontend and `npm --prefix docs-site run build` before packaging; stale assets are a release blocker.

## Publish a release

1. Run all required checks, inspect desktop and mobile once, and record concrete results in acceptance.md.
2. Confirm only generic code, synthetic tests, examples and documentation are tracked. Never add run evidence, credentials or project-specific workflows.
3. Confirm package and __version__ agree on the release version, then build wheel/source archive and SHA256SUMS.
4. Commit the tested source and publish the release with those assets. Create a Git tag only with explicit user authorization. Mark stable releases as latest; mark preview releases as prereleases. Preserve historical evidence.
5. Use disposable library/storage for release verification. Do not change existing projects, active dashboards or consumer pins as a side effect of publishing.
6. Native Windows tests must pass before removing the unverified label. Do not imply production certification from macOS results.

## Native Windows process verification

Workbench inherits the launcher environment; `runtime:python` selects the
running Workbench Python (including npm-managed installations). It does not
install or guess application-specific Java, Go, Flutter or compiler toolchains.
Configure those in the launching terminal or workflow environment.

The process adapter resolves Windows commands against the child workflow PATH,
normalizes case-insensitive environment overrides, and defaults Python output
to unbuffered UTF-8. Explicit Python environment settings are preserved. Bash
script cards select native Git Bash instead of the Windows/WSL launcher and
pass script paths with forward slashes. Explicit executable paths remain
authoritative. No shell command string is constructed from program arguments.

Run `python -m unittest tests.test_process_host -v` on Windows for real
child-PATH, batch-wrapper, Git Bash, spaces and Unicode checks. The full Python
suite also runs on Windows; symlink-specific checks explicitly skip when the
account lacks symlink privilege. Native macOS, browser, signing and application
toolchain acceptance are separate checks.
