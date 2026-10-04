#!/bin/sh
# Restore the t261004-08 watchdog harness seam if a main merge dropped it
# (loss mode seen twice: the seam lives in harness.mjs while the worker's
# commit fallback only picked integration/ files; the next main merge then
# wiped the uncommitted change). Idempotent: no-op when the seam is present.
cd "$(git rev-parse --show-toplevel 2>/dev/null || echo .)"
if grep -q "requests_seed" server/plugins/watchdog/harness.mjs; then
  echo "seam already present"; exit 0
fi
git apply integration/t261004-08/harness-seam.patch && node --check server/plugins/watchdog/harness.mjs && echo "seam restored"
