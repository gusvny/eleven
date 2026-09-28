"""Event ledger（工单 t260928-13，epic project-executor 第一片）：每项目一条
append-only JSONL 事件流（<引擎数据目录>/ledger/<project>.jsonl），逐行记票的
段状态迁移（stage-state transition），供 watchdog / panel / request ledger /
wake-ups 等后续 epic 件消费。

设计基准=已过审方案 .sandbar/plan_event_ledger.md（gen1，[R1]–[R6] 全落地）。
借用面=audit.py 的 admin_log 先例（路径/env 覆盖、project.yaml 行式解析、
rolling+sweep 轮转、配置缓存键形状），借镜故障面 carried/dropped 清单见方案
[R1] 表——此处只重申关键两条：
  - 轮转=纯命名面 rename（POSIX 下对持有 O_APPEND fd 的并发写者安全），不重写
    活动文件内容；rename→announce 在同一活动体内相邻两语句、中间无 await，
    不存在 audit._adopt_orphan 要收养的「半轮转孤儿」形态（dropped 理由）。
  - 配置读不到/解析坏一律回落内置缺省（fail-open），绝不阻断事件写。

核心口径：
  - 一行一事件，单次 O_APPEND write，行 <4KB（reason 超限截断点名）。
  - 幂等键 idem = project|ticket|run_id|seq（[R3]：run_id 隔离同票新工作流
    run 的 seq 重启，重放稳定）；at-least-once 重投永不落第二行。
  - 去重=[R4] 命中缓存（每路径有界 FIFO 集，cap 4096，逐出只可能多一次扫盘，
    绝不会错压制）未命中 → 扫活动文件定夺——冷进程（重启/第二个 worker）仍认
    得已有键。**已声明局限（多进程 TOCTOU）**：同一事件同时重投到两个写者进程
    时，scan-then-append 不原子，可能各落一行；重复 idem 行是重建/对账面的已知
    良性伪影（ledger_rebuild 只计数上报，绝不重复修复）。O_APPEND 保证单行自身
    原子。
  - fail-open 且 LOUD（[R5]）：账面写失败永不 raise。**保证面**（永远可得）=
    点名 stderr 行 + 模块计数器 WRITE_FAILURES；**机会面** = <project>.gaps.jsonl
    补一条 {"gap": true,...}（磁盘满/目录只读时该补写也失败→再点一次 stderr 后
    吞掉）。绝无静默成功；对账路径按 timeline 跑 ledger_rebuild 补洞。
  - 未声明/停用（project.yaml 无 event_ledger: 或 enabled 非 true）⇒ 活动直接
    返回 {"emitted": false}，零文件行为（验收⑧）。注意 gate 在活动侧：workflow
    侧不读文件（重放安全），停用项目的代价只是每迁移一次空跑活动。
  - 配置（per-project，声明在场才生效）：event_ledger: {enabled, keep_days,
    max_mb}——keep_days 内置缺省 14（文档化缺省），≤0=永不删；max_mb ≤0=关
    rolling。本账只装事件（无未应答项），rename 轮转天然不丢未应答项；策略在
    配置不在代码。
  - rebuild：ledger_rebuild() 从该票 timeline 里带 ledger_seq/ledger_run 标记的
    条目重生成期望行，与活动文件比对，只补缺失 idem 的行——账本是时间线的派生
    投影（derived & rebuildable）这一性质由此向用户可证。

单进程单写者之外的并发（同项目多票各占独立 worker 进程写同一账本）：O_APPEND
保行原子；幂等键判定见上 TOCTOU 局限声明。
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from temporalio import activity

from shared import ENGINE_VERSION_V2

SCHEMA_V = "event-ledger-v1"
LINE_LIMIT = 4096           # 单行硬上限（字节），reason 先截断再拼行
REASON_LIMIT = 1200         # reason 截断点（留足其余字段的行内余量）
REASON_TRUNC_MARK = "…(截断,原文不落盘)"
IDEM_SET_CAP = 4096         # 每路径幂等键加速集容量（FIFO 逐出；纯加速器）
DEFAULT_KEEP_DAYS = 14      # 保留窗内置缺省（event_ledger.keep_days 缺席兜底；≤0=永不删）
DEFAULT_MAX_MB = 512        # rolling 阈值内置缺省；≤0=关 rolling
ENGINE_DATA_DIR = Path(__file__).resolve().parent.parent   # server/
GAPS_SUFFIX = ".gaps.jsonl"
_ARCH_SUFFIX_RE = re.compile(r'^(\d{8})(?:-(\d{6}))?(?:-([0-9a-f]{1,8}))?$')

# 活动重投/冷进程共享的幂等键加速集：path → (set(keys), deque(order))。
_SEEN: Dict[str, tuple] = {}
# [R5] 保证面计数器：账面写失败次数（gaps 补写失败单独计，见 GAPS_FAILURES）。
WRITE_FAILURES = 0
GAPS_FAILURES = 0


def _ledger_dir() -> Path:
    """账本目录（测试隔离 env SANDBAR_EVENT_LEDGER_DIR 优先；缺省=引擎数据目录
    server/ledger/，与 audit.ADMIN_LOG 同根）。"""
    env = os.environ.get('SANDBAR_EVENT_LEDGER_DIR')
    return Path(env) if env else (ENGINE_DATA_DIR / 'ledger')


def ledger_path(project: str, ledger_dir: Optional[Path] = None) -> Path:
    return (Path(ledger_dir) if ledger_dir else _ledger_dir()) / ('%s.jsonl' % project)


# ---- 配置面（借镜 audit.py：行式解析 + 三元缓存键；畸形逐键回落缺省） ----

def _projects_root():
    """注册表根（与 audit._projects_root 同口径的本地镜像，避免私有跨模块耦合）：
    SANDBAR_PROJECTS_DIR 覆盖 > ~/.sandbar/projects。"""
    return Path(os.environ.get('SANDBAR_PROJECTS_DIR')
                or (Path.home() / '.sandbar' / 'projects'))


def _strip_yaml_line(raw):
    line = re.sub(r'#.*$', '', raw).rstrip()
    return line if line.strip() else None


def _parse_event_ledger_overrides(text):
    """从 project.yaml 文本提取顶层 `event_ledger:` 块的 enabled/keep_days/max_mb
    （additive 顶层段，读面归本模块）。

    **不是「旧读取方零感知」**（260928 实测纠正：本模块首版 docstring 声称「shared 顶层段
    白名单不动」，与实际入口不符并因此误导）——注册表唯一装载器
    `shared.parse_project_file` 有顶层键白名单，段名不在其中则**整条注册条目被隔离**，
    宿主症状=控制台左栏该项目整块消失（260928 实案：声明 `event_ledger:` 后 sandbar
    即刻不可见，修于 `0c0ee58` 放行该键）。凡新增/改用本段，前提是装载器白名单已同批
    放行；跨模块一致性锁见 integration/t260928-13/sc_registry_additive_keys.py 的 A2
    （从读者源码派生段名逐个断言装载器容忍，新增第三个段会被该锁自动要求放行）。

    逐键容错：非整数值该键回落缺省（不整体作废）。"""
    out: Dict[str, Any] = {}
    in_block = False
    for i, raw in enumerate(text.splitlines()):
        stripped = _strip_yaml_line(raw)
        if stripped is None:
            continue
        if not raw[:1].isspace():
            in_block = (stripped == 'event_ledger:')
            continue
        if not in_block:
            continue
        m = re.match(r'^(\w+):\s*(.*?)\s*$', stripped.strip())
        if not m:
            continue
        key, val = m.group(1), m.group(2)
        if key == 'enabled':
            out['enabled'] = str(val).strip().lower() in ('true', '1', 'yes', 'on')
        elif key in ('keep_days', 'max_mb'):
            try:
                out[key] = int(str(val).strip())
            except ValueError:
                pass    # 非整数：该键缺席=内置缺省（[R1] 畸形值逐键回落）
    return out


#: 引擎仓根（本模块位于 <repo>/server/engine/）。与 audit.ENGINE_REPO 同式——
#: 两处必须等价，由 tests/test_event_ledger.py 的一致性锁钉住。
ENGINE_REPO = Path(__file__).resolve().parents[2]


def _dirs_cover_engine(text) -> bool:
    """条目 dirs 是否覆盖引擎仓根（等值或祖先——主仓命中等值，worktree 命中祖先）。

    **忠实镜像 audit._dirs_cover_engine 的语义，且刻意不 import audit**：本模块被
    base.py 在工作流的 `imports_passed_through()` 块里 import，而 audit 不在工作流
    沙箱的 passthrough 清单内（那份清单只收项目外置模板模块）——把 audit 拖进工作流
    依赖图会触发「Failed validating workflow」（KI-143 同族）。故此处本地实现，并以
    一致性锁（同一组夹具下与 audit 版选中同一文件）防两处漂移。

    历史（t260928-13 合并后复核发现并修复）：本函数最初**没有落地**——`_find_engine
    _project_yaml` 当时用「有 `paths:` 段 + 任意列表项」冒充本守卫，于是按目录名稳定序
    会命中**任意**恰好带 paths 段的项目（实测命中 dengzhufpv），引擎账本的 enabled 声明
    写了也不生效（静默失效）；且原 docstring 仍声称 dirs 规则，误导读者。"""
    repo = ENGINE_REPO
    in_dirs = False
    for raw in text.split('\n'):
        line = _strip_yaml_line(raw)
        if line is None:
            continue
        if not line[:1].isspace():
            in_dirs = False
            continue
        s = line.strip()
        if s == 'dirs:':
            in_dirs = True
            continue
        if in_dirs:
            m = re.match(r'^-\s+(\S+)\s*$', s)
            if m:
                try:
                    p = Path(os.path.realpath(m.group(1)))
                except OSError:
                    continue
                if p == repo or p in repo.parents:
                    return True
            else:
                in_dirs = False
    return False


def _find_engine_project_yaml(root: Path):
    """定位「引擎所属项目」条目的 project.yaml：dirs 覆盖引擎仓根的首个条目
    （按目录名排序取稳定序）。找不到/不可读 → None（调用方走内置缺省兜底）。"""
    try:
        entries = sorted(root.iterdir())
    except OSError:
        return None
    for d in entries:
        y = d / 'project.yaml'
        try:
            if not y.is_file():
                continue
            text = y.read_text(encoding='utf-8', errors='replace')
        except OSError:
            continue
        if _dirs_cover_engine(text):
            return y
    return None


_CONFIG_CACHE: Dict[str, Any] = {'key': None, 'enabled': False,
                                 'keep_days': DEFAULT_KEEP_DAYS,
                                 'max_mb': DEFAULT_MAX_MB}


def reset_config_for_test():
    """测试钩子：清配置缓存与幂等键加速集（生产路径零调用）。"""
    _CONFIG_CACHE.update(key=None, enabled=False, keep_days=DEFAULT_KEEP_DAYS,
                         max_mb=DEFAULT_MAX_MB)
    _SEEN.clear()


def event_ledger_config(projects_root: Optional[Path] = None) -> Dict[str, Any]:
    """event_ledger 配置单点：引擎所属项目 project.yaml 顶层
    `event_ledger: {enabled, keep_days, max_mb}`。缺省=未启用（undeclared ⇒ 零
    行为，验收⑧）+ 14 天 + rolling 512MB。缓存键=(根路径, 根 mtime, yaml mtime)
    ——与 audit 同形状，env 现读、变更可感知、每行只多两次 stat。fail-open：
    注册表缺席/条目未命中/解析失败=内置缺省，绝不阻断事件写。"""
    root = Path(projects_root) if projects_root else _projects_root()
    try:
        key = (str(root), root.stat().st_mtime_ns)
    except OSError:
        key = (str(root), None)
    if _CONFIG_CACHE['key'] == key:
        return _CONFIG_CACHE
    enabled, keep, mb = False, DEFAULT_KEEP_DAYS, DEFAULT_MAX_MB
    y = _find_engine_project_yaml(root)
    if y is not None:
        try:
            key = key + (y.stat().st_mtime_ns,)
        except OSError:
            key = key + (None,)
        try:
            ov = _parse_event_ledger_overrides(
                y.read_text(encoding='utf-8', errors='replace'))
        except OSError:
            ov = {}
        enabled = bool(ov.get('enabled', False))
        keep = ov.get('keep_days', DEFAULT_KEEP_DAYS)
        mb = ov.get('max_mb', DEFAULT_MAX_MB)
    _CONFIG_CACHE.update(key=key, enabled=enabled, keep_days=keep, max_mb=mb)
    return _CONFIG_CACHE


# ---- 写面：announce（保证面）+ gaps（机会面）+ 轮转 + append ----

def _announce(err: Any, project: str, ticket: str) -> None:
    """[R5] 保证面：点名 stderr（模块名+项目+票+异常）+ 计数器。永远可得。"""
    global WRITE_FAILURES
    WRITE_FAILURES += 1
    try:
        sys.stderr.write(
            "event_ledger: 账面写失败（项目=%s 票=%s 次数=%d）：%s: %s\n"
            % (project, ticket, WRITE_FAILURES, type(err).__name__, err))
        sys.stderr.flush()
    except Exception:
        pass    # stderr 也不可得时只剩计数器——仍是可观测面，绝不 raise


def _announce_gap_failure(err: Any, project: str) -> None:
    global GAPS_FAILURES
    GAPS_FAILURES += 1
    try:
        sys.stderr.write(
            "event_ledger: gap 补写也失败（项目=%s 次数=%d）：%s: %s——缺口只剩"
            "计数器/stderr 可见，对账请跑 ledger_rebuild\n"
            % (project, GAPS_FAILURES, type(err).__name__, err))
        sys.stderr.flush()
    except Exception:
        pass


def _write_gap_record(project: str, ticket: str, why: str,
                      ledger_dir: Optional[Path] = None) -> None:
    """[R5] 机会面：向 <project>.gaps.jsonl 补一条 gap 记录。补写失败被吞
    （先点 stderr）——缺口保底可见面=计数器+stderr。"""
    global GAPS_FAILURES
    try:
        d = Path(ledger_dir) if ledger_dir else _ledger_dir()
        d.mkdir(parents=True, exist_ok=True)
        line = json.dumps({"gap": True, "v": SCHEMA_V, "project": project,
                           "ticket": ticket, "at": time.strftime(
                               '%Y-%m-%dT%H:%M:%S', time.localtime()),
                           "why": str(why)[:REASON_LIMIT]},
                          ensure_ascii=False, separators=(',', ':'))
        with open(d / (project + GAPS_SUFFIX), 'a', encoding='utf-8') as f:
            f.write(line + '\n')
    except Exception as e:      # noqa: BLE001——机会面失败吞掉（保底=announce）
        _announce_gap_failure(e, project)


def _day_key(ts=None):
    return time.strftime('%Y%m%d', time.localtime(time.time() if ts is None else ts))


def _parse_archive_day(name: str, base: str):
    """归档名 → 当日 day-key（借镜 audit 命名面：<base>.<YYYYMMDD>[-<HHMMSS>[-hex]]）；
    命名面外 → None（清扫面跳过）。"""
    if not name.startswith(base + '.'):
        return None
    suf = name[len(base) + 1:]
    m = _ARCH_SUFFIX_RE.match(suf)
    return m.group(1) if m else None


def _maybe_rotate(path: Path, cfg: Dict[str, Any]) -> None:
    """rolling：活动文件 ≥ max_mb → rename 到 <name>.<YYYYMMDD>-<HHMMSS>-<hex6>
    （纯命名面；O_APPEND 语义下对并发写者安全）。≤0=关。重名碰撞补 hex 重试
    三次，仍撞=本轮放弃轮转（下轮再试，事件照写不丢）。"""
    mb = int(cfg.get('max_mb') or 0)
    if mb <= 0:
        return
    try:
        st = path.stat()
    except OSError:
        return      # 活动文件还不存在：无需轮转
    if st.st_size < mb * 1024 * 1024:
        return
    stamp = time.strftime('%Y%m%d-%H%M%S')
    for _ in range(3):
        dst = path.with_name('%s.%s-%s' % (path.name, stamp, os.urandom(3).hex()))
        if not dst.exists():
            try:
                os.rename(path, dst)
            except OSError:
                pass    # 轮转失败不阻断事件写（下轮再试）
            return
    # 三次全撞（概率≈0）：放弃本轮轮转，活动文件继续追加。


def _sweep(project: str, cfg: Dict[str, Any], ledger_dir: Optional[Path] = None) -> None:
    """保留窗清扫：只删 <today - keep_days> 的归档；活动文件与 gaps 永不碰。
    keep_days ≤0=永不删。归档日解析不出=命名面外，跳过。"""
    keep = int(cfg.get('keep_days') or 0)
    if keep <= 0:
        return
    d = Path(ledger_dir) if ledger_dir else _ledger_dir()
    base = '%s.jsonl' % project
    cutoff = _day_key()
    try:
        names = os.listdir(d)
    except OSError:
        return
    today = time.strftime('%Y%m%d', time.localtime())
    for name in names:
        day = _parse_archive_day(name, base)
        if day is None or day >= today:
            continue
        try:
            import datetime as _dt
            age = (_dt.datetime.strptime(today, '%Y%m%d')
                   - _dt.datetime.strptime(day, '%Y%m%d')).days
        except ValueError:
            continue
        if age > keep:
            try:
                (d / name).unlink()
            except OSError:
                pass    # 删不掉留给下轮清扫，不阻断事件写


def _ensure_trailing_newline(path: Path) -> None:
    """活动文件存在且末字节非换行（撕裂尾行）⇒ 先补一个换行再追加：撕裂行保持
    自身一条（清扫/去重扫描面已按「跳过+计数」处理），新行绝不与它粘连成一条
    坏行。补换行失败（只读等）由外层 fail-open 面统一承接。"""
    try:
        if path.stat().st_size == 0:
            return
        with open(path, 'rb') as f:
            f.seek(-1, os.SEEK_END)
            if f.read(1) == b'\n':
                return
        fd = os.open(path, os.O_WRONLY | os.O_APPEND)
        try:
            os.write(fd, b'\n')
        finally:
            os.close(fd)
    except Exception:               # noqa: BLE001——外层 append 的 fail-open 面兜底
        pass


def _file_keys(path: Path) -> set:
    """扫活动文件收幂等键（[R4] 冷路径权威面）。撕裂行（末行无换行/JSON 坏）
    跳过并计数——绝不致命，也绝不用于压制写入。"""
    seen: set = set()
    try:
        with open(path, 'r', encoding='utf-8', errors='replace') as f:
            for raw in f:
                line = raw.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except ValueError:
                    global WRITE_FAILURES
                    # 撕裂/坏行计数但不中断（保证面口径，写失败计数复用同一可见面）
                    WRITE_FAILURES += 1
                    continue
                if isinstance(obj, dict) and obj.get('idem'):
                    seen.add(str(obj['idem']))
    except FileNotFoundError:
        pass
    except OSError as e:
        _announce(e, path.stem, '*')
    return seen


def _seen_for(path: Path):
    entry = _SEEN.get(str(path))
    if entry is None:
        entry = (set(), [])
        _SEEN[str(path)] = entry
    return entry


def build_line(payload: Dict[str, Any]) -> bytes:
    """payload → 单行字节（<4KB；reason 先截断）。畸形 payload（非 dict/缺键/
    非串字段）在此归一/兜缺省，绝不 raise——外部输入面（[R1] 畸形必回落）。"""
    ev = payload if isinstance(payload, dict) else {}
    reason = ev.get('reason')
    if not isinstance(reason, str):
        reason = '' if reason is None else str(reason)
    if len(reason) > REASON_LIMIT:
        reason = reason[:REASON_LIMIT] + REASON_TRUNC_MARK

    def _s(k):
        v = ev.get(k)
        return str(v) if v is not None else ""

    def _n(k):
        try:
            return int(ev.get(k) or 0)
        except (TypeError, ValueError):
            return 0

    line = json.dumps({
        'v': SCHEMA_V,
        'project': _s('project'),
        'scope': _s('scope') or 'project',
        'ticket': _s('ticket'),
        'workflow': _s('workflow'),
        'template': _s('template'),
        'stage': _s('stage'),
        'state': _s('state'),
        'reason': reason,
        'gen': _n('gen'),
        'ts': _s('ts'),
        'seq': _n('seq'),
        'run_id': _s('run_id'),
        'idem': _s('idem'),
        'engine': _n('engine') or ENGINE_VERSION_V2,
    }, ensure_ascii=False, separators=(',', ':'))
    data = (line + '\n').encode('utf-8')
    if len(data) >= LINE_LIMIT:     # 极端超限：reason 再砍到行达标（点名截断已在前）
        room = LINE_LIMIT - (len(data) - len(reason.encode('utf-8'))) - 1
        if room < 0:
            room = 0
        data = (line[:len(line) - len(reason)] + reason[:room]
                + REASON_TRUNC_MARK + '\n').encode('utf-8')
    return data


def append_event(payload: Dict[str, Any], ledger_dir: Optional[Path] = None,
                 skip_enabled_gate: bool = False) -> Dict[str, Any]:
    """账面写单事件（活动体与 rebuild 补写共用的单点）：去重 → 轮转 → 清扫 →
    O_APPEND 单次写。返回回执，永不 raise。"""
    ev = payload if isinstance(payload, dict) else {}
    project = str(ev.get('project') or '')
    ticket = str(ev.get('ticket') or '')
    cfg = event_ledger_config()
    if not skip_enabled_gate and not cfg.get('enabled'):
        return {'emitted': False, 'why': 'event_ledger 未声明或未启用（零行为）'}
    path = ledger_path(project, ledger_dir)
    idem = str(ev.get('idem') or '')
    if idem:
        keys, order = _seen_for(path)
        if idem not in keys:
            # [R4] 冷路径权威面：加速集未命中 → 扫活动文件定夺
            if idem in _file_keys(path):
                keys.add(idem)
                order.append(idem)
                _trim(path)
                return {'emitted': False, 'dedup': True, 'path': str(path)}
            keys.add(idem)
            order.append(idem)
            _trim(path)
        else:
            return {'emitted': False, 'dedup': True, 'path': str(path)}
    data = build_line(ev)
    try:
        d = path.parent
        d.mkdir(parents=True, exist_ok=True)
        _maybe_rotate(path, cfg)
        _ensure_trailing_newline(path)  # 撕裂尾行（无换行）不与新行粘连
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
        try:
            os.write(fd, data)      # 单次 write：O_APPEND 下行原子
        finally:
            os.close(fd)
        _sweep(project, cfg, ledger_dir)
        return {'emitted': True, 'path': str(path), 'bytes': len(data)}
    except Exception as e:      # noqa: BLE001——fail-open：绝不向 workflow 抛
        _announce(e, project, ticket)
        _write_gap_record(project, ticket, '%s: %s' % (type(e).__name__, e),
                          ledger_dir)
        return {'emitted': False, 'failed': True,
                'error': '%s: %s' % (type(e).__name__, e)}


def _trim(path: Path) -> None:
    """加速集 FIFO 逐出（纯加速器：逐出只可能多一次扫盘，不会错压制）。"""
    keys, order = _seen_for(path)
    while len(order) > IDEM_SET_CAP:
        old = order.pop(0)
        keys.discard(old)


@activity.defn
async def append_event_ledger(payload: Dict[str, Any]) -> Dict[str, Any]:
    """账面写活动（workflow-body 禁 IO 的 IO 承载面）。at-least-once 重投由
    idem 去重兜住；内部一切失败 fail-open（[R5]），回执如实点 emitted/failed，
    永不 raise。"""
    try:
        return append_event(payload)
    except Exception as e:      # noqa: BLE001——双保险（append_event 已不抛）
        _announce(e, str((payload or {}).get('project') or '?'),
                  str((payload or {}).get('ticket') or '?'))
        return {'emitted': False, 'failed': True,
                'error': '%s: %s' % (type(e).__name__, e)}


# ---- rebuild：账本=时间线的派生投影（验收⑥） ----

def _expected_line(entry: Dict[str, Any], seq: int, run: str, project: str,
                   ticket: str, workflow_class: str,
                   template_id: str) -> Dict[str, Any]:
    """单条期望事件（字段与运行时 enqueue 同源同形状）。"""
    return {
        'v': SCHEMA_V,
        'project': project,
        'scope': 'project',
        'ticket': ticket,
        'workflow': workflow_class,
        'template': template_id,
        'stage': str(entry.get('stage') or ''),
        'state': str(entry.get('state') or ''),
        'reason': str(entry.get('reason') or ''),
        'gen': int(entry.get('gen') or 0),
        'ts': str(entry.get('at') or ''),
        'seq': int(seq),
        'run_id': str(run),
        'idem': '%s|%s|%s|%d' % (project, ticket, run, int(seq)),
        'engine': ENGINE_VERSION_V2,
    }


def expected_lines(timeline: List[Dict[str, Any]], project: str,
                   ticket: str, workflow_class: str = '',
                   template_id: str = '',
                   marks: Optional[List[Dict[str, Any]]] = None
                   ) -> List[Dict[str, Any]]:
    """重生成期望事件。迁移定位两轨（[R-merge] gen2）：
    - marks 轨（现役）：op=ledger_rebuild 传 snapshot 的 ledger_marks
      （[{i: timeline 下标, seq, run}]）；timeline 条目本身零标记（票面形状
      逐字不变，t260915-01 四键锁/未声明零变化承诺）。
    - 兼容轨（marks 缺省）：扫条目内嵌 ledger_seq/ledger_run 标记（gen0/gen1
      期间落账的在途票快照仍可重建；探针/旧快照同径）。"""
    out: List[Dict[str, Any]] = []
    if marks:
        for m in marks:
            try:
                entry = timeline[int(m.get('i'))]
            except (IndexError, TypeError, ValueError):
                continue
            if not isinstance(entry, dict):
                continue
            seq, run = int(m.get('seq') or 0), str(m.get('run') or '')
            if seq <= 0 or not run:
                continue
            out.append(_expected_line(entry, seq, run, project, ticket,
                                      workflow_class, template_id))
        return out
    for entry in timeline or []:
        if not isinstance(entry, dict):
            continue
        seq = entry.get('ledger_seq')
        run = entry.get('ledger_run')
        if seq is None or not run:
            continue
        out.append(_expected_line(entry, int(seq), str(run), project, ticket,
                                  workflow_class, template_id))
    return out


def ledger_rebuild(project: str, ticket: str, timeline: List[Dict[str, Any]],
                   workflow_class: str = '', template_id: str = '',
                   ledger_dir: Optional[Path] = None,
                   marks: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    """重建单票账面行（op=ledger_rebuild 的核心，纯引擎本地 IO）：期望行 ×
    活动文件比对 → 只补缺失 idem 的行（同一 O_APPEND 单点，去重语义不变）。
    marks=snapshot 的 ledger_marks（现役轨）；缺省走条目内嵌标记兼容轨。
    返回 {expected, present, missing_added, duplicate_idem}——重复 idem 行计数
    上报（多进程 TOCTOU 已知伪影），绝不重复修复。"""
    expected = expected_lines(timeline, project, ticket, workflow_class,
                              template_id, marks=marks)
    path = ledger_path(project, ledger_dir)
    present_keys = _file_keys(path)
    duplicate_idem = 0
    missing: List[Dict[str, Any]] = []
    for ev in expected:
        if ev['idem'] in present_keys:
            duplicate_idem += 1
        else:
            missing.append(ev)
    added = 0
    healed_by_concurrent = 0
    for ev in missing:
        res = append_event(ev, ledger_dir, skip_enabled_gate=True)
        if res.get('emitted'):
            added += 1
            present_keys.add(ev['idem'])
        elif res.get('failed'):
            # 补写失败已走 announce/gaps 保证面；继续补剩余行（尽力面）
            continue
        elif res.get('dedup'):
            # 并发面另一写者刚落了同一行：视为 present，不再计 missing
            healed_by_concurrent += 1
            present_keys.add(ev['idem'])
    return {'project': project, 'ticket': ticket,
            'expected': len(expected),
            'present': len(expected) - len(missing) + added + healed_by_concurrent,
            'missing_added': added, 'duplicate_idem': duplicate_idem,
            'path': str(path)}
