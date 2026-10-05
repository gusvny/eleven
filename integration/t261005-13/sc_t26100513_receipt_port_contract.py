#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""t261005-13 场景①：up 回执端口契约（灰盒 L2，integration 岗 design_integration_tests 段）。

intent（登记于 run_scenarios.py SCENARIOS）——工单 REQUIRED OUTCOME 2 的集成面钉子：
起台回执（boot receipt）与引擎校验器的端口要求必须在**具名的一侧**对齐，且 fail-closed
纪律原样保留。事故形态（2026-09-29 t260929-22 与 2026-10-05 t261005-06 两次实锤）：
回执声明 services=['temporal','dsh']、端口面按生产者契约（integration/stage_docker.py
_flip_lease_up）只会有 {temporal, ui, console} 三个键（dsh 服务暴露的是 console 口），
而引擎校验器按服务名 1:1 索要 ports.dsh → 生产者合法回执被误红、UI 证据供给全断。
本场景钉在**编排公开缝** `ui_capture_stage.up_stage`（runner 可注入，docstring 明文
场景注入面；不读私有函数），断言只落在公开契约（绿/红与点名文案）上：

- A1（主修，事故形态绿）：production 形态回执（services=['temporal','dsh']、
  ports={temporal,ui,console}）必须过闸——修前此形态直红，即本工单病灶。
- B1..B4（fail-closed 面不弱化）：缺 console / 缺 temporal / console 非 int
  （bool/str/0 三态）/ 幽灵键回执（services 带 dsh 但端口面只有 ports.dsh 无
  console）一律红，且报错点名缺失的端口键（「哪个检查失败」可判，不断言「没有 X」）。
  B4 是「修复没有靠顺手认下幽灵键 ports.dsh 来放行」的守卫。
- C（旧格式兼容面不动）：无 services 列表的旧回执保守要求 console——缺=红、
  带=绿（既有行为，守卫不漂移）。
- D（环境/契约分型面）：runner 回 rc=2 走 UiStageEnvError（可降级），不走契约
  直红——环境红与契约红不可混（三态总纲）。

intent 分工：validate_stage_receipt 的纯函数真值表（逐畸形字面矩阵）归 developer
L1（随实现交付）；本条钉的是 up_stage 公开缝上的「生产者↔消费者对齐 + fail-closed
保留」契约，与 t260915-18（终态回收）不互替、与 capture 族（截图内容/面板渲染）
不重叠——截图内容按工单口径 out of scope。

零 docker、零网络、零 3099；临时仓桩（假 repo_root）随用随收。引擎模块缺席=
ENV_FAIL exit 2。实现前红属预期（TDD 信号）；arbitrate/merge 必须绿。
"""
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
ENGINE = os.path.join(REPO, "server", "engine")
sys.path.insert(0, REPO)
sys.path.insert(0, ENGINE)
sys.path.insert(0, os.path.join(REPO, "integration"))

try:
    from lib_result import emit_case
    from ui_capture_stage import UiStageEnvError, UiStageError, up_stage
except Exception as e:  # engine module absent = environment red, named
    try:
        from lib_result import emit_case
        emit_case(name="t261005-13-receipt-port-contract", status="not-checked",
                  cause="external", reason="engine ui_capture_stage import failed",
                  evidence=repr(e)[:300])
    except Exception:
        print("ENV_FAIL: engine ui_capture_stage import failed: %r" % (e,))
    sys.exit(2)

SUITE = "t261005-13-receipt-port-contract"
_FAILS = []


def check(name, ok, reason="", evidence=""):
    emit_case(name=name, suite=SUITE,
              status="pass" if ok else "fail", cause="self",
              reason=reason, evidence=str(evidence)[:400])
    if not ok:
        _FAILS.append(name)


def receipt(project="ui-shot-t261005-13-g0", services=None, ports=None):
    r = {"project": project}
    if services is not None:
        r["services"] = services
    if ports is not None:
        r["ports"] = ports
    return json.dumps(r) + "\n"


def runner_for(stdout, rc=0, stderr=""):
    def run(cmd, cap_s, env_extra):
        return rc, stdout, stderr
    return run


def main():
    ok_all = True
    # fake repo root: stage_cli_path only needs the CLI file to exist
    with tempfile.TemporaryDirectory(prefix="sc-t26100513-") as tmp:
        cli_dir = os.path.join(tmp, "integration")
        os.makedirs(cli_dir)
        cli_path = os.path.join(cli_dir, "stage_docker.py")
        open(cli_path, "w").close()

        def up(stdout, rc=0, stderr=""):
            return up_stage("ui-shot-t261005-13-g0", repo_root=tmp,
                            runner=runner_for(stdout, rc, stderr))

        # A1 incident shape: full bench receipt must pass (pre-fix this is RED)
        full_ports = {"temporal": 7233, "ui": 8099, "console": 3999}
        try:
            r = up(receipt(services=["temporal", "dsh"], ports=full_ports))
            check("A1-full-receipt-green",
                  isinstance(r, dict) and r.get("project") == "ui-shot-t261005-13-g0",
                  "incident shape (services temporal+dsh, ports temporal/ui/console) "
                  "must pass at the public up_stage seam",
                  json.dumps(r)[:200])
        except Exception as e:
            check("A1-full-receipt-green", False,
                  "incident shape rejected — producer/consumer still disagree",
                  "%s: %s" % (type(e).__name__, str(e)[:200]))

        # B1 missing console -> contract red, message names the port key
        try:
            up(receipt(services=["temporal", "dsh"],
                       ports={"temporal": 7233, "ui": 8099}))
            check("B1-missing-console-red", False, "half receipt passed — fail-closed lost")
        except UiStageEnvError as e:
            check("B1-missing-console-red", False,
                  "contract red must not be classified as env face", str(e)[:200])
        except UiStageError as e:
            check("B1-missing-console-red", "console" in str(e),
                  "red ok, but error must name the failed check (ports.console)",
                  str(e)[:200])

        # B2 missing temporal -> red, message names temporal
        try:
            up(receipt(services=["temporal", "dsh"],
                       ports={"ui": 8099, "console": 3999}))
            check("B2-missing-temporal-red", False, "half receipt passed — fail-closed lost")
        except UiStageError as e:
            check("B2-missing-temporal-red", "temporal" in str(e),
                  "red ok, but error must name the failed check (ports.temporal)",
                  str(e)[:200])

        # B3 console wrong type: bool / str / zero all red
        for tag, bad in (("bool", True), ("str", "3999"), ("zero", 0)):
            try:
                up(receipt(services=["temporal", "dsh"],
                           ports={"temporal": 7233, "ui": 8099, "console": bad}))
                check("B3-console-type-%s-red" % tag, False,
                      "non-positive-int console passed — fail-closed lost")
            except UiStageError:
                check("B3-console-type-%s-red" % tag, True)
            except UiStageEnvError as e:
                check("B3-console-type-%s-red" % tag, False,
                      "contract red misclassified as env", str(e)[:200])

        # B4 phantom-key receipt: ports carries dsh but not console -> still red
        try:
            up(receipt(services=["temporal", "dsh"],
                       ports={"temporal": 7233, "dsh": 3999}))
            check("B4-phantom-dsh-key-red", False,
                  "phantom ports.dsh accepted — fix weakened instead of mapping")
        except UiStageError as e:
            check("B4-phantom-dsh-key-red", "console" in str(e),
                  "red ok, and must demand console (dsh maps to console), not dsh",
                  str(e)[:200])

        # C legacy receipt without services list: conservative console demand kept
        try:
            up(receipt(ports={"temporal": 7233}))
            check("C1-legacy-missing-console-red", False,
                  "legacy receipt without console passed — guard drifted")
        except UiStageError as e:
            check("C1-legacy-missing-console-red", "console" in str(e),
                  "red ok, message names console", str(e)[:200])
        try:
            r = up(receipt(ports={"temporal": 7233, "console": 3999}))
            check("C2-legacy-with-console-green", isinstance(r, dict),
                  "legacy receipt with console stays green", json.dumps(r)[:150])
        except Exception as e:
            check("C2-legacy-with-console-green", False,
                  "legacy green face drifted", "%s: %s" % (type(e).__name__, str(e)[:200]))

        # D rc=2 stays an env face (degradable), never a contract red
        try:
            up("{}", rc=2, stderr="STAGE_WAIT docker daemon unreachable\n")
            check("D-envfail-rc2-degradable", False, "rc=2 accepted as success")
        except UiStageEnvError:
            check("D-envfail-rc2-degradable", True)
        except UiStageError as e:
            check("D-envfail-rc2-degradable", False,
                  "env red (rc=2) misclassified as contract red", str(e)[:200])

    ok_all = not _FAILS
    print("SUMMARY %s: %s" % (SUITE, "all green" if ok_all else "FAIL: %s" % ",".join(_FAILS)))
    return 0 if ok_all else 1


if __name__ == "__main__":
    sys.exit(main())
