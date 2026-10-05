#!/usr/bin/env python3
"""t260903-06 场景：查询谎报面全链回归（KI-025 事故回归，integration L3）。

用户旅程（t260903-02/04/05 实案）：值守在阶段切换窗打开工单详情，Temporal 抖动
（worker 写历史 + SQLite 单写者占用）→ 台面/CLI 报「工单不存在」，值守险些走数据
抢救误路径；CLI describe 同刻证实 workflow 活着。

被测链（灰盒：只打 Temporal 边界桩，其余全真）：
  桩 Temporal client/handle（复用 t260901-23 的 _stub_temporalio 共享夹具）
    → 真 client.py 命令层（分级 + 退避，产出 kind）
    → 真 ticket.py（_poc 子进程跳在进程内按同契约重放：JSON dict 进出、不判 ok）
    → 真 tools_registry.call（duck-type 并入 kind = review C1 断链修复面）
断言只落在用户可感知回执（ok / error / kind / 文案不变量），不锚内部结构。

守护的用户可感知合同：
  A. 瞬时故障（超时/连接失败）→ kind=transient，文案含「刷新重试」指引，
     绝不含「工单不存在」——谎报面消灭（KI-025）；真链上重试发生过
     （精确次数与退避序列归 t01 单元层，此处不重复锚定）。
  B. 「工单不存在」只能由 NotFoundFailure 语义产出（kind=not_found 存活到
     registry 回执——404 的唯一合法来源）。
  C. 终态票（TERMINATED 等）→ kind=terminal，文案明说终态/永久，绝不提示
     「瞬时/刷新重试」（反向谎报守卫：死票不得诱导无限重试），也不谎报不存在。
  D. 畸形快照（非 dict）→ kind=internal，文案说清形态检查失败，
     不谎报不存在、不谎报瞬时（确定性缺陷非抖动）。
  E. 上游回执缺 kind（畸形/旧形态）→ 回执绝不产出 not_found 语义。
  F. 空 ticket_id（分级表未列出口的兜底）→ 不产不存在语义（gen1 条件 2）。
  G. 非 QueryError 异常不并 kind（duck-type 识别面零误并反例，gen1 条件 3）。

跑法：python3 -B integration/t260903-06/sc_query_kind_no_lie.py
（纯 stdlib，零模型调用；Temporal 边界打桩，不碰 3099/网络/真 Temporal；
audit 桩收口，仓库零写入。）
"""
import asyncio
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
sys.path.insert(0, str(HERE.parent / 't260901-23'))            # 共享夹具 _stub_temporalio
sys.path.insert(0, str(REPO / 'server' / 'engine'))  # 真 client.py
sys.path.insert(0, str(REPO / 'server'))                        # 真 tools_registry

import _stub_temporalio  # noqa: E402
_stub_temporalio.install()

import client as client_mod  # noqa: E402  # 桩环境下的真 client.py 命令层
import tools_registry as registry_mod  # noqa: E402


class NotFoundFailure(Exception):
    """与 Temporal NotFoundFailure 同名的本地桩类：client 判别走 import/isinstance
    或类名兜底双通路均命中（方案 v2 承诺）。"""


class _Status:
    def __init__(self, name):
        self.name = name


class _Desc:
    def __init__(self, status_name):
        self.status = _Status(status_name) if status_name else None
        self.typed_search_attributes = None  # epic 回填分支 try/except 安全降级


class FakeHandle:
    def __init__(self, status_name, query_fn=None, describe_exc=None):
        self._status = status_name
        self._query_fn = query_fn
        self._describe_exc = describe_exc
        self.queries = 0
        self.run_id = 'stub-run'
        self.result_run_id = 'stub-run'

    async def describe(self):
        if self._describe_exc is not None:
            raise self._describe_exc
        return _Desc(self._status)

    async def query(self, name):
        self.queries += 1
        if self._query_fn is not None:
            return self._query_fn(name)
        return None

    async def result(self):
        raise AssertionError('场景未预期走 result() 路径')


class FakeClient:
    def __init__(self, handle):
        self._h = handle

    def get_workflow_handle(self, tid):
        return self._h


def _install_handle(handle):
    async def _fake_connect():
        return FakeClient(handle)
    client_mod._connect = _fake_connect
    return handle


PASS = 0
FAIL = 0


def ok(cond, msg):
    global PASS, FAIL
    if cond:
        PASS += 1
        print('  ok  %s' % msg)
    else:
        FAIL += 1
        print('FAIL  %s' % msg)


def main():
    # 真 ticket 模块 = registry 装载实例（load_tools 带缓存，call() 用同一实例）；
    # audit 桩收口：场景对仓库零写入（ro 语义）。
    tools = registry_mod.load_tools()
    ticket_mod = tools['ticket']
    registry_mod.audit = lambda rec: None

    def _poc_inproc(subcmd, payload):
        # 进程内重放 _poc 子进程跳：JSON dict 进出契约与真 _poc 一致（不判 ok）。
        if subcmd == 'ticket-query':
            return asyncio.run(client_mod.cmd_ticket_query(dict(payload or {})))
        raise ValueError('场景只消费 ticket-query，收到 %r' % (subcmd,))

    ticket_mod._poc = _poc_inproc
    TID = 't-stub-06'

    def show(tid=TID):
        return registry_mod.call('ticket', {'op': 'show', 'id': tid})

    # ---- A 瞬时故障（RUNNING snapshot 三连超时）----
    def _q_timeout(name):
        raise asyncio.TimeoutError('snapshot query timeout (stub)')

    h = _install_handle(FakeHandle('RUNNING', query_fn=_q_timeout))
    res = show()
    err_txt = str(res.get('error') or '')
    ok(res.get('ok') is False, 'A 瞬时故障回执 ok:false')
    ok(res.get('kind') == 'transient',
       'A kind=transient 跨层存活到 registry 回执（review C1 断链守卫）')
    ok('工单不存在' not in err_txt, 'A 瞬时文案零「工单不存在」（KI-025 谎报面消灭）')
    ok('刷新重试' in err_txt, 'A 文案给用户可行动指引（刷新重试）')
    ok(h.queries >= 2, 'A 真链上重试发生过（queries=%d；精确序列归 t01 单元层）' % h.queries)

    # ---- B 真·不存在（describe 抛 NotFoundFailure 语义）----
    h = _install_handle(FakeHandle(None, describe_exc=NotFoundFailure('workflow not found (stub)')))
    res = show()
    err_txt = str(res.get('error') or '')
    ok(res.get('kind') == 'not_found', 'B 不存在 → kind=not_found 存活到回执（404 唯一合法来源）')
    ok('工单不存在' in err_txt, 'B 不存在语义只在 NotFound 路径出现')

    # ---- C 终态票（TERMINATED）----
    h = _install_handle(FakeHandle('TERMINATED'))
    res = show()
    err_txt = str(res.get('error') or '')
    ok(res.get('kind') == 'terminal', 'C 终态 → kind=terminal（独立分级）')
    ok('terminal' in err_txt, 'C 文案明说终态（永久，快照不可得）')
    ok('transient' not in err_txt, 'C 终态绝不提示瞬时（反向谎报守卫）')
    ok('retry' not in err_txt, 'C 终态绝不诱导重试（死票不得无限重试）')
    ok('does not exist' not in err_txt, 'C 终态不谎报不存在')

    # ---- D 畸形快照（query 返回非 dict）----
    h = _install_handle(FakeHandle('RUNNING', query_fn=lambda name: ['not', 'a', 'dict']))
    res = show()
    err_txt = str(res.get('error') or '')
    ok(res.get('kind') == 'internal', 'D 畸形快照 → kind=internal')
    ok('工单不存在' not in err_txt, 'D 畸形不谎报不存在')
    ok('瞬时' not in err_txt, 'D 畸形不谎报瞬时（确定性缺陷非抖动）')
    ok('形态' in err_txt or 'dict' in err_txt, 'D 文案说清哪个检查失败（形态异常）')

    # ---- E 上游回执缺 kind（畸形/旧形态 client 回执）----
    def _poc_legacy(subcmd, payload):
        return {'ok': False, 'error': 'workflow 不存在或不可达：Stub: legacy'}

    ticket_mod._poc = _poc_legacy
    res = show()
    ok(res.get('ok') is False, 'E 上游无 kind 回执 ok:false')
    ok(res.get('kind') != 'not_found', 'E 上游缺 kind → 绝不产出 not_found 语义')

    # ---- F 空 ticket_id（未列出口兜底）----
    ticket_mod._poc = _poc_inproc
    res = show(tid='')
    err_txt = str(res.get('error') or '')
    ok(res.get('ok') is False, 'F 空 id 回执 ok:false')
    ok(res.get('kind') != 'not_found', 'F 空 id 兜底不产不存在语义')
    ok('工单不存在' not in err_txt, 'F 空 id 文案零「工单不存在」')

    # ---- G 非 QueryError 异常不带 kind（duck-type 识别面反例，gen1 条件 3）----
    real_load_tools = registry_mod.load_tools

    class _PlainFailTool:
        def run(self, args):
            raise ValueError('plain boom')

    registry_mod.load_tools = lambda: {'plain': _PlainFailTool()}
    res = registry_mod.call('plain', {})
    registry_mod.load_tools = real_load_tools
    ok(res.get('ok') is False, 'G 普通异常回执 ok:false')
    ok('kind' not in res, 'G 普通异常不并 kind（识别面零误并，只有分级异常才带 kind）')

    print('sc_query_kind_no_lie: pass=%d fail=%d' % (PASS, FAIL))
    return 0 if FAIL == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
