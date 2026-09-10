#!/usr/bin/env python3
"""无差别自审计 + entry_hint 单一真源（KI-067，t260910-06）。

背景（260910 两实证）：唯一审计点在 server 层 tools_registry.call()，client.py
进程自身不进账——裸调用（含被拒收调用）admin.log 零痕迹，回执也不提示正规入口。
本模块把两件事收成单一真源：

  1. audit_call()：client.py main() 每个出口（含 -h/无参/未知子命令/argsJSON
     非法/连接失败兜底）与 ticket.py 直 spawn 路径，各记一行 JSONL 到
     server/admin.log（与 tools_registry 同文件；行形状：<4KB，POSIX O_APPEND
     原子）。**连被拒收的调用也记**（拒收不记录=盲区仍在，KI-067 钦点）。
  2. attach_entry_hint()：非正规入口的回执（**含成功回执**——260910 的错发生
     在成功回执里）附 entry_hint 指路 server/tools/ticket.py。

自报家门标记（普通 env，非密钥、非安全语义——宿主 260910 拍板）：
  - env SANDBAR_CLIENT_ENTRY 精确等值 'ticket'（ticket.py _poc 注入）→ 回执
    安静（不附 hint）。
  - **其余任意值一律按 bare 待遇**（回执附 hint）；静默待遇与 source 原文解耦。
  - admin.log 的 source 记 env 原值（≤32 字符截断，缺省字面量 'bare'）——保留
    自称原文便于排查伪造/误配。
  - 口径声明：source 是 **claimed-source 而非系统判定身份**（env 由调用方自带，
    泳道 agent 理论上可自称 'ticket'）。宿主已裁非安全语义，本模块只保证
    「静默待遇仅由代码路径注入的精确值触发」这一合同，不做身份鉴别
    （身份=调用方凭证闸，宿主明确不做，多实例架构未定）。

仅依赖 stdlib（与 shared.py 同独立性），engine 与 tools 两侧共用，双份必漂移
（KI-032 教训）。审计写失败 → stderr 留痕但**不吞回执**（回执是主契约；降级
显式声明于此，非静默）。
"""
import json
import os
import sys
import time
import uuid
from pathlib import Path

# 自报家门 env 名（普通 env，非密钥）；'ticket' 是唯一获静默待遇的精确值。
ENTRY_ENV = 'SANDBAR_CLIENT_ENTRY'
ENTRY_MARK = 'ticket'
# ticket.py → client.py 的调用关联键 env（一次直调 = admin.log 两行同 call_id）。
CALL_ID_ENV = 'SANDBAR_CLIENT_CALL_ID'
# admin.log 路径（server/admin.log；env SANDBAR_ADMIN_LOG 覆盖，供测试隔离）。
ADMIN_LOG = Path(__file__).resolve().parent.parent / 'admin.log'
ENTRY_HINT = '此为裸入口，请走 server/tools/ticket.py'


def _log_path():
    return Path(os.environ.get('SANDBAR_ADMIN_LOG') or ADMIN_LOG)


def claimed_source():
    """claimed-source：env 原值（≤32 字符截断），缺省 'bare'。非身份鉴别（见模块头）。"""
    raw = os.environ.get(ENTRY_ENV, '')
    if not raw:
        return 'bare'
    return raw[:32]


def is_ticket_entry():
    """静默待遇判定：精确等值才认（'ticket.py'/'1'/空串/带空白一律不认）。"""
    return os.environ.get(ENTRY_ENV) == ENTRY_MARK


def attach_entry_hint(receipt):
    """非正规入口回执附 entry_hint（含成功回执）；已是 'ticket' 或非 dict 则原样返回。"""
    if isinstance(receipt, dict) and not is_ticket_entry() and 'entry_hint' not in receipt:
        receipt['entry_hint'] = ENTRY_HINT
    return receipt


def audit_call(sub, receipt, call_id=None, source=None):
    """记一行审计到 admin.log，返回本行 call_id。

    sub：子命令/操作名（client.py 传 argv[1]；ticket.py 直 spawn 传 'ticket.<op>'）。
    receipt：回执 dict（只读摘要进 summary，不整抄 args——畸形/超长输入在此截断）。
    call_id：缺省取 env SANDBAR_CLIENT_CALL_ID（ticket.py 直调的关联键），再缺省自生成。
    source：调用方覆盖（ticket.py 直 spawn 行用 'ticket.py-direct'；缺省 claimed_source）。
    写失败只 stderr 留痕，绝不 raise——审计不吞回执（主契约优先，见模块头）。
    """
    if not call_id:
        call_id = os.environ.get(CALL_ID_ENV) or uuid.uuid4().hex[:12]
    if source is None:
        source = claimed_source()
    try:
        summary = json.dumps(receipt, ensure_ascii=False, default=repr)
    except Exception:
        summary = repr(receipt)
    rec = {
        'ts': int(time.time()),
        'call_id': str(call_id)[:64],
        'source': str(source)[:32],
        'sub': str(sub)[:64],
        'ok': bool(receipt.get('ok')) if isinstance(receipt, dict) else False,
        'summary': summary[:800],
    }
    line = json.dumps(rec, ensure_ascii=False, default=repr)
    try:
        with _log_path().open('a', encoding='utf-8') as f:
            f.write(line + '\n')
    except OSError as e:
        # 显式降级：admin.log 不可写（只读盘/权限）时回执照常返回，stderr 留痕。
        # 不静默：吞掉这条等于把 KI-067 的盲区从「不记」换成「记失败无人知」。
        print('audit: admin.log 写失败（回执不受影响）：%s' % e, file=sys.stderr)
    return call_id
