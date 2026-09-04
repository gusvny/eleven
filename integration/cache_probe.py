#!/usr/bin/env python3
"""cache_probe —— k3 会话 prompt cache（cacheReadTokens）排查工具（t260901-19 ①，只读）。

扫 .worktrees/*/.dsh/sessions/**/*.jsonl.zstd（工单泳道 agent 会话，dsh-headless-resume
落盘格式），逐 turn 提取 usage（inputTokens/outputTokens/cacheReadTokens），输出每会话
命中率 cache_read/(input+cache_read) 与节省估算。不写任何文件、不碰 spawn 链路。

usage 形态（实测）：
  {"inputTokens":27,"outputTokens":520,"cacheReadTokens":25856}
口径：
  - 每条含 usage 且 inputTokens+outputTokens+cacheReadTokens>0 的消息计一个样本；
    重复出现两次（dsh 落盘同 turn 双写）不去重——分子分母同倍增，命中率不变。
  - 畸形/半截行跳过并计数（zstd 撕裂帧、非 JSON 行）。

依赖：系统 zstd 二进制（会话文件是 zstd 压缩 JSONL）。缺失 → 可读报错 + exit(2)。
跑法：python3 integration/cache_probe.py [root]   # root 缺省=仓库根
"""
import json
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent  # integration/ 的父目录 = 仓库根


def fail(msg, code=2):
    print("[cache_probe] %s" % msg, file=sys.stderr)
    sys.exit(code)


def probe_session(f: Path):
    """解压一个会话文件，返回 (samples, skipped)。sample=(input,output,cache_read)。"""
    r = subprocess.run(["zstd", "-dc", str(f)], capture_output=True)
    if r.returncode != 0:
        return [], 1
    samples, skipped = [], 0
    for ln in r.stdout.decode("utf-8", errors="replace").splitlines():
        try:
            obj = json.loads(ln)
        except Exception:
            skipped += 1
            continue
        usage = obj.get("usage") if isinstance(obj, dict) else None
        if usage is None and isinstance(obj, dict) and isinstance(obj.get("data"), dict):
            usage = obj["data"].get("usage")  # dsh 落盘形态：assistant/message 事件，
            # usage 在 data 下（实测 t260901-16/18 会话）
        if not isinstance(usage, dict):
            continue
        i = usage.get("inputTokens") or 0
        o = usage.get("outputTokens") or 0
        c = usage.get("cacheReadTokens") or 0
        if not all(isinstance(v, int) for v in (i, o, c)):
            skipped += 1
            continue
        if i + o + c > 0:
            samples.append((i, o, c))
    return samples, skipped


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
          ("ticket", "session", "turns", "input", "cacheRead", "hit%", "skip"))
    grand_i = grand_c = grand_turns = grand_skip = 0
    for f in sessions:
        parts = f.parts
        ticket = parts[parts.index(".worktrees") + 1]
        sess = f.parent.name
        samples, skipped = probe_session(f)
        ti = sum(s[0] for s in samples)
        tc = sum(s[2] for s in samples)
        hit = (tc * 100.0 / (ti + tc)) if (ti + tc) else 0.0
        grand_i += ti
        grand_c += tc
        grand_turns += len(samples)
        grand_skip += skipped
        print("%-14s %-52s %8d %10d %10d %6.1f%% %6d" %
              (ticket, sess[:52], len(samples), ti, tc, hit, skipped))
    ghit = (grand_c * 100.0 / (grand_i + grand_c)) if (grand_i + grand_c) else 0.0
    print("-" * 110)
    print("合计：turns=%d input=%d cacheRead=%d 命中率=%.1f%%（约节省 %d 非 cached input tokens）"
          " 畸形行=%d" % (grand_turns, grand_i, grand_c, ghit, grand_c, grand_skip))


if __name__ == "__main__":
    main()
