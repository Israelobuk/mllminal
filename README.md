# MLLminal

MLLminal is a private, local workflow-intelligence system that learns how you work across your computer and turns recurring, approved behavior into safe, inspectable automation.

Mil is the conversational interface. MLLminal observes only approved activity, represents reusable workflows as typed capabilities, keeps actions permission- and approval-controlled, ensures effects are independently verified, and supports recovery or rollback where a provider allows it. Your data and model execution stay local. MLLminal is application-agnostic: it is not an Excel or Outlook automation product.

## Install for Windows

The normal-user installation is intentionally short:

1. Download the Windows installer.
2. Run setup.
3. Open PowerShell in a new terminal.
4. Run mllminal doctor.
5. Start Mil: mllminal mil.

The installer includes the MLLminal daemon, mllminal CLI, Textual TUI, Mil terminal, bundled Python runtime, dependencies, database migrations, Start Menu shortcuts, and uninstall support. Python, uv, Git, a source checkout, and manual environment variables are not required.

The installer uses a per-user location where practical, adds only its own CLI entry to the user PATH, keeps mutable data outside the installation directory, detects existing installations, and supports repair and reinstall. Mil and the TUI start or verify the local daemon when they open. Launch-at-login is optional.

## Start using MLLminal

These are the commands most people need:

~~~text
mllminal                  Open Mil
mllminal chat             Open the same Mil interface
mllminal run              Choose a workflow and run it
mllminal status           Show a concise health summary
mllminal apps             List discovered applications
mllminal workflows       List workflows and recent runs
mllminal approvals       Review pending approvals
mllminal doctor           Diagnose the local installation
mllminal stop             Emergency stop, with confirmation
mllminal start            Re-enable normal operation
mllminal help             Show common commands
~~~

With a TTY, run and approval review support numbered and arrow-key selection. In a non-interactive terminal they print numbered choices and return a stable nonzero exit code when a choice is required. Workflow names, short IDs, and exact IDs are accepted.

Useful aliases are apps for applications, flows for workflows, runs for executions, approve and deny for approval decisions, chat for Mil, and stop for emergency stop. Advanced command trees remain available for scripts and operators.

## What MLLminal can do

MLLminal can help you:

- discover application capabilities on the local computer;
- learn repeatable workflows from explicit demonstrations;
- move structured information between eligible applications;
- organize and transform files inside approved locations;
- generate reports and create drafts without sending them;
- execute bounded multi-application workflows;
- recover after interruptions from durable checkpoints;
- explain what happened, which provider or policy was selected, and why;
- improve provider ranking from verified outcomes through offline learning.

A workflow is proposed before it runs. Permission, approval, eligibility, execution, verification, and audit state remain daemon-owned. Observation can inform a proposal but never has execution authority.

## How it works

~~~text
CLI / Textual / Mil
        ↓
Authenticated local daemon
        ↓
Workflow compiler and safety gates
        ↓
Capability and provider resolution
        ↓
Application, browser, filesystem, and document providers
        ↓
Independent verification and durable checkpoints
        ↓
Offline learning and advisory ranking
~~~

The runtime follows this sequence:

1. Observe approved behavior.
2. Identify a reusable workflow.
3. Propose a typed plan.
4. Request permission and approval.
5. Select an eligible provider.
6. Execute bounded actions.
7. Independently verify the effects.
8. Checkpoint the result and learn only from verified outcomes.

A learned policy may advise ranking or suggestions. It cannot introduce an ineligible action, bypass approval, weaken permissions, suppress verification, retrain online, or promote itself.

## Safety and privacy

MLLminal is local-first. It does not offload MLLminal data or model execution to an MLLminal cloud service. Observation requires explicit consent and stays metadata-oriented.

MLLminal does not capture passwords, credentials, cookies, tokens, private keys, secure fields, clipboard contents, raw typed text, microphone input, camera input, or unrestricted screen content. It does not provide unrestricted shell execution, automatic email sending, automatic form submission, purchasing, or online model training during live execution.

The emergency stop remains authoritative. Deterministic safety filtering occurs before learned ranking. There is no automatic policy promotion. Policies are never automatically promoted. Every consequential effect requires independent verification, and recovery or rollback is used where the selected provider supports it.

## Technology and why it exists

- SQLAlchemy 2 + Alembic provide durable typed database access and safe, versioned schema migrations.
- SQLite stores workflow, policy, approval, execution, checkpoint, profile, and Mil session state locally.
- PyTorch trains offline advisory policies and runs bounded local inference for validated promoted artifacts.
- scikit-learn provides preprocessing, evaluation, calibration, clustering, drift analysis, and lightweight classical ML baselines.
- LangGraph is an optional way to structure Mil reasoning flows; it never becomes the execution authority.
- Ollama + Qwen provide local conversational reasoning and structured plan generation without hosted model calls.
- MLflow records local experiments, candidate comparisons, and policy provenance so promotion decisions are inspectable.
- DuckDB + Parquet make replay datasets and offline analysis efficient without changing authoritative SQLite state.
- FastAPI exposes authenticated daemon contracts, Typer provides the CLI, and Textual provides the keyboard-first TUI.

## Product status

MLLminal is a technical preview. The categories below describe the current boundary honestly.

### Implemented

- Authenticated local daemon with durable SQLite state and Alembic migrations.
- mllminal CLI, Textual TUI, and Mil interactive terminal.
- Typed workflow compilation, permissions, approvals, emergency stop, checkpoints, verification, and recovery paths.
- Bounded filesystem, application, browser-bridge, and manual-handoff capability contracts.
- Metadata-only Windows observation with consent and privacy exclusions.
- Local Ollama/Qwen support plus deterministic fixtures.
- Offline training, evaluation, explicit policy promotion and rollback, provider ranking, suggestion ranking, and decision provenance.
- Per-user Windows install, repair, upgrade migration backups, data-retaining uninstall, and explicit purge command.

### Optional

- Ollama and a local Qwen model for conversational planning.
- Launch-at-login daemon startup.
- Browser bridge and provider-specific adapters when configured and available.
- Local MLflow tracking and DuckDB/Parquet replay analysis.

### Experimental

- Learned advisory ranking in live runtime decisions. Deterministic eligibility and safety checks remain authoritative.
- Windows UI Automation and native observer adapters across unfamiliar applications.
- Provider-specific recovery and rollback where effects can be independently checked.

### Deferred

- Universal compatibility with every desktop application.
- Signed release distribution and clean-machine certification.
- Rich provider-specific document semantics beyond bounded capability contracts.
- Automatic workflow discovery from unrestricted screen or content capture.

### Unsupported

- Credential or secure-field learning.
- Unrestricted shell, PowerShell, CMD, Python, SQL, or arbitrary URL execution.
- Automatic sending, form submission, purchasing, or other external submission.
- Cloud execution or online model training during live execution.

## CLI examples

~~~powershell
mllminal status
mllminal doctor
mllminal mil
mllminal applications discover
mllminal capabilities list
mllminal workflows list
mllminal executions watch <id>
mllminal approvals list
mllminal emergency-stop
mllminal tui
~~~

Human-readable output is the default. Supported projections also accept --json for scripts. The JSON shape remains daemon-owned and stable; use advanced command trees when you need detailed records.

Service and installation commands are available for repair and automation:

~~~powershell
mllminal service start
mllminal service stop
mllminal service restart
mllminal service status
mllminal install status
mllminal install repair
mllminal install data-path
mllminal install purge-data
~~~

## Upgrade, repair, and uninstall

Run a newer installer over an existing installation to upgrade. Before migrations, MLLminal backs up the SQLite database. Upgrades preserve workflows, execution history, checkpoints, application profiles, policy bindings, still-valid approvals, Mil sessions, settings, and learning metadata. Unsafe database downgrades are blocked.

Run the same setup executable again to repair an installation. Repair validates the runtime, dependencies, PATH entry, shortcuts, daemon registration, and migrations without replacing mutable user data.

The normal Windows uninstaller stops MLLminal-owned processes and removes installed binaries, shortcuts, its own PATH entry, startup registration, owned browser-host registration, and orphaned MLLminal processes. It asks whether to keep local MLLminal data or delete MLLminal-owned state.

Uninstall never deletes user-created documents, spreadsheets, PDFs, downloads, reports, or workflow outputs outside MLLminal-owned directories. To remove retained local state separately, use the explicit confirmation command:

~~~powershell
mllminal install purge-data --confirm MLLMINAL
~~~

Purge targets only MLLminal-owned data and backups.

## Developer installation

Developer installation is separate from the normal-user installer and requires Python 3.12 and uv:

~~~powershell
git clone https://github.com/Israelobuk/mllminal.git
cd mllminal
uv sync --all-groups
uv run mllminal doctor
uv run mllminal mil
~~~

The local Qwen provider is optional:

~~~powershell
ollama serve
ollama pull qwen3:4b
uv run mllminal models use qwen
uv run mllminal models status
uv run mllminal models test
~~~

For deterministic fixtures and tests, use uv run mllminal models use deterministic.

## Troubleshooting

- After installation, open a new terminal and run mllminal doctor if a command cannot find the daemon.
- If Qwen is unavailable, start Ollama, confirm the model is installed, or switch to deterministic mode.
- If an upgrade reports an unsafe database revision, restore the latest backup and use a matching installer version. Do not force a downgrade.
- If an adapter is unavailable, inspect mllminal capabilities list and mllminal diagnostics collect --json; unsupported applications degrade to bounded discovery or manual handoff.
- Use mllminal emergency-stop whenever an execution must halt immediately.
- The Start Menu Diagnostics shortcut runs a bounded diagnostic projection without requiring a manually opened shell.

## Project status and limitations

MLLminal is a technical preview, not a production-certified automation platform. It is not certified on every Windows build or clean machine, the installer is not yet code-signed, and application compatibility is not universal. Real Office-specific verification is not claimed; Excel and Outlook may require provider-specific capability work. Review every proposed plan and consequential effect.

Deeper engineering details, design records, and acceptance evidence live under [docs/](docs/). The root README stays focused on the product, its boundaries, and how to use it safely.
