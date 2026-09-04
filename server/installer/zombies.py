"""doctor 第五面：异仓引擎进程（僵尸）探测（KI-033 防再犯，t260904-02）。

背景=260904 实案：suyou 时代遗留 headless（node，cwd=suyou poc）未随迁移清场，
新工单被其抢先 spawn 的 worker 接管（跨仓脑裂）。本探针把「迁移/切换后清点旧仓
引擎进程」从纪律变命令：扫 cwd 指向**非当前引擎仓**的 node/python 引擎进程，
红了逐个报出来（pid/命令/cwd），供人工清点——探针只读不杀（杀进程归人）。

三档输入（与 doctor 既有探针的 fixture/live 纪律同构）：
- 缺省（fixture 档）：内嵌干净样本（只练解析/判定逻辑，**不扫真机**）——绿行文案
  必须自辨「样本档」，防「跑过 doctor 绿」被误读为「无僵尸」（review C2）；
- --live：lsof 真扫全机进程 cwd（`lsof -F pnc -d cwd`；lsof 缺失/失败=显式红，
  不静默假绿——fail-closed）；
- SANDBAR_ZOMBIE_CENSUS=<file>：场景/人工注入 census JSON（红绿自证用）。

判定谓词（引擎进程 = 命令名 node/python*）：cwd 所在目录树是「引擎地界」（cwd 是
poc 目录、引擎仓根，或其祖先链上有 server/dsh/temporal-poc 标记），且该树的
git 归属**不属于当前仓家族**。家族=当前仓根 + 其主仓 + 主仓的全部 worktree
（读 .git/worktrees/ 枚举；worktree 的 .git 是 gitfile，指向主仓）——主树 console
与兄弟泳道 agent 是本仓正常活动，不红（真机实扫 333 进程里它们常驻，误报会让
doctor 永远红、训练用户无视告警）。归属不到任何 git 根的引擎树（fixture 注入的
假路径、裸目录）按异仓红——注入面成立。冻结旧仓（suyou）有独立 .git → 红。
"""

from __future__ import annotations

import json
import os
import subprocess

NAME = "probe-engine-zombies"

# poc 目录标记（引擎仓判据）：worker/console 的 cwd 常见就是它（260904 实案形态）。
_ENGINE_MARKER = os.path.join("server", "dsh", "temporal-poc")

# 引擎进程命令名白名单（basename 前缀/全等）：node 系与 python 系。
# 不含 dsh 本身——dsh 壳是脚本/二进制，其引擎面最终落在 node/python 进程上。
_COMMAND_RULES = ("node", "python")

# lsof 全量扫描超时（秒）：超时按「扫描失败=红」处理，不静默。
_LSOF_TIMEOUT = 30

# 缺省（fixture 档）内嵌干净样本：一条当前仓 node 引擎进程 + 一条无关进程。
# cwd 用占位 {ENGINE_ROOT}，probe() 调用时以真实 engine_root 代入——保证
# 「当前仓内的引擎进程=绿」这条判定在样本档也真被练到。
_EMBEDDED_SAMPLE_TEMPLATE = [
    {"pid": 100001, "command": "node /x/console/main.js", "cwd": "{ENGINE_ROOT}/server/dsh/temporal-poc"},
    {"pid": 100002, "command": "python3 /some/unrelated/tool.py", "cwd": "/Users/whoever/work"},
]


def _is_engine_command(command: str) -> bool:
    """命令是否 node/python 系（按第一个 token 的 basename 判，大小写不敏感——
    macOS framework Python 进程名是 "Python"）。"""
    if not isinstance(command, str) or not command.strip():
        return False
    head = command.strip().split()[0]
    base = os.path.basename(head).lower()
    return base == "node" or base.startswith("python")


def _family_roots(engine_root: str) -> set:
    """当前仓家族根集合：{当前仓根} ∪ {主仓根（若是 worktree）} ∪ {主仓全部 worktree}。

    worktree 的 .git 是 gitfile（"gitdir: <main>/.git/worktrees/<name>"）——读它
    找主仓；主仓侧枚举 .git/worktrees/* 收全家族。枚举失败（无该目录/权限）静默
    收窄为已知根——家族收窄只会多红不少红（保守方向正确）。"""
    roots = {os.path.realpath(engine_root)}
    main = _main_root_of(engine_root)
    if main is not None:
        roots.add(main)
        wt_dir = os.path.join(main, ".git", "worktrees")
        try:
            for name in os.listdir(wt_dir):
                d = os.path.join(wt_dir, name)
                if os.path.isdir(d):
                    roots.add(os.path.realpath(os.path.join(main, name)))
        except OSError:
            pass
    return roots


def _main_root_of(repo_root: str):
    """repo_root 若是 worktree（.git 为 gitfile）→ 返回主仓根；否则 None。
    gitfile 内容 "gitdir: <main>/.git/worktrees/<name>" → 主仓=gitdir 上三级。"""
    git_path = os.path.join(repo_root, ".git")
    try:
        if not os.path.isfile(git_path):
            return None
        with open(git_path, encoding="utf-8") as f:
            first = f.readline().strip()
    except OSError:
        return None
    if not first.startswith("gitdir:"):
        return None
    gitdir = os.path.normpath(first[len("gitdir:"):].strip())
    if not os.path.isabs(gitdir):  # 相对 gitfile 所在目录
        gitdir = os.path.normpath(os.path.join(repo_root, gitdir))
    parts = gitdir.split(os.sep)
    if len(parts) >= 3 and parts[-2] == "worktrees" and parts[-3] == ".git":
        return os.sep.join(parts[:-3])
    return None


def _engine_origin(cwd: str):
    """从 cwd 向上爬（至多 8 层，到 / 为止），返回 (is_engine, git_root)。

    is_engine=路径落在引擎地界（某祖先目录下存在 server/dsh/temporal-poc，
    或祖先本身以该标记结尾）；git_root=最近的 .git 归属根（无=None）。
    fixture 假路径（不存在的目录）自然走「有引擎标记、无 git 归属」→ 异仓。"""
    cur = os.path.normpath(cwd)
    marker_tail = os.sep + _ENGINE_MARKER
    is_engine = False
    git_root = None
    for _ in range(8):
        if not is_engine and (cur.endswith(marker_tail)
                              or os.path.isdir(os.path.join(cur, *_ENGINE_MARKER.split(os.sep)))):
            is_engine = True
        if git_root is None and os.path.exists(os.path.join(cur, ".git")):
            git_root = cur
        if is_engine and git_root is not None:
            break
        if cur == os.sep or len(os.path.dirname(cur)) >= len(cur):
            # 已到根（或 normpath 边界）：根目录自身再判一次标记后停
            if not is_engine and os.path.isdir(os.path.join(os.sep, *_ENGINE_MARKER.split(os.sep))):
                is_engine = True
            break
        cur = os.path.dirname(cur)
    return is_engine, git_root


def _points_foreign_engine(cwd: str, family: set) -> bool:
    """cwd 是否指向「非当前仓家族」的引擎地界（谓词见模块注释）。"""
    if not isinstance(cwd, str) or not cwd:
        return False
    is_engine, git_root = _engine_origin(cwd)
    if not is_engine:
        return False
    if git_root is None:
        return True   # 引擎地界但归属不到 git（fixture 假路径/裸目录）→ 保守红
    repo = git_root
    main = _main_root_of(repo)
    if main is not None:
        repo = main   # worktree 归属按主仓比（家族集合里两形态都有，双保险）
    real = os.path.realpath(repo)
    return real not in family and repo not in family


def parse_census(text: str) -> list:
    """解析 census JSON（契约形态：{"processes": [...]}；裸数组也收——UT 直喂便利）。
    元素 {pid:int>0, command:str, cwd:str}。畸形（非 JSON/形状错/缺键/类型错/
    非正 pid）→ ValueError，大声报错不静默。"""
    try:
        data = json.loads(text)
    except ValueError as e:
        raise ValueError("census 不是合法 JSON：%s" % e)
    if isinstance(data, dict):
        procs = data.get("processes")
        if not isinstance(procs, list):
            raise ValueError('census 对象形态必须含 "processes" 数组，实得 %s'
                             % type(procs).__name__)
        data = procs
    if not isinstance(data, list):
        raise ValueError("census 顶层必须是 {\"processes\":[…]} 或数组，实得 %s" % type(data).__name__)
    entries = []
    for i, item in enumerate(data):
        if not isinstance(item, dict):
            raise ValueError("census[%d] 必须是对象，实得 %s" % (i, type(item).__name__))
        pid, command, cwd = item.get("pid"), item.get("command"), item.get("cwd")
        if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0:
            raise ValueError("census[%d].pid 必须是正整数，实得 %r" % (i, pid))
        if not isinstance(command, str) or not command.strip():
            raise ValueError("census[%d].command 必须是非空字符串" % i)
        if not isinstance(cwd, str) or not cwd.strip():
            raise ValueError("census[%d].cwd 必须是非空字符串" % i)
        entries.append({"pid": pid, "command": command, "cwd": cwd})
    return entries


def judge_zombies(entries, engine_root: str) -> list:
    """从 census 条目里挑出异仓引擎进程（返回原条目列表，供红行逐个点名）。"""
    family = _family_roots(engine_root)
    hits = []
    for e in entries:
        if _is_engine_command(e.get("command", "")) and _points_foreign_engine(e.get("cwd", ""), family):
            hits.append(e)
    return hits


def _format_hits(hits) -> str:
    return "；".join("pid=%s cmd=%s cwd=%s" % (h.get("pid"), h.get("command"), h.get("cwd")) for h in hits)


def scan_live():
    """lsof 真扫全机进程 cwd。返回 (entries, error)：error 非空=扫描失败（fail-closed，
    调用方按红处理），entries 尽力解析（失败时为空表）。"""
    try:
        proc = subprocess.run(
            ["lsof", "-nP", "-w", "-F", "pnc", "-d", "cwd"],
            capture_output=True, text=True, timeout=_LSOF_TIMEOUT)
    except FileNotFoundError:
        return [], "lsof 不在 PATH（live 扫描不可用）"
    except subprocess.TimeoutExpired:
        return [], "lsof 超时（>%ds）" % _LSOF_TIMEOUT
    except OSError as e:
        return [], "lsof 启动失败：%s: %s" % (type(e).__name__, e)
    if proc.returncode != 0:
        tail = (proc.stderr or "").strip()[:200]
        return [], "lsof 退出码 %d：%s" % (proc.returncode, tail or "（无 stderr）")
    entries, cur = [], None
    saw_cwd_fd = False
    for line in proc.stdout.splitlines():
        if line.startswith("p") and line[1:].isdigit():
            cur = {"pid": int(line[1:]), "command": "", "cwd": ""}
            saw_cwd_fd = False
        elif line.startswith("c") and cur is not None:
            cur["command"] = line[1:]
        elif line.startswith("f") and cur is not None:
            saw_cwd_fd = line[1:] == "cwd"
        elif line.startswith("n") and cur is not None and saw_cwd_fd:
            cur["cwd"] = line[1:]
            if cur["command"]:
                entries.append(cur)
            cur = None
    return entries, ""


def probe(live: bool = False, engine_root=None, census_path=None):
    """探针入口（doctor 拼装点调用）。返回 (ok, detail)——不用 probes.ProbeResult，
    保持本模块 stdlib-only、对 probes 包零依赖（ProbeResult 包装归 doctor.py）。

    输入优先级：census 注入 > live 真扫 > 缺省内嵌干净样本。"""
    if engine_root is None:
        engine_root = os.getcwd()
    engine_root = os.path.realpath(engine_root)
    if census_path:
        try:
            with open(census_path, encoding="utf-8") as f:
                entries = parse_census(f.read())
        except OSError as e:
            return False, "census 注入文件不可读（%s）：%s: %s" % (census_path, type(e).__name__, e)
        except ValueError as e:
            return False, "census 注入畸形（%s）：%s" % (census_path, e)
        hits = judge_zombies(entries, engine_root)
        if hits:
            return False, "census 注入档：%d 个异仓引擎进程——%s" % (len(hits), _format_hits(hits))
        engine_procs = [e for e in entries if _is_engine_command(e.get("command", ""))]
        return True, ("census 注入档：%d 条样本（引擎进程 %d 个）无异仓引擎进程"
                      "（注入≠真机全貌，真扫用 --live）" % (len(entries), len(engine_procs)))
    if live:
        entries, err = scan_live()
        if err:
            return False, "live 扫描失败（fail-closed，不假绿）：%s" % err
        hits = judge_zombies(entries, engine_root)
        if hits:
            return False, "live 真扫 %d 进程：%d 个异仓引擎进程——%s（处置：人工清点，doctor 只读不杀）" % (
                len(entries), len(hits), _format_hits(hits))
        engine_procs = [e for e in entries if _is_engine_command(e.get("command", ""))]
        return True, "live 真扫 %d 进程（node/python %d 个）无 cwd 指向异仓引擎地界的进程" % (
            len(entries), len(engine_procs))
    sample = [{"pid": e["pid"], "command": e["command"], "cwd": e["cwd"].replace("{ENGINE_ROOT}", engine_root)}
              for e in _EMBEDDED_SAMPLE_TEMPLATE]
    hits = judge_zombies(sample, engine_root)
    if hits:  # 内嵌样本竟红=本探针自身回归（样本构造错），显式报不吞
        return False, "内嵌样本自检失败（这是探针 bug 不是环境问题）——%s" % _format_hits(hits)
    return True, ("缺省档=内嵌干净样本（未扫真机）：解析/判定逻辑绿。真扫请 --live；"
                  "fixture 注入请 SANDBAR_ZOMBIE_CENSUS=<census.json>")
