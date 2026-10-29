#!/usr/bin/env python3
"""Shared helper for three-state scenario verdicts (t260904-12: no SKIP inside
the integration gate, final ruling section 7.3).

Scenario-level states are only PASS / FAIL / ENV_FAIL / N/A (leg-level); the
exit-code contract:
  0 = all green; 1 = some FAIL (product red, including all-legs N/A — nothing
      to verify is a scenario design/coverage problem, fix the scenario rather
      than the environment);
  2 = some ENV_FAIL (environment red: nothing got verified, the cause belongs
      to the environment, and the SUMMARY/output names what is missing).

Discipline (against a SKIP-hole comeback):
- a missing environment (dependency, test stage, credentials, playwright, ...)
  always goes through env_fail(), never exit 0;
- na() is only for legs conditioned on **system state** (not on the test
  environment, e.g. "with this feature flag absent the leg has no object");
  a scenario whose legs are all N/A is product red per the contract (exit 1) —
  fail_if_all_na() below is where that verdict is enforced;
- malformed/exception paths are equally not allowed to go silently green:
  prefer an explicit FAIL red.

mjs-side equivalent = integration/t260904-05/lib_browser.mjs makeResults()
(same state vocabulary pass/fail/env_fail/na + summarize() with the same
exit-code priority).
"""
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

EXIT_PASS = 0
EXIT_FAIL = 1
EXIT_ENV_FAIL = 2


def env_fail(reason):
    """Missing environment: print what exactly is absent, exit 2 (ENV_FAIL,
    environment red). Never exit 0."""
    print("ENV_FAIL: %s" % reason)
    sys.exit(2)


def na(reason):
    """A leg conditioned on system state has no object (not a missing
    environment). Only emits the marker; whether the scenario is all-N/A is
    judged uniformly by fail_if_all_na() over the scenario's leg table."""
    print("N/A: %s" % reason)


def fail_if_all_na(total_legs, na_legs, scenario=""):
    """A scenario whose legs are all N/A is red (product red, exit 1): having
    nothing to verify is a scenario design/coverage problem.
    total_legs = total legs in the scenario; na_legs = how many are N/A."""
    if total_legs > 0 and na_legs >= total_legs:
        print("FAIL: 全部子用例 N/A——场景无可验对象（设计/覆盖问题，修场景而非补环境）%s" % scenario)
        sys.exit(1)


# ======================================================================================
# 260930（真票 t260930-09 实况；宿主令「继承的收窄旋钮必须清零」）：窄化旋钮的单点清理
# ======================================================================================
# 病根：泳道轮的闸环境里带着**本轮收窄面**（SANDBAR_SCENARIO_ONLY=<改动面>，引擎
# t260930 起默认走面计划收窄）。场景/夹具自己再起执行器或闸时，**子进程继承**了它 →
# 内层被收窄成不含夹具点名的面 → 断言成片红（实测 5 条：t260913-03-* ×4 +
# t260916-25-stage-console-selfcheck-red）。与票的改动无关。
#
# 纪律（本函数即纪律的机械化身）：**被测面必须由夹具显式声明，绝不继承外层泳道轮的
# 收窄/策略旋钮**。清理=先剥再注入：调用方要用哪一档，自己在 extra 里写明。
NARROWING_ENV_PREFIXES = (
    "SANDBAR_SCENARIO_",   # 收窄面（ONLY）/池排除/台账目录…
    "SANDBAR_INTEG_",      # 跑锁路径、台账来源、允许并发、批次预算…
    "SANDBAR_KNOWN_RED_",  # 在册红豁免开关与名册路径
    "SANDBAR_GATE_",       # 基线开关及其依赖软链
    "SANDBAR_SUPPLY_",     # 供给段预算/等待上限
)
#: **具名**的台面收窄注入（引擎每轮往执行器 env 里塞的那两个；t260923 C 自愈清扫半径）。
#: 为什么**不**用 `SANDBAR_STAGE_` 前缀（260930 修正）：该前缀下有**共享缝**——
#: `SANDBAR_STAGE_BATCH`（批台名，run_scenarios 注入给批消费者条目，消费缝
#: lib_gate/with_stage.sh 据此走共享台 ns）与 `SANDBAR_STAGE_*`（夹具自己的等待/租约
#: 旋钮）。一句话清掉会把「共享/夹具声明的档」一起剥掉=改了被测面（如
#: t260921-06/run_inner_runner.py 的调用方明确注入 BATCH 的语义）。收窄面只清
#: 「引擎每轮注入的收窄件」，**不是**整族台面旋钮。
NARROWING_ENV_NAMES = (
    "SANDBAR_POOL_CONC",                     # 并发宽度（进环境指纹、影响判定宽度）
    "SANDBAR_CONC_POOLS",                    # 池并发声明
    "SANDBAR_UNDECLARED_POLICY",             # 调用方身份策略（影响引擎写操作闸）
    "SANDBAR_STAGE_SWEEP_ORPHANS",           # 引擎每轮注入：挂点孤儿清扫总闸
    "SANDBAR_STAGE_SWEEP_ORPHAN_PREFIX",     # 引擎每轮注入：清扫半径前缀
    # t261017-10（宿主令 261012 实测）：台账绿行复用的 kill switch 也是轮级行为钉——
    # 线轮自钉 SANDBAR_LEDGER_REUSE=0 时，前缀族剥不掉（裸名），漏进夹具自起的
    # 执行器子进程，复用/Run-record 被测面被外层环境翻转成片假红。同纪律：要测
    # 复用行为（含 kill switch 面）的夹具用 extra 显式声明自己那一档。
    "SANDBAR_LEDGER_REUSE",                  # 台账复用 kill switch（行为钉，非收窄面）
)
# 261004（执行器请求 -0023，t261004-26）：继承的**调用方身份**与本表同族同纪律——
# ticket.py/client.py 的 spawn 链往下注入 SANDBAR_CALLER_PROJECT +
# SANDBAR_CALLER_IDENTITY_SRC；夹具自己起票入口时不剥它，继承来的身份会让跨项目闸
# 抢在要断言的具名面之前一步拒收（79e4cb6 手修的两条场景即此族，此处收编为纪律）。
# 判据同样是「被测面由夹具声明，绝不继承」：要测身份闸本身，用 extra 显式注入敌对值。
INHERITED_IDENTITY_NAMES = (
    "SANDBAR_CALLER_PROJECT",
    "SANDBAR_CALLER_IDENTITY_SRC",
)


def _inherited_names() -> tuple:
    """清理时要剥的具名旋钮全集（收窄 + 身份）——四个清理出口共用一份。"""
    return NARROWING_ENV_NAMES + INHERITED_IDENTITY_NAMES


def narrow_env_names() -> tuple:
    """被清理的旋钮名全集（前缀 + 具名）——守卫/自证/文档共用一份。"""
    return (NARROWING_ENV_PREFIXES, NARROWING_ENV_NAMES)


def inherited_narrowing_knobs(env=None) -> dict:
    """env 里**还带着**的继承旋钮（收窄 + 调用方身份；诊断/守卫自证用；空 dict = 干净）。"""
    src = os.environ if env is None else env
    named = _inherited_names()
    out = {}
    for k, v in src.items():
        if k in named or k.startswith(NARROWING_ENV_PREFIXES):
            out[k] = v
    return out


def clean_narrowing_env(extra=None, base=None) -> dict:
    """副本 env：剥掉**继承来的窄化/策略旋钮与调用方身份**，再并入调用方显式声明的 extra。

    所有「场景/夹具自己起执行器/闸/票入口」的地方都必须走这里（守卫=integration/
    lint_tests.py L12）：子进程只该看见夹具自己声明的那一档，绝不继承外层泳道轮的
    收窄面或身份（SANDBAR_CALLER_PROJECT 族，t261004-26 起）。"""
    env = dict(os.environ if base is None else base)
    named = _inherited_names()
    for k in list(env):
        if k in named or k.startswith(NARROWING_ENV_PREFIXES):
            env.pop(k, None)
    for k, v in (extra or {}).items():
        env[str(k)] = str(v)
    return env


# ======================================================================================
# t261017-10（宿主令 261012 规格②「具名认领」）：夹具剥掉与自己被测面相矛盾的继承钉时，
# 必须在自己的 stdout 通道**点名**剥了哪些（名=值），不许无声剥（红得没头绪）也不许
# 假绿（继承值悄悄改了被测面）。输出走夹具自己的 stdout——绝不写进被夹具捕获的
# 子进程流，解析面字节兼容不受扰。空 env=静默（无矛盾可认领）。
# ======================================================================================
OWNED_ENV_NOTE_PREFIX = "INTEG_ENV_OWNED:"


def owned_env_note(names, env=None, out=None):
    """点名列出 env 里还在的继承钉（限 names 全集内），返回所发行文；干净 env 返回 None。

    畸形值（空串/空白/任意字节）原样点名为 `名=值`——认领面是「剥了什么」的诚实
    声明，不做值断言；值判断归各夹具自己的子用例。"""
    src = os.environ if env is None else env
    knobs = inherited_narrowing_knobs(src)
    hits = ["%s=%s" % (k, knobs[k]) for k in names if k in knobs]
    if not hits:
        return None
    line = "%s scrubbed inherited %s — this case owns its env" % (
        OWNED_ENV_NOTE_PREFIX, ", ".join(hits))
    print(line, file=out if out is not None else sys.stdout, flush=True)
    return line


class no_narrowing_env:
    """上下文管理器：**进程内**调用执行器/闸时（`rs.main()` / `verify_lane.run()`），
    临时把继承来的收窄旋钮从 os.environ 摘掉，退出时原样恢复。

    为什么需要：进程内调用读的是本进程 env，`clean_narrowing_env` 那种「传给子进程」的
    写法对它无效。用法：`with no_narrowing_env(): rc = rs.main()`。"""

    def __init__(self, extra=None):
        self.extra = dict(extra or {})
        self._saved = {}
        self._added = []

    def __enter__(self):
        named = _inherited_names()
        for k in list(os.environ):
            if k in named or k.startswith(NARROWING_ENV_PREFIXES):
                self._saved[k] = os.environ.pop(k)
        for k, v in self.extra.items():
            os.environ[str(k)] = str(v)
            self._added.append(str(k))
        return self

    def __exit__(self, *exc):
        for k in self._added:
            os.environ.pop(k, None)
        os.environ.update(self._saved)
        return False


# ======================================================================================
# t261002-14：双语言收窄旋钮清单的**机械互锁**（纯函数，文本进/报告出）。
# 病根：本文件的 NARROWING_ENV_PREFIXES/NAMES 与 lib_env.mjs 的 NARROWING_PREFIXES/
# NAMES 是同一词表的两份手抄（260930 修正时已经对齐过一次——纯靠人盯）。本函数把
# 「两份必须逐元素相同」变成可机械判定的真值，消费方=integration/lint_tests.py L14
# 与单测（单测用夹具文本钉「单侧独改必被抓」的漂移面）。
# fail-closed 纪律：任一侧提不出字面量（改名/改形态/语法坏）一律产报告行，**绝不**
# 返回空报告（空=假绿，比漂移更危险）。
# ======================================================================================

import ast as _ast


def _py_tuple_strings(src: str, assign_name: str):
    """从 python 源文本提 `ASSIGN_NAME = ("a", "b")` 的元素；提不出/形态漂移=None。"""
    try:
        tree = _ast.parse(src)
    except SyntaxError:
        return None
    for node in _ast.walk(tree):
        if (isinstance(node, _ast.Assign)
                and any(isinstance(t, _ast.Name) and t.id == assign_name
                        for t in node.targets)):
            if isinstance(node.value, _ast.Tuple):
                try:
                    return [str(_ast.literal_eval(el)) for el in node.value.elts]
                except Exception:  # noqa: BLE001 —— 非 const 元素=形态漂移，fail-closed
                    return None
            return None
    return None


def _mjs_array_strings(src: str, const_name: str):
    """从 mjs 源文本提 `const NAME = ['a', 'b']` 的元素；提不出/形态漂移=None。

    锚点必须是**赋值形态**（`NAME = [` 整词+赋值号）：改名（如 `NARROWING_NAMES_V2`）
    不得被子串命中、声明写坏提不出 → 都 fail-closed（畸形面假绿防线，t261002-14
    单测钉住）。"""
    m = re.search(r"\b%s\s*=\s*\[" % re.escape(const_name), src)
    if not m:
        return None
    start = m.end() - 1
    if start < 0:
        return None
    end = src.find("]", start)
    if end < 0:
        return None
    body = src[start + 1:end]
    out = []
    for m in re.findall(r"'([^']*)'|\"([^\"]*)\"", body):
        out.append(m[0] or m[1])
    return out or None     # 空括号=提不出（fail-closed），不当「空清单恰好相等」


def narrowing_lock_report(py_src: str, mjs_src: str) -> list:
    """跨语言收窄旋钮清单互锁报告（空 list=两侧逐元素相同=锁住）。

    判据：NARROWING_ENV_PREFIXES/NAMES（py）与 NARROWING_PREFIXES/NAMES（mjs）
    各自作为**有序清单**逐元素相同。漂移报告行点名侧与元素；单侧独改/单侧畸形
    都必产行（fail-closed，见组注释）。"""
    report = []
    py_prefixes = _py_tuple_strings(py_src, "NARROWING_ENV_PREFIXES")
    py_names = _py_tuple_strings(py_src, "NARROWING_ENV_NAMES")
    py_idn = _py_tuple_strings(py_src, "INHERITED_IDENTITY_NAMES")
    mjs_prefixes = _mjs_array_strings(mjs_src, "NARROWING_PREFIXES")
    mjs_names = _mjs_array_strings(mjs_src, "NARROWING_NAMES")
    mjs_idn = _mjs_array_strings(mjs_src, "INHERITED_IDENTITY_NAMES")
    # 调用方身份清单与收窄清单同锁（t261004-26：身份收编进同一份纪律后，两份手抄
    # 同样不许漂移；缺一侧=fail-closed 产行，不当相等）。
    for side, val in (("py", py_idn), ("mjs", mjs_idn)):
        if val is None:
            report.append("%s-side identity names literal not extractable (fail-closed)" % side)
    if py_idn is not None and mjs_idn is not None:
        for i in range(max(len(py_idn), len(mjs_idn))):
            p = py_idn[i] if i < len(py_idn) else "<absent>"
            m = mjs_idn[i] if i < len(mjs_idn) else "<absent>"
            if p != m:
                report.append("identity-names[%d] drift: py=%r mjs=%r" % (i, p, m))
    for side, val in (("py", py_prefixes), ("mjs", mjs_prefixes)):
        if val is None:
            report.append("%s-side prefixes literal not extractable (fail-closed)" % side)
    for side, val in (("py", py_names), ("mjs", mjs_names)):
        if val is None:
            report.append("%s-side names literal not extractable (fail-closed)" % side)
    if py_prefixes is not None and mjs_prefixes is not None:
        for i in range(max(len(py_prefixes), len(mjs_prefixes))):
            p = py_prefixes[i] if i < len(py_prefixes) else "<absent>"
            m = mjs_prefixes[i] if i < len(mjs_prefixes) else "<absent>"
            if p != m:
                report.append("prefixes[%d] drift: py=%r mjs=%r" % (i, p, m))
    if py_names is not None and mjs_names is not None:
        for i in range(max(len(py_names), len(mjs_names))):
            p = py_names[i] if i < len(py_names) else "<absent>"
            m = mjs_names[i] if i < len(mjs_names) else "<absent>"
            if p != m:
                report.append("names[%d] drift: py=%r mjs=%r" % (i, p, m))
    return report


# ======================================================================================
# t261029-30 / KI-373: stage premises are a first-class, NAMED result.
#
# A case whose ASSERTION depends on a stage premise that the machine does not
# provide (a container stage, a uid boundary, a network rig) must not report a
# content red: the assertion can never hold there, so a red blames the product
# for an environment that is absent. Such a case reports an ENVIRONMENT failure
# instead: exit 2, with `ENV_FAIL: <premise> missing (<what was probed>)`.
#
# One shared probe, no per-case invention. A case asks this module, and may
# override only the PROBE FACE (for example: judge the uid boundary inside the
# container instead of on the host) - never the premise vocabulary and never
# the miss shape.
#
# Injection (`SANDBAR_STAGE_PREMISE_INJECT`) exists for batteries and for a
# two-direction run without the real stage: `docker-daemon=ready` or
# `stage-uid-boundary=miss:<observed text>`, comma separated. An injected run
# prints a PREMISE_INJECT receipt line, so it never passes silently for a real
# probe. The seam fakes the PREMISE only; the case's assertions still run.
# ======================================================================================

#: The one "the premise is here" answer. A miss is a PremiseMiss (never None,
#: never ""), so a caller can never mistake it for success.
PREMISE_READY = "ready"

#: Closed premise vocabulary. A case that needs a new premise adds it HERE.
PREM_DOCKER_DAEMON = "docker-daemon"
PREM_AGENT_IMAGE = "agent-image"
PREM_MODEL_CREDENTIALS = "model-credentials"
PREM_STAGE_UID_BOUNDARY = "stage-uid-boundary"
PREM_STAGE_NETWORK_RIG = "stage-network-rig"

PREMISE_NAMES = (
    PREM_DOCKER_DAEMON,
    PREM_AGENT_IMAGE,
    PREM_MODEL_CREDENTIALS,
    PREM_STAGE_UID_BOUNDARY,
    PREM_STAGE_NETWORK_RIG,
)

#: Environment seam that injects a probe result (battery / two-direction run).
PREMISE_INJECT_ENV = "SANDBAR_STAGE_PREMISE_INJECT"

#: Stable probe names. A miss names the probe that failed, so a reader knows
#: which check to look at (not just which premise).
PROBE_DOCKER_INFO = "docker-info"
PROBE_DOCKER_IMAGE_LS = "docker-image-ls"
PROBE_CREDENTIALS_FILE = "credentials-file"
PROBE_UID_BOUNDARY = "uid-boundary"
PROBE_NETWORK_RIG = "docker-network-rig"

PREMISE_PROBE = {
    PREM_DOCKER_DAEMON: PROBE_DOCKER_INFO,
    PREM_AGENT_IMAGE: PROBE_DOCKER_IMAGE_LS,
    PREM_MODEL_CREDENTIALS: PROBE_CREDENTIALS_FILE,
    PREM_STAGE_UID_BOUNDARY: PROBE_UID_BOUNDARY,
    PREM_STAGE_NETWORK_RIG: PROBE_NETWORK_RIG,
}

#: What each probe LOOKS FOR. This text is the second half of a miss, so the
#: reader learns the expected condition, not only the observed one.
PREMISE_LOOKED_FOR = {
    PREM_DOCKER_DAEMON:
        "a reachable docker daemon answering `docker info --format "
        "{{.ServerVersion}}`",
    PREM_AGENT_IMAGE:
        "an image of repository sandbar-agent present in the local image store",
    PREM_MODEL_CREDENTIALS:
        "the model credentials file ~/.dsh/.credentials.yaml, present and non-empty",
    PREM_STAGE_UID_BOUNDARY:
        "a non-root uid on the execution face whose write to /usr/local is "
        "refused by the OS",
    PREM_STAGE_NETWORK_RIG:
        "a docker rig that lists networks and renders compose files "
        "(`docker network ls`, `docker compose version`)",
}


class PremiseMiss(object):
    """A named premise miss: which premise, which probe, what it looked for and
    what it observed. `reason()` is the text the ENV_FAIL line carries."""

    __slots__ = ("premise", "probe", "looked_for", "observed")

    def __init__(self, premise, probe, looked_for, observed):
        self.premise = str(premise)
        self.probe = str(probe)
        self.looked_for = str(looked_for)
        self.observed = str(observed)

    def reason(self):
        return "%s missing (probe %s: looked for %s; observed %s)" % (
            self.premise, self.probe, self.looked_for, self.observed)

    def __str__(self):
        return self.reason()

    def __repr__(self):
        return "PremiseMiss(%r, probe=%r, observed=%r)" % (
            self.premise, self.probe, self.observed)

    def __eq__(self, other):
        return (isinstance(other, PremiseMiss)
                and (self.premise, self.probe) == (other.premise, other.probe))

    def __ne__(self, other):
        return not self.__eq__(other)

    def __hash__(self):
        return hash((self.premise, self.probe))


def _run_bounded(cmd, timeout=20):
    """One bounded call, one answer, never a hard wait. Returns
    (rc, stdout, stderr); rc is None when the call could not start at all
    (absent binary / OSError), which is a different fact from a failing rc."""
    try:
        p = subprocess.run([str(c) for c in cmd], capture_output=True, text=True,
                           timeout=timeout)
    except (OSError, subprocess.SubprocessError) as e:
        return None, "", "%s: %s" % (type(e).__name__, str(e)[:120])
    return p.returncode, p.stdout or "", p.stderr or ""


def _observed_call(rc, out, err):
    """Compact observed-value text for a bounded call (miss evidence)."""
    left = ("stdout=%r" % (out or "").strip()[:80]) if (out or "").strip() else ""
    right = ("stderr=%r" % (err or "").strip()[:120]) if (err or "").strip() else ""
    if rc is None:
        return "the call did not start (%s)" % ((err or "").strip()[:120] or "no error text")
    return "rc=%s %s" % (rc, " ".join(x for x in (left, right) if x) or "no output")


# ---------------------------------------------------------------- the probes
def probe_docker_daemon():
    """The docker daemon probe. Same one-call bounded shape as run_scenarios'
    batch_preboot prelude probe: `docker info`, one answer, no retry loop."""
    if shutil.which("docker") is None:
        return False, "no docker CLI on PATH"
    rc, out, err = _run_bounded(["docker", "info", "--format", "{{.ServerVersion}}"])
    if rc == 0 and (out or "").strip():
        return True, "server %s" % (out or "").strip()[:40]
    return False, _observed_call(rc, out, err)


def probe_agent_image():
    """The agent image must be in the local store (this project builds it; there
    is no registry to pull from)."""
    if shutil.which("docker") is None:
        return False, "no docker CLI on PATH"
    rc, out, err = _run_bounded(
        ["docker", "image", "ls", "--format", "{{.Repository}}:{{.Tag}}",
         "sandbar-agent"])
    if rc != 0:
        return False, _observed_call(rc, out, err)
    tags = [ln.strip() for ln in (out or "").splitlines() if ln.strip()]
    if not tags:
        return False, "the image store holds no image of repository sandbar-agent"
    return True, "image %s" % tags[0]


def probe_model_credentials():
    """A real agent round needs real model credentials."""
    p = Path(os.path.expanduser("~")) / ".dsh" / ".credentials.yaml"
    try:
        size = p.stat().st_size
    except OSError:
        return False, "absent: %s" % p
    if size <= 0:
        return False, "empty file: %s" % p
    return True, "present: %s (%d bytes)" % (p, size)


def uid_boundary_check(run=None):
    """The ONE uid-boundary check, over any execution face.

    `run(cmd_list)` returns (rc, stdout, stderr) for a command list on the stage
    face; run=None judges the host process face. The premise holds only when the
    face runs as a NON-root uid AND /usr/local is NOT writable by it: then, and
    only then, the OS refuses an out-of-bounds write. On a root face the write
    succeeds whatever the product does, so the assertion can never hold there
    (KI-373, measured: image runs as uid=0, /usr/local writable).
    """
    if run is None:
        uid = os.getuid()
        writable = os.path.isdir("/usr/local") and os.access("/usr/local", os.W_OK)
        observed = "host uid=%d, /usr/local writable=%s" % (uid, writable)
    else:
        rc, out, err = run(["id", "-u"])
        first = (out or "").strip().splitlines()[0].strip() if (out or "").strip() else ""
        if rc != 0 or not first.isdigit():
            return False, ("the stage face did not report a uid (%s)"
                           % _observed_call(rc, out, err))
        uid = int(first)
        rc2, out2, err2 = run(["test", "-w", "/usr/local"])
        if rc2 not in (0, 1):
            return False, ("/usr/local writability is not judgeable on the stage face (%s)"
                           % _observed_call(rc2, out2, err2))
        writable = rc2 == 0
        observed = "stage uid=%d, /usr/local writable=%s" % (uid, writable)
    if uid == 0:
        return False, observed + " (uid 0: no boundary, the OS refuses no write)"
    if writable:
        return False, observed + " (/usr/local writable: the OS refuses no write)"
    return True, observed


def uid_boundary_probe(run=None, face=""):
    """Probe callable for the `stage-uid-boundary` premise on the given face.

    `face` only labels the miss (for example "docker-exec"), so the reader sees
    which face was judged without reading the case."""
    def _probe():
        return uid_boundary_check(run)
    _probe.probe_name = PROBE_UID_BOUNDARY + (("@%s" % face) if face else "")
    return _probe


def probe_stage_network_rig():
    """A stage rig needs the daemon's network face and the compose renderer."""
    if shutil.which("docker") is None:
        return False, "no docker CLI on PATH"
    rc, out, err = _run_bounded(["docker", "network", "ls", "-q"])
    if rc != 0:
        return False, "`docker network ls` failed: " + _observed_call(rc, out, err)
    names = [x for x in (out or "").split() if x.strip()]
    rc2, out2, err2 = _run_bounded(["docker", "compose", "version"])
    if rc2 != 0:
        return False, "`docker compose version` failed: " + _observed_call(rc2, out2, err2)
    first = (out2 or "").strip().splitlines()[0].strip() if (out2 or "").strip() else "?"
    return True, "networks=%d compose=%s" % (len(names), first[:60])


DEFAULT_PREMISE_PROBES = {
    PREM_DOCKER_DAEMON: probe_docker_daemon,
    PREM_AGENT_IMAGE: probe_agent_image,
    PREM_MODEL_CREDENTIALS: probe_model_credentials,
    PREM_STAGE_UID_BOUNDARY: uid_boundary_probe(None, face="host"),
    PREM_STAGE_NETWORK_RIG: probe_stage_network_rig,
}


# ---------------------------------------------------------------- injection seam
def premise_injections(env=None):
    """Parse PREMISE_INJECT_ENV into {premise: raw value}. Malformed parts
    (no `=`) are ignored here: the seam is a battery aid, not user input."""
    raw = (os.environ if env is None else env).get(PREMISE_INJECT_ENV, "")
    out = {}
    for part in str(raw).split(","):
        part = part.strip()
        if not part or "=" not in part:
            continue
        name, value = part.split("=", 1)
        if not name.strip():
            continue          # malformed: a value without a premise name
        out[name.strip()] = value.strip()
    return out


def _injected_result(premise, env=None):
    """Injected answer for `premise`, or None when the seam does not cover it."""
    injected = premise_injections(env)
    if premise not in injected:
        return None
    value = injected[premise]
    if value == PREMISE_READY:
        print("PREMISE_INJECT: %s -> ready (injected; the real probe did NOT run; %s)"
              % (premise, PREMISE_INJECT_ENV), flush=True)
        return PREMISE_READY
    observed = value.split(":", 1)[1].strip() if value.startswith("miss:") else value
    print("PREMISE_INJECT: %s -> miss (injected; the real probe did NOT run; %s)"
          % (premise, PREMISE_INJECT_ENV), flush=True)
    return PremiseMiss(premise, PREMISE_PROBE[premise] + "@injected",
                       PREMISE_LOOKED_FOR[premise], observed or "injected miss")


# ---------------------------------------------------------------- the entry points
def probe_stage_premise(premise, probes=None, env=None):
    """Ask one premise. Returns PREMISE_READY or a PremiseMiss.

    `probes` injects probe callables ({premise: callable() -> (ok, observed)});
    an unknown premise name is refused loudly (no per-case inventions). A probe
    that raises is a MISS, never a pass."""
    if premise not in PREMISE_NAMES:
        raise ValueError("unknown stage premise %r (vocabulary: %s)"
                         % (premise, ", ".join(PREMISE_NAMES)))
    injected = _injected_result(premise, env)
    if injected is not None:
        return injected
    probe = (probes or {}).get(premise) or DEFAULT_PREMISE_PROBES[premise]
    try:
        ok, observed = probe()
    except Exception as e:  # noqa: BLE001 - a broken probe must not pass
        ok, observed = False, "the probe raised %s: %s" % (type(e).__name__, str(e)[:120])
    if ok:
        return PREMISE_READY
    name = getattr(probe, "probe_name", PREMISE_PROBE[premise])
    return PremiseMiss(premise, name, PREMISE_LOOKED_FOR[premise], observed)


def stage_premise_miss(premises=None, probes=None, env=None):
    """First NAMED miss in the given order, or None when every premise is ready.

    Use this form when the case must keep judging its other legs. Use
    require_stage_premise() for a case whose whole round is void without the
    premise."""
    for premise in (PREMISE_NAMES if premises is None else premises):
        result = probe_stage_premise(premise, probes=probes, env=env)
        if result != PREMISE_READY:
            return result
    return None


def require_stage_premise(premises=None, probes=None, env=None):
    """Gate a whole case on a premise set: a miss prints the named ENV_FAIL and
    exits 2 (the suite's environment-failure code), never 1 (content red)."""
    miss = stage_premise_miss(premises, probes=probes, env=env)
    if miss is not None:
        env_fail(miss.reason())
    return PREMISE_READY
