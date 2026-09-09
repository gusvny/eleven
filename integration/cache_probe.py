#!/usr/bin/env python3
"""cache_probe — prompt-cache (cacheReadTokens) investigation for k3 sessions
(t260901-19 item 1, read-only).

Scans .worktrees/*/.dsh/sessions/**/*.jsonl.zstd (ticket-lane agent sessions,
the dsh-headless-resume on-disk format), extracts usage per turn
(inputTokens/outputTokens/cacheReadTokens), and prints each session's hit rate
cache_read/(input+cache_read) plus a savings estimate. Writes no files and
never touches the spawn chain.

Observed usage shape:
  {"inputTokens":27,"outputTokens":520,"cacheReadTokens":25856}
Counting rules:
  - every message carrying usage with inputTokens+outputTokens+cacheReadTokens>0
    counts as one sample;
  - the duplicate (dsh writes the same turn twice) is not deduplicated —
    numerator and denominator double together, so the hit rate is unchanged;
  - malformed/truncated lines are skipped and counted (torn zstd frames,
    non-JSON lines).

Dependency: the system zstd binary (session files are zstd-compressed JSONL).
Missing -> readable error + exit(2).
Usage: python3 integration/cache_probe.py [root]   # root defaults to the repo root
"""
import json
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent  # parent of integration/ = repo root


def fail(msg, code=2):
    print("[cache_probe] %s" % msg, file=sys.stderr)
    sys.exit(code)


def probe_session(f: Path):
    """Decompress one session file, return (samples, bad_n).
    sample = (input, output, cache_read)."""
    r = subprocess.run(["zstd", "-dc", str(f)], capture_output=True)
    if r.returncode != 0:
        return [], 1
    samples, bad_n = [], 0
    for ln in r.stdout.decode("utf-8", errors="replace").splitlines():
        try:
            obj = json.loads(ln)
        except Exception:
            bad_n += 1
            continue
        usage = obj.get("usage") if isinstance(obj, dict) else None
        if usage is None and isinstance(obj, dict) and isinstance(obj.get("data"), dict):
            usage = obj["data"].get("usage")  # dsh on-disk shape: assistant/message
            # events keep usage under "data" (seen in the t260901-16/18 sessions)
        if not isinstance(usage, dict):
            continue
        i = usage.get("inputTokens") or 0
        o = usage.get("outputTokens") or 0
        c = usage.get("cacheReadTokens") or 0
        if not all(isinstance(v, int) for v in (i, o, c)):
            bad_n += 1
            continue
        if i + o + c > 0:
            samples.append((i, o, c))
    return samples, bad_n


def main():
    if not shutil.which("zstd"):
        fail("未找到 zstd 二进制（会话文件是 zstd 压缩 JSONL）。"
             "请先安装：brew install zstd ——本工具不做降级解压。")
    root = Path(sys.argv[1]) if len(sys.argv) > 1 else REPO
    sessions = sorted((root / ".worktrees").glob("*/.dsh/sessions/**/*.jsonl.zstd"))
    if not sessions:
        print("[cache_probe] %s/.worktrees 下无会话文件" % root)
        return
    print("%-14s %-52s %8s %10s %10s %7s %6s" %
          ("ticket", "session", "turns", "input", "cacheRead", "hit%", "bad"))
    grand_i = grand_c = grand_turns = grand_bad = 0
    for f in sessions:
        parts = f.parts
        ticket = parts[parts.index(".worktrees") + 1]
        sess = f.parent.name
        samples, bad_n = probe_session(f)
        ti = sum(s[0] for s in samples)
        tc = sum(s[2] for s in samples)
        hit = (tc * 100.0 / (ti + tc)) if (ti + tc) else 0.0
        grand_i += ti
        grand_c += tc
        grand_turns += len(samples)
        grand_bad += bad_n
        print("%-14s %-52s %8d %10d %10d %6.1f%% %6d" %
              (ticket, sess[:52], len(samples), ti, tc, hit, bad_n))
    ghit = (grand_c * 100.0 / (grand_i + grand_c)) if (grand_i + grand_c) else 0.0
    print("-" * 110)
    print("合计：turns=%d input=%d cacheRead=%d 命中率=%.1f%%（约节省 %d 非 cached input tokens）"
          " 畸形行=%d" % (grand_turns, grand_i, grand_c, ghit, grand_c, grand_bad))


if __name__ == "__main__":
    main()
