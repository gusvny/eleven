# -*- coding: utf-8 -*-
"""t260916-02 场景共享夹具（无 sc_ 前缀=共享子检查代码，不登记场景清单）。

本票三场景（relocation-realchain / decl-gate-aggregate / board-legacy-three-state）
共享的前置与基础步骤：注册表缝夹具、仓根声明夹具、指路声明夹具、去重指针夹具、
测试台预检（含本票新增两个 SA 的幂等注册）。跨票复用 t260905-03 的 lib_inspection
（spawn_env 白名单单点 / StageWorker / 票账本 / 三态纪律）——前置代码共享复用是
纪律允许面；断言面各自独立，不共享。

绑定面（方案 t260916-02 §2 声明的对外契约，场景侧不再发明）：
- 声明落位：注册条目 paths.inspection_decl 未声明 → 默认 <dirs[0]>/inspection.yaml；
- 覆盖层优先级：--decl-path（显式）> env SANDBAR_INSPECTION_DECL（测试覆盖）> 聚合；
- 去重指针：<INSPECTION_DIR>/inspection-<实例>-<期>.ticket（目录接 SANDBAR_INSPECTION_DIR）；
- 巡检票 SA：ProjectKey / InspectionInstance / InspectionPeriod（Keyword）。
"""
from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, os.path.join(REPO, "integration"))
sys.path.insert(0, os.path.join(REPO, "integration", "t260905-03"))

from lib_inspection import (  # noqa: E402,F401  ——跨票共享前置（纪律允许）
    RepoTree, StageWorker, TEST_NAMESPACE, TEST_TARGET_HOST, TP_DIR,
    cleanup_tickets, die_env, die_fail, last_json, note_started_ticket,
    py_runner, run_client, run_trigger, spawn_env,
)

# 巡检票三个 SA 的名字（对外契约面：t260915-20 立ProjectKey、t260916-02 立后两个）。
SA_PROJECT = "ProjectKey"
SA_INSTANCE = "InspectionInstance"
SA_PERIOD = "InspectionPeriod"
# 全部需要注册的 SA（precheck 幂等补建；tolerate already）。
SA_ALL = (SA_PROJECT, SA_INSTANCE, SA_PERIOD)

# 永不触发的 cron（2 月 31 日不存在）——场景自建调度退出即删，双保险。
# 隔离习语（t260916-02 arbitrate gen2 调整）：deadman 期望期计算已守卫
# 「四年内无命中=显式报错」（inspection_ticket_count.py），2/31 形永伪 cron 不再可用；
# 改用年年命中但远离测试窗的稀有 cron（3/30 00:00）保持隔离语义。
RARE_CRON = "0 0 30 3 *"


def write_registry(root: str, key: str, name: str, dirs: list,
                   paths_lines: list = None) -> str:
    """per-key 注册条目（契约①a schema v1 形状；paths_lines=可选 paths 节行列表）。"""
    d = os.path.join(root, key)
    os.makedirs(d, exist_ok=True)
    lines = ["# t260916-02 场景夹具注册条目", "schema: v1", "project:",
             "  - key: %s" % key, "    name: %s" % name, "    dirs:"]
    lines += ["      - %s" % x for x in dirs]
    if paths_lines:
        lines.append("paths:")
        lines += ["  " + x for x in paths_lines]
    path = os.path.join(d, "project.yaml")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    return path


def decl_yaml(instances: list) -> str:
    """巡检声明文本。instances=[(id, project_key, cron, face), ...]（全 enabled）。"""
    out = ["schema: v1", "instances:"]
    for iid, pkey, cron, face in instances:
        out += [
            "  - id: %s" % iid,
            "    enabled: true",
            "    project_key: %s" % pkey,
        ]
        if face:
            out.append("    scan_face: %s" % face)
        out += [
            "    schedule:",
            "      kind: cron",
            "      cron: %s" % cron,
            "    workflow: InspectionPeriodicWorkflow",
            "    template: inspection-lite",
        ]
    return "\n".join(out) + "\n"


def write_file(path: str, text: str) -> str:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    return path


def pointer_path(ledger_dir: str, instance: str, period: str) -> str:
    """去重指针落点（方案 §2.2 步骤3：<INSPECTION_DIR>/inspection-<实例>-<期>.ticket）。"""
    return os.path.join(ledger_dir, "inspection-%s-%s.ticket" % (instance, period))


def plant_pointer(ledger_dir: str, instance: str, period: str,
                  content: bytes, age_s: float = 3600.0) -> str:
    """种一枚指针并做旧（mtime 后拨 age_s 秒）——超过 CLAIM_GRACE_SEC(120s) 用真实
    文件年龄表达，不依赖注入钩子；返回指针路径。"""
    os.makedirs(ledger_dir, exist_ok=True)
    p = pointer_path(ledger_dir, instance, period)
    with open(p, "wb") as f:
        f.write(content)
    past = __import__("time").time() - age_s
    os.utime(p, (past, past))
    return p


def precheck_stage() -> None:
    """环境前提（ENV_FAIL 面）：测试台可达 + temporal CLI + namespace + 本票 SA 族。

    SA 缺注册在真台是「no mapping defined」环境不完整（t260915-20 同款教训）——
    幂等补建四个 SA（ProjectKey/InspectionInstance/InspectionPeriod；EpicCode 由
    台供给步负责，与本票无关）。全部容忍 already。"""
    import socket
    import subprocess

    host, port = TEST_TARGET_HOST.split(":")
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(3.0)
    try:
        rc = s.connect_ex((host, int(port)))
    finally:
        s.close()
    if rc != 0:
        die_env("测试台 %s 不可达（sh server/docker-compose.test.yml up -d 起台后重试）"
                % TEST_TARGET_HOST)

    # temporal CLI 解析（supply 同款回落链，t260915-20 先例照抄）
    cand = os.path.join(TP_DIR, "bin", "temporal")
    if not os.path.exists(cand):
        import shutil as _sh
        which = _sh.which("temporal")
        if which:
            cand = which
        else:
            try:
                git_common = subprocess.run(
                    ["git", "rev-parse", "--path-format=absolute", "--git-common-dir"],
                    capture_output=True, text=True, timeout=15, cwd=REPO,
                ).stdout.strip()
                main_root = os.path.abspath(os.path.join(git_common or "", ".."))
            except Exception:  # noqa: BLE001
                main_root = ""
            found = ""
            for src in (os.path.join(main_root, "server", "engine", "bin", "temporal"),
                        os.path.join(main_root, "server", "dsh", "temporal-poc", "bin", "temporal")):  # engine-venv-compat（蓄意兼容回落：迁移窗机器旧布局候选，新路径优先；旧布局退役票落地后随 marker 撤除——t260907-10 行级豁免锚）
                if main_root and os.path.exists(src):
                    found = src
                    break
            if not found:
                die_env("temporal CLI 缺席（%s 或 PATH，主树候选也无）" % cand)
            try:
                os.makedirs(os.path.dirname(cand), exist_ok=True)
                if not os.path.exists(cand):
                    os.symlink(found, cand)
            except OSError as e:
                die_env("temporal CLI 软链补建失败（%s → %s）：%s" % (found, cand, e))

    # SA 幂等注册（CLI operator 子族吃全局 flag，t260915-20 实测）
    for name in SA_ALL:
        sa = subprocess.run(
            [cand, "--address", TEST_TARGET_HOST, "--namespace", TEST_NAMESPACE,
             "operator", "search-attribute", "create", "--name", name,
             "--type", "Keyword"],
            capture_output=True, text=True, timeout=60)
        blob = (sa.stdout or "") + (sa.stderr or "")
        if sa.returncode != 0 and "already" not in blob.lower():
            die_env("测试台 SA %s 注册失败：%s" % (name, blob[-200:]))
    return None


def delete_schedule_best_effort(instance_id: str) -> None:
    """退出自清：本场景自建的 schedule 幂等删除（失败只 WARN，不炸退出路径）。"""
    import subprocess
    cand = os.path.join(TP_DIR, "bin", "temporal")
    cli = cand if os.path.exists(cand) else None
    if not cli:
        return
    try:
        subprocess.run(
            [cli, "--address", TEST_TARGET_HOST, "--namespace", TEST_NAMESPACE,
             "schedule", "delete", "--schedule-id", "sandbar-inspection-%s" % instance_id],
            capture_output=True, text=True, timeout=60)
    except Exception as e:  # noqa: BLE001——清理失败 WARN 放行
        print("WARN: schedule 删除失败（%s）：%s" % (instance_id, e), flush=True)
