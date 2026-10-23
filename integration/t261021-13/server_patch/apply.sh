#!/usr/bin/env sh
# t261021-13 — apply the server patch bundle (write-set escalation handover).
#
# The ticket's write set is integration/ only, but the root cause lives in
# server/plugins/executor-panel/. The engine reverts out-of-write-set edits
# (t261021-06 precedent), so this bundle carries the change as files instead of
# landing it. Run from the lane root AFTER the write set is widened:
#   sh integration/t261021-13/server_patch/apply.sh
# Refuses to run if the targets drifted from the tree this bundle was cut from.
set -e
cd "$(dirname "$0")/../../.."
check() {
  want="$1"; got="$2"
  if command -v shasum >/dev/null 2>&1; then h=$(shasum -a 256 "$got" | cut -d' ' -f1)
  else h=$(sha256sum "$got" | cut -d' ' -f1); fi
  if [ "$h" != "$want" ]; then
    echo "REFUSED: $got drifted from the tree this bundle was cut from ($h)" >&2
    exit 1
  fi
}
check 36d3dac14fd5e6a43c611351ed66d5f1bb221a8adf9d902f812bdbb15fd130d5 server/plugins/executor-panel/src/host/panel-page.ts
check 2056a98c8fd893e676b6040a5925efcea17b725deaef3c120437177f274c75c3 server/plugins/executor-panel/src/host/markdown.ts
check 7f9910204d0908a2b31767a8bc51b361b19f6057c2bb2f8d98aa1da011e88f11 server/plugins/executor-panel/tests/markdown.test.mjs
cp integration/t261021-13/server_patch/panel-page.ts.new    server/plugins/executor-panel/src/host/panel-page.ts
cp integration/t261021-13/server_patch/markdown.ts.new      server/plugins/executor-panel/src/host/markdown.ts
cp integration/t261021-13/server_patch/markdown.test.mjs.new server/plugins/executor-panel/tests/markdown.test.mjs
echo "applied: panel-page.ts, markdown.ts, markdown.test.mjs"
