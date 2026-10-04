#!/usr/bin/env python3
"""t261004-34 scenario D: the L1-L18 lint battery stays wired into the code
lane.

Host order 261004 (executor request -0001, main-side commit 8b66af0): the
static lint battery runs as a check of the code lane, so a lane cannot merge
with a red lint face. verify.yaml is a protected path - a lane cannot silently
remove the wiring - but nothing prevented a main-side edit from dropping it.
This scenario pins the wiring: the guard reads the real verify.yaml through a
real YAML parser, so a commented-out or renamed entry simply is not there and
the guard goes red instead of fake-green.

Grey-box L3, offline, seconds, read-only. Contract asserted (config surface,
not implementation):

- D1 lanes.code.checks contains an ACTIVE entry with id `lint`;
- D2 that entry's cmd invokes the battery entrypoint
  (`integration/lint_tests.py`) and the script exists on disk (a wired-but-
  dangling cmd is as dead as no wiring);
- D3 negative control: the same parser over a config where the lint entry is
  commented out does NOT see it - proves this guard can detect a silent
  removal by construction.

Three states: verify.yaml missing / unparseable / no yaml parser = ENV_FAIL
exit 2 (named, no fake red, no fake green). Run with the engine venv first so
the yaml parser is present:
  PY=server/engine/.venv/bin/python; [ -x "$PY" ] || PY=python3;
  "$PY" -B integration/t261004-34/sc_lint_battery_wired_into_code_lane.py
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
VERIFY_YAML = os.path.join(REPO, "verify.yaml")
BATTERY = "integration/lint_tests.py"

FAILURES = []


def check(name, cond, detail=""):
    print("%s %s%s" % ("PASS" if cond else "FAIL", name,
                       (" | " + detail) if detail else ""))
    if not cond:
        FAILURES.append(name)


def lint_entries(cfg):
    """Active `lint` entries under lanes.code.checks (post-parse: commented-out
    lines never survive a real parser). Returns (entries, cmd_strings)."""
    checks = (((cfg.get("lanes") or {}).get("code") or {}).get("checks")) or []
    hits = [c for c in checks
            if isinstance(c, dict) and str(c.get("id", "")) == "lint"]
    return hits, [str(c.get("cmd", "")) for c in hits]


def main():
    try:
        import yaml  # noqa: PLC0415
    except ImportError:
        print("ENV_FAIL: no yaml parser (run under server/engine/.venv/bin/python)")
        return 2
    if not os.path.isfile(VERIFY_YAML):
        print("ENV_FAIL: verify.yaml not found at repo root")
        return 2
    try:
        with open(VERIFY_YAML, encoding="utf-8") as f:
            cfg = yaml.safe_load(f)
    except Exception as e:  # noqa: BLE001
        print("ENV_FAIL: verify.yaml unparseable: %s" % e)
        return 2

    print("== D1/D2 the code lane actively wires the lint battery")
    hits, cmds = lint_entries(cfg)
    check("D1 lanes.code.checks has an active id=lint entry", bool(hits),
          "hits=%r" % hits)
    wired = [c for c in cmds if BATTERY in c]
    check("D2 the lint entry's cmd invokes the battery entrypoint",
          bool(hits) and bool(wired), "cmds=%r" % cmds)
    check("D2b the battery script exists on disk",
          os.path.isfile(os.path.join(REPO, BATTERY)), "")

    print("== D3 negative control: commented-out wiring is not wiring")
    bare = ("schema: v1\n"
            "lanes:\n"
            "  code:\n"
            "    checks:\n"
            "      # - id: lint\n"
            "      #   cmd: python3 integration/lint_tests.py\n")
    ghost, _ = lint_entries(yaml.safe_load(bare))
    check("D3 parser sees no active lint entry after commenting it out",
          not ghost, "ghost=%r" % ghost)

    if FAILURES:
        print("SUMMARY: fail=%d" % len(FAILURES))
        return 1
    print("SUMMARY: fail=0 env_fail=0")
    return 0


if __name__ == "__main__":
    sys.exit(main())
