#!/usr/bin/env python3
"""ticket —— 工单系统（M11 v2 模版即代码 + 260823 多项目化：真源 = Temporal workflow）。

一张工单 = 一条 Temporal workflow（id = 工单 id，单例），状态只在 workflow，
show/list 全走 client.py ticket-query/ticket-list。旧 server/dsh/tickets/ JSON 投影
目录已于 260823 删除（52 张存量全部 closed，历史查 git），老 TicketWorkflow 类与
adopt/md→json 迁移工具一并退场。

项目区分：create 必传 project（注册表 key——真源=机器级 per-key 目录
~/.sandbar/projects/<key>/project.yaml，见下「项目注册表」节；无默认值），
workflow 启动时打 ProjectKey search attribute；list 可按 project 过滤（不传=全部项目）。
project 是逻辑概念，1:N 对应目录（注册表 dirs，首个=主目录）。

立项关联（epic-linkage）：create 可传 epic（立项代号，notes/epics/<代号>.md 必须存在，
否则拒收）；合法则 workflow 打 EpicCode search attribute，可按 EpicCode 查询捞出。

状态机（status）：dispatched→settled→verified→closed / rework；
stage_state（进度维度，与 status 正交）：running | awaiting | awaiting-human | blocked。

op:
  create {workflow, project, title, body?, user_request?, spec?, role?, lane?, write_set?,
          acceptance?, deliverables?, id?, worktree?, branch?, workspace?, proposal_id?, book_path?}
      → 转发 client.py ticket-start（模板 id→workflow 类）；dev-lane 自动登记
        .lane/t<id> + 分支 lane/t<id>（未创建，仅登记路径；旧名 .worktrees 兼容读）
      → 正文=原始用户需求（user_request 逐字保留，显式优先；缺省回落 body），
        加工后派发规格独立进 spec 字段
  update {id, status?, note?, pending_add?, book_path?} → 转发 workflow update
      （stage_state 由 workflow 派生，外部不得设置——无 set-stage 红线）
  list   {status?, workflow?, role?, stage_state?, project?, epic?}
      → 结构化：{count, tickets:[{id, project, epic, title, workflow, stage, stage_state, status, role,
                                  updated, handoff_count, pending_count, worktree}]}
      （epic 过滤先过 validate_epic_code 强校验：不存在的代号明确报错，不返回空表冒充）
  show   {id}   → 全文（snapshot+meta：含 handoffs/checks/pending/log/body/results/
                  pulse 运行脉搏=RUNNING 工单的 pending activity 心跳，无心跳为 None）
  rework {id, to_stage?, note}  → 打回（signal 回目标段重跑），status=rework，log 记原因
  accept/advance/dispatch-next  → v2 已取消（workflow 过门自动推进，验收=事后看产物；
                                  blocked 重跑=client.py signal retry_qc），保留 op 报结构化错误

全部调用经 admin.log run-id 审计（tools_registry）。
"""
import json
import os
import re
import subprocess
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent

# Temporal 后端：全部 op 转发 temporal-poc/client.py（workflow update/signal/query/list）。
TEMP_POC = REPO / 'server' / 'dsh' / 'temporal-poc'
TEMP_PY = str(TEMP_POC / '.venv' / 'bin' / 'python') if (TEMP_POC / '.venv' / 'bin' / 'python').is_file() else 'python3'

# 项目注册表（sandbar M1-1 出仓）：真源=机器级 per-key 目录
# ~/.sandbar/projects/<key>/project.yaml（装载=扫 */project.yaml，与
# server/dsh/suyou-projects.ts 同一注册表、两边各自最小解析、语义同构）。
# t260904-02（KI-032 硬闸）：装载逻辑整块上收 temporal-poc/shared.py（单一真源，
# client.py ticket-start 同源锚 project_root），本文件只留薄壳委托（见下方
# 「项目注册表（薄壳委托）」节）；下面两个常量保留为兼容别名（值与真源一致）。
# env 优先级（每次调用现读）：SUYOU_PROJECTS_YAML（legacy 单文件模式，旧格式
# projects: 列表，行为与 260823 版一致）> SANDBAR_PROJECTS_DIR > ~/.sandbar/projects。
# 单条目畸形/版本不支持=该项目隔离（fail-closed 可见，不炸其他项目）；目录名必须
# 过 PROJECT_KEY_RE 白名单，条目 key 必须与目录名全等；迁移判据只认 .migrated 标记。
# 无标记且根里有内容时分三类现场（修订 v2.1）：纯种子字节子集=崩溃残留→续迁补齐；
# 与种子零交集=人工注册表→接受；部分相关不可复现=混合现场→fail-closed 抛错。
PROJECTS_YAML = REPO / 'server' / 'dsh' / 'projects.yaml'   # 兼容别名（真源=shared.PROJECTS_YAML）
PROJECT_KEY_RE = re.compile(r'^[a-z0-9][a-z0-9-]{0,40}$')   # 兼容别名（真源=shared.PROJECT_KEY_RE）

TOOL = {
    'name': 'ticket',
    'description': ('工单系统（真源=Temporal workflow）：create（派活，挂 workflow 模板，'
                    'project 必传）/update（结算/验收/收口/返工）'
                    '/list（结构化，可按 project/epic 过滤）/show/rework（打回）。'
                    'accept/advance/dispatch-next 在 v2 引擎已取消（自动推进+事后看产物）。'
                    'status 状态机 dispatched→settled→verified→closed/rework，'
                    'stage_state=running/awaiting/awaiting-human/blocked 为进度维度，两者正交。'),
    'parameters': {
        'type': 'object',
        'properties': {
            'op': {'type': 'string', 'enum': ['create', 'update', 'list', 'show', 'accept',
                                              'advance', 'dispatch-next', 'rework']},
            'id': {'type': 'string', 'description': '工单 id（update/show/accept/advance/dispatch-next/rework 必填；create 可指定否则自动生成）'},
            'project': {'type': 'string', 'description': '项目 key（机器级注册表 ~/.sandbar/projects/<key>/project.yaml；create 必传、无默认值；list 可选过滤，不传=全部项目）'},
            'epic': {'type': 'string', 'description': '立项代号（epic-linkage 机制，可选）：notes/epics/<代号>.md 必须存在否则 create 拒收；合法则 workflow 打 EpicCode search attribute，可按 EpicCode 查询捞出。list 可按 epic 过滤（先强校验，不存在的代号明确报错而非空表）'},
            'workflow': {'type': 'string', 'description': '工作流模板 id（create 必填，见 workflow list）'},
            'proposal_id': {'type': 'string', 'description': '挂提案 id（content-pipeline 用）'},
            'book_path': {'type': 'string', 'description': '内容预览定位：app/public/data/ 下相对路径（如 books/hanshu/jizhuan.json）；工单详情「预览内容」按钮按此读该书，缺省不显示预览'},
            'role': {'type': 'string', 'description': '角色（M10 五角色定稿）：developer/integration/ops/product-operation/artist（缺省取模板首段角色）'},
            'title': {'type': 'string'},
            'lane': {'type': 'string', 'description': '工作位置：主树 或 泳道路径（.lane/xxx，旧 .worktrees 兼容）；缺省取模板 lane'},
            'write_set': {'type': 'array', 'items': {'type': 'string'}, 'description': '允许写的路径白名单（glob 口径文字描述即可）'},
            'allow_empty_write_set': {'type': 'boolean', 'description': 'create 显式声明本票无文件改动（t260901-01）：空写集 + 此声明才放行建票，meta 记 no_file_changes；有文件改动请传 write_set，勿用此声明绕过白名单护栏'},
            'acceptance': {'type': 'array', 'items': {'type': 'string'}, 'description': '实例验收增项（追加到模板首段清单，A5.5）'},
            'deliverables': {'type': 'string', 'description': '交接物格式约定'},
            'user_request': {'type': 'string', 'description': '原始用户需求（用户原话逐字保留）——显式优先；缺省回落 body'},
            'spec': {'type': 'string', 'description': '加工后派发规格（独立字段，供执行参考，不覆盖正文）'},
            'body': {'type': 'string', 'description': '工单正文（向后兼容：user_request 缺省时作正文）'},
            'status': {'type': 'string', 'enum': ['dispatched', 'settled', 'verified', 'closed', 'rework']},
            'stage_state': {'type': 'string', 'enum': ['running', 'awaiting', 'awaiting-human', 'blocked']},
            'note': {'type': 'string', 'description': '备注（结算摘要/验收结论/返工原因）'},
            'pending_add': {'type': 'string', 'description': '追加一条挂起项（遗留问题，不硬改交回）'},
            'to_stage': {'type': 'string', 'description': 'rework 打回目标 stage（缺省回上一段）'},
            'worktree': {'type': 'string', 'description': 'create 显式登记泳道路径（缺省 dev-lane 自动 .lane/<id>）'},
            'branch': {'type': 'string', 'description': 'create 显式登记分支名（缺省 lane/<id>）'},
            'workspace': {'type': 'object', 'description': 'create 显式登记工作空间 {type: worktree|dir, path}（缺省按模板推导：lane=worktree→泳道，模板带 workspace:dir→/tmp/suyou-ws/<id> 隔离目录）'},
            'by': {'type': 'string', 'description': 'rework 操作人（身份注入）'},
        },
        'required': ['op'],
        'additionalProperties': False,
    },
}


# ---------- 项目注册表（薄壳委托，t260904-02 上收单一真源）----------
# 装载器真源=server/dsh/temporal-poc/shared.py「项目注册表」节：KI-032 硬闸要求
# client.py ticket-start 与本文件 create 用同一份装载器锚 project（双份必漂移，
# t260824 三次事故教训）。本节保留对外函数名与错误文案（逐字不变，wrapper 只转调），
# 其余调用方（_create/_list 等）零改动。env 语义（SUYOU_PROJECTS_YAML >
# SANDBAR_PROJECTS_DIR > ~/.sandbar/projects，每次现读）与迁移/隔离/混合现场
# 判定逻辑全部随真源走，见 shared.py 注释。


def _load_registry():
    """读注册表全量（委托 shared.load_projects_registry，语义同迁前）。"""
    return _shared().load_projects_registry()


def _assert_nonempty(projects, quarantined):
    """空注册表统一报错（委托 shared.assert_registry_nonempty，文案不变）。"""
    _shared().assert_registry_nonempty(projects, quarantined)


def _projects():
    """读项目注册表（per-key 目录模式，语义与 server/dsh/suyou-projects.ts 同构）。"""
    projects, quarantined = _load_registry()
    _assert_nonempty(projects, quarantined)
    return projects


def _project(key):
    """按 key 查注册表项目；缺失/未知一律 ValueError（无默认值）。返回 {key,name,dirs}。
    key 对应隔离条目时错误文案带目录+原因（fail-closed 可见，不静默当未知）。"""
    return _shared().lookup_project(key)


# ---------- 共用 ----------

def _wf():
    import importlib.util
    spec = importlib.util.spec_from_file_location('_wf_mod', HERE / 'workflow.py')
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_SHARED_POC = None


def _shared():
    """加载 temporal-poc/shared.py（workspace 推导/契约/模板类名映射的单一真源，
    Temporal 侧共用同一模块，两边不漂移）。shared.py 仅依赖 stdlib，可独立加载。"""
    global _SHARED_POC
    if _SHARED_POC is None:
        import importlib.util
        import sys
        spec = importlib.util.spec_from_file_location('_poc_shared', TEMP_POC / 'shared.py')
        mod = importlib.util.module_from_spec(spec)
        # 必须注册进 sys.modules：py3.9 dataclasses 处理 postponed annotations 时
        # 按 cls.__module__ 反查 sys.modules，查不到即 AttributeError（260821 实测）。
        sys.modules['_poc_shared'] = mod
        spec.loader.exec_module(mod)
        _SHARED_POC = mod
    return _SHARED_POC


def _poc(subcmd, payload):
    """spawn temporal-poc/client.py，返回解析后的回执 dict（不判 ok）。"""
    cmd = [TEMP_PY, str(TEMP_POC / 'client.py'), subcmd,
           json.dumps(payload, ensure_ascii=False)]
    try:
        proc = subprocess.run(cmd, cwd=str(REPO), capture_output=True, text=True, timeout=900)
    except Exception as e:
        raise ValueError('Temporal 调用失败（temporal server/worker 在线？'
                         'cd server/dsh/temporal-poc && ./run_server.sh + .venv/bin/python worker.py）: %s' % e)
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError:
        raise ValueError('Temporal 返回非 JSON: %s' % ((proc.stderr or proc.stdout or '')[:400]))


def _poc_ok(out):
    """从 client.py 回执取 result（业务拒绝→ValueError，错误契约不变）。"""
    if not out.get('ok'):
        raise ValueError('Temporal 拒绝: %s' % (out.get('error') or out))
    result = out.get('result')
    if isinstance(result, dict) and result.get('ok') is False:
        raise ValueError(result.get('error') or 'Temporal 拒绝该操作')
    if isinstance(result, dict):
        result = {k: v for k, v in result.items() if k != 'ok'}  # 剥内层 ok，返回形状对齐
    return result


class QueryError(ValueError):
    """工单查询失败（分级，KI-025 t260903-06）：kind 随异常存活，tools_registry.call
    的异常出口按 hasattr(e, 'kind') 把它并入回执 dict，工作台/UI 据此分流
    404（not_found）/503（transient）/410（terminal）/500（internal）。

    红线：查询失败（超时/连接/取消）绝不伪造成「工单不存在」——不存在语义只有
    client.py kind=not_found（describe 命中 NotFoundFailure）一个入水口。"""

    def __init__(self, msg, kind='internal'):
        super().__init__(msg)
        self.kind = kind


def _v2_query(tid):
    """工单查询：返回 (meta, snapshot)。

    返回 None 的唯一语义 = 工单不存在（client 回执 kind=not_found；旧引擎/非 v2
    执行同样视为「此 id 无 v2 工单」）。其余任何失败（transient 超时/连接、
    terminal 终态、internal 畸形）抛 QueryError(kind)——绝不回落成不存在
    （KI-025：t260903-02 实案，查询失败谎报不存在诱导值守误操作）。"""
    out = _poc('ticket-query', {'ticket_id': tid})
    if not out.get('ok'):
        kind = out.get('kind') if isinstance(out.get('kind'), str) and out.get('kind') else 'internal'
        if kind == 'not_found':
            return None
        raise QueryError('工单查询失败（%s）：%s' % (kind, out.get('error') or '未知错误'), kind)
    res = out.get('result') or {}
    if res.get('engine') != _shared().ENGINE_V2:
        return None
    snap = res.get('snapshot') or {}
    meta = dict(res.get('ticket') or {})
    meta['id'] = tid
    # 运行脉搏（t260825-03）：client.py 从 describe 掏的 pending activity 心跳
    # （RUNNING 时 {activity,attempt,last_heartbeat_ts,started_ts,heartbeat:{stage,gen,
    # polls,session_kb}}；非 RUNNING/无心跳 → None，前端脉搏行据此软降级）。
    meta['pulse'] = res.get('pulse')
    meta['stage_acceptance'] = snap.get('stage_acceptance') or []
    meta['stage_name'] = snap.get('stage_name') or ''
    for k in ('signatures', 'gate_runs', 'refused', 'timeline', 'results',
              'human_context', 'engine', 'workflow_class'):
        meta[k] = snap.get(k)
    return meta, snap


def _v2_cancelled(op):
    raise ValueError(
        'v2 引擎（模版即代码）工单：%s 已取消——workflow 过门自动推进，验收=事后看产物'
        '（ticket show 的 results/handoffs）；打回用 rework，blocked 重跑=Temporal signal retry_qc'
        % op)


def _base_ref(primary_dir):
    """项目主目录 HEAD 短哈希（QA A2.1：create 登记 base ref，长活泳道续作基点）。"""
    try:
        main = Path(primary_dir)
        if main.parent.name in ('.lane', '.worktrees'):
            main = main.parent.parent
        r = subprocess.run(['git', '-C', str(main), 'rev-parse', '--short', 'HEAD'],
                           capture_output=True, text=True, timeout=5)
        return r.stdout.strip() if r.returncode == 0 else ''
    except Exception:
        return ''


def _uniq_v2(tid):
    """撞 id 检查走 Temporal（一票到底；completed 的同 id 技术上可再开新 run，
    但单例语义：撞即避让）。自动短 id（t<yymmdd>-<NN>）按序号递增避让；
    显式 id 撞车加 -2/-3 后缀。"""
    def _exists(cand):
        try:
            out = _poc('ticket-query', {'ticket_id': cand})
        except ValueError:
            return False  # Temporal 不可达：ticket-start 的 AlreadyStarted 兜底
        return bool(out.get('ok'))
    m = re.match(r'^(t\d{6}-)(\d{2,})$', tid)
    if m:
        pre, n = m.group(1), int(m.group(2))
        while _exists('%s%02d' % (pre, n)):
            n += 1
        return '%s%02d' % (pre, n)
    cand, i = tid, 2
    while _exists(cand):
        cand = '%s-%d' % (tid, i)
        i += 1
    return cand


def _next_seq_v2(prefix):
    """当天短 id 自增序号（t<yymmdd>-<NN>）：扫 Temporal 全项目工单取同前缀最大序号 +1
    （工单 id 全局唯一——workflow id 就是工单 id，不分项目）。"""
    out = _poc('ticket-list', {})
    if not out.get('ok'):
        raise ValueError('Temporal 不可达，无法分配工单序号: %s' % (out.get('error') or out))
    best = 0
    pat = re.compile(r'^%s-(\d{2,})$' % re.escape(prefix))
    for r in (out.get('result') or {}).get('tickets') or []:
        m = pat.match(str(r.get('id') or ''))
        if m:
            best = max(best, int(m.group(1)))
    return best + 1


def _check_paths_under_project(proj, ws, worktree):
    """显式给的绝对路径必须落在该项目注册目录之一（防把别的项目的目录登记进来）；
    相对路径不拦（执行侧对项目主目录解析）。（t260904-02 起委托 shared 同名函数，
    client.py ticket-start 硬闸共用同一判定。）"""
    _shared().check_paths_under_project(proj, ws, worktree)


# ---------- 操作 ----------

def _create(a):
    now = int(time.time())
    proj = _project(a.get('project') or '')  # 必传，无默认值（260823 用户拍板）
    wid = a.get('workflow')
    if not wid or wid not in _shared().TEMPLATE_CLASS_NAMES:
        raise ValueError('create 需要 workflow（模板 id，可用：%s）'
                         % '、'.join(sorted(_shared().TEMPLATE_CLASS_NAMES)))
    if not a.get('title'):
        raise ValueError('create 缺必填字段: title')
    # 短 id 生成（时序可见，260820 用户要求）：缺省 t<yymmdd>-<NN>（当天自增序号，补零两位）；
    # 显式 id（a.get('id')）保留原样（UI 只显示短形）。
    if a.get('id'):
        tid = a['id']
    else:
        today = time.strftime('%y%m%d')
        tid = 't%s-%02d' % (today, _next_seq_v2('t' + today))
    tid = _uniq_v2(tid)  # 撞 id 检查走 Temporal（一票到底）
    wfmod = _wf()
    wf = wfmod.load(wfmod.DIR / (wid + '.yaml'))  # yaml=代码生成的快照，仅取 lane/workspace 推导
    stage0 = wf['stages'][0]
    role = a.get('role') or stage0['role']
    # lane/泳道字段推导+校验走 shared 单一真源（t260824-04/-10/-11 三次事故：
    # 双份推导必漂移；形态错/字段不一致在创建瞬间拒收，不再放跑到运行期才暴露）
    try:
        lane, ws, worktree, branch = _shared().derive_lane_workspace(
            tid, wf['lane'], lane=a.get('lane') or '',
            workspace=a.get('workspace'), worktree=a.get('worktree') or '',
            branch=a.get('branch') or '',
            template_workspace_dir=(wf.get('workspace') == 'dir'),
            project_root=proj['dirs'][0])
    except ValueError as e:
        raise ValueError('create 参数非法：%s' % e)
    _check_paths_under_project(proj, ws, worktree)
    # t260903-05 教训（宿主令直改不建票）：dev-lane 流程结构性写 integration/
    # （design_integration_tests 场景落 integration/<票>/ + run_scenarios.py 清单登记），
    # 建单侧自动并入防人工漏报——白名单拦得对，错在声明漏（red=5 blocked 实案）。
    write_set = list(a.get('write_set') or [])
    if wid == 'dev-lane' and 'integration/' not in write_set:
        write_set.append('integration/')
    validate_write_set_no_notes(write_set)
    tpl_acc = list(stage0.get('acceptance') or [])
    extra = [x for x in (a.get('acceptance') or []) if x not in tpl_acc]  # A5.5 实例增项
    out = _poc('ticket-start', {
        'ticket_id': tid, 'template_id': wid, 'project': proj['key'], 'title': a['title'],
        # epic 只透传：强校验单点在 client.py（validate_epic_code），错误经 _poc_ok 原样上抛
        'epic': a.get('epic') or '',
        'lane': lane, 'workspace': ws, 'worktree': worktree, 'branch': branch,
        'base_ref': _base_ref(proj['dirs'][0]) if lane == 'worktree' else '',
        'proposal_id': a.get('proposal_id') or '',
        'book_path': a.get('book_path') or '',
        'write_set': write_set,
        # t260901-01「无文件改动」显式声明：只透传，不代办——校验单点在 client.py
        # （validate_write_set_args：空写集+声明才放行，meta 记 no_file_changes）。
        'allow_empty_write_set': bool(a.get('allow_empty_write_set')),
        'acceptance_extra': extra,
        'deliverables': a.get('deliverables') or '',
        # 正文=原始用户需求（user_request 逐字保留，显式优先；缺省回落 body）
        'user_request': a.get('user_request') or '',
        'spec': a.get('spec') or '',
        'body': a.get('body') or '（无正文）',
        'created': now,
    })
    res = _poc_ok(out)
    # 每工单专属 worker（260824 A 案二轮拍板）：ticket.py 不再 spawn——console 的
    # keepalive ensure 是工单 worker 唯一生产 spawn 点（15s 内补拉；无 console 时
    # 工单在 Temporal 里待命，console 起来自动开跑，活不丢）。
    return {'id': tid, 'path': '',  # 无 JSON 投影（状态只在 workflow）
            'project': proj['key'],
            'epic': res.get('epic') or '',
            'status': 'dispatched', 'workflow': wid, 'stage': res.get('stage'),
            'stage_state': res.get('stage_state'), 'role': role,
            'worktree': worktree, 'branch': branch, 'workspace': ws,
            'temporal_adopted': True, 'engine': _shared().ENGINE_V2,
            'workflow_class': res.get('workflow_class'),
            'worker': 'console ensure 补拉（≤15s；无 console 时待命）'}


def _update(a):
    tid = a.get('id')
    if not tid:
        raise ValueError('update 需要 id')
    if not a.get('status') and a.get('book_path') is None and not a.get('pending_add') and not a.get('note'):
        raise ValueError('update 需要 status / note / pending_add / book_path（至少一个）')
    if a.get('stage_state') is not None:
        raise ValueError('stage_state 由 workflow 派生，不得外部设置（无 set-stage 红线）')
    out = _poc('ticket', {'op': 'update', 'ticket_id': tid,
                          'status': a.get('status') or '', 'note': a.get('note') or '',
                          'pending_add': a.get('pending_add') or '',
                          'book_path': a.get('book_path')})
    return _poc_ok(out)


def _list(a):
    # 纯 Temporal：client.py ticket-list（project 走 ProjectKey search attribute 过滤；
    # 不传=全部项目，admin 全局视图）。Temporal 不可达直接抛错——没有第二真源可降级。
    payload = {}
    if a.get('project'):
        _project(a['project'])  # 注册表白名单校验（未知 key 大声报错，不静默空表）
        payload['project'] = a['project']
    if a.get('epic'):
        # 立项过滤（epic-linkage 验收标准 6）：先走 validate_epic_code 强校验单点
        # （形状+notes/epics/<代号>.md 存在性），不存在的代号明确报错——
        # 绝不透传出空列表冒充「该立项下没有工单」。
        payload['epic'] = _shared().validate_epic_code(a['epic'])
    out = _poc('ticket-list', payload)
    if not out.get('ok'):
        raise ValueError('ticket-list 失败: %s' % (out.get('error') or out))
    v2_rows = (out.get('result') or {}).get('tickets') or []
    rows = [{
        'id': r.get('id'), 'project': r.get('project') or '',
        'epic': r.get('epic') or '',
        'role': r.get('role'), 'status': r.get('status'),
        'title': r.get('title'), 'workflow_id': r.get('workflow') or '',
        'proposal_id': r.get('proposal_id') or '',
        'stage': r.get('stage'), 'stage_state': r.get('stage_state') or 'awaiting',
        'engine': r.get('engine') or '',
        'handoffs': [None] * int(r.get('handoff_count') or 0),   # 只用于计数
        'pending': [None] * int(r.get('pending_count') or 0),
        'worktree': r.get('worktree') or '', 'workspace': r.get('workspace'),
        'created': r.get('created'), 'updated': r.get('updated_ts') or 0,
        'close_ts': r.get('close_ts') or 0,
    } for r in v2_rows]
    out_rows = []
    for meta in rows:
        if a.get('status') and meta.get('status') != a['status']:
            continue
        if a.get('role') and meta.get('role') != a['role']:
            continue
        if a.get('workflow') and (meta.get('workflow_id') or '') != a['workflow']:
            continue
        if a.get('stage_state') and meta.get('stage_state') != a['stage_state']:
            continue
        out_rows.append({
            'id': meta['id'], 'project': meta.get('project') or '',
            'epic': meta.get('epic') or '',
            'role': meta.get('role'), 'status': meta.get('status'),
            'title': meta.get('title'),
            'workflow': meta.get('workflow_id') or '',
            'proposal_id': meta.get('proposal_id') or '',
            'stage': meta.get('stage'), 'stage_state': meta.get('stage_state', 'awaiting'),
            'engine': meta.get('engine') or '',
            'handoff_count': len(meta.get('handoffs') or []),
            'pending_count': len(meta.get('pending') or []),
            'worktree': meta.get('worktree') or '',
            'workspace': meta.get('workspace'),
            'created': meta.get('created'),
            'updated': time.strftime('%m-%d %H:%M', time.localtime(meta.get('updated', 0))),
            'updated_ts': meta.get('updated'),
            'close_ts': meta.get('close_ts') or 0,
        })
    return {'count': len(out_rows), 'tickets': out_rows}


def _show(a):
    tid = a.get('id') or ''
    v2 = _v2_query(tid)
    if v2 is None:
        # None 的唯一来源=kind=not_found（_v2_query 契约）——这里必须带 kind 抛
        # QueryError，否则 registry 回执丢 kind，工作台 404 分流失去唯一合法判据。
        raise QueryError('工单不存在: %s（Temporal 无此 workflow）' % tid, kind='not_found')
    return v2[0]


def _accept(a):
    _v2_cancelled('逐项 accept')


def _advance(a):
    _v2_cancelled('advance')


def _dispatch_next(a):
    _v2_cancelled('dispatch-next')


def _rework(a):
    tid = a.get('id') or ''
    if not a.get('note'):
        raise ValueError('rework 需要 note（返工原因）')
    # rework=signal（回目标段重跑）；client.py 内部按引擎分流
    out = _poc('ticket', {'op': 'rework', 'ticket_id': tid,
                          'note': a.get('note') or '',
                          'to_stage': a.get('to_stage') or '',
                          'who': a.get('by') or ''})
    return _poc_ok(out)


def validate_write_set_no_notes(write_set):
    """宿主令 260904 机械闸（建单侧）：工单写集禁含 notes/——票据/知识库账本
    （KI 册/epic 立项单/决策与讨论档）由 main 侧 integration/宿主直管，工单不写。
    合并闸 verify_lane 同口径独立拦截（A/M/T/D 全拦），此处建单即拒是前置人话，
    非唯一防线——纯函数便于场景直接压测（不触 Temporal）。"""
    for e in write_set or []:
        e = str(e).strip()
        if e == 'notes' or e == 'notes/' or e.startswith('notes/'):
            raise ValueError(
                'create 参数非法：写集禁含 notes/（%s）——票据/知识库账本由 main 侧'
                '（integration/宿主）直管，工单不写 notes/（宿主令 260904 机械闸）。'
                '待落账项（KI/epic/决策档）写进结算 note，由 integration 在 main 落。' % e)


def run(args):
    op = args.get('op')
    if op == 'create':
        return _create(args)
    if op == 'update':
        return _update(args)
    if op == 'list':
        return _list(args)
    if op == 'show':
        return _show(args)
    if op == 'accept':
        return _accept(args)
    if op == 'advance':
        return _advance(args)
    if op == 'dispatch-next':
        return _dispatch_next(args)
    if op == 'rework':
        return _rework(args)
    raise ValueError('未知 op: %r' % (op,))
