# Preview acceptance

Version **0.18.0a3**, schema v3. Verified locally on macOS on 16 October 2026. This is a breaking preview and does not replace the stable installation.

| Check | Result |
|---|---|
| Python unittest | 88 passed |
| Ruff lint and format | Passed |
| mypy source checks | Passed, no untyped definitions |
| Strict TypeScript with unused-code checks | Passed |
| Vitest editor commands, bindings and project paths | 21 passed |
| Playwright Chromium | 16 passed |
| Browser-only ten-step creation, wiring, save/reload/run | Passed |
| Function navigation, manual True/False across runs, Stop | Passed |
| Context actions, undo/redo, layout collapse, mobile List/dropdowns | Passed |
| Desktop/mobile visual review and Impeccable detector | Completed |
| Wheel and source archive build | Passed |
| Clean wheel install outside checkout, no Node/PYTHONPATH | Blank, Python/file, While, Parallel and recovery passed |
| Existing installation and application workflows | Left separate and unchanged |
| Native Windows | Unverified; manual acceptance workflow supplied |

Backend coverage includes zero/count/nested loops, changing Boolean functions, Break/Continue and Finally, limits/unlimited cancellation, isolated function inputs, global resets and parallel conflicts through calls, named Join results, shared external-workspace concurrency and isolated globals, child-source fingerprints, separate Python logs/returns, scripts and programs, file/HTTP failures/timeouts/cancellation, manual evidence, retry filtering, explicit resume and process cleanup. Reports are escaped, report paths restricted, and saves require a local token/revision.

## Practical limits

Commands are trusted local configuration, not sandboxed untrusted code. Bash requires a local Bash installation. POSIX process groups and tracked detached descendants are cleaned up; a process that deliberately escapes and reparents before observation cannot be guaranteed. Environment/service state and undeclared source files are not a reproducibility guarantee: declare source_paths and avoid including generated outputs in source globs. Redacted outputs block resume rather than being reused as real values.

For-each, Switch, Repeat-until, recursion, arbitrary Go To, remote agents, schedules, database connectors and multiplayer editing are outside this initial catalog. Use functions and Python where appropriate. Native Windows support must remain unverified until its acceptance suite actually passes.

## Draft-save regression (0.18.0a2)

Save accepts schema-valid unfinished flowcharts. Validate and Run still perform full execution validation. YAML switching and importing unfinished drafts remain available. Failed validation creates a revision-matched recovery backup without overwriting the saved file; a new editor restores that draft after reload. External revisions are never replaced by a recovery record. Browser tests cover save/reload, blocked execution and old-editor draft recovery.

Open browser sessions retain their protected token across preview restarts. Restart persistence, private token-file permissions, and incorrect-token/origin rejection are covered by backend tests.

Validation diagnostics name the card and its main-workflow/function location. Every semantic issue is selectable, including return-type and invalid Finish placement. Diagnostics appear only after Save or Validate and are hidden when the draft changes; value connections override unused literal defaults. Regression coverage includes identical card IDs across graphs and explicit validation, hidden diagnostics after reload/edit, and corrected outputs passing Save.

Finish and Return expose a Result source picker for constants, Void or named card results. Browser acceptance covers replacing a misplaced Finish with Return, returning Python False from a Boolean function, publishing Calculate output from Finish, and switching to Void without retaining stale results. Function pickers omit Finish. Execution wiring remains separate from data bindings.

Global creation is available from Variable cards through Create / initialize global, which opens and focuses the declaration form. Browser tests verify a numeric global with initial value 0 is saved correctly.

The full-code review and resolved findings are recorded in [the review report](reviews/2026-10-16-code-review.md). The 0.18.0a3 wheel was tested outside the source checkout with Node and PYTHONPATH unavailable. No stable installation or user workflow was migrated.


## 0.18.2 Windows release checks (25 October 2026)

Executed on native Windows with Python 3.14 and Node 24.19.0. Python lint,
formatting and mypy passed; 177 backend tests, 28 frontend unit tests, 34
Playwright Chromium tests, 40 executable documentation examples and both
npm launcher tests passed. Frontend schema/type generation and build passed.
Both documentation base paths built successfully; browser checks verified
local search, downloads, real 404/path boundaries, preserved edits, active
runs and hosted-base routing. Desktop and mobile screenshots were reviewed.

The Windows changes resolve commands using each child's PATH, preserve UTF-8
output, select native Git Bash, and expose report attachment paths with URL
separators. Documentation checks read UTF-8 explicitly and compare reviewed
source hashes after CRLF normalization without changing the review digests.
The documentation browser harness uses Playwright HTTP requests to avoid a
reproducible Node 24 fetch parser assertion with the local fixture server.

These checks used disposable synthetic projects. Existing consumer workflows,
active dashboards, browser sessions and installed runtime pins were not
modified. macOS was not rerun for this patch; prior macOS results above retain
their original scope. This entry records automated Windows acceptance and
visual review, not certification of arbitrary consumer toolchains.
