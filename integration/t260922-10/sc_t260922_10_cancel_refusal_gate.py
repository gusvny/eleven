#!/usr/bin/env python3
"""t260922-10 场景②：拒收面与跨项目闸一致（registry: t260922-10-cancel-refusal-gate）。

用户旅程（工单验收①④+A3.5 同源教训「拒绝=零副作用、被拒也留痕」）：值守清场时
给错参数/越权动别家票，入口必须结构化拒收（不是抛栈不是静默放行），被拒调用进
admin.log，票零改动；undeclared 身份走清场入口必须拿到诚实回执——260922 实测
裸入口的「本 op=cancel 载荷契约不盖章：查询面列不出」缺口在新入口不得回潮。

被测链同场景①（桩 handle→真 client.py→真 ticket.py→真 registry；真 audit 写
SANDBAR_ADMIN_LOG=tmp，仓库零写入；CLI 子用例走真 ticket.py 子进程）。

守护的用户可感知合同（分级/记名断言锚 client stdout 面=host 直读契约；包装面锚
结构化文本与零副作用——ticket.py _poc_ok 剥壳后 kind/身份键留在 client 面）：
  R1-R4 reason 缺/空串/纯空白/非串 → 结构化拒收，校验先于任何 Temporal 动作；
  R5-R6 who/id 缺 → 结构化拒收，同；
  R7 越权旗缺 reason → 包装层 fail-fast 拒收（与既有写 op 同口径）；
  R8 declared 异项目无旗 → kind=cross_project_refused + 回执点名目标票与项目，
     零 signal/terminate（与既有跨项目闸同口径的接线面）；
  R9 带旗 → 放行；信号载荷章=异项目、note=旗理由原文（cross_project_uses 记名
     的输入；查询面列出的 workflow 侧行为归 developer UT，此处锁载体契约）；
  R10 票不存在 → client 面 kind=not_found，零终结动作；
  R11 describe 瞬时 → client 面 kind=transient 拒收不判越权（KI-025 纪律），零终结；
  R12 undeclared 身份（无声明、env 空、仓树 cwd 不推导）→ B 策略放行，client 面
      identity_class=undeclared 如实记名 + 诚实 notice，零「列不出」——260922
      实测缺口主回归；
  R13 CLI 子进程 reason 空 → 退出非零+一行 JSON 结构化（零抛栈），
      admin.log（隔离 tmp）有被拒调用行（被拒也留痕）。

分工（防 intent 级重复）：闸矩阵本体（含裸 cancel 过闸）归 t260915-12 两场景锁；
本条锁新记名入口的拒收形状/零副作用/诚实回执。实现落地前红属预期（TDD 信号），
arbitrate/merge 期必须绿。
跑法：PY=server/engine/.venv/bin/python; "$PY" -B integration/t260922-10/sc_t260922_10_cancel_refusal_gate.py（cwd=仓根）
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))

import lib_t26092210 as fx  # noqa: E402
from lib_env import EXIT_FAIL, EXIT_PASS  # noqa: E402

TID = 't26092210-sc2'
WHO = 'integration-agent'
REASON = '残渣票清场：夹具临时目录已物理不存在（场景②）'
LEGS = []


def check(name, cond, detail=''):
    LEGS.append(bool(cond))
    print('[%s] %s%s' % ('PASS' if cond else 'FAIL', name, ('：' + detail) if detail else ''))


class NotFoundFailure(Exception):
    """与 Temporal NotFoundFailure 同名的本地桩类（client 判别双通路命中，
    sc_query_kind_no_lie 同款）。"""


def structured_reject(tag, payload, want_word, client_touch):
    """R1-R7 共用：结构化拒收 + 零 Temporal 交互 + 文案点名真实原因。

    client_touch=True：参数校验在 client 层连接之前（到达 client 但零 describe/
    signal/terminate）；False：包装层 fail-fast（client 层零触达）。「拒绝=零副作用」
    的机械面两态相同：Temporal 边界零动作。
    """
    counter = [0]
    ticket = fx.load_ticket()
    ticket._poc = fx.poc_inproc_factory(counter)
    h = fx.install_handle(fx.FakeHandle(
        status='RUNNING', snapshot={'meta': {'project': 'proj-a'}}))
    r = fx.ticket_call(payload)
    err = str(r.get('error') or '')
    check('%s 结构化拒收（ok:false 非抛栈）' % tag,
          r.get('ok') is False and 'Traceback' not in err, 'error=%s' % err[:120])
    check('%s 文案点名真实原因（含 %r，零「未知 op」含糊）' % (tag, want_word),
          want_word in err and '未知' not in err, 'error=%s' % err[:160])
    layer_ok = (counter[0] == 1) if client_touch else (counter[0] == 0)
    check('%s 拒绝=零副作用：零 Temporal 交互（校验层触达=%s）' % (tag, 'client 连接前' if client_touch else '包装层'),
          layer_ok and h.calls == [], 'calls=%r' % ([c[0] for c in h.calls],))


def main():
    os.environ.pop('SANDBAR_CALLER_PROJECT', None)
    default_log = fx.tmp_admin_log()
    os.environ['SANDBAR_ADMIN_LOG'] = str(default_log)   # 进程内 audit 全落 tmp（仓库零写入）
    ticket = fx.load_ticket()

    # ---- R1~R6 必填拒收（校验在任何 Temporal 动作之前）----
    structured_reject('R1 reason 缺',
                      {'op': 'cancel', 'id': TID, 'who': WHO, 'caller_project': 'proj-a'}, 'reason', False)
    structured_reject('R2 reason 空串',
                      {'op': 'cancel', 'id': TID, 'who': WHO, 'reason': '', 'caller_project': 'proj-a'}, 'reason', False)
    structured_reject('R3 reason 纯空白',
                      {'op': 'cancel', 'id': TID, 'who': WHO, 'reason': '   ', 'caller_project': 'proj-a'}, 'reason', False)
    structured_reject('R4 reason 非串（归一后空）',
                      {'op': 'cancel', 'id': TID, 'who': WHO, 'reason': ['x'], 'caller_project': 'proj-a'}, 'reason', False)
    structured_reject('R5 who/by 双缺',
                      {'op': 'cancel', 'id': TID, 'reason': REASON, 'caller_project': 'proj-a'}, 'who', False)
    structured_reject('R6 id 缺',
                      {'op': 'cancel', 'who': WHO, 'reason': REASON, 'caller_project': 'proj-a'}, 'id', False)

    # ---- R7 越权旗缺 reason：包装层 fail-fast（client 层零触达）----
    structured_reject('R7 旗缺 reason',
                      {'op': 'cancel', 'id': TID, 'who': WHO, 'reason': REASON,
                       'caller_project': 'proj-b',
                       'cross_project': {'by': 'host'}}, 'reason', False)

    # ---- R8 declared 异项目无旗 → 闸拒收点名、零副作用、被拒留痕 ----
    counter = [0]
    ticket._poc = fx.poc_inproc_factory(counter)
    h8 = fx.install_handle(fx.FakeHandle(
        status='RUNNING', snapshot={'meta': {'project': 'proj-a'}}))
    log8 = fx.tmp_admin_log()
    os.environ['SANDBAR_ADMIN_LOG'] = str(log8)
    try:
        r8 = fx.ticket_call({'op': 'cancel', 'id': TID, 'who': WHO, 'reason': REASON,
                             'caller_project': 'proj-b'})
        e8 = str(r8.get('error') or '')
        check('R8 异项目无旗 → 包装面结构化拒收（ok:false 非抛栈）',
              r8.get('ok') is False, '回执=%s' % json.dumps(r8, ensure_ascii=False)[:200])
        check('R8 拒收回执点名目标票与所属项目', TID in e8 and 'proj-a' in e8, 'error=%s' % e8[:160])
        check('R8 零副作用：零 signal/terminate', h8.count('signal') == 0 and h8.count('terminate') == 0)
        check('R8 被拒调用进 admin.log（隔离 tmp 台账行含 op=cancel 与点名目标）',
              'cancel' in fx.read_log_text(log8) and TID in fx.read_log_text(log8),
              'log_len=%d' % len(fx.read_log_text(log8)))
    finally:
        fx.remove_quiet(log8)
    # R8b client 面：kind=cross_project_refused（KI-025 分级契约在 client stdout 面）
    h8b = fx.install_handle(fx.FakeHandle(
        status='RUNNING', snapshot={'meta': {'project': 'proj-a'}}))
    rc8 = fx.client_cancel({'ticket_id': TID, 'who': WHO, 'reason': REASON,
                            'caller_project': 'proj-b'})
    check('R8b client 面 kind=cross_project_refused（404/503/410 分流判据面）',
          rc8.get('ok') is False and rc8.get('kind') == 'cross_project_refused',
          '回执=%s' % json.dumps(rc8, ensure_ascii=False)[:200])
    check('R8b 零终结动作', h8b.count('signal') == 0 and h8b.count('terminate') == 0)

    # ---- R9 带旗 → 放行 + 载体契约 ----
    counter2 = [0]
    ticket._poc = fx.poc_inproc_factory(counter2)
    h9 = fx.install_handle(fx.FakeHandle(
        status='RUNNING', snapshot={'meta': {'project': 'proj-a'}}))
    r9 = fx.ticket_call({'op': 'cancel', 'id': TID, 'who': WHO, 'reason': REASON,
                         'caller_project': 'proj-b',
                         'cross_project': {'by': 'host', 'reason': '宿主令 260922 清场裁决'}})
    sigs = [c for c in h9.calls if c[0] == 'signal']
    sig = sigs[0] if sigs else None
    res9 = r9.get('result') if isinstance(r9.get('result'), dict) else {}
    check('R9 带旗放行：ok:true 且 terminated=true', r9.get('ok') is True and res9.get('terminated') is True,
          '回执=%s' % json.dumps(r9, ensure_ascii=False)[:200])
    check('R9 信号载荷章=异项目 proj-b、note=旗理由原文（记名输入）',
          bool(sig) and sig[2].get('caller_project') == 'proj-b'
          and sig[2].get('cross_project_note') == '宿主令 260922 清场裁决',
          'signal=%r' % (sig,))
    check('R9 主 reason 仍为终结同串（旗理由≠清场理由，两处各自入账）',
          bool(sig) and sig[2].get('reason') == REASON
          and [c for c in h9.calls if c[0] == 'terminate'][0][1] == REASON)

    # ---- R10 not_found（client 面 kind=分级契约锚；包装面=结构化文本）----
    h10 = fx.install_handle(fx.FakeHandle(
        status='RUNNING', snapshot={'meta': {'project': 'proj-a'}},
        describe_exc=NotFoundFailure('workflow not found')))
    rc10 = fx.client_cancel({'ticket_id': 't-not-exist', 'who': WHO,
                             'reason': REASON, 'caller_project': 'proj-a'})
    check('R10 client 面 kind=not_found（存在性谎报红线面）', rc10.get('ok') is False
          and rc10.get('kind') == 'not_found', '回执=%s' % json.dumps(rc10, ensure_ascii=False)[:160])
    check('R10 零终结动作', h10.count('signal') == 0 and h10.count('terminate') == 0)

    # ---- R11 describe 瞬时 → transient 不判越权、零终结（KI-025 纪律）----
    import asyncio
    h11 = fx.install_handle(fx.FakeHandle(
        status='RUNNING', snapshot={'meta': {'project': 'proj-a'}},
        describe_exc=asyncio.TimeoutError('describe timeout')))
    rc11 = fx.client_cancel({'ticket_id': TID, 'who': WHO, 'reason': REASON,
                             'caller_project': 'proj-b'})
    check('R11 client 面 kind=transient（瞬时绝不判越权/绝不终结）',
          rc11.get('ok') is False and rc11.get('kind') == 'transient'
          and h11.count('signal') == 0 and h11.count('terminate') == 0,
          '回执=%s' % json.dumps(rc11, ensure_ascii=False)[:160])

    # ---- R12 undeclared 主案（260922 实测缺口回归；client 面=身份键与诚实回执契约）----
    h12 = fx.install_handle(fx.FakeHandle(
        status='RUNNING', snapshot={'meta': {'project': 'proj-a'}}))
    rc12 = fx.client_cancel({'ticket_id': TID, 'who': WHO, 'reason': REASON})
    blob12 = json.dumps(rc12, ensure_ascii=False)
    res12 = rc12.get('result') if isinstance(rc12.get('result'), dict) else {}
    check('R12 undeclared 身份 → B 策略放行清场', rc12.get('ok') is True and res12.get('terminated') is True,
          '回执=%s' % blob12[:200])
    check('R12 回执 identity_class=undeclared 如实记名（身份键在 client 面顶层）',
          rc12.get('identity_class') == 'undeclared', '键=%r' % (rc12.get('identity_class'),))
    check('R12 回执零「列不出」谎报 + 诚实 notice 在场（新入口真盖章/真记名）',
          '列不出' not in blob12 and '记名放行' in str(rc12.get('cross_project_notice') or ''))

    # ---- R13 CLI 子进程：reason 空 → 退出非零+一行 JSON+被拒留痕 ----
    log13 = fx.tmp_admin_log()
    try:
        rc, out, full = fx.cli_ticket({'op': 'cancel', 'id': TID, 'who': WHO}, log13)
        check('R13 CLI reason 空 → 退出非零、一行 JSON 结构化（零抛栈零静默放行）',
              rc != 0 and isinstance(out, dict) and out.get('ok') is False
              and 'Traceback' not in full, 'rc=%r out=%r' % (rc, out))
        check('R13 CLI 文案点名 reason（必填语义）',
              isinstance(out, dict) and 'reason' in str(out.get('error') or ''), 'out=%r' % (out,))
        check('R13 被拒调用进 admin.log（隔离 tmp 有 cancel 行=被拒也留痕）',
              'cancel' in fx.read_log_text(log13))
    finally:
        fx.remove_quiet(log13)
    fx.remove_quiet(default_log)

    print('== SUMMARY：PASS=%d FAIL=%d ==' % (LEGS.count(True), LEGS.count(False)))
    return EXIT_PASS if all(LEGS) else EXIT_FAIL


if __name__ == '__main__':
    sys.exit(main())
