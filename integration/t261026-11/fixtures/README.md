# fixtures — provenance and regen commands (t261026-11)

The degrade matrix's fifth shape is the PRODUCER'S REAL PAYLOAD. What each
face's real payload is, where it comes from, and how it is regenerated:

## metrics (kpi tiles + secondary charts)

No checked-in fixture. The payload is regenerated at run time by
`lib_metrics_real.mjs`, which drives the REAL `buildMetricsResponse`
(workbench/src/host/metrics.ts) over the standard stub harness
(SANDBAR_METRICS_STUB, same technique as integration/t261025-14). Fixture
freshness is mechanical — born fresh every run. Needs `zstd`.

## requests list

No checked-in fixture. The real ledger is produced at run time by the REAL
writer (`appendRequest`) through the face's own LedgerIo seam.

## inspection-coverage (`coverage-real.json`)

Rows follow the archive's recordsToAttempts contract. CAPTURE LIMITATION
(filed in the handover): this lane's sandbox has no reachable project store,
so the checked-in rows were composed from the reader's own documented row
contract and the t261009-49 archive shapes — they are NOT a live capture.
Re-capture from a live store before treating the real-shape verdict as
producer-grade:

    SANDBAR_PROJECTS_DIR=<root> SANDBAR_PROJECT_KEY=<key> \
      python3 integration/t261026-11/fixtures/regen_coverage_rows.py

## certification tab (`cert-receipt.json` — NOT captured yet)

The real payload must be the engine adapter's own one-line JSON receipt.
Capture command (run on a machine with the project store; adapter is
read-only):

    python3 server/plugins/executor-panel/src/host/certification-adapter.py <project-key> \
      > integration/t261026-11/fixtures/cert-receipt.json

Until that file exists, degrade_certification_tab.mjs exits ENV_FAIL (2) —
never a stubbed green.
