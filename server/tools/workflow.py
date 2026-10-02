#!/usr/bin/env python3
"""workflow —— 工单工作流模板（server/workflows/<id>.yaml，只读热插拔）。

模板=阶段链：不同活流程不同，工单只挂实例（Ticket Workflow Console Design §8/§9）。
丢文件即上线（同 tools_registry 热插拔）。模板是线性单链：
stages[i].next == stages[i+1].id（末段无 next）；fanout 表示该段可扇出多 agent
并行，不是流程分叉。

yaml 子集解析（纯 stdlib，无 PyYAML 依赖——server 层铁律）：
  - 顶层 map + stages 列表 + stage 内标量/acceptance 标量列表，最多两级嵌套
  - ' #' 起内联注释、'#' 起整行注释；禁 tab 缩进；值内禁 ' #' 与裸 ':' 后空格
  - 不认识的写法大声报错（不静默丢，同管线 lint 哲学）

op:
  list           → [{id, name, lane, stages:[{id, role, name, next, exit, fanout, parts, acceptance}],
                     topology（t260915-05 additive：模板拓扑导出面契约；None=未声明，UI 回落线性呈现）}]
  show {id}      → 模板全文（含 desc/description）
"""
import json
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
DIR = HERE.parent / 'workflows'
ENGINE = HERE.parent / 'engine'

# 引擎 venv 解析（回落链与 ticket.py TEMP_PY 同口径：server/engine/.venv 优先）。
def _engine_py() -> str:
    cand = ENGINE / '.venv' / 'bin' / 'python'
    if cand.is_file():
        import os
        if os.access(str(cand), os.X_OK):
            return str(cand)
    return 'python3'

# t260915-05：模板拓扑导出面。被导者是引擎**纯数据模块**（零 IO 零 temporalio），
# server 层「不跨层 import 运行时」的铁律不破。导入失败=导出面缺位，list 通道
# 继续活，缺席以 stderr 一行点名（渲染器回落线性步骤条，绝不静默冒充有拓扑）。
sys.path.insert(0, str(ENGINE))
try:
    import template_topology  # type: ignore
except Exception as _tt_err:  # pragma: no cover - 引擎目录缺席的极端部署形态
    template_topology = None  # type: ignore[assignment]
    print('workflow: template_topology 导入失败，list 不带 topology 值：%s: %s'
          % (type(_tt_err).__name__, _tt_err), file=sys.stderr)

# 前五个=M10 五角色定稿（t260822）；后五个=退役 id——在跑工单模板快照仍钉着
# 旧值，校验须继续放行。content-pipeline 人门段已退役 260904，其 approve/
# final-review（exit=human）仍标 dispatcher，属兼容留存。
ROLES = ('developer', 'integration', 'ops', 'product-operation', 'artist',  # M10 五角色定稿
         'dispatcher', 'editor', 'proofreader', 'qa', 'analyst')  # 退役 id（兼容在跑单/人门段）

# 执行主体枚举（t260828-01，与 engine/shared.py PART_KINDS 同口径；
# 本文件是 server 层纯 stdlib 工具，不跨层 import，枚举在此复述一份）。
PART_KINDS = ('agent', 'script', 'human')

TOOL = {
    'name': 'workflow',
    'description': ('工单工作流模板：list 列全部模板（id/name/lane/stages 链；'
                    't260927-05 起含项目声明的外置模板——与 create 闸同源 '
                    'template-faces，可用 project 参数按声明方过滤，故障/缺席以 '
                    'catalog_note 点名），show 看单模板全文（外置 id=权威面推导视图）。'
                    '内置模板存 server/workflows/<id>.yaml 只读热插拔，线性单链'
                    '（next=下一段，末段无 next），fanout 表示该段可扇出多 agent。'),
    'parameters': {
        'type': 'object',
        'properties': {
            'op': {'type': 'string', 'enum': ['list', 'show']},
            'id': {'type': 'string', 'description': '模板 id（show 必填）'},
        },
        'required': ['op'],
        'additionalProperties': False,
    },
}


# ---------- yaml 子集解析 ----------

def _tokens(text):
    toks = []
    for raw in text.splitlines():
        line = raw.rstrip('\n')
        if ' #' in line:
            line = line.split(' #', 1)[0].rstrip()
        if not line.strip():
            continue
        if line.lstrip().startswith('#'):
            continue
        indent = len(line) - len(line.lstrip(' '))
        if '\t' in line[:indent]:
            raise ValueError('缩进禁用 tab（第 %d 行）' % (len(toks) + 1))
        toks.append((indent, line.strip()))
    return toks


def _split_kv(s):
    """返回 (key, value, nested)。nested=True 表示冒号后无值、下面挂块。"""
    if s.endswith(':'):
        return s[:-1].strip(), '', True
    m = re.match(r'^([^:]+):\s?(.*)$', s)
    if m:
        return m.group(1).strip(), m.group(2), False
    return None, None, False


def _parse_value(v):
    v = v.strip()
    if not v:
        return None
    if v[0] in "'\"":
        if len(v) >= 2 and v[-1] == v[0]:
            return v[1:-1]
        raise ValueError('未闭合引号: %r' % v)
    if v == 'true':
        return True
    if v == 'false':
        return False
    if re.fullmatch(r'-?\d+', v):
        return int(v)
    return v


def parse_yaml(text):
    """yaml 子集 → dict。结构：顶层 map；值=标量 | 块 map | 块 list；
    列表项=标量 | 内联 map（'- k: v'）| 块 map。"""
    toks = _tokens(text)
    if not toks:
        raise ValueError('空 yaml')
    if toks[0][0] != 0:
        raise ValueError('顶层缩进必须为 0')
    i = [0]

    def _peek():
        return toks[i[0]] if i[0] < len(toks) else (None, None)

    def _nested_block(indent):
        """吃掉 > indent 的下一块，返回 (value, consumed)。"""
        ind, t = _peek()
        if ind is None or ind <= indent:
            return None, False
        if t.startswith('- '):
            return parse_list(ind), True
        return parse_map(ind), True

    def parse_map(indent):
        d = {}
        while i[0] < len(toks):
            ind, t = toks[i[0]]
            if ind < indent:
                break
            if ind > indent:
                raise ValueError('缩进跳跃（%d→%d）: %r' % (indent, ind, t))
            if t.startswith('- '):
                raise ValueError('map 内不允许裸列表项: %r' % t)
            k, v, nested = _split_kv(t)
            if k is None:
                raise ValueError('无法解析行: %r' % t)
            i[0] += 1
            if nested:
                val, _ = _nested_block(indent)
                d[k] = val
            else:
                d[k] = _parse_value(v)
        return d

    def parse_list(indent):
        out = []
        while i[0] < len(toks):
            ind, t = toks[i[0]]
            if ind < indent:
                break
            if ind > indent:
                raise ValueError('缩进跳跃: %r' % t)
            if not t.startswith('- '):
                raise ValueError('列表内必须是 "- " 项: %r' % t)
            rest = t[2:].strip()
            i[0] += 1
            if not rest:
                val, _ = _nested_block(indent)
                out.append(val)
                continue
            k, v, nested = _split_kv(rest)
            if k is not None:
                item = {}
                if nested:
                    val, _ = _nested_block(indent)
                    item[k] = val
                else:
                    item[k] = _parse_value(v)
                ind2, _ = _peek()
                if ind2 is not None and ind2 > indent:
                    item.update(parse_map(ind2))
                out.append(item)
            else:
                out.append(_parse_value(rest))
        return out

    root = parse_map(0)
    if i[0] < len(toks):
        raise ValueError('解析未耗尽: %r' % (toks[i[0]:],))
    return root


# ---------- 结构校验 ----------

def validate(t):
    for k in ('id', 'name', 'lane', 'stages'):
        if k not in t:
            raise ValueError('模板缺 %s' % k)
    if t['lane'] not in ('main', 'worktree'):
        raise ValueError('lane 必须 main/worktree，实际 %r' % t['lane'])
    stages = t['stages']
    if not isinstance(stages, list) or not stages:
        raise ValueError('stages 必须是非空列表')
    ids = [s.get('id') for s in stages]
    if len(ids) != len(set(ids)):
        raise ValueError('stage id 重复: %s' % ids)
    for idx, s in enumerate(stages):
        for k in ('id', 'role', 'name'):
            if not s.get(k):
                raise ValueError('stage[%d] 缺 %s' % (idx, k))
        if s['role'] not in ROLES:
            raise ValueError('stage %s 未知角色 %r（可用: %s）'
                             % (s['id'], s['role'], '/'.join(ROLES)))
        acc = s.get('acceptance')
        if acc is not None:
            if not isinstance(acc, list) or not all(isinstance(x, str) and x.strip() for x in acc):
                raise ValueError('stage %s 的 acceptance 必须是字符串列表' % s['id'])
        if s.get('fanout') not in (None, 0, 1):
            raise ValueError('stage %s 的 fanout 必须 0/1' % s['id'])
        if s.get('exit') not in (None, 'human'):
            raise ValueError('stage %s 的 exit 只能 human' % s['id'])
        # 执行主体组合声明（t260828-01）：可选（旧 yaml 无 parts 不拦），有则必须枚举内。
        parts = s.get('parts')
        if parts is not None:
            if not isinstance(parts, list) or not all(isinstance(x, str) for x in parts):
                raise ValueError('stage %s 的 parts 必须是字符串列表' % s['id'])
            bad = [p for p in parts if p not in PART_KINDS]
            if bad:
                raise ValueError('stage %s 的 parts 含非法值 %r（可用: %s）'
                                 % (s['id'], bad, '/'.join(PART_KINDS)))
        nx = s.get('next')
        if nx is not None and nx not in ids:
            raise ValueError('stage %s 的 next 指向不存在的 stage: %r' % (s['id'], nx))
    # 线性单链：stages[i].next == stages[i+1].id，末段无 next
    for idx, s in enumerate(stages):
        expect = stages[idx + 1]['id'] if idx + 1 < len(stages) else None
        if s.get('next') != expect:
            raise ValueError('模板必须是线性单链：stage %s 的 next 应为 %r，实际 %r'
                             % (s['id'], expect, s.get('next')))
    return t


# ---------- 加载 ----------

def load(path):
    if not path.is_file():
        raise ValueError('模板不存在: %s' % path)
    t = parse_yaml(path.read_text('utf-8'))
    validate(t)
    if path.stem != t['id']:
        raise ValueError('文件名 %s 与模板 id %s 不一致' % (path.name, t['id']))
    return t


def load_all():
    out = {}
    if DIR.is_dir():
        for f in sorted(DIR.glob('*.yaml')):
            try:
                t = load(f)
            except Exception as e:
                raise ValueError('模板 %s 加载失败: %s' % (f.name, e))
            out[t['id']] = t
    return out


def _topology_of(tid):
    """模板拓扑契约导出（t260915-05）。None=未声明模板（渲染器回落线性呈现，
    绝不猜拓扑）；导出抛错（声明被改坏）= stderr 点名后回落 None——list 通道
    不被导出面炸掉，但缺口有痕。"""
    if template_topology is None:
        return None
    try:
        return template_topology.export_template_topology(tid)
    except Exception as e:
        print('workflow: %s 拓扑导出失败（回落 None）：%s: %s'
              % (tid, type(e).__name__, e), file=sys.stderr)
        return None


def _brief(t):
    return {'id': t['id'], 'name': t['name'], 'lane': t['lane'],
            'stages': [{'id': s['id'], 'role': s['role'], 'name': s['name'],
                        'next': s.get('next'), 'exit': s.get('exit'),
                        'fanout': s.get('fanout', 0),
                        'revision_to': s.get('revision_to'),
                        'parts': s.get('parts') or [],
                        'acceptance': s.get('acceptance') or []}
                       for s in t['stages']],
            # t260915-05：additive 键——stages 仍是线性近似参考链（老消费面不动），
            # topology 才是真并行拓扑（KI-019）；未知模板显式 None 不省键（形状稳定）。
            'topology': _topology_of(t['id'])}


def _v2_extra_rows(yaml_ids):
    """环境门下 v2 注册表模板补进目录面（t260915-05 锁②通道）。

    yaml 参考目录只收生产模板（收窄守卫 sc_template_face_narrowing 钉默认面
    ={dev-lane}，测试夹具模板不进 yaml）；SANDBAR_FIXTURE_TEMPLATES=1 时把
    v2 注册表里 yaml 没有的模板补进 list——渲染器通用性对拍与目录完整性消费
    同一通道。import workflows_v2 会拉 temporalio：纯 stdlib 部署形态（无 venv）
    门开着也列不出=stderr 点名后缺席（绝不静默冒充，也绝不让 list 通道炸掉）。
    """
    import os
    if os.environ.get('SANDBAR_FIXTURE_TEMPLATES') != '1':
        return []
    try:
        import workflows_v2  # type: ignore  # engine 目录已入 sys.path（模板导出面同款）
    except Exception as e:
        print('workflow: v2 注册表导入失败（SANDBAR_FIXTURE_TEMPLATES=1 但缺 '
              'temporalio/引擎目录？），list 缺 v2 模板：%s: %s'
              % (type(e).__name__, e), file=sys.stderr)
        return []
    rows = []
    for cls in getattr(workflows_v2, 'ALL_WORKFLOWS_V2', []) or []:
        tid = getattr(cls, 'TEMPLATE_ID', '') or ''
        if not tid or tid in yaml_ids:
            continue
        stages = []
        for s in (getattr(cls, 'STAGES', None) or ()):
            stages.append({'id': getattr(s, 'id', ''), 'role': getattr(s, 'role', ''),
                           'name': getattr(s, 'name', ''), 'next': getattr(s, 'next', '') or None,
                           'exit': getattr(s, 'exit', '') or None,
                           'fanout': getattr(s, 'fanout', 0) or 0,
                           'revision_to': getattr(s, 'revision_to', '') or None,
                           'parts': list(getattr(s, 'parts', ()) or ()),
                           'acceptance': list(getattr(s, 'acceptance', ()) or ())})
        rows.append({'id': tid, 'name': getattr(cls, 'TEMPLATE_NAME', tid),
                     'lane': getattr(cls, 'TEMPLATE_LANE', 'worktree'),
                     'stages': stages, 'topology': _topology_of(tid)})
    return rows


def _faces_catalog(project=None):
    """项目外置模板目录行（t260927-05）：经 client.py template-faces 权威面取
    项目声明的外置模板——与 create 闸（ticket.py _template_faces）同源，绝不另立
    第二真源；回执 templates 条目带 STAGES 推导视图与线性拓扑（topology_from_stages）。

    故障清单（对照 ticket.py _poc 通道 review 拍板清单逐条 carried/dropped）：
      - 子进程异常/超时（spawn 失败、timeout）→ carried：stderr 点名 + catalog_note，
        list/show 通道不炸，项目行缺席（fallback naming 纪律：缺席可判别不静默）；
      - 非 JSON 回执 → carried：同上换壳点名（原文截 400 字符留痕）；
      - ok=false / 回执畸形（缺键、类型错）→ carried：fail-closed 点名 catalog_note，
        绝不静默当空表（畸形输入用例纪律）；
      - faces 通道每次现算的延迟 → dropped：只读本地扫描，timeout=120s（远低于
        ticket.py 写闸 900s 口径）；不做进程内缓存——缓存会变成第二真源，风险大于延迟。
      - 声明被加载口拒收（rejections 非空）→ carried（t260927-05 仲裁 Gap 1）：逐条
        stderr 点名 + catalog_note「项目 X 声明的外置模板（模块 m）不在目录：<原因>」
        ——拒收≠装死，目录面必须点名缺席，绝不静默只剩内置模板；
      - 模板 STAGES 拓扑导出失败（topology_error 非空）→ carried（仲裁 Gap 2）：行内
        topology_error 键原样透传 + stderr 点名——topology=None 绝不许匿名。
    project 给定时只收声明方=该项目的模板行（「只有声明方看得见」，无跨项目泄漏）；
    None 收全部已登记项目（宿主机目录面全景），行内自带 project 键可辨来源。
    返回 (rows, note)：note=''=正常；非空=缺席/故障点名文案（多条以「；」相连）。
    """
    cmd = [_engine_py(), str(ENGINE / 'client.py'), 'template-faces', '{}']
    try:
        proc = subprocess.run(cmd, cwd=str(HERE.parent.parent), capture_output=True,
                              text=True, timeout=120)
    except Exception as e:
        _note('项目模板权威面不可达（template-faces 子进程故障）：%s: %s'
              % (type(e).__name__, e))
        return [], 'project template face unreachable (%s)' % type(e).__name__
    try:
        out = json.loads(proc.stdout)
    except (json.JSONDecodeError, TypeError):
        _note('项目模板权威面非 JSON 回执：%s'
              % ((proc.stderr or proc.stdout or '')[:400]))
        return [], 'project template face returned non-JSON'
    if not isinstance(out, dict) or not out.get('ok'):
        _note('项目模板权威面回执 ok=false：%s' % (out if not isinstance(out, dict)
              else out.get('error')))
        return [], 'project template face rejected the query'
    res = out.get('result')
    bad = None
    if not isinstance(res, dict):
        bad = 'result 非对象'
    elif not isinstance(res.get('templates'), dict):
        bad = 'templates 须为对象'
    elif not isinstance(res.get('class_available'), list) or not all(
            isinstance(x, str) for x in res['class_available']):
        bad = 'class_available 须为字符串列表'
    elif not isinstance(res.get('builtin'), list):
        bad = 'builtin 须为字符串列表'
    if bad:
        _note('项目模板权威面回执畸形（%s），fail-closed 不静默当空表' % bad)
        return [], 'project template face malformed (%s)' % bad
    builtin = set(res['builtin'])
    templates = res['templates']
    rows, unshaped, notes = [], [], []
    for tid in res['class_available']:
        if tid in builtin:
            continue  # 内置∪夹具行走 yaml/v2 通道，本通道只补项目外置模板
        tv = templates.get(tid)
        if not isinstance(tv, dict):
            unshaped.append(tid)
            continue
        tproj = str(tv.get('project') or '')
        if project and tproj != project:
            continue  # 未声明方不见（过滤即隔离，无全局泄漏）
        stages = tv.get('stages') or []
        terr = str(tv.get('topology_error') or '')
        if terr:
            # 仲裁 Gap 2：topology=None 必须有名有姓——行内透传 + stderr 点名。
            _note('外置模板 %s 拓扑不可用（%s）——回落线性呈现' % (tid, terr))
        rows.append({'id': tid, 'name': str(tv.get('name') or tid),
                     'lane': str(tv.get('lane') or 'worktree'),
                     'stages': [dict(s) for s in stages if isinstance(s, dict)],
                     'project': tproj,
                     # additive 键：None=该模板 STAGES 导出失败（topology_error 点名），
                     # 渲染器回落线性呈现，绝不猜拓扑。
                     'topology': tv.get('topology'),
                     'topology_error': terr or None})
    if unshaped:
        _note('项目模板回执缺视图（无 stages 推导，不冒充空段表）：%s'
              % '、'.join(sorted(unshaped)))
    # 仲裁 Gap 1：加载口拒收的声明=「声明了但目录里没有」——逐条点名（fallback
    # naming 纪律），project 过滤同样适用（未声明方不见别项目的拒收）。
    for r in (res.get('rejections') or []):
        if not isinstance(r, dict):
            continue
        rproj = str(r.get('project') or '')
        if project and rproj != project:
            continue
        notes.append('project %s declares external template (module %s), not in '
                     'the catalog: rejected [%s] %s'
                     % (rproj or '?', r.get('module') or '?',
                        r.get('check') or '?', str(r.get('detail') or '')[:160]))
    if notes:
        _note('; '.join(notes))
    return rows, '；'.join(notes)


def _note(msg):
    """stderr 点名通道（缺席/故障有痕，list/show 通道不被导出面炸掉）。"""
    print('workflow: %s' % msg, file=sys.stderr)


def run(args):
    op = args.get('op')
    if op == 'list':
        yaml_rows = [_brief(t) for t in load_all().values()]
        listed = {t['id'] for t in yaml_rows}
        # t260915-05：夹具门通道（收窄守卫语义不动——默认面仍=yaml 行）。
        rows = yaml_rows + _v2_extra_rows(listed)
        # t260927-05：项目外置模板通道（与 create 闸同源 template-faces）。
        # 条件=SANDBAR_FIXTURE_TEMPLATES 语义不受影响：本通道独立于夹具门，
        # 但只补「已声明项目」的外置 id——不声明=零行为变化（默认面仍 {dev-lane}）。
        listed |= {r['id'] for r in rows}
        prows, note = _faces_catalog(args.get('project') or None)
        rows += [r for r in prows if r['id'] not in listed]
        out = {'workflows': rows}
        if note:
            out['catalog_note'] = note  # additive 键：缺席/故障点名，前台可显式提示
        return out
    if op == 'show':
        tid = args.get('id') or ''
        try:
            t = load(DIR / (tid + '.yaml'))
        except ValueError:
            t = None
        if t is not None:
            return t
        # t260927-05：yaml 缺席（项目外置模板无引擎仓快照）→ 权威面推导视图。
        # faces 故障/真未知 id → 维持旧契约 raise「模板不存在」（内置未知 id 零
        # 回归）；faces 通道故障同时 stderr 点名（缺席有痕，不静默冒充）。
        rows, _unused = _faces_catalog()
        for r in rows:
            if r['id'] == tid:
                return r
        raise ValueError('模板不存在: %s' % tid)
    raise ValueError('未知 op: %r（list/show）' % (op,))


if __name__ == '__main__':
    import sys
    print(json.dumps(run({'op': 'list'}), ensure_ascii=False, indent=1).encode("utf-8", "backslashreplace").decode("utf-8"))
    sys.exit(0)
