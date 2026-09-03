#!/usr/bin/env python3
"""溯游 admin 工具注册表 —— 热插拔（架构§12.2 契约第 1 条）。

server/tools/ 下每个 .py 文件 = 一个工具：
    TOOL = {"name": ..., "description": ..., "parameters": <JSON Schema>}
    def run(args: dict) -> dict
新工具 = 丢文件即上线，本文件不用动。以 "_"/"." 开头的文件被忽略。

所有调用（CLI 与 API 双形态共用 call()）append-only 写 server/admin.log（JSONL，
契约第 4 条 run-id 审计）。
"""
import importlib.util
import json
import time
import traceback
import uuid
from pathlib import Path

HERE = Path(__file__).resolve().parent
TOOLS_DIR = HERE / 'tools'
LOG = HERE / 'admin.log'

_cache = None


def load_tools():
    """扫描 tools/ 目录，返回 {name: module}。带进程内缓存，reload() 可刷新。"""
    global _cache
    if _cache is not None:
        return _cache
    tools = {}
    if TOOLS_DIR.is_dir():
        for f in sorted(TOOLS_DIR.glob('*.py')):
            if f.name.startswith(('_', '.')):
                continue
            spec = importlib.util.spec_from_file_location('suyou_admin_tool_' + f.stem, f)
            mod = importlib.util.module_from_spec(spec)
            try:
                spec.loader.exec_module(mod)
            except Exception:
                # 坏工具不拖垮整表：登记为加载错误，调用时回报
                tools[f.stem] = _broken(f.stem, traceback.format_exc(limit=3))
                continue
            meta = getattr(mod, 'TOOL', None)
            runner = getattr(mod, 'run', None)
            if not isinstance(meta, dict) or not meta.get('name') or not callable(runner):
                tools[f.stem] = _broken(f.stem, '缺 TOOL dict 或 run(args)')
                continue
            tools[meta['name']] = mod
    _cache = tools
    return tools


def _broken(name, why):
    class M:
        TOOL = {'name': name, 'description': '[加载失败] ' + why.splitlines()[-1],
                'parameters': {'type': 'object', 'properties': {}}}

        @staticmethod
        def run(args):
            raise RuntimeError('工具加载失败: ' + why)
    return M


def reload():
    global _cache
    _cache = None
    return load_tools()


def schema():
    """DeepSeek/OpenAI tools 格式直出（契约第 1 条：任意 harness 可绑）。"""
    out = []
    for name, mod in sorted(load_tools().items()):
        t = mod.TOOL
        out.append({'type': 'function', 'function': {
            'name': t['name'],
            'description': t.get('description', ''),
            'parameters': t.get('parameters', {'type': 'object', 'properties': {}}),
        }})
    return out


def _summarize(obj, limit=800):
    s = json.dumps(obj, ensure_ascii=False)
    return s if len(s) <= limit else s[:limit] + '…'


def audit(rec):
    with LOG.open('a', encoding='utf-8') as f:
        f.write(json.dumps(rec, ensure_ascii=False) + '\n')


def call(name, args=None, actor='cli'):
    """统一调用入口：返回 {ok, result|error, run_id}，并写审计日志。"""
    run_id = uuid.uuid4().hex[:12]
    args = args or {}
    tools = load_tools()
    if name not in tools:
        res = {'ok': False, 'error': '未知工具 %r（可用: %s）' % (name, ', '.join(sorted(tools)))}
    else:
        try:
            res = {'ok': True, 'result': tools[name].run(args)}
        except Exception as e:
            res = {'ok': False, 'error': '%s: %s' % (type(e).__name__, e)}
            # 分级错误 kind 存活口（KI-025，t260903-06）：带 .kind 属性的异常
            # （tools.ticket.QueryError 等）把 kind 并入回执 dict——否则 kind 在
            # 本出口湮灭，工作台/UI 的 404/503/410 分流失去判据。
            # duck-type 识别（不 import 具体类，避免 registry→tools 循环依赖）：
            # 全仓对抗核查（2026-09-03）无其他异常携带 .kind 属性，误并面为零；
            # 即便误并也只是多带一个字符串字段，方向安全。
            kind = getattr(e, 'kind', None)
            if isinstance(kind, str) and kind:
                res['kind'] = kind
    res['run_id'] = run_id
    audit({'run_id': run_id, 'ts': int(time.time()), 'actor': actor,
           'name': name, 'args': args, 'ok': res['ok'],
           'summary': _summarize(res.get('result', res.get('error')))})
    return res
