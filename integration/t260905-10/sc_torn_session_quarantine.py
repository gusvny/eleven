#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""sc_torn_session_quarantine.py —— 会话撕裂检疫增强回归（t260905-10 场景②，池=ro）。

intent（守护的用户可感知行为，灰盒 L3，05 号 260906 两次卡死 + t260829-06 帧撕裂同族）：
- zstd 帧完整但 JSONL record 中截断（好帧内撕裂=05 号事故同型）→ spawn 前
  `_quarantine_torn_sessions` 把它挪进隔离区留档，原位不再有坏档（同 id 新建走得通）；
- 好帧内出现非 JSON 行（内容损坏另一形态）→ 同判隔离；
- 健康对照组：多行合法 JSONL × 多帧 zstd 拼接 → **不**被检疫（防「见档就隔离」
  的反向事故——好会话误隔离=每次跑丢上下文，比漏检更常态化）；多会话目录独立
  判定，只挪坏的、不连坐好的；
- 隔离后同 id 新建：原路径重写合法会话档，再跑检疫不动它（恢复旅程）；
- 挪不动（隔离路径不可建）→ 不抛不致命，坏档留原位（既有兜底口径）；
- 空文件 / 二进制垃圾 → 既有 zstd -t 路径仍隔离（既有行为回归备注，非新代码腿）。

断言面=文件系统结果（挪没挪、原位在不在、隔离区留档在不在）——检疫是 spawn 前
的工程化动作，用户可感知面就是「坏档被清走、好档原样、流程能继续」。不锚日志
文案与隔离文件名细节。

实现段落地前红属预期（TDD 信号）：逐行试析缺席 → 好帧内撕裂/非 JSON 行两腿
不挪 → 场景红；arbitrate/merge 期必须绿。

直跑：python3 integration/t260905-10/sc_torn_session_quarantine.py（cwd=仓库根；
进程内文件夹具，零网络零 docker；temporalio 缺席走回落链重执行）。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib_lane import (EXIT_ENV, EXIT_FAIL, Fail, ensure_poc_python,  # noqa: E402
                      tmp_dir, zstd_available, zstd_frames)

ensure_poc_python()  # 需要引擎模块（temporalio 链）——回落链重执行

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "server/dsh/temporal-poc"))
import agent_activities  # noqa: E402


def build_session(dsh_home: Path, session_id: str, frames, torn_tail: bytes = b"") -> Path:
    """写 <dsh_home>/sessions/<session_id>/session.jsonl.zstd；frames=[bytes,...] 各成一帧。"""
    sdir = dsh_home / "sessions" / session_id
    sdir.mkdir(parents=True, exist_ok=True)
    data = zstd_frames(frames) + torn_tail
    f = sdir / "session.jsonl.zstd"
    f.write_bytes(data)
    return f


def line(obj: dict) -> bytes:
    return (json.dumps(obj, ensure_ascii=False) + "\n").encode("utf-8")


def main() -> int:
    f = Fail("t260905-10 场景② 会话撕裂检疫增强")
    if not zstd_available():
        print("ENV_FAIL: zstd CLI 缺席（检疫功能依赖 zstd，环境缺供）")
        return EXIT_ENV
    work = tmp_dir("sc-t26090510-quar-")
    try:
        dsh = work / "dshhome"
        dsh.mkdir(parents=True)
        # 新 base 首写落 .sandbar（resolve_dot_dir 规则3；老名泳道粘滞走 resolve 同序判定）
        quarantine = work / ".sandbar" / "quarantine"

        # ---- L1 核心：好帧内 JSONL record 中截断（05 号同型）→ 隔离 ----
        torn = build_session(
            dsh, "sess-torn",
            frames=[line({"i": 1, "role": "user"}), line({"i": 2, "role": "assistant"})],
            torn_tail='{"i":3,"role":"assistant","content":"说到一半被杀'.encode("utf-8"))
        healthy_sibling = build_session(
            dsh, "sess-fine", frames=[line({"i": 1}), line({"i": 2}), line({"i": 3})])
        agent_activities._quarantine_torn_sessions(dsh)
        f.check(not torn.exists(), "L1 好帧内撕裂档被挪离原位")
        moved = list(quarantine.glob("torn-sess-torn-*"))
        f.check(len(moved) == 1, "L1 隔离区恰留一份坏档留档（torn-*）")
        f.check(healthy_sibling.exists(), "L1 同批健康会话不连坐（多会话独立判定）")

        # ---- L2 好帧内非 JSON 行 → 隔离 ----
        notjson = build_session(
            dsh, "sess-notjson",
            frames=[line({"i": 1}), b"this is not json\n", line({"i": 3})])
        agent_activities._quarantine_torn_sessions(dsh)
        f.check(not notjson.exists(), "L2 好帧内非 JSON 行被判撕裂隔离")

        # ---- L3 健康对照组：多行合法 JSONL × 多帧拼接 → 不检疫 ----
        # 两帧：帧 A 含 2 行、帧 B 含 2 行（多帧拼接=真实会话档形态）
        sdir = dsh / "sessions" / "sess-multiframe"
        sdir.mkdir(parents=True, exist_ok=True)
        multi = sdir / "session.jsonl.zstd"
        multi.write_bytes(zstd_frames([line({"i": 1}) + line({"i": 2}),
                                       line({"i": 3}) + line({"i": 4})]))
        agent_activities._quarantine_torn_sessions(dsh)
        f.check(multi.exists(), "L3 多帧拼接的健康会话档不被误隔离（反向事故守卫）")

        # ---- L3b 裸空行宽容：记录间夹空行 → 不判撕裂不隔离（防误隔离承诺）----
        sdir_b = dsh / "sessions" / "sess-blankline"
        sdir_b.mkdir(parents=True, exist_ok=True)
        blank = sdir_b / "session.jsonl.zstd"
        blank.write_bytes(zstd_frames([line({"i": 1}), b"\n", line({"i": 2})]))
        agent_activities._quarantine_torn_sessions(dsh)
        f.check(blank.exists(), "L3b 裸空行不判撕裂（合法 JSONL 容忍面，防误隔离）")

        # ---- L4/L5 既有路径回归：空文件 / 二进制（zstd -t 拒收）----
        empty_dir = dsh / "sessions" / "sess-empty"
        empty_dir.mkdir(parents=True, exist_ok=True)
        empty = empty_dir / "session.jsonl.zstd"
        empty.write_bytes(b"")
        binary_dir = dsh / "sessions" / "sess-bin"
        binary_dir.mkdir(parents=True, exist_ok=True)
        binary = binary_dir / "session.jsonl.zstd"
        binary.write_bytes(bytes(range(64)))
        agent_activities._quarantine_torn_sessions(dsh)
        f.check(not empty.exists(), "L4 空会话档仍被既有路径隔离")
        f.check(not binary.exists(), "L5 二进制垃圾仍被既有路径隔离")

        # ---- L6 同 id 新建走得通：原路径重写合法档再检疫不动它 ----
        rebuilt = build_session(dsh, "sess-torn", frames=[line({"i": 1, "fresh": True})])
        agent_activities._quarantine_torn_sessions(dsh)
        f.check(rebuilt.exists(), "L6 同 id 新建合法档存活（恢复旅程走得通）")

        # ---- L7 挪不动：隔离路径不可建 → 不抛、坏档留原位 ----
        # 注意隔离根=<dsh 父>/.sandbar/quarantine（老泳道粘滞则 .suyou）；  # naming-compat
        # 换个新父目录造「.sandbar 是文件」的夹具（原稿在旧父上  # naming-compat
        # write_text 会撞 IsADirectoryError，夹具自炸）。
        work2 = tmp_dir("sc-t26090510-quar-l7-")
        dsh2 = work2 / "dshhome"
        dsh2.mkdir(parents=True)
        (work2 / ".sandbar").write_text("not a dir", encoding="utf-8")
        stuck = build_session(
            dsh2, "sess-stuck",
            frames=[line({"i": 1})], torn_tail=b'{"i":2,"cut')
        try:
            agent_activities._quarantine_torn_sessions(dsh2)
            f.check(stuck.exists(), "L7 隔离路径不可建：不抛且坏档留原位（插件兜底不变）")
        except Exception as e:
            f.check(False, "L7 挪不动竟抛异常 %s:%s（应 pass 不致命）" % (type(e).__name__, e))
    finally:
        import shutil
        shutil.rmtree(work, ignore_errors=True)
    return f.exit_code()


if __name__ == "__main__":
    sys.exit(main())
