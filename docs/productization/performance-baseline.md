# Performance baseline

## Status

No clean-machine baseline is claimed. The acceptance report lists every metric as manual_required until raw measurements are captured on the target Windows installation. CI duration is not a product performance measurement.

## Required measurements

| Metric | Procedure | Evidence |
| --- | --- | --- |
| Idle daemon CPU and memory | Sample the daemon for at least ten minutes with observation disabled | timestamped samples and mean/p95 |
| Observation overhead | Repeat the idle sample with visible observation enabled | paired delta |
| Event persistence throughput | Capture a bounded semantic event batch | count, elapsed time, database size |
| Event-stream latency | Compare persisted event time with client receipt time | p50/p95 |
| CLI and desktop startup | Measure cold and warm startup to ready | command and timings |
| Workflow preview | Compile and preview weekly-report workflow | input count and elapsed time |
| Filesystem action | Preview, execute, and verify a test rename/move | elapsed time and verification |
| Excel export | Open test workbook and export PDF | workbook size, elapsed time, PDF size |
| OCR latency | Inspect one bounded active-window frame | dimensions, provider, elapsed time |
| Vision worker memory | Repeat bounded inspections | peak working set |
| Model load/unload | Only if explicitly configured locally | model name and timings |
| One-hour database growth | Observe a non-sensitive quiet workflow for one hour | before/after size |

## Collection rules

Use a clean Windows account and non-sensitive fixture. Record CPU, memory, Windows version, provider availability, and application versions. Do not include file contents, secure text, credentials, tokens, screenshots, or raw OCR. Keep observation visible and stop if emergency stop is required. Do not install or download a model solely to manufacture a measurement.

Attach raw CSV or JSON samples to the acceptance evidence directory and record paths with mllminal acceptance record. Treat one machine as a baseline, not a universal requirement. Readiness remains Beta or Prototype until measurements and the complete scenario are reviewed.
