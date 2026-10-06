#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""t261006-05 场景③：投递指名跨面一致（灰盒 L2 契约锚，integration 岗）。

intent（登记于 run_scenarios.py SCENARIOS）——执行器账本投递的「换路指名」
必须在所有告诉执行器怎么投递的面上**指同一条引擎侧投递面**（client.py deliver），
不许一面改名、其余面还在指旧路（漂移守卫，t261006-01 同族方法论）：

- P1 引擎拒收面：executor_requests.py 里执行器通道的拒收文案点名 deliver；
- P2 人格面：executor preset（agent.cordis.yml）的审批/升权纪律条款写明
  「无审批应答者、优先沙箱内动作、账本投递走引擎侧 deliver」，且不推荐直写；
- P3 全族扫描：preset/charter 面与引擎 CLI 面都不再把 --op file 直写当成
  执行器的推荐动作（实报即全族：本票病灶是「唯一合法通道=直写」，修后任何
  面残留该推荐=红）。

intent 分工：各文件内部的逐条 source-lock 断言（preset 三锚点逐字、CLI 拒收
真值表）归 developer L1（随实现交付）；deliver 的有界/拒收分类归
t261004-44-deliver-bounded-refusal；本条只钉「多面同指一条活路」的跨面一致。

零 docker、零网络、零 3099；只读三个仓内源文件。抽取失败 = FAIL 点名
（fail-closed，绝不静默当无）。实现前红属预期（TDD 信号）；arbitrate/merge
必须绿。
"""
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, os.path.join(REPO, "integration"))

try:
    from lib_result import emit_case
except Exception as e:
    print("ENV_FAIL: integration lib_result import failed: %r" % (e,))
    sys.exit(2)

SUITE = "t261006-05-delivery-pointer-agreement"
FACES = {
    "engine_cli": os.path.join(REPO, "server", "engine", "executor_requests.py"),
    "executor_preset": os.path.join(REPO, "server", "profile", "agent-presets",
                                    "sandbar-executor", "agent.cordis.yml"),
}
FAILS = []


def read_face(name, path):
    if not os.path.isfile(path):
        emit_case(name="%s-%s-extract" % (SUITE, name), suite=SUITE, status="fail",
                  cause="self", reason="face source file missing",
                  evidence=path)
        FAILS.append(name)
        return None
    try:
        with open(path, encoding="utf-8") as f:
            return f.read()
    except Exception as e:
        emit_case(name="%s-%s-extract" % (SUITE, name), suite=SUITE, status="fail",
                  cause="self", reason="face unreadable", evidence="%s: %r" % (path, e))
        FAILS.append(name)
        return None


def main():
    texts = {n: read_face(n, p) for n, p in FACES.items()}

    # P1 engine refusal face names the replacement.
    t = texts["engine_cli"]
    if t is not None:
        # the executor-channel refusal branch must carry the deliver pointer
        ok = "client.py" in t and "deliver" in t
        emit_case(name="P1-engine-refusal-names-deliver", suite=SUITE,
                  status=("pass" if ok else "fail"), cause="self",
                  reason="engine CLI face must name the deliver replacement face",
                  evidence="deliver_hits=%d" % len(re.findall(r"deliver", t)))
        if not ok:
            FAILS.append("P1")

    # P2 persona face: approval-discipline clause present, engine-side delivery
    # named, never wait on an approval prompt.
    t = texts["executor_preset"]
    if t is not None:
        has_clause = ("approval" in t and "deliver" in t)
        emit_case(name="P2-preset-clause-names-approval-and-deliver", suite=SUITE,
                  status=("pass" if has_clause else "fail"), cause="self",
                  reason="preset persona must state the no-answerer approval discipline and the engine-side delivery face",
                  evidence="approval_hits=%d deliver_hits=%d" % (
                      len(re.findall(r"approval", t)), len(re.findall(r"deliver", t))))
        if not has_clause:
            FAILS.append("P2")

        # P3 family scan: no face recommends the direct --op file append as the
        # executor's route (the incident's "only lawful channel" must not survive
        # as advice anywhere in the preset face).
        recommends_direct = bool(re.search(r"--op\s+file", t))
        emit_case(name="P3-preset-does-not-recommend-direct-append", suite=SUITE,
                  status=("fail" if recommends_direct else "pass"), cause="self",
                  reason="preset face must not recommend the direct --op file ledger write to the executor",
                  evidence="direct_op_file_hits=%d" % len(re.findall(r"--op\s+file", t)))
        if recommends_direct:
            FAILS.append("P3")

    if FAILS:
        print("SUMMARY: %s FAIL=%s" % (SUITE, ",".join(FAILS)))
        sys.exit(1)
    print("SUMMARY: %s all pass" % SUITE)


if __name__ == "__main__":
    main()
