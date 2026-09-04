#!/usr/bin/env python3
"""t260901-19 T4: cache_probe tool (plan v3 item 1, read-only investigation tool).

Contract under test (integration/cache_probe.py):
- zstd binary missing -> readable error mentioning zstd + exit code 2 (never a
  traceback exit 1). The probe checks shutil.which("zstd") before anything else.
- Scan root is injectable via positional arg:  cache_probe.py <root>  ; a root
  with no sessions is a valid answer (exit 0).
- Malformed / truncated session lines are skipped AND counted, not fatal; hit
  rate is cache_read/(input+cache_read) — fixture: one valid usage row
  {input:100, cacheRead:900} => 90%, plus 2 broken rows => skip count 2.
- Read-only: the probe writes nothing (contract stated in its docstring).

cwd = lane root. zstd needed only for the fixture half (missing -> ENV_FAIL exit 2,
三态契约定稿 §7.3「闸内无 SKIP」).
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

PROBE = Path("integration/cache_probe.py")
passed, failed, env_failed = 0, 0, 0


def check(name, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
    else:
        failed += 1
        print("FAIL %s %s" % (name, detail))


def env_fail(name, reason):
    global env_failed
    env_failed += 1
    print("ENV_FAIL: %s %s" % (name, reason))


def run(args, env_path=None):
    env = dict(os.environ)
    if env_path is not None:
        env["PATH"] = env_path
    return subprocess.run([sys.executable, str(PROBE)] + args,
                          capture_output=True, text=True, timeout=120, env=env)


def main():
    if not PROBE.is_file():
        check("probe-exists", False, "integration/cache_probe.py missing")
        print("SUMMARY pass=%d fail=%d env_fail=%d na=0" % (passed, failed, env_failed))
        sys.exit(1)
    check("probe-exists", True)

    # zstd missing -> readable error, exit 2 (run python via absolute path,
    # PATH stripped so shutil.which("zstd") finds nothing)
    r = run([], env_path="/nonexistent")
    if r.returncode == 2 and "zstd" in (r.stdout + r.stderr):
        check("zstd-missing-exit2", True)
    elif r.returncode == 0:
        env_fail("zstd-missing-exit2", "probe exited 0 with PATH stripped — "
                 "zstd-missing branch not exercised (zstd found elsewhere)")
    else:
        check("zstd-missing-exit2", False,
              "rc=%d out=%s" % (r.returncode, (r.stdout + r.stderr)[:200]))

    root = tempfile.mkdtemp(prefix="t260901-19-t4-")
    try:
        empty = os.path.join(root, "empty")
        os.makedirs(empty)
        r = run([empty])
        check("empty-root-exit0", r.returncode == 0,
              "rc=%d %s" % (r.returncode, r.stderr[:200]))

        if shutil.which("zstd"):
            sess = os.path.join(root, ".worktrees", "fx", ".dsh", "sessions",
                                "ws1", "t1-integration")
            os.makedirs(sess)
            raw = "\n".join([
                json.dumps({"role": "assistant",
                            "usage": {"inputTokens": 100, "outputTokens": 10,
                                      "cacheReadTokens": 900}}),
                "not-json-at-all",
                '{"usage": {"inputTokens":',       # truncated half line
            ]) + "\n"
            plain = os.path.join(sess, "session.jsonl")
            Path(plain).write_text(raw, "utf-8")
            zfile = os.path.join(sess, "session.jsonl.zstd")
            subprocess.run(["zstd", "-q", "-f", plain, "-o", zfile],
                           check=True, timeout=60)
            check("fixture-compressed", os.path.exists(zfile))
            r = run([root])
            out = r.stdout + r.stderr
            check("fixture-exit0", r.returncode == 0,
                  "rc=%d %s" % (r.returncode, out[:200]))
            check("hit-rate-90", re.search(r"90\.0%", out) is not None,
                  "hit rate 900/1000 not reported in: %s" % out[-300:])
            check("skip-counted", re.search(r"畸形行=\s*2\b|\bskip\b.*\b2\b", out)
                  is not None or re.search(r"\b2\b\s*$", out, re.M) is not None,
                  "2 malformed rows not counted in: %s" % out[-300:])
            # read-only contract: probe must not create/modify files under root
            leftovers = [str(p) for p in Path(root).rglob("*")
                         if p.is_file() and not p.name.endswith(".zstd")
                         and p.name != "session.jsonl"]
            check("read-only", not leftovers, str(leftovers))
        else:
            env_fail("fixture-exit0+hit-rate+skip-counted+read-only",
                     "zstd binary missing")
    finally:
        shutil.rmtree(root, ignore_errors=True)

    print("SUMMARY pass=%d fail=%d env_fail=%d na=0" % (passed, failed, env_failed))
    sys.exit(2 if env_failed else (1 if failed else 0))


if __name__ == "__main__":
    main()
