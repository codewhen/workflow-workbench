# Keep project integrations reusable

Workbench orchestrates trusted local automation. Its runtime does not know what a device serial, IP address, build artifact or store submission means. A project combines the generic mechanisms below with its own scripts and workflows.

## Responsibility boundary

| Capability | Workbench owns | Consuming project owns |
|---|---|---|
| Required setup | Typed `inputs`, defaults and browser Run inputs | Names, descriptions, nonempty/address/device validation |
| Automatic discovery | `input_detection` command invocation, timeout, candidate validation and choice UI | Read-only detection script, platform tools and discovery rules |
| Execution directory | Relative `workspace`, bounded built-in paths and card `cwd` | Repository layout and workflow locations |
| Commands | Python/Bash/Script/Program execution and typed results | Tool installation, command arguments, build/test/install behavior |
| Python interpreter | `runtime:python` selects the running engine | Separate environments and dependencies needed by project scripts |
| Reusable workflows | External workspace calls, explicit inputs/results and shared coordinator | Child YAML files, prerequisites and meaningful card names |
| Resource scheduling | Named locks, shared concurrency, interactive desktop lock, exclusive operations | Consistent resource names and cross-process locks for other tools |
| Progress | Structured `::workbench::` records and visible evidence | Stage names, done/total values and concise operation summaries |
| Reports | `report_paths`, confined live links and bounded saved text attachments | Report generation, interpretation and artifact retention |
| Approval | Repeated manual prompts and noninteractive blocking | Instructions and decisions; Workbench does not certify a release |

The `desktop` resource is a general interactive-session convention, not a project-specific dependency. Locks coordinate operations sharing a run's coordinator, including nested workflows. Separate CLI/server processes do not share that in-memory coordinator: use project/tool-owned cross-process locks when needed. One server currently accepts one top-level active workflow at a time; use Parallel/Join inside it for concurrent work.

## A reusable integration recipe

1. Put workflow YAML and adapters in the consuming repository. Register its folders explicitly; opening the dashboard must not start commands.
2. Declare inputs and validate application constraints before side effects. Keep discovery optional and read-only.
3. Run an adapter with Program or Script. Use literal argument arrays and serialized stdin, not concatenated shell source. Return concise JSON on stdout and diagnostic logs on stderr when capturing JSON.
4. Emit measured progress where meaningful. Attach reports explicitly. Large logs stream to evidence; bounded returned text is not the entire report.
5. Compose reusable child workflows with explicit arguments. Collect each child's typed result and saved evidence.
6. Protect physical devices or interactive sessions with named resources, and request human evidence when preparation or approval is required.

See the [input/discovery tutorial](../user/inputs.md), [settings](../user/settings.md), [Program](../user/cards/program.md) and [External workspace](../user/cards/workspace.md) contracts.

## Distribution boundary

Only generic Starters and synthetic manual examples belong in the public package. A project's workflows, real logs, credentials, identifiers and private plugins stay in that project. Downloadable documentation examples are teaching fixtures; they are not additional personal dashboard registrations. Fresh storage creates the generic Starter project, then registers workflows in the explicitly selected folder.

`tools/verify_distribution.py` checks wheel, source and npm archives, including the wheel nested inside npm. Its consumer-data path exclusions and checks for stray root `full.yaml` and `release-workbench.yaml` files are regression guards against accidentally bundling a consumer, not runtime dependencies or built-in integrations. The guard is a targeted check, not a proof that arbitrary new secrets or private filenames can never be packaged; review release contents too.

Commands and discovery are trusted local configuration with the user's permissions. Bounded file/report paths do not sandbox arbitrary Python, Bash or executables. Workbench currently provides no hosted agents, built-in SSH credentials manager, schedules or database connectors. A Program card may invoke an installed tool for those tasks. Native Windows acceptance remains unverified.
