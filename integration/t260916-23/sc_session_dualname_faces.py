#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""sc_session_dualname_faces.py —— 会话文件双名兼容读侧·检疫与统计两面（t260916-23 场景①，池=ro）。

intent（守护的用户可感知行为，灰盒 L3；dsh-upgrade T1——dsh 0.1.1-rc.2→0.1.5-rc.2 把
泳道会话档从 session.jsonl.zstd 换名为 session.v3.jsonl.zstd，引擎读侧必须双名发现，
否则升级后引擎找不到会话、回退踩同一坑。新名字面来自派发规格 260916，不符时改常量即回）：

检疫面（spawn 前坏档清道，升级/回退两个方向都不卡流程）：
- Q1 双名并存·新名好帧内撕裂 → 新名挪隔离区留档，旧名健康档原位（读侧接住新代名）；
- Q2 双名并存·旧名撕裂 → 照样挪（检疫是完整性全量清查，**不吃「组内取最新」**——
  旧名撕裂档不清，回退 dsh 0.1.1 读侧照样卡死；本 epic「可回退」原则的正面断言）；
- Q3 双名全健康对照组 → 双双原位、隔离区零新增（防「见档就隔离」反向事故——好会话
  误隔离=每次跑丢上下文，比漏检更常态化）；
- Q4 v3 名是个目录 → 不检疫不崩、同目录旧名健康档原位（名字层 is_file 守卫，
  防幼稚实现把目录喂给 zstd -t 连锅端）。

统计面（settle 快照 token 聚合：双名并存不翻倍、不漏计、半径不变）：
- S1 双名并存（新名 mtime 新）+ 另一 slug 旧名单档 → 组内只计最新一份+跨目录各计
  （防同一会话两代被双计，也防「全局只取一份」把别的目录漏掉）；
- S2 双名并存（旧名 mtime 新）→ 计旧名（取 mtime 最新与代数无关，防名字偏好实现）；
- S3 仅新名 → 计新名（升级后新会话可统计）；
- S4 两层以外的同名旧名档（一层/三层深）不入集（发现半径保持现状两层——纯名字层
  加宽不改发现深度，验收「当前树行为逐字节不变」的半径钉子）；
- S5 零会话 → tokens_zero=True 且 reason 含新名字面（文案与实现一致，验收④运行时子用例）；
- S6 v3 名是目录 → 统计不崩、不计其值、旧名档照常入集。

断言面=文件系统结果+聚合返回值——用户可感知面就是「坏档被清走好档原样、token 账
不翻倍不漏、找不到会话时报错说得清」。不锚隔离区文件名细节与日志文案。
实现细节绑定声明：直接驱动 agent_activities 的检疫/聚合入口（既有灰盒先例
t260905-10/t260904-09 同款接缝），断言落盘终态而非内部调用序。

intent 分界：与 t260905-10-torn-session-quarantine 不同面（彼守单代撕裂检疫语义、
恢复旅程与挪不动兜底；本条守双名并存下的两代清查）；与 t260904-09 settle 快照旅程
不同面（彼守旧名统计旅程与快照落盘/幂等；本条守双名聚合口径）。

实现落地前红属预期（TDD 信号）：Q1/S1/S3/S5 在双名接线前=产品红（Q2/S2/S4/S6/
Q3 为双向回归钉，前后皆绿）；arbitrate/merge 期必须绿。
直跑：PY=server/engine/.venv/bin/python; $PY -B integration/t260916-23/sc_session_dualname_faces.py
（cwd=仓库根；进程内文件夹具，零网络零 docker；zstd 缺席=ENV_FAIL exit 2 点名。）
"""
from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib_dualname import (EXIT_ENV, Fail, ensure_poc_python,  # noqa: E402
                          tmp_dir, zstd_available, zstd_frames)

ensure_poc_python()  # 需要引擎模块（temporalio 链）——回落链重执行

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "server/engine"))
import agent_activities  # noqa: E402

OLD = "session.jsonl.zstd"
NEW = "session.v3.jsonl.zstd"
TICKET = "t260916-23"
T0 = 1789000000


def line(obj: dict) -> bytes:
    return (json.dumps(obj, ensure_ascii=False) + "\n").encode("utf-8")


def usage_frames(i: int, o: int, c: int, model=None) -> list:
    """usage 记录形状锚引擎聚合解析面（request/context 归属 + assistant/message 计数）。"""
    frames = []
    if model:
        frames.append(line({"type": "request/context",
                            "data": {"provider": model[0], "model": model[1]}}))
    frames.append(line({"type": "assistant/message",
                        "data": {"usage": {"inputTokens": i, "outputTokens": o,
                                           "cacheReadTokens": c}}}))
    return frames


def lane_file(dsh: Path, slug: str, sub: str, name: str) -> Path:
    p = dsh / "sessions" / slug / sub / name
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def put(dsh: Path, slug: str, sub: str, name: str, ioc, mtime=None, torn=False) -> Path:
    p = lane_file(dsh, slug, sub, name)
    p.write_bytes(zstd_frames(usage_frames(*ioc)))
    if torn:  # 好帧内截断 record（05 号事故同型：zstd -t 过、逐行解析炸）
        with p.open("ab") as f:
            f.write('{"type":"assistant/message","data":{"usage":{"inputTok'.encode("utf-8"))
    if mtime:
        os.utime(p, (mtime, mtime))
    return p


def main() -> int:
    f = Fail("t260916-23 场景① 会话双名兼容·检疫与统计两面")
    if not zstd_available():
        print("ENV_FAIL: zstd CLI 缺席（检疫/统计两面都依赖 zstd，环境缺供）")
        return EXIT_ENV
    work = tmp_dir("sc-t260916-23-faces-")
    try:
        dsh = work / "dshhome"
        dsh.mkdir(parents=True)
        quarantine = work / ".sandbar" / "quarantine"  # lane_dot_path(local_dsh.parent) 规则

        # ---- Q1 双名并存·新名撕裂：新名挪、旧名健康档原位 ----
        old_ok = put(dsh, "projmain", TICKET + "-developer", OLD, (1, 2, 3))
        new_torn = put(dsh, "projmain", TICKET + "-developer", NEW, (4, 5, 6), torn=True)
        agent_activities._quarantine_torn_sessions(dsh)
        f.check(not new_torn.exists(), "Q1 新名好帧内撕裂档被挪离原位（读侧接住新代名）")
        f.check(old_ok.exists(), "Q1 同目录旧名健康档不连坐")
        f.check(any(quarantine.glob("*" + NEW)), "Q1 隔离区留档含新名原文件名")

        # ---- Q2 双名并存·旧名撕裂：旧名也挪（全量清查，不吃「取最新」）----
        old_torn = put(dsh, "projback", TICKET + "-developer", OLD, (1, 2, 3), torn=True)
        new_ok = put(dsh, "projback", TICKET + "-developer", NEW, (4, 5, 6))
        agent_activities._quarantine_torn_sessions(dsh)
        f.check(not old_torn.exists(), "Q2 双名并存下旧名撕裂档仍被清查（回退 0.1.1 不卡同一坑）")
        f.check(new_ok.exists(), "Q2 同目录新名健康档不连坐")

        # ---- Q3 健康对照组：双名全健康 → 零检疫动作 ----
        before = len(list(quarantine.glob("*"))) if quarantine.is_dir() else 0
        q3_old = put(dsh, "projfine", TICKET + "-developer", OLD, (1, 1, 1))
        q3_new = put(dsh, "projfine", TICKET + "-developer", NEW, (2, 2, 2))
        agent_activities._quarantine_torn_sessions(dsh)
        after = len(list(quarantine.glob("*"))) if quarantine.is_dir() else 0
        f.check(q3_old.exists() and q3_new.exists(), "Q3 双名全健康并存双双原位（反向事故守卫）")
        f.check(after == before, "Q3 隔离区零新增")

        # ---- Q4 v3 名是目录：不检疫不崩（is_file 守卫）----
        v3_dir = lane_file(dsh, "projdir", TICKET + "-developer", NEW)
        v3_dir.parent.mkdir(parents=True, exist_ok=True)
        v3_dir.mkdir(exist_ok=True)
        (v3_dir / "junk").write_text("x", encoding="utf-8")
        q4_old = put(dsh, "projdir", TICKET + "-developer", OLD, (1, 1, 1))
        agent_activities._quarantine_torn_sessions(dsh)
        f.check(v3_dir.is_dir(), "Q4 v3 名目录不被当会话档清走（不崩不误挪）")
        f.check(q4_old.exists(), "Q4 同目录旧名健康档原位")

        # ---- 统计面（每子用例独立 wt 夹具，互不污染）----
        def stat(wt: Path, ticket=TICKET):
            return agent_activities._aggregate_lane_usage(wt, ticket)

        # S1 双名并存新名新 + 跨 slug 旧名单档：组内取最新一份、跨目录各计
        wt1 = work / "wt1"
        put(wt1 / ".dsh", "sluga", TICKET + "-developer", OLD, (10, 20, 5), mtime=T0)
        put(wt1 / ".dsh", "sluga", TICKET + "-developer", NEW, (100, 200, 50), mtime=T0 + 100)
        put(wt1 / ".dsh", "slugb", TICKET + "-integration", OLD, (7, 11, 13), mtime=T0)
        tokens, _ = stat(wt1)
        f.check((tokens["in"], tokens["out"], tokens["cacheRead"]) == (107, 211, 63),
                "S1 组内只计最新一份+跨目录各计（100/200/50 + 7/11/13，不翻倍不漏计）")

        # S2 双名并存旧名新：取 mtime 最新与代数无关
        wt2 = work / "wt2"
        put(wt2 / ".dsh", "slugc", TICKET + "-developer", OLD, (30, 40, 50), mtime=T0 + 200)
        put(wt2 / ".dsh", "slugc", TICKET + "-developer", NEW, (3, 4, 5), mtime=T0)
        tokens, _ = stat(wt2)
        f.check((tokens["in"], tokens["out"], tokens["cacheRead"]) == (30, 40, 50),
                "S2 旧名 mtime 更新 → 计旧名（最新语义不看代数）")

        # S3 仅新名：升级后新会话可统计
        wt3 = work / "wt3"
        put(wt3 / ".dsh", "slugd", TICKET + "-developer", NEW, (11, 22, 33), mtime=T0)
        tokens, _ = stat(wt3)
        f.check((tokens["in"], tokens["out"], tokens["cacheRead"]) == (11, 22, 33)
                and not tokens["tokens_zero"], "S3 仅新名 → 按新名档计账")

        # S4 半径钉子：两层以外的同名档不入集（发现半径保持现状两层）
        wt4 = work / "wt4"
        sess4 = wt4 / ".dsh" / "sessions"
        put(wt4 / ".dsh", "sluge", TICKET + "-developer", OLD, (5, 6, 7), mtime=T0)
        deep1 = sess4 / "sluge" / OLD
        deep1.parent.mkdir(parents=True, exist_ok=True)
        deep1.write_bytes(zstd_frames(usage_frames(999, 999, 999)))
        deep3 = sess4 / "sluge" / (TICKET + "-developer") / "deep" / OLD
        deep3.parent.mkdir(parents=True, exist_ok=True)
        deep3.write_bytes(zstd_frames(usage_frames(888, 888, 888)))
        tokens, _ = stat(wt4)
        f.check((tokens["in"], tokens["out"], tokens["cacheRead"]) == (5, 6, 7),
                "S4 一层/三层深的同名旧名档不入集（发现半径=两层不变）")

        # S5 零会话：tokens_zero + reason 双名表述
        wt5 = work / "wt5"
        (wt5 / ".dsh" / "sessions" / "slugf" / "other-999").mkdir(parents=True)
        tokens, note = stat(wt5)
        f.check(tokens["tokens_zero"] is True, "S5 零本票会话 → tokens_zero（现行为不变）")
        f.check(NEW in note, "S5 零会话 reason 含新名字面（文案与实现一致，验收④）")

        # S6 v3 名是目录：统计不崩不计、旧名照常
        wt6 = work / "wt6"
        sess6 = wt6 / ".dsh" / "sessions"
        v6 = sess6 / "slugg" / (TICKET + "-developer") / NEW
        v6.mkdir(parents=True, exist_ok=True)
        s6_old = put(wt6 / ".dsh", "slugg", TICKET + "-developer", OLD, (6, 7, 8), mtime=T0)
        tokens, _ = stat(wt6)
        f.check((tokens["in"], tokens["out"], tokens["cacheRead"]) == (6, 7, 8),
                "S6 v3 名目录不崩不计、旧名档照常入集")
    finally:
        shutil.rmtree(work, ignore_errors=True)
    return f.exit_code()


if __name__ == "__main__":
    sys.exit(main())
