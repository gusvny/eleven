#!/usr/bin/env python3
"""t260922-10 记名清场入口场景共享夹具（无 sc_ 前缀=共享代码，不入注册表）。

离线全链桩样式（sc_query_kind_no_lie 同款，零 docker/零 3099/零真 Temporal）：
  桩 Temporal client/handle（复用 t260901-23 的 _stub_temporalio）
    → 真 client.py 命令层（cmd_ticket_cancel：幂等闸/跨项目闸/先信号后终结）
    → 真 ticket.py 包装层（op=cancel 必填 fail-fast/越权旗归一/分发）
    → 真 tools_registry.call（ValueError 结构化并入 + 真 audit 写 SANDBAR_ADMIN_LOG）
审计隔离：SANDBAR_ADMIN_LOG 指向临时文件（audit.py 供测试隔离的 env 缝），
仓库零写入（*.log 本就 gitignore，tmp 双保险）；每场景各自 tmp，互不串写。
"""
import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent

sys.path.insert(0, str(HERE.parent / 't260901-23'))   # 共享夹具 _stub_temporalio
sys.path.insert(0, str(REPO / 'server' / 'engine'))   # 真 client.py
sys.path.insert(0, str(REPO / 'server'))              # 真 tools_registry

import _stub_temporalio  # noqa: E402  必须先于 client 导入装桩
_stub_temporalio.install()

import client as client_mod  # noqa: E402
import tools_registry as registry_mod  # noqa: E402


class _Status:
    def __init__(self, name):
        self.name = name


class _Desc:
    """describe 桩：只需 status 名与 SA 降级安全位（对齐 sc_query_kind_no_lie）。"""

    def __init__(self, status_name):
        self.status = _Status(status_name) if status_name else None
        self.typed_search_attributes = None


class FakeHandle:
    """记录调用次序的 Temporal handle 桩——「先留痕后终结」的机械观测面。

    calls 追加 ('describe'|'query'|'signal'|'terminate', ...) 元组；
    signal 记 (名, 载荷)，terminate 记 reason。
    """

    def __init__(self, status='RUNNING', snapshot=None, describe_exc=None,
                 signal_exc=None, terminate_exc=None):
        self.status_name = status
        self.snapshot = snapshot if snapshot is not None else {}
        self.describe_exc = describe_exc
        self.signal_exc = signal_exc
        self.terminate_exc = terminate_exc
        self.calls = []

    async def describe(self):
        self.calls.append(('describe', self.status_name))
        if self.describe_exc is not None:
            raise self.describe_exc
        return _Desc(self.status_name)

    async def query(self, name, *a, **kw):
        self.calls.append(('query', name))
        return self.snapshot

    async def signal(self, name, payload):
        self.calls.append(('signal', name, dict(payload or {})))
        if self.signal_exc is not None:
            raise self.signal_exc

    async def terminate(self, reason=''):
        self.calls.append(('terminate', reason))
        if self.terminate_exc is not None:
            raise self.terminate_exc

    def first_index(self, kind):
        for i, c in enumerate(self.calls):
            if c[0] == kind:
                return i
        return -1

    def count(self, kind):
        return sum(1 for c in self.calls if c[0] == kind)


class FakeClient:
    def __init__(self, handle):
        self._h = handle

    def get_workflow_handle(self, tid):
        return self._h


def install_handle(handle):
    async def _fake_connect():
        return FakeClient(handle)
    client_mod._connect = _fake_connect
    return handle


def load_ticket():
    """真 ticket 模块 = registry 装载实例；audit 保持真写（env 已指 tmp）。"""
    tools = registry_mod.load_tools()
    return tools['ticket']


def poc_inproc_factory(counter):
    """进程内重放 _poc 子进程跳（JSON dict 进出契约与真 _poc 一致）。

    counter 是 list[int]：每次真实触达 client 层 +1——「拒绝=零副作用」
    的机械观测面（校验层拒收必须在任何 client 动作之前）。
    """

    def _poc_inproc(subcmd, payload, caller=None):
        counter[0] += 1
        payload = dict(payload or {})
        # 保真度关键：真 _poc 把 caller 注入子进程 env（SANDBAR_CALLER_PROJECT）——
        # 进程内重放必须同样注入，否则 client 侧身份推导全部退化成 undeclared。
        old = os.environ.get('SANDBAR_CALLER_PROJECT')
        if caller:
            os.environ['SANDBAR_CALLER_PROJECT'] = str(caller)
        try:
            if subcmd == 'ticket-cancel':
                return asyncio.run(client_mod.cmd_ticket_cancel(payload))
            if subcmd == 'ticket-query':
                return asyncio.run(client_mod.cmd_ticket_query(payload))
            raise ValueError('场景只消费 ticket-cancel/ticket-query，收到 %r' % (subcmd,))
        finally:
            if caller:
                if old is None:
                    os.environ.pop('SANDBAR_CALLER_PROJECT', None)
                else:
                    os.environ['SANDBAR_CALLER_PROJECT'] = old

    return _poc_inproc


def ticket_call(payload):
    """真 registry.call：ticket.py 全链（含 ValueError→{ok:false} 结构化）。

    审计管道（implement 段修正，保留）：registry.call 台账落模块常量
    registry_mod.LOG=server/admin.log，不吃 audit.py 的 env 缝——env 在场即调用期
    重定向到同一 tmp（场景「仓库零写入」契约靠它成立）；env 缺席回落真 LOG。
    """
    log_env = os.environ.get('SANDBAR_ADMIN_LOG')
    old_log = registry_mod.LOG
    if log_env:
        registry_mod.LOG = Path(log_env)
    try:
        return registry_mod.call('ticket', dict(payload))
    finally:
        registry_mod.LOG = old_log


def client_cancel(args):
    """client 面直调（cmd_ticket_cancel 原始回执：身份键/kind 在顶层的 stdout 契约面）。

    真链上这张面=client.py 子进程 stdout 的 JSON（host/值守直读）；ticket.py 包装面
    经 _poc_ok 剥壳只提 result（kind 与身份键留在 client 面）——分级与记名断言锚这里。
    """
    return asyncio.run(client_mod.cmd_ticket_cancel(dict(args)))


def cli_ticket(payload, admin_log):
    """真 ticket.py CLI 子进程（SANDBAR_ADMIN_LOG 隔离）。

    返回 (rc, 末行 JSON dict|None, stdout 全文)。cwd=仓根=身份不推导面。
    """
    import subprocess
    env = dict(os.environ)
    env['SANDBAR_ADMIN_LOG'] = str(admin_log)
    env.pop('SANDBAR_CALLER_PROJECT', None)
    p = subprocess.run(
        [sys.executable, '-B', str(REPO / 'server' / 'tools' / 'ticket.py'),
         json.dumps(payload, ensure_ascii=False)],
        capture_output=True, text=True, timeout=60, cwd=str(REPO), env=env)
    lines = [ln for ln in (p.stdout or '').strip().splitlines() if ln.strip()]
    out = None
    if lines:
        try:
            out = json.loads(lines[-1])
        except json.JSONDecodeError:
            out = None
    return p.returncode, out, (p.stdout or '') + (p.stderr or '')


def tmp_admin_log():
    """独立 tmp 审计日志（env 缝 audit.SANDBAR_ADMIN_LOG，仓库零写入）。"""
    fd, path = tempfile.mkstemp(prefix='t26092210-admin-', suffix='.log')
    os.close(fd)
    return Path(path)


def read_log_text(path):
    try:
        return Path(path).read_text(encoding='utf-8', errors='replace')
    except OSError:
        return ''


def remove_quiet(path):
    try:
        os.unlink(path)
    except OSError:
        pass
