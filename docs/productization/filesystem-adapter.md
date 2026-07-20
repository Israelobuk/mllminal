# Real filesystem and File Explorer adapter

Milestone 4 provides bounded local filesystem capabilities under approved roots. Every request is normalized and confined before use; symlinks and Windows junctions are rejected so a path cannot escape an approved root.

## Capabilities

The adapter exposes `filesystem.list`, `inspect`, `find_latest`, `exists`, `hash`, `create_folder`, `rename`, `copy`, `move`, `delete_to_recycle_bin`, and `restore`, plus `explorer.open_folder` and `explorer.select_file`. Read operations return structured metadata. Mutations default to preview and require the existing workflow authorization, action approval, and `filesystem.write` grant before execution.

Preview results include the resolved source/destination, collision policy, and `mutation_performed: false`. The default collision policy rejects an existing destination; `unique` can select a numbered destination without overwriting. Permanent deletion is not exposed: Windows deletion uses the Recycle Bin, with a bounded local rollback backup and token for restoration.

Each execution is persisted by the application bridge idempotency store and appended to a local audit JSONL file. Rename, move, copy, folder creation, Recycle Bin deletion, and restore operations emit rollback metadata. Independent verification checks the resulting filesystem state rather than trusting model output.

## Real acceptance

On a real Windows desktop, configure an approved test root containing a non-sensitive spreadsheet. Preview and approve a workflow that finds the newest workbook, renames it using a date variable, moves it to an approved Reports\Weekly folder, verifies destination existence and source absence, then restores it with the rollback token. Repeat the execution request with the same idempotency key after a daemon restart and confirm no duplicate mutation occurs. File Explorer open/select commands are Windows-only.

CI exercises the provider-neutral contracts and injected adapter boundaries. Manual acceptance remains required for Windows Recycle Bin behavior, junction rejection, Explorer selection, and daemon restart persistence.
