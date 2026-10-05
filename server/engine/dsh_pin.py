"""dsh 版本面（钉路径）解析与自检 —— t260916-24（dsh-upgrade epic T4）。

背景：引擎 spawn 的 dsh 命令此前在 import 时静默解析（agent_activities.DSH_CMD），
「本 worker 用的 dsh 是哪个版本、从哪来」无处可查，升级切流只能靠猜。本模块把
版本面变成可观测、可对照、可响亮三件事：

- 可观测：dsh_face_payload() 产出统一 face（mode/cmd/bin/real_bin/version/来源/
  镜像/期望版本），worker 启动写进 meta JSON、首票落票面 artifacts 并进日志；
- 可对照：SANDBAR_DSH_EXPECTED_VERSION 非空时与版本比对，不符 = mismatch 响亮
  （告警级，每次 spawn 都提，票面留痕）；SANDBAR_DSH_STRICT=1 时升格硬闸
  （raise，缺省 off = 不破现状）；
- 可解耦：host 形态命令走 SANDBAR_AGENT_CMD 显式钉（既有旋钮，语义不变），docker
  形态镜像走 SANDBAR_AGENT_IMAGE（既有旋钮，agent_runtime 消费）——升级只切引擎
  侧旋钮，console(3099) 用的全局 dsh 不受影响（红线 #1 自动满足）。

旋钮一览（全部普通 env，缺省=现行为）：
- SANDBAR_AGENT_CMD           host 形态整命令（shlex），缺省 "dsh --profile sandbar-headless"
- paths.dsh_bin（声明键，t260921-14）host 形态只钉二进制路径（项目 per-key 条目
  paths 节；词法校验/锚点/可执行判定归 shared.project_paths 家族，本模块收已校验
  的绝对路径串），缺省=裸 `dsh` 走 PATH（回归锚）；与 SANDBAR_AGENT_CMD 并存=
  env 胜 + dsh_bin_shadowed=True（调用方响亮点名遮蔽）
- SANDBAR_AGENT_IMAGE         docker 形态镜像 tag，缺省 agent_runtime.DEFAULT_AGENT_IMAGE
                              （由调用方传参注入；本模块刻意零仓内依赖——agent_runtime
                              禁 import shared/agent_activities 一族，反向同样不 import）
- SANDBAR_DSH_EXPECTED_VERSION 期望版本（host=实证版；docker=tag 提取版）；空=只记录不比对
- SANDBAR_DSH_STRICT          "1"=mismatch 升格硬闸（raise）；缺省只告警

docker 形态版本自镜像 tag 按 `dsh-<version>-s<seq>` 约定提取，标注 tag-derived
非实证；T3（t260921-14）落地 tri_face_payload 三面自检：宿主全局 / 引擎生效
（=spawn 同源 face）/ 容器内实测 `dsh --version`（探针=agent_runtime
.probe_image_dsh_version，由调用方注入——本模块零仓内依赖），不一致响亮点名，
原 TODO(T3/Q3) 关账。

fail-closed 边界（与调用方的分工）：
- 坏 SANDBAR_AGENT_CMD（shlex 解析失败/空命令）→ DshPinError 响亮点名——与旧
  import 时炸同等响亮，但文案带旋钮名与原文；
- `<dsh> --version` 跑不出来（缺文件/非零/超时/输出畸形）→ 不抛，face 里
  version_state=error + detail 照记（观测面不挡启动；真正 spawn 时的失败自有
  spawn 路径响亮）；
- mode 非法值 → face 记 "unknown" 不炸（fail-closed 归 agent_runtime.runtime_mode
  的 spawn 路径，观测面不抢职责、不静默改名）。

版本输出契约：`dsh --version` 单行版本样 token（260916 实测输出 "0.1.1-rc.2"）。
空/多行/非版本样 = error（升级对账语境宁红勿漏：输出形态漂移本身就是接缝信号）。
"""

from __future__ import annotations

import os
import re
import shlex
import signal
import subprocess
import time
from typing import Any, Dict, List, Optional

DEFAULT_DSH_CMD_TEXT = "dsh --profile sandbar-headless"
ENV_AGENT_CMD = "SANDBAR_AGENT_CMD"
ENV_AGENT_IMAGE = "SANDBAR_AGENT_IMAGE"
ENV_EXPECTED = "SANDBAR_DSH_EXPECTED_VERSION"
ENV_STRICT = "SANDBAR_DSH_STRICT"
ENV_RUNTIME = "SANDBAR_AGENT_RUNTIME"
RUNTIME_MODES = ("host", "docker")
PROBE_TIMEOUT_DEFAULT_SEC = 10.0

# 镜像 tag 约定：sandbar-agent:dsh-<version>-s<seq>（build_agent_image.sh 产出）；
# 贪婪捕获让「版本段自身含 -s」时仍锚定最后一个 -s<数字> 为序号
_IMAGE_TAG_RE = re.compile(r"^sandbar-agent:dsh-(.+)-s\d+$")
# 版本样 token：semver 带预发布段（0.1.1-rc.2）
_VERSION_RE = re.compile(r"^\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?$")


class DshPinError(RuntimeError):
    """版本面解析/硬闸失败（响亮点名，绝不静默回落）。"""


def _env(env) -> Dict[str, str]:
    return os.environ if env is None else env


def resolve_dsh_cmd(env: Optional[Dict[str, str]] = None,
                    dsh_bin: Optional[str] = None) -> Dict[str, Any]:
    """解析 host 形态 dsh 命令。返回 {"cmd": [...], "source": "env"|"default"|"declared",
    "raw": str, "dsh_bin_shadowed": bool}。

    优先级（t260921-14）：SANDBAR_AGENT_CMD（env 整命令，最显式）> paths.dsh_bin 声明
    （只钉二进制，参数保持文档化缺省逐元素）> 缺省裸 `dsh`（与 agent_activities.DSH_CMD
    旧缺省逐元素等值，回归锚）。env 与声明并存 = env 胜 + dsh_bin_shadowed=True（调用方
    响亮点名遮蔽，不静默吞掉任何一边）。坏 shlex / 空命令 → DshPinError（点名旋钮名与
    原文）；dsh_bin 只收 shared.dsh_bin_for_spawn 已校验的路径串（词法/锚点/可执行判定
    归声明家族，本模块不重复第二套）。
    """
    env = _env(env)
    raw = (env.get(ENV_AGENT_CMD) or "").strip()
    if raw:
        try:
            cmd = shlex.split(raw)
        except ValueError as e:
            raise DshPinError("%s 解析失败（shlex：%s）：%r" % (ENV_AGENT_CMD, e, raw))
        if not cmd or not cmd[0]:
            raise DshPinError("%s 解析为空命令：%r" % (ENV_AGENT_CMD, raw))
        return {"cmd": cmd, "source": "env", "raw": raw,
                "dsh_bin_shadowed": bool(dsh_bin)}
    if dsh_bin:
        tail = shlex.split(DEFAULT_DSH_CMD_TEXT)[1:]  # 缺省参数逐元素保持
        return {"cmd": [dsh_bin] + tail, "source": "declared",
                "raw": dsh_bin, "dsh_bin_shadowed": False}
    return {"cmd": shlex.split(DEFAULT_DSH_CMD_TEXT),
            "source": "default", "raw": DEFAULT_DSH_CMD_TEXT,
            "dsh_bin_shadowed": False}


def is_dsh_runner(cmd0: Optional[str]) -> bool:
    """这条命令的首 token 是不是 dsh runner 本体（t260921-14）：裸名与钉死的绝对/相对
    路径都算（basename 判定），桩/其他可执行体不算。泳道 .dsh 预检等判定点共用——
    防钉成绝对路径后判定点被静默跳过（t260916-28 不变量在钉态不回归）。"""
    if not cmd0:
        return False
    return os.path.basename(str(cmd0)) == "dsh"


def probe_dsh_version(cmd0: str, timeout: float = PROBE_TIMEOUT_DEFAULT_SEC,
                      env: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """跑 `<dsh> --version` 实证版本。

    返回 {"version": str|None, "state": "ok"|"error", "detail": str}。
    失败（缺文件/非零退出/超时/输出非单行版本样）= error + detail 点名；
    三条路径（正常/超时/调用方异常）都全终态回收（kill 进程组 + wait 收割）。
    """
    full_env = dict(_env(env))
    try:
        proc = subprocess.Popen(
            [cmd0, "--version"], stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL, env=full_env, start_new_session=True)
    except OSError as e:
        return {"version": None, "state": "error",
                "detail": "cannot start %s --version: %s" % (cmd0, e)}
    killed = False
    try:
        out, _ = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        _kill_proc_group(proc)
        killed = True
        return {"version": None, "state": "error",
                "detail": "%s --version timed out (>%ss), process group reaped" % (cmd0, timeout)}
    except BaseException:
        _kill_proc_group(proc)
        raise
    text = (out or b"").decode("utf-8", "replace").strip()
    if proc.returncode != 0:
        return {"version": None, "state": "error",
                "detail": "%s --version exit code %s, output=%r" % (cmd0, proc.returncode, text[:200])}
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if len(lines) != 1 or not _VERSION_RE.match(lines[0]):
        return {"version": None, "state": "error",
                "detail": "%s --version output is not a single version-like line (%d lines): %r" % (cmd0, len(lines), text[:200])}
    if killed:  # pragma: no cover - 防御位，communicate 正常返回时不会置位
        return {"version": None, "state": "error", "detail": "process reaped, output untrusted"}
    return {"version": lines[0], "state": "ok",
            "detail": "%s verified %s" % (cmd0, lines[0])}


def _kill_proc_group(proc: subprocess.Popen) -> None:
    """进程组级终止 + 等待收割（全终态：正常/超时/异常三路共用）。"""
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    except OSError:
        try:
            proc.kill()
        except OSError:
            pass
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:  # pragma: no cover - SIGKILL 后不该发生
        pass


def image_tag_version(image: str) -> Dict[str, Any]:
    """从镜像 tag 提取 dsh 版本（约定 sandbar-agent:dsh-<version>-s<seq>）。

    返回 {"version": str|None, "state": "ok"|"unknown", "detail": str}；
    异形 tag = unknown 不炸（tag 只是弱证据，异形仅意味着「无法从 tag 判版」）。
    """
    m = _IMAGE_TAG_RE.match(image or "")
    if not m:
        return {"version": None, "state": "unknown",
                "detail": "image tag %r does not follow the dsh-<version>-s<seq> convention, "
                          "version cannot be derived from the tag (tag-derived is not proof; "
                          "in-container measurement is covered by the tri-face self-check, t260921-14)" % image}
    ver = m.group(1)
    if not _VERSION_RE.match(ver):
        return {"version": None, "state": "unknown",
                "detail": "image tag %r extracted segment %r is not version-like" % (image, ver)}
    return {"version": ver, "state": "ok",
            "detail": "image tag extracted %s (tag-derived is not proof; in-container measurement "
                      "is covered by the tri-face self-check, t260921-14)" % ver}


def expected_state_of(version: Optional[str], env: Optional[Dict[str, str]] = None) -> str:
    """期望版本比对（纯函数）：unset（未配）/ match / mismatch。"""
    env = _env(env)
    expected = (env.get(ENV_EXPECTED) or "").strip()
    if not expected:
        return "unset"
    return "match" if version == expected else "mismatch"


def enforce_expected(face: Dict[str, Any], env: Optional[Dict[str, str]] = None) -> str:
    """对已算好的 face 做期望对照与硬闸判定。返回一行人读 note（供日志/票面）。

    mismatch 且 SANDBAR_DSH_STRICT=1 → raise DshPinError（硬闸，升级切错版本时
    宁可整段失败也不静默跑错版本）；缺省只返回 note 由调用方 warning。
    """
    env = _env(env)
    state = face.get("expected_state") or expected_state_of(face.get("version"), env)
    expected = (env.get(ENV_EXPECTED) or "").strip()
    note = face_note(face)
    if state == "mismatch":
        if (env.get(ENV_STRICT) or "").strip() == "1":
            raise DshPinError(
                "dsh 版本与预期不符（硬闸）：实际=%r 期望=%r（%s=%r）。升级切流走错版本，"
                "拒绝开工；核对本 worker 的 %s/%s" % (face.get("version"), expected,
                                                     ENV_EXPECTED, expected,
                                                     ENV_AGENT_CMD, ENV_AGENT_IMAGE))
        return note + " 【mismatch】期望=%s 不符——响亮告警（设 %s=1 升格硬闸）" % (expected, ENV_STRICT)
    if state == "match":
        return note
    return note


def face_note(face: Dict[str, Any]) -> str:
    """版本面一行人读文案（日志/票面用，可查询字段全部在场）。"""
    version = face.get("version")
    vstate = face.get("version_state")
    vtag = {("ok", "host"): "实证", ("ok", "docker"): "tag-derived"}.get((vstate, face.get("mode")), vstate)
    cmd = " ".join(face.get("cmd") or [])
    image = face.get("image")
    est = face.get("expected_state")
    parts = ["mode=%s" % face.get("mode")]
    if face.get("mode") == "docker":
        parts.append("image=%s(来源=%s) 版本=%s(%s)"
                     % (image, face.get("image_source"), version or "?", vtag))
    else:
        parts.append("cmd='%s'(来源=%s) bin=%s(→%s) 版本=%s(%s)"
                     % (cmd, face.get("cmd_source"), face.get("bin"),
                        face.get("real_bin") or "?", version or "?", vtag))
    if vstate == "error" and face.get("version_detail"):
        parts.append("细节=%s" % face["version_detail"])
    parts.append("期望=%s(%s)" % ((env_expected(face)) or "未配", est))
    return "dsh 版本面：" + " ".join(parts)


def env_expected(face: Dict[str, Any]) -> str:
    """face 携带的期望值（便于文案拼装；不读 env）。"""
    return face.get("expected") or ""


def dsh_face_payload(mode: Optional[str] = None,
                     env: Optional[Dict[str, str]] = None,
                     default_image: Optional[str] = None,
                     probe_timeout: float = PROBE_TIMEOUT_DEFAULT_SEC,
                     probe: bool = True,
                     resolved: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """统一版本面。worker 启动 / 首票 spawn 各取一次（调用方自做 once 缓存）。

    mode：host|docker；None → 读 SANDBAR_AGENT_RUNTIME（缺省 host；非法值记
    "unknown" 不炸——fail-closed 归 agent_runtime 的 spawn 路径）。
    default_image：docker 形态的缺省镜像（调用方传 agent_runtime.DEFAULT_AGENT_IMAGE，
    保持本模块零仓内依赖）。
    probe=False：跳过 `--version` 子进程（docker 形态天然跳过；供纯形状 UT）。
    resolved（t260921-14，C1 贯通）：调用方已解析的 dsh 命令结果（=spawn cmd 的同一
    份 resolve_dsh_cmd 产物）——传入时 host 面 cmd/cmd_source/bin/dsh_bin_shadowed
    直接取它，version 探测于 cmd[0]（即被钉二进制），face↔spawn 同源是结构事实；
    缺省 None=内部 env 锚解析（worker 启动面现状，逐字节不变）。
    坏 SANDBAR_AGENT_CMD → DshPinError（响亮，对齐旧 import 行为）。
    """
    env = _env(env)
    if mode is None:
        raw = (env.get(ENV_RUNTIME) or "").strip().lower()
        mode = raw if raw in RUNTIME_MODES else ("host" if not raw else "unknown")
    elif mode not in RUNTIME_MODES:
        mode = "unknown"  # 显式非法值同样归 unknown（观测面不抢 spawn 路径的 fail-closed）
    face: Dict[str, Any] = {
        "mode": mode,
        "cmd": None, "cmd_source": None, "bin": None, "real_bin": None,
        "dsh_bin_shadowed": False,
        "version": None, "version_state": "not-probed", "version_detail": "",
        "image": None, "image_source": None,
        "expected": (env.get(ENV_EXPECTED) or "").strip(),
        "ts": int(time.time()),
    }
    if mode == "docker":
        image = (env.get(ENV_AGENT_IMAGE) or "").strip()
        face["image"] = image or default_image
        face["image_source"] = "env" if image else ("default" if face["image"] else None)
        if face["image"]:
            tag = image_tag_version(face["image"])
            face["version"] = tag["version"]
            face["version_state"] = tag["state"] if tag["state"] == "ok" else "unknown"
            face["version_detail"] = tag["detail"]
        else:
            face["version_state"] = "unknown"
            face["version_detail"] = "无镜像可判（env 与缺省皆空）"
    else:
        resolved = resolved or resolve_dsh_cmd(env)  # 坏 shlex 在此响亮抛出
        face["cmd"] = resolved["cmd"]
        face["cmd_source"] = resolved["source"]
        face["dsh_bin_shadowed"] = bool(resolved.get("dsh_bin_shadowed"))
        face["bin"] = resolved["cmd"][0]
        if os.path.sep in face["bin"] or "/" in face["bin"]:
            real = os.path.realpath(face["bin"])
            face["real_bin"] = real if os.path.exists(real) else None
        else:
            import shutil
            face["real_bin"] = shutil.which(face["bin"])  # PATH 内二进制：解析真实落点
        if probe:
            pv = probe_dsh_version(face["bin"], timeout=probe_timeout, env=env)
            face["version"] = pv["version"]
            face["version_state"] = pv["state"]
            face["version_detail"] = pv["detail"]
    face["expected_state"] = expected_state_of(face["version"], env)
    return face


def tri_face_payload(engine_face: Dict[str, Any],
                     host_bin: Optional[str],
                     host_probe: Optional[Dict[str, Any]],
                     container_probe: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """三面版本自检（t260921-14 交付③，接缝矩阵 #8「宿主/容器行为分叉」的点名机）。

    engine_face 必须是 spawn 实际执行的同一 face（dsh_face_payload(resolved=…) 的
    产物，face↔spawn 同源——C1 贯通；tri 不做第二次解析，engine 面与票面
    dsh_pin_<tag>.json 是同一份数据）。host_probe / container_probe 是调用方探得的
    {"version","state","detail"}（探针归调用方：宿主=probe_dsh_version(which("dsh"))，
    容器=agent_runtime.probe_image_dsh_version——本模块零仓内依赖）。纯函数：只组装
    与点名，不做 IO、不抛。

    consistency 三态：
      consistent = 所有可判面版本一致（且无失败面）；
      divergent  = 至少两面版本可判且不等（divergences 逐对列出）；
      incomplete = 无版本分歧但存在探测失败/缺席面（incomplete 逐面点名——判不了
                   一致性本身就是要点名的观测缺口，不静默当一致）。
    container 面仅 docker 形态在（host 形态无容器面，faces 不含该键=缺席非失败）。
    """
    def _of(p, k, default=None):
        return (p or {}).get(k, default)

    engine_state = engine_face.get("version_state")
    faces: Dict[str, Any] = {
        "host_global": {"bin": host_bin,
                        "version": _of(host_probe, "version"),
                        "version_state": _of(host_probe, "state"),
                        "version_detail": _of(host_probe, "detail", "")},
        "engine": {"cmd": engine_face.get("cmd"), "cmd_source": engine_face.get("cmd_source"),
                   "bin": engine_face.get("bin"), "version": engine_face.get("version"),
                   "version_state": engine_state,
                   "dsh_bin_shadowed": bool(engine_face.get("dsh_bin_shadowed"))},
    }
    if container_probe is not None:
        faces["container"] = {"version": _of(container_probe, "version"),
                              "version_state": _of(container_probe, "state"),
                              "version_detail": _of(container_probe, "detail", "")}
    known = {"host_global": _of(host_probe, "version"), "engine": engine_face.get("version")}
    if container_probe is not None:
        known["container"] = _of(container_probe, "version")
    judged = {k: v for k, v in known.items() if v}
    failed = []
    if _of(host_probe, "state") != "ok":
        failed.append("host_global(%s)" % _of(host_probe, "state", "absent"))
    if engine_state != "ok":
        failed.append("engine(%s)" % (engine_state or "absent"))
    if container_probe is not None and _of(container_probe, "state") != "ok":
        failed.append("container(%s)" % _of(container_probe, "state", "absent"))
    divergences = []
    items = sorted(judged.items())
    for i in range(len(items)):
        for j in range(i + 1, len(items)):
            if items[i][1] != items[j][1]:
                divergences.append("%s=%s != %s=%s" % (items[i][0], items[i][1],
                                                       items[j][0], items[j][1]))
    if divergences:
        consistency = "divergent"
    elif failed:
        consistency = "incomplete"
    else:
        consistency = "consistent"
    ver_line = " ".join("%s=%s" % (k, v or "?") for k, v in items) or "（无可判版本）"
    if consistency == "divergent":
        note = "dsh 三面版本自检【不一致】：%s ｜ %s" % (ver_line, "；".join(divergences))
    elif consistency == "incomplete":
        note = "dsh 三面版本自检【不完整】：%s ｜ 判不了的面：%s" % (ver_line, "；".join(failed))
    else:
        note = "dsh 三面版本自检【一致】：%s" % ver_line
    return {"faces": faces, "consistency": consistency,
            "divergences": divergences, "incomplete": failed, "note": note}
