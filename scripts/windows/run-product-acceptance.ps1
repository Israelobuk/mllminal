param(
    [string]$Label = "Weekly report acceptance"
)

$ErrorActionPreference = "Stop"
if ($env:OS -ne "Windows_NT") { throw "This acceptance runbook must execute on Windows." }

mllminal system hardware
mllminal acceptance start

Write-Output ""
Write-Output "Manual acceptance sequence (nothing below sends email automatically):"
@(
    "1. Enable observation explicitly: mllminal observe enable",
    "2. Start the demonstration: mllminal demonstrate start `"$Label`"",
    "3. In File Explorer, select a non-sensitive test workbook and perform the weekly report routine.",
    "4. Stop and review the inactive candidate; label source file, reporting date, destination folder, and draft recipient.",
    "5. Compile three mined demonstrations and review the typed workflow draft.",
    "6. Run workflow preview; approve only after permissions, rollback, and verification are visible.",
    "7. Execute filesystem find/rename/move with the approved root and verify source absence/destination existence.",
    "8. Open the workbook read-only, export PDF, verify non-empty output, and close without saving.",
    "9. Create the Outlook draft, set recipient/subject/body, attach the approved PDF, and verify it remains unsent.",
    "10. Confirm mllminal-ui and CLI show the same task, progress, and verification state.",
    "11. Run mllminal acceptance record for each stage with evidence; finish only after user review."
) | ForEach-Object { Write-Output $_ }

Write-Output ""
Write-Output "Security gates to exercise: secure input suppression, traversal/junction/symlink rejection, forged verification, replay authorization, stale approval, emergency stop, duplicate execution after restart, application identity, malicious OCR, prompt injection, adapter crash, corrupted state, and unauthorized desktop client."
Write-Output "Performance metrics to record: idle CPU/memory, observation overhead, event throughput/latency, CLI/desktop startup, workflow preview, filesystem action, Excel export, and OCR latency."
