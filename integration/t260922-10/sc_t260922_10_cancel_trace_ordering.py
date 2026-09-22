#!/usr/bin/env python3
"""t260922-10 场景①：记名清场主链——先留痕后终结 + 三方同串（registry: t260922-10-cancel-trace-ordering）。

用户旅程（工单 260922 现场实测）：blocked 残渣票永远推不动，值守走正规入口
`ticket op=cancel`（who+reason 必填）把 terminate 包装成记名操作——终结前 who+reason
先落到票面可见面，终结后在 admin.log 与 workflow 事件历史查到同一 reason 串。

被测链（灰盒，零 docker/零 3099/零真 Temporal）：桩 Temporal handle（记录调用次序）
→ 真 client.py cmd_ticket_cancel → 真 ticket.py op=cancel → 真 tools_registry.call
（真 audit 写 SANDBAR_ADMIN_LOG=tmp，仓库零写入）。

守护的用户可感知合同（工单验收②③+关键设计约束）：
  T1 成功链回执：ok/terminated=true，reason/who 原文回显；
  T2 次序机械可验：cancel_notice 信号先于 terminate，且 terminate 恰一次；
  T3 信号载荷含 who+reason 原文与盖章 caller_project（== 比较，不做模糊匹配）；
  T4 三方同串：signal 载荷 reason == terminate reason == 回执 reason；
  T5 admin.log（隔离 tmp）含同串 reason；回执零「列不出」谎报；
  T6 幂等：已终态票重复 cancel → 结构化「已终态」，零新 signal/terminate；
  T7 终结后 show → kind=terminal 结构化（终态不可查契约，真链面归
     t260915-12-gate-real-chain 已锁的查询分级，此处锁旅程收口形状）；
  T8 terminate 失败（⑥成功⑦失败 race）→ 结构化报错点名「信号已留痕、未终结」，
     重试安全，无第二次 terminate；
  T9 信号失败 → 结构化报错且 terminate 零调用（先留痕失败即不终结）。

分工（防 intent 级重复）：跨项目闸矩阵本身与真链维度归 t260915-12 两场景；
拒收形状细节归本票场景②；本条只锁「记名+次序+同串」主链。
实现落地前 T1-T5/T8/T9 红属预期（TDD 信号），arbitrate/merge 期必须绿。
跑法：PY=server/engine/.venv/bin/python; "$PY" -B integration/t260922-10/sc_t260922_10_cancel_trace_ordering.py（cwd=仓根）
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(HERE))          # integration/ 根（lib_env）
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))  # 仓根

import lib_t26092210 as fx  # noqa: E402
from lib_env import EXIT_FAIL, EXIT_PASS  # noqa: E402

TID = 't26092210-sc1'
WHO = 'integration-agent'
REASON = '工作空间 /var/folders/.../t260910-* 已不存在，retry_qc 复现失败（场景清场）'
LEGS = []


def check(name, cond, detail=''):
    LEGS.append(bool(cond))
    print('[%s] %s%s' % ('PASS' if cond else 'FAIL', name, ('：' + detail) if detail else ''))


def main():
    os.environ.pop('SANDBAR_CALLER_PROJECT', None)
    default_log = fx.tmp_admin_log()
    os.environ['SANDBAR_ADMIN_LOG'] = str(default_log)   # 进程内 audit 全落 tmp（仓库零写入）
    ticket = fx.load_ticket()

    counter = [0]
    ticket._poc = fx.poc_inproc_factory(counter)

    # ---- T1~T5 成功链（同项目 declared 身份）----
    log1 = fx.tmp_admin_log()
    os.environ['SANDBAR_ADMIN_LOG'] = str(log1)
    h = fx.install_handle(fx.FakeHandle(
        status='RUNNING', snapshot={'meta': {'project': 'proj-a'}}))
    try:
        r = fx.ticket_call({'op': 'cancel', 'id': TID, 'who': WHO, 'reason': REASON,
                            'caller_project': 'proj-a'})
        blob = json.dumps(r, ensure_ascii=False)
        res = r.get('result') if isinstance(r.get('result'), dict) else {}
        check('T1 成功链回执 ok:true 且 terminated=true', r.get('ok') is True and res.get('terminated') is True,
              '回执=%s' % blob[:200])
        check('T1 回执回显 reason/who 原文', res.get('reason') == REASON and res.get('who') == WHO)
        check('T2 cancel_notice 信号先于 terminate（先留痕后终结）',
              0 <= h.first_index('signal') < h.first_index('terminate'))
        check('T2 terminate 恰一次（单票终结无重复副作用）', h.count('terminate') == 1,
              'calls=%r' % ([c[0] for c in h.calls],))
        sigs = [c for c in h.calls if c[0] == 'signal']
        sig = sigs[0] if sigs else None
        check('T3 信号名 cancel_notice 且载荷含 who+reason 原文',
              bool(sig) and sig[1] == 'cancel_notice'
              and sig[2].get('who') == WHO and sig[2].get('reason') == REASON,
              'signal=%r' % (sig,))
        check('T3 信号载荷盖章 caller_project 在场（第二道闸解码输入）',
              bool(sig) and bool(str(sig[2].get('caller_project') or '').strip()))
        term = [c for c in h.calls if c[0] == 'terminate']
        check('T4 三方同串：signal.reason == terminate.reason == 回执.reason（== 不模糊）',
              bool(sig) and bool(term) and term[0][1] == REASON and res.get('reason') == REASON)
        log_text = fx.read_log_text(log1)
        check('T5 admin.log（隔离 tmp）含同串 reason', REASON in log_text,
              'log_len=%d' % len(log_text))
        check('T5 回执零「列不出」谎报（不盖章 notice 不许回潮）', '列不出' not in blob)
    finally:
        fx.remove_quiet(log1)

    # ---- T6 幂等（已终态票重复 cancel）----
    h2 = fx.install_handle(fx.FakeHandle(
        status='TERMINATED', snapshot={'meta': {'project': 'proj-a'}}))
    r2 = fx.ticket_call({'op': 'cancel', 'id': TID, 'who': WHO, 'reason': REASON,
                         'caller_project': 'proj-a'})
    blob2 = json.dumps(r2, ensure_ascii=False)
    res2 = r2.get('result') if isinstance(r2.get('result'), dict) else {}
    check('T6 已终态重复 cancel → ok:true 结构化「已终态」非异常',
          r2.get('ok') is True and (res2.get('already_terminal') is True or '已终态' in blob2),
          '回执=%s' % blob2[:200])
    check('T6 幂等零副作用：无新 signal/terminate', h2.count('signal') == 0 and h2.count('terminate') == 0,
          'calls=%r' % ([c[0] for c in h2.calls],))

    # ---- T7 终结后 show：终态不可查结构化面（旅程收口）----
    r3 = fx.ticket_call({'op': 'show', 'id': TID})
    check('T7 终态后 show → ok:false kind=terminal（快照不可得契约）',
          r3.get('ok') is False and r3.get('kind') == 'terminal',
          '回执=%s' % (json.dumps(r3, ensure_ascii=False)[:160],))

    # ---- T8 terminate 失败（信号已留痕未终结）----
    h4 = fx.install_handle(fx.FakeHandle(
        status='RUNNING', snapshot={'meta': {'project': 'proj-a'}},
        terminate_exc=RuntimeError('race: workflow completed'))
    )
    r4 = fx.ticket_call({'op': 'cancel', 'id': TID, 'who': WHO, 'reason': REASON,
                         'caller_project': 'proj-a'})
    e4 = str(r4.get('error') or '')
    check('T8 terminate 失败 → 结构化 ok:false 不抛栈', r4.get('ok') is False and 'Traceback' not in e4)
    check('T8 文案点名「信号已留痕、本次未终结」（重试安全指引）',
          ('留痕' in e4 or '信号' in e4) and ('未终结' in e4 or '未执行终结' in e4),
          'error=%s' % e4[:160])
    check('T8 失败后无重复 terminate（终态回收恰一次）', h4.count('terminate') == 1)

    # ---- T9 信号失败 → 不终结 ----
    h5 = fx.install_handle(fx.FakeHandle(
        status='RUNNING', snapshot={'meta': {'project': 'proj-a'}},
        signal_exc=RuntimeError('signal unreachable'))
    )
    r5 = fx.ticket_call({'op': 'cancel', 'id': TID, 'who': WHO, 'reason': REASON,
                         'caller_project': 'proj-a'})
    check('T9 信号失败 → 结构化 ok:false 且 terminate 零调用（先留痕失败即不终结）',
          r5.get('ok') is False and h5.count('terminate') == 0,
          'calls=%r' % ([c[0] for c in h5.calls],))

    print('== SUMMARY：PASS=%d FAIL=%d ==' % (LEGS.count(True), LEGS.count(False)))
    fx.remove_quiet(default_log)
    return EXIT_PASS if all(LEGS) else EXIT_FAIL


if __name__ == '__main__':
    sys.exit(main())
