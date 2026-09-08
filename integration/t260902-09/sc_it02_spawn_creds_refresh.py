#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""t260902-09 集成测试 it02 —— 老泳道 spawn 后新 provider key 可见（用户场景钉）。

KI-016 根因有两道守卫：_copy_creds 内部 return（it01 钉）+ _prepare_agent_spawn
外层 exists 守卫（本件钉）。用户视角：同一泳道从 create_plan 走到后续 stage，
每次 agent spawn 前的本地 .dsh 准备都必须让「项目凭据源里新增的 provider key」
对下一个 agent 可见，且不抹掉 agent 中途换 key 的现场；spawn 准备本身绝不因
凭据源缺失而炸（MISSING_CREDENTIAL 由引擎/agent 侧报，不归 spawn 准备）。

黑盒边界 = _prepare_agent_spawn 的返回 (cmd, env) 与泳道 .dsh 的文件系统终态；
全 tmp/env 桩，不触真凭据、不起进程、不连 Temporal。
依赖 PyYAML 的场景（S1/S3）在无 yaml 且无 venv 的解释器上记 ENV_FAIL（三态契约定稿 §7.3：缺依赖=环境红）。
跑法：PY=server/engine/.venv/bin/python; "$PY" integration/t260902-09/it02_spawn_creds_refresh.py
末行 SUMMARY pass=N fail=N env_fail=N na=N；退出码 0=PASS、1=FAIL（产品红）、2=ENV_FAIL（环境红）。
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))
import fixture as fx  # noqa: E402

K_DEEPSEEK, V_DEEPSEEK = "DEEPSEEK_API_KEY", "sk-fixture-deepseek-old"
K_ZAI, V_ZAI = "ZAI_CODING_CN_API_KEY", "sk-fixture-zai-coding-cn-new"
ROTATED = "sk-fixture-rotated-mid-ticket"


def _spawn(aa, sb):
    """以 fixture 泳道为 cwd 跑 spawn 准备（role 空 = 不触角色 patch/会话延续）。"""
    art = sb.tmp / "artifacts"
    art.mkdir(parents=True, exist_ok=True)
    return aa._prepare_agent_spawn(
        cwd=sb.lane, role="", kind="", ticket_id="t260902-09-fixture",
        artifacts_dir=art, tag="fx", project="suyou")


def main():
    aa = fx.load_agent_activities()
    yaml_ok = fx.ensure_yaml()
    L = fx.Ledger()

    print("== S 老泳道 spawn 场景 ==")
    # S2 dst 缺失 → spawn 后快照出现（整拷路径经 spawn 真实触发；yaml-free）
    with fx.Sandbox() as sb:
        src = sb.perkey("suyou", fx.creds_text([(K_DEEPSEEK, V_DEEPSEEK)]))
        cmd, env = _spawn(aa, sb)
        L.ok(sb.dst().is_file(), "S2 spawn 后快照落位")
        L.ok(sb.dst().read_text("utf-8") == src.read_text("utf-8"),
             "S2 快照与源字节等值")
        L.ok(isinstance(cmd, list) and env.get("DSH_HOME") == str(sb.lane / ".dsh"),
             "S2 返回 (cmd, env) 且 agent DSH_HOME 指向泳道 .dsh")

    # S4 无任何凭据源 → spawn 准备不炸、不造默认凭据（yaml-free）
    with fx.Sandbox() as sb:
        threw = None
        try:
            cmd, env = _spawn(aa, sb)
        except Exception as e:
            threw = e
        L.ok(threw is None, "S4 无源时 spawn 准备不抛错", threw)
        L.ok(not sb.dst().exists(), "S4 无源不造默认凭据")
        L.ok(isinstance(cmd, list), "S4 仍返回可用 cmd")

    if not yaml_ok:
        L.env1("S1/S3 合并刷新场景（2 用例）",
                "PyYAML 不可用且无 engine venv（venv=%s）" % fx.VENV_PY)
        return L.finish()

    # S1 KI-016 用户场景：老泳道快照 + 源新增 provider key → 下一次 spawn 可见
    with fx.Sandbox() as sb:
        dst_text = fx.creds_text([(K_DEEPSEEK, V_DEEPSEEK)])
        sb.write_dst(dst_text, mode=0o600)
        sb.perkey("suyou", fx.creds_text([(K_DEEPSEEK, V_DEEPSEEK), (K_ZAI, V_ZAI)]))
        cmd, env = _spawn(aa, sb)
        merged = sb.dst().read_text("utf-8")
        refs = (fx.yaml_load(merged) or {}).get("refs") or {}
        L.ok(refs.get(K_ZAI) == V_ZAI, "S1 老泳道下一次 spawn 即见新 provider key",
             refs.get(K_ZAI))
        L.ok(fx.insertion_only(dst_text, merged), "S1 原快照行无改写无删除")
        L.ok(env.get("DSH_HOME") == str(sb.lane / ".dsh"),
             "S1 agent 凭据解析位 = 泳道暂存快照")
    # S3 agent 中途换 key 的现场不被后续 spawn 抹掉
    with fx.Sandbox() as sb:
        sb.write_dst(fx.creds_text([(K_DEEPSEEK, ROTATED)]))
        sb.perkey("suyou", fx.creds_text([(K_DEEPSEEK, V_DEEPSEEK), (K_ZAI, V_ZAI)]))
        _spawn(aa, sb)
        _spawn(aa, sb)  # 连续两个 stage 的 spawn 都不抹
        refs = (fx.yaml_load(sb.dst().read_text("utf-8")) or {}).get("refs") or {}
        L.ok(refs.get(K_DEEPSEEK) == ROTATED,
             "S3 中途换 key 现场经两次 spawn 保留", refs.get(K_DEEPSEEK))
        L.ok(refs.get(K_ZAI) == V_ZAI, "S3 同一快照新 key 照常可见")

    return L.finish()


if __name__ == "__main__":
    sys.exit(main())
