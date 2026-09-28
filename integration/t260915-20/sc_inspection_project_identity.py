#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""t260915-20 集成场景（真链路半）：巡检分项目归属的用户旅程契约面（真 docker 台）。

intent（登记于 run_scenarios.py，名 t260915-20-project-identity-realchain）：
  巡检实例带项目身份（声明 project_key → 起票盖 ProjectKey SA → repo_root 按项目
  注册表主目录解析）之后，双项目用户的可感知契约：
  ① 双项目各起一期巡检票（trigger **不带 --repo-root**，真走注册表解析）→
    a) 工单板项目过滤天然含巡检票：kind=inspection + project=<key> 各归各
      （A 票只在 A 板、B 票只在 B 板），行 project 字段==各自 key（SA 是行 project
      真源——无 SA 即不可见的用户面回归）；
    b) 票面 payload 与 SA 同源：describe 快照 project 键、ticket 详情回执 project
      键均非空且==SA 值（两真源不漂移，review R3）；
    c) 扫对仓：两票发现各自命中本仓种下的独特漂移锚、绝不串到对方仓（发现内容级
      互斥=「扫在与套件跑在各自项目仓」的可判定承接）；被扫树逐字节不变（巡检
      不改码红线）。
  ② 迁移机制可证（review R1）：schedule-up 建（created）→ 改声明 → 第二次
    schedule-up（**update 路径**）→ `temporal schedule describe` 断言 action 已带
    新 payload（scan_face/project_key/repo_root）与 ProjectKey SA——update 不重铸
    action 即红（t260913-02 只修 create 侧同族坑的常驻闸）。
  ③ 未知项目键 fail-closed：声明身份指向未注册 key → trigger 显式报错点名该 key
    与注册表语境，绝不报成网络错（报错必须说哪个检查失败）。
  ④ 无主票守卫：旧调度 payload 形态（无 project_key 无 repo_root，直发 SDK 旁路
    起票）→ patched 新 worker 判 blocked 终态、票面点名「无项目身份」——杀静默
    回落引擎仓的最后残窗，可见不假绿。

分工（防 intent 级重复）：
  · t260915-20-decl-project-identity（ro，离线）守声明解析门；本条从起票面开始；
  · t260905-03-period-journey 守单期全链旅程质量（发现→人门→收口审计链），本条
    只取「发现落面」为扫对仓的载体，人门/收口链不重测；
  · t260915-08-board-rows 守巡检行形状契约（快照注入离线对拍），本条守**项目
    过滤可见性**（SA→行 project 的多项目用户面）——彼时票无 SA，行 project 恒空
    不在其断言面；
  · t260915-12-gate-real-chain 守**调用方**项目身份闸（写操作维度），本条守**票
    归属**项目身份（SA/扫描仓维度），不同维；
  · developer L1（resolve 三子用例/守卫两子用例/串键回归单测）不同层。

三态：PASS exit 0 / FAIL exit 1（产品红，缺什么点名什么）/ ENV_FAIL exit 2
（docker 测试台/temporal CLI/temporalio 缺件=环境红点名，不假红不假绿）。
实现未落地=产品红（红属预期：TDD 信号），arbitrate/merge 期必须绿。

跑法（cwd=仓根）：
  PY=server/engine/.venv/bin/python; [ -x "$PY" ] || PY=python3; \
    "$PY" -B integration/t260915-20/sc_inspection_project_identity.py
"""
import asyncio
import base64
import datetime
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))   # integration/<票>/ → 仓根
sys.path.insert(0, os.path.join(REPO, "integration"))
sys.path.insert(0, os.path.join(REPO, "integration", "t260905-03"))
sys.path.insert(0, os.path.join(REPO, "server", "engine"))

import lib_inspection as lib  # noqa: E402
from lib_inspection import (  # noqa: E402
    RepoTree, StageWorker, cleanup_tickets, die_env, die_fail, note_started_ticket,
    run_client, run_trigger,
)
# t260916-22：scan 段退役 → inspect 段（桩 agent）；发现注入走桩缝（方案 §3），
# 伪造器/复核态访问器单点在 t260916-22/lib_inspect。
sys.path.insert(0, os.path.join(REPO, "integration", "t260916-22"))
import lib_inspect as inspect_lib  # noqa: E402

try:
    import temporalio  # noqa: F401——J4 直发 SDK 需要；缺席=环境红
except Exception:  # noqa: BLE001
    die_env("temporalio SDK 缺席（server/engine/.venv 不可用）——真链路子用例无法执行")

PRODUCER_REL = lib.PRODUCER_REL
STATS = {"pass": 0, "fail": 0}
FAILS = []

PID = os.getpid()
KEY_A = "pka%d" % PID
KEY_B = "pkb%d" % PID
GHOST_KEY = "ghost%d" % PID
INST_A = "insa-%d" % PID
INST_B = "insb-%d" % PID
INST_GHOST = "insg-%d" % PID
INST_GUARD = "insw-%d" % PID
PERIOD = datetime.datetime.now().strftime("%Y%m%d")
# 漂移锚=**文案字面形态**（test 面 S2 锚判据：≥2 CJK+非纯词字符——ASCII token 不入选
# 锚，anchors_checked=0=扫描器静默零发现，首轮实跑教训）；PID 戳保证双仓互斥（A 锚
# 绝不出现在 B 仓发现里），且生产方纯重写不含锚=KI-051 high 支路必报。
TOKEN_A = "项目甲仓『分项目巡检锚%d』" % PID
TOKEN_B = "项目乙仓『分项目巡检锚%d』" % PID
NEVER_CRON = "0 0 31 2 *"   # 2 月 31 日不存在：场景运行期调度永不真触发
SCHEDULE_NOTE = "t260915-20 场景自建（退出即删）"
# 触发面子进程 env 单点：SANDBAR_PROJECTS_DIR（注册表缝→夹具注册表根）+
# SANDBAR_TASK_QUEUE（trigger/schedule-up 与场景自供给 worker 同队列）。
TRIGGER_ENV = {}


def check(name, cond, detail=""):
    if cond:
        STATS["pass"] += 1
        print("PASS %s" % name, flush=True)
    else:
        STATS["fail"] += 1
        FAILS.append("%s%s" % (name, ("：" + detail) if detail else ""))
        print("FAIL %s%s" % (name, ("：" + detail) if detail else ""), flush=True)


def trg(args):
    """触发面 CLI 统一出口：env 一律带注册表缝与私有队列（spawn_env 白名单单点）。"""
    return run_trigger(args, env=dict(TRIGGER_ENV))


# ---------------------------------------------------------------- 环境前提（ENV_FAIL 面）

def precheck_temporal_reachable():
    host, port = lib.TEST_TARGET_HOST.split(":")
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(3.0)
    try:
        rc = s.connect_ex((host, int(port)))
    finally:
        s.close()
    if rc != 0:
        die_env("测试台 %s 不可达（本场景写真票真调度到隔离台；"
                "sh server/docker-compose.test.yml up -d 起台后重试）" % lib.TEST_TARGET_HOST)


def precheck_temporal_cli():
    """temporal CLI 解析（supply 同款回落链）：bin 软链 → PATH → 主树候选自动补链。
    软链落点 server/engine/bin/ 在本票写集内（t260907-10 供给语义：主树 CLI 单源）。"""
    cand = os.path.join(lib.TP_DIR, "bin", "temporal")
    if os.path.exists(cand):
        return cand
    import shutil as _sh
    which = _sh.which("temporal")
    if which:
        return which
    # 主树候选（闸级 supply 同款）：worktree 的主库根下找 CLI，自动补软链（幂等）
    try:
        git_common = subprocess.run(
            ["git", "rev-parse", "--path-format=absolute", "--git-common-dir"],
            capture_output=True, text=True, timeout=15, cwd=REPO,
        ).stdout.strip()
        main_root = os.path.abspath(os.path.join(git_common or "", ".."))
    except Exception:  # noqa: BLE001——git 不可用则主树候选面放弃，走 ENV_FAIL 点名
        main_root = ""
    for src in (os.path.join(main_root, "server", "engine", "bin", "temporal"),
                os.path.join(main_root, "server", "dsh", "temporal-poc", "bin", "temporal")):  # engine-venv-compat（蓄意兼容回落：迁移窗机器旧布局候选，新路径优先；旧布局退役票落地后随 marker 撤除——t260907-10 行级豁免锚）
        if main_root and os.path.exists(src):
            try:
                os.makedirs(os.path.dirname(cand), exist_ok=True)
                if not os.path.exists(cand):
                    os.symlink(src, cand)
                return cand
            except OSError as e:
                die_env("temporal CLI 软链补建失败（%s → %s）：%s" % (src, cand, e))
    die_env("temporal CLI 缺席（%s 或 PATH，主树候选也无）——迁移重铸子用例的调度自检无法执行"
            % cand)


def precheck_namespace():
    """测试台供给自愈（ENV_FAIL 面）：namespace 在场探测/补建 + ProjectKey SA 注册。

    台可达但 namespace/SA 未注册=**环境不完整**（compose 台的注册归供给步骤，
    docker-compose.test.yml L50-55 注释明示 SA 需起台后注册），不是产品红——真台
    干跑 260915 实锤：自建 namespace 缺 ProjectKey 映射时，ticket-list 项目过滤与
    schedule-up 全线报「no mapping defined for search attribute ProjectKey」，按
    产品红会误导归因。SDK 直连建 namespace（1.8.3 的 namespace 子命令族不吃全局
    --address，实测 unknown flag；SA 注册用 CLI——operator 子族吃全局 flag，实测
    可用）。幂等：namespace 已在/SA 已注册均容忍。"""
    import asyncio as _aio
    from google.protobuf.duration_pb2 import Duration
    from temporalio.api.workflowservice.v1 import DescribeNamespaceRequest
    from temporalio.api.workflowservice.v1.request_response_pb2 import (
        RegisterNamespaceRequest,  # 本代 proto 无 CreateNamespaceRequest（创建面=Register）
    )
    from temporalio.client import Client
    from temporalio.service import RPCError

    async def _ensure_ns():
        client = await Client.connect(lib.TEST_TARGET_HOST, namespace=lib.TEST_NAMESPACE)
        try:
            await client.workflow_service.describe_namespace(
                DescribeNamespaceRequest(namespace=lib.TEST_NAMESPACE))
            return
        except RPCError as e:
            if "not found" not in str(e):
                die_env("测试台 namespace 探测失败（%s）：%s" % (lib.TEST_NAMESPACE, e))
        try:
            await client.workflow_service.register_namespace(
                RegisterNamespaceRequest(
                    namespace=lib.TEST_NAMESPACE,
                    workflow_execution_retention_period=Duration(seconds=86400)))
            print("NOTE: 已补建测试台 namespace %s" % lib.TEST_NAMESPACE, flush=True)
        except RPCError as e:
            if "already" in str(e).lower():
                return
            die_env("测试台 namespace %s 自建失败：%s" % (lib.TEST_NAMESPACE, e))

    try:
        _aio.run(_ensure_ns())
    except SystemExit:
        raise
    except Exception as e:  # noqa: BLE001——SDK 面/网络面异常=环境红点名
        die_env("测试台 namespace 探测异常：%s: %s" % (type(e).__name__, e))

    # ProjectKey SA 注册（Keyword 型，工单板项目过滤与起票盖章的前提；幂等）
    cli = precheck_temporal_cli()
    sa = subprocess.run(
        [cli, "--address", lib.TEST_TARGET_HOST, "--namespace", lib.TEST_NAMESPACE,
         "operator", "search-attribute", "create", "--name", "ProjectKey",
         "--type", "Keyword"],
        capture_output=True, text=True, timeout=60)
    blob = (sa.stdout or "") + (sa.stderr or "")
    if sa.returncode != 0 and "already" not in blob.lower():
        die_env("测试台 ProjectKey SA 注册失败：%s" % blob[-200:])
    if sa.returncode == 0:
        print("NOTE: 已注册测试台 ProjectKey SA（Keyword）", flush=True)


# ---------------------------------------------------------------- 夹具

GUARD_REL = "integration/sc_pk20_guard.mjs"


def _guard_lines(producer_rel: str, token: str) -> list:
    """守卫文件内容（行序=落盘行序；**行号从这份内容算**，见 GUARD_ANCHOR_LINE）。"""
    return [
        "// 守卫：分项目巡检夹具锚（t260915-20 场景夹具，capture-chat 形态）",
        "// 守卫对象生产方: %s" % producer_rel,
        "const label = await page.locator('.session-create').innerText();",
        'assert(label.includes("%s"), "守卫锚缺失");' % token,
    ]


# 260928 修：锚行号原来写死 5，而守卫文件只有 4 行 ⇒ 复核层判「行号越界（合法 1~4）」，
# 桩发现的引文复核恒 unverified（本场景 J1g2-A/B 双红的真因；夹具自证不成立=「假锚」）。
# 现改为与内容同源：drifty_tree 落盘前自检 `_guard_lines()[行号-1] == guard_anchor_line(token)`，
# 行号与文件再漂移即当场红，不会再退化成一枚查不出的 unverified。
GUARD_ANCHOR_LINE = 4   # = _guard_lines(...) 里 assert 那行的 1-based 行号


def guard_anchor_line(token: str) -> str:
    """守卫文件第 5 行原文（inspect 桩发现的 evidence 引文锚：只可能在本仓对上）。"""
    return 'assert(label.includes("%s"), "守卫锚缺失");' % token


def drifty_tree(label: str, token: str) -> RepoTree:
    """仓形漂移夹具：KI-051 high 形态（守卫断言锚字面、生产方纯重写不含锚）——
    必产 high 发现且证据带本仓独特锚（token 只在守卫侧，发现的 evidence 必点名）。
    t260916-22 后：夹具改作 inspect 桩发现的证据锚底座（引文锚=本行）。"""
    t = RepoTree(label)
    t.write_scenarios([("t-pk20-guard", "分项目巡检夹具守卫（%s）" % label, "true")])
    _gl = _guard_lines(PRODUCER_REL, token)
    assert _gl[GUARD_ANCHOR_LINE - 1] == guard_anchor_line(token), (
        "锚行号与守卫文件内容漂移：第 %d 行=%r，而 guard_anchor_line=%r"
        % (GUARD_ANCHOR_LINE, _gl[GUARD_ANCHOR_LINE - 1], guard_anchor_line(token)))
    t.write(GUARD_REL, "\n".join(_gl) + "\n")
    # 纯重写形态：生产方在位但锚字面缺席 → KI-051 high 支路必报
    t.write(PRODUCER_REL,
            'const section = "项目行";\n'
            'const label = section + "『+ 钮』";\n'
            "export function buttonLabel() { return label; }\n")
    t.keep_checksums()
    return t


def write_registry(root: str, key: str, name: str, dirs: list) -> str:
    """per-key 注册条目（契约①a schema v1 固定形状：顶层只认 schema:/project:）。"""
    d = os.path.join(root, key)
    os.makedirs(d, exist_ok=True)
    lines = ["# t260915-20 场景夹具注册条目", "schema: v1", "project:",
             "  - key: %s" % key, "    name: %s" % name, "    dirs:"]
    lines += ["      - %s" % x for x in dirs]
    path = os.path.join(d, "project.yaml")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    return path


def build_decl(inst_a_face: str) -> str:
    """场景声明：三启用实例 + 守卫实例，身份各归各位（guard 实例身份在册，但 J4
    直发的旧 payload 故意不带——旧调度 payload 形态）。cron 全部永不触发。"""
    return (
        "schema: v1\n"
        "instances:\n"
        "  - id: %s\n"
        "    enabled: true\n"
        "    project_key: %s\n"
        "    scan_face: %s\n"
        "    schedule:\n"
        "      kind: cron\n"
        "      cron: %s\n"
        "    workflow: InspectionPeriodicWorkflow\n"
        "    template: inspection-lite\n"
        "  - id: %s\n"
        "    enabled: true\n"
        "    project_key: %s\n"
        "    schedule:\n"
        "      kind: cron\n"
        "      cron: %s\n"
        "    workflow: InspectionPeriodicWorkflow\n"
        "    template: inspection-lite\n"
        "  - id: %s\n"
        "    enabled: true\n"
        "    project_key: %s\n"
        "    schedule:\n"
        "      kind: cron\n"
        "      cron: %s\n"
        "    workflow: InspectionPeriodicWorkflow\n"
        "    template: inspection-lite\n"
        "  - id: %s\n"
        "    enabled: true\n"
        "    project_key: %s\n"
        "    schedule:\n"
        "      kind: cron\n"
        "      cron: %s\n"
        "    workflow: InspectionPeriodicWorkflow\n"
        "    template: inspection-lite\n"
        % (INST_A, KEY_A, inst_a_face, NEVER_CRON,
           INST_B, KEY_B, NEVER_CRON,
           INST_GHOST, GHOST_KEY, NEVER_CRON,
           INST_GUARD, KEY_A, NEVER_CRON))


def write_file(path: str, text: str) -> None:
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def findings_text(snapshot: dict) -> str:
    face = (snapshot or {}).get("face") if isinstance(snapshot, dict) else {}
    fs = (face or {}).get("findings") if isinstance(face, dict) else None
    parts = []
    for f in fs if isinstance(fs, list) else []:
        if isinstance(f, dict):
            parts.append("%s %s" % (f.get("subject") or "", f.get("evidence") or ""))
    return "\n".join(parts)


def fetch_snapshot(inst: str, period: str):
    _, parsed = trg(["describe", "--instance", inst, "--period", period])
    res = (parsed or {}).get("result") if isinstance(parsed, dict) else None
    snap = (res or {}).get("snapshot") if isinstance(res, dict) else None
    return snap if isinstance(snap, dict) else None


def poll_snapshot(inst: str, period: str, timeout_s: float, want_findings: bool):
    """轮询 describe 直到快照可达且（按需）发现已落面；超时返回最后快照。"""
    deadline = time.time() + timeout_s
    snap = None
    while time.time() < deadline:
        snap = fetch_snapshot(inst, period)
        if isinstance(snap, dict):
            if not want_findings:
                return snap
            face = snap.get("face") if isinstance(snap.get("face"), dict) else {}
            if isinstance(face.get("findings"), list) and face.get("findings"):
                return snap
        time.sleep(3.0)
    return snap


def list_rows(project_key: str):
    """client.py ticket-list（kind=inspection，可选 project 过滤）→ 行列表。
    client 子进程带 SANDBAR_INSPECTION_DECL=夹具声明：巡检白名单按**场景夹具实例**
    过滤（进程缺省读引擎真源声明，insa/insb 不在册 → 行被滤光；t260915-08-board-rows
    同款声明 env 手法）——不改写集内 client 的白名单语义。"""
    args = {"kind": "inspection"}
    if project_key:
        args["project"] = project_key
    decl_path = TRIGGER_ENV.get("DECL_PATH", "")
    extra_env = {"SANDBAR_INSPECTION_DECL": decl_path} if decl_path else None
    proc, parsed = run_client("ticket-list", args, env=extra_env)
    res = (parsed or {}).get("result") if isinstance(parsed, dict) else None
    rows = (res or {}).get("tickets") if isinstance(res, dict) else None
    return rows if isinstance(rows, list) else None, parsed


def row_ids(rows):
    return [str(r.get("id") or "") for r in rows if isinstance(r, dict)]


# ---------------------------------------------------------------- 子用例

def j1_dual_project(queue: str, decl_path: str, tree_a: RepoTree, tree_b: RepoTree,
                    stub_path: str = ""):
    # t260916-02：票号=t 形工单号（开票面铸造）——从 trigger 回执取真票号，
    # 不再硬编 inspection- 旧形（旧形仍可能是历史在途票，由 legacy 只读子用例辨认）。
    tid_a = tid_b = ""

    def tid_of(parsed):
        res = (parsed or {}).get("result") if isinstance(parsed, dict) else {}
        return str((res or {}).get("ticket_id") or "")

    proc_a, parsed_a = trg(["trigger", "--instance", INST_A, "--period", PERIOD,
                            "--decl-path", decl_path])
    tid_a = tid_of(parsed_a)
    check("J1a-A trigger(A) 放行且未带 --repo-root（注册表解析路）",
          (parsed_a or {}).get("ok") is True and tid_a,
          "ok=%r ticket_id=%r out=%s" % ((parsed_a or {}).get("ok"), tid_a,
                                         (proc_a.stdout or "")[-200:]))

    # t260916-22 桩缝：A 票用 A 锚引文桩（同相对路径在两仓都在，引文只可能对上 A 仓
    # 内容=引擎 base_dir 正确性的内容级证明）；inspect 在 spawn 时刻读桩文件，A 票发现
    # 落面后再重写桩为 B 锚，才触发 B 票（时序隔离防桩互染）。
    if stub_path:
        with open(stub_path, "w", encoding="utf-8") as f:
            f.write(inspect_lib.fenced_message([
                inspect_lib.finding("Repo-A unique anchor drift", GUARD_REL, GUARD_ANCHOR_LINE,
                                    guard_anchor_line(TOKEN_A), severity="high",
                                    confidence=0.9),
            ]))

    snap_a = poll_snapshot(INST_A, PERIOD, 150, want_findings=True)
    if stub_path:
        with open(stub_path, "w", encoding="utf-8") as f:
            f.write(inspect_lib.fenced_message([
                inspect_lib.finding("Repo-B unique anchor drift", GUARD_REL, GUARD_ANCHOR_LINE,
                                    guard_anchor_line(TOKEN_B), severity="high",
                                    confidence=0.9),
            ]))
    proc_b, parsed_b = trg(["trigger", "--instance", INST_B, "--period", PERIOD,
                            "--decl-path", decl_path])
    tid_b = tid_of(parsed_b)
    check("J1a-B trigger(B) 放行", (parsed_b or {}).get("ok") is True,
          "ok=%r out=%s" % ((parsed_b or {}).get("ok"), (proc_b.stdout or "")[-200:]))

    snap_b = poll_snapshot(INST_B, PERIOD, 150, want_findings=True)
    check("J1b-A 发现落面（worker 扫描完成）",
          isinstance(snap_a, dict) and bool(findings_text(snap_a).strip()),
          "快照=%s" % (json.dumps(snap_a, ensure_ascii=False)[:200] if snap_a else "None"))
    check("J1b-B 发现落面",
          isinstance(snap_b, dict) and bool(findings_text(snap_b).strip()),
          "快照=%s" % (json.dumps(snap_b, ensure_ascii=False)[:200] if snap_b else "None"))

    # ①b payload 面与 SA 同源（describe 快照 project 键 + ticket 详情回执 project 键）
    check("J1c-A describe 快照 project==A（payload 真源）",
          isinstance(snap_a, dict) and str(snap_a.get("project") or "") == KEY_A,
          "project=%r" % (snap_a or {}).get("project"))
    check("J1c-B describe 快照 project==B",
          isinstance(snap_b, dict) and str(snap_b.get("project") or "") == KEY_B,
          "project=%r" % (snap_b or {}).get("project"))
    _, t_parsed = trg(["ticket", "--instance", INST_A, "--period", PERIOD])
    t_res = (t_parsed or {}).get("result") if isinstance(t_parsed, dict) else {}
    check("J1d-A ticket 回执 project==A 且非空（详情面同构）",
          str((t_res or {}).get("project") or "") == KEY_A,
          "result.project=%r" % (t_res or {}).get("project"))

    # ①a 工单板项目过滤各归各（行 project 真源=SA）
    rows_a, parsed_la = list_rows(KEY_A)
    ids_a = row_ids(rows_a or [])
    check("J1e-A A 板含 A 票不含 B 票",
          rows_a is not None and tid_a in ids_a and tid_b not in ids_a,
          "tickets=%s parsed=%s" % (ids_a[:6], json.dumps(parsed_la, ensure_ascii=False)[:160]))
    row_a = next((r for r in (rows_a or []) if isinstance(r, dict) and r.get("id") == tid_a), {})
    check("J1f-A 行 project==A（SA 是行 project 真源）",
          str((row_a or {}).get("project") or "") == KEY_A,
          "row.project=%r" % (row_a or {}).get("project"))
    rows_b, _ = list_rows(KEY_B)
    ids_b = row_ids(rows_b or [])
    check("J1e-B B 板含 B 票不含 A 票",
          rows_b is not None and tid_b in ids_b and tid_a not in ids_b,
          "tickets=%s" % ids_b[:6])
    row_b = next((r for r in (rows_b or []) if isinstance(r, dict) and r.get("id") == tid_b), {})
    check("J1f-B 行 project==B",
          str((row_b or {}).get("project") or "") == KEY_B,
          "row.project=%r" % (row_b or {}).get("project"))

    # ①c 扫对仓：发现内容与本仓独特锚互斥匹配 + 证据复核 verified（引文只可能在
    # 本仓对上=引擎 base_dir 正确性的内容级证明；串仓即引文不符→unverified）
    txt_a, txt_b = findings_text(snap_a), findings_text(snap_b)
    check("J1g-A 发现命中 A 仓独特锚",
          TOKEN_A in txt_a and TOKEN_B not in txt_a,
          "含A锚=%s 含B锚=%s" % (TOKEN_A in txt_a, TOKEN_B in txt_a))
    check("J1g-B 发现命中 B 仓独特锚",
          TOKEN_B in txt_b and TOKEN_A not in txt_b,
          "含B锚=%s 含A锚=%s" % (TOKEN_B in txt_b, TOKEN_A in txt_b))

    def _face_states(snap):
        face = (snap or {}).get("face") if isinstance(snap, dict) else None
        fs = (face or {}).get("findings") if isinstance(face, dict) else None
        return [(lib_inspect_state(f)) for f in (fs or []) if isinstance(f, dict)]

    def lib_inspect_state(f):
        return inspect_lib.finding_state(f)

    # 260928：失败面补证据——原来只印 states，看不出**为什么**判 unverified；
    # 复核层的点名理由就在 finding["unverified_reasons"]（KI-018① 同族：报错必须精确）。
    def _face_reasons(snap):
        face = (snap or {}).get("face") if isinstance(snap, dict) else {}
        fs = (face or {}).get("findings") if isinstance(face, dict) else None
        return [((f.get("subject") or "")[:28], f.get("verified"),
                 f.get("unverified_reasons")) for f in (fs or []) if isinstance(f, dict)]

    check("J1g2-A A 票发现证据复核 verified（基座=A 仓内容级证明）",
          bool(txt_a.strip()) and "verified" in _face_states(snap_a),
          "states=%r reasons=%s" % (_face_states(snap_a), json.dumps(_face_reasons(snap_a), ensure_ascii=False)[:400]))
    check("J1g2-B B 票发现证据复核 verified（基座=B 仓内容级证明）",
          bool(txt_b.strip()) and "verified" in _face_states(snap_b),
          "states=%r reasons=%s" % (_face_states(snap_b), json.dumps(_face_reasons(snap_b), ensure_ascii=False)[:400]))
    check("J1h 被扫树逐字节不变（巡检不改码红线）",
          not tree_a.tree_unchanged() and not tree_b.tree_unchanged(),
          "%s %s" % (tree_a.tree_unchanged(), tree_b.tree_unchanged()))


def j3_unknown_key(decl_path: str):
    proc, parsed = trg(["trigger", "--instance", INST_GHOST,
                        "--period", PERIOD, "--decl-path", decl_path])
    err = str((parsed or {}).get("error") or "") or (proc.stdout or "")[-300:]
    check("J3 未知项目键 fail-closed 点名（不冒充网络错）",
          (parsed or {}).get("ok") is not True
          and GHOST_KEY in err
          and ("未知项目" in err or "注册表" in err or "registry" in err)
          and "不可达" not in err and "unreachable" not in err.lower(),
          "ok=%r error=%r" % ((parsed or {}).get("ok"), err[:200]))


def j2_update_recast(decl_path: str, tmp: str, tree_a: RepoTree):
    cli = precheck_temporal_cli()
    sched_id = "sandbar-inspection-%s" % INST_A
    addr_args = ["--address", lib.TEST_TARGET_HOST, "--namespace", lib.TEST_NAMESPACE]

    _, up1 = trg(["schedule-up", "--instance", INST_A,
                  "--decl-path", decl_path, "--note", SCHEDULE_NOTE])
    check("J2a 首次 schedule-up 建（created）",
          str(((up1 or {}).get("result") or {}).get("mode") or "") == "created",
          "回执=%s" % json.dumps(up1, ensure_ascii=False)[:200])

    # 改声明（inst-a scan_face test→mechanism）→ 第二次 schedule-up 走 update 分支
    decl_v2 = os.path.join(tmp, "decl-v2.yaml")
    write_file(decl_v2, build_decl("mechanism"))
    _, up2 = trg(["schedule-up", "--instance", INST_A,
                  "--decl-path", decl_v2, "--note", SCHEDULE_NOTE + " v2"])
    check("J2b 第二次 schedule-up 走 update（幂等更新在册）",
          str(((up2 or {}).get("result") or {}).get("mode") or "") == "updated",
          "回执=%s" % json.dumps(up2, ensure_ascii=False)[:200])

    p = subprocess.run([cli] + addr_args + ["schedule", "describe",
                                            "--schedule-id", sched_id, "--output", "json"],
                       capture_output=True, text=True, timeout=60)
    blob = (p.stdout or "") + (p.stderr or "")
    # CLI 的 describe JSON 对 payload/SA 值一律 base64（metadata.encoding=json/plain，
    # data=base64）——明文断言前把全部 data 段解码拼进来（首轮实跑教训：明文 in blob
    # 恒 False=断言空转；引擎行为其实已正确）。
    plain_parts = []
    for m in re.finditer(r'"data":\s*"([A-Za-z0-9+/=]+)"', blob):
        try:
            plain_parts.append(base64.b64decode(m.group(1)).decode("utf-8", "replace"))
        except Exception:  # noqa: BLE001——非 base64 段跳过（键名等明文本就在 blob）
            pass
    plain = blob + "\n" + "\n".join(plain_parts)
    check("J2c update 后 action 已重铸（新 payload：scan_face/project_key/repo_root）",
          p.returncode == 0 and "mechanism" in plain and KEY_A in plain
          and tree_a.root in plain,
          "rc=%s 含mechanism=%s 含key=%s 含repo_root=%s tail=%s"
          % (p.returncode, "mechanism" in plain, KEY_A in plain, tree_a.root in plain,
             blob[-200:]))
    check("J2d update 后 action 带 ProjectKey SA",
          p.returncode == 0 and "ProjectKey" in blob and KEY_A in plain,
          "含ProjectKey=%s 含值=%s" % ("ProjectKey" in blob, KEY_A in plain))


def j4_unowned_guard(queue: str, decl_path: str):
    """旧调度 payload 形态直发（无 project_key 无 repo_root）→ patched worker 判
    blocked 终态并点名「无项目身份」（旁路起票残窗的守卫闸）。"""
    from inspection_flow import InspectionPeriodicInput
    # t260916-02：inspection_ticket_id 已退役（票号=t 形由开票面铸造）；本子用例守卫
    # 「旁路直发旧 payload」，id 用确定性旧形模拟迁移前形态，不再依赖铸号函数。
    tid = "inspection-%s-%s" % (INST_GUARD, PERIOD)
    note_started_ticket(tid)

    async def _start():
        from temporalio.client import Client
        client = await Client.connect(lib.TEST_TARGET_HOST, namespace=lib.TEST_NAMESPACE)
        # 旧 payload 形态：字段与迁移前调度 payload 同形（无 project_key、repo_root 空）
        await client.start_workflow(
            "InspectionPeriodicWorkflow",
            InspectionPeriodicInput(instance_id=INST_GUARD, period=PERIOD,
                                    face="test", repo_root="", decl_path=decl_path),
            id=tid, task_queue=queue)

    try:
        asyncio.run(_start())
    except Exception as e:  # noqa: BLE001——AlreadyStarted（上轮残留）=隔离台内去重，继续判读
        if "already started" not in str(e).lower():
            check("J4a 直发旧 payload 起票", False, "%s: %s" % (type(e).__name__, e))
            return
    snap = poll_snapshot(INST_GUARD, PERIOD, 120, want_findings=False)
    blob = json.dumps(snap, ensure_ascii=False) if isinstance(snap, dict) else ""
    check("J4b 无主守卫：旧 payload 票 blocked 终态并点名无项目身份",
          isinstance(snap, dict) and str(snap.get("status") or "") == "blocked"
          and "无项目身份" in blob,
          "status=%r 含守卫点名=%s" % ((snap or {}).get("status"), "无项目身份" in blob))


# ---------------------------------------------------------------- 主流程

def main() -> int:
    precheck_temporal_reachable()
    precheck_temporal_cli()
    precheck_namespace()

    tmp = tempfile.mkdtemp(prefix="sandbar-t26091520-")
    reg_root = os.path.join(tmp, "projects")
    os.makedirs(reg_root, exist_ok=True)
    tree_a = drifty_tree("sbxa-%d" % PID, TOKEN_A)
    tree_b = drifty_tree("sbxb-%d" % PID, TOKEN_B)
    stub_path = os.path.join(tmp, "inspect-stub-message.txt")
    with open(stub_path, "w", encoding="utf-8") as f:
        f.write(inspect_lib.fenced_message([]))
    try:
        write_registry(reg_root, KEY_A, "Fixture A", [tree_a.root])
        write_registry(reg_root, KEY_B, "Fixture B", [tree_b.root])
        decl_path = os.path.join(tmp, "decl-v1.yaml")
        write_file(decl_path, build_decl("test"))

        # 专属队列：TICKET_QUEUE_PREFIX 前缀（ticket-list 收录专属前缀执行）且
        # 场景自供给 worker 独占（常驻生产 worker 不 poll 该队列，无领活竞态）
        queue = "sandbar-ticket-insp20-%d" % PID
        TRIGGER_ENV.update({"SANDBAR_PROJECTS_DIR": reg_root,
                            "SANDBAR_TASK_QUEUE": queue,
                            "DECL_PATH": decl_path})   # list_rows 的白名单声明 env 取这里
        try:
            with StageWorker(queue, extra_env={
                    "SANDBAR_INSPECT_STUB": "1",
                    "SANDBAR_INSPECT_STUB_FILE": stub_path}):
                j1_dual_project(queue, decl_path, tree_a, tree_b, stub_path)
                j3_unknown_key(decl_path)
                j2_update_recast(decl_path, tmp, tree_a)
                j4_unowned_guard(queue, decl_path)
        finally:
            TRIGGER_ENV.clear()
    finally:
        # 资源回收：调度删除（幂等，失败只 WARN）→ 票 cancel（lib 账本）→ 夹具拆除
        import shutil as _sh
        cand = os.path.join(lib.TP_DIR, "bin", "temporal")
        cli = cand if os.path.exists(cand) else _sh.which("temporal")
        if cli:
            subprocess.run([cli, "--address", lib.TEST_TARGET_HOST,
                            "--namespace", lib.TEST_NAMESPACE,
                            "schedule", "delete",
                            "--schedule-id", "sandbar-inspection-%s" % INST_A],
                           capture_output=True, text=True, timeout=60)
        try:
            cleanup_tickets()
        except Exception as e:  # noqa: BLE001——自清失败不炸退出路径
            print("WARN: 退出自清异常（%s）" % e, flush=True)
        tree_a.cleanup()
        tree_b.cleanup()
        shutil.rmtree(tmp, ignore_errors=True)

    print("SUMMARY pass=%d fail=%d env_fail=%d na=%d"
          % (STATS["pass"], STATS["fail"], 0, 0), flush=True)
    if FAILS:
        print("FAIL_REASON: %s" % "；".join(FAILS), flush=True)
        return 1
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except Exception as e:  # noqa: BLE001——意外异常=产品红点名，不静默不假绿
        die_fail("场景异常退出：%s: %s" % (type(e).__name__, e))
