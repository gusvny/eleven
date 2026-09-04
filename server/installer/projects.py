"""sandbar project 子命令族：注册表接入面（add/list；remove 只挂点位，属票②）。

立项真源 = notes/epics/project-lifecycle.md 票①（面A 接入 + 面C 报告）：
- add：fail-closed 前置校验 → 原子写 <注册表根>/<key>/project.yaml → 接入体检报告
  （黄牌只提示不代写不阻塞，exit 0）。
- list：注册+隔离条目全列（隔离原因含 <dir>/project.yaml 定位）+ 每 key 票计数
  （子进程查 Temporal，服务不可达/SDK 缺失两态降级可辨且不红——KI-039 教训：
  依赖缺失不得吞成「无数据」，也不得与「不可达」混同）。
- remove：票②交付，本版恒红占位。

CLI 契约面（与 integration/t260904-10 三场景共同冻结，改动须场景+ops 手册同步）：
  sandbar project add --key <key> --name <name> --dir <abs> [--dir <abs> ...] [--json]
  sandbar project list [--json]
  sandbar project remove --key <key> [--json]   （恒红，票②）

装载复用真源 = server/dsh/temporal-poc/shared.py（importlib 按路径装载，不改本体；
与 TS 侧 server/dsh/suyou-projects.ts 同一注册表、两侧各自最小解析、语义同构）。
本模块 stdlib-only（installer 惯例；temporalio 依赖隔离在票计数子进程里）。

add 写入故障模式取舍（方案 R2 表，实现落点）：
  tmp 并发互踩→带（_registry_tmp_name 唯一后缀）；写失败残留→带（tmp+认领+空目录清理）；
  幂等同字节跳过→不带（add 语义=已注册即拒收，与迁移的幂等重写不同）；
  值严格子集校验→带（name/dirs 拒 # 与换行）；并发同 key TOCTOU→带——
  排他锚=project.yaml 文件（O_CREAT|O_EXCL 认领），**不锚条目目录**：契约①b 的
  合法用户旅程允许先手工布置 <root>/<key>/credentials.yaml（目录可先于 add 存在），
  目录 mkdir 闸会把这条旅程判死；文件认领对并发同 key 提供同一保证（输家
  FileExistsError → 重装载 → 幂等拒收，绝不静默覆盖）。

出口码沿用 cli.py：0=绿；1=红（FailClosed，语义拒收）；2=用法错（argparse 面）。
"""

from __future__ import annotations

import importlib.util
import json
import os
import pathlib
import subprocess
import sys

from installer.service import FailClosed

# 票计数子进程超时（秒）。超时路径由 subprocess.run 兜底（kill+wait，四路终态之一）。
TICKET_QUERY_TIMEOUT_S = 20.0

_LEGACY_ENV = "SUYOU_PROJECTS_YAML"   # 存量标识，只引用不新增（CLAUDE.md 硬规则5）


def _load_shared(poc_dir):
    """按路径装载装载器真源 shared.py（不污染 sys.path；同名已装载且同源则复用）。"""
    path = str(pathlib.Path(poc_dir) / "shared.py")
    mod = sys.modules.get("shared")
    if mod is not None and str(getattr(mod, "__file__", "")) == path:
        return mod
    spec = importlib.util.spec_from_file_location("shared", path)
    if spec is None or spec.loader is None:
        raise FailClosed("装载器真源不可定位：%s" % path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["shared"] = mod
    spec.loader.exec_module(mod)
    return mod


# ---------- 值校验（闸 g：严格最小 YAML 子集——# 起注释被装载器剥掉，换行破结构） ----------

def _check_scalar(field: str, value: str):
    """name/dirs 值校验：非空、不含 # 与换行（写入即自隔离/值损坏的故障形态，源头拒）。"""
    if not value or not value.strip():
        raise FailClosed("%s 不能为空" % field)
    if "#" in value:
        raise FailClosed("%s 含 #（装载器按行尾注释剥掉，值会静默损坏），拒绝写入" % field)
    if "\n" in value or "\r" in value:
        raise FailClosed("%s 含换行（破坏条目文件结构），拒绝写入" % field)


def validate_add_inputs(key: str, name: str, root_dirs):
    """add 前置校验闸（纯输入面）：key 白名单 / name 标量 / 根目录恰一个·绝对·存在。

    多目录输入=语义拒收（单根模型，决策6：工具恰写一条 dirs，多目录形状不提供）。
    返回 (key, name_trimmed, root_path)。"""
    shared = sys.modules.get("shared")
    if not shared:
        raise FailClosed("内部错误：装载器未初始化")
    key = str(key or "").strip()
    if not shared.PROJECT_KEY_RE.match(key):
        raise FailClosed(
            "key 不合法：%r（白名单 %s：小写字母/数字/中划线，小写字母或数字开头）"
            % (key, shared.PROJECT_KEY_RE.pattern))
    name = str(name or "").strip()
    _check_scalar("name", name)
    dirs = [str(d or "").strip() for d in (root_dirs or [])]
    if len(dirs) != 1:
        raise FailClosed(
            "单根目录模型（决策6）：--dir 恰给一个根目录，实际 %d 个——多目录=归属歧义，"
            "拒绝注册（多 repo 项目请用父目录作根）" % len(dirs))
    root = dirs[0]
    _check_scalar("root_dir", root)
    if not os.path.isabs(root):
        raise FailClosed("根目录必须是绝对路径：%r（相对路径随 cwd 漂移，拒绝）" % root)
    p = pathlib.Path(root)
    if not p.is_dir():
        raise FailClosed("根目录不存在或不是目录：%s（add 不代建项目目录）" % root)
    return key, name, p


def serialize_project_entry(key: str, name: str, dirs) -> str:
    """per-key 注册条目序列化（schema v1 严格最小子集，与装载器 parse_project_file
    同构可往返；注释行自述来源，不用迁移器 seed 标注）。"""
    _check_scalar("key", key)
    _check_scalar("name", name)
    dirs = list(dirs)
    if len(dirs) != 1:
        raise FailClosed("单根目录模型：恰写一条 dirs，实际 %d 条" % len(dirs))
    for d in dirs:
        _check_scalar("dirs 条目", d)
    lines = [
        "# 由 sandbar project add 写入，格式=契约① per-key 注册条目（schema v1）",
        "schema: v1",
        "project:",
        "  - key: %s" % key,
        "    name: %s" % name,
        "    dirs:",
        "      - %s" % dirs[0],
    ]
    return "\n".join(lines) + "\n"


def _norm(path: str) -> str:
    return os.path.normpath(str(path))


def _crossing_with(new_root: pathlib.Path, projects):
    """根交叉/互为父子嵌套检查（决策6 阻塞闸）。返回 (key, dir) 或 None。
    票的空间=项目根 .lane/，根交叠=归属歧义，宁可拒收报两个 key。"""
    new = _norm(new_root)
    for p in projects:
        for d in p.get("dirs") or []:
            old = _norm(d)
            if new == old or new.startswith(old + os.sep) or old.startswith(new + os.sep):
                return p["key"], d
    return None


# ---------- add ----------

def cmd_project_add(paths, args, log=print) -> int:
    """sandbar project add --key <key> --name <name> --dir <abs> [--json]。"""
    shared = _load_shared(paths.poc_dir)
    as_json = bool(getattr(args, "json", False))

    # 闸 e：legacy 单文件模式在位 → 拒收指路（写 per-key 目录=运行时静默无效）。
    if os.environ.get(_LEGACY_ENV):
        raise FailClosed(
            "%s 在位（legacy 单文件注册表模式）：add 只写 per-key 目录，运行时读不到，"
            "拒绝执行。请移除该 env 后重试（迁移语义见装载器 shared.load_projects_registry）"
            % _LEGACY_ENV)

    key, name, root = validate_add_inputs(getattr(args, "key", ""),
                                          getattr(args, "name", ""),
                                          getattr(args, "dir", None) or [])
    reg_root = shared.registry_root()

    # 闸 f：前置装载原样走装载器全语义（seed 自动播种 / 三类现场判定 / 混合现场
    # fail-closed），不绕过不预判、不自行建根——装载不过就是红（R4 口径）。
    try:
        projects, quarantined = shared.load_projects_registry()
    except ValueError as e:
        raise FailClosed("注册表装载失败（add 前置检查）：%s" % e)

    # 闸 c：key 已注册（含隔离条目同名）→ 幂等重跑同判（两次输出全等）。
    for p in projects:
        if p["key"] == key:
            raise FailClosed(
                "项目 %s 已注册（name=%s，dirs=%s）。add 幂等：已注册即拒收，不做改写"
                % (key, p.get("name", ""), "、".join(p.get("dirs") or [])))
    for q in quarantined:
        if pathlib.Path(q["dir"]).name == key:
            raise FailClosed(
                "项目 %s 已有注册目录但条目被隔离（%s：%s）。请先人工修复或移除该目录，"
                "add 不覆盖现场" % (key, q["dir"], q["error"]))

    # 闸 d：根目录交叉/互为父子 → 拒收报两个 key。
    hit = _crossing_with(root, projects)
    if hit is not None:
        raise FailClosed(
            "根目录 %s 与已注册项目 %s 的目录 %s 交叉或互为父子嵌套（单根模型："
            "根交叠=票空间归属歧义）。涉及 key：%s、%s——拒绝注册"
            % (root, hit[0], hit[1], hit[0], key))

    content = serialize_project_entry(key, name, [str(root)])
    key_dir = reg_root / key
    target = key_dir / "project.yaml"
    created_dir = not key_dir.is_dir()
    # 契约①b 旅程：目录可先在（预布置 credentials.yaml 等），缺则建（幂等）。
    key_dir.mkdir(parents=True, exist_ok=True)

    # 并发同 key TOCTOU 闸：排他认领 project.yaml（O_CREAT|O_EXCL），输家重装载确认后
    # 报幂等拒收——不静默覆盖；认领空文件即条目终点（tmp+rename 原子替换）。
    claim_fd = None
    try:
        claim_fd = os.open(str(target), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        try:
            projects2, quarantined2 = shared.load_projects_registry()
        except ValueError as e:
            raise FailClosed("注册表装载失败：%s" % e)
        if any(p["key"] == key for p in projects2) or \
                any(pathlib.Path(q["dir"]).name == key for q in quarantined2):
            raise FailClosed("项目 %s 已注册（并发 add 后写方）：add 幂等，已注册即拒收" % key)
        raise FailClosed(
            "注册条目已存在但装载不可见：%s（并发写入现场）。请人工处置后重试，add 不覆盖"
            % target)
    finally:
        if claim_fd is not None:
            os.close(claim_fd)

    # 原子写：tmp + os.replace（原子替换认领空文件）；失败清理链见 _rollback。
    tmp = pathlib.Path(shared._registry_tmp_name(target))
    try:
        tmp.write_text(content, "utf-8")
        os.replace(tmp, target)
    except OSError as e:
        _rollback_after_write_failure(tmp, key_dir, target, created_dir)
        raise FailClosed("条目写入失败，已回滚（注册表零残留）：%s: %s"
                         % (type(e).__name__, e))

    # 写后自检：内容可被装载器解析 + 全表现场零隔离不变。不过=红并回滚本票产物。
    try:
        shared.parse_project_file(content, str(target))
        projects3, quarantined3 = shared.scan_registry(reg_root)
        if not any(p["key"] == key for p in projects3):
            raise ValueError("写后扫描未见新条目 %s" % key)
        if len(quarantined3) != len(quarantined):
            raise ValueError("写后出现隔离条目（%d → %d）"
                             % (len(quarantined), len(quarantined3)))
    except ValueError as e:
        _rollback_after_write_failure(tmp, key_dir, target, created_dir)
        raise FailClosed("写后自检未过，已回滚（注册表零残留）：%s" % e)

    warnings, credentials_state = _health_report(shared, key)
    if as_json:
        log(json.dumps({
            "ok": True, "action": "add",
            "project": {"key": key, "name": name, "dirs": [str(root)]},
            "entry": str(target),
            "credentials": credentials_state,
            "warnings": warnings,
        }, ensure_ascii=False, indent=2))
        return 0
    log("[绿] 项目已注册：%s（name=%s）" % (key, name))
    log("      注册条目：%s" % target)
    log("      根目录：%s" % root)
    if credentials_state == "present":
        log("[绿] 体检·credentials：per-key credentials.yaml 在位（无需回落）。")
    for w in warnings:
        log("[黄] 体检·%s：%s" % (w["code"], w["message"]))
    log("提示：黄牌只提示不代写不阻塞；第一张 dev-lane 票会按项目自备策略执行。")
    return 0


def _rollback_after_write_failure(tmp, key_dir, target, created_dir):
    """写失败/自检失败的清理链：tmp 必清；条目文件可删——它要么是零字节认领、要么是
    本票刚写入的内容（认领经 O_EXCL 独占赢来，无并发写者，非他人数据）；目录仅当
    「本票创建且已空」才删——防误删预布置了 credentials 的目录（契约①b 旅程）。
    拒收零残留口径（C2）。"""
    try:
        if tmp.is_file():
            tmp.unlink()
    except OSError:
        pass
    try:
        if target.is_file():
            target.unlink()
    except OSError:
        pass
    if created_dir:
        try:
            key_dir.rmdir()  # 仅空目录可删；非空（预布置/并发）原样保留
        except OSError:
            pass


def _health_report(shared, key):
    """接入体检报告：三类黄牌，契约三态=缺失只提示、不代写、不阻塞（报告不是闸）。
    credentials 两态可辨：在位（①b 旅程预布置）=绿行不进黄牌；缺失=回落提示黄牌。"""
    out = []
    # ① verify.yaml：承载位置由项目注册自定（契约②a，.sandbar/ 非硬性路径）——
    #   不猜路径、不查假路径报「缺失」，只提示未声明。
    out.append({
        "code": "verify-yaml-undeclared",
        "message": "项目未声明 verify.yaml 位置（契约②a：承载位置由项目注册自定）。"
                   "若第一张票需要集成测试而项目未自备，会在 integration 道红。",
    })
    # ② credentials：add 不代拷（260904 定案）；per-key 在位=绿；缺失=①b 回落提示。
    cred = shared.registry_root() / key / "credentials.yaml"
    credentials_state = "present" if cred.is_file() else "fallback"
    if credentials_state == "fallback":
        out.append({
            "code": "credentials-fallback",
            "message": "per-key credentials.yaml 不存在（%s）——运行时按①b 回落 dsh 平台"
                       "文件（DSH_HOME/.credentials.yaml → ~/.dsh/.credentials.yaml，"
                       "弃用窗口口径）。add 不代拷。" % cred,
        })
    # ③ paths：本工具不产 paths 节——无声明=按现行约定回落。
    out.append({
        "code": "paths-default",
        "message": "未声明 paths 节——roles_dir/model_routes 按现行约定回落"
                   "（roles 相对 spawn cwd，model_routes 相对注册主目录）。",
    })
    return out, credentials_state


# ---------- list ----------

def _archived_count(reg_root, key) -> int:
    """已归档票计数（本地 fs：<root>/<key>/data/tickets/<id>/ 子目录数，契约①c）。"""
    d = reg_root / key / "data" / "tickets"
    if not d.is_dir():
        return 0
    return sum(1 for c in d.iterdir() if c.is_dir() and not c.name.startswith("."))


def _ticket_counts(paths, key, reg_root):
    """票计数三态（R5 口径，KI-039 教训：依赖缺失必须可辨，不得吞成「无数据」）：
    - ok：{"state":"ok","open":n,"closed":m,"archived":a}
    - unreachable：Temporal 服务不可达/输出不可解析/超时（detail 带诊断）
    - sdk-missing：子进程缺 temporalio SDK（与不可达分开报，两态输出可辨）
    子进程隔离 temporalio 依赖（client.py 顶层 import；installer 保持 stdlib-only）。
    终态四路：正常=wait 收割；报错=returncode+stderr 收割；超时=run 内 kill+wait；
    本函数无取消路径（同步调用）。"""
    args_json = json.dumps({"project": key}, ensure_ascii=False)
    cmd = [sys.executable, str(pathlib.Path(paths.poc_dir) / "client.py"),
           "ticket-list", args_json]
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=TICKET_QUERY_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        return {"state": "unreachable",
                "detail": "ticket-list 子进程超时（%.0fs，已终止回收）" % TICKET_QUERY_TIMEOUT_S}
    if proc.returncode != 0:
        err = (proc.stderr or "").strip()
        if "No module named" in err or "temporalio" in err:
            last = err.splitlines()[-1] if err else "temporalio SDK 缺失"
            return {"state": "sdk-missing", "detail": last}
        return {"state": "unreachable",
                "detail": err.splitlines()[-1] if err else "exit %d" % proc.returncode}
    try:
        payload = json.loads(proc.stdout)
    except ValueError:
        return {"state": "unreachable", "detail": "ticket-list 输出不是合法 JSON"}
    if not payload.get("ok"):
        return {"state": "unreachable", "detail": str(payload.get("error") or "")}
    rows = (payload.get("result") or {}).get("tickets") or []
    open_n = sum(1 for r in rows if r.get("exec_status") == "RUNNING")
    closed_n = sum(1 for r in rows if r.get("exec_status") == "COMPLETED")
    return {"state": "ok", "open": open_n, "closed": closed_n,
            "archived": _archived_count(reg_root, key)}


def cmd_project_list(paths, args, log=print) -> int:
    """sandbar project list [--json]。只读报告：注册表装载失败才红；Temporal 降级不红。"""
    shared = _load_shared(paths.poc_dir)
    as_json = bool(getattr(args, "json", False))
    legacy = os.environ.get(_LEGACY_ENV)
    try:
        projects, quarantined = shared.load_projects_registry()
    except ValueError as e:
        raise FailClosed("注册表装载失败：%s" % e)
    reg_root = shared.registry_root()

    entries = []
    degraded = []
    for p in projects:
        counts = _ticket_counts(paths, p["key"], reg_root)
        if counts["state"] != "ok":
            degraded.append((p["key"], counts))
            row = {"key": p["key"], "name": p.get("name", ""),
                   "dirs": list(p.get("dirs") or []), "tickets": None,
                   "tickets_state": counts["state"], "tickets_note": counts["detail"]}
        else:
            row = {"key": p["key"], "name": p.get("name", ""),
                   "dirs": list(p.get("dirs") or []),
                   "tickets": {"open": counts["open"], "closed": counts["closed"],
                               "archived": counts["archived"]}}
        entries.append(row)

    quarantine_rows = [{"key": pathlib.Path(q["dir"]).name,
                        "dir": q["dir"], "error": q["error"]} for q in quarantined]

    if as_json:
        log(json.dumps({
            "ok": True, "action": "list",
            "mode": "legacy" if legacy else "per-key",
            "projects": entries,
            "quarantined": quarantine_rows,
        }, ensure_ascii=False, indent=2))
        return 0

    mode_note = "（legacy 单文件模式：%s，无隔离概念）" % legacy if legacy else ""
    log("注册项目 %d 个%s：" % (len(entries), mode_note))
    for row in entries:
        if row["tickets"] is not None:
            t = row["tickets"]
            count_s = "在飞 %d / 完结 %d / 已归档 %d" % (t["open"], t["closed"], t["archived"])
        else:
            count_s = "票计数降级（%s：%s）" % (row["tickets_state"], row["tickets_note"])
        log("  %s  %s  根目录：%s  票：%s"
            % (row["key"], row["name"], "、".join(row["dirs"]), count_s))
    if quarantine_rows:
        log("隔离条目 %d 个（fail-closed 可见，不炸全表）：" % len(quarantine_rows))
        for q in quarantine_rows:
            log("  %s\n    原因：%s" % (q["dir"], q["error"]))
    for key, counts in degraded:
        log("[黄] %s 票计数降级（%s：%s）——只读报告不阻塞；要查票先起 server"
            "（sandbar up）后重试。" % (key, counts["state"], counts["detail"]))
    return 0


# ---------- remove（票②点位） ----------

def cmd_project_remove(paths, args, log=print) -> int:
    """remove 属票②（project-lifecycle）交付：在飞闸/退役移位/摘除报告/purge 双旗
    尚未实现，本版恒红占位——不提供半成品摘除路径（fail-closed 纪律）。"""
    del paths, args, log
    raise FailClosed(
        "project remove 属票②交付，本版未实现（在飞闸/退役移位/摘除报告/purge 闸随票②落地）。"
        "当前摘除请走人工口径并先读 docs/ops 操作手册的红线节（审计真源不蒸发）。")
