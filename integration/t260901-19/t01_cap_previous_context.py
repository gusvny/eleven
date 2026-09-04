#!/usr/bin/env python3
"""t260901-19 T1: cap_previous_context scoping + build_stage_prompt wiring (black-box).

Contract under test (plan v3, approved by review round 3):
- Only lines with the six "- 上次*：" history prefixes are capped: the LINE is cut
  to 800 chars (prefix included) + "…（截断）"; history-class total is capped at
  4000 chars by dropping TAIL (oldest) lines + "…（后续历史已省略）" marker.
- "- 打回原因：" line and ALL unrecognized lines pass through verbatim, except a
  20000-char hard ceiling for deformed giant lines.
- Defensive normalization: None / non-str / bytes / blank -> "".
- build_stage_prompt applies the cap before injecting previous_context, so rework
  blocks and machine payloads (arb_ctx JSON) survive verbatim in the prompt.

Runs on plain python3 (shared.py is stdlib-only). cwd = lane root.
"""
import pathlib
import sys

sys.path.insert(0, "server/dsh/temporal-poc")
import shared  # noqa: E402

HIST_PREFIXES = [
    "- 上次状态：", "- 上次摘要：", "- 上次报告：",
    "- 上次产物：", "- 上次改动文件：", "- 上次验收证据：",
]
REWORK_PREFIX = "- 打回原因："
LINE_MARK = "…（截断）"
TAIL_MARK = "…（后续历史已省略）"
PER_LINE = 800      # history line cap, prefix INCLUDED (plan: 行截到 800+标记)
TOTAL = 4000        # history-class total cap
HARD_CEIL = 20000   # unrecognized-line hard ceiling

passed, failed = 0, 0


def check(name, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
    else:
        failed += 1
        print("FAIL %s %s" % (name, detail))


def main():
    cap = getattr(shared, "cap_previous_context", None)
    check("cap-defined", callable(cap), "shared.cap_previous_context missing")

    if callable(cap):
        # configured limits must equal the approved plan
        check("cfg-line-limit", getattr(shared, "CAP_PREV_LINE_LIMIT", 0) == PER_LINE,
              str(getattr(shared, "CAP_PREV_LINE_LIMIT", None)))
        check("cfg-total-limit", getattr(shared, "CAP_PREV_TOTAL_LIMIT", 0) == TOTAL,
              str(getattr(shared, "CAP_PREV_TOTAL_LIMIT", None)))
        check("cfg-hard-limit", getattr(shared, "CAP_PREV_HARD_LIMIT", 0) == HARD_CEIL,
              str(getattr(shared, "CAP_PREV_HARD_LIMIT", None)))

        # -- defensive normalization --------------------------------------
        check("norm-none", cap(None) == "")
        check("norm-int", cap(123) == "")
        check("norm-bytes", cap(b"\xff\xfe garbage") == "")
        check("norm-empty", cap("") == "")
        check("norm-blank", cap("   \n  ") == "")

        # -- history lines: whole line (prefix included) capped to 800 ----
        body = PER_LINE - len("- 上次状态：")
        for p in HIST_PREFIXES:
            out = cap(p + "X" * 2000)
            keep = PER_LINE - len(p)
            check("hist-linecap:%s" % p.strip("：-"),
                  out.startswith(p) and out.endswith(LINE_MARK)
                  and "X" * keep in out and "X" * (keep + 1) not in out,
                  "len=%d" % len(out))
        # at the boundary: line of exactly 800 chars is NOT truncated, 801 is
        out = cap("- 上次报告：" + "Y" * (PER_LINE - len("- 上次报告：")))
        check("hist-boundary-exact", LINE_MARK not in out and out.endswith("Y"))
        out = cap("- 上次报告：" + "Y" * (PER_LINE - len("- 上次报告：") + 1))
        check("hist-boundary-over", out.endswith(LINE_MARK))

        # -- rework line verbatim (ticket core: 打回意见逐字) --------------
        note = "R" * 3000
        out = cap(REWORK_PREFIX + note)
        check("rework-verbatim", note in out and LINE_MARK not in out)

        # -- unrecognized lines pass through ------------------------------
        blob = "U" * 5000
        out = cap(blob)
        check("unknown-verbatim", blob in out and LINE_MARK not in out)
        # arb_ctx-like single-line JSON payload must survive
        js = '{"ran":9,"details":["' + "D" * 9000 + '"]}'
        out = cap(js)
        check("json-verbatim", js in out)

        # -- hard ceiling for deformed giant unknown lines ----------------
        giant = "G" * (HARD_CEIL + 5000)
        out = cap(giant)
        check("hard-ceil",
              giant not in out and len(out) <= HARD_CEIL + 50, "len=%d" % len(out))

        # -- history total cap: tail (oldest) drop + marker, rework kept --
        lines = [p + "H%d" % i + "x" * (PER_LINE - 4 - len(p))
                 for i, p in enumerate(HIST_PREFIXES * 2)]
        lines.append(REWORK_PREFIX + "KEEPME")
        out = cap("\n".join(lines))
        check("total-tail-drop", out.endswith(TAIL_MARK), "no tail marker")
        check("total-head-kept", lines[0][:20] in out)
        check("total-rework-kept", "KEEPME" in out)
        # at least one tail history line was dropped
        check("total-some-dropped", lines[-2][:20] not in out)

    # -- build_stage_prompt wiring ----------------------------------------
    bp = shared.build_stage_prompt
    body_long = PER_LINE - len("- 上次报告：")
    ctx = "\n".join([
        "【方案审读打回（第 2 轮）】review comments：",
        "B" * 1500,                       # unrecognized rework block line -> verbatim
        "- 上次报告：" + "P" * 2000,        # history line -> capped in prompt
        REWORK_PREFIX + "NOTE" * 100,      # rework line -> verbatim
    ])
    stage = shared.Stage(id="implement", name="实现", role="developer",
                         next="", desc="")
    prompt = bp("t260901-19", {"title": "x"}, stage, [], "/tmp/rf.json", 1, ctx)
    check("prompt-rework-block-verbatim", "B" * 1500 in prompt)
    check("prompt-rework-note-verbatim", "NOTE" * 100 in prompt)
    check("prompt-history-capped",
          "P" * 2000 not in prompt and "P" * body_long in prompt)

    print("SUMMARY pass=%d skip=0 fail=%d" % (passed, failed))
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
