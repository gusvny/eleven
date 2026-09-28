#!/usr/bin/env python3
"""ledger_live_check.py — 真票落地核对：一次迁移 = 恰一行台账（验收① 的活体判据）。

为什么单独成器：t260928-13 的验收①「真票跑一遍，每次段状态迁移落恰一行」**无法在票内自证**
——账面缺省关闭、开关在机器级 `~/.sandbar/projects/<key>/project.yaml`（任何写集之外），
且代码要合并后才到 worker。本条把它做成**可重复的单命令判据**：任何一张真票收口（或跑动中）
都能当场核对，缺口即红。

用法（必须用引擎 venv 的 python）：
    server/engine/.venv/bin/python -B integration/t260928-13/ledger_live_check.py <ticket_id>
    ... --project sandbar        # 快照里 meta.project 不可得时显式给
    ... --json                   # 机器可读回执
    ... --selftest               # 用合成夹具自证判据本身（好/缺行/多行/字段不符/缺口/收口少行）

只读：查 snapshot（Temporal query/result）+ 读台账文件，不写任何东西、不发信号。
退出码：0=全绿；1=有红（缺口/多余行/字段不符）；2=ENV（连不上 Temporal / 缺 temporalio /
快照无 ledger_marks=worker 是旧代码）；`--selftest` 全绿退 0。
判定依据=**公开面**：snapshot.timeline × snapshot.ledger_marks（增量键）与台账行的关系，
不锚定实现内部（不假设写入时机、不假设 flush 次数）——契约不变的实现重构不该把它弄红。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / 'server/engine'))

PASS = 0
FAIL = 0


def ok(cond, label, detail=''):
    global PASS, FAIL
    if cond:
        PASS += 1
        if not QUIET[0]:
            print('  ✓ %s' % label)
    else:
        FAIL += 1
        if not QUIET[0]:
            print('  ✗ %s%s' % (label, ('　—— %s' % detail) if detail else ''))
    return bool(cond)


QUIET = [False]


def _snapshot(ticket_id):
    """只读取快照（回执形状 = client._ok{'result': {...}}；COMPLETED 走 result()）。"""
    import asyncio
    import client as engine_client
    res = asyncio.run(engine_client.cmd_ticket_query({'ticket_id': ticket_id}))
    if not isinstance(res, dict) or not res.get('ok'):
        return None, '', str((res or {}).get('error') or res)
    payload = res.get('result') or {}
    snap = payload.get('snapshot')
    if not isinstance(snap, dict):
        return None, '', 'snapshot 形态异常：%s（exec_status=%s）' % (
            type(snap).__name__, payload.get('exec_status'))
    return snap, str(payload.get('exec_status') or ''), ''


def _ledger_lines(ledger_dir, project):
    import event_ledger as el
    f = el.ledger_path(project, ledger_dir)
    if not f.exists():
        return f, []
    out = []
    for raw in f.read_text(encoding='utf-8', errors='replace').splitlines():
        if not raw.strip():
            continue
        try:
            obj = json.loads(raw)
        except ValueError:
            continue        # 撕裂行：读取面跳过（与模块扫描面同口径）
        if isinstance(obj, dict):
            out.append(obj)
    return f, out


def _mark_key(project, ticket_id, mark):
    return '%s|%s|%s|%s' % (project, ticket_id, mark.get('run'), mark.get('seq'))


def _reason_matches(got, want):
    """账本 reason 与票面 reason 的判据（含声明的截断规则）。

    event_ledger.build_line：reason 长度 > REASON_LIMIT 时截断并追加 REASON_TRUNC_MARK。
    故合法形态有二：逐字相等；或「账本 == 票面前 REASON_LIMIT 字 + 标记」。
    REASON_LIMIT 现读模块常量（缺失则回落 1200，与本仓声明一致）。"""
    import event_ledger as el
    limit = int(getattr(el, 'REASON_LIMIT', 1200))
    mark = str(getattr(el, 'REASON_TRUNC_MARK', '…(截断,原文不落盘)'))
    g, w = str(got or ''), str(want or '')
    if g == w:
        return True
    return w.startswith(g[:-len(mark)]) and g.endswith(mark) if len(g) > len(mark) else False


def evaluate(snap, project, ticket_id, ledger_dir):
    """判据核心（与取数解耦，供 --selftest 复用）：返回回执 dict。"""
    global PASS, FAIL
    PASS = FAIL = 0
    meta = snap.get('meta') or {}
    timeline = snap.get('timeline') or []
    marks = snap.get('ledger_marks') or []
    f, all_lines = _ledger_lines(ledger_dir, project)
    mine = [x for x in all_lines if str(x.get('ticket') or '') == str(ticket_id)]

    # ① 开关真的生效了（机器级声明 → 真落盘）
    ok(f.exists(), '台账文件在盘（%s）' % f.name,
       '账本关闭/声明未生效——查 project.yaml 的 event_ledger 与「引擎所属项目」归属')
    ok(len(mine) > 0, '本票有台账行（enabled 声明生效）',
       '一行都没有=门或声明错了（立即排查）')

    # ② 一次迁移恰一行：mark ↔ line 双射（idem 为键）
    #
    # 在飞票的「pending 尾巴」不是缺口：flush 只发生在固定边界（长等待/人门/主循环顶/收口），
    # 所以任意时刻最新几个 mark 可能还在 workflow 内存里没投出。判据按 seq 序区分两种缺：
    #   · 缺失键的 seq 全在「已落盘最大 seq」之后 ⇒ pending 尾巴（在飞票=data 未到，不作红；
    #     收口票=终态仍缺 ⇒ 红，因为收口前必有一次 flush）
    #   · 任一缺失键的 seq ≤ 已落盘最大 seq ⇒ 真缺口（跳过中间转移）⇒ 红
    valid = [m for m in marks if isinstance(m.get('i'), int) and 0 <= m['i'] < len(timeline)]
    mark_keys = [_mark_key(project, ticket_id, m) for m in valid]
    line_keys = [str(x.get('idem') or '') for x in mine]
    closed = (str(meta.get('status') or '') == 'closed'
              and str(meta.get('stage_state') or '') == 'awaiting')
    done_seqs = [x.get('seq') for x in mine if isinstance(x.get('seq'), int)]
    max_done = max(done_seqs) if done_seqs else 0
    missing = [m for m in valid if _mark_key(project, ticket_id, m) not in line_keys]
    tail = [m for m in missing if isinstance(m.get('seq'), int) and m['seq'] > max_done]
    real = [m for m in missing if m not in tail]
    if real:
        ok(False, '每次迁移都有对应行（真缺口 %d）' % len(real),
           '缺：%s' % [_mark_key(project, ticket_id, m) for m in real[:3]])
    elif tail and not closed:
        print('  · 每次迁移都有对应行（在飞票：%d 条 pending 尾巴未冲，不作缺口——收口前必冲）'
              % len(tail))
    else:
        ok(not missing, '每次迁移都有对应行（缺 %d%s）'
           % (len(missing), '，收口票不允许缺' if closed else ''),
           '缺：%s' % [_mark_key(project, ticket_id, m) for m in missing[:3]])
    extra = [k for k in line_keys if k not in mark_keys]
    ok(not extra, '无多余行（多 %d）' % len(extra), '多：%s' % extra[:3])
    dups = sorted({k for k in line_keys if line_keys.count(k) > 1})
    ok(not dups, '无重复 idem', '重复：%s' % dups[:3])

    # ③ 逐条字段与票面迁移一致（公开面：timeline 条目 vs 台账行）
    bad = []
    for m in valid:
        key = _mark_key(project, ticket_id, m)
        rows = [x for x in mine if str(x.get('idem') or '') == key]
        if len(rows) != 1:
            continue
        row, t = rows[0], timeline[m['i']]
        for field, want in (('stage', t.get('stage')), ('state', t.get('state')),
                            ('reason', t.get('reason')), ('gen', t.get('gen')),
                            ('run_id', m.get('run')), ('project', project),
                            ('seq', m.get('seq'))):
            got = row.get(field)
            if field == 'reason':
                # 票面 reason 可能超长；账本是**派生面**，按声明的截断规则落盘
                # （REASON_LIMIT + REASON_TRUNC_MARK，见 event_ledger.build_line）。
                # 判据=「未超限逐字相等」或「超限时账面 == 票面前缀+截断标记」，
                # 绝不把有意的截断当字段不符（真票 t260928-20 实测踩出的假红）。
                if _reason_matches(got, want):
                    continue
                bad.append('%s#%s reason: 账面 %r 与票面不符（票面长度 %s）'
                           % (ticket_id, m.get('seq'), str(got)[:60],
                              len(str(want or ''))))
                continue
            if isinstance(want, int) and not isinstance(got, int):
                try:
                    got = int(got)
                except (TypeError, ValueError):
                    pass
            if str(got) != str(want):
                bad.append('%s#%s %s: 账面 %r ≠ 票面 %r'
                           % (ticket_id, m.get('seq'), field, got, want))
    ok(not bad, '逐行字段与票面一致（%d 条迁移）' % len(valid), '；'.join(bad[:3]))

    # ④ 无静默缺口：本票不得出现在 gaps 记录里
    hits = []
    for g in sorted(ledger_dir.glob('*.gaps.jsonl')):
        try:
            if any(ticket_id in raw for raw in
                   g.read_text(encoding='utf-8', errors='replace').splitlines()):
                hits.append(g.name)
        except OSError:
            continue
    ok(not hits, '本票无 gap 记录（投递无静默失败）', '命中：%s' % sorted(set(hits)))

    # ⑤ 收口口径：closed 的正常完单，账面行数应等于迁移数
    if str(meta.get('status') or '') == 'closed' and str(meta.get('stage_state') or '') == 'awaiting':
        ok(len(mine) == len(valid), '收口票：账面行数 == 迁移标记数（%d vs %d）'
           % (len(mine), len(valid)))

    return {'ticket': ticket_id, 'project': project, 'ledger': str(f),
            'lines': len(mine), 'marks': len(marks), 'pass': PASS, 'fail': FAIL}


def _selftest():
    """判据自证：合成夹具下该红的必须红、该绿的必须绿（否则本器等于装饰）。"""
    import event_ledger as el
    fails = 0
    with tempfile.TemporaryDirectory() as td:
        ldir = Path(td) / 'ledger'
        ldir.mkdir()
        proj, tid, run = 'demo', 't-1', 'run-A'
        timeline = [
            {'stage': 'plan', 'state': 'running', 'reason': '起', 'gen': 1, 'at': 'ts1'},
            {'stage': 'plan', 'state': 'done', 'reason': '完', 'gen': 1, 'at': 'ts2'},
            {'stage': 'implement', 'state': 'running', 'reason': '做', 'gen': 2, 'at': 'ts3'},
        ]
        marks = [{'i': i, 'seq': i + 1, 'run': run} for i in range(3)]

        def _clip(reason):
            """按 event_ledger 的声明规则截断（判据器必须消费同一规则，不是另立一个）。"""
            limit = int(getattr(el, 'REASON_LIMIT', 1200))
            mark = str(getattr(el, 'REASON_TRUNC_MARK', '…(截断,原文不落盘)'))
            return reason if len(reason) <= limit else reason[:limit] + mark

        def line(i, **over):
            row = {'v': 'event-ledger-v1', 'project': proj, 'scope': 'project',
                   'ticket': tid, 'workflow': 'DevLaneWorkflow', 'template': 'dev-lane',
                   'stage': timeline[i]['stage'], 'state': timeline[i]['state'],
                   'reason': timeline[i]['reason'], 'gen': timeline[i]['gen'],
                   'ts': timeline[i]['at'], 'seq': i + 1, 'run_id': run,
                   'idem': '%s|%s|%s|%d' % (proj, tid, run, i + 1), 'engine': 3}
            row.update(over)
            row['reason'] = _clip(str(row.get('reason') or ''))
            return row

        def snap(status='running', state='running', tl=None, mk=None):
            return {'meta': {'project': proj, 'status': status, 'stage_state': state},
                    'timeline': timeline if tl is None else tl,
                    'ledger_marks': marks if mk is None else mk}

        def seed(rows):
            """每次评估前重铺盘面（盘面是共享的单一文件，必须按案重铺——否则每个案
            看到的都是最后一案的状态，自证就变成装饰）。"""
            el.ledger_path(proj, ldir).write_text(
                '\n'.join(json.dumps(r) if isinstance(r, dict) else r for r in rows) + '\n',
                encoding='utf-8')

        gap_path = ldir / ('%s.gaps.jsonl' % proj)

        def no_gap():
            if gap_path.exists():
                gap_path.unlink()

        def with_gap():
            gap_path.write_text(json.dumps({'ticket': tid, 'reason': '写失败'}) + '\n',
                                encoding='utf-8')

        def no_file():
            p = el.ledger_path(proj, ldir)
            if p.exists():
                p.unlink()

        # (标签, 铺盘面, 快照, 期望是否有红)
        cases = [
            ('好（恰一行×3）', lambda: seed([line(0), line(1), line(2)]), snap(), 0),
            # 在飞票的 pending 尾巴：最新 mark 还没冲（seq 3 未落盘）⇒ 不作红
            ('在飞票 pending 尾巴', lambda: seed([line(0), line(1)]), snap(), 0),
            # 但同一形态在收口票上就是缺口（收口前必有 flush）
            ('收口票同形态=缺口', lambda: seed([line(0), line(1)]),
             snap(status='closed', state='awaiting'), 1),
            # 中间跳一条（非尾巴）= 真缺口，即便在飞票也红
            ('在飞票中间真缺口', lambda: seed([line(0), line(2)]), snap(), 1),
            ('缺一行', lambda: seed([line(0), line(2)]), snap(status='closed', state='awaiting'), 1),
            ('多余一行', lambda: seed([line(0), line(1), line(2),
                                       line(2, idem='%s|%s|%s|99' % (proj, tid, run), seq=99)]),
             snap(), 1),
            ('重复 idem', lambda: seed([line(0), line(1), line(1), line(2)]), snap(), 1),
            ('字段不符', lambda: seed([line(0, state='blocked'), line(1), line(2)]), snap(), 1),
            ('收口票少行', lambda: seed([line(0), line(1)]),
             snap(status='closed', state='awaiting'), 1),
            ('gap 记录在盘', lambda: (seed([line(0), line(1), line(2)]), with_gap()), snap(), 1),
            # 超长 reason：账本按声明规则截断（前缀+标记）不是字段不符；截断后与票面
            # 对不上的才红（260928 真票 t260928-20 实测踩出的假红）
            ('超长 reason 按声明截断', lambda: seed([line(0, reason='X' * 4000), line(1), line(2)]),
             snap(tl=[{'stage': 'plan', 'state': 'running', 'reason': 'X' * 4000, 'gen': 1, 'at': 'ts1'},
                      timeline[1], timeline[2]]), 0),
            ('截断件与票面对不上', lambda: seed([line(0, reason='Y' * 4000), line(1), line(2)]),
             snap(tl=[{'stage': 'plan', 'state': 'running', 'reason': 'X' * 4000, 'gen': 1, 'at': 'ts1'},
                      timeline[1], timeline[2]]), 1),
            ('一行都没有', no_file, snap(), 1),
        ]

        for label, setup, s, want_fail in cases:
            no_gap()
            setup()
            QUIET[0] = True
            r = evaluate(s, proj, tid, ldir)
            QUIET[0] = False
            got_fail = r['fail']
            if (got_fail > 0) == (want_fail > 0):
                print('  ✓ 自证：%s ⇒ %s' % (label, '红' if want_fail else '绿'))
            else:
                print('  ✗ 自证失败：%s ⇒ 期望%s，实得 fail=%d'
                      % (label, '红' if want_fail else '绿', got_fail))
                fails += 1
    return fails


def main():
    ap = argparse.ArgumentParser(add_help=True)
    ap.add_argument('ticket_id', nargs='?')
    ap.add_argument('--project', default='')
    ap.add_argument('--json', action='store_true')
    ap.add_argument('--selftest', action='store_true')
    args = ap.parse_args()

    try:
        import event_ledger as el
    except Exception as exc:                                    # noqa: BLE001
        print('ENV_FAIL: 引擎依赖不可导入（请用 server/engine/.venv/bin/python 跑）：%r' % (exc,))
        return 2

    if args.selftest:
        QUIET[0] = False
        fails = _selftest()
        print('\nSELFTEST_FAIL=%d' % fails)
        return 1 if fails else 0

    if not args.ticket_id:
        print('用法：ledger_live_check.py <ticket_id> [--project P] [--json] [--selftest]')
        return 2

    snap, exec_status, err = _snapshot(args.ticket_id)
    if snap is None:
        print('ENV_FAIL: snapshot 不可得：%s' % err)
        return 2

    meta = snap.get('meta') or {}
    project = str(args.project or meta.get('project') or '')
    ledger_dir = el._ledger_dir()                                # env 现读（测试可钉）
    print('票 %s　项目 %s　状态 %s/%s　exec=%s' % (
        args.ticket_id, project or '(未声明)',
        meta.get('status'), meta.get('stage_state'), exec_status or '?'))
    print('账面目录 %s' % ledger_dir)

    if 'ledger_marks' not in snap:
        print('ENV_FAIL: 快照无 ledger_marks 键——worker 跑的是旧代码（先确认 worker 版本）')
        return 2
    if not project:
        print('ENV_FAIL: 项目不可得（快照无 meta.project）——用 --project 显式给')
        return 2

    r = evaluate(snap, project, args.ticket_id, ledger_dir)
    print('\nLEDGER_LIVE_PASS=%d LEDGER_LIVE_FAIL=%d' % (r['pass'], r['fail']))
    if args.json:
        print(json.dumps(r, ensure_ascii=False))
    return 1 if r['fail'] else 0


if __name__ == '__main__':
    code = 3
    try:
        code = main()
    except Exception as exc:                                    # noqa: BLE001
        print('ENV_FAIL: 探针自身异常：%r' % (exc,))
        code = 2
    sys.stdout.flush()
    os._exit(code)      # 跳过 temporalio Rust 核心的 teardown（client.py 同款规避）
