#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""sc_t260917_05_session_face_loud.py —— 会话发现面零静默降级·engine 统计/检疫面
（t260917-05 票面验收①②，T1 双名遗留的格式层，灰盒 L3，池=ro）。

intent（用户可感知）：token 统计 notes 与坏会话隔离面对「本目录存在会话文件但
名字/格式对不上本版本解析面」必须响亮点名，绝不静默 0——工单台看到的 settle
note / merge warns 是唯一出口，静默 0 = 升级换格式后用量统计悄悄归零。

断言面（锚定 _aggregate_lane_usage 返回的 note/tokens 契约 + 文件系统结果 +
root logger 捕获；零网络零 docker）：
 A 双名+健康样本：本票与 <票id>-developer 双目录都入统计、他票不混入、note 干净
   （T1 已落行为的回归锚）；
 B 坏格式（合法 zstd 帧包非 JSON 文本）→ note 含票面例句（格式不认识/疑似 dsh
   版本不匹配/统计值不可信）+ 点名文件 + format_suspect 注记 + tokens 记零；
 C 混合态（好+坏各一）→ 金额只来自好文件，format_suspect 与坏文件点名仍在场
   （部分降级不静默）；
 D 刚启动边界（有事件无 usage / 空档 / 纯空行）→ 保留既有「无 usage 事件」人话、
   不冤枉格式（防误报方向的对抗腿）；
 E 发现集空而目录有他票三层/旧扁平/未知名三样 → 三类分流点名（他票与旧代=未入
   统计、未知名=疑似 dsh 版本不匹配）+ suspect_unmatched 注记；
 F 点名单封顶（30 个未知名档）→ 名单有界不膨胀（settle note 进不可变账本，
   MERGE_FILES_CAP 同纪律）；
 G 检疫盲区 → 未知名会话样文件 warning 点名「隔离面未覆盖」且不挪不解析；健康档
   与旧扁平档不动、也不被点名（已知旧代不喊狼）。
 H TS 半同构判据（workbench 用量/发现面，node>=22.18 type-stripping 子进程直调
   lib_face_probe.mjs，review 意见7 钉死机制）：resolveAll 双名全取/健康无
   suspect/混合态 suspect 浮出/发现集空按类点名+suspectFiles/单文件面（agent-live）
   同样点名。zstd/node 缺席=ENV_FAIL 点名（exit 2），绝不装绿。

实现段落地前红属预期（TDD 信号：B-G 的判据与注记键未落地），arbitrate/merge 期
必须绿。与 developer L1（判据纯函数 UT、检疫 caplog UT）intent 不同面：本条守
多文件合成后的整串 note 与三态分流/封顶/盲区的整行为，L1 看不到合成结果。
直跑：python3 integration/t260917-05/sc_t260917_05_session_face_loud.py（cwd=仓库根；
进程内文件夹具，temporalio 缺席走回落链重执行）。
"""
from __future__ import annotations

import json
import logging
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib_face import (EXIT_ENV, EXIT_FAIL, Fail, ensure_poc_python,  # noqa: E402
                      tmp_dir, zstd_available, zstd_bytes)

ensure_poc_python()  # 需要引擎模块（temporalio 链）——回落链重执行

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "server/engine"))
import agent_activities  # noqa: E402

TICKET = "t260917-05"


def line(obj) -> bytes:
    return (json.dumps(obj, ensure_ascii=False) + "\n").encode("utf-8")


def healthy_lines(n_in=10, n_out=20, cache=5):
    """健康会话行：session 头 + 模型上下文 + 带 usage 的 assistant/message。"""
    return [
        line({"type": "session", "version": 0, "id": "s", "createdAt": 1}),
        line({"type": "request/context", "data": {"provider": "p", "model": "m1"}}),
        line({"type": "assistant/message",
              "data": {"usage": {"inputTokens": n_in, "outputTokens": n_out,
                                 "cacheReadTokens": cache}}}),
    ]


def put(root: Path, rel, payload: bytes) -> Path:
    """写 <root>/<*rel>（rel 各段为目录/文件名），返回文件路径。"""
    p = root.joinpath(*rel)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(payload)
    return p


def sess_put(wt: Path, rel_under_sessions, payload: bytes) -> Path:
    return put(wt, (".dsh", "sessions") + tuple(rel_under_sessions), payload)


def main() -> int:
    f = Fail("t260917-05 场景 会话发现面零静默降级（engine 统计/检疫面）")
    if not zstd_available():
        print("ENV_FAIL: zstd CLI 缺席（统计/检疫通路依赖 zstd，环境缺供）")
        return EXIT_ENV
    work = tmp_dir("sc-t26091705-face-")

    # ---- 腿 A：双名+健康样本（T1 双名回归锚：金额并、他票不混、note 干净）----
    wt = work / "wtA"
    sess_put(wt, ("slugA", TICKET, "session.jsonl.zstd"), zstd_bytes(healthy_lines(10, 20, 5)))
    sess_put(wt, ("slugA", TICKET + "-developer", "session.jsonl.zstd"), zstd_bytes(healthy_lines(1, 2, 3)))
    sess_put(wt, ("slugA", "t9999-99", "session.jsonl.zstd"), zstd_bytes(healthy_lines(100, 100, 100)))
    tokens, note = agent_activities._aggregate_lane_usage(wt, TICKET)
    f.check(tokens["in"] == 11 and tokens["out"] == 22 and tokens["cacheRead"] == 8,
            "A1 双名两档都入统计（10+1/20+2/5+3），他票 100 不混入")
    f.check(note == "", "A2 健康路径 note 干净（无注记污染既有口径）")
    f.check(not tokens.get("format_suspect") and not tokens.get("suspect_unmatched"),
            "A3 健康聚合无任何 suspect 注记")

    # ---- 腿 B：坏格式（解压成功、内容不可解析）→ 票面例句响亮 ----
    wt = work / "wtB"
    sess_put(wt, ("slugB", TICKET, "session.jsonl.zstd"),
             zstd_bytes([b"ce n'est pas json\nnope neither is this\n"]))
    tokens, note = agent_activities._aggregate_lane_usage(wt, TICKET)
    f.check("格式不认识" in note and "疑似 dsh 版本不匹配" in note and "统计值不可信" in note,
            "B1 note 含票面例句三段（响亮文案，非轻描 0）")
    f.check("session.jsonl.zstd" in note, "B2 note 点名到文件")
    f.check(tokens.get("format_suspect") is True, "B3 format_suspect 注记在位（机器可读）")
    f.check(tokens["in"] == 0 and tokens.get("tokens_zero") is True,
            "B4 tokens 记零但注记在场（0 但非静默 0）")

    # ---- 腿 C：混合态（好+坏）→ 部分降级不静默 ----
    wt = work / "wtC"
    sess_put(wt, ("slugC", TICKET, "session.jsonl.zstd"), zstd_bytes(healthy_lines(7, 0, 0)))
    sess_put(wt, ("slugC", TICKET + "-badsoup", "session.jsonl.zstd"), zstd_bytes([b"garbage line\n"]))
    tokens, note = agent_activities._aggregate_lane_usage(wt, TICKET)
    f.check(tokens["in"] == 7, "C1 金额只来自好文件（一份坏不清零整体，既有口径）")
    f.check(tokens.get("format_suspect") is True, "C2 混合态 suspect 注记仍置位")
    f.check("badsoup" in note and "格式不认识" in note, "C3 note 仍点名坏文件（坏档不因好档有数被吞）")
    f.check(tokens.get("tokens_zero") is False, "C4 好文件 usage 在场 → 非零态保持")

    # ---- 腿 D：刚启动边界（有事件无 usage/空档/纯空行）→ 不冤枉格式 ----
    wt = work / "wtD"
    sess_put(wt, ("slugD", TICKET, "session.jsonl.zstd"),
             zstd_bytes([line({"type": "session", "version": 0, "id": "s", "createdAt": 1}),
                         line({"type": "request/context", "data": {"provider": "p", "model": "m"}})]))
    sess_put(wt, ("slugD", TICKET + "-void", "session.jsonl.zstd"), zstd_bytes([b""]))
    sess_put(wt, ("slugD", TICKET + "-blank", "session.jsonl.zstd"), zstd_bytes([b"\n\n   \n"]))
    tokens, note = agent_activities._aggregate_lane_usage(wt, TICKET)
    f.check("格式不认识" not in note, "D1 空/纯空行/无 usage 都不冤枉成格式违约（防误报）")
    f.check("无 usage 事件" in note, "D2 保留既有「无 usage 事件」人话（弱响亮不缺席）")
    f.check(tokens.get("tokens_zero") is True, "D3 tokens_zero 注记照旧")
    f.check(not tokens.get("format_suspect"), "D4 无 format_suspect（非格式违约）")

    # ---- 腿 E：发现集空而目录有会话样文件 → 三类分流点名 ----
    wt = work / "wtE"
    sess_put(wt, ("eslug-other", "t9999-99", "session.jsonl.zstd"), zstd_bytes(healthy_lines()))
    sess_put(wt, ("eslug-old", "session-0425.zstd"), zstd_bytes(healthy_lines()))
    sess_put(wt, ("eslug-new", "x9", "session.jsonl.zst"), zstd_bytes([b"k\n"]))
    tokens, note = agent_activities._aggregate_lane_usage(wt, TICKET)
    f.check(tokens.get("suspect_unmatched") is True, "E1 suspect_unmatched 注记在位")
    f.check("eslug-other" in note and "未入统计" in note, "E2 他票三层 → 点名+「未入统计」（不喊损坏）")
    f.check("eslug-old" in note, "E3 旧扁平（已知旧代）→ 点名在场（不无声消失）")
    f.check("eslug-new" in note and "疑似 dsh 版本不匹配" in note,
            "E4 未知名 → 点名+「疑似 dsh 版本不匹配」")
    f.check(tokens["in"] == 0 and tokens.get("tokens_zero") is True,
            "E5 统计仍零但点名在场（非静默）")

    # ---- 腿 F：点名单封顶（30 个未知名档）→ 名单有界不膨胀 ----
    wt = work / "wtF"
    names = ["fcap-%02d" % i for i in range(30)]
    for i, nm in enumerate(names):
        sess_put(wt, (nm, "x9", "session-cap-%02d.zst" % i), zstd_bytes([b"k\n"]))
    tokens, note = agent_activities._aggregate_lane_usage(wt, TICKET)
    hit = sum(1 for nm in names if nm in note)
    f.check(tokens.get("suspect_unmatched") is True, "F1 suspect_unmatched 在位")
    f.check(0 < hit < 30, "F2 点名单有界（30 个未知名只列部分、hit=%d；全列=撑爆不可变账本）" % hit)

    # ---- 腿 G：检疫盲区 → 未知名 warning 点名、不挪不解析 ----
    dsh = work / "dshhome"
    good = put(dsh, ("sessions", "gslug", TICKET, "session.jsonl.zstd"), zstd_bytes(healthy_lines()))
    newg = put(dsh, ("sessions", "gslug-new", "x9", "session.jsonl.zst"), zstd_bytes([b"whatever\n"]))
    oldf = put(dsh, ("sessions", "gslug-old", "session-legacy.zstd"), zstd_bytes(healthy_lines()))

    class _Cap(logging.Handler):
        def __init__(self):
            super().__init__()
            self.records = []

        def emit(self, record):
            self.records.append(record)

    cap = _Cap()
    root = logging.getLogger()
    root.addHandler(cap)
    old_level = root.level
    root.setLevel(logging.WARNING)
    try:
        agent_activities._quarantine_torn_sessions(dsh)
    finally:
        root.removeHandler(cap)
        root.setLevel(old_level)

    f.check(good.exists() and newg.exists() and oldf.exists(),
            "G1 三档全部原位（未知名不挪不解析——不懂的格式不能动）")
    msgs = [str(r.getMessage()) for r in cap.records]
    f.check(any("隔离面未覆盖" in m for m in msgs), "G2 盲区 warning 在场（「隔离面未覆盖」）")
    f.check(any("隔离面未覆盖" in m and "gslug-new" in m for m in msgs),
            "G3 warning 点名未知名文件")
    f.check(all("gslug-old" not in m for m in msgs),
            "G4 旧扁平=已知旧代不被点名（不喊狼）")

    # ---- 腿 H：TS 半（workbench 用量/发现面）同构判据——node 子进程直调 ----
    if shutil.which("node") is None:
        print("ENV_FAIL: node 缺席（TS 半直调需要 node>=22.18 type-stripping，环境缺供）")
        return EXIT_ENV
    probe = str(Path(__file__).resolve().parent / "lib_face_probe.mjs")

    def ts_probe(action, arg):
        p = subprocess.run(["node", probe, action, json.dumps(arg)],
                           capture_output=True, text=True, timeout=120)
        try:
            out = json.loads((p.stdout or "").strip().splitlines()[-1])
        except (ValueError, IndexError):
            f.check(False, "H0 TS probe %s 输出不可解析（rc=%s，stderr尾=%s）"
                    % (action, p.returncode, (p.stderr or "")[-160:]))
            return {}
        if p.returncode == 2 or str(out.get("error", "")).startswith("ENV_FAIL"):
            print("ENV_FAIL: %s" % out.get("error"), flush=True)
            sys.exit(EXIT_ENV)
        if p.returncode != 0 or not out.get("ok"):
            f.check(False, "H0 TS probe %s 失败：%s" % (action, out.get("error")))
            return {}
        return out.get("result") or {}

    repo = work / "repo"
    wt_rel = ".worktrees/wt"
    wt_ts = repo / wt_rel
    sess_put(wt_ts, ("slug-ts", TICKET, "session.jsonl.zstd"), zstd_bytes(healthy_lines(10, 20)))
    sess_put(wt_ts, ("slug-ts", TICKET + "-developer", "session.jsonl.zstd"), zstd_bytes(healthy_lines(1, 2)))
    sess_put(wt_ts, ("slug-ts", "other-ticket-developer", "session.jsonl.zstd"), zstd_bytes(healthy_lines(100, 100)))
    ra = ts_probe("resolveAll", {"repo": str(repo), "ticketId": TICKET,
                                 "ticket": {"worktree": wt_rel}})
    f.check(len(ra.get("paths") or []) == 2, "H1 TS resolveAll 双名两档全取、他票不混（T1 锚）")
    rb = ts_probe("aggregate", {"paths": ra.get("paths") or [], "windows": []})
    f.check(rb.get("exists") is True and not rb.get("suspect"), "H2 TS 健康聚合无 suspect")
    bad = sess_put(wt_ts, ("slug-ts", TICKET + "-badsoup", "session.jsonl.zstd"),
                   zstd_bytes([b"garbage line\n"]))
    rc = ts_probe("aggregate", {"paths": [str(bad)] + (ra.get("paths") or []), "windows": []})
    f.check(rc.get("exists") is True and rc.get("suspect") is True
            and "格式不认识" in str(rc.get("suspectDetail"))
            and str(bad) in str(rc.get("suspectDetail")),
            "H3 TS 混合态：totals 照常、坏文件 suspect/明细浮出（绝不静默）")
    (wt_ts / ".dsh" / "sessions" / "slug-ts" / "stray.session.bin").write_bytes(b"x")
    rd = ts_probe("resolveAll", {"repo": str(repo), "ticketId": "t-absent-ts",
                                 "ticket": {"worktree": wt_rel}})
    f.check(len(rd.get("suspectFiles") or []) == 5
            and "他票会话" in str(rd.get("reason"))
            and "疑似 dsh 版本不匹配" in str(rd.get("reason")),
            "H4 TS 发现集空+5 样在场 → 按类点名+suspectFiles（绝不静默 0）")
    re_one = ts_probe("resolveOne", {"repo": str(repo), "ticketId": "t-absent-ts",
                                     "ticket": {"worktree": wt_rel}})
    f.check(re_one.get("path") is None and "他票会话" in str(re_one.get("reason")),
            "H5 TS 单文件面（agent-live）同样点名")

    return f.exit_code()


if __name__ == "__main__":
    sys.exit(main())
