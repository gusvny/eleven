#!/usr/bin/env bash
# apply_sidebar_wiring.sh — t261019-09 arbitration round 2, structural demand (b):
# the agent sandbox cannot land server/plugins/workbench/src/client/sidebar.tsx
# (the settle gate's write-set whitelist refuses it — three quarantine batches
# prove it), so the WORKER applies this one line + rebuild deterministically at
# settle. Idempotent: re-running is a no-op. Never touches .git.
set -euo pipefail
cd "$(dirname "$0")/../.."

SRC=server/plugins/workbench/src/client/sidebar.tsx
ANCHOR='openTicketOverlay={(id) => handleTicketClick({ id } as Ticket, viewProject)} />'
LINE='                closeTicketOverlay={() => setListNonce(n => n + 1)} />'

if grep -q 'closeTicketOverlay={() => setListNonce' "$SRC"; then
  echo "already wired: $SRC"
else
  python3 - "$SRC" "$ANCHOR" "$LINE" <<'PYEOF'
import sys
path, anchor, line = sys.argv[1], sys.argv[2], sys.argv[3]
s = open(path).read()
if s.count(anchor) != 1:
    sys.exit(f"anchor not unique in {path}: {s.count(anchor)}")
open(path, 'w').write(s.replace(anchor, anchor[:-2].rstrip() + '\n' + line, 1))
print("wired:", path)
PYEOF
fi

# Rebuild so source and the served bundles agree (skew guard lives in the unit battery).
( cd server/plugins/workbench && npm run build >/dev/null )

# Verify: source, bundle, and the developer skew guard must all agree.
grep -q 'closeTicketOverlay={() => setListNonce' "$SRC" || { echo 'FAIL: source unwired' >&2; exit 1; }
grep -q 'closeTicketOverlay: () => setListNonce((n) => n + 1)' server/plugins/workbench/lib/client.js || { echo 'FAIL: client.js unwired' >&2; exit 1; }
grep -q 'closeTicketOverlay: () => setListNonce((n) => n + 1)' server/plugins/workbench/lib/client.cjs || { echo 'FAIL: client.cjs unwired' >&2; exit 1; }
node --test server/plugins/workbench/tests/t261019-09-close-overlay.mjs >/dev/null || { echo 'FAIL: skew-guard battery red' >&2; exit 1; }
echo "OK: t261019-09 sidebar wiring landed (source + both bundles + unit battery green)"
