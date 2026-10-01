#!/usr/bin/env python3
"""t260922-10 场景③：说明书=入口、幂等闸口径与边界负锁（registry: t260922-10-cancel-contract-surface）。

用户旅程（KI-079 教训：说明书教了一个不存在的入口=每次操作都掉旁路丢身份）：
值守从工具说明/帮助文本得知 cancel 入口与「残渣票判据」——说明书宣告的必须真实
存在；对未收口形态（CONTINUED_AS_NEW 换代活票）绝不能谎报「已终态」；危险默认
（批量清理）必须不在面上。

被测面（离线，零 docker/零 3099）：真 ticket.py TOOL schema/帮助文本 + 真
client.py COMMANDS/USAGE + cmd_ticket_cancel 闸链（桩 handle）。

守护的用户可感知合同：
  C1 schema op enum 宣告 cancel（additionalProperties:False 下入口可达的必要项）；
  C2 schema 宣告 reason 键（必填语义的机读面；顺带补 authorize 漏宣告=KI-079 族）；
  C3 帮助文本含 cancel + 清场 runbook 判据锚词（'清场'、'retry_qc'）——工具帮助
     文本承载 runbook 是本票交付口径之一，宣告面与入口面必须同在；
  C4 client COMMANDS/USAGE 宣告 ticket-cancel（说明书=入口，client 侧）；
  C5 幂等闸口径：CONTINUED_AS_NEW（未收口换代态）+ 异项目无旗 → kind=
     cross_project_refused，绝不回「已终态」（_EXEC_ALIVE_OK 既有口径；KI-025
     家族红线「不许把活报成终」）；
  C6 边界负锁：无批量清理 op/子命令（只做记名单票终结，危险默认不许上桌面；
     261001：只读审计面 cancel-audit 例外在册，且对它另做「零写动词调用」的机械负锁）；
  C7 裸 cancel 子命令仍在（本票不改裸入口的边界锚）。

分工（防 intent 级重复）：pause/resume 的说明书漂移已由 KI-079 定性、暂无场景锁
（不属本票）；t260915-12-cross-project-gate 锁 schema 的 caller_project/旗/authorize
宣告面，本条只锁 cancel/reason 新宣告。实现落地前红属预期（TDD 信号），
arbitrate/merge 期必须绿。
跑法：PY=server/engine/.venv/bin/python; "$PY" -B integration/t260922-10/sc_t260922_10_cancel_contract_surface.py（cwd=仓根）
"""
import asyncio
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))

import lib_t26092210 as fx  # noqa: E402
from lib_env import EXIT_FAIL, EXIT_PASS  # noqa: E402

LEGS = []


def check(name, cond, detail=''):
    LEGS.append(bool(cond))
    print('[%s] %s%s' % ('PASS' if cond else 'FAIL', name, ('：' + detail) if detail else ''))


def main():
    os.environ.pop('SANDBAR_CALLER_PROJECT', None)
    os.environ['SANDBAR_ADMIN_LOG'] = str(fx.tmp_admin_log())  # audit 落 tmp（仓库零写入）
    ticket = fx.load_ticket()

    schema = getattr(ticket, 'TOOL', None)
    params = ((schema or {}).get('parameters') or {})
    props = params.get('properties') or {}
    enums = ((props.get('op') or {}).get('enum') or [])

    # ---- C1/C2 schema 宣告面 ----
    check('C1 schema op enum 宣告 cancel（入口机读可达）', 'cancel' in enums,
          'enum=%r' % (enums,))
    check('C2 schema 宣告 reason 键（必填语义机读面）', 'reason' in props,
          'properties=%r' % (sorted(props.keys())[:20],))

    # ---- C3 帮助文本承载 runbook 判据（KI-079：说明书=入口）----
    desc = str((schema or {}).get('description') or '')
    doc = str(getattr(ticket, '__doc__', '') or '')
    help_text = desc + '\n' + doc
    check('C3 帮助文本宣告 cancel 入口', 'cancel' in help_text)
    check('C3 帮助文本含清场 runbook 判据锚词（清场 + retry_qc 复现判据）',
          '清场' in help_text and 'retry_qc' in help_text,
          'help_len=%d' % len(help_text))

    # ---- C4 client 侧宣告面 ----
    cmds = getattr(fx.client_mod, 'COMMANDS', None) or {}
    usage = str(getattr(fx.client_mod, 'USAGE', '') or '')
    check('C4 COMMANDS 宣告 ticket-cancel', 'ticket-cancel' in cmds,
          'keys=%r' % (sorted(cmds.keys())[:20],))
    check('C4 USAGE 文本提及 ticket-cancel', 'ticket-cancel' in usage)

    # ---- C5 幂等闸口径：CONTINUED_AS_NEW 不是已终态 ----
    h = fx.install_handle(fx.FakeHandle(
        status='CONTINUED_AS_NEW', snapshot={'meta': {'project': 'proj-a'}}))
    fn = getattr(fx.client_mod, 'cmd_ticket_cancel', None)
    if fn is None:
        check('C5 cmd_ticket_cancel 在场（入口未实现=本组红）', False, 'client 缺 cmd_ticket_cancel')
    else:
        r = asyncio.run(fn({'ticket_id': 't26092210-sc3', 'who': 'integration-agent',
                            'reason': '换代活票不许谎报已终态（场景③）',
                            'caller_project': 'proj-b'}))
        blob = json.dumps(r, ensure_ascii=False)
        check('C5 CONTINUED_AS_NEW 未收口 → 继续走闸（cross_project_refused），绝不回已终态',
              r.get('ok') is False and r.get('kind') == 'cross_project_refused'
              and not r.get('already_terminal'),
              '回执=%s' % blob[:200])
        check('C5 未收口票零终结动作', h.count('signal') == 0 and h.count('terminate') == 0)

    # ---- C6 边界负锁：无批量清理面 ----
    batch_like = [op for op in enums if op != 'cancel' and 'cancel' in str(op)]
    check('C6 schema 无批量清理 op（cancel 族只有单票 cancel）', batch_like == [],
          'cancel 族=%r' % (batch_like,))
    # 261001 口径同步（integration 岗位判词）：260930 批次 B 新增 **只读审计**子命令
    # `cancel-audit`（列近期 TERMINATED 票、逐张读事件历史，核「先留痕后终结」的对账；
    # client.py::cmd_cancel_audit 文档明写「只读：不发信号、不写状态、不推进任何票」，
    # 真源用例 server/engine/tests/test_260930_cancel_audit_and_terminal_face.py B5）。
    # 契约意图——**危险默认（批量/自动清理）不许上桌面**——不变，故负锁改成：
    # ① cancel 族里除单票 cancel/ticket-cancel 外只许登记在册的**只读审计面**；
    # ② 对这个例外做**机械负锁**：其处理函数源码里零写动词调用（`.signal(` / `.terminate(` /
    #    `handle.signal` / `handle.terminate`）——「文档说只读」不算证据，代码里没有写路径才算。
    READ_ONLY_CANCEL_FACES = ('cancel-audit',)
    extra_cmd_cancel_like = [k for k in cmds
                             if 'cancel' in k and k not in ('cancel', 'ticket-cancel')]
    unregistered = [k for k in extra_cmd_cancel_like if k not in READ_ONLY_CANCEL_FACES]
    check('C6 client 无批量/自动清理子命令（只读审计面除外）', unregistered == [],
          'cancel 族=%r（未登记=%r）' % (extra_cmd_cancel_like, unregistered))
    import inspect as _inspect
    for _face in READ_ONLY_CANCEL_FACES:
        _fn = cmds.get(_face)
        try:
            _src = _inspect.getsource(_fn) if _fn else ''
        except (OSError, TypeError):
            _src = ''
        _writes = [w for w in ('.signal(', '.terminate(', 'handle.signal', 'handle.terminate')
                   if w in _src]
        check('C6b 只读审计面 %s 真只读（处理函数零写动词调用）' % _face,
              bool(_src) and _writes == [],
              'src_len=%d writes=%r' % (len(_src), _writes))

    # ---- C7 裸入口原样（边界：不改裸 cancel）----
    check('C7 裸 cancel 子命令仍在（workflow_id 口径原样保留）', 'cancel' in cmds)

    print('== SUMMARY：PASS=%d FAIL=%d ==' % (LEGS.count(True), LEGS.count(False)))
    return EXIT_PASS if all(LEGS) else EXIT_FAIL


if __name__ == '__main__':
    sys.exit(main())
