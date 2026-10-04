# -*- coding: utf-8 -*-
"""executor_actions（工单 t261004-11，epic project-executor 后续片）：每项目一条
执行器受闸写动作账，append-only JSONL，一行一次「闸真实裁决」的写尝试。

落盘位置：`<projects_root>/<project>/ledger/executor-actions.jsonl`
（projects_root=SANDBAR_PROJECTS_DIR || ~/.sandbar/projects，与 event_ledger
同源；测试平铺缝 SANDBAR_EXECUTOR_ACTIONS_DIR ⇒ `<dir>/<project>.jsonl`）。
面板 Recent-actions 只读这一个文件——机器级 admin.log 读取在本票退役
（27/25000 行带键、512KB 窗 4.5 分钟、邻居淹没、行形漂移打碎读方，见票面）。

写入点：client._executor_grant_gate（执行器授权闸唯一漏斗，三处调用源共用）。
行边界（方案 gen1 C3 裁决）：只记「闸真实裁决」——enforced 放行 + 一切拒收
（元权限反锁/面外 op/声明缺席畸形/未授予）；豁免通道放行（enforced=false，
judge_core 声明读取前即返回）**不落行**——票面定义「一行一次 gated write
attempt"; a write the gate never set is not a gated write. The in-row channel is
therefore always arg/env/cwd/declared-session (the is_executor_channel truth set;
declared-session = the t261004-31 declared-executor-session seam, a new
caller_gate.resolve_identity channel).

启用闸（方案 gen1 C2 裁决）：**无条件落账**——票面口径「引擎记录每一次受闸
写」，无 per-project opt-in。event_ledger_config() 只取 keep_days/max_mb 作
轮转/保留策略；其 enabled 键在本模块被显式忽略，不存在零行为路径。未声明
保留策略的项目走内置缺省（14 天 / 512MB），照常轮转——面板空态文案
「记录启动以来本项目无执行器动作」对未声明项目依然为真。

行字段（schema v1，方案 gen1 C4 裁决）：
  allowed 行恰含 {v, at, op, ticket, grant, grant_source, session, channel,
  decision, idem}（reason 键省略）；refused 行恰为上述集合 + reason（短人话，
  超限截断）。stage 预留不落（v1 无闸点携带 stage）。行内不装原始参数、不装
  回执、不快照整份声明（宿主裁决）。

借用面=event_ledger 的机制（方案 gen1 C1 十二行借用故障表，carried/dropped/
adapted 逐条在案）：轮转 rename（_maybe_rotate 原样复用，并发 O_APPEND 安全）、
撕裂尾行补换行、配置 fail-open 缺省、幂等键加速集+扫盘冷路径、多进程 TOCTOU
重复 idem=已声明良性伪影、空项目键拒收（announce 不落畸形文件）、append 失败
fail-open 且 LOUD（stderr 点名 + WRITE_FAILURES 计数 + gaps 补写，gaps 再失败
再点名后吞掉——绝不静默）、单次 O_APPEND 行原子、4KB 行上限 reason 先截断。
enable 门被 drop（C2）；无 rebuild 面（本账是独立 append 流，非时间线投影）。

idem=sha1(key|op|ticket|session|channel|decision|reason 前缀)+10 分钟 UTC 桶：
重试（分钟级重跑同一 client 命令）同桶去重成一行；同 op 数小时后的真实再次
执行落新桶=新行。已知局限：跨桶边界的重试会留两行（与 event_ledger TOCTOU
同信任档的良性伪影；读方对重复 idem 不报错，只计数 deduped_rows）。
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, Optional

import executor_grants
from ledger_retention import _maybe_rotate, sweep_archives

SCHEMA_V = 1
BASENAME = 'executor-actions.jsonl'
GAPS_BASENAME = 'executor-actions.gaps.jsonl'
LINE_LIMIT = 4096           # 单行硬上限（字节），与审计账同纪律
REASON_LIMIT = 500          # reason 第一道截断（其余字段行内余量充足）
REASON_TRUNC_MARK = "…(truncated)"
IDEM_BUCKET_MS = 10 * 60 * 1000   # idem 时间桶（10 分钟 UTC）
IDEM_SET_CAP = 4096         # 每路径幂等键加速集容量（FIFO 逐出；纯加速器）
DEFAULT_KEEP_DAYS = 14      # 保留窗内置缺省（与 event_ledger 内置缺省同值；见 _retention_cfg）
DEFAULT_MAX_MB = 512        # rolling 阈值内置缺省（同上）

WRITE_FAILURES = 0          # 保证面计数器（写失败/坏行扫描共用可见面，event_ledger 同名先例）

_CFG_FALLBACK_ANNOUNCED = False   # temporalio-free 进程的一次性点名（见 _retention_cfg）


def _retention_cfg() -> Dict[str, Any]:
    """保留策略配置单点（t261004-11 仲裁轮）：策略本体=「event ledger 自己的规则」
    ——keep_days/max_mb 来自 event_ledger.event_ledger_config()。该模块因活动装饰器
    模块级依赖 temporalio，而本模块被 client.py（temporalio-free 轻导入纪律）引入，
    故此处【调用点懒加载】：import 失败（无 temporalio.activity 的解释器/桩）⇒
    回落内置缺省（14 天 / 512MB，与 event_ledger 内置缺省同值）并一次性 stderr
    点名（绝不静默）。轮转/清扫本体在 ledger_retention（stdlib-only 单一真源），
    本回退只影响配置读面，不改变追加/去重/响亮面行为。"""
    global _CFG_FALLBACK_ANNOUNCED
    try:
        from event_ledger import event_ledger_config
        return event_ledger_config()
    except ImportError as e:
        if not _CFG_FALLBACK_ANNOUNCED:
            _CFG_FALLBACK_ANNOUNCED = True
            _announce(e, '*', 'event_ledger_config unavailable (temporalio-free '
                              'interpreter); retention falls back to built-in defaults')
        return {'enabled': False, 'keep_days': DEFAULT_KEEP_DAYS, 'max_mb': DEFAULT_MAX_MB}

# 每路径幂等键加速集：path → (set(keys), deque-like list order)。纯加速：
# 逐出只可能多一次扫盘，绝不会错压制。
_SEEN: Dict[str, tuple] = {}


def reset_for_test() -> None:
    """测试钩子：清幂等加速集（生产路径零调用）。"""
    _SEEN.clear()


def _announce(err: Any, project: str, why: str) -> None:
    """保证面：stderr 点名（绝不静默；不 raise——记账永不动写结局）。"""
    try:
        sys.stderr.write(
            "executor-actions: record failed for project %s: %s (%s)\n"
            % (project or '?', why, type(err).__name__))
        sys.stderr.flush()
    except Exception:       # noqa: BLE001——stderr 都没时只剩计数（仍不 raise）
        pass


def _projects_root() -> Path:
    """注册表根（与 event_ledger._projects_root 同口径的本地镜像，避免私有跨模块耦合）。"""
    return Path(os.environ.get('SANDBAR_PROJECTS_DIR')
                or (Path.home() / '.sandbar' / 'projects'))


def actions_path(project: str, actions_dir: Optional[Path] = None) -> Path:
    """账本文件路径（与面板 recent-actions.executorActionsFile 逐字同式，跨语言
    漂移由两侧 tests 双向钉死）：
    - env SANDBAR_EXECUTOR_ACTIONS_FILE ⇒ 直连文件路径（最高优先；场景/壳缝）；
    - 显式 actions_dir / env SANDBAR_EXECUTOR_ACTIONS_DIR ⇒ 平铺 `<dir>/<project>.jsonl`（测试缝）；
    - 都缺席（生产缺省）⇒ `<projects_root>/<project>/ledger/executor-actions.jsonl`。"""
    direct = os.environ.get('SANDBAR_EXECUTOR_ACTIONS_FILE')
    if direct:
        return Path(direct)
    env = os.environ.get('SANDBAR_EXECUTOR_ACTIONS_DIR')
    d = Path(actions_dir) if actions_dir is not None else (Path(env) if env else None)
    if d is None:
        d = _projects_root() / project / 'ledger'
    return d / ('%s.jsonl' % project) if env or actions_dir is not None \
        else d / BASENAME


def gaps_path(path: Path) -> Path:
    """gaps 旁账路径（status face）：账本文件同目录固定名，平铺/缺省两形状同名。"""
    return path.parent / GAPS_BASENAME


def idem_key(project: str, op: str, ticket: str, session: str, channel: str,
             decision: str, reason: str, at_ms: int) -> str:
    """幂等键：稳定字段摘要 + 10 分钟 UTC 桶（方案已声明桶界伪影）。"""
    bucket = int(max(0, int(at_ms)) // IDEM_BUCKET_MS)
    basis = '|'.join([str(project or ''), str(op or ''), str(ticket or ''),
                      str(session or ''), str(channel or ''), str(decision or ''),
                      str(reason or '')[:120], str(bucket)])
    return hashlib.sha1(basis.encode('utf-8')).hexdigest()[:16]


def build_line(row: Dict[str, Any]) -> bytes:
    """行 → 单行字节（<4KB；reason 先截断再极端二砍）。畸形字段归一，绝不 raise。"""
    r = row if isinstance(row, dict) else {}
    reason = r.get('reason')
    reason = '' if reason is None else (reason if isinstance(reason, str) else str(reason))
    if len(reason) > REASON_LIMIT:
        reason = reason[:REASON_LIMIT] + REASON_TRUNC_MARK
    out: Dict[str, Any] = {
        'v': SCHEMA_V,
        'at': int(r.get('at') or 0),
        'op': str(r.get('op') or ''),
        'ticket': str(r.get('ticket') or ''),
        'grant': str(r.get('grant') or ''),
        'grant_source': str(r.get('grant_source') or ''),
        'session': str(r.get('session') or ''),
        'channel': str(r.get('channel') or ''),
        'decision': str(r.get('decision') or ''),
        'idem': str(r.get('idem') or ''),
    }
    if str(r.get('decision') or '') == 'refused':
        out['reason'] = reason       # C4：reason 键只在 refused 行在场
    line = json.dumps(out, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
    data = (line + '\n').encode('utf-8')
    if len(data) >= LINE_LIMIT:      # 极端超限：reason 二砍到行达标
        room = LINE_LIMIT - (len(data) - len(reason.encode('utf-8'))) - 1
        if room < 0:
            room = 0
        data = (line[:len(line) - len(reason)] + reason[:room]
                + REASON_TRUNC_MARK + '\n').encode('utf-8')
    return data


def _ensure_trailing_newline(path: Path) -> None:
    """撕裂尾行（末字节非换行）先补换行再追加——坏行保自身一条，新行绝不粘连。
    补失败由外层 fail-open 面承接（event_ledger 同名先例逐字口径）。"""
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
    """扫活动文件收幂等键（冷进程权威面）。撕裂/坏行跳过并计数（写失败计数
    复用同一可见面），绝不致命、绝不用于压制写入。"""
    global WRITE_FAILURES
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
                    WRITE_FAILURES += 1
                    continue
                if isinstance(obj, dict) and obj.get('idem'):
                    seen.add(str(obj['idem']))
    except FileNotFoundError:
        pass
    except OSError as e:
        _announce(e, path.parent.name, 'scan %s failed' % path.name)
    return seen


def _seen_for(path: Path):
    entry = _SEEN.get(str(path))
    if entry is None:
        entry = (set(), [])
        _SEEN[str(path)] = entry
    return entry


def _trim(path: Path) -> None:
    """加速集 FIFO 逐出（纯加速器：逐出只多一次扫盘）。"""
    entry = _SEEN.get(str(path))
    if entry is None:
        return
    keys, order = entry
    while len(order) > IDEM_SET_CAP:
        old = order.pop(0)
        keys.discard(old)


def _write_gap_record(path: Path, project: str, why: str) -> None:
    """机会面：gaps 旁账补一条 {"gap": true, ...}（append 失败时的状态面）。
    补写再失败=再点一次 stderr 后吞掉——绝无静默成功（event_ledger R5 口径）。"""
    global WRITE_FAILURES
    gp = gaps_path(path)
    row = {'gap': True, 'at': int(time.time() * 1000), 'project': str(project or ''),
           'why': str(why or '')[:500]}
    try:
        gp.parent.mkdir(parents=True, exist_ok=True)
        with open(gp, 'a', encoding='utf-8') as f:
            f.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + '\n')
    except Exception as e:      # noqa: BLE001
        WRITE_FAILURES += 1
        _announce(e, project, 'gap record failed at %s' % gp)


def record_executor_action(project: str, op: str, ticket: str = "",
                           grant: str = "", grant_source: str = "",
                           session: str = "", channel: str = "",
                           decision: str = "", reason: str = "",
                           now_ms: Optional[int] = None,
                           actions_dir: Optional[Path] = None) -> Dict[str, Any]:
    """落一行执行器动作账（真 IO 包装；从不 raise、从不反向影响写结局）。

    去重 → 轮转 → 补换行 → O_APPEND 单次写 → 清扫（与 event_ledger.append_event
    同序）。返回回执：{"appended": bool, "deduped"?: True, "failed"?: True, ...}。"""
    global WRITE_FAILURES
    key = str(project or '').strip()
    if not key:
        # 空项目键=拒收不落盘（防畸形 `<root>//ledger/...` 文件；announce 保证面）
        WRITE_FAILURES += 1
        _announce(RuntimeError('empty project key'), project or '?',
                  'project-scope row has empty project key (rejected)')
        return {'appended': False, 'failed': True,
                'why': 'empty project key (rejected)'}
    dec = str(decision or '').strip()
    if dec not in ('allowed', 'refused'):
        # 判定字段畸形=不猜：announce 后拒收（内部产源本不该发生，防线双落）
        WRITE_FAILURES += 1
        _announce(RuntimeError('bad decision %r' % decision), key,
                  'decision must be allowed|refused (rejected)')
        return {'appended': False, 'failed': True,
                'why': 'decision must be allowed|refused (rejected)'}
    ms = int(now_ms if now_ms is not None else time.time() * 1000)
    rs = reason if isinstance(reason, str) else ('' if reason is None else str(reason))
    if dec == 'refused' and not rs.strip():
        rs = '(no reason given)'     # refused 行 reason 必须在场（票面 schema）
        _announce(RuntimeError('refused row without reason'), key,
                  'refused row arrived with an empty reason (placeholder written)')
    path = actions_path(key, actions_dir)
    idem = idem_key(key, op, ticket, session, channel, dec, rs, ms)
    keys, order = _seen_for(path)
    if idem in keys:
        return {'appended': False, 'deduped': True, 'path': str(path)}
    if idem in _file_keys(path):
        keys.add(idem)
        order.append(idem)
        _trim(path)
        return {'appended': False, 'deduped': True, 'path': str(path)}
    keys.add(idem)
    order.append(idem)
    _trim(path)
    row = {'v': SCHEMA_V, 'at': ms, 'op': str(op or ''), 'ticket': str(ticket or ''),
           'grant': str(grant or ''), 'grant_source': str(grant_source or ''),
           'session': str(session or ''), 'channel': str(channel or ''),
           'decision': dec, 'idem': idem}
    if dec == 'refused':
        row['reason'] = rs
    data = build_line(row)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        cfg = _retention_cfg()
        _maybe_rotate(path, cfg)
        _ensure_trailing_newline(path)   # 撕裂尾行不与新行粘连
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
        try:
            os.write(fd, data)           # 单次 write：O_APPEND 下行原子
        finally:
            os.close(fd)
        sweep_archives(cfg, path)
        return {'appended': True, 'path': str(path), 'bytes': len(data)}
    except Exception as e:      # noqa: BLE001——fail-open 且 LOUD：绝不向闸抛
        WRITE_FAILURES += 1
        _announce(e, key, 'append to %s failed' % path)
        try:
            _write_gap_record(path, key, '%s: %s' % (type(e).__name__, e))
        except Exception as e2:  # noqa: BLE001——gaps 再失败：再点名后吞掉（R5）
            WRITE_FAILURES += 1
            _announce(e2, key, 'gap record failed at %s' % gaps_path(path))
        return {'appended': False, 'failed': True,
                'error': '%s: %s' % (type(e).__name__, e)}


def record_from_gate(op: str, key: str, ticket: str, verdict: Dict[str, Any],
                     channel: str, now_ms: Optional[int] = None,
                     session: Optional[str] = None) -> Dict[str, Any]:
    """闸漏斗接线面（client._executor_grant_gate 唯一消费方）：verdict 已在手，
    grant/grant_source 从 provenance 取；session 缺省从声明读口
    （executor_grants.caller_session_id，env DSH_SESSION_ID 族）现读，可注入覆盖。

    行边界（C3）：enforced 放行与一切拒收落行；exempt（enforced 非 True 且未
    拒收）零行零文件行为。"""
    v = verdict if isinstance(verdict, dict) else {}
    sid = executor_grants.caller_session_id() if session is None else str(session)
    if not v.get('allowed'):
        return record_executor_action(
            key, op, ticket=ticket, grant='', grant_source='',
            session=sid,
            channel=str(channel or ''), decision='refused',
            reason=str(v.get('why') or ''), now_ms=now_ms)
    if not v.get('enforced'):
        return {'appended': False, 'exempt': True}
    grant_op = str(v.get('grant_op') or '')
    prov = (v.get('provenance') or {}) if isinstance(v.get('provenance'), dict) else {}
    grant_source = str((prov.get('keys') or {}).get(grant_op) or '')
    return record_executor_action(
        key, op, ticket=ticket, grant=grant_op, grant_source=grant_source,
        session=sid,
        channel=str(channel or ''), decision='allowed', now_ms=now_ms)
