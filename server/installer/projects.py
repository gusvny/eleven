"""sandbar project 子命令族：注册表接入面（add/list/remove）。

立项真源 = notes/epics/project-lifecycle.md 票①（面A 接入 + 面C 报告）+
票②（面B 摘除，t260904-14）：
- add：fail-closed 前置校验 → 原子写 <注册表根>/<key>/project.yaml → 接入体检报告
  （黄牌只提示不代写不阻塞，exit 0）。t260906-01 容器式代建：根目录不存在=
  闸序全过后 mkdir 代建（含父目录）并落容器最小脚手架（scaffold.py，只对本次
  代建的新根落；已存在目录零覆盖；全程零 git，报告提示容器未含 git 仓库）。
- list：注册+隔离条目全列（隔离原因含 <dir>/project.yaml 定位）+ 每 key 票计数
  （子进程查 Temporal，服务不可达/SDK 缺失两态降级可辨且不红——KI-039 教训：
  依赖缺失不得吞成「无数据」，也不得与「不可达」混同）。
- remove：可逆摘除（契约①a-1）——模式闸（legacy 拒收）/最后条目确认闸/在飞闸
  （拒摘报票号；不可达 fail-closed 无绕过旗）/closed 全归档闸（purge 前置，未归档
  差集=Temporal COMPLETED−fs archive.json 三态判定）→ project.yaml 退役改名
  （retired-<UTC>，零 schema 改动可逆）→ 摘除报告（.lane/ 泳道只报不删、
  closed 未归档黄牌、数据字节数账目）；--purge-data/--purge-credentials 显式
  分离，--dry-run 全闸预演零现场变更。

CLI 契约面（与 integration/t260904-10 三场景共同冻结，改动须场景+ops 手册同步）：
  sandbar project add --key <key> --name <name> --dir <abs> [--dir <abs> ...] [--json]
  sandbar project list [--json]
  sandbar project remove --key <key> [--dry-run] [--purge-data]
                         [--purge-credentials] [--confirm-last] [--json]

装载复用真源 = server/engine/shared.py（importlib 按路径装载，不改本体；
与 TS 侧 server/project-registry.ts 同一注册表、两侧各自最小解析、语义同构）。
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
import time as _time

from installer import runtime as _runtime
from installer import scaffold as scaffold_mod
from installer.service import FailClosed

# 票计数子进程超时（秒）。超时路径由 subprocess.run 兜底（kill+wait，四路终态之一）。
TICKET_QUERY_TIMEOUT_S = 20.0

_LEGACY_ENV = "SANDBAR_PROJECTS_YAML"   # 存量标识，只引用不新增（CLAUDE.md 硬规则5）


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
    # t260906-01 代建：根目录不存在不再拒收——交由 cmd_project_add 闸序全过后代建
    # （mkdir parents，含父目录）并落容器脚手架；这里只把路径带回去。
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

    # t260906-01 代建+容器脚手架：闸序（装载/重名/交叉）全过后，根目录不存在=
    # 代建（mkdir parents，含父目录）并落容器最小脚手架（只对本次代建的新根落，
    # 已存在目录零覆盖）。脚手架先于条目写入：失败=红+全量回滚（含新建根），
    # 不留半成品容器。全程零 git（容器式定稿，容器无 git 仓库见报告提示）。
    created_root = not root.is_dir()
    if created_root:
        try:
            root.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            if created_dir:
                try:
                    key_dir.rmdir()  # 仅空目录可删（零残留口径）
                except OSError:
                    pass
            raise FailClosed("根目录代建失败：%s: %s" % (root, e))
    scaffold = {"created": [], "skipped": []}
    # JSON 口径下脚手架过程行静默（不污染机器输出）；账目走 JSON scaffold 字段。
    scaffold_log = (lambda *a, **k: None) if as_json else log
    if created_root:
        try:
            engine_root = getattr(paths, "root", None) or _runtime.repo_root()
            scaffold = scaffold_mod.scaffold_container(
                root, engine_root=pathlib.Path(engine_root), log=scaffold_log)
        except FailClosed:
            scaffold_mod.rollback_scaffold(root, scaffold, created_root=True)
            if created_dir:
                try:
                    key_dir.rmdir()  # 仅空目录可删（零残留口径）
                except OSError:
                    pass
            raise

    # 并发同 key TOCTOU 闸：排他认领 project.yaml（O_CREAT|O_EXCL），输家重装载确认后
    # 报幂等拒收——不静默覆盖；认领空文件即条目终点（tmp+rename 原子替换）。
    claim_fd = None
    try:
        claim_fd = os.open(str(target), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        try:
            projects2, quarantined2 = shared.load_projects_registry()
        except ValueError as e:
            _rollback_add(root, scaffold, created_root)
            raise FailClosed("注册表装载失败：%s" % e)
        if any(p["key"] == key for p in projects2) or \
                any(pathlib.Path(q["dir"]).name == key for q in quarantined2):
            _rollback_add(root, scaffold, created_root)
            raise FailClosed("项目 %s 已注册（并发 add 后写方）：add 幂等，已注册即拒收" % key)
        _rollback_add(root, scaffold, created_root)
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
        _rollback_after_write_failure(tmp, key_dir, target, created_dir,
                                      root, scaffold, created_root)
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
        _rollback_after_write_failure(tmp, key_dir, target, created_dir,
                                      root, scaffold, created_root)
        raise FailClosed("写后自检未过，已回滚（注册表零残留）：%s" % e)

    warnings, credentials_state = _health_report(shared, key)
    if created_root:
        warnings.append({
            "code": "container-no-git",
            "message": "容器未含 git 仓库（容器式定稿：add 不做任何 git 操作）——"
                       "开工单前需先建/clone repo（多 repo 支持与工单泳道挂靠改造"
                       "另行立项=票B）。",
        })
    if as_json:
        log(json.dumps({
            "ok": True, "action": "add",
            "project": {"key": key, "name": name, "dirs": [str(root)]},
            "entry": str(target),
            "root_created": created_root,
            "scaffold": scaffold,
            "credentials": credentials_state,
            "warnings": warnings,
        }, ensure_ascii=False, indent=2))
        return 0
    log("[绿] 项目已注册：%s（name=%s）" % (key, name))
    log("      注册条目：%s" % target)
    log("      根目录：%s%s" % (root, "（本次代建，含父目录）" if created_root else ""))
    if created_root:
        log("      生成物清单：\n        - %s\n        - %s"
            % ("\n        - ".join(scaffold.get("created", [])) or "（无）",
               ("（已存在跳过）" + "、".join(scaffold.get("skipped", [])))
               if scaffold.get("skipped") else "（零覆盖：无跳过项）"))
    if credentials_state == "present":
        log("[绿] 体检·credentials：per-key credentials.yaml 在位（无需回落）。")
    for w in warnings:
        log("[黄] 体检·%s：%s" % (w["code"], w["message"]))
    log("提示：黄牌只提示不代写不阻塞；第一张 dev-lane 票会按项目自备策略执行。")
    return 0


def _rollback_add(root, scaffold, created_root):
    """拒收路径的容器回滚：本票代建的根+脚手架产物一并清（零残留；仅本票新建，
    不碰他人数据）。"""
    scaffold_mod.rollback_scaffold(root, scaffold, created_root)


def _rollback_after_write_failure(tmp, key_dir, target, created_dir,
                                  root=None, scaffold=None, created_root=False):
    """写失败/自检失败的清理链：tmp 必清；条目文件可删——它要么是零字节认领、要么是
    本票刚写入的内容（认领经 O_EXCL 独占赢来，无并发写者，非他人数据）；目录仅当
    「本票创建且已空」才删——防误删预布置了 credentials 的目录（契约①b 旅程）；
    本票代建的容器（根+脚手架）一并清（t260906-01）。拒收零残留口径（C2）。"""
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
    if root is not None and scaffold is not None and created_root:
        scaffold_mod.rollback_scaffold(root, scaffold, created_root=True)


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


# ---------- remove（票②交付：可逆摘除） ----------
#
# remove 故障模式取舍（方案 gen2 R1 表，实现落点）：
#   ticket-list 子进程通道→带（temporalio 依赖隔离在子进程；超时 run 内 kill+wait、
#     stderr 收割、JSON 解析原样；扩展为票号级 rows——闸/报告都需要票号）；
#   各态语义反转→带（list 语境=降级黄牌不红；remove 语境=状态变更闸，unreachable/
#     sdk-missing/ok=false/坏 JSON 一律 fail-closed 拒摘，决策4 无绕过旗）；
#   子进程终态→三路实情落字（正常=wait 收割、报错=returncode+stderr、超时=run 内
#     kill+wait；同步调用无取消路——票① L329 自认，不照抄「四路」口号）；
#   sdk-missing 判定=stderr 字符串启发式→带不改（remove 侧两态同归红拒摘，误分类
#     不改变行为结局；为分类而分类=引入新漂移面）；
#   装载闸→带（票①闸 f 原样装载语义，两命令对同一注册表不得有两种装载口径）；
#   零残留→带+并发补强：回滚改名前 exists 检查 project.yaml——在位即放弃回滚、
#     报「现场已变，请重跑」（POSIX rename 对文件目标是静默替换，不得依赖其抛错）；
#   remove 并发立场→单宿主操作面定位（写操作只落安装器 CLI=宿主亲手），不做跨进程
#     互斥；可立住的保证=回滚路径绝不无条件覆盖他人新条目；
#   legacy env→带闸（同 add 闸 e：per-key 目录上的退役/purge 对运行时静默无效）。

_REMOVE_RETIRED_PREFIX = "project.yaml.retired-"


def _ticket_rows(paths, key):
    """票号级查询（复用票① _ticket_counts 的子进程通道，扩展返回 rows）。
    返回 (state, rows_or_detail)：state∈ok|unreachable|sdk-missing；ok 时
    rows=[{id, exec_status}]，否则 detail=诊断串。终态三路：正常=wait 收割；
    报错=returncode+stderr 收割；超时=run 内 kill+wait（同步调用无取消路）。"""
    args_json = json.dumps({"project": key}, ensure_ascii=False)
    cmd = [sys.executable, str(pathlib.Path(paths.poc_dir) / "client.py"),
           "ticket-list", args_json]
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=TICKET_QUERY_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        return "unreachable", "ticket-list 子进程超时（%.0fs，已终止回收）" % TICKET_QUERY_TIMEOUT_S
    if proc.returncode != 0:
        err = (proc.stderr or "").strip()
        if "No module named" in err or "temporalio" in err:
            # 启发式带而不改：remove 侧两态同归红拒摘，误分类不改变行为结局。
            return "sdk-missing", err.splitlines()[-1] if err else "temporalio SDK 缺失"
        return "unreachable", err.splitlines()[-1] if err else "exit %d" % proc.returncode
    try:
        payload = json.loads(proc.stdout)
    except ValueError:
        return "unreachable", "ticket-list 输出不是合法 JSON"
    if not payload.get("ok"):
        return "unreachable", str(payload.get("error") or "")
    rows = [{"id": r.get("id"), "exec_status": r.get("exec_status")}
            for r in (payload.get("result") or {}).get("tickets") or []]
    return "ok", rows


def _archived_ticket_ids(reg_root, key):
    """fs 侧已归档票号集合，判定锚=archive.json 三态（契约①a-1/①c 关闭语义）：
    - 在位且可解析（含 schema: v1）→ 已归档；
    - 目录在/manifest 缺 → 未归档（不在本集合）；
    - manifest 畸形（不可解析/缺 schema: v1）→ FailClosed 点名文件
      （不静默归侧、不静默重产——①c 明文「重产即消灭证据」）。"""
    d = reg_root / key / "data" / "tickets"
    archived = set()
    if not d.is_dir():
        return archived
    for sub in sorted(d.iterdir()):
        if not sub.is_dir() or sub.name.startswith("."):
            continue
        manifest = sub / "archive.json"
        if not manifest.is_file():
            continue  # 缺失态=未归档
        try:
            payload = json.loads(manifest.read_text("utf-8"))
        except (OSError, ValueError) as e:
            raise FailClosed(
                "归档 manifest 畸形（fail-closed，不静默归侧、不静默重产）：%s：%s"
                % (manifest, e))
        if payload.get("schema") != "v1":
            raise FailClosed(
                "归档 manifest 畸形（缺 schema: v1，fail-closed）：%s" % manifest)
        archived.add(sub.name)
    return archived


def _unarchived_closed_ids(paths, key, reg_root):
    """未归档差集（契约①a-1）：Temporal COMPLETED 票号集合 − fs 已归档集合。
    TERMINATED 族不进差集（ticket-list 不上台面，且归档对象=完结工单）。
    Temporal 各态非 ok 一律 FailClosed（remove 语义反转：不可达=拒摘拒 purge）。"""
    state, rows = _ticket_rows(paths, key)
    if state != "ok":
        raise FailClosed(
            "在飞闸不可过（Temporal %s：%s）——摘除拒执行、无绕过旗。"
            "先起 server（sandbar up）后重试；引擎真死透时走手工路径（先读 docs/ops 红线节）。"
            % (state, rows))
    archived = _archived_ticket_ids(reg_root, key)
    return sorted({r["id"] for r in rows if r.get("exec_status") == "COMPLETED"}
                  - archived), rows


def _dir_bytes(path: pathlib.Path) -> int:
    """目录字节数账目（摘除报告/将删清单用；读不到的项跳过计 0，账目只增不减真源）。"""
    total = 0
    if path.is_file():
        try:
            return path.stat().st_size
        except OSError:
            return 0
    if not path.is_dir():
        return 0
    for p in path.rglob("*"):
        try:
            if p.is_file():
                total += p.stat().st_size
        except OSError:
            pass
    return total


def _lane_dirs(root_dir: pathlib.Path):
    """项目根 .lane/ 各票泳道清单（只报不删；lane=票的空间）。"""
    lane = root_dir / ".lane"
    if not lane.is_dir():
        return []
    return sorted(c.name for c in lane.iterdir() if c.is_dir())


def cmd_project_remove(paths, args, log=print) -> int:
    """sandbar project remove --key <key> [--dry-run] [--purge-data]
    [--purge-credentials] [--confirm-last] [--json]。

    闸序（契约①a-1）：模式闸→装载/key 闸→最后条目闸→在飞闸→closed 全归档闸
    （purge 前置）→退役移位（os.replace 原子改名）→写后自检→摘除报告。
    默认不删任何数据；purge 双旗显式分离；--dry-run 全闸预演零现场变更。
    """
    shared = _load_shared(paths.poc_dir)
    as_json = bool(getattr(args, "json", False))
    as_dry = bool(getattr(args, "dry_run", False))
    purge_data = bool(getattr(args, "purge_data", False))
    purge_credentials = bool(getattr(args, "purge_credentials", False))
    confirm_last = bool(getattr(args, "confirm_last", False))

    # 闸 0（模式闸）：legacy 单文件模式在位 → 拒收（退役/purge 写 per-key 目录
    # 对运行时静默无效=假成功摘除；与 add 闸 e 同因同构）。
    if os.environ.get(_LEGACY_ENV):
        raise FailClosed(
            "%s 在位（legacy 单文件注册表模式）：remove/purge 写的是 per-key 目录，"
            "运行时读不到，摘除=假成功，拒绝执行。请移除该 env 后重试" % _LEGACY_ENV)

    # 闸 1（装载/key 闸）：原样走装载器全语义；key 白名单挡 traversal。
    key = str(getattr(args, "key", "") or "").strip()
    if not shared.PROJECT_KEY_RE.match(key):
        raise FailClosed(
            "key 不合法：%r（白名单 %s）" % (key, shared.PROJECT_KEY_RE.pattern))
    try:
        projects, quarantined = shared.load_projects_registry()
    except ValueError as e:
        raise FailClosed("注册表装载失败（remove 前置检查）：%s" % e)
    reg_root = shared.registry_root()
    project = next((p for p in projects if p["key"] == key), None)
    if project is None:
        hit = next((q for q in quarantined if pathlib.Path(q["dir"]).name == key), None)
        if hit is not None:
            raise FailClosed(
                "项目 %s 的注册目录存在但条目被隔离（%s：%s）。请先人工修复或处置该目录，"
                "remove 不对隔离现场执行摘除" % (key, hit["dir"], hit["error"]))
        raise FailClosed("项目 %s 未注册（remove 只摘已注册条目；全表见 sandbar project list）" % key)

    # 闸 2（最后条目闸）：摘最后一个注册条目=零条目警告语义 + 显式确认旗（验收9）。
    if len(projects) == 1 and not confirm_last:
        raise FailClosed(
            "%s 是注册表最后一个项目：摘除后装载器对空表抛错（注册表零条目=%s 无项目可服务）。"
            "确认摘除请加 --confirm-last" % (key, reg_root))

    root_dir = pathlib.Path((project.get("dirs") or [""])[0])
    target = reg_root / key / "project.yaml"

    # 闸 3（在飞闸）：running 非空=拒摘报票号；各态非 ok=FailClosed（语义反转）。
    unarchived, rows = _unarchived_closed_ids(paths, key, reg_root)
    running = sorted(r["id"] for r in rows if r.get("exec_status") == "RUNNING")
    if running:
        raise FailClosed(
            "项目 %s 有 %d 张在飞工单，拒摘（可逆摘除不对在飞票现场动注册表）：%s"
            % (key, len(running), "、".join(running)))

    credentials = reg_root / key / "credentials.yaml"
    data_dir = reg_root / key / "data"
    plan = {
        "retire": {"from": str(target), "to": None},
        "purge": {"data": {"path": str(data_dir), "bytes": _dir_bytes(data_dir)} if purge_data else None,
                  "credentials": {"path": str(credentials), "bytes": _dir_bytes(credentials)} if purge_credentials else None},
    }

    # 闸 4（closed 全归档闸，purge-data 前置；差集同时喂报告黄牌）。
    if purge_data and unarchived:
        raise FailClosed(
            "--purge-data 前置闸（closed 全归档）未过：%s 有 %d 张完结票未归档，"
            "删 data/=消灭审计真源。先归档（或核对差集）后重试。未归档票：%s"
            % (key, len(unarchived), "、".join(unarchived)))

    if as_dry:
        report = _removal_report(project, root_dir, reg_root, key,
                                 unarchived, running, purge_data, purge_credentials)
        if as_json:
            log(json.dumps({"ok": True, "action": "remove", "dry_run": True,
                            "project": {"key": key, "name": project.get("name", ""),
                                        "dirs": list(project.get("dirs") or [])},
                            "plan": plan, "report": report},
                           ensure_ascii=False, indent=2))
            return 0
        log("[演] dry-run：全闸已过，以下为将执行清单（零现场变更）——")
        log("      退役改名：%s → <同目录>/%s<UTC>" % (target, _REMOVE_RETIRED_PREFIX))
        if purge_data:
            log("      将删 data/：%s（%d 字节）" % (data_dir, plan["purge"]["data"]["bytes"]))
        if purge_credentials:
            log("      将删 credentials：%s（%d 字节）" % (credentials, plan["purge"]["credentials"]["bytes"]))
        if not purge_data and not purge_credentials:
            log("      data/ 与 credentials 原样保留（无 purge 旗）。")
        for w in report["warnings"]:
            log("[黄] %s" % w)
        log("      closed 未归档：%s" % ("、".join(unarchived) if unarchived else "无"))
        return 0

    # 退役移位（决策2）：同目录原子改名，不删数据；同前缀退役文件已存在=拒收
    # 点名人工处置（同秒碰撞/重复摘除现场，不猜后缀）。
    ts = _time.strftime("%Y-%m-%dT%H:%M:%SZ", _time.gmtime())
    retired = target.parent / (_REMOVE_RETIRED_PREFIX + ts)
    if retired.exists():
        raise FailClosed(
            "退役文件已存在：%s（同秒退役/重复摘除现场）。请人工处置后重试，"
            "remove 不猜后缀覆盖" % retired)
    if not target.is_file():
        raise FailClosed(
            "注册条目不在位（前次摘除已执行或现场被外部改动）：%s——请人工核对，"
            "remove 不重复摘除" % target)
    try:
        os.replace(str(target), str(retired))
    except OSError as e:
        raise FailClosed("退役改名失败（注册表零残留，条目原样在位）：%s: %s"
                         % (type(e).__name__, e))

    # 写后自检：装载不再列本 key、其余条目数与隔离数不变；不过=回滚改名。
    try:
        projects2, quarantined2 = shared.scan_registry(reg_root)
        if any(p["key"] == key for p in projects2):
            raise ValueError("退役后扫描仍见条目 %s" % key)
        if len(projects2) != len(projects) - 1 or len(quarantined2) != len(quarantined):
            raise ValueError("退役后全表现场变化（条目 %d→%d，隔离 %d→%d）"
                             % (len(projects), len(projects2),
                                len(quarantined), len(quarantined2)))
    except ValueError as e:
        # R1-4 并发补强：回滚前 exists 检查——POSIX rename 对文件目标静默替换，
        # 在位（并发 add 重建）即放弃回滚，绝不无条件覆盖他人新条目。
        if not target.exists():
            try:
                os.replace(str(retired), str(target))
            except OSError:
                pass
        if target.exists() and pathlib.Path(retired).exists():
            raise FailClosed(
                "写后自检未过且现场已变（并发 add 重建了条目），已放弃回滚——请重跑 remove 核对现场：%s" % e)
        raise FailClosed("写后自检未过，已回滚改名（注册表零残留）：%s" % e)

    # 数据处置：purge 双旗显式分离（闸 4 已过 purge-data）；删除路径形状由
    # key 白名单（无 / 与 ..）+ reg_root 拼接保证，不收用户直给的删除路径。
    purged = {"data": None, "credentials": None}
    if purge_data and data_dir.exists():
        _rmtree(data_dir)
        purged["data"] = str(data_dir)
    if purge_credentials and credentials.is_file():
        credentials.unlink()
        purged["credentials"] = str(credentials)

    report = _removal_report(project, root_dir, reg_root, key,
                             unarchived, running, purge_data, purge_credentials)
    if as_json:
        log(json.dumps({"ok": True, "action": "remove", "dry_run": False,
                        "project": {"key": key, "name": project.get("name", ""),
                                    "dirs": list(project.get("dirs") or [])},
                        "retired_to": str(retired),
                        "purged": purged, "report": report},
                       ensure_ascii=False, indent=2))
        return 0
    log("[绿] 项目已摘除（可逆）：%s（name=%s）" % (key, project.get("name", "")))
    log("      退役条目：%s（改回文件名即恢复，re-add 同 key 再接入）" % retired)
    if purged["data"]:
        log("      已 purge data/：%s" % purged["data"])
    if purged["credentials"]:
        log("      已 purge credentials：%s" % purged["credentials"])
    if not purged["data"] and not purged["credentials"]:
        # 摘除报告逐项字节数账目（gen2 方案承诺；验收6 的数据处置账目面）
        log("      data/（归档+metrics）原样保留：%d 字节；credentials.yaml 原样保留：%d 字节"
            "（默认摘除不删数据）。"
            % (report["data_bytes"], report["credentials_bytes"]))
    if report["lanes"]:
        log("      项目根 .lane/ 泳道残骸（只报不删，指路 teardown/手工清理）：")
        for name in report["lanes"]:
            log("        %s/.lane/%s" % (root_dir, name))
    for w in report["warnings"]:
        log("[黄] %s" % w)
    if len(projects) == 1:
        log("[黄] 注册表已零条目：装载器对空表抛错（%s 无项目可服务），"
            "请确认这是本意。" % reg_root)
    return 0


def _rmtree(path: pathlib.Path):
    """purge-data 删除（路径形状已由闸链保证：<registry_root>/<key 白名单>/data）。"""
    import shutil
    shutil.rmtree(path)


def _removal_report(project, root_dir, reg_root, key, unarchived, running,
                    purge_data, purge_credentials):
    """摘除报告（人读与 --json 共用口径）：数据账目/泳道清单（只报不删）/
    closed 未归档黄牌。"""
    warnings = []
    if unarchived:
        warnings.append("closed 未归档 %d 张（%s）——归档链未闭合，re-add 后建议先补档。"
                        % (len(unarchived), "、".join(unarchived)))
    data_dir = reg_root / key / "data"
    credentials = reg_root / key / "credentials.yaml"
    return {
        "lanes": _lane_dirs(root_dir),
        "data_bytes": _dir_bytes(data_dir),
        "credentials_bytes": _dir_bytes(credentials),
        "data_kept": not purge_data,
        "credentials_kept": not purge_credentials,
        "closed_unarchived": unarchived,
        "running_tickets": running,
        "warnings": warnings,
    }
