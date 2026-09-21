#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""t260921-14 场景①：dsh 路径钉声明键的翻转/回归锚/遮蔽/docker 不消费四面
（灰盒 L2，ro 池，离线秒级：零真 docker、零 Temporal server、零真全局 dsh 依赖）。

intent（用户可感知）：引擎为项目起 dsh 时，「用哪个 dsh 二进制」由项目声明
（per-key project.yaml 的 paths.dsh_bin）说了算——翻转变真用（不只在解析层）、
不翻则行为与现状逐字一致、env 旋钮永远压得过声明且被压过时响亮点名、docker 形态
不受声明影响（容器内版本由镜像承载）。

依据（三依据穷尽）：
①工单验收 L2①「翻转后 spawn 真用绝对路径（桩观测）」+L2②「不翻转时行为与现状
  逐字一致（回归锚）」；宿主令「回退=配置改回一行」的行为面前提=声明行确实掌管
  二进制选择（本条①④即其正向面）。
②KI：KI-058「机器层安装态≠代码态」——本条①的 face↔spawn 同源断言即其观测解药
  （票面 dsh_pin_<tag>.json 必须与真执行的 cmd 出自同一次解析）；KI-051 锚语义
  （warning 断言锚关键词不锁整句）。
③对外契约：契约 v1 ①d paths 键族语义（声明=钉、未声明=现状逐字）；dsh_pin 旋钮
  优先级 SANDBAR_AGENT_CMD > paths.dsh_bin > 缺省（方案 v2 §2.2 定稿）。

high-level steps：每条子用例独立 tmp 注册表+独立桩（EnvSandbox 隔离，绝不写真
~/.sandbar/projects、真 ~/.dsh）→直调 _prepare_agent_spawn（spawn 预备单点）→
①声明子用例：cmd[0]=桩绝对路径+参数=缺省逐元素；桩账本出现与 prepared cmd 逐元素
相同的执行记录（进程级「被真调」）；票面 face cmd_source=declared 且 cmd[0] 与
spawn 同源；②回归子用例：无声明无 env→cmd 与缺省逐元素等值、face cmd_source=default、
既有 face 键集全保持（版本值不断言——真机全局 dsh 缺席属机器态，版本面归
t260916-24-dsh-face-meta 的真机子用例）；③遮蔽子用例：env 整命令+声明并存→env 胜+
face dsh_bin_shadowed=True+WARNING 点名遮蔽；④docker 子用例：SANDBAR_AGENT_RUNTIME=
docker+声明在场→cmd 不钉（容器内解析）、face 走镜像面、WARNING 点名 docker 不消费
声明。

intent 分工（防 intent 级重复）：t260916-24-dsh-face-meta 守 env 旋钮启动链 face
与探测失败不挡启动、t260916-24-dsh-expected-loud 守执行面期望响亮——本条只守
「声明键」这一新旋钮族（翻转/回归/遮蔽/形态分叉）；声明词法/fail-closed 矩阵归
developer L1（test_t260921_14_dsh_path_pin，方案 §2.6 取舍清单）与 sc_paths 契约
族不同对象。

三态：PASS 0 / FAIL 1 / ENV_FAIL 2。实现落地前红属预期（TDD 信号：声明键未接线
=①③红、tri/face 缺口红），arbitrate/merge 期必须绿；引擎模块不可导入=ENV_FAIL
exit 2 点名。
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import lib_t26092114 as L  # noqa: E402

C = L.Checker("t260921-14-pin-flip")

KEY1, KEY2, KEY3, KEY4 = ("sct26092114a", "sct26092114b", "sct26092114c",
                          "sct26092114d")
LEGACY_FACE_KEYS = ("mode", "cmd", "cmd_source", "bin", "real_bin", "version",
                    "version_state", "version_detail", "image", "image_source",
                    "expected", "expected_state", "ts")


def leg1_flip_real_invocation(aa, dp):
    """①翻转生效：声明→cmd[0]=桩；桩账本证明该命令行被真执行；face↔spawn 同源。"""
    tmp = L.tmp_root("flip")
    stub, ledger = L.make_stub(tmp / "bin", "9.9.9-pin")
    L.make_registry(tmp / "registry", KEY1, dsh_bin=str(stub))
    cmd, env, pin = L.run_prepare(
        aa, tmp, "flip", KEY1, extra_env={L.STUB_LEDGER_ENV: str(ledger)})

    C.check(bool(cmd) and cmd[0] == str(stub),
            "①声明翻转→prepare 产出 cmd[0]=桩绝对路径",
            "实得 cmd=%r 桩=%r" % (cmd, str(stub)))
    C.check(cmd[1:] == L.legacy_default_cmd(dp)[1:],
            "①参数保持文档化缺省逐元素（钉只钉二进制）",
            "实得尾参=%r" % (cmd[1:],))

    # face↔spawn 同源（KI-058 观测解药）：票面 face 必须与真执行的 cmd 同一次解析
    if pin is None:
        C.fail("①票面 dsh_pin_flip.json 在场", "缺席——face 未落 artifacts（C1 贯通面）")
    else:
        C.check(pin.get("cmd_source") == "declared",
                "①face cmd_source=declared（钉在票面可查）",
                "实得 %r" % pin.get("cmd_source"))
        C.check((pin.get("cmd") or [None])[0] == str(stub),
                "①face↔spawn 同源：face cmd[0] 与真执行 cmd[0] 相同",
                "face cmd=%r spawn cmd=%r" % (pin.get("cmd"), cmd))
        C.check(pin.get("dsh_bin_shadowed") is False,
                "①无 env 并存时无遮蔽标记",
                "实得 %r" % pin.get("dsh_bin_shadowed"))

    # 进程级「被真调」：桩账本（属被钉桩独有）记录 prepared cmd 的实参序列
    # （账本记 argv[1:]；--version 探针记录是另一形状，不混判）
    proc = L.execute_prepared(cmd, env)
    calls = []
    if ledger.is_file():
        calls = [json.loads(x) for x in
                 ledger.read_text("utf-8").splitlines() if x.strip()]
    C.check(proc.returncode == 0, "①prepared cmd 作为真进程执行成功",
            "rc=%s err=%r" % (proc.returncode, proc.stderr[:120]))
    arg_lines = [list(c) for c in calls]
    C.check(cmd[1:] in arg_lines,
            "①桩账本记录了 prepared cmd 的实参序列（账本属被钉桩独有→真调证明）",
            "账本=%r 期望含=%r" % (arg_lines[-3:], cmd[1:]))


def leg2_regression_anchor(aa, dp):
    """②回归锚（票面硬要求）：不翻转=现状逐字；face 既有键集全保持。"""
    tmp = L.tmp_root("anchor")
    L.make_registry(tmp / "registry", KEY2, dsh_bin=None)
    cmd, env, pin = L.run_prepare(aa, tmp, "anchor", KEY2)

    C.check(cmd == L.legacy_default_cmd(dp),
            "②无声明无 env→cmd 与缺省逐元素等值（裸 dsh 现状）",
            "实得 cmd=%r 期望=%r" % (cmd, L.legacy_default_cmd(dp)))
    if pin is None:
        C.fail("②票面 dsh_pin_anchor.json 在场", "缺席——face 未落 artifacts")
    else:
        C.check(pin.get("cmd_source") == "default",
                "②face cmd_source=default（缺省=完整配置非降级）",
                "实得 %r" % pin.get("cmd_source"))
        missing = [k for k in LEGACY_FACE_KEYS if k not in pin]
        C.check(not missing,
                "②face 既有键集全保持（additive 不减键）",
                "缺席键=%r 实有键=%r" % (missing, sorted(pin.keys())))
        C.check(pin.get("dsh_bin_shadowed") in (False, None),
                "②无遮蔽标记", "实得 %r" % pin.get("dsh_bin_shadowed"))


def leg3_env_shadows_declaration(aa):
    """③遮蔽点名：env 整命令胜于声明，且被压过的声明响亮点名（不静默吞）。"""
    tmp = L.tmp_root("shadow")
    env_stub, _ = L.make_stub(tmp / "bin", "9.9.9-env", name="dsh_env_stub.py")
    pin_stub, _ = L.make_stub(tmp / "bin", "9.9.9-pin", name="dsh_pin_stub3.py")
    L.make_registry(tmp / "registry", KEY3, dsh_bin=str(pin_stub))
    with L.capture_warnings() as cap:
        cmd, env, pin = L.run_prepare(
            aa, tmp, "shadow", KEY3,
            extra_env={"SANDBAR_AGENT_CMD": "%s --profile sandbar-headless"
                       % str(env_stub)})
    C.check(bool(cmd) and cmd[0] == str(env_stub),
            "③env 整命令胜：cmd[0]=env 桩", "实得 cmd=%r" % (cmd,))
    if pin is None:
        C.fail("③票面 dsh_pin_shadow.json 在场", "缺席")
    else:
        C.check(pin.get("cmd_source") == "env",
                "③face cmd_source=env", "实得 %r" % pin.get("cmd_source"))
        C.check(pin.get("dsh_bin_shadowed") is True,
                "③遮蔽标记在案（face 可查）", "实得 %r" % pin.get("dsh_bin_shadowed"))
    text = L.warn_join(cap)
    C.check(("遮蔽" in text) or ("dsh_bin" in text) or ("shadowed" in text),
            "③WARNING 点名遮蔽（锚关键词，不锁整句——KI-051）",
            "捕获 WARNING=%r" % text[:300])


def leg4_docker_ignores_declaration(aa):
    """④docker 形态不消费声明：cmd 不钉（容器内解析），镜像面承载版本，点名可见。"""
    tmp = L.tmp_root("docker")
    pin_stub, _ = L.make_stub(tmp / "bin", "9.9.9-pin", name="dsh_pin_stub4.py")
    L.make_registry(tmp / "registry", KEY4, dsh_bin=str(pin_stub))
    with L.capture_warnings() as cap:
        cmd, env, pin = L.run_prepare(
            aa, tmp, "docker", KEY4,
            extra_env={"SANDBAR_AGENT_RUNTIME": "docker",
                       "SANDBAR_AGENT_IMAGE": L.OLD_IMAGE_TAG})
    C.check(bool(cmd) and cmd[0] == "dsh",
            "④docker 形态 cmd 不钉（容器内解析，宿主绝对路径不可见）",
            "实得 cmd=%r" % (cmd,))
    if pin is None:
        C.fail("④票面 dsh_pin_docker.json 在场", "缺席")
    else:
        C.check(pin.get("mode") == "docker", "④face mode=docker",
                "实得 %r" % pin.get("mode"))
        C.check(pin.get("image") == L.OLD_IMAGE_TAG
                and pin.get("image_source") == "env",
                "④docker 版本面由镜像承载（env 指旧 tag）",
                "image=%r source=%r" % (pin.get("image"), pin.get("image_source")))
    text = L.warn_join(cap)
    C.check(("docker" in text.lower()) and ("dsh_bin" in text),
            "④WARNING 点名 docker 形态不消费 paths.dsh_bin（锚关键词）",
            "捕获 WARNING=%r" % text[:300])


def main():
    aa, ar, dp, sb = L.import_engine()
    leg1_flip_real_invocation(aa, dp)
    leg2_regression_anchor(aa, dp)
    leg3_env_shadows_declaration(aa)
    leg4_docker_ignores_declaration(aa)
    return C.finish()


if __name__ == "__main__":
    sys.exit(main())
