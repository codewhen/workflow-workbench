# Whole-codebase review — 16 October 2026

## Scope

Reviewed the complete Workflow Workbench checkout at baseline commit `89ac51b`, including staged, unstaged and new files. This covers the Python domain/application/infrastructure/interfaces layers, React editor and Home, public schema and generated types, tests, packaging, CI configuration and documentation. Generated frontend assets are verified by rebuilding their reviewed sources. Consuming application code, private plugins and the stable Workbench installation are outside this review.

The findings below were addressed in the working tree. Changes were made in small batches with regression checks; this review is not a claim of mathematically perfect architecture or native Windows acceptance.

## Findings and fixes

| Priority | Finding | Change and evidence |
|---|---|---|
| High | Nonfinite progress values could enter run state and prevent JSON evidence/report generation. Arbitrary progress keys could also collide with event metadata. | `application/progress.py` validates finite, ordered bounds and keeps only known progress fields before state mutation. Regression runs malformed and valid progress records through a Python card and verifies report completion. |
| High | Declared secrets overridden in a card's environment were absent from the evidence masker. | Evidence composition includes declared secret values from both workflow and card environments. A synthetic-secret test inspects all saved evidence files for leaks. |
| Medium | Binding resolution happened before creating the card's execution record, so some failed runs had no failed-card evidence. | The runtime records the card before resolving inputs/configuration and retains status, result and elapsed evidence on failure. |
| Medium | Shared mutable catalog defaults/configuration could be modified through a compiled card. | Compilation deep-copies defaults and configuration. A mutation regression checks registry and source-document isolation. |
| Medium | Stream decoding could replace Unicode characters split across process reads; ordinary Python prints were buffered. | Per-stream incremental UTF-8 decoding and an unbuffered Python worker. Tests verify complete streamed text and output before process completion without explicit `flush`. |
| Medium | If/Poll could accept resource settings that their structural execution path ignored. Retry/scheduling policy lists were duplicated. | Specification-owned scheduling/retry policies are consumed by both validation and execution. Structural locks are rejected explicitly. |
| Medium | Loop iteration limits accepted fractions, and loop/poll timeout validation allowed invalid values. | Card-specific positive/finite bounds and integral iteration limits, checked by contract tests. |
| Medium | Nested JSON comparison inherited Python's Boolean/number equality while scalar comparison distinguished integer and floating representations of the same JSON number. | Recursive typed JSON equality: `False` differs from `0` at every depth, while `1` equals `1.0`. |
| Medium | Browser state requests overlapped and an old response could overwrite a newly started run. | A dedicated sequential, abortable polling hook discards responses from before direct state replacement. Run, manual prompt, Stop and selected-evidence browser journeys pass. |
| Medium | Python cards ignored their configured working directory, unlike program/script cards. | Python handlers now resolve the configured directory through the same workspace boundary; a nested-directory execution regression verifies the result. |
| Medium | Home's project filter assumed POSIX path separators. Text persistence used host-default encodings. | Tested POSIX/Windows/UNC path filtering and explicit UTF-8 persistence. These are reviewed portability fixes; native Windows remains unverified. |
| Maintainability | Card definitions, executors and tool handlers were grouped in three large modules; several generic executor aliases added no behavior. | Separate modules for all 25 specifications and 25 executors, eight tool handlers, shared abstract bases and explicit registries. Redundant generic file/HTTP aliases were removed. |
| Maintainability | The editor mixed configuration rendering, control rendering, polling and inline data mutations; result-binding/type logic was duplicated. | Extracted card inspector, toolbar, polling hook and tested immutable commands; shared binding readers and result-type helper used by card forms/rendering. |
| Maintainability | Architecture import tests only inspected top-level Python files. | Recursive checks now include nested implementations, plus schema/registry agreement, inheritance and implementation-module contracts. |

## SOLID assessment

- **Single responsibility:** card metadata, execution, external effects, persistence and presentation have distinct locations. The editor remains the integration coordinator, while form rendering, toolbar rendering, state polling and configuration mutation are separate modules.
- **Open/closed:** new operation implementations extend their base classes and explicit registries. Shared scheduling, retry and result-type queries use specification contracts rather than duplicating card lists across unrelated services.
- **Liskov substitution:** concrete executors obey the same asynchronous `Outcome` contract; handlers obey the same injected operation interface. Boolean False, Void and failure retain distinct meanings.
- **Interface segregation:** clock, process execution, evidence, masking and execution-context boundaries remain independent application protocols. JSON dictionaries are retained at serialization/configuration boundaries; runtime values and graph outcomes use typed models.
- **Dependency inversion:** domain code has no effect adapters; application code consumes its own protocols. Local infrastructure is wired at the CLI/server composition boundary. Recursive architecture tests protect this direction.

React uses functional composition rather than forced inheritance. Backend card/tool classes use inherited abstract contracts. One shared card renderer and metadata-driven forms avoid duplicating a complete UI implementation for every card.

## Verification

Completed on the final working tree:

| Check | Result |
|---|---|
| Python unittest | 88 passed |
| Ruff lint and format | Passed with 0.17.1 |
| mypy | Passed across 90 source files with declared dependency version 1.20.2, targeting Python 3.11 |
| Strict TypeScript/build | Passed |
| Vitest | 21 passed |
| Playwright Chromium | 16 passed |
| Wheel and source archive | Built as 0.18.0a3 |
| Clean wheel installation | All 25 specs, 25 executors and eight handlers imported |
| Standalone examples | Blank, Python/file, While, Parallel and recovery passed without source checkout, `PYTHONPATH` or Node |

Local Python execution used 3.14; this does not assert native Python 3.11 or Windows execution. These results cover the complete working tree, including new modules, rather than only the pre-existing staged snapshot. Related source modules, generated assets and version metadata belong in the same commit. A second pre-commit review checked runtime evidence, typed comparisons, value bindings, polling and registry boundaries and found no additional actionable issues.

## Limits and follow-up

- Native Windows execution, signing and interactive desktop/device workflows were not run. Portable path tests do not substitute for native acceptance.
- Commands remain trusted local automation, not a sandbox for untrusted programs. Existing documented process-tree limitations still apply.
- `Editor.tsx` remains the application integration component; further extraction should follow a concrete responsibility or regression risk, not an arbitrary file-length target.
- The workflow schema and stored user workflows were not migrated. Historical reports and the stable installation remain separate. The preview package is a local review artifact, not a newly published stable release.
