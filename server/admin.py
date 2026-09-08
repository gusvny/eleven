#!/usr/bin/env python3
"""溯游 admin CLI + DeepSeek agent loop（架构§12.2 harness 契约）。

用法：
  python3 server/admin.py tools                      # 列工具（DeepSeek tools schema 直出）
  python3 server/admin.py call <name> '<json>'       # 直接调用（不走 HTTP，工具化第一形态）
  python3 server/admin.py chat "<自然语言任务>"       # DeepSeek agent loop（需 DEEPSEEK_API_KEY）

chat：OpenAI 兼容协议打 https://api.deepseek.com（model=deepseek-chat），tools=注册表
直出；多轮 tool-call ≤8 轮（契约第 4 条：防 agent 失控循环）；每轮打印调了哪个工具。
无 key 时友好报错并提示 CLI 直调可用。纯 stdlib（urllib），零 pip 依赖。

chat_loop() 是 CLI 与 serve.py 的 POST /api/admin/chat（WebUI）共用的唯一 loop 实现。
"""
import json
import os
import sys
import urllib.request
import urllib.error
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import tools_registry  # noqa: E402

API = 'https://api.deepseek.com/chat/completions'
MODEL = 'deepseek-chat'
MAX_ROUNDS = 8

SYSTEM = (
    '你是 sandbar 多项目工单引擎的 admin agent（引擎中立面，项目 persona 由各项目仓自带），'
    '内容管线产物在 pipeline/output/<期次>/，app 运行时数据在 app/public/data/。'
    '你通过工具完成 QC、参数调整、数据盘点。规则：'
    '①QC 红项必须逐条列出（ku id + 原因），不许只说"红了"；'
    '②green=true 才可建议放行；③参数改动用 params_set，改前可 params_get 看现值；'
    '④破坏性操作不在你的工具面内——你只出结构化结论与提案，人来做终审。'
)


def cmd_tools():
    print(json.dumps(tools_registry.schema(), ensure_ascii=False, indent=1))


def cmd_call(name, args_json):
    try:
        args = json.loads(args_json) if args_json else {}
    except json.JSONDecodeError as e:
        print('args 不是合法 JSON: %s' % e, file=sys.stderr)
        sys.exit(2)
    res = tools_registry.call(name, args, actor='cli')
    print(json.dumps(res, ensure_ascii=False, indent=1))
    sys.exit(0 if res['ok'] else 1)


def _post(payload, key):
    req = urllib.request.Request(
        API, data=json.dumps(payload).encode('utf-8'),
        headers={'Content-Type': 'application/json', 'Authorization': 'Bearer ' + key},
        method='POST')
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read().decode('utf-8'))


def chat_loop(messages, key, actor='deepseek-chat', on_call=None):
    """DeepSeek tool-calling loop（CLI 与 API/WebUI 共用的唯一实现）。

    messages: 全量对话历史 [{role, content}...]（不含 system，本函数自动前置 SYSTEM；
              只取 user/assistant，其余 role 忽略）。
    key:      DeepSeek API key（调用方负责判空）。
    actor:    写进 admin.log 的调用者名（CLI='deepseek-chat'，WebUI='webui'）。
    on_call:  可选回调 on_call(round, name, args)，CLI 用来逐轮打印。

    返回 {ok, reply, calls, rounds, ...}：
      ok=True  → reply=最终文本；capped=True 表示撞到 MAX_ROUNDS 上限后强制收尾。
      ok=False → error/detail 描述失败（api_http / api_request）；calls 保留已跑部分。
      calls=[{name, args, ok, run_id, summary}]，每次工具调用都经 tools_registry.call 审计。
    """
    convo = [{'role': 'system', 'content': SYSTEM}]
    for m in messages:
        if isinstance(m, dict) and m.get('role') in ('user', 'assistant') \
                and isinstance(m.get('content'), str):
            convo.append({'role': m['role'], 'content': m['content']})
    trace = []
    tools = tools_registry.schema()

    def _fail(kind, detail, rounds_done):
        return {'ok': False, 'error': kind, 'detail': detail, 'reply': None,
                'calls': trace, 'rounds': rounds_done}

    for rnd in range(1, MAX_ROUNDS + 1):
        try:
            resp = _post({'model': MODEL, 'messages': convo, 'tools': tools,
                          'tool_choice': 'auto'}, key)
        except urllib.error.HTTPError as e:
            return _fail('api_http', 'DeepSeek API %s: %s' % (
                e.code, e.read().decode('utf-8', 'replace')[:400]), rnd - 1)
        except Exception as e:
            return _fail('api_request', 'DeepSeek API 请求失败: %s' % e, rnd - 1)
        msg = resp['choices'][0]['message']
        convo.append(msg)
        tcs = msg.get('tool_calls') or []
        if not tcs:
            return {'ok': True, 'reply': msg.get('content') or '(空回复)',
                    'calls': trace, 'rounds': rnd, 'capped': False}
        for tc in tcs:
            fn = tc['function']['name']
            try:
                targs = json.loads(tc['function'].get('arguments') or '{}')
            except json.JSONDecodeError:
                targs = {}
            if on_call:
                on_call(rnd, fn, targs)
            res = tools_registry.call(fn, targs, actor=actor)
            trace.append({'name': fn, 'args': targs, 'ok': res['ok'],
                          'run_id': res['run_id'],
                          'summary': tools_registry._summarize(
                              res.get('result', res.get('error')))})
            convo.append({'role': 'tool', 'tool_call_id': tc['id'],
                          'content': json.dumps(res, ensure_ascii=False)})
    # 已达上限：最后一轮不带 tools 让模型总结
    try:
        resp = _post({'model': MODEL, 'messages': convo}, key)
    except urllib.error.HTTPError as e:
        return _fail('api_http', 'DeepSeek API %s: %s' % (
            e.code, e.read().decode('utf-8', 'replace')[:400]), MAX_ROUNDS)
    except Exception as e:
        return _fail('api_request', 'DeepSeek API 请求失败: %s' % e, MAX_ROUNDS)
    return {'ok': True, 'reply': resp['choices'][0]['message'].get('content') or '(空回复)',
            'calls': trace, 'rounds': MAX_ROUNDS, 'capped': True}


def cmd_chat(task):
    key = os.environ.get('DEEPSEEK_API_KEY', '').strip()
    if not key:
        print('未设置 DEEPSEEK_API_KEY，chat 不可用。', file=sys.stderr)
        print('提示：export DEEPSEEK_API_KEY=sk-... 后重试；'
              '或直接用 CLI 直调：python3 server/admin.py call <name> \'<json>\''
              '（tools 子命令可看全部工具）。', file=sys.stderr)
        sys.exit(2)

    def _on_call(rnd, fn, targs):
        print('[轮%d] 调工具 %s %s' % (rnd, fn, json.dumps(targs, ensure_ascii=False)),
              flush=True)

    out = chat_loop([{'role': 'user', 'content': task}], key,
                    actor='deepseek-chat', on_call=_on_call)
    if not out['ok']:
        print(out['detail'], file=sys.stderr)
        sys.exit(1)
    if out.get('capped'):
        print('已达 %d 轮工具调用上限，强制收尾。' % MAX_ROUNDS, file=sys.stderr)
    print(out['reply'])


def main():
    if len(sys.argv) < 2 or sys.argv[1] in ('-h', '--help'):
        print(__doc__)
        return
    cmd = sys.argv[1]
    if cmd == 'tools':
        cmd_tools()
    elif cmd == 'call':
        if len(sys.argv) < 3:
            print('用法: admin.py call <name> \'<json>\'', file=sys.stderr)
            sys.exit(2)
        cmd_call(sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else '{}')
    elif cmd == 'chat':
        if len(sys.argv) < 3:
            print('用法: admin.py chat "<任务>"', file=sys.stderr)
            sys.exit(2)
        cmd_chat(sys.argv[2])
    else:
        print('未知子命令 %r（tools / call / chat）' % cmd, file=sys.stderr)
        sys.exit(2)


if __name__ == '__main__':
    main()
