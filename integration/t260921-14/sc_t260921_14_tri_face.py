#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""t260921-14 场景②：dsh 三面版本自检点名（灰盒 L2，ro 池，离线秒级——宿主面走
PATH 注入桩、容器面走假 docker 桩，零真 docker、零真全局 dsh 依赖）。

intent（用户可感知）：宿主全局 dsh / 引擎侧 dsh（host=钉的二进制、docker=镜像
tag）/ 容器内实测 dsh 三面版本，票面（dsh_pin_<tag>.json 的 tri 块）与 spawn 日志
双口径可查——不一致=divergent 逐对点名、一致=不告警、判不了=incomplete 逐面点名
（判不了一致性本身就是要点名的观测缺口），且探针失败绝不挡 spawn（观测面不抢
spawn 职责）。防的正是接缝矩阵 #8「同一张票两段行为分叉」的静默漂移（KI-058
「机器层安装态≠代码态」家族）。

依据：①工单交付③「三面版本自检点名：不一致即响亮点名」+验收 L2③；②KI-058/
KI-051（点名在场+锚语义断言）；③对外契约=票面 tri 块机器可读面（faces/
consistency/divergences/incomplete/note）+「探针失败不挡启动」的观测/spawn 分工
（方案 v2 §2.2/§2.5 定稿）。

high-level steps：每条子用例独立 tmp 桩/注册表/假 docker（EnvSandbox 隔离）→直调
_prepare_agent_spawn→读票面 tri 块+捕获 WARNING：
①docker 三面互异子用例（宿主 PATH 桩=9.9.9-host / 镜像 tag 提取=9.9.9-tag / 假
  docker 实测=9.9.9-ctr）→consistency=divergent、divergences 逐对列全三面、note
  含三版本、WARNING 在场；
②一致子用例（三面同版）→consistency=consistent 且零 dsh_pin WARNING（一致面不噪声）；
③探针失败子用例（假 docker run 恒败）→consistency=incomplete、incomplete 列点名
  container、detail 留痕、spawn 照常产出 cmd/env（不挡启动）；
④face↔tri 同源子用例（host 形态+声明钉）→tri.faces.engine 与票面 face 同一
  cmd/cmd_source/bin、host 形态无容器面=缺席非失败。

intent 分工：tag-derived 弱证据语义与 TODO(T3/Q3) 关账归 developer L1；
t260916-24-dsh-face-meta 守 docker 启动链接线（真 worker 起跑链），本条守三面
对账点名语义（离线可复现的判级矩阵），不同面不互替。

三态：PASS 0 / FAIL 1 / ENV_FAIL 2。实现落地前红属预期（TDD 信号：tri 块/容器
实测探针未接线=红），arbitrate/merge 期必须绿；引擎模块不可导入=ENV_FAIL exit 2
（真 docker/真全局 dsh 缺席不 ENV_FAIL——全桩）。
"""
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import lib_t26092114 as L  # noqa: E402

# 逐子用例独立子进程跑（父进程编排 + RES 协议回传）：每条子用例的判级只取决于
# 本子用例注入的桩，不依赖引擎进程级 memo 的键控策略（灰盒绑定浅——引擎 memo 现在
# 已按输入键控：宿主面按 which() 结果逐键、tri key 含宿主 bin，回归由 L1
# test_host_global与tri_memo_换PATH换桩不串面 守；本场景的子进程隔离是独立于该
# 实现细节的护栏，memo 键控将来怎么重构都不影响本场景判级）。
LEGS = ("div", "con", "inc", "src")
_LEG_FN = {
    "div": "leg1_divergent",
    "con": "leg2_consistent_no_warning",
    "inc": "leg3_probe_failure_does_not_block",
    "src": "leg4_face_tri_same_source",
}

C = L.Checker("t260921-14-tri-face",
              res=(len(sys.argv) > 1 and sys.argv[1] in LEGS))


def tri_of(pin):
    """取票面 tri 块（键名兼容 tri_face/tri 两种拼写——锚语义不锚命名）；
    缺席返回 None（调用方点名缺席并附实有键——报错与事实同向）。"""
    if pin is None:
        return None
    for k in ("tri_face", "tri"):
        if isinstance(pin.get(k), dict):
            return pin[k]
    return None


def leg1_divergent(aa, dp=None):
    """①docker 三面互异→divergent 逐对点名（票面+日志双口径）。"""
    tmp = L.tmp_root("tri-div")
    host_stub, _ = L.make_host_path_stub(tmp / "bin", "9.9.9-host")
    fake, state = L.make_fake_docker(tmp / "bin", tmp / "fake-state")
    L.fake_docker_state(state, ctr_version="9.9.9-ctr")
    L.make_registry(tmp / "registry", "sct26092114t1", dsh_bin=None)
    with L.capture_warnings() as cap:
        cmd, env, pin = L.run_prepare(
            aa, tmp, "tridiv", "sct26092114t1",
            extra_env={"SANDBAR_AGENT_RUNTIME": "docker",
                       "SANDBAR_AGENT_IMAGE": "sandbar-agent:dsh-9.9.9-tag-s1",
                       "SANDBAR_DOCKER_BIN": str(fake),
                       "PATH": str(tmp / "bin") + os.pathsep + os.environ["PATH"]})
    tri = tri_of(pin)
    if tri is None:
        C.fail("①票面 tri 块在场",
               "缺席——实有键=%r（tri 未落票面/探针未接线）" % (sorted((pin or {}).keys()),))
        return
    faces = tri.get("faces") or {}
    C.check(tri.get("consistency") == "divergent",
            "①三面互异→consistency=divergent", "实得 %r" % tri.get("consistency"))
    C.check(faces.get("host_global", {}).get("version") == "9.9.9-host"
            and faces.get("engine", {}).get("version") == "9.9.9-tag"
            and faces.get("container", {}).get("version") == "9.9.9-ctr",
            "①三面版本各自在案（host/tag-derived/容器实测）",
            "实得 faces=%r" % faces)
    div_text = " ".join(tri.get("divergences") or [])
    C.check(all(name in div_text for name in
                ("host_global", "engine", "container")),
            "①divergences 逐对点名含全部三面",
            "实得 divergences=%r" % (tri.get("divergences"),))
    note = str(tri.get("note") or "")
    C.check(all(tok in note for tok in
                ("9.9.9-host", "9.9.9-tag", "9.9.9-ctr")),
            "①人读 note 含三版本 token", "实得 note=%r" % note[:200])
    pin_warns = [t for t in cap.texts if "[dsh_pin]" in t]
    C.check(any("不一致" in t or "divergent" in t for t in pin_warns),
            "①spawn 日志 WARNING 点名不一致（[dsh_pin] 口径，票面+日志双口径之一）",
            "捕获 [dsh_pin] WARNING=%r 全量=%r"
            % (pin_warns[:3], L.warn_join(cap)[:300]))


def leg2_consistent_no_warning(aa, dp=None):
    """②三面同版→consistent 且零 dsh_pin WARNING（一致面不噪声）。"""
    tmp = L.tmp_root("tri-con")
    host_stub, _ = L.make_host_path_stub(tmp / "bin", "9.9.9-same")
    fake, state = L.make_fake_docker(tmp / "bin", tmp / "fake-state")
    L.fake_docker_state(state, ctr_version="9.9.9-same")
    L.make_registry(tmp / "registry", "sct26092114t2", dsh_bin=None)
    with L.capture_warnings() as cap:
        cmd, env, pin = L.run_prepare(
            aa, tmp, "tricon", "sct26092114t2",
            extra_env={"SANDBAR_AGENT_RUNTIME": "docker",
                       "SANDBAR_AGENT_IMAGE": "sandbar-agent:dsh-9.9.9-same-s1",
                       "SANDBAR_DOCKER_BIN": str(fake),
                       "PATH": str(tmp / "bin") + os.pathsep + os.environ["PATH"]})
    tri = tri_of(pin)
    if tri is None:
        C.fail("②票面 tri 块在场", "缺席——实有键=%r" % sorted((pin or {}).keys()))
        return
    C.check(tri.get("consistency") == "consistent",
            "②三面同版→consistency=consistent", "实得 %r" % tri.get("consistency"))
    C.check(tri.get("divergences") == [] and tri.get("incomplete") == [],
            "②无分歧无失败面", "实得 %r / %r"
            % (tri.get("divergences"), tri.get("incomplete")))
    dsh_pin_warns = [t for t in cap.texts if "[dsh_pin]" in t]
    C.check(not dsh_pin_warns,
            "②一致面零 [dsh_pin] WARNING（consistent=info 不噪声）",
            "捕获=%r" % (dsh_pin_warns or None))


def leg3_probe_failure_does_not_block(aa, dp=None):
    """③容器探针失败→incomplete 逐面点名；spawn 照常产出（观测面不抢 spawn 职责）。
    镜像 tag 与宿主面同版（dsh-9.9.9-host-s1）：唯容器面失败→无版本分歧+有失败面
    =incomplete（divergent 只在有版本分歧时优先）。"""
    tmp = L.tmp_root("tri-inc")
    host_stub, _ = L.make_host_path_stub(tmp / "bin", "9.9.9-host")
    fake, state = L.make_fake_docker(tmp / "bin", tmp / "fake-state")
    L.fake_docker_state(state, ctr_version=None, run_fails=True)
    L.make_registry(tmp / "registry", "sct26092114t3", dsh_bin=None)
    cmd, env, pin = L.run_prepare(
        aa, tmp, "triinc", "sct26092114t3",
        extra_env={"SANDBAR_AGENT_RUNTIME": "docker",
                   "SANDBAR_AGENT_IMAGE": "sandbar-agent:dsh-9.9.9-host-s1",
                   "SANDBAR_DOCKER_BIN": str(fake),
                   "PATH": str(tmp / "bin") + os.pathsep + os.environ["PATH"]})
    tri = tri_of(pin)
    if tri is None:
        C.fail("③票面 tri 块在场", "缺席——实有键=%r" % sorted((pin or {}).keys()))
        return
    C.check(tri.get("consistency") == "incomplete",
            "③探测失败→consistency=incomplete（不静默当一致）",
            "实得 %r" % tri.get("consistency"))
    inc_text = " ".join(tri.get("incomplete") or [])
    C.check("container" in inc_text,
            "③incomplete 逐面点名 container", "实得 %r" % (tri.get("incomplete"),))
    ctr = (tri.get("faces") or {}).get("container") or {}
    C.check(ctr.get("version_state") == "error"
            and bool(str(ctr.get("version_detail") or "").strip()),
            "③容器面 error+detail 留痕", "实得 %r" % ctr)
    C.check(bool(cmd) and bool(env),
            "③探针失败不挡 spawn：cmd/env 照常产出", "cmd=%r" % (cmd,))
    C.check(cmd[0] == "dsh" and (pin or {}).get("version") == "9.9.9-host",
            "③引擎面不受容器探针失败牵连（tag-derived 仍可判）",
            "cmd[0]=%r face version=%r" % (cmd[0], (pin or {}).get("version")))


def leg4_face_tri_same_source(aa, dp):
    """④face↔tri 同源（host 形态+声明钉）：tri.faces.engine=票面同一 face；
    host 形态无容器面=缺席非失败。"""
    tmp = L.tmp_root("tri-src")
    host_stub, _ = L.make_host_path_stub(tmp / "bin", "9.9.9-host")
    pin_stub, _ = L.make_stub(tmp / "bin", "9.9.9-pin", name="dsh_pin_stub_t4.py")
    L.make_registry(tmp / "registry", "sct26092114t4", dsh_bin=str(pin_stub))
    cmd, env, pin = L.run_prepare(
        aa, tmp, "trisrc", "sct26092114t4",
        extra_env={"PATH": str(tmp / "bin") + os.pathsep + os.environ["PATH"]})
    tri = tri_of(pin)
    if tri is None:
        C.fail("④票面 tri 块在场", "缺席——实有键=%r" % sorted((pin or {}).keys()))
        return
    engine = (tri.get("faces") or {}).get("engine") or {}
    C.check(engine.get("cmd") == (pin or {}).get("cmd")
            and engine.get("cmd_source") == "declared"
            and engine.get("bin") == str(pin_stub),
            "④tri.faces.engine 与票面 face 同一（cmd/cmd_source/bin）",
            "engine=%r 票面 cmd=%r" % (engine, (pin or {}).get("cmd")))
    C.check(bool(cmd) and cmd[0] == str(pin_stub),
            "④spawn 真用被钉二进制（同源的行为半边）", "实得 cmd=%r" % (cmd,))
    C.check("container" not in (tri.get("faces") or {}),
            "④host 形态无容器面=缺席非失败", "实有面=%r" % sorted((tri.get("faces") or {}).keys()))
    C.check(tri.get("consistency") == "divergent",
            "④宿主全局≠被钉二进制→divergent（试验窗口的预期点名形态）",
            "实得 %r" % tri.get("consistency"))


def main():
    if len(sys.argv) > 1 and sys.argv[1] in _LEG_FN:
        # 子用例模式：跑单条子用例，RES 协议回传，exit 码=finish 优先级
        aa, ar, dp, sb = L.import_engine()
        globals()[_LEG_FN[sys.argv[1]]](aa, dp)
        return C.finish(silent=True)
    # 父进程编排：逐子用例子进程，RES 行回传聚合；子进程诊断走 stderr 透传
    for leg in LEGS:
        p = subprocess.run([sys.executable, "-B", str(Path(__file__)), leg],
                           capture_output=True, text=True, timeout=300)
        got_rows = False
        for line in (p.stdout or "").splitlines():
            if not line.startswith("RES\t"):
                continue
            got_rows = True
            _, st, name, detail = (line.split("\t") + ["", ""])[:4]
            if st == "pass":
                C.ok(name, detail)
            elif st == "env_fail":
                C.env_fail_leg(name, detail)
            elif st == "na":
                C.na(name, detail)
            else:
                C.fail(name, detail)
        if p.returncode == 2 and not got_rows:
            C.env_fail_leg("子用例 %s 环境红（引擎不可导入等）" % leg,
                           (p.stderr or "")[-300:])
        elif p.returncode == 1 and not got_rows:
            C.fail("子用例 %s 异常退出（无逐条判定回传——子进程崩在判定前）" % leg,
                   "rc=1 stderr=%r" % ((p.stderr or "")[-400:],))
        elif p.returncode not in (0, 1, 2):
            C.fail("子用例 %s 异常退出" % leg,
                   "rc=%s stderr=%r" % (p.returncode, (p.stderr or "")[-300:]))
        if p.stderr:
            sys.stderr.write("[child %s] %s\n" % (leg, p.stderr[-500:]))
    return C.finish()


if __name__ == "__main__":
    sys.exit(main())
