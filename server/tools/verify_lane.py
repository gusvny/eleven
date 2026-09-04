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
  verify.yaml（schema v1，字段级定义见 docs/design/sandbar项目接入契约v1.md ②a），
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
     .suyou/ .dsh/ 引擎运行时目录一律不判（与 merge_check SETTLE_PATHSPEC 同口径）。
     require_base=true（合并闸口径）且 base 为空/未传 → fail-closed 红「base_ref 未登记」；
     手动调用未传 base → 跳过但 green 项 note 可见（要验就显式传 base）。
  2. checks 列表命令制（契约②a，t260903-01 对齐）：每条 {id, cmd, cwd?, timeout?}
  仅在声明在位时跑；全部并行跑（独立子进程），总时长取最长者。
"""
import json
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
sys.path.insert(0, str(HERE))

TOOL = {
    'name': 'verify_lane',
    'description': ('泳道一键复验：lane="content"（qc_run 四项+跨源对账+正文重复段+书集格式；'
                    'scope 缺省 auto=只扫 git 变更期次，"all" 全库）或 lane="code"（全配置驱动：'
                    '读泳道根 verify.yaml 按声明装配写集白名单+checks 列表命令制；path 指泳道根、'
                    'base 指 diff 对比 ref（三点口径 base...HEAD=merge-base 对称差，'
                    '即「本次合并将给 main 带来什么」；合并闸传当前 main tip）、'
                    'write_set 指当前工单声明写集（优先于 write_allow）、'
                    'require_base=true 供合并闸——base 为空即白名单 fail-closed 判红）。'
                    '返回 {lane, green, red_count, checks}。'),
    'parameters': {
        'type': 'object',
        'properties': {
            'lane': {'type': 'string', 'enum': ['content', 'code', 'integ']},
            'scope': {'type': 'string', 'description': 'content 道：期次（如 260627）、all（全库）或缺省 auto（只扫 git 变更期次）'},
            'path': {'type': 'string', 'description': 'code 道：泳道根目录（缺省主树）'},
            'base': {'type': 'string', 'description': 'code 道：diff 对比的 git ref（三点口径 base...HEAD；合并闸必传当前 main tip；手动调用缺省=跳过白名单并注明）'},
            'write_set': {'type': 'array', 'items': {'type': 'string'},
                          'description': 'code 道：当前工单声明写集（文件或目录前缀）；提供时优先于 verify.yaml write_allow，空列表=零写集'},
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
RUNTIME_PREFIXES = ('.suyou/', '.dsh/')

# v2：checks 为列表命令制（无专属类型词表）——每条 {id, cmd, cwd?, timeout?}。


def _check(name, items):
    return {'check': name, 'level': 'red' if items else 'green', 'items': items}


def _sh(cmd, cwd, timeout=300, crop=2000):
    """默认把输出裁到最后 crop 字节（仅供人类可读 detail）。**逐行解析文件清单
    的调用必须传 crop=None**：按字节裁剪会把首行裁成半截路径——KI-015 实证
    （t260902-05）：diff 2650 字节被裁出假路径「ial/token-30d.json」→ 白名单
    假越界误阻断，且裁点之前的文件静默漏检。"""
    p = subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True, timeout=timeout)
    out = p.stdout + p.stderr
    return p.returncode, (out if crop is None else out[-crop:])


def _diff_names(base, root):
    """base...HEAD（三点）变更文件清单：merge-base(base,HEAD)..HEAD——即「本次合并
    将给 main 带来什么」。泳道在制期间他人并入 main 的文件不在差集里，不判越界
    （t260901-14 假阳性根因：旧两点 base..HEAD 会把 main 侧文件计成泳道改动）。
    -c core.quotepath=false：非 ASCII 文件名输出原样 UTF-8
    （缺省 quotepath 会输出「引号+八进制转义」，转义串以 " 开头，任何写集前缀都匹配不上
    → 中文名文件必被误判越界。t260901-08 acceptance S2a 实测打回项）。
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

    参照 agent_activities._parse_bundle_pairs 的故障模式取舍（t260901-08 方案②①清单）：
    ①tab 展开两空格——带过来；②空行与 # 注释跳过——带过来；③未知行 raise ValueError
    带行内容——带过来并升格为畸形态判定主口径（调用方按契约 fail-closed）；
    ④结构残缺静默过滤——不带走（verify.yaml 是道的本体声明，残缺=fail-closed，
    校验在 _validate_cfg）；⑤段作用域隔离——带过来（先按顶层键切段）。
    支持：嵌套映射（两空格缩进）、裸 token 标量、'- ' 字符串列表、
    '- k: v' 列表套映射（v2 checks 条目，后续深缩进行并入条目）。"""
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
    unknown = set(cfg) - {'schema', 'lanes', 'integration'}
    if unknown:
        raise ValueError('未知顶层键: %s' % '、'.join(sorted(unknown)))
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
        unk = set(integ) - {'cmd', 'supply'}
        if unk:
            raise ValueError('integration 未知键: %s（v2：只认 cmd/supply）' % '、'.join(sorted(unk)))
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
        # 不红（t260903-12 实雷：amend 致 merge-base 漂移后清除 .suyou 的 D
        # 被误红成「入库」）；新增/修改敏感路径才是泄漏。
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
                # main 侧直管，t260904-01/03 的 KI 行合并冲突为直接动因）。独立于
                # 写集判定——声明了 notes/ 也拦（防自授权）；D 同拦（删账=丢账，
                # 与运行时前缀「D=清退放行」口径不同：notes 是账本不是运行时残留）。
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

    # ② 检查装配（v2 列表命令制，宿主令 t260902）：checks = [{id, cmd, cwd?, timeout?}]，
    # 全部 /bin/sh -c、exit 非零=红、并行跑。引擎零项目策略——跑什么、怎么跑全由
    # verify.yaml 声明（旧 shotdebug/tsc/smoke/test/deps_dir 五个专属类型退役：
    # shotdebug 本质是 grep、tsc/smoke/test 本质是命令、deps 在位护栏并入各 cmd 自带
    # test -x 前置，防 npx 占位包假绿——t260824-01 教训以声明形态延续）。
    # skip_slow 语义：跳过全部命令检查（白名单/残留面在①段已完成）。
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


def _integ(args):
    """集成道（薄壳化，宿主令 t260902）：执行项目声明的 integration.cmd 并解析输出契约
    （PASS/FAIL 行 + 末行 SCENARIOS ran=N pass=N fail=N）。执行与解析全天下唯此一份——
    引擎 activity 只下单（spawn 本工具）+ 翻译 JSON。红绿=退出码+契约解析，引擎零项目策略。"""
    import os as _os
    root = Path(args.get('path') or '.').resolve()
    cfg, err = _cfg_load(root)
    if err:
        return {'lane': 'integ', 'green': False, 'err': err}
    if cfg is None:
        return {'lane': 'integ', 'green': False,
                'err': 'verify.yaml 缺失：integration 道 fail-closed（本道无声明级关闭态，凡调道必判；契约②b）'}
    integ_cfg = cfg.get('integration') or {}
    cmd = str(integ_cfg.get('cmd') or '').strip()
    if not cmd:
        return {'lane': 'integ', 'green': False,
                'err': 'integration.cmd 缺失或为空 = 畸形 fail-closed；要表达「该道无事可做」，'
                       '声明恒成功空命令（如 true）得零场景绿（契约②b）'}
    # supply 供给声明（t260904-12 乙段，契约 ②a）：逐条幂等装配命令先于 integration.cmd
    # 执行；失败/超时 = 显式红点名 need，不静默继续（契约「装配失败=红点名 need」）。
    for e in (integ_cfg.get('supply') or []):
        need, scmd = str(e.get('need')), str(e.get('cmd'))
        scwd = root / str(e.get('cwd') or '.')
        sto = int(e.get('timeout') or 900)
        try:
            sp = subprocess.run(['/bin/sh', '-c', scmd], cwd=str(scwd), capture_output=True,
                                text=True, timeout=sto)
        except subprocess.TimeoutExpired:
            return {'lane': 'integ', 'green': False,
                    'err': 'supply 装配超时（need=%s，>%ds）——供给面红点名，不静默' % (need, sto)}
        if sp.returncode != 0:
            return {'lane': 'integ', 'green': False,
                    'err': 'supply 装配失败（need=%s，exit=%d）：%s——供给面红点名，不静默'
                           % (need, sp.returncode, ((sp.stdout or '') + (sp.stderr or ''))[-1500:])}
    timeout = int(_os.environ.get('SUYOU_INTEG_BATCH_TIMEOUT_SEC') or 5400)
    try:
        proc = subprocess.run(['/bin/sh', '-c', cmd], cwd=str(root), capture_output=True,
                              text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return {'lane': 'integ', 'green': False, 'err': '场景执行器整体超时（>%ds）' % timeout}
    ran = passed = failed = env_failed = 0
    scen, cur = [], None
    for line in (proc.stdout or '').splitlines():
        line = line.rstrip()
        if line.startswith('PASS ['):
            ran += 1
            passed += 1
            cur = None
            scen.append({'name': line[6:-1], 'exit': 0, 'output_tail': ''})
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
    if ran == 0 and proc.returncode != 0:
        return {'lane': 'integ', 'green': False,
                'err': '场景执行器未产出结果（exit=%s）：%s'
                       % (proc.returncode, ((proc.stdout or '') + (proc.stderr or ''))[-2000:])}
    return {'lane': 'integ', 'green': failed == 0 and env_failed == 0 and proc.returncode == 0,
            'ran': ran, 'pass': passed, 'fail': failed, 'env_fail': env_failed,
            'scenarios': scen, 'err': None}


def run(args):
    lane = args['lane']
    if lane == 'integ':
        return _integ(args)
    checks = _content(args) if lane == 'content' else _code(args)
    red = sum(len(c['items']) for c in checks if c['level'] == 'red')
    return {'lane': lane, 'green': red == 0, 'red_count': red, 'checks': checks}
