#!/usr/bin/env python3
"""review_store —— knowledge review 持久化的 pipeline/agent 侧入口（M5②，t260821-m45）。

与本插件 node 侧 src/shared/review-store.ts **同制式**（同文件格式、同路径映射、同白名单）：

  落盘  docs/reviews/<path 中 / 换 __>.json
        （如 docs/reviews/design__知识库设计.md.json）
  结构  { path, rounds: [ { base, ts, reviewer, conclude, blocks: [
            { block_key, summary, type, status, decision?, comment? } ] } ] }
  conclude: approved | changes-requested | in-progress
  round 可带扩展键 ticket/stage（审校出自哪张工单哪一段，TS 侧读写原样透传）。

用途：content-pipeline 的 ai-review 段（proofreader agent）把逐块审校意见落盘——
落盘后知识库 UI（GET /sandbar-knowledge/api/review）按 block_key 自动回填显示；
rework 子命令生成**可一键复制的返工指令**（直接贴进 ticket rework note / 派活 prompt）。
block_key 取知识库 diff API（/sandbar-knowledge/api/diff）返回的块键才能在 UI 回填到块；
整篇级意见用 doc: 前缀自由锚点（如 doc:whole、doc:结构），不回填块但进 rounds 存档。

CLI（stdout 单行 JSON，{"ok":true,"result":...} / {"ok":false,"error":...}，同 admin 工具契约）：

  save '{"path":"design/xx.md","base":"HEAD","conclude":"changes-requested",
         "reviewer":"proofreader","ticket":"t260821-xx","stage":"ai-review",
         "blocks":[{"block_key":"h2:3:a1b2","summary":"§3 标题","type":"heading",
                    "status":"modified","decision":"reject","comment":"…"}]}'
      → 追加一轮 review 落盘 + server/admin.log JSONL 审计（actor=knowledge-review，回 run_id）
  show '<path>'                      → 读已存 review（无则空 rounds）
  rework '<path>' [ticket]           → 取最后一轮 conclude=changes-requested 的 reject 块，
                                       生成一键复制返工指令文本（result.instruction）

环境变量 SUYOU_REPO 覆盖仓库根（自测用临时目录，绝不碰真 docs/）；缺省按本文件位置推导
（<repo>/server/dsh/knowledge/review_store.py 上三级）。

内容 KU 审校（接口预留说明，本工单不打通）：
  - block_key 约定：ku:<ku_id>#p<段序>（如 ku:260725-ku-03#p2），整 KU 级用 ku:<ku_id>；
  - path 约定：content/ku/<期次>.md 虚拟锚点文档（一期一文件，reviews 文件名
    content__ku__<期次>.md.json）；
  - 接通时需要：node.ts 的 DOC_PATH_RE 扩 content/ku/ 前缀白名单 + 知识库 UI 按 ku: 键
    回填到 KU 视图 + pipeline 侧产出 KU 切块（对齐 blocks.ts 细粒度契约）。
  本文件只对 docs 类文档审校负责（白名单与 node.ts 同源）；ku: 前缀 block_key 不拦截，
  但 path 白名单未扩前 content/ku/* 会被拒——这是有意的（接口未通不假装通）。
"""
import json
import os
import re
import sys
import time
import uuid
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = Path(os.environ.get('SUYOU_REPO') or HERE.parents[2]).resolve()
DOCS = REPO / 'docs'
REVIEWS = DOCS / 'reviews'
ADMIN_LOG = REPO / 'server' / 'admin.log'

# 与 node.ts DOC_PATH_RE 同源白名单（防穿路径）：四分类目录下的一层 .md。
DOC_PATH_RE = re.compile(r'^(design|content|ops|reference)/[^/]+\.md$')
CONCLUDES = ('approved', 'changes-requested', 'in-progress')
DECISIONS = ('approve', 'reject')
BASE_RE = re.compile(r'^[A-Za-z0-9._~^/-]+$')


class ReviewError(ValueError):
    """业务拒绝（与引擎工具同契约：不走异常栈，走 ok=False）。"""


def _file_name(p):
    return p.replace('/', '__') + '.json'


def _file_path(p):
    return REVIEWS / _file_name(p)


def load_review(p):
    """读已存 review；不存在返回空 rounds（不是错误）。"""
    fp = _file_path(p)
    if not fp.is_file():
        return {'path': p, 'rounds': []}
    try:
        data = json.loads(fp.read_text('utf-8'))
    except Exception as e:
        raise ReviewError('review 文件损坏: %s: %s' % (fp, e))
    rounds = data.get('rounds') if isinstance(data, dict) else None
    return {'path': p, 'rounds': rounds if isinstance(rounds, list) else []}


def append_round(p, rnd):
    """追加一轮 review（读-改-写；reviews 目录不存在则建）。"""
    REVIEWS.mkdir(parents=True, exist_ok=True)
    cur = load_review(p)
    cur['rounds'].append(rnd)
    _file_path(p).write_text(json.dumps(cur, ensure_ascii=False, indent=2) + '\n', 'utf-8')
    return cur


def _audit(run_id, name, args, ok, summary):
    """admin.log 同款审计：append-only JSONL，与 tools_registry/node.ts 同形同文件。"""
    rec = json.dumps({
        'run_id': run_id, 'ts': int(time.time()), 'actor': 'knowledge-review',
        'name': name, 'args': args, 'ok': ok,
        'summary': summary[:800] + ('…' if len(summary) > 800 else ''),
    }, ensure_ascii=False)
    try:
        ADMIN_LOG.parent.mkdir(parents=True, exist_ok=True)
        with ADMIN_LOG.open('a', encoding='utf-8') as f:
            f.write(rec + '\n')
    except Exception as e:  # 审计失败不影响主流程，但要喊出来
        print('review_store: admin.log 审计写入失败: %s' % e, file=sys.stderr)


def _validate_block(b):
    if not isinstance(b, dict) or not isinstance(b.get('block_key'), str) or not b['block_key']:
        raise ReviewError('每个 block 必须带非空 block_key（diff API 块键或 doc:/ku: 锚点）')
    out = {
        'block_key': b['block_key'],
        'summary': str(b.get('summary') or '')[:120],
        'type': str(b.get('type') or ''),
        'status': str(b.get('status') or ''),
    }
    if b.get('decision') in DECISIONS:
        out['decision'] = b['decision']
    if isinstance(b.get('comment'), str) and b['comment']:
        out['comment'] = b['comment'][:2000]
    return out


def op_save(a):
    run_id = uuid.uuid4().hex[:12]
    p = a.get('path') if isinstance(a.get('path'), str) else ''
    try:
        if not DOC_PATH_RE.match(p):
            raise ReviewError('path 不合法（只允许 design|content|ops|reference/<文件>.md）: %r' % p)
        base = a.get('base') if isinstance(a.get('base'), str) and a.get('base') else 'HEAD'
        if base != 'HEAD' and not BASE_RE.match(base):
            raise ReviewError('base 不合法: %r' % base)
        conclude = a.get('conclude')
        if conclude not in CONCLUDES:
            raise ReviewError('conclude 必须是 %s' % ' | '.join(CONCLUDES))
        blocks = a.get('blocks')
        if not isinstance(blocks, list):
            raise ReviewError('blocks 必须是数组')
        entries = [_validate_block(b) for b in blocks]
        reviewer = str(a.get('reviewer') or '').strip()[:40] or 'agent'
        rnd = {'base': base, 'ts': int(time.time()), 'reviewer': reviewer,
               'conclude': conclude, 'blocks': entries}
        if a.get('ticket'):
            rnd['ticket'] = str(a['ticket'])[:60]
        if a.get('stage'):
            rnd['stage'] = str(a['stage'])[:40]
        saved = append_round(p, rnd)
        summary = '%s 第 %d 轮 conclude=%s 块 %d' % (p, len(saved['rounds']), conclude, len(entries))
        _audit(run_id, 'review.save', {'path': p, 'base': base, 'conclude': conclude,
                                       'blocks': len(entries),
                                       'ticket': rnd.get('ticket', '')}, True, summary)
        return {'path': p, 'rounds': len(saved['rounds']), 'round': rnd, 'run_id': run_id}
    except ReviewError as e:
        _audit(run_id, 'review.save', {'path': p}, False, str(e))
        raise


def op_show(p):
    if not DOC_PATH_RE.match(p or ''):
        raise ReviewError('path 不合法（只允许 design|content|ops|reference/<文件>.md）: %r' % p)
    return load_review(p)


def build_rework_instruction(p, ticket=''):
    """取最后一轮 conclude=changes-requested 的 review，生成一键复制返工指令。"""
    cur = load_review(p)
    last = None
    for rnd in reversed(cur['rounds']):
        if rnd.get('conclude') == 'changes-requested':
            last = rnd
            break
    if last is None:
        raise ReviewError('%s 没有 conclude=changes-requested 的 review 轮次（共 %d 轮）'
                          % (p, len(cur['rounds'])))
    rejects = [b for b in (last.get('blocks') or []) if b.get('decision') == 'reject']
    n = cur['rounds'].index(last) + 1
    lines = [
        '【返工指令】%s 第 %d 轮审校（reviewer=%s，conclude=changes-requested）' % (
            p, n, last.get('reviewer', '')),
        '审校存档：docs/reviews/%s（知识库 UI 按 block_key 回填）' % _file_name(p),
        '逐条修改（reject 块 %d 条）：' % len(rejects),
    ]
    for i, b in enumerate(rejects, 1):
        lines.append('%d. [%s] %s' % (i, b.get('block_key', ''), b.get('summary', '')))
        if b.get('comment'):
            lines.append('   意见：%s' % b['comment'])
    if not rejects:
        lines.append('（本轮无逐块 reject，按整篇结论修改）')
    ticket_id = ticket or last.get('ticket') or '<工单id>'
    brief = '；'.join(('%s: %s' % (b.get('block_key', ''), b.get('summary', '')))
                      for b in rejects[:3]) or '按审校意见修改'
    lines += [
        '',
        '一键复制（贴进终端执行工单返工）：',
        "python3 server/admin.py call ticket rework '{\"id\":\"%s\",\"note\":\"%s 审校返工：%s（详见 docs/reviews/%s）\"}'"
        % (ticket_id, p, brief, _file_name(p)),
    ]
    return {'path': p, 'round': n, 'rejects': len(rejects),
            'ticket': ticket_id, 'instruction': '\n'.join(lines)}


def main(argv):
    if len(argv) < 2:
        print(json.dumps({'ok': False, 'error': __doc__}, ensure_ascii=False))
        return 2
    op = argv[1]
    try:
        if op == 'save':
            if len(argv) < 3:
                raise ReviewError('save 需要 JSON 参数')
            a = json.loads(argv[2])
            if not isinstance(a, dict):
                raise ReviewError('save 参数需为 JSON 对象')
            res = op_save(a)
        elif op == 'show':
            if len(argv) < 3:
                raise ReviewError('show 需要 path')
            res = op_show(argv[2])
        elif op == 'rework':
            if len(argv) < 3:
                raise ReviewError('rework 需要 path [ticket]')
            res = build_rework_instruction(argv[2], argv[3] if len(argv) > 3 else '')
        else:
            raise ReviewError('未知 op: %r（save/show/rework）' % op)
    except (ReviewError, json.JSONDecodeError) as e:
        print(json.dumps({'ok': False, 'error': str(e)}, ensure_ascii=False))
        return 1
    print(json.dumps({'ok': True, 'result': res}, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
