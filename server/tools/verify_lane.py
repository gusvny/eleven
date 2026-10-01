#!/usr/bin/env python3
"""verify_lane —— 泳道一键复验（多角色协作基础设施；roles/README「检查与合并决策链」）。

总管收口的机械复验脚本化：不相信提交者自检，独立重跑验收电池。
分道返回形状（契约②b-2）：lane=content/code → {lane, green, red_count,
checks:[{check, level, items:[{detail}], note?}]}；lane=integ → {lane, green,
ran, pass, fail, scenarios:[{name, exit, output_tail}], err}——integ 道无
red_count/checks，消费方不得按 content 形状读 integ。

lane=content（内容道，主树）：
  1. qc_run 四项（复用 qc_run.py，scope 可指定期次）
  2. 跨源对账：books JSON vs knowledge_units（章数/正文缺失）、quiz 期次覆盖与计数、
     entries 计数、registry 节点期次覆盖
  3. 正文重复段扫描（merge_prose append 陷阱探针，260117/260808 教训）
  4. books.json 书集格式（build_shelf 中途态检测）
  scope 缺省 'auto'：从 git diff（staged+unstaged vs HEAD，无则最近 1 个 commit）推出
  变更期次只扫这些册；'all' 才全库（留给夜间定时/发布前）。对账类在 auto 模式下
  同样只扫变更册（books_json 书集格式等全库项保留，读单文件代价可忽略）。

lane=code（代码道，泳道）——**全配置驱动（t260901-08，契约②）**：检查内容来自泳道根
  verify.yaml（schema v1，字段级定义见 docs/design/sandbar-project-onboarding-contract-v1.md ②a），
  引擎只跑与判、零项目特定硬编码。三态关闭语义（契约②总纲）：
  - 缺失（无 verify.yaml 或无 lanes.code）：该道按项目声明关闭，green 项可见非静默；
  - 畸形（不可解析/结构不合法）：fail-closed 整道红，detail 指明文件与行/字段；
  - 版本不支持：fail-closed 红，写明声明版本与引擎支持区间。
  在位且合法时按声明装配：
  1. 写集白名单：git diff --name-only <base>...HEAD（三点=merge-base 对称差，
      口径=「本次合并将给 main 带来什么」——泳道在制期间他人并入 main 的文件
      不进差集、不判越界；t260901-14 假阳性修正，base 建议传当前 main tip）。
      判据优先级=调用方 write_set
     （工单精判，空列表=零写集，任何改动即红）> verify.yaml write_allow（粗判据）；
     协调目录（.sandbar/ 老 .suyou/）与 .dsh/ 引擎运行时目录一律不判（与 merge_check SETTLE_PATHSPEC 同口径）。  # naming-compat
     require_base=true（合并闸口径）且 base 为空/未传 → fail-closed 红「base_ref 未登记」；
     手动调用未传 base → 跳过但 green 项 note 可见（要验就显式传 base）。
  2. checks 列表命令制（契约②a，t260903-01 对齐）：每条 {id, cmd, cwd?, timeout?}
  仅在声明在位时跑；全部并行跑（独立子进程），总时长取最长者。
"""
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / 'engine'))
# 机器 token 单源（shared.py）：供给面出口文案=「状态 token + 英文人话 + 侧面 token」，
# 签名判据认 token 不认人话（改文案不影响签名；t260927 单源改造）。
from shared import (  # noqa: E402
    SUPPLY_FAIL_SIG, SUPPLY_SIDE_SIG, SUPPLY_STAGE_TIMEOUT_SIG, SUPPLY_TIMEOUT_SIG,
)

TOOL = {
    'name': 'verify_lane',
    'description': ('泳道一键复验：lane="content"（qc_run 四项+跨源对账+正文重复段+书集格式；'
                    'scope 缺省 auto=只扫 git 变更期次，"all" 全库）或 lane="code"（全配置驱动：'
                    '读泳道根 verify.yaml 按声明装配写集白名单+checks 列表命令制；path 指泳道根、'
                    'base 指 diff 对比 ref（三点口径 base...HEAD=merge-base 对称差，'
                    '即「本次合并将给 main 带来什么」；合并闸传当前 main tip）、'
                    'write_set 指当前工单声明写集（优先于 write_allow）、'
                    'require_base=true 供合并闸——base 为空即白名单 fail-closed 判红）。'
                    '或 lane="integ"（跑泳道声明 integration.cmd 并解析三态输出契约；'
                    'apply_skip_pools=true 时按 integration.exclude_pools 声明排除池，'
                    '声明即跳过——例外分支已按宿主 260914 口径撤除）。'
                    '返回 {lane, green, red_count, checks}（integ 道为 {lane, green, ran, pass, fail, scenarios, err[, pool_exclude]}）。'),
    'parameters': {
        'type': 'object',
        'properties': {
            'lane': {'type': 'string', 'enum': ['content', 'code', 'integ']},
            'scope': {'type': 'string', 'description': 'content 道：期次（如 260627）、all（全库）或缺省 auto（只扫 git 变更期次）'},
            'path': {'type': 'string', 'description': 'code 道：泳道根目录（缺省主树）'},
            'base': {'type': 'string', 'description': 'code 道：diff 对比的 git ref（三点口径 base...HEAD；合并闸必传当前 main tip；手动调用缺省=跳过白名单并注明）'},
            'write_set': {'type': 'array', 'items': {'type': 'string'},
                          'description': 'code 道：当前工单声明写集（文件或目录前缀）；提供时优先于 verify.yaml write_allow，空列表=零写集。integ 道：票面写集——宿主 260914 口径下**不再**参与排除例外分支判定，仅用于旧口径命中面留痕（回执 pool_exclude.former_force_assets）'},
            'apply_skip_pools': {'type': 'boolean',
                                 'description': 'integ 道：true=按泳道 verify.yaml integration.exclude_pools 声明排除池（每票段由引擎显式置位，**声明即跳过**）；缺省 false/不传=恒全跑（巡检、手动、老回放形态不受声明影响，被跳池只由这一路覆盖）。资产派生仍跑，用于未知池/非法池名单点判红；旧例外分支命中面写进回执 pool_exclude.former_force_assets 但不再拦'},
            'require_base': {'type': 'boolean',
                             'description': 'code 道：合并闸调用置 true——base 为空/未传时写集白名单 fail-closed 判红（不许静默跳过）'},
            'skip_slow': {'type': 'boolean', 'description': 'code 道：跳过全部命令检查（只验白名单与装配面）'},
        },
        'required': ['lane'],
        'additionalProperties': False,
    },
}

# 引擎运行时目录：白名单 diff 一律不判（与 agent_activities.SETTLE_PATHSPEC 同口径——
# worker 代落盘结果文件等不属工单写集，判进来会把合并闸变成永久红）。
RUNTIME_PREFIXES = ('.sandbar/', '.suyou/', '.dsh/')  # .suyou=老泳道名粘滞回落（LEGACY 兼容，t260907-04）

# v2：checks 为列表命令制（无专属类型词表）——每条 {id, cmd, cwd?, timeout?}。


def _check(name, items):
    return {'check': name, 'level': 'red' if items else 'green', 'items': items}


def _sh(cmd, cwd, timeout=300, crop=2000):
    """跑命令并把输出裁到最后 crop 字节（detail 供人读）。
    逐行解析文件清单的调用必须传 crop=None：按字节裁剪会把首行裁成半截路径——
    KI-015 实证（t260902-05）：裁出的假路径「ial/token-30d.json」造成白名单
    假越界误阻断，且裁点之前的文件静默漏检。"""
    p = subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True, timeout=timeout)
    out = p.stdout + p.stderr
    return p.returncode, (out if crop is None else out[-crop:])


def _diff_names(base, root):
    """base...HEAD（三点）变更文件清单=merge-base(base,HEAD)..HEAD——即「本次合并
    将给 main 带来什么」。泳道在制期间他人并入 main 的文件不在差集里，不判越界
    （t260901-14：旧两点口径会把 main 侧文件计成泳道改动，假阳性）。
    -c core.quotepath=false：非 ASCII 文件名输出原样 UTF-8（缺省 quotepath 会输出
    八进制转义串，任何写集前缀都匹配不上，中文名文件必被误判越界）。
    crop=None：本清单逐行判写集，裁剪即假红+漏检（KI-015），不许裁。"""
    return _sh(['git', '-c', 'core.quotepath=false', 'diff', '--name-only', base + '...HEAD'], root, crop=None)


# ---------------- content 道 ----------------

def _auto_scopes():
    """从 git 变更推出受影响期次：工作区 vs HEAD，干净则看最近 1 个 commit。"""
    rc, out = _sh(['git', '-c', 'core.quotepath=false', 'diff', '--name-only', 'HEAD'], REPO, crop=None)
    files = out.splitlines() if rc == 0 and out.strip() else []
    if not files:
        rc, out = _sh(['git', '-c', 'core.quotepath=false', 'show', '--name-only', '--format=', 'HEAD'], REPO, crop=None)
        files = out.splitlines() if rc == 0 else []
    scopes = set()
    for f in files:
        m = re.search(r'(?:pipeline/output/|books/)(\d{6})', f)
        if m:
            scopes.add(m.group(1))
    return sorted(scopes)


def _content(a):
    import qc_run
    checks = []
    scope = a.get('scope') or 'auto'
    stems = None  # None=全库
    if scope == 'auto':
        stems = _auto_scopes()
        if not stems:
            return [{'check': 'auto 范围', 'level': 'green', 'items': [],
                     'note': 'git 变更未涉及任何期次内容，内容道无需复验'}]
        r = {'checks': []}
        for s in stems:
            r['checks'].extend(qc_run.run({'scope': s})['checks'])
    elif scope == 'all':
        r = qc_run.run({'scope': 'all'})
    else:
        stems = [scope]
        r = qc_run.run({'scope': scope})
    agg = {}
    for c in r['checks']:  # scope=all/多期次时 qc_run 按期次重复四项名，按名聚合
        slot = agg.setdefault(c['check'], [])
        slot.extend({'detail': str(i)[:200]} for i in c.get('items', []))
    for name, items in agg.items():
        checks.append(_check('qc_run.' + name, items))

    books_dir = REPO / 'app' / 'public' / 'data' / 'books'
    out_dir = REPO / 'pipeline' / 'output'
    qz = json.loads((REPO / 'app' / 'public' / 'data' / 'quiz.json').read_text('utf-8'))

    def _book_files():
        for bf in sorted(books_dir.glob('*.json')):
            if '-' in bf.stem:
                continue  # 古籍（zztj 等）跳过
            if stems is not None and bf.stem not in stems:
                continue
            yield bf

    # 对账①：books vs knowledge_units（章数、正文缺失）
    items = []
    for bf in _book_files():
        ku_f = out_dir / bf.stem / 'knowledge_units.json'
        if not ku_f.is_file():
            items.append({'detail': '%s 缺 knowledge_units.json' % bf.stem})
            continue
        book = json.loads(bf.read_text('utf-8'))
        kus = json.loads(ku_f.read_text('utf-8'))
        ku_list = kus.get('知识单元', []) + kus.get('时事单元', [])  # books 章节=知识单元+时事单元合流
        nb, nk = len(book.get('章节', [])), len(ku_list)
        if nb != nk:
            items.append({'detail': '%s 章数不符：books=%d vs KU=%d（知识+时事）' % (bf.stem, nb, nk)})
        for c in book.get('章节', []):
            if not c.get('正文'):
                items.append({'detail': '%s %s 正文缺失' % (bf.stem, c.get('id'))})
    checks.append(_check('对账.books_vs_ku', items))

    # 对账②：quiz 覆盖（每个有正文的讲读期次应有题）
    items = []
    for bf in _book_files():
        if bf.stem not in qz or not qz[bf.stem]:
            items.append({'detail': '%s quiz.json 无期次键或为空' % bf.stem})
    checks.append(_check('对账.quiz_覆盖', items))

    # 对账③：正文重复段扫描（append 陷阱探针）
    items = []
    for bf in _book_files():
        book = json.loads(bf.read_text('utf-8'))
        for c in book.get('章节', []):
            z = c.get('正文')
            if isinstance(z, dict):
                z = z.get('成人') or []
            seen = set()
            for p in (z or []):
                if p in seen:
                    items.append({'detail': '%s %s 正文重复段: %s…' % (bf.stem, c.get('id'), p[:30])})
                    break
                seen.add(p)
    checks.append(_check('对账.正文重复段', items))

    # 对账④：books.json 书集格式
    bj = json.loads((REPO / 'app' / 'public' / 'data' / 'books.json').read_text('utf-8'))
    items = [] if isinstance(bj.get('书集'), list) else [{'detail': 'books.json 非书集格式（build_shelf 未跑？）'}]
    checks.append(_check('对账.books_json_书集', items))
    return checks


# ---------------- code 道 ----------------

def _strip_val(vv):
    """标量值清洗（v2）：剥行内注释/整值引号（引号是语法不是内容）。"""
    vv = vv.strip()
    if vv.startswith('#'):
        return ''
    if vv and vv[0] in ('"', "'"):
        q = vv[0]
        endq = vv.find(q, 1)
        if endq != -1:
            rest = vv[endq + 1:].strip()
            if rest == '' or rest.startswith('#'):
                return vv[1:endq]
    elif ' #' in vv:
        vv = vv.split(' #', 1)[0].rstrip()
    return vv


def _parse_verify_yaml(text):
    """verify.yaml 最小 YAML 子集解析器（stdlib-only；裸 python3 无 pyyaml）。
    取舍与 agent_activities 的解析器同口径（t260901-08）：
    - tab 展开两空格；空行与 # 注释跳过；未知行 raise ValueError（调用方按契约
      fail-closed 判畸形）。
    - 结构残缺不静默过滤——verify.yaml 是道的本体声明，残缺=fail-closed，
      结构校验在 _validate_cfg。
    支持：嵌套映射（两空格缩进）、裸标量、'- ' 字符串列表、'- k: v' 列表套映射
    （v2 checks 条目，后续更深缩进行并入该条目）。"""
    root = {}
    stack = [(-1, root, None, None)]  # (indent, container, parent_container, key_in_parent)
    for raw in text.replace('\t', '  ').splitlines():
        if not raw.strip() or raw.lstrip().startswith('#'):
            continue
        indent = len(raw) - len(raw.lstrip(' '))
        line = raw.strip()
        while indent <= stack[-1][0]:
            stack.pop()
        cont, parent, key = stack[-1][1], stack[-1][2], stack[-1][3]
        if line.startswith('- '):
            if not isinstance(cont, list):
                if isinstance(cont, dict) and not cont and parent is not None:
                    cont = []
                    parent[key] = cont
                    stack[-1] = (stack[-1][0], cont, parent, key)
                else:
                    raise ValueError('列表项位置不合法: %s' % raw)
            item_raw = line[2:].strip()
            if ':' in item_raw and item_raw.split(':', 1)[0].strip() not in ('',):
                # 列表套映射（v2 checks）：'- k: v' 起条目，后续更深缩进行并入该条目
                k, _, vv = item_raw.partition(':')
                item = {k.strip(): _strip_val(vv)}
                cont.append(item)
                stack.append((indent, item, cont, None))
            else:
                cont.append(item_raw)
            continue
        if ':' not in line:
            raise ValueError('无法解析的行（畸形）: %s' % raw)
        k, _, v = line.partition(':')
        k, v = k.strip(), v.strip()
        # 行内注释剥离（v2）：引号包裹值取闭引号前；裸值遇 ' #' 截断（# 前有空格
        # 才算注释——值内紧贴 # 的形态如 url#anchor 不误伤）。
        v = _strip_val(v)
        if not k or not isinstance(cont, dict):
            raise ValueError('无法解析的行（畸形）: %s' % raw)
        if v:
            if v.startswith('[') and v.endswith(']'):
                # 行内流列表（write_allow: ["a/", "b"]）：逗号切分，token 去引号
                inner = v[1:-1].strip()
                cont[k] = ([t.strip().strip('"\'') for t in inner.split(',') if t.strip()]
                           if inner else [])
            else:
                cont[k] = v
        else:
            child = {}
            cont[k] = child
            stack.append((indent, child, cont, k))
    return root


def _validate_cfg(cfg):
    """结构校验：一切残缺/未知键 raise ValueError（畸形态 fail-closed，不静默过滤）。"""
    # t260904-18 KI-050 门③：顶层白名单随 ui_evidence 声明键同步（与契约②a
    # append 同票；不加白名单=项目一声明整道 fail-closed，自家声明挡死自家合并）。
    unknown = set(cfg) - {'schema', 'lanes', 'integration', 'ui_evidence'}
    if unknown:
        raise ValueError('未知顶层键: %s' % '、'.join(sorted(unknown)))
    ue = cfg.get('ui_evidence')
    if ue is not None:
        # 最小形态校验（三态总纲：畸形=fail-closed；缺省=green+可见 note 由
        # merge_check 3.6 出项，不在本道）。dirs 须为非空字符串列表；supply 为
        # 保留字段本版引擎不消费，不做值校验（t260904-12 乙段票面）。
        if not isinstance(ue, dict):
            raise ValueError('ui_evidence 结构不合法：须为映射（含 dirs 列表）')
        dirs = ue.get('dirs')
        if not isinstance(dirs, list) or not dirs or \
                any(not isinstance(d, str) or not d.strip() for d in dirs):
            raise ValueError('ui_evidence.dirs 须为非空字符串列表（UI 截图证据目录声明）')
    lanes = cfg.get('lanes', {})
    if not isinstance(lanes, dict):
        raise ValueError('lanes 结构不合法')
    unk = set(lanes) - {'code'}
    if unk:
        raise ValueError('未知 lanes 道: %s' % '、'.join(sorted(unk)))
    code = lanes.get('code', {})
    if not isinstance(code, dict):
        raise ValueError('lanes.code 结构不合法')
    unk = set(code) - {'write_allow', 'checks'}
    if unk:
        raise ValueError('lanes.code 未知键: %s' % '、'.join(sorted(unk)))
    wa = code.get('write_allow', [])
    if not isinstance(wa, list) or not wa or not all(isinstance(x, str) and x.strip() for x in wa):
        raise ValueError('write_allow 结构不合法（须为非空前缀/路径列表）')
    ck = code.get('checks')
    if ck is not None:
        if not isinstance(ck, list) or not ck:
            raise ValueError('checks 结构不合法（v2：须为非空列表 [{id,cmd,cwd?,timeout?}]）')
        for c in ck:
            if not isinstance(c, dict):
                raise ValueError('checks 条目结构不合法（须为映射）：%r' % (c,))
            unk = set(c) - {'id', 'cmd', 'cwd', 'timeout'}
            if unk:
                raise ValueError('checks 条目未知键: %s（支持 id/cmd/cwd/timeout）' % '、'.join(sorted(unk)))
            if not isinstance(c.get('id'), str) or not c.get('id', '').strip() \
                    or not isinstance(c.get('cmd'), str) or not c.get('cmd', '').strip():
                raise ValueError('checks 条目 id 与 cmd 均须非空字符串：%r' % (c,))
    integ = cfg.get('integration', {})
    if integ:
        if not isinstance(integ, dict):
            raise ValueError('integration 结构不合法')
        unk = set(integ) - {'cmd', 'supply', 'exclude_pools',
                            'exclude_pools_force_assets'}
        if unk:
            raise ValueError('integration 未知键: %s（v2：只认 cmd/supply/'
                             'exclude_pools/exclude_pools_force_assets）'
                             % '、'.join(sorted(unk)))
        # t260913-03 池排除声明（纯增量可选键；缺省=全跑零回归）：
        # exclude_pools=逗号分隔池名（token 形 [a-z0-9-]+；未知池由执行器资产入口
        # --print-pool-assets 单点判红）；exclude_pools_force_assets=被排除池的
        # 项目级资产路径列表（票面写集命中即强制全跑）。
        ep = integ.get('exclude_pools')
        if ep is not None:
            if not isinstance(ep, str) or \
                    not re.match(r'^[a-z0-9-]+(,[a-z0-9-]+)*$', ep.strip()):
                raise ValueError('integration.exclude_pools 结构不合法'
                                 '（逗号分隔池名，形如 engine,exclusive）')
        efa = integ.get('exclude_pools_force_assets')
        if efa is not None:
            if not isinstance(efa, list) or not efa or \
                    any(not isinstance(x, str) or not x.strip() for x in efa):
                raise ValueError('integration.exclude_pools_force_assets 须为非空'
                                 '字符串路径列表（被排除池的项目级资产面）')
        sup = integ.get('supply')
        if sup is not None:
            if not isinstance(sup, list) or not sup:
                raise ValueError('integration.supply 结构不合法（须为非空列表 [{need,cmd,cwd?,timeout?}]）')
            for e in sup:
                if not isinstance(e, dict):
                    raise ValueError('supply 条目结构不合法（须为映射）：%r' % (e,))
                unk = set(e) - {'need', 'cmd', 'cwd', 'timeout'}
                if unk:
                    raise ValueError('supply 条目未知键: %s（支持 need/cmd/cwd/timeout）' % '、'.join(sorted(unk)))
                if not isinstance(e.get('need'), str) or not e.get('need', '').strip() \
                        or not isinstance(e.get('cmd'), str) or not e.get('cmd', '').strip():
                    raise ValueError('supply 条目 need 与 cmd 均须非空字符串：%r' % (e,))
        if not isinstance(integ.get('cmd'), str) or not integ['cmd'].strip():
            raise ValueError('integration.cmd 缺失或不合法（v2：集成道声明=一条命令，'
                             '引擎 /bin/sh -c 执行，exit 非零=红；红绿判据即退出码）')


def _cfg_load(root):
    """读泳道根 verify.yaml，返回 (cfg, err)。三态：缺失=(None,None)；畸形/版本不支持=(None,红字)。"""
    f = root / 'verify.yaml'
    if not f.is_file():
        return None, None
    try:
        cfg = _parse_verify_yaml(f.read_text('utf-8'))
        if cfg.get('schema') != 'v1':  # 键缺失或值未知都拦在这（声明值 v1 ↔ 引擎全等比较）
            raise ValueError('schema 版本不支持: 声明 %r，引擎支持 v1' % cfg.get('schema'))
        _validate_cfg(cfg)
    except ValueError as e:
        return None, 'verify.yaml fail-closed（%s）: %s' % ('版本不支持' if '版本不支持' in str(e) else '畸形', e)
    return cfg, None


def _in_write_set(path, entries):
    """path 是否落在声明写集内：条目为精确文件路径或目录前缀（自动补 /）。"""
    for e in entries:
        e = e.strip()
        if not e:
            continue
        if path == e or path.startswith(e.rstrip('/') + '/'):
            return True
    return False


def _closed_note(note):
    return {'check': 'verify.yaml', 'level': 'green', 'items': [], 'note': note}


def _code(a):
    root = Path(a.get('path') or str(REPO)).resolve()
    checks = []

    cfg, err = _cfg_load(root)
    if cfg is None:
        if err:  # 畸形 / 版本不支持：fail-closed
            checks.append(_check('verify.yaml', [{'detail': err}]))
        else:  # 缺失：该道按项目声明关闭（契约缺失态，可见非静默）
            checks.append(_closed_note('verify.yaml 缺失：code 道按项目声明关闭（契约缺失态；'
                                       '集成道同理无集成测试可跑）。引擎不内置默认策略。'))
        return checks

    lane_cfg = cfg.get('lanes', {}).get('code')
    if not isinstance(lane_cfg, dict):
        checks.append(_closed_note('verify.yaml 无 lanes.code 声明：code 道关闭（缺失态）'))
        return checks

    # ①写集白名单：判据=工单 write_set（精判，可为空列表=零写集）> verify.yaml write_allow
    base = a.get('base')
    require_base = bool(a.get('require_base'))
    has_ws = 'write_set' in a and a.get('write_set') is not None
    ws = [str(x) for x in (a.get('write_set') or [])] if has_ws else []
    allow = lane_cfg.get('write_allow') or []
    if require_base and not base:
        items = [{'detail': 'base_ref 未登记（空），写集白名单 fail-closed：合并闸无法判写集边界，'
                            '先补工单 base_ref（meta.base_ref），不得静默放行'}]
        checks.append(_check('写集白名单', items))
    elif base:
        items = []
        # name-status（非 name-only）：增/改/删分开判——删除敏感路径=正确清退
        # 不红（t260903-12：merge-base 漂移后清除运行时目录的 D 被误红成「入库」）；
        # 新增/修改敏感路径才是泄漏。
        rc, out = _sh(['git', '-c', 'core.quotepath=false', 'diff',
                       '--name-status', base + '...HEAD'], root, crop=None)
        if rc != 0:
            items.append({'detail': 'git diff 失败: %s' % out[-200:]})
        else:
            if has_ws:
                judge, judge_src = ws, '工单 write_set'
            else:
                judge, judge_src = allow, 'verify.yaml write_allow（粗判据）'
            for ln in out.splitlines():
                ln = ln.strip()
                if not ln:
                    continue
                st = ln.split('	')[0][:1]
                f = ln.split('	')[-1].strip()
                if not f:
                    continue
                # 宿主令 260904 机械闸：dev-lane 工单禁写 notes/（票据/知识库账本归
                # main 侧直管）。独立于写集判定——声明了 notes/ 也拦（防自授权）；
                # D 同拦（删账=丢账：notes 是账本，不是运行时残留，不适用清退放行）。
                if f == 'notes' or f.startswith('notes/'):
                    items.append({'detail': '越界写（notes/ 禁写，宿主令 260904）：'
                                  '票据/知识库账由 main 侧（integration/宿主）直管，'
                                  '工单不得增删改 notes/——%s（%s）。'
                                  '待落账项写进结算 note，由 integration 在 main 落。' % (f, st)})
                    continue
                if f.startswith(RUNTIME_PREFIXES):
                    if st in ('A', 'M', 'T'):
                        # t260903-12 安全事件：运行时前缀以新增/修改出现在 diff
                        # =已被 commit 入库（凭据/会话泄漏通道，03d128f 式收殓裸
                        # add -A 的必红项）；D=清退，放行。
                        items.append({'detail': '敏感/运行时路径入库（必须 untrack）：' + f})
                    continue
                if not _in_write_set(f, judge):
                    items.append({'detail': '越界写: %s（判据=%s：%s）' % (f, judge_src, '、'.join(judge[:6]))})
        checks.append(_check('写集白名单', items))
    else:
        # 手动/脚本调用未传 base：跳过是中性事实不是失败，但必须可见（260821 口径收窄：
        # 合并闸经 require_base=true 走上方 fail-closed 分支，不再落此处）。
        checks.append({'check': '写集白名单', 'level': 'green', 'items': [],
                       'note': '未传 base，写集白名单未验（要验就显式传 base；合并闸须传 require_base=true）'})

    # ② 检查装配（v2 列表命令制，宿主令 t260902）：checks=[{id,cmd,cwd?,timeout?}]，
    # 全部 /bin/sh -c、exit 非零=红、并行跑。引擎零项目策略——跑什么全由
    # verify.yaml 声明（旧 shotdebug/tsc/smoke/test/deps_dir 五个专属类型退役：
    # 本质是 grep/命令，deps 护栏并入各 cmd 自带的 test -x 前置，
    # 防 npx 占位包假绿）。skip_slow=跳过全部命令检查（白名单面在①已完成）。
    ck = lane_cfg.get('checks')

    def _p(v):
        return root / str(v)

    if isinstance(ck, list) and ck:
        from concurrent.futures import ThreadPoolExecutor

        def _one(c):
            if not isinstance(c, dict):
                return _check('声明校验', [{'detail': 'checks 条目必须是映射：%r' % (c,)}])
            cid = str(c.get('id') or 'check')
            cmd = str(c.get('cmd') or '').strip()
            if not cmd:
                return _check(cid, [{'detail': '声明缺 cmd'}])
            cwd = _p(c.get('cwd') or '.')
            to = int(c.get('timeout') or 600)
            try:
                rc, out = _sh(['/bin/sh', '-c', cmd], cwd, timeout=to, crop=None)
            except subprocess.TimeoutExpired:
                return _check(cid, [{'detail': '%s 超时（%ds），进程已终态回收' % (cid, to)}])
            return _check(cid, [{'detail': 'rc=%d: %s' % (rc, out[-400:])}] if rc != 0 else [])

        if a.get('skip_slow'):
            return checks
        with ThreadPoolExecutor(max_workers=min(8, len(ck))) as ex:
            for f in [ex.submit(_one, c) for c in ck]:
                checks.append(f.result())
    elif ck is not None:
        checks.append(_check('声明校验', [{'detail': 'checks 必须是非空列表 [{id,cmd,cwd?,timeout?}]'
                                              '（v2：旧 shotdebug/tsc/smoke/test/deps_dir 键式已退役）'}]))
    return checks


def _pool_exclude_assets(root, pools, declared):
    """被排除池资产面 = 声明固定资产 ∪ 泳道执行器 --print-pool-assets 派生面（t260913-03）。

    返回 (assets, err)。派生入口缺席/超时/非零/坏 JSON = 红点名（fail-closed：例外分支
    判据不可得时不得静默放行，也不得静默少跑）。未知池名由执行器资产入口单点判红
    （独立进程读真注册表，进程内注入假表够不到）。"""
    assets = set(str(x).strip() for x in (declared or []) if str(x).strip())
    runner = Path(root) / 'integration' / 'run_scenarios.py'
    if not runner.is_file():
        return [], ('pool-exclusion asset derivation failed: the lane has no '
                    'integration/run_scenarios.py (%s) — the exemption-branch criterion '
                    'is unavailable, fail-closed' % runner)
    try:
        p = subprocess.run(['python3', str(runner), '--print-pool-assets',
                            ','.join(pools)],
                           cwd=str(root), capture_output=True, text=True, timeout=120)
    except subprocess.TimeoutExpired:
        return [], ('pool-exclusion asset derivation timed out (>120s): '
                    '--print-pool-assets %s' % ','.join(pools))
    except OSError as ex:
        return [], ('pool-exclusion asset derivation failed to spawn (%s: %s)'
                    % (type(ex).__name__, ex))
    if p.returncode != 0:
        return [], ('pool-exclusion asset derivation failed (--print-pool-assets %s, '
                    'exit=%d): %s'
                    % (','.join(pools), p.returncode,
                       ((p.stdout or '') + (p.stderr or ''))[-800:]))
    try:
        data = json.loads((p.stdout or '').strip().splitlines()[-1])
        derived = [str(x) for x in (data.get('assets') or [])]
    except (ValueError, IndexError, AttributeError):
        return [], ('pool-exclusion asset derivation output malformed (bad JSON): %s'
                    % (p.stdout or '')[-300:])
    assets.update(a for a in derived if a)
    return sorted(assets), None


def _integ_pool_exclude(root, integ_cfg, args):
    """池排除消费面（t260913-03；宿主 260914 口径变更）→ (回执 dict | None, 子进程 env | None)。

    - apply 参数缺省/False（巡检、手动、老回放形态）→ (None, None)：一个分支都不进，
      行为与加旋钮前逐字节一致（验收 B/E 的机械锁）；**巡检/手动轮由此恒全跑**；
    - apply=True 且声明在场 → 注入 SANDBAR_SCENARIO_EXCLUDE_POOLS（cmd 与基线子进程
      同 env），**声明即跳过、不再设例外分支**；
    - 资产派生失败 → 回执带 err（调用方整道红点名，不静默）。

    宿主 260914 口径（取代 t260913-03 的「碰了就得全跑」例外分支）：**每票段一律跳过
    声明池；被跳池只由项目级全量轮（巡检/手动/回放）覆盖**。原例外分支的判据是「票面
    write_set 与被排除池资产面求交」（_in_write_set 前缀语义），而写集带目录形条目
    （如 integration/）即命中整个测试目录——实测四张在跑票写集全含 integration/、
    逐票命中 77~78 项，导致排除声明对**全部**在跑票恒定失效（KI-089）。
    旧口径下的命中面仍会被算出并写进回执 `former_force_assets`（迁移期可见性），
    但不再据此放行。资产派生（`--print-pool-assets`）保留：由既定入口单点判未知池/
    池名非法，仍 fail-closed、不静默降级。
    """
    import os as _os
    if not args.get('apply_skip_pools'):
        return None, None
    integ_cfg = integ_cfg or {}
    decl = str(integ_cfg.get('exclude_pools') or '').strip()
    if not decl:
        return None, None
    pools = [p.strip() for p in decl.split(',') if p.strip()]
    declared = [str(x).strip() for x in
                (integ_cfg.get('exclude_pools_force_assets') or [])
                if str(x).strip()]
    assets, err = _pool_exclude_assets(root, pools, declared)
    if err:
        return {'err': err}, None
    ws = [str(x) for x in (args.get('write_set') or [])]
    former = sorted(a for a in assets if _in_write_set(a, ws))
    rec = {'declared': pools, 'applied': True}
    if former:
        # 可见性留痕：这些资产在旧口径下会触发全跑，现按宿主口径不再拦。
        rec['former_force_assets'] = former
    return (rec,
            dict(_os.environ, SANDBAR_SCENARIO_EXCLUDE_POOLS=decl))


# t260924-05 KI-116：integ 道整体超时**单源三级回落**（arbitrate gen1 发现 3 修正）：
# 载荷 integ_timeout_sec → env SANDBAR_INTEG_BATCH_TIMEOUT_SEC → 常量缺省 3000。
# 旧病根是「两个独立缺省值」（本处 or 5400 vs 引擎 or 3000）双读漂移，不是「读同一个
# 运维旋钮」——env 是运维契约面（独立入口 admin call + env 无载荷键也须生效，引擎
# 生产链则经载荷下发同值），单源语义=同一 env+同一缺省常量，由单测跨模块锁定。
# 载荷畸形/非正仍 fail-closed 红；env 畸形同理（不静默回落）。
INTEG_DEFAULT_TIMEOUT_SEC = 3000
INTEG_TIMEOUT_ENV = 'SANDBAR_INTEG_BATCH_TIMEOUT_SEC'
# 260927 供给段（integration.supply）**独立具名预算**：供给是「起台/装依赖」的前置面，
# 与跑者的场景预算是**两条**预算——混成一笔就会互相吃（t260927-01 实况：供给
# `stage_docker ensure --services full` ≈40min + 跑者本体 ≈47min 合计 87min，比活动超时
# 85min 还长，活动在跑者差约 2 分钟收尾时被判死）。到点/失败都返回**点名供给段**的红：
# 既不一言不发，也不伪装成「套件零信号」（那种归因会把人引到错误方向）。
# 缺省 3600s（=实测 40min 量级 + 余量）；env 可覆盖（运维契约面，同 INTEG_TIMEOUT_ENV 的
# 单源纪律：一个旋钮决定一处预算，不各自读 env）。
SUPPLY_TIMEOUT_DEFAULT_SEC = 3600
SUPPLY_TIMEOUT_ENV = 'SANDBAR_SUPPLY_TIMEOUT_SEC'


def _supply_timeout_sec():
    """供给段预算解析 → (秒, err)。缺省链尾=常量；畸形/非正=fail-closed 红（绝不静默回缺省）。"""
    raw = os.environ.get(SUPPLY_TIMEOUT_ENV)
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        return SUPPLY_TIMEOUT_DEFAULT_SEC, None
    try:
        t = int(raw)
    except (TypeError, ValueError):
        return None, ('supply-stage budget malformed (%s=%r) — fail-closed, no silent fallback '
                      'to the default' % (SUPPLY_TIMEOUT_ENV, raw))
    if t <= 0:
        return None, ('supply-stage budget must be a positive integer (%s=%d) — fail-closed'
                      % (SUPPLY_TIMEOUT_ENV, t))
    return t, None


def _integ_timeout_sec(args):
    """解析 integ 整体超时（三级回落）→ (秒, err)。缺省链尾=常量；畸形=fail-closed 红。
    err 文案按**实际来源**点名键（acceptance gen2 打回修正）：载荷路径报
    `integ_timeout_sec`、env 路径报 `SANDBAR_INTEG_BATCH_TIMEOUT_SEC`——报错源标错
    会把运维排查引向错误旋钮。"""
    src = 'integ_timeout_sec'
    raw = args.get('integ_timeout_sec')
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        src = INTEG_TIMEOUT_ENV                            # 运维契约面（独立入口）
        raw = os.environ.get(INTEG_TIMEOUT_ENV)
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        return INTEG_DEFAULT_TIMEOUT_SEC, None
    try:
        t = int(raw)
    except (TypeError, ValueError):
        return None, 'integ overall timeout malformed (%s=%r) — fail-closed, no silent fallback' % (src, raw)
    if t <= 0:
        return None, 'integ overall timeout must be a positive integer (%s=%d) — fail-closed' % (src, t)
    return t, None


#: 执行器总预算耗尽的标记行前缀（run_scenarios._budget_exhausted_exit 唯一产出口；
#: 两侧同串=契约，改一侧必改另一侧——单测跨模块锁定）。
BUDGET_SIGNAL_PREFIX = 'INTEG_BUDGET_EXHAUSTED'
#: 跑者进度件 env（260927 第二刀）：与 agent_activities.SANDBAR_INTEG_PROGRESS_ENV 和
#: run_scenarios.PROGRESS_ENV **同一串**（三方同源，单测锁定）；执行器每完成一条原子落盘，
#: 验道被自己的执行器墙打断时读它，把「已跑 N 条但无汇总」与「未产出结果」分开点名。
PROGRESS_ENV = 'SANDBAR_INTEG_PROGRESS_JSON'


def _read_runner_progress(path):
    """读跑者进度件 → {} 或已完成面（畸形/缺失 → {}，绝不抛、绝不伪造 ran=0）。

    本函数是「被打断」这一态的**唯一读点**：空 dict = 「未产出任何结果」（真·零），
    非空 = 「已跑 N 条但无汇总」（进度面可读）。两态在下游分开点名，不许混装。"""
    p = Path(str(path or ''))
    if not str(path or '').strip() or not p.is_file():
        return {}
    try:
        data = json.loads(p.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    try:
        data['ran'] = int(data.get('ran') or 0)
    except (TypeError, ValueError):
        data['ran'] = 0
    if data['ran'] <= 0 and not data.get('done'):
        return {}
    return data


def _integ_timeout_payload_given(args):
    """载荷是否显式给了执行器墙（`integ_timeout_sec` 非空白）——混版本接缝判据之一。

    为什么不用 `_integ_timeout_sec` 的回退结果判：那条链会把 env/缺省也吃进去，
    而本判据要的正是「**载荷**这一路有没有人到岗」（缺=调用方是旧活动/旧副本）。"""
    raw = (args or {}).get('integ_timeout_sec')
    return not (raw is None or (isinstance(raw, str) and not str(raw).strip()))


def _parse_budget_signal(stdout):
    """执行器「总预算耗尽」信号解析 → {} 或 {exhausted, unrun_count, unrun, line}。

    260927 必做②：套件预算耗尽必须是**独立的可见发现**，不能落成中性 ran=0，也不能
    诬成产品红（那些场景根本没验到）。执行器给三种痕迹：`FAIL [__budget__]` 汇总行、
    逐条未跑 ENV_FAIL 行、以及本标记行；结构化未跑清单优先取 INTEG_SUMMARY 的 budget
    块（同源），标记行缺 INTEG_SUMMARY 时按标记行文本兜底——**两者都缺才返回 {}**（缺
    信号=老执行器形态，本段零分支，老路径逐字节不变）。"""
    out = {}
    for ln in (stdout or '').splitlines():
        if ln.startswith(BUDGET_SIGNAL_PREFIX):
            out = {'exhausted': True, 'line': ln.strip()[:600],
                   'unrun_count': 0, 'unrun': []}
        elif ln.startswith('INTEG_SUMMARY '):
            try:
                payload = json.loads(ln[len('INTEG_SUMMARY '):])
            except (json.JSONDecodeError, ValueError):
                continue
            b = payload.get('budget') if isinstance(payload, dict) else None
            if isinstance(b, dict) and b.get('exhausted'):
                out = {'exhausted': True,
                       'line': out.get('line', ''),
                       'unrun_count': int(b.get('unrun_count') or 0),
                       'unrun': [str(x) for x in (b.get('unrun') or [])][:200],
                       'budget_sec': b.get('budget_sec')}
    return out


def _parse_reuse_counts(payload):
    """执行器汇总里的复用面 → `(reused, names_or_None, had_key)`。

    t260930-01：**additive** 读取——老执行器没有 `reused` 键时 had_key=False、
    count=0，调用方据此走与改前**逐字节相同**的路径（清单完整性仍判 ran==expected）。
    畸形值（负数/非整数/名单非列表）按 0/None 处理并保留 had_key=True：键在场却读不懂
    属执行器撒谎面，由 recount 复核与 err 文案点名，不在此处静默当「没有这个特性」。"""
    if not isinstance(payload, dict) or 'reused' not in payload:
        return 0, None, False
    raw = payload.get('reused')
    count = raw if isinstance(raw, int) and not isinstance(raw, bool) and raw > 0 else 0
    names = payload.get('reused_names')
    names = [str(x) for x in names] if isinstance(names, list) else None
    return count, names, True


def _reuse_accounted(reused, expected, header_seen):
    """全复用轮的**可交代性**判据（t260930-01，纯函数、可直测）。

    全复用轮 `ran=0` + `reused=N>0`：它之所以能算「有信号」而不是「零信号」，前提是
    这笔复用**能对得上账**——否则就是新开的静默逃逸口（拿一句 reused=N 顶掉「什么
    都没验到」）。三条件全中才算可交代，任一不中=红（由调用方落 detail_red）：
      ① `expected` 在场且 **恰等于** reused（「N==本轮在册」：不是随手报一个数）；
      ② `INTEG_REUSE` 专行在场（响亮的唯一 stdout 凭证）；
      ③ 该专行**没有被截断**（截断时 stdout 名单不全——可交代性改由汇总行的
         权威名单承担，此处不因截断判红）。
    非全复用轮（reused==0）恒 True（本判据只针对「零实跑」这个特例）。"""
    if not reused:
        return True
    if expected is None or int(expected) != int(reused):
        return False
    if not header_seen[0]:
        return False
    return True


def _track_reuse_lines(stdout, reuse_lines, header_seen):
    """跟读执行器的复用面行（t260930-01 回执取源）。

    行形：`INTEG_REUSE 复用台账绿行 N 条（同 commit 同环境指纹同宽，未实跑）：<名,名…>`
    ——按**公开行契约**取名字（全角冒号后逗号分隔；执行器把名单上限截断时行尾是
    `…（共 N 条）`，此时置 header_seen[1]=截断标记）。汇总行的 `reused_names` 是权威
    取源，本行只是 stdout 冗余面（读不到就少一份证据，不改任何判定）。"""
    for ln in (stdout or '').splitlines():
        if not ln.startswith('INTEG_REUSE '):
            continue
        header_seen[0] = True
        if '：' not in ln:
            continue
        tail = ln.split('：', 1)[1].strip()
        if '…' in tail:
            header_seen[1] = True
            tail = tail.split('…', 1)[0]
        for nm in tail.split(','):
            nm = nm.strip()
            if nm and nm not in reuse_lines:
                reuse_lines.append(nm)


def _parse_integ_run(stdout, returncode):
    """解析执行器三态输出契约（PASS [ / FAIL [ / ENV_FAIL [ + 四空格缩进尾注）
    → (ran, passed, failed, env_failed, scen, err)。

    t260924-05 KI-116：拆除「ran==0 且 stdout 含规范行且 exit==0 → 静默绿」逃逸口，
    但零信号判据**与闸判定面同源**（t260910-13 行权威口径；arbitrate 打回令修正——
    首版只数文本行曾误杀规范行协议回执）：文本结果行 / '{'·'[' 开头规范行 /
    INTEG_SUMMARY 汇总行 ran>0，任一在场=有信号、不红（绿红交闸既有判定面）；
    三者全空且 exit==0 才是「零场景信号」红（执行器空转/坏面，不冒充绿）。
    半截行（如 `PASS [x` 无闭括号）不计数不崩，随零信号面显式红。

    t260930-01：**全轮复用**是第四种合法信号（`ran=0` 但汇总声明 `reused=N>0`）——
    它同样不是静默：执行器自报了「这 N 条按台账绿行跳过」。此处的判据只做**在场判定**
    （reused>0 即算有信号），是否「可交代」（reused 与在册数/名单/专行对得上）由
    `_reuse_accounted` + 复用回执面判——本层不提前 err，否则全复用轮永远到不了闸的
    判定面（KI-116 逃逸口是「零信号静默绿」，不是「把有交代的复用当成信号」）。"""
    ran = passed = failed = env_failed = 0
    scen, cur = [], None
    has_signal_row = False
    summary_ran = 0
    summary_reused = 0
    for line in stdout.splitlines():
        s = line.strip()
        if s[:1] in ('{', '['):
            has_signal_row = True     # 规范行协议在场=信号（解析权威在闸，此处只判在场）
        elif s.startswith('INTEG_SUMMARY '):
            try:
                _pl = json.loads(s[len('INTEG_SUMMARY '):])
                summary_ran = int(_pl.get('ran') or 0)
                summary_reused = int(_pl.get('reused') or 0)
            except (json.JSONDecodeError, ValueError, AttributeError, TypeError):
                pass                  # 畸形汇总由闸 malformed 面点名，此处不判
        line = line.rstrip()
        if line.startswith('PASS ['):
            if ']' not in line:      # 半截行：不计绿不崩（KI-116 畸形输入面）
                continue
            ran += 1
            passed += 1
            cur = None
            # name 取第一个 ]（260908：场景行可带耗时尾注「 (X.Xs)」——KI-060 备料②；
            # 旧无尾注形态首 ] 即行尾 ]，向后兼容）
            scen.append({'name': line[6:line.index(']')], 'exit': 0, 'output_tail': ''})
        elif line.startswith('ENV_FAIL ['):
            # 三态协议（t260904-12 契约 ②b-1）：环境红行；畸形（缺 exit=2）沿 FAIL 惯例
            # name=整行、exit=-1 计——畸形输出不静默吞。
            m = re.match(r'ENV_FAIL \[(.+?)\] exit=(-?\d+)', line)
            if m and int(m.group(2)) == 2:
                name, exit_code = m.group(1), 2
            else:
                name, exit_code = (line if not m else line, -1)
            ran += 1
            env_failed += exit_code == 2
            failed += exit_code != 2
            cur = {'name': name, 'exit': exit_code, 'output_tail': ''}
            scen.append(cur)
        elif line.startswith('FAIL ['):
            m = re.match(r'FAIL \[(.+?)\] exit=(-?\d+)', line)
            name, exit_code = (m.group(1), int(m.group(2))) if m else (line, -1)
            ran += 1
            failed += 1
            cur = {'name': name, 'exit': exit_code, 'output_tail': ''}
            scen.append(cur)
        elif cur is not None and line.startswith('    '):
            cur['output_tail'] = (cur['output_tail'] + line + '\n')[-4000:]
    if ran == 0 and (has_signal_row or summary_ran > 0 or summary_reused > 0):
        # 信号在场（规范行协议/汇总行计数面）——恒交闸既有判定面（t260910-13
        # 行权威口径），**先于 exit≠0 判定**：真红以 cases 承载、rc≠0 与用例红面的
        # 一致性由闸自检，台账写入面也消费同一用例面——本层提前 err 会连写账路径
        # 一起跳过（arbitrate gen1 发现 1/2 修正点），不得因缺文本行或非零退出误杀。
        return ran, passed, failed, env_failed, scen, None
    if ran == 0:
        if returncode != 0:
            return ran, passed, failed, env_failed, scen, \
                ('scenario executor produced no result (exit=%s): %s'
                 % (returncode, stdout[-2000:]))
        return ran, passed, failed, env_failed, scen, \
            ('zero scenario signal (exit=0 with no PASS/FAIL/ENV_FAIL rows, no spec rows, '
             'summary ran=0) — an idle/broken executor is an explicit red, never a fake '
             'green (the KI-116 silent escape hatch is gone): %s' % stdout[-800:])
    return ran, passed, failed, env_failed, scen, None


def _integ(args):
    """集成道（薄壳化，宿主令 t260902）：执行项目声明的 integration.cmd 并解析输出契约
    （PASS/FAIL 行 + 末行 SCENARIOS ran=N pass=N fail=N）。执行与解析全天下唯此一份——
    引擎 activity 只下单（spawn 本工具）+ 翻译 JSON。红绿=退出码+契约解析，引擎零项目策略。"""
    import os as _os
    root = Path(args.get('path') or '.').resolve()
    # ---- 1② 混版本接缝（显式 WARN 进回执，绝不静默回落 3000 硬杀）---------------
    # 巡检形态（台账来源=inspection）却两个预算面**都缺**（载荷 integ_timeout_sec 与
    # env SANDBAR_INTEG_RUN_BUDGET_SEC 同时缺席）= worker/闸**混版本**（旧活动 + 新闸，
    # 或泳道里带的是旧副本）：此时执行器墙会回落缺省 3000s，恒全跑的巡检必被它判成
    # 「整体超时」——正是 t260928-01 的病象。WARN 必须上回执（不让混版本静默）。
    _warnings = []
    _run_budget_env = os.environ.get('SANDBAR_INTEG_RUN_BUDGET_SEC')
    if _ledger_source() == 'inspection' and not _integ_timeout_payload_given(args) \
            and not _run_budget_env:
        _warn = ('mixed-version seam: inspection form without any budget/exec-timeout knob '
                 '(payload integ_timeout_sec and env SANDBAR_INTEG_RUN_BUDGET_SEC both '
                 'absent) — the executor wall falls back to the %ds default, which a '
                 'full-suite inspection round will exceed; restart the worker on the '
                 'current revision (or pass the knob) instead of relying on the default'
                 % INTEG_DEFAULT_TIMEOUT_SEC)
        _warnings.append(_warn)
        sys.stderr.write('INTEG_WARN %s\n' % _warn)
        sys.stderr.flush()
    cfg, err = _cfg_load(root)
    if err:
        return {'lane': 'integ', 'green': False, 'err': err,
                'warnings': list(_warnings)}
    if cfg is None:
        return {'lane': 'integ', 'green': False,
                'err': 'verify.yaml missing: the integ lane fails closed (no declaration-level off state; '
                       'any call is judged; contract 2b)'}
    integ_cfg = cfg.get('integration') or {}
    cmd = str(integ_cfg.get('cmd') or '').strip()
    if not cmd:
        return {'lane': 'integ', 'green': False,
                'err': 'integration.cmd missing or empty = malformed, fail-closed; to express "this lane '
                       'has nothing to do", declare an always-succeeding empty command '
                       '(e.g. true) and the round is green with zero scenarios (contract 2b)'}
    # supply 供给声明（t260904-12 乙段，契约 ②a）：逐条幂等装配命令先于 integration.cmd
    # 执行；失败/超时 = 显式红点名 need，不静默继续（契约「装配失败=红点名 need」）。
    #
    # 260927 供给段预算（宿主实测校准）：供给是**独立预算的前置面**，到点/失败一律点名
    # 「供给段」，绝不让它把跑者的场景预算吃掉、也绝不落成「套件零信号」的模糊归因。
    # 预算形态：段级 SUPPLY_TO（整段上限）与逐条 timeout（单条上限）取小——任一命中都
    # 返回红并带上已耗墙钟（事后归因要能读出「供给吃掉了多少」）。
    _supply_to, _supply_err = _supply_timeout_sec()
    if _supply_err:
        return {'lane': 'integ', 'green': False, 'err': _supply_err,
                'warnings': list(_warnings)}
    _sup_t0 = time.time()
    for e in (integ_cfg.get('supply') or []):
        need, scmd = str(e.get('need')), str(e.get('cmd'))
        scwd = root / str(e.get('cwd') or '.')
        sto = int(e.get('timeout') or 900)
        _spent = time.time() - _sup_t0
        _remain = _supply_to - _spent
        if _remain <= 0:
            return {'lane': 'integ', 'green': False,
                    'err': ('%s: supply stage timed out (>%ds, elapsed %.0fs) before reaching '
                            'need=%s — supply-side red, named, not silent; the supply budget is '
                            'independent of the runner scenario budget (%s is the knob) %s'
                            % (SUPPLY_STAGE_TIMEOUT_SIG, _supply_to, _spent, need,
                               SUPPLY_TIMEOUT_ENV, SUPPLY_SIDE_SIG)),
                    'supply': {'timeout_sec': int(_supply_to), 'used_sec': round(_spent, 1),
                               'stage_timeout': True, 'need': need}}
        _item_to = min(sto, _remain)
        try:
            sp = subprocess.run(['/bin/sh', '-c', scmd], cwd=str(scwd), capture_output=True,
                                text=True, timeout=_item_to)
        except subprocess.TimeoutExpired:
            _stage_hit = _item_to < sto          # 撞的是段级预算还是单条预算
            if _stage_hit:
                return {'lane': 'integ', 'green': False, 'warnings': list(_warnings),
                        'err': ('%s: supply stage budget exhausted (need=%s, elapsed %.0fs, '
                                'cap %s=%ds) — supply-side red, named, not silent; the supply '
                                'budget is independent of the runner scenario budget %s'
                                % (SUPPLY_STAGE_TIMEOUT_SIG, need, time.time() - _sup_t0,
                                   SUPPLY_TIMEOUT_ENV, int(_supply_to), SUPPLY_SIDE_SIG)),
                        'supply': {'timeout_sec': int(_supply_to),
                                   'used_sec': round(time.time() - _sup_t0, 1),
                                   'stage_timeout': True, 'need': need}}
            # 单条 timeout（段预算没撞上）：文案与旧契约逐字同口径——dev_lane 的
            # 「供给失败不计入 tests-fault 轮次」签名就吃这句话，措辞漂了签名就漂。
            return {'lane': 'integ', 'green': False, 'warnings': list(_warnings),
                    'err': '%s: supply assembly timed out (need=%s, >%ds) — supply-side red, '
                           'named, not silent %s'
                           % (SUPPLY_TIMEOUT_SIG, need, sto, SUPPLY_SIDE_SIG),
                    'supply': {'timeout_sec': int(_supply_to),
                               'used_sec': round(time.time() - _sup_t0, 1),
                               'stage_timeout': False, 'need': need}}
        if sp.returncode != 0:
            return {'lane': 'integ', 'green': False, 'warnings': list(_warnings),
                    'err': '%s: supply assembly failed (need=%s, exit=%d): %s — supply-side '
                           'red, named, not silent %s'
                           % (SUPPLY_FAIL_SIG, need, sp.returncode,
                              ((sp.stdout or '') + (sp.stderr or ''))[-1500:], SUPPLY_SIDE_SIG),
                    'supply': {'timeout_sec': int(_supply_to),
                               'used_sec': round(time.time() - _sup_t0, 1),
                               'stage_timeout': False, 'need': need}}
    supply_used = round(time.time() - _sup_t0, 1)   # 供给墙钟（回执观测面：与跑者分别落账）
    # t260924-05 KI-116：超时由载荷显式传（_integ_timeout_sec，缺键回落同源缺省）。
    timeout, terr = _integ_timeout_sec(args)
    if terr:
        return {'lane': 'integ', 'green': False, 'err': terr}
    # ---- t260913-03 池排除（每票段专用通道；apply 缺省 False=零分支）----
    pool_exclude, cmd_env = _integ_pool_exclude(root, integ_cfg, args)
    if pool_exclude is not None and pool_exclude.get('err'):
        return {'lane': 'integ', 'green': False, 'err': pool_exclude['err'],
                'warnings': list(_warnings)}
    # 260927：执行器自己也有总预算（SANDBAR_INTEG_RUN_BUDGET_SEC，引擎侧下发）——闸的子
    # 进程截止恒晚于它（跑者自行收口），这里只把同一份预算回执给下游同源可见。
    _prog_path = os.environ.get(PROGRESS_ENV)
    _run_t0 = time.time()
    # 260927 第二刀 1①（宿主令）：执行器用 **Popen + 进程组回收**并**取回部分输出**——
    # 旧实现 subprocess.run 超时即丢 stdout，回执只剩「整体超时」一句（t260928-01：
    # ran=0/wall=3003.3s，连「跑到哪」都读不出来）。现在超时也把已产出的规范行/
    # PASS·FAIL·ENV_FAIL 行与 INTEG_BUDGET 标记解析进回执（partial=true 点明）。
    proc = None
    timed_out = False
    _out_s, _err_s, _rc = '', '', 0
    try:
        proc = subprocess.Popen(['/bin/sh', '-c', cmd], cwd=str(root),
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                text=True, env=cmd_env, start_new_session=True)
        try:
            _out_s, _err_s = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired as _te:
            timed_out = True
            _out_s = _te.output if isinstance(_te.output, str) else \
                (_te.output or b'').decode('utf-8', 'replace')
            _err_s = _te.stderr if isinstance(_te.stderr, str) else \
                (_te.stderr or b'').decode('utf-8', 'replace')
            # 进程组回收（KI-116 纪律：裸 kill 会漏 verify_lane→sh→run_scenarios→node/docker
            # 一串孙进程——它们会继续写盘/占端口，跨期孤儿累积）
            import signal as _signal
            try:
                os.killpg(os.getpgid(proc.pid), _signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                try:
                    proc.kill()
                except ProcessLookupError:
                    pass
            try:
                _more_out, _more_err = proc.communicate(timeout=30)
                _out_s = (_out_s or '') + (_more_out or '')
                _err_s = (_err_s or '') + (_more_err or '')
            except subprocess.TimeoutExpired:
                sys.stderr.write('INTEG_WARN executor pipe still open 30s after SIGKILL '
                                 '(pid=%s)\n' % getattr(proc, 'pid', '?'))
                sys.stderr.flush()
        _rc = proc.returncode if proc.returncode is not None else -9
    except OSError as e:
        return {'lane': 'integ', 'green': False,
                'err': 'executor could not start (%s: %s)' % (type(e).__name__, e),
                'supply_used_sec': supply_used,
                'runner_used_sec': round(time.time() - _run_t0, 1),
                'warnings': _warnings}

    class _ProcView:            # 既有下游按 proc.stdout/returncode 读，保持同形
        def __init__(self, out, rc):
            self.stdout = out
            self.returncode = rc

    proc = _ProcView(_out_s, _rc)
    if timed_out:
        # 260927 第二刀（宿主要求②）：被打断也要**保留已完成信息**——三重取数：
        #   ①部分 stdout 里的规范行/文本行（已完成的场景，逐条可读）；
        #   ②INTEG_BUDGET 标记/汇总（跑者自行收口过的话）；
        #   ③跑者进度件（逐条落盘，最权威的「跑到哪」）。
        # 两态分开点名：有进度=「已跑 N 条但无汇总」；无进度=「未产出任何结果」。
        prog = _read_runner_progress(_prog_path)
        _pran, _pp, _pf, _pef, _pscen, _ = _parse_integ_run(_out_s, _rc)
        n = max(int(prog.get('ran') or 0), int(_pran or 0))
        if n > 0:
            _last = prog.get('last') or (_pscen[-1].get('name') if _pscen else '?')
            tail = ('%d scenarios ran but there is no summary (last=%s) — this is NOT a '
                    'product red and NOT "0 scenarios": the executor wall (%ds) reaped an '
                    'interrupted runner; the completed face is in the progress file %s'
                    % (n, _last, timeout, _prog_path or '(not handed down)'))
        else:
            tail = ('no scenario results at all (progress file absent or empty) — this is '
                    'NOT "0 scenarios green", it is nothing verified; the executor wall (%ds) '
                    'reaped an interrupted runner; progress file=%s'
                    % (timeout, _prog_path or '(not handed down)'))
        _partials = [{'name': s.get('name', ''), 'exit': int(s.get('exit') or 0),
                      'output_tail': s.get('output_tail') or ''} for s in (_pscen or [])]
        return {'lane': 'integ', 'green': False,
                'err': 'scenario executor wall timed out (>%ds): %s' % (timeout, tail),
                'ran': n,
                'pass': max(int(prog.get('pass') or 0), int(_pp or 0)),
                'fail': max(int(prog.get('fail') or 0), int(_pf or 0)),
                'env_fail': max(int(prog.get('env_fail') or 0), int(_pef or 0)),
                'interrupted': True,
                'partial': True,          # 宿主口径命名（=interrupted 的同义键，显式可读）
                'progress': prog,
                'scenarios': _partials,   # 已完成的逐条明细（部分输出不丢）
                'budget': _parse_budget_signal(_out_s) or {},
                'stdout_tail': (_out_s or '')[-2000:],
                'supply_used_sec': supply_used,
                'runner_used_sec': round(time.time() - _run_t0, 1),
                'run_budget_sec': int(float(_run_budget_env)) if _run_budget_env else None,
                'warnings': _warnings}
    runner_used = round(time.time() - _run_t0, 1)
    # t260924-05 KI-116：解析面抽成 _parse_integ_run 纯函数（单测直调），并拆除
    # 「ran==0 且含规范行且 exit==0 → 静默绿」逃逸口（零场景信号一律显式 err）。
    ran, passed, failed, env_failed, scen, perr = \
        _parse_integ_run(proc.stdout or '', proc.returncode)
    if perr:
        return {'lane': 'integ', 'green': False, 'err': perr,
                'warnings': list(_warnings),
                'supply_used_sec': supply_used, 'runner_used_sec': runner_used}
    # 260927 总预算耗尽（执行器自行收口的形态）：**独立可见发现**——不是产品红（那些
    # 场景根本没验到），也不是「零信号」；点名已跑/未跑数量，明细在明细行与执行器汇总。
    _budget_face = _parse_budget_signal(proc.stdout or '')

    # ---------------- t260910-13：失败分类协议 + 机械归属判定 ----------------
    # 双解析：规范行（首字符 { 的 JSON 行）权威；旧文本行保留计数（兼容期观测面）。
    # 畸形规范行计红不静默（消费外部输入 fail-closed）。
    sys.path.insert(0, str(HERE.parent / 'engine'))
    import failure_protocol as fp

    lane_out = proc.stdout or ''
    case_objs, malformed = [], []
    for ln in lane_out.splitlines():
        s = ln.strip()
        if s[:1] in ('{', '['):
            parsed = fp.parse_spec_line(s)
            if parsed is None or '__malformed__' in parsed:
                malformed.append(s[:200])
            else:
                case_objs.append(parsed)
    lane_cases = [fp.normalize_case(o) for o in case_objs]
    # attempt 盖写（t260910-13 K4：单写者=引擎侧——工单 rework 代数由引擎 activity
    # 经 args 传入；0/缺省=未声明，保留发射器写的 1）
    _attempt = int(args.get('attempt') or 0)
    if _attempt > 0:
        lane_cases = [dict(c, attempt=_attempt) for c in lane_cases]
    cases_dedup, dupes = fp.dedupe_cases(lane_cases)

    executor_summary = None
    for ln in lane_out.splitlines():
        if ln.startswith('INTEG_SUMMARY '):
            try:
                executor_summary = json.loads(ln[len('INTEG_SUMMARY '):])
            except json.JSONDecodeError:
                malformed.append(('INTEG_SUMMARY 畸形：' + ln)[:200])
    # t260930-01：执行器复用了 N 条（`ran + reused == expected` 不变式的一半）。
    # **additive**：老执行器（无 reused 键）→ reuse_n=0/reuse_had_key=False，本段
    # 全部判据与回执形状与改前逐字节一致；键在场却读不懂 → 记 had_key=1、计数 0，
    # 由下面的完整性判据响亮红（不静默当「没有这个特性」）。
    reuse_n, reuse_names_summary, reuse_had_key = _parse_reuse_counts(executor_summary)
    # 260930：执行器侧的两块具名观测面（纯搬运，缺键=空，判据零改动）
    _env_red_names_summary: List[str] = []
    _known_red_face: Dict[str, Any] = {}
    if isinstance(executor_summary, dict):
        _raw_env_names = executor_summary.get('env_red_names')
        if isinstance(_raw_env_names, list):
            for _n in _raw_env_names:
                if isinstance(_n, str) and _n.strip() and _n.strip() not in _env_red_names_summary:
                    _env_red_names_summary.append(_n.strip())
        _kr_skipped = executor_summary.get('known_red_skipped')
        _kr_names = executor_summary.get('known_red_names')
        if _kr_skipped is not None or _kr_names is not None:
            try:
                _kr_n = int(_kr_skipped or 0)
            except (TypeError, ValueError):
                _kr_n = 0
            _known_red_face = {
                'skipped': _kr_n,
                'names': [str(x) for x in _kr_names if str(x).strip()]
                         if isinstance(_kr_names, list) else [],
                'note': ('未跑 ≠ 判绿：这些条目本轮没有被验证'
                         if _kr_n else ''),
            }
    reuse_parsed, reuse_header = [], [False, False]
    _track_reuse_lines(lane_out, reuse_parsed, reuse_header)
    # 全复用轮（ran=0/reused>0）凭什么算「有信号」：**这笔复用得能交代**——见
    # `_reuse_accounted`（expected 恰等于 reused + 专行在场 + 未截断）。不交代的
    # 零实跑轮照旧红（新逃逸口不许开）。
    reuse_ok = _reuse_accounted(
        reuse_n, (executor_summary or {}).get('expected'), reuse_header)

    lane_fp = fp.env_fingerprint(_env_fp_parts(root))

    # 闸重算复核（C6/C8：权威=闸重算；执行器汇总只是前置快检）+
    # 清单完整性（t260911 仲裁③：expected 在场时 ran==expected 是唯一机械不变式，
    # 自洽性挡不住条目级丢失——执行器静默丢条面在此现形）
    # t260930-01：复用条目不跑也不计 ran，故不变式升级为 **ran + reused == expected**
    # ——「清单残缺」与「复用轮冒充实跑全绿」两侧同时封死（不改写 ran 的含义：
    # ran 恒为**实跑**条数，复用单独一列）。老执行器（无 reused 键）reuse_n=0 →
    # 判据退化成改前的 ran==expected，逐字节同改前。
    recount_mismatch = None
    if executor_summary is not None and cases_dedup:
        real = fp.recount(cases_dedup)
        if (real['ran'] != executor_summary.get('ran')
                or real['pass'] != executor_summary.get('pass')
                or real['fail'] + real['not_checked']
                != (executor_summary.get('fail') or 0)
                + (executor_summary.get('not_checked') or 0)):
            recount_mismatch = ('gate recount %r does not match the executor summary %r '
                            '(a lying summary is red)' % (real, executor_summary))
        elif executor_summary.get('expected') is not None \
                and int(executor_summary['expected']) != \
                (executor_summary.get('ran') or 0) + reuse_n:
            recount_mismatch = ('manifest incomplete: ran=%s + reused=%s != registered '
                                'expected=%s (silent item loss, or a partly-reused round '
                                'passed off as a full fresh run; ledger reuse counted '
                                'separately, t260911/t260930-01)'
                                % (executor_summary.get('ran'),
                                   executor_summary.get('reused'),
                                   executor_summary['expected']))
    elif executor_summary is not None and not cases_dedup and reuse_n > 0:
        # 执行器自报复用了 N 条却**零规范行**：唯一合法解释=全轮复用（ran=0）；此时
        # 不变式仍必须自洽（expected == reused），否则是「零场景信号却自称复用」的
        # 撒谎面——explicit 红，绝不当空转绿放过。
        expected = executor_summary.get('expected')
        if expected is not None and int(expected) != reuse_n:
            recount_mismatch = ('fully-reused round inconsistent: reused=%s != expected=%s '
                                '(nothing ran and the reuse count does not account for the '
                                'whole register, t260930-01)'
                                % (executor_summary.get('reused'), expected))
        elif expected is None:
            recount_mismatch = ('executor reports reuse (reused=%s) but carries no expected '
                                'count and no case rows — unaccountable reuse is red '
                                '(t260930-01)' % executor_summary.get('reused'))

    legacy_red = (failed + env_failed) > 0
    baseline_enabled = _os.environ.get('SANDBAR_GATE_BASELINE', '1').lower() \
        not in ('0', 'off', 'false', 'no')

    # ---------------- t260922-12 结果台账：先查账后实跑（③④） ----------------
    # 台账缺席/无红名 → 本段全部零分支（answer 全空、need_baseline 原式），行为
    # 与改前逐字节一致（降级路径=今天的实跑归属）。
    ledger_mod, ledger_degraded = _ledger_module(root)
    ledger_source = _ledger_source()
    lane_head = _git_head(root)
    lane_dirty = _worktree_dirty(root) if lane_head else True
    base_ref_name = _resolve_base_ref(root, args.get('base'))
    base_sha = _git_rev_parse(root, base_ref_name)
    lane_width = executor_summary.get('concurrency') if executor_summary else None
    red_names = sorted({c['name'] for c in cases_dedup if c['status'] != 'pass'})
    (ledger_answers, ledger_hits_red,
     ledger_hits_green, ledger_ambiguous) = _ledger_consult(
        fp, ledger_mod, red_names, lane_fp.get('value'), lane_width,
        base_sha, root)

    baseline_ok, baseline_cases, baseline_err, baseline_ref, baseline_fp = \
        True, [], None, None, None
    baseline_deps_note = None
    # 先泳道后基线串行（C4）：只有泳道有红时才需要基线对照；全绿跳过=零额外成本。
    # K6①：基线强制 SANDBAR_POOL_CONC=1 是「降负载串行」，不是泳道缺省多宽池同口径。
    need_baseline = baseline_enabled and (legacy_red or any(
        c['status'] != 'pass' for c in cases_dedup))
    # t260922-12 ③④：台账已答全部红名（同红欠账/绿）→ 免基线整跑；有歧义 →
    # 基线只复跑歧义条（SANDBAR_SCENARIO_ONLY 注入，执行器 fail-closed 校验在册
    # 性，不在册=基线缺席=保守拦，绝不松绑）。无记录/指纹不等/过期/宽度不等都在
    # 歧义面里，照旧回退实跑——「查不到」永不等于「当绿」。
    baseline_skipped_by_ledger = False
    baseline_targeted = []
    if need_baseline and ledger_mod is not None and red_names:
        if not ledger_ambiguous:
            need_baseline = False
            baseline_skipped_by_ledger = True
        elif len(ledger_ambiguous) < len(red_names):
            baseline_targeted = list(ledger_ambiguous)
    # 261001：基线那一步的 env 是**重建**的（`cmd_env` + 本 extra）⇒ 执行器加在 env 里的
    # 嵌套深度（INTEG_RUN_DEPTH）必须**显式透传**，否则内层每次都从 0 起算、深度护栏永远
    # 到不了帽（实测：自递归 12 层、护栏零命中）。这是「层级嵌套跑同一个面」的判据面。
    _depth_now = str(os.environ.get('INTEG_RUN_DEPTH') or '')
    # 261001 **自指收窄护栏**（风暴根因面）：基线若把「本层正在跑的那个面」再点名一次，
    # 就等于让「自己会起闸」的场景在内层再跑一遍 —— 而基线那一层的 env 是**重建**的，
    # 所以任何基于 env 的深度计数都会在这里归零（实测：自递归 12 层、护栏零命中）。
    # 判据=本层 `SANDBAR_SCENARIO_ONLY` ∩ 基线点名集 非空 ⇒ 从点名里摘掉并具名上报
    # （摘掉=退回整跑，方向是**更宽**不是更窄：不假绿，只防递归）。
    _self_face = {x.strip() for x in (os.environ.get('SANDBAR_SCENARIO_ONLY') or '').split(',')
                  if x.strip()}
    _self_drop = sorted(_self_face & set(baseline_targeted))
    if _self_drop:
        baseline_targeted = [n for n in baseline_targeted if n not in _self_face]
        print("BASELINE_SELF_NARROW_DROP 基线点名里含本层正在跑的面（%s）——摘掉这几个名字改整跑："
              "自指收窄会让内层再跑同一个面（261001 自递归风暴根因面）" % ",".join(_self_drop),
              flush=True)
    baseline_env_extra = ({'SANDBAR_SCENARIO_ONLY': ','.join(baseline_targeted),
                           'INTEG_RUN_DEPTH': _depth_now}
                          if baseline_targeted else None)
    baseline_wall_s = None
    if need_baseline:
        _t0b = time.time()
        _rv = _run_baseline(root, cmd, args.get('base'), timeout, env=cmd_env,
                            extra_env=baseline_env_extra,
                            lane_wall=supply_used + runner_used)
        # P1 的 deps_note 是本票后加位（真函数返回 6 元组）；t260913-03 既有
        # 护栏（test_i_baseline_inherits_exclude_env）按 5 元组桩本函数——扩展
        # 不得破坏既有形状消费方（merge_check 真红实证回归），此处按长度兼容
        # 补位（短=无 deps_note 记 None），既有护栏测试零改动。
        if len(_rv) < 6:
            _rv = tuple(_rv) + (None,) * (6 - len(_rv))
        (baseline_ok, baseline_cases, baseline_err, baseline_ref, baseline_fp,
         baseline_deps_note) = _rv
        baseline_wall_s = round(time.time() - _t0b, 1)
    else:
        baseline_ref = args.get('base') or None

    if ledger_mod is not None and (cases_dedup or legacy_red):
        aff = fp.apply_affiliation_ledger(
            cases_dedup, baseline_cases, lane_fp, baseline_fp,
            baseline_ok=baseline_ok, ledger_answers=ledger_answers)
    else:
        aff = (fp.apply_affiliation(cases_dedup, baseline_cases, lane_fp,
                                    baseline_fp, baseline_ok=baseline_ok)
               if (cases_dedup or legacy_red) else None)

    # 兼容文本行红面（无规范行可判）→ fail-closed 红不猜测归属（C5 盲区明示：
    # 兼容路径无 cause/reason，违约类机械不可见，这里只保守红不归因）。
    compat_unparsed_red = legacy_red and not cases_dedup and not malformed

    protocol_mode = bool(case_objs or malformed)
    blockers = (aff or {}).get('blockers') or []
    # 执行器异常退出/汇总行缺席 = 用例集可能残缺（崩溃/被杀形态）——「没检验到
    # 却出绿结论」的闸侧 fail-open 形态，fail-closed 治理（验收走查 gen1 问题一）：
    # 协议模式要求 INTEG_SUMMARY 在场（真执行器必吐；缺席=用例集可能残缺）；
    # 汇总在场时 rc 与用例集红面须一致（rc!=0 而用例全绿 / rc=0 而用例有红 = 同为
    # 撒谎面）。注意 rc!=0 × 用例有红不是崩溃（场景级产品红与用例红一致，S3 面）。
    _real = fp.recount(cases_dedup) if cases_dedup else None
    _real_red = bool(_real and (_real['fail'] + _real['not_checked']) > 0)
    executor_crashed = (protocol_mode
                        and (executor_summary is None
                             or (proc.returncode != 0 and not _real_red)
                             or (proc.returncode == 0 and _real_red)))
    crash_note = ('executor exited abnormally (exit=%s) or the summary row is absent / '
                  'inconsistent with the case set — the case set may be incomplete, '
                  'fail-closed never returns green (protocol discipline: abnormal exit '
                  'is not green)' % proc.returncode)
    if protocol_mode:
        # 规范行模式：红绿由用例判定面决定（旧退出码被用例 status 收编——
        # 「基线红只记录不堵票」的机械面就是 record 用例不抬 green=false）；
        # 例外=执行器异常退出面（上），收编前提是用例集完整。
        green = (not blockers
                 and not malformed
                 and not recount_mismatch
                 and not dupes
                 and not executor_crashed
                 and reuse_ok)
    else:
        green = (failed == 0 and env_failed == 0 and proc.returncode == 0
                 and not recount_mismatch and not compat_unparsed_red)
    summary = None
    if cases_dedup:
        summary = fp.summarize(
            cases_dedup, executor_summary.get('wall_s') if executor_summary else None,
            executor_summary.get('concurrency') if executor_summary else None,
            executor_summary.get('pool_config') if executor_summary else None,
            env_fp=lane_fp['value'], baseline_ref=baseline_ref)
    # 260929 直修 B1（宿主令·不开票）：环境红**具名**通道（纯加性键，判据与计数零改动）。
    # 取源=**用例级权威判决面**：cases_dedup（规范行解析面，上方）经语义收紧+决策表后的
    # 逐条归属 verdicts，点名 why=`not_checked_external(...)`（即 not-checked × external，
    # 闸判 record 不拦的那一族）。**绝不**从文本行 `ENV_FAIL [...] exit=N` 反推——那条面
    # 已知与闸判决不一致（spawn 失败 -8 执行器记 env、闸按败计）。aff 缺席（无规范行
    # 可判/全绿）→ 空列表；名字只作观测面，不进任何判定。
    env_red = sorted({str(v["name"]) for v in ((aff or {}).get("verdicts") or [])
                      if isinstance(v, dict) and v.get('name')
                      and str(v.get('why') or '').startswith('not_checked_external')})
    _out = {'lane': 'integ', 'green': green,
            'ran': ran, 'pass': passed, 'fail': failed, 'env_fail': env_failed,
            'scenarios': scen, 'err': None,
            'cases': cases_dedup, 'summary': summary,
            'affiliation': aff,
            'env_red': env_red,
            # 260930 宿主令（真票 t260930-09 实况：env_fail=2 而本回执 env_red=[]）：
            # **执行器侧**的具名环境红通道（runner 的 INTEG_SUMMARY env_red_names）——
            # 纯加性观测键，判据零改动、不进任何判定：
            #   · 与 'env_red' 的分工：后者=闸的**权威**判决面（not-checked × external，
            #     B2 口径，豁免只认它）；前者=执行器自报表（exit=2 行的具名），
            #     **不是**豁免依据——引擎票面把两路都亮出来，谁是空的也如实点名。
            'env_red_names': _env_red_names_summary,
            # 同在册红豁免面（runner 汇总的 known_red_skipped/known_red_names；t260930-01
            # 「在册红不进每轮路径」）。同一加性口径：缺键/畸形 → 空块，老执行器零漂移。
            'known_red': _known_red_face,
            'baseline_ref': baseline_ref,
            'baseline': {'ok': baseline_ok, 'err': baseline_err,
                         'enabled': baseline_enabled,
                         # 260926 KI-122①「加保险」：活基线主跑**逐名答案**（{红名:
                         # red|green}；缺名=没跑到/not-checked=不算答案）。只读派生物，
                         # 不改任何判定（判据单点=failure_protocol._baseline_answer）；
                         # 只对红面取名（全绿用例对采纳无意义，回执更小）。
                         'answers': fp.baseline_answers(
                             [c for c in (cases_dedup or [])
                              if isinstance(c, dict) and c.get('status') != 'pass'],
                             baseline_cases, lane_fp, baseline_fp, baseline_ok)},
            'detail_red': ([{'malformed': m} for m in malformed]
                           + ([{'reuse_unaccounted': (
                               'executor reports reused=%s with ran=0 but the reuse is '
                               'not accounted for (expected=%s, INTEG_REUSE line '
                               'present=%s) — a fully-reused round must name its count, '
                               'the register size and print the loud line (t260930-01)'
                               % (reuse_n, (executor_summary or {}).get('expected'),
                                  reuse_header[0]))}]
                              if not reuse_ok else [])
                           + ([{'executor_crashed': crash_note}] if executor_crashed else [])
                           + ([{'recount': recount_mismatch}] if recount_mismatch else [])
                           + ([{'compat_unparsed_red': 'legacy text rows are red with no spec rows; fail-closed, '
                                         'no attribution'}]
                              if compat_unparsed_red else [])),
            'deprecation': (sorted(set(dupes)) and
                            ['duplicate spec rows (one row = one case, broken): %s'
                             % ', '.join(sorted(set(dupes)))] or [])}
    # 260927 分相墙钟（供给 / 跑者两笔分别落账，事后归因要能读出「供给吃掉了多少」）：
    # 两键恒在（additive；NaN 面用 -1 表「未跑到」而不是 0=「瞬时完成」的假值）。
    _out['supply_used_sec'] = supply_used
    _out['runner_used_sec'] = runner_used
    if _warnings:                       # 1② 混版本接缝显式 WARN（进回执，不静默）
        _out['warnings'] = list(_warnings)
    if _run_budget_env:
        try:
            _out['run_budget_sec'] = int(float(_run_budget_env))
        except (TypeError, ValueError):
            _out['run_budget_sec'] = None
    # ---- 260927 总预算耗尽：独立可见发现（不是产品红、不是零信号、不是绿）----
    if _budget_face:
        _out['budget'] = _budget_face        # 结构化未跑清单（票面/回执据此点名）
        _out['green'] = False                # 没跑完=不绿（红线：不得以截断换绿）
        _out['err'] = ('suite total budget exhausted: %d scenarios ran, %d never started — NOT a '
                       'product red (those scenarios were never verified), it is a '
                       'capacity/budget face; the unrun list is in budget.unrun and the '
                       'per-item ENV_FAIL lines | %s'
                       % (ran, int(_budget_face.get('unrun_count') or 0),
                          _budget_face.get('line') or ''))
        _out['detail_red'].append({'budget_exhausted': _out['err']})
    if pool_exclude is not None:
        # t260913-03：排除面/例外分支必须点名到消费面（红线：少跑不得静默）
        if pool_exclude.get('applied') and executor_summary is not None:
            pool_exclude['excluded_count'] = executor_summary.get('excluded_count')
            pool_exclude['excluded_pools'] = \
                executor_summary.get('excluded_pools') or []
        _out['pool_exclude'] = pool_exclude

    # ---- t260930-01 复用面回执（**additive**：老执行器无 reused 键 → 键一个不加）----
    # 仲裁读者不问执行器 stdout 就要能读出「N of M verified by ledger reuse at this
    # exact commit」；全轮复用更要一眼可辨（all_reused + 专行）。判定语义零改动：
    # 这段只读汇总/专行的观测面，绝不翻 green、不作 blocker、不进写账。
    if reuse_had_key:
        _expected_n = executor_summary.get('expected') if executor_summary else None
        _names = list(reuse_names_summary or [])
        if not _names and reuse_parsed and not reuse_header[1]:
            _names = list(reuse_parsed)          # 汇总行名单缺失时的 stdout 冗余面
        _out['reuse'] = {
            'reused': reuse_n,
            'names': _names,
            'names_capped': bool(reuse_header[1]),
            'expected': _expected_n,
            'all_reused': bool(reuse_n > 0 and _expected_n is not None
                               and reuse_n == int(_expected_n)),
            'accounted': bool(reuse_ok),
            'header_line': bool(reuse_header[0]),
            'report': 'out/integration-report-*.json (reused/reused_names; the runner '
                      'caps the INTEG_REUSE stdout name list (20) and the report JSON '
                      'carries the full list)',
            'note': ('reused scenarios were NOT executed in this round: the ledger '
                     'already held verdict=pass at the same commit + env_fp + '
                     'conc_width — reuse is counted separately from ran, never as a '
                     'fresh pass'),
        }
        if reuse_n > 0 and not reuse_header[0]:
            # 复用必须响亮：计数在场却连专行都没有=执行器自报的复用不可核（不改判定，
            # 但绝不静默——回执上点名）。
            sys.stderr.write('REUSE_WARN executor reports reused=%d but printed no '
                             'INTEG_REUSE line — the reuse claim is unreadable on '
                             'stdout (observation only; no judging change)\n' % reuse_n)
            sys.stderr.flush()
        if reuse_n > 0:
            print('REUSE %d of %s scenario(s) verified by ledger reuse at commit %s '
                  '(not executed: same commit + env_fp + width green row)'
                  % (reuse_n, _expected_n if _expected_n is not None else '?',
                     lane_head or '?'), flush=True)
        if _out['reuse']['all_reused']:
            print('REUSE_FULL_ROUND this round executed NOTHING: every one of the %d '
                  'registered scenario(s) was reused from the ledger at commit %s — a '
                  'green receipt here means "already verified at this exact tree", not '
                  '"verified again"' % (reuse_n, lane_head or '?'), flush=True)

    # ---------------- t260922-12 写账（①⑦）+ 回执面 ----------------
    # lane 行 + 基线行一次成批；记账面≠判定面——写失败不翻 green，但必须响亮
    # （ledger 面 error + details 上票面）。脏树/缺 source/缺 width/缺 commit
    # 一律不写（宁可缺行不可脏行），跳写原因点名进 ledger 面。out/ 快照（执行器
    # 报告）只作展示，判定真源只在主账（禁第二真源）。
    ledger_face = {
        'available': ledger_mod is not None, 'degraded': ledger_degraded,
        'source': ledger_source or None, 'commit': lane_head or None,
        'base': base_sha or None, 'base_ref': base_ref_name,
        'width': lane_width,
        'consulted': sorted(ledger_answers),
        'hits_red': ledger_hits_red, 'hits_green': ledger_hits_green,
        'ambiguous': ledger_ambiguous,
        'baseline_skipped_by_ledger': baseline_skipped_by_ledger,
        'baseline_targeted': baseline_targeted,
        'baseline_wall_s': baseline_wall_s,
        # P1：基线依赖软链点名文案上回执面（原 stdout 横幅，已改 stderr+此处）。
        'baseline_deps_note': baseline_deps_note,
        # width 分工（review 条件 C，写明防「记了账却永不命中=台账失效」误读）：
        # 基线行恒 conc_width=1（K6①）——对缺省宽泳道红不满足采信边界④；main
        # 覆盖主要靠巡检同宽行（每日 main 全集）与活基线权威；基线行价值在②查询
        # 与同宽采信。
        'width_semantics': ('baseline rows are conc_width=1 (K6①): they do not '
                            'satisfy trust-boundary width-equality for '
                            'default-width lane reds; main-tip coverage comes '
                            'from same-width inspection rows and the '
                            'live-baseline authority'),
    }
    if ledger_mod is not None:
        rows, skip_whys = [], []
        if cases_dedup:
            if not ledger_source:
                skip_whys.append('source missing (neither %s nor SANDBAR_TICKET_ID set)' % LEDGER_SOURCE_ENV)
            if not lane_head:
                skip_whys.append('HEAD sha could not be resolved')
            if lane_dirty:
                skip_whys.append('lane worktree is dirty (git status non-empty) — a missing row beats '
                             'a dirty row')
            if not lane_width:
                skip_whys.append('concurrency width missing (no INTEG_SUMMARY)')
        if cases_dedup and not skip_whys:
            rows += _ledger_rows_from_cases(
                cases_dedup, commit=lane_head, env_fp=lane_fp.get('value'),
                conc_width=lane_width, source=ledger_source)
        if baseline_ok and baseline_fp and baseline_cases and base_sha:
            rows += _ledger_rows_from_cases(
                baseline_cases, commit=base_sha, env_fp=baseline_fp.get('value'),
                conc_width=1, source='baseline')
        ledger_face['written'] = 0
        if rows:
            _rcpt = _ledger_write(ledger_mod, rows)
            ledger_face['written'] = _rcpt.get('written', 0)
            if _rcpt.get('rejected'):
                ledger_face['rejected'] = _rcpt['rejected'][:10]
            if _rcpt.get('error'):
                ledger_face['error'] = _rcpt['error']
        elif skip_whys:
            ledger_face['write_skipped'] = '；'.join(skip_whys)
    _out['ledger'] = ledger_face
    return _out


def _env_fp_parts(root):
    """闸侧指纹键集（与 integration/run_scenarios.py 执行器同键集同算法——
    键集选成永 diff 面=lane/基线恒不等=归属恒 unknown，K1）。键值取 root
    （泳道根或基线树根）下的协议库内容——票改协议库 → 与 main 基线合法 diff。"""
    import hashlib as _h
    import platform as _pl
    parts = {'python': _pl.python_version()}
    try:
        nv = subprocess.run(['node', '--version'], capture_output=True,
                            text=True, timeout=10)
        parts['node'] = nv.stdout.strip() if nv.returncode == 0 else 'absent'
    except Exception:
        parts['node'] = 'absent'
    h = _h.sha256()
    integ = Path(root) / 'integration'
    for f in ('lib_env.py', 'lib_result.py', 'conftest_result_protocol.py',
              'conftest.py'):
        p = integ / f
        if p.is_file():
            h.update(f.encode() + b'\0' + p.read_bytes() + b'\0')
    parts['integ_protocol_libs'] = h.hexdigest()
    return parts


def _resolve_base_ref(root, base):
    if base:
        return str(base)
    for ref in ('main', 'origin/main'):
        p = subprocess.run(['git', '-C', str(root), 'rev-parse', '--verify', ref],
                           capture_output=True, text=True, timeout=30)
        if p.returncode == 0:
            return p.stdout.strip()
    return None


def _baseline_root(_root, _ref):
    """占位：基线树指纹在 _run_baseline 内部采（临时树路径只有它知道）。"""
    return None


def _run_baseline(root, cmd, base, lane_timeout, env=None, extra_env=None,
                  lane_wall=None):
    """main 基线跑（t260910-13 机械归属）：临时 detach worktree + 同一命令 +
    SANDBAR_POOL_CONC=1（降负载串行，C4/K6①）。借鉴 prepare_workspace 先例的
    取舍清单（gen1 方案 C3）逐项落地：
    - worktree add 120s 超时；目录被占/非本仓 worktree → 基线缺席降级，不覆盖不删除；
    - 墙钟上限 SANDBAR_GATE_BASELINE_TIMEOUT_SEC（缺省 1800s），超时=降级+组回收；
    - 终态回收：finally 里 worktree remove --force（自建路径，KI-065 半径限界）
      + rmtree 兜底，正常/报错/超时/取消四路都到；
    - 依赖软链（t260922-12⑤）：建树后按 _baseline_dep_links 挂主仓共享依赖
      （旋钮 SANDBAR_GATE_BASELINE_DEPS 缺省开；跨仓守卫见彼注）——裸态路径
      仍可达（旋钮关/软链全败=基线维持裸态，not-checked 口径照旧，不假绿）；
    - 不带 supply 装配（那是泳道侧的事）：基线缺依赖 → 场景自身 not-checked，
      红名单口径只收 checked fail，不污染归属（C1）。
    extra_env：调用方追加旋钮（t260922-12 ④定点复跑注入 SANDBAR_SCENARIO_ONLY）。
    lane_wall（260927）：调用方带上的**本道已耗墙钟**（供给 + 泳道跑面）——基线墙钟上限
    由它从 lane_timeout 里扣出来，基线不越闸内截止（越了整轮验证被解析层丢弃）。
    返回 (ok, baseline_cases, err, baseline_ref, baseline_fp, deps_note)。
    deps_note=基线依赖软链点名文案（P1，仲裁 gen1：只进 stderr 闸日志+回执
    ledger 面，绝不进 stdout——工具 run 路径 stdout 只有唯一 JSON 信封，admin.py
    call 按 json.loads 整体解析，横幅先行=信封解析炸=整轮验证被解析层丢弃）。"""
    import os as _os2
    import shutil as _shutil
    import tempfile as _tempfile
    sys.path.insert(0, str(HERE.parent / 'engine'))
    import failure_protocol as fp2
    ref = _resolve_base_ref(root, base)
    if not ref:
        return False, [], '基线缺席：base ref 解析失败（main/origin/main 均不可解析）', None, None, None
    tmp = _tempfile.mkdtemp(prefix='sandbar-baseline-')
    try:
        try:
            p = subprocess.run(['git', '-C', str(root), 'worktree', 'add',
                                '--detach', tmp, ref],
                               capture_output=True, text=True, timeout=120)
        except subprocess.TimeoutExpired:
            return False, [], '基线缺席：git worktree add 超时（>120s）', ref, None, None
        if p.returncode != 0:
            return False, [], ('基线缺席：git worktree add 失败（目录已存在但非本仓 '
                               'worktree？不覆盖不删除）：%s'
                               % ((p.stderr or p.stdout or '').strip()[-400:])), ref, None, None
        base_fp = fp2.env_fingerprint(_env_fp_parts(tmp))
        # t260922-12⑤：主仓共享依赖软链（每条独立失败响亮不致命）。
        # P1（仲裁 gen1）：点名文案改走 stderr（闸日志）+ 随返回值上回执 ledger
        # 面——原先裸 print 到 stdout，在 JSON 信封前插横幅，admin.py call 的
        # json.loads 直接炸（Expecting value: line 1 column 1）→ 机械段
        # 「verify_lane integ 无有效输出（exit=0）」、整轮验证被解析层丢弃。
        deps_note = _baseline_dep_links(tmp, root)
        sys.stderr.write('BASELINE_DEPS %s\n' % deps_note)
        sys.stderr.flush()
        bl_timeout = int(_os2.environ.get('SANDBAR_GATE_BASELINE_TIMEOUT_SEC') or 1800)
        # 260927：基线是自己的**一趟**（泳道侧收口后另跑干净 worktree），它的墙钟只能
        # 从「本道整体截止 − 已耗供给 − 泳道跑面」剩下的时间里出——不 min 就会越闸
        # （基线 1800s 叠在满预算的泳道之上 = 闸内截止被越过 = 整轮验证被解析层丢弃）。
        _elapsed = float(lane_wall or 0.0)
        _remain = lane_timeout - _elapsed
        if _remain < bl_timeout:
            bl_timeout = max(1, int(_remain))
        # t260913-03：过滤开启时基线同 env（泳道/基线同口径；main 侧执行器认该 env
        # 后基线墙钟同步受益——合并前 main 版执行器无视它=恒全集，仅慢不假）
        env = dict(env if env is not None else _os2.environ, SANDBAR_POOL_CONC='1')
        # 260927 基线**不吃跑者总预算**：该预算的语义是「套件本体（泳道侧场景跑面）到点
        # 自行收口」，而基线是**另一趟**（干净 worktree 同命令）——继承同一份预算时它
        # 一开跑就「预算已耗尽」（预算按进程起始算），会把自己的每一条都点名成
        # 「未开跑/ENV_FAIL」，归属判定就吃到一份假基线（把没验到记成环境红）。
        # **无条件摘除**（不看上游 env 在不在）：调用方（活动/场景/手跑）可能带着这份
        # env 一路下来，基线必须自己免疫，而不是赌上游有没有。基线的墙钟由 bl_timeout
        # 单独界定（上面按已耗墙钟 min 过，不越闸内截止）。
        env.pop('SANDBAR_INTEG_RUN_BUDGET_SEC', None)
        if extra_env:
            env.update({str(k): str(v) for k, v in extra_env.items()})
        # 真进程组回收（验收走查 gen1 问题三：terminate→wait→kill 升级链，
        # 孙进程随组全灭——start_new_session 使子进程自成进程组）
        bp = subprocess.Popen(['/bin/sh', '-c', cmd], cwd=tmp,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              text=True, env=env, start_new_session=True)
        timed_out = False
        try:
            out, _err = bp.communicate(timeout=bl_timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            import signal as _signal
            try:
                _os2.killpg(_os2.getpgid(bp.pid), _signal.SIGTERM)
            except (ProcessLookupError, PermissionError):
                pass
            try:
                bp.communicate(timeout=30)
            except subprocess.TimeoutExpired:
                try:
                    _os2.killpg(_os2.getpgid(bp.pid), _signal.SIGKILL)
                except (ProcessLookupError, PermissionError):
                    pass
                out, _err = bp.communicate()
        if timed_out:
            return False, [], '基线缺席：整体超时（>%ds，进程组 TERM→KILL 已终态回收）' % bl_timeout, ref, base_fp, deps_note
        cases, bad = [], []
        for ln in out.splitlines():
            s = ln.strip()
            if s[:1] in ('{', '['):
                parsed = fp2.parse_spec_line(s)
                if parsed is None or '__malformed__' in parsed:
                    bad.append(s[:200])
                else:
                    cases.append(fp2.normalize_case(parsed))
        if bad:
            return False, cases, ('基线输出含畸形规范行（fail-closed 降级）：%s'
                                  % '; '.join(bad[:3])), ref, base_fp, deps_note
        return True, cases, None, ref, base_fp, deps_note
    finally:
        # 全终态回收（四路都到；自建路径，KI-065 半径限界）
        try:
            subprocess.run(['git', '-C', str(root), 'worktree', 'remove', '--force', tmp],
                           capture_output=True, text=True, timeout=120)
        except subprocess.TimeoutExpired:
            pass
        _shutil.rmtree(tmp, ignore_errors=True)


# ---------------- t260922-12 结果台账：闸侧单写者接线（①③④⑦） ----------------
# 单写者纪律：本工具是台账唯一写者——lane/巡检/基线三路都经 lane=integ 收口，
# 在此一处写账；执行器/引擎 activity 只产数据不碰账。台账库本体在
# <泳道根>/integration/scenario_ledger.py（项目侧交付件），按文件位装载；
# 缺席/坏 = 台账面降级响亮，归属回退实跑（=改前行为），绝不静默。
LEDGER_SOURCE_ENV = 'SANDBAR_INTEG_LEDGER_SOURCE'

# 基线树依赖软链名单（t260922-12⑤）：LANE_DEP_SYMLINKS（agent_activities 泳道侧
# 同名单）+ verify.yaml supply 的文件面等价两条。指向主仓共享依赖，基线树只读使用
# ——不是装依赖，是把基线从「起不来场景的裸树」拉到「能检验」的水平。
BASELINE_DEP_LINKS = (
    'app/node_modules',
    'server/engine/.venv',
    'server/ui-check/node_modules/playwright-core',
    'server/engine/bin/temporal',
)


def _git_common_dir(repo):
    """仓库 git 共享目录（worktree 与主仓同值）——同仓判定的比较键；解析失败 None。"""
    try:
        p = subprocess.run(['git', '-C', str(repo), 'rev-parse',
                            '--path-format=absolute', '--git-common-dir'],
                           capture_output=True, text=True, timeout=30)
    except (subprocess.TimeoutExpired, OSError):
        return None
    if p.returncode != 0:
        return None
    return str(Path(p.stdout.strip()).resolve())


def _baseline_dep_links(baseline_root, lane_root):
    """基线树依赖软链（t260922-12⑤；旋钮 SANDBAR_GATE_BASELINE_DEPS 缺省开）。
    取舍清单（照搬 _ensure_lane_deps 语义族，review 条件 A 补跨仓守卫）：
    - 同仓守卫（t260903-10 同族「依赖目录属引擎仓，跨仓不外链」）：基线树与泳道根
      的 git 共享目录不同仓 → 一条不挂+响亮点名；
    - 只读共享：软链指向本仓主 checkout 的共享依赖；只新增不覆盖（dst 已在跳过）；
      src 缺席跳过（新 clone/布局不同，verify_lane 的红文案照旧给红）；单条失败
      响亮不致命——软链全败=基线维持裸态，not-checked 口径照旧（不假绿、判据零
      放宽）；
    - 半径限界（KI-065）：只动本函数自建临时树内的路径，_run_baseline 的 finally
      回收连树带链全灭。
    返回一行点名文案（BASELINE_DEPS 行进 stderr 闸日志+随 _run_baseline 返回值
    上回执 ledger 面——P1：绝不走 stdout，工具 run 路径 stdout 只有唯一 JSON
    信封）。"""
    knob = os.environ.get('SANDBAR_GATE_BASELINE_DEPS', '1')
    if knob.strip().lower() in ('0', 'off', 'false', 'no'):
        return ('基线依赖软链：显式关闭（SANDBAR_GATE_BASELINE_DEPS=%s）——基线维持裸态'
                % knob)
    common_base = _git_common_dir(baseline_root)
    common_lane = _git_common_dir(lane_root)
    if not common_base or not common_lane:
        return '基线依赖软链：跳过（git common dir 解析失败）——基线维持裸态'
    if common_base != common_lane:
        return ('基线依赖软链：跳过（跨仓守卫：基线树与泳道根非同仓，不外链——'
                't260903-10 同族）——基线维持裸态')
    main_root = Path(common_base).parent
    linked, skipped, failed = [], [], []
    for rel in BASELINE_DEP_LINKS:
        src = main_root / rel
        dst = Path(baseline_root) / rel
        if not src.exists() or os.path.lexists(dst):
            skipped.append(rel)
            continue
        try:
            dst.parent.mkdir(parents=True, exist_ok=True)
            os.symlink(str(src), str(dst))
            linked.append(rel)
        except OSError as e:
            failed.append('%s(%s:%s)' % (rel, type(e).__name__, e))
    note = '基线依赖软链：%d 条挂上' % len(linked)
    if linked:
        note += '（%s）' % ','.join(linked)
    if skipped:
        note += '；跳过 %d 条（src 缺席或 dst 已在）' % len(skipped)
    if failed:
        note += '；失败=%s' % ';'.join(failed)
    return note


def _ledger_module(root):
    """按文件位装载泳道树台账库（integration/scenario_ledger.py）。
    返回 (module, None) 或 (None, reason)——缺席/坏都是降级面：不查账不写账，
    归属回退实跑（=改前行为），reason 上 ledger 回执面响亮。"""
    import importlib.util as _ilu
    p = Path(root) / 'integration' / 'scenario_ledger.py'
    if not p.is_file():
        return None, ('台账库缺席：%s（泳道树未含台账交付件）——本轮不查账不写账，'
                      '归属回退实跑' % p)
    try:
        spec = _ilu.spec_from_file_location('_scenario_ledger_lane', str(p))
        mod = _ilu.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod, None
    except Exception as e:  # noqa: BLE001 —— 装载失败=降级面，响亮不静默
        return None, ('台账库装载失败（%s: %s）——本轮不查账不写账，归属回退实跑'
                      % (type(e).__name__, e))


def _ledger_source():
    """记账来源（source 字段）：集测段=lane:<票>、巡检段=inspection（引擎
    activity 注入 env）；缺 env 回落 SANDBAR_TICKET_ID；再缺=空（写账跳过+点名
    ——来源判不了就不写，宁可缺行不可脏行）。"""
    s = (os.environ.get(LEDGER_SOURCE_ENV) or '').strip()
    if s:
        return s
    tid = (os.environ.get('SANDBAR_TICKET_ID') or '').strip()
    return ('lane:%s' % tid) if tid else ''


def _git_head(root):
    """泳道树 HEAD sha（lane 行的 commit 键）；解析失败空串（写账跳过）。"""
    try:
        p = subprocess.run(['git', '-C', str(root), 'rev-parse', 'HEAD'],
                           capture_output=True, text=True, timeout=30)
    except (subprocess.TimeoutExpired, OSError):
        return ''
    return p.stdout.strip() if p.returncode == 0 else ''


def _git_rev_parse(root, ref):
    """ref → 完整 sha（base 行的 commit 键/祖先判定的比较对象）；失败空串。
    P0（仲裁 gen1）：曾拼 `^commit`——非合法 git 修订语法（rev-parse rc=128
    「Needed a single revision」）→ base_sha 恒空 → 台账采信链全断+基线行永不
    落账且无报错。合法的「剥到 commit」形是 `^{commit}`（tag/分支/sha 通吃）。"""
    if not ref:
        return ''
    try:
        p = subprocess.run(['git', '-C', str(root), 'rev-parse', '--verify',
                            str(ref) + '^{commit}'],
                           capture_output=True, text=True, timeout=30)
    except (subprocess.TimeoutExpired, OSError):
        return ''
    return p.stdout.strip() if p.returncode == 0 else ''


def _worktree_dirty(root):
    """泳道工作区干净判（lane 行写账前提：脏树结果冒充 HEAD 状态=脏记录）。
    git 判不了（非仓/超时）→ 按脏处理（宁可缺行不可脏行）。"""
    try:
        p = subprocess.run(['git', '-C', str(root), 'status', '--porcelain'],
                           capture_output=True, text=True, timeout=30)
    except (subprocess.TimeoutExpired, OSError):
        return True
    if p.returncode != 0:
        return True
    return bool(p.stdout.strip())


def _is_ancestor(root, commit, base):
    """commit 是否 base 的祖先或相同（git merge-base --is-ancestor rc=0）。
    commit/base 缺失或 git 失败 → False（不采信，回退实跑）。"""
    if not commit or not base:
        return False
    try:
        p = subprocess.run(['git', '-C', str(root), 'merge-base', '--is-ancestor',
                            str(commit), str(base)],
                           capture_output=True, text=True, timeout=30)
    except (subprocess.TimeoutExpired, OSError):
        return False
    return p.returncode == 0


def _now_iso():
    """台账 ts：本地时区 ISO8601（冒号偏移形 +08:00——老版 fromisoformat 不认
    %z 的 +0800 无冒号形；写侧就对齐读侧解析面，failure_protocol.ledger_ts_epoch）。"""
    import datetime as _dt
    return _dt.datetime.now().astimezone().isoformat(timespec="seconds")


def _ledger_rows_from_cases(cases, commit, env_fp, conc_width, source):
    """规范行用例 → 台账行（十字段）。verdict 映射：pass→pass、fail→fail、
    not-checked→env_fail（没检验到；协议内无 skip）。ticket 仅 lane:<票> 形态
    携带票号（inspection/baseline 无票号语义，空串）。"""
    rows = []
    for c in cases:
        verdict = {'pass': 'pass', 'fail': 'fail'}.get(c.get('status'), 'env_fail')
        rows.append({
            'ts': _now_iso(),
            'commit': str(commit),
            'env_fp': str(env_fp),
            'conc_width': int(conc_width),
            'pool': str(c.get('suite') or ''),
            'scenario': str(c.get('name') or ''),
            'verdict': verdict,
            'wall_s': c.get('dur_s'),
            'source': str(source),
            'ticket': (str(source)[5:] if str(source).startswith('lane:') else ''),
        })
    return rows


def _ledger_consult(fp_mod, ledger_mod, red_names, lane_fp_value, lane_width,
                    base_sha, root):
    """红名单先查账（③）：每红名取「同指纹+同宽+检验到+祖先或相同+≤7 天」的
    最新可信行（ts 新→旧逐条过 ledger_trust，首个可信即定）。
    width 分工（review 条件 C，写明防误读）：基线行恒 conc_width=1（K6①）——对
    缺省宽泳道红不满足边界④；main 覆盖主要靠巡检同宽行（每日 main 全集）与活
    基线权威；基线行价值在②查询与同宽采信。
    返回 (answers{name:{trusted,reason,verdict,ts,source}}, hits_red, hits_green,
    ambiguous)。"""
    if ledger_mod is None or not red_names:
        return {}, [], [], []
    try:
        rows, _bad = ledger_mod.read_rows()
    except Exception as e:  # noqa: BLE001 —— 读账失败=本轮无账可查（回退实跑），响亮
        sys.stderr.write('LEDGER_WARN 主账读取失败（%s: %s）——本轮不查账，归属回退实跑\n'
                         % (type(e).__name__, e))
        # P4（仲裁 gen1）：此处必须回「全歧义」而非空歧义名单——空名单会被下游
        # 「台账已答全部红名 → 免基线」门控当「无歧义」，台账临时不可读时基线被
        # 静默跳过（违反自身「无记录/不可读=回退实跑」降级契约）。
        return {}, [], [], list(red_names)
    answers = {}
    for name in red_names:
        cands = [r for r in rows
                 if r.get('scenario') == name and r.get('env_fp') == lane_fp_value]
        cands.sort(key=lambda r: fp_mod.ledger_ts_epoch(r.get('ts')) or 0.0,
                   reverse=True)
        for r in cands:
            anc = _is_ancestor(root, r.get('commit'), base_sha)
            t = fp_mod.ledger_trust(r, lane_fp_value, anc, lane_width, time.time())
            if t.get('trusted'):
                answers[name] = dict(t, verdict=r.get('verdict'),
                                     ts=r.get('ts'), source=r.get('source'))
                break
    hits_red = sorted(n for n, a in answers.items() if a.get('verdict') == 'fail')
    hits_green = sorted(n for n, a in answers.items() if a.get('verdict') == 'pass')
    ambiguous = sorted(n for n in red_names if n not in answers)
    return answers, hits_red, hits_green, ambiguous


def _ledger_write(ledger_mod, rows):
    """写账（记账面≠判定面：失败不翻 green，但必须响亮——回执 error 上 ledger 面
    +details，仲裁与运维可见）。返回 append_records 回执（异常折成 error 回执）。"""
    try:
        return ledger_mod.append_records(rows)
    except Exception as e:  # noqa: BLE001
        return {'written': 0, 'rejected': [],
                'error': '台账写失败（%s: %s）——记账缺席不影响判定，点名待治理'
                         % (type(e).__name__, e)}


def run(args):
    lane = args['lane']
    if lane == 'integ':
        return _integ(args)
    checks = _content(args) if lane == 'content' else _code(args)
    red = sum(len(c['items']) for c in checks if c['level'] == 'red')
    return {'lane': lane, 'green': red == 0, 'red_count': red, 'checks': checks}
