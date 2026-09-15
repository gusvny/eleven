#!/usr/bin/env python3
"""ticket —— 工单系统（M11 v2 模版即代码 + 260823 多项目化：真源 = Temporal workflow）。

一张工单 = 一条 Temporal workflow（id = 工单 id，单例），状态只在 workflow，
show/list 全走 client.py ticket-query/ticket-list。旧 server/tickets/ JSON 投影
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
  sign   {id, gate?, by(who), decision(approve|reject), note?}  → 人工审批签字（signal）
  retry_qc {id, by(who)}  → blocked 重跑请求（signal 裸串 who；不收 note——workflow
                            契约只收 who，带话走 update pending_add / ruling）
  pause/resume {id, by(who), note?}  → 段间暂停·恢复（signal；t260914-04 补正规入口
      ——KI-079：宪章「引擎操作面」教的此形式此前不存在，暂停只能回落裸 client.py
      ticket，且裸口只认 who 不认宪章教的 by＝事件历史 who 全落 op-local 无法追溯）。
      who 必填由调用方注入、纯空白在本层拒收（D1：正规入口不落 op-local——
      client.py 的 op-local 缺省只留给裸入口）；note 可选透传，上限不在此抢答
      （单点=workflow intake PAUSE_NOTE_INPUT_LIMIT）。
  ruling {id, by(who), note}  → 宿主裁决注入（signal；t260915-12 补包装层出口，
      与 schema 宣告对齐——宣告不支持的 op=对模型面撒谎，KI-079 同族）。who/note
      必填非空本层 fail-fast（D1 同族）；note 上限单点=workflow intake
      HOST_RULING_NOTE_INPUT_LIMIT；跨项目闸第二道在 workflow intake。
  accept/advance/dispatch-next  → v2 已取消（workflow 过门自动推进，验收=事后看产物；
                                  blocked 重跑=retry_qc op），保留 op 报结构化错误

全部调用经 admin.log 审计：registry.call 路径=run-id 审计（tools_registry）；
直 spawn 路径（__main__，t260910-06）=本文件自记 source=ticket.py-direct 一行 +
client.py 记 source=ticket 一行（call_id 关联）——双行形状是契约不是重复 bug。

跨项目写操作闸（t260915-12，契约详见 server/engine/README.md §11）：写 op（create/
update/rework/sign/retry_qc/pause/resume/authorize/ruling）带调用方项目身份与越权旗——
身份推导=显式 caller_project > env SANDBAR_CALLER_PROJECT > cwd 窄兜底（引擎仓树内
一律不推导，防间接调用凭空造身份）；形状非法/越权旗缺 by|reason/超上限在本层
fail-fast。declared 身份与目标票项目不符由 client.py 闸拒收（cross_project_refused）；
确需跨项目带 cross_project={by, reason 必填}（记名留痕，show 出口可对账）。undeclared
=B 策略放行+记名（翻严条件见 README §11.2）。读 op 不带闸上下文。

直 spawn 形态（KI-067 根因修复）：本文件历史上没有 CLI 入口，任何直接
`python3 ticket.py '{...}'` 都是空输出+退出 0+admin.log 无痕（260910 两实证）。
现提供 __main__：首参 JSON（含 op）→ run() → 结构化回执；任何失败**非零退出**+
{ok:false,error,kind?}，绝不空输出。
"""
import json
import os
import re
import subprocess
import time
import uuid
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent

# Temporal 后端：全部 op 转发 engine/client.py（workflow update/signal/query/list）。
TEMP_POC = REPO / 'server' / 'engine'
def _engine_py() -> str:
    """引擎 venv 解析（回落链与 engine/shared.engine_venv_python 同口径，见该函数注释）。"""
    for rel in (('server', 'engine'), ('server', 'dsh', 'temporal-poc')):
        cand = REPO.joinpath(*rel) / '.venv' / 'bin' / 'python'
        if cand.is_file() and os.access(str(cand), os.X_OK):
            return str(cand)
    return 'python3'


TEMP_PY = _engine_py()

# 项目注册表：真源=机器级 per-key 目录 ~/.sandbar/projects/<key>/project.yaml，
# 装载逻辑在 engine/shared.py 单一真源（t260904-02，KI-032：client.py ticket-start
# 与本文件 create 必须同一份装载器，双份必漂移）。下面两个常量只是兼容别名。
# env 优先级（每次调用现读）：SANDBAR_PROJECTS_YAML（legacy 单文件模式）>
# SANDBAR_PROJECTS_DIR > ~/.sandbar/projects。单条目畸形=该项目隔离（不炸其他项目）；
# 迁移判据只认 .migrated 标记，无标记按现场内容分三类判定（详见 shared.py 注释）。
PROJECTS_YAML = REPO / 'server' / 'projects.yaml'   # 兼容别名（真源=shared.PROJECTS_YAML）
PROJECT_KEY_RE = re.compile(r'^[a-z0-9][a-z0-9-]{0,40}$')   # 兼容别名（真源=shared.PROJECT_KEY_RE）

TOOL = {
    'name': 'ticket',
    'description': ('工单系统（真源=Temporal workflow）：create（派活，挂 workflow 模板，'
                    'project 必传）/update（结算/验收/收口/返工）'
                    '/list（结构化，可按 project/epic 过滤）/show/rework（打回）'
                    '/pause·resume（段间暂停·恢复，t260914-04）。'
                    'accept/advance/dispatch-next 在 v2 引擎已取消（自动推进+事后看产物）。'
                    'status 状态机 dispatched→settled→verified→closed/rework，'
                    'stage_state=running/awaiting/awaiting-human/blocked 为进度维度，两者正交。'),
    'parameters': {
        'type': 'object',
        'properties': {
            'op': {'type': 'string', 'enum': ['create', 'update', 'list', 'show', 'accept',
                                              'advance', 'dispatch-next', 'rework',
                                              'sign', 'retry_qc', 'pause', 'resume',
                                              'authorize', 'ruling']},
            'caller_project': {'type': 'string', 'description': '调用方项目身份（t260915-12 跨项目闸）：显式声明优先于 env/cwd 推导；写操作身份与目标票项目不符=拒收（cross_project_refused），确需跨项目带 cross_project 旗。引擎仓树内 cwd 不推导（防间接调用凭空造身份）'},
            'cross_project': {'type': 'object', 'properties': {'by': {'type': 'string', 'description': '谁在越权（记名）'}, 'reason': {'type': 'string', 'description': '为什么跨项目（理由必填入账）'}}, 'required': ['by', 'reason'], 'description': '越权豁免旗（记名留痕可查）：declared 身份跨项目写操作的显式放行钥匙；缺理由=拒收'},
            'cross_project_reason': {'type': 'string', 'description': '越权旗扁平形（理由必填；by 缺省取 by|who）——与 cross_project.reason 互斥'},
            'id': {'type': 'string', 'description': '工单 id（update/show/accept/advance/dispatch-next/rework/sign/retry_qc/pause/resume 必填；create 可指定否则自动生成）'},
            'project': {'type': 'string', 'description': '项目 key（机器级注册表 ~/.sandbar/projects/<key>/project.yaml；create 必传、无默认值；list 可选过滤，不传=全部项目）'},
            'epic': {'type': 'string', 'description': '立项代号（epic-linkage 机制，可选）：notes/epics/<代号>.md 必须存在否则 create 拒收；合法则 workflow 打 EpicCode search attribute，可按 EpicCode 查询捞出。list 可按 epic 过滤（先强校验，不存在的代号明确报错而非空表）'},
            'workflow': {'type': 'string', 'description': '工作流模板 id（create 必填，见 workflow list）'},
            'proposal_id': {'type': 'string', 'description': '挂提案 id（可选；原 content-pipeline 专用，260904 起仅留兼容形态）'},
            'book_path': {'type': 'string', 'description': '内容预览定位：app/public/data/ 下相对路径（如 books/hanshu/jizhuan.json）；工单详情「预览内容」按钮按此读该书，缺省不显示预览'},
            'role': {'type': 'string', 'description': '角色（M10 五角色定稿）：developer/integration/ops/product-operation/artist（缺省取模板首段角色）'},
            'title': {'type': 'string'},
            'lane': {'type': 'string', 'description': '工作位置：主树 或 泳道路径（.lane/xxx，旧 .worktrees 兼容）；缺省取模板 lane'},
            'write_set': {'type': 'array', 'items': {'type': 'string'}, 'description': '允许写的路径白名单（glob 口径文字描述即可）'},
            'refs': {'type': 'array', 'items': {'type': 'string'}, 'description': '票面引用的背景文件清单（仓库相对路径；t260904-18 门①：必须已提交且干净 HEAD 态，未提交/带脏改=拒建并点名文件；缺省不校验）'},
            'allow_empty_write_set': {'type': 'boolean', 'description': 'create 显式声明本票无文件改动（t260901-01）：空写集 + 此声明才放行建票，meta 记 no_file_changes；有文件改动请传 write_set，勿用此声明绕过白名单护栏'},
            'acceptance': {'type': 'array', 'items': {'type': 'string'}, 'description': '实例验收增项（追加到模板首段清单，A5.5）'},
            'deliverables': {'type': 'string', 'description': '交接物格式约定'},
            'user_request': {'type': 'string', 'description': '原始用户需求（用户原话逐字保留）——显式优先；缺省回落 body'},
            'spec': {'type': 'string', 'description': '加工后派发规格（独立字段，供执行参考，不覆盖正文）'},
            'body': {'type': 'string', 'description': '工单正文（向后兼容：user_request 缺省时作正文）'},
            'status': {'type': 'string', 'enum': ['dispatched', 'settled', 'verified', 'closed', 'rework']},
            'stage_state': {'type': 'string', 'enum': ['running', 'awaiting', 'awaiting-human', 'blocked']},
            'note': {'type': 'string', 'description': '备注（结算摘要/验收结论/返工原因；pause/resume 为可选理由，上限由 workflow intake 把关）'},
            'pending_add': {'type': 'string', 'description': '追加一条挂起项（遗留问题，不硬改交回）'},
            'to_stage': {'type': 'string', 'description': 'rework 打回目标 stage（缺省回上一段）'},
            'worktree': {'type': 'string', 'description': 'create 显式登记泳道路径（缺省 dev-lane 自动 .lane/<id>）'},
            'branch': {'type': 'string', 'description': 'create 显式登记分支名（缺省 lane/<id>）'},
            'workspace': {'type': 'object', 'description': 'create 显式登记工作空间 {type: worktree|dir, path}（缺省按模板推导：lane=worktree→泳道，模板带 workspace:dir→/tmp/sandbar-ws/<id> 隔离目录（老 base 粘滞））'},
            'by': {'type': 'string', 'description': 'rework/sign/retry_qc/pause/resume 操作人（身份注入，who 语义由调用方负责；等价别名 who 也收；pause/resume 必填非空——正规入口不落 op-local）'},
            'who': {'type': 'string', 'description': '操作人别名（=by，信号语义名；rework/sign/retry_qc/pause/resume 收）'},
            'gate': {'type': 'string', 'description': 'sign：审批门标识（可选，缺省空串透传）'},
            'decision': {'type': 'string', 'enum': ['approve', 'reject'], 'description': 'sign：审批决定（缺省 approve=放行推进；reject=打回）'},
        },
        'required': ['op'],
        'additionalProperties': False,
    },
}


# ---------- 项目注册表（薄壳委托，t260904-02 上收单一真源） ----------
# 真源=engine/shared.py：KI-032 要求 client.py ticket-start 与本文件 create 用
# 同一份装载器（双份必漂移，t260824 三次事故）。本节保留对外函数名与错误文案
# （逐字不变，wrapper 只转调）；env 语义与迁移/隔离判定全部随真源走。


def _load_registry():
    """读注册表全量（委托 shared.load_projects_registry，语义同迁前）。"""
    return _shared().load_projects_registry()


def _assert_nonempty(projects, quarantined):
    """空注册表统一报错（委托 shared.assert_registry_nonempty，文案不变）。"""
    _shared().assert_registry_nonempty(projects, quarantined)


def _projects():
    """读项目注册表（per-key 目录模式，语义与 server/project-registry.ts 同构）。"""
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
    """加载 engine/shared.py（workspace 推导/契约/模板类名映射的单一真源，
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


def _audit_mod():
    """加载 engine/audit.py（无差别审计+entry_hint 单一真源，stdlib-only）。"""
    global _AUDIT_MOD
    if _AUDIT_MOD is None:
        import importlib.util
        import sys
        spec = importlib.util.spec_from_file_location('_poc_audit', TEMP_POC / 'audit.py')
        mod = importlib.util.module_from_spec(spec)
        sys.modules['_poc_audit'] = mod
        spec.loader.exec_module(mod)
        _AUDIT_MOD = mod
    return _AUDIT_MOD


_AUDIT_MOD = None


def _poc(subcmd, payload, caller=None):
    """spawn engine/client.py，返回解析后的回执 dict（不判 ok）。

    子进程注入自报家门标记 SANDBAR_CLIENT_ENTRY='ticket'（普通 env，非密钥——
    client.py 据此免附 entry_hint、admin.log source 记 'ticket'）与关联键
    SANDBAR_CLIENT_CALL_ID（__main__ 直调路径生成，使双行审计可关联）。
    t260915-12：caller 非 None（写 op 的调用方项目身份推导结果）时注入
    SANDBAR_CALLER_PROJECT——client 侧跨项目闸按 env 来源消费（spawn 链注入，
    身份有出处；空串=未声明身份，不注入、由 client 按策略记名/拒收）。"""
    env = dict(os.environ)
    env['SANDBAR_CLIENT_ENTRY'] = _audit_mod().ENTRY_MARK
    if caller:
        env[_shared().CALLER_PROJECT_ENV] = caller
    cid = os.environ.get(_audit_mod().CALL_ID_ENV)
    if cid:
        env[_audit_mod().CALL_ID_ENV] = cid
    cmd = [TEMP_PY, str(TEMP_POC / 'client.py'), subcmd,
           json.dumps(payload, ensure_ascii=False)]
    try:
        proc = subprocess.run(cmd, cwd=str(REPO), capture_output=True, text=True,
                              timeout=900, env=env)
    except Exception as e:
        raise ValueError('Temporal 调用失败（temporal server/worker 在线？'
                         'cd server/engine && ./run_server.sh + .venv/bin/python worker.py）: %s' % e)
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


# ---------- 跨项目写操作闸：包装层身份推导与越权旗（t260915-12） ----------
# 分工：本层只做「推导+形状/必填 fail-fast」，权威判定在 client.py 闸（判定矩阵）与
# workflow intake（第二道）；包装层只加审计不加权力（KI-067 以来既定哲学）。

def _resolve_caller(a):
    """调用方项目身份推导（单一入口，解析顺序=显式 > env 透传 > cwd 窄兜底）。

    - 显式 caller_project / env SANDBAR_CALLER_PROJECT：须过 PROJECT_KEY_RE（形状非法
      =ValueError 显式暴露，不静默当未声明——review C2② 同口径）；
    - cwd 窄兜底：真人在项目工作区直跑时 cwd 可推导（出处=cwd×注册表）；**引擎仓树内
      一律不推导**（review C1：dsh 工具链 spawn cwd=repo、console 插件 cwd=engine 子目录，
      仓树内 cwd 标识「被调用的引擎」而非「调用方会话」）→ 返回 ''（未声明）。
    返回 key 或 ''（''=未声明身份，_poc 不注入 env，client 按策略记名/拒收）。"""
    s = _shared()
    explicit = str(a.get('caller_project') or '').strip()
    env_raw = str(os.environ.get(s.CALLER_PROJECT_ENV) or '').strip()
    if explicit or env_raw:
        v = explicit or env_raw
        if not s.PROJECT_KEY_RE.match(v):
            raise ValueError(
                '调用方项目身份形状非法：%r（来源=%s；白名单 %s）——修正 caller_project '
                '或注入链后重试' % (v[:64], 'caller_project' if explicit else s.CALLER_PROJECT_ENV,
                                    s.PROJECT_KEY_RE.pattern))
        return v
    cwd = os.path.realpath(os.getcwd())
    repo_root = os.path.realpath(str(s.REPO_ROOT))
    key = s.project_key_for_dir(cwd, _projects(), (repo_root,))
    return key or ''


def _cross_project_flag(a):
    """越权旗归一与本层校验（review C3/C4：by/reason 必填非空+上限；畸形旗 fail-fast）。
    接受 cross_project={by,reason}（结构形）或 cross_project_reason（扁平形，by 缺省取
    by|who）。返回 {'by','reason'} 或 None（无旗）。"""
    flag = a.get('cross_project')
    flat = str(a.get('cross_project_reason') or '').strip()
    if flag is None and not flat:
        return None
    if flag is not None and not isinstance(flag, dict):
        raise ValueError('越权旗 cross_project 需为对象 {by, reason}（收到 %s）'
                         % type(flag).__name__)
    by = str((flag or {}).get('by') or '').strip()
    reason = str((flag or {}).get('reason') or '').strip()
    if flat:
        if reason:
            raise ValueError('越权旗理由重复：cross_project.reason 与 cross_project_reason 只给其一')
        reason = flat
    if not by:
        by = str(a.get('by') or a.get('who') or '').strip()
    if not by:
        raise ValueError('越权旗缺 by（谁在越权——旗必须记名）；扁平形可省略（by 取操作人 by|who）')
    if not reason:
        raise ValueError('越权旗缺 reason（为什么跨项目——理由必填，记名留痕可查）')
    s = _shared()
    if len(by) > s.CROSS_PROJECT_BY_LIMIT:
        raise ValueError('越权旗 by 超限（%d > %d 字符）' % (len(by), s.CROSS_PROJECT_BY_LIMIT))
    if len(reason) > s.CROSS_PROJECT_NOTE_LIMIT:
        raise ValueError('越权旗 reason 超限（%d > %d 字符）——拆条后在目标票 ruling/pending 补充'
                         % (len(reason), s.CROSS_PROJECT_NOTE_LIMIT))
    return {'by': by, 'reason': reason}


def _write_op_poc(subcmd, payload, a):
    """写 op 统一出口：推导身份+越权旗（payload 只带旗；身份走 env 注入）→ _poc。"""
    return _poc(subcmd, payload, caller=_resolve_caller(a))


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
    for k in ('signatures', 'gate_runs', 'gens', 'refused', 'timeline', 'results',
              'human_context', 'engine', 'workflow_class',  # gens=t260915-01 ③ 段→轮次读数
              'topology'):  # t260915-05 ④ 模板拓扑导出（门内 additive 键；缺=旧票回落模板级导出）
        meta[k] = snap.get(k)
    # t260915-12 越权对账面（工单③）：越权旗/未声明身份的写操作记名（workflow 侧
    # meta['cross_project_uses']，盖章 op 才有账；retry_qc/update/cancel 的记名只在
    # admin.log——覆盖口径如实分档，见 server/engine/README.md 闸契约节）。
    meta['cross_project_uses'] = (snap.get('meta') or {}).get('cross_project_uses') or []
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
    # dev-lane 结构性写 integration/（design_integration_tests 落场景文件+清单登记，
    # t260903-05 实案：白名单拦得对、错在声明漏）——建单侧自动并入，防人工漏报。
    # t260910-03：write_set 组装（含 integration/ 自动并入）必须先于 derive——
    # derive_lane_workspace 的多仓派生以写集归属为唯一输入（repo_write_set），
    # 组装滞后=并入条目不参与归属推导=成员仓明细缺失（dengzhufpv 260910 缺陷形态）。
    write_set = list(a.get('write_set') or [])
    if wid == 'dev-lane' and 'integration/' not in write_set:
        # t260910-03：并入前先探归属——补传 repo_write_set 后，无 integration/
        # 成员仓的多仓项目若盲目并入，整票在派生即拒收（integration/ 不落任何仓）。
        # 单仓项目归属恒成功（前缀归属不查存在性），行为与旧无条件并入完全一致；
        # 多仓项目无此成员路径则跳过并入（自动化便利项缺席≠静默降级：票照开，
        # 写集白名单仍守用户声明面）。
        try:
            _shared().resolve_repos_for_paths(proj['dirs'][0], ['integration/'])
            write_set.append('integration/')
        except ValueError:
            pass
    validate_write_set_no_notes(write_set)
    # lane/泳道字段推导+校验走 shared 单一真源（t260824 三次漂移事故）：
    # 形态错/字段不一致在创建瞬间拒收，不放跑到运行期才暴露。
    # t260910-03：补传 repo_write_set——与裸 client.py 入口共用同一多仓派生条件
    # （ws is None and not worktree × 写集归属），正规入口不再堵死引擎侧多仓明细。
    try:
        lane, ws, worktree, branch = _shared().derive_lane_workspace(
            tid, wf['lane'], lane=a.get('lane') or '',
            workspace=a.get('workspace'), worktree=a.get('worktree') or '',
            branch=a.get('branch') or '',
            template_workspace_dir=(wf.get('workspace') == 'dir'),
            project_root=proj['dirs'][0],
            repo_write_set=write_set)
    except ValueError as e:
        raise ValueError('create 参数非法：%s' % e)
    _check_paths_under_project(proj, ws, worktree)
    tpl_acc = list(stage0.get('acceptance') or [])
    extra = [x for x in (a.get('acceptance') or []) if x not in tpl_acc]  # A5.5 实例增项
    flag = _cross_project_flag(a)
    payload = {
        'ticket_id': tid, 'template_id': wid, 'project': proj['key'], 'title': a['title'],
        # epic 只透传：强校验单点在 client.py（validate_epic_code），错误经 _poc_ok 原样上抛
        'epic': a.get('epic') or '',
        'lane': lane, 'workspace': ws, 'worktree': worktree, 'branch': branch,
        'base_ref': _base_ref(proj['dirs'][0]) if lane == 'worktree' else '',
        'proposal_id': a.get('proposal_id') or '',
        'book_path': a.get('book_path') or '',
        'write_set': write_set,
        # 门①背景文件闸（t260904-18）：只透传，校验单点在 client.py ticket-start
        # （_connect() 之前），薄壳不第二真源。
        'refs': list(a.get('refs') or []),
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
    }
    if flag:
        payload['cross_project'] = flag
    out = _write_op_poc('ticket-start', payload, a)
    res = _poc_ok(out)
    # 每工单专属 worker（260824 拍板）：ticket.py 不再 spawn——console 的
    # keepalive ensure 是唯一生产 spawn 点（15s 内补拉；无 console 时工单在
    # Temporal 里待命，console 起来自动开跑，活不丢）。
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
    payload = {'op': 'update', 'ticket_id': tid,
               'status': a.get('status') or '', 'note': a.get('note') or '',
               'pending_add': a.get('pending_add') or '',
               'book_path': a.get('book_path')}
    flag = _cross_project_flag(a)
    if flag:
        payload['cross_project'] = flag
    out = _write_op_poc('ticket', payload, a)
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
        'authz_active': int(r.get('authz_active') or 0),   # t260912-03 生效中授权计数
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
            # t260912-03：列表可读面＝生效中的人授权条数（client.py 行内已按
            # expires>now 过滤；行缺键=老引擎，补 0 不炸）
            'authz_active': int(meta.get('authz_active') or 0),
        })
    return {'count': len(out_rows), 'tickets': out_rows}


def _authz_view(snap):
    """ticket show 的人授权可读面（t260912-03）：全量条目 + 逐条状态（生效中/已过期）。
    口径写死：show=全量（含已过期，供审计回溯），list=authz_active 只数生效中。
    状态比较点=CLI 进程读取时刻（issued/expires 均为 epoch 秒，workflow 侧不读墙钟）。
    形状兼容两吃（260912 仲裁实证：_show 实参=_v2_query[0]=扁平 ticket face，
    authorizations 在顶层——只吃嵌套 meta 形状会让真路径恒拿 None，展示层假死）：
      · 扁平（真路径）：{'authorizations': [...], ...}
      · 嵌套（快照形状/兼容）：{'meta': {'authorizations': [...]}}"""
    if not isinstance(snap, dict):
        return None
    meta = snap.get('meta') if isinstance(snap.get('meta'), dict) else {}
    items = snap.get('authorizations')
    if not isinstance(items, list):
        items = meta.get('authorizations')
    if not isinstance(items, list):
        return None
    now = int(time.time())
    out = []
    for it in items:
        if not isinstance(it, dict):
            continue
        exp = int(it.get('expires') or 0)
        uses = it.get('uses') if isinstance(it.get('uses'), list) else []
        out.append({
            'kind': str(it.get('kind') or ''),
            'who': str(it.get('who') or ''),
            'scope': [str(s) for s in (it.get('scope') or [])],
            'reason': str(it.get('reason') or ''),
            'issued': int(it.get('issued') or 0),
            'expires': exp,
            'status': '生效中' if exp > now else '已过期',
            'uses': uses,
            'used_count': len(uses),
        })
    return out


def _show(a):
    tid = a.get('id') or ''
    v2 = _v2_query(tid)
    if v2 is None:
        # None 的唯一来源=kind=not_found（_v2_query 契约）——这里必须带 kind 抛
        # QueryError，否则 registry 回执丢 kind，工作台 404 分流失去唯一合法判据。
        raise QueryError('工单不存在: %s（Temporal 无此 workflow）' % tid, kind='not_found')
    snap = v2[0]
    # t260912-03 可查面：authorizations 全量已在（_v2_query[0] 扁平 ticket face，
    # 引擎 ticket 面原样投影），此处加展示层 authz（逐条状态+消费次数）与计数——
    # 附加键，不改既有形状（老票无该键=返回 None 不加）。
    authz = _authz_view(snap)
    if authz is not None and isinstance(snap, dict):
        snap['authz'] = authz
        snap['authz_active'] = len([x for x in authz if x['status'] == '生效中'])
    return snap


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
    payload = {'op': 'rework', 'ticket_id': tid,
               'note': a.get('note') or '',
               'to_stage': a.get('to_stage') or '',
               'who': _who(a)}
    flag = _cross_project_flag(a)
    if flag:
        payload['cross_project'] = flag
    out = _write_op_poc('ticket', payload, a)
    return _poc_ok(out)


def _who(a):
    """操作人字段双读：by（本工具 schema 主名）| who（信号语义名，workbench/场景
    同名面）——who 在包装层被丢=代签无主（K-067 包装面事故形状），双读防漏。"""
    return str(a.get('by') or a.get('who') or '')


def _sign(a):
    """人工审批签字（KI-067：此前代签只走裸 client.py，是唯一不进审计的工单操作；
    现包进正规入口——包装层只加审计不加权力，who 仍由调用方注入）。"""
    tid = a.get('id') or ''
    if not tid:
        raise ValueError('sign 需要 id')
    decision = a.get('decision') or 'approve'
    if decision not in ('approve', 'reject'):
        raise ValueError("sign decision 只收 approve|reject（收到 %r）" % (decision,))
    payload = {'op': 'sign', 'ticket_id': tid,
               'input': {'who': _who(a),
                         'gate': a.get('gate') or '',
                         'decision': decision,
                         'note': a.get('note') or ''}}
    flag = _cross_project_flag(a)
    if flag:
        payload['cross_project'] = flag
    out = _write_op_poc('ticket', payload, a)
    return _poc_ok(out)


def _retry_qc(a):
    """blocked 重跑请求（KI-067：signal 子命令退役后 CLI 无 retry_qc 通道，当日只能
    Temporal 直连兜底）。workflow 侧契约（base.py retry_qc(self, who: str)）只收
    **裸字符串**：note 非空在此显式拒收（静默蒸发不可接受），带话走 update
    pending_add 或 ruling。"""
    tid = a.get('id') or ''
    if not tid:
        raise ValueError('retry_qc 需要 id')
    if str(a.get('note') or '').strip():
        raise ValueError('retry_qc 不收 note（workflow 契约只收 who）——带话走 '
                         'update pending_add，或 ruling 注入裁决')
    payload = {'op': 'retry_qc', 'ticket_id': tid,
               'who': _who(a) or 'op-local'}
    flag = _cross_project_flag(a)
    if flag:
        payload['cross_project'] = flag
    out = _write_op_poc('ticket', payload, a)
    return _poc_ok(out)


def _ruling(a):
    """宿主裁决注入（t260915-12 F2 收口：schema op enum 宣告了 ruling 而分发器无出口
    ——宣告不支持的工具面=对模型面撒谎，KI-079 同族「说明书与实际入口不符」）。薄壳
    委托 client.py ticket op=ruling（intake 单点在 workflow：who/note 必填非空、note
    上限 HOST_RULING_NOTE_INPUT_LIMIT、跨项目闸第二道复核——本层不第二真源）；
    D1 同族：who 必填由调用方注入、纯空白本层拒收（正规入口不落 op-local）。"""
    tid = a.get('id') or ''
    if not tid:
        raise ValueError('ruling 需要 id')
    who = _who(a)
    if not who.strip():
        raise ValueError('ruling 需要 by|who（裁决人身份由调用方注入，不得留空）')
    if not str(a.get('note') or '').strip():
        raise ValueError('ruling 需要 note（裁决内容，非空）')
    payload = {'op': 'ruling', 'ticket_id': tid, 'who': who,
               'note': str(a.get('note') or '')}
    flag = _cross_project_flag(a)
    if flag:
        payload['cross_project'] = flag
    out = _write_op_poc('ticket', payload, a)
    return _poc_ok(out)


def _pause_resume(a, op):
    """段间暂停/恢复（t260914-04，KI-079 收口）：宪章 session_charter「引擎操作面」
    所教形式 `{"op":"pause"|"resume","id":"…","by":"…"}` 此前无此 op，暂停只能回落
    裸 client.py ticket——无写集闸、回执带 entry_hint，且裸口只认 who 不认宪章教的
    by＝事件历史 who 全落 op-local。薄壳委托 client.py ticket op=pause|resume，
    与 rework/retry_qc 同族顶层载荷形状（client.py 对 pause/resume 本就
    input/顶层双吃，零适配）。D1 身份闸（review_plan C4②/C5）：who 必填由调用方
    注入、纯空白在本层拒收——_authorize 同族先例；client.py 的 'op-local' 缺省
    从此只留给裸入口，正规入口机械保证不产生 op-local。note 可选透传，上限不在此
    抢答（单点=workflow intake PAUSE_NOTE_INPUT_LIMIT，不造第二真源）；「who 空白
    → workflow refused」语义仍由裸入口承载（场景 L3.1 腿，不重复设防）。"""
    tid = a.get('id') or ''
    if not tid:
        raise ValueError('%s 需要 id' % op)
    who = _who(a).strip()
    if not who:
        raise ValueError('%s 需要 by|who（操作人身份由调用方注入，不得留空）'
                         '——正规入口不落 op-local' % op)
    payload = {'op': op, 'ticket_id': tid, 'who': who,
               'note': str(a.get('note') or '')}
    flag = _cross_project_flag(a)
    if flag:
        payload['cross_project'] = flag
    out = _write_op_poc('ticket', payload, a)
    return _poc_ok(out)


def _authorize(a):
    """人授权签发（t260912-03，KI-067 教训：包装层只加审计不加权力，who/scope/reason/
    expires 全由调用方注入）。唯一入口＝既有 sign 信号面——本 op 只是它的载荷封装，
    与 sign 同审计面；agent 不得自签（who 不得为 agent 角色名）由 workflow intake 判。
    kind=protected_path（scope=路径/目录前缀）/ arbitration_verdict（scope=[本票票号]）。"""
    tid = a.get('id') or ''
    if not tid:
        raise ValueError('authorize 需要 id')
    who = _who(a)
    if not who.strip():
        raise ValueError('authorize 需要 by|who（授权人身份由调用方注入，不得留空）')
    kind = str(a.get('kind') or '')
    if kind not in ('protected_path', 'arbitration_verdict'):
        raise ValueError("authorize 的 kind 只收 protected_path|arbitration_verdict（收到 %r）"
                         % (kind,))
    scope = a.get('scope')
    if isinstance(scope, str):
        scope = [s.strip() for s in scope.split(',') if s.strip()]
    if not isinstance(scope, list) or not scope:
        raise ValueError('authorize 需要 scope（数组或逗号分隔串）：路径/目录前缀或本票票号')
    if a.get('expires') in (None, ''):
        raise ValueError('authorize 需要 expires（epoch 秒或 ISO8601——授权必须到期作废）')
    if not str(a.get('reason') or '').strip():
        raise ValueError('authorize 需要 reason（为什么批——授权记录必须能回答此问）')
    payload = {'op': 'authorize', 'ticket_id': tid,
               'input': {'who': who, 'kind': kind,
                         'scope': [str(s).strip() for s in scope],
                         'reason': str(a.get('reason') or ''),
                         'expires': a.get('expires')}}
    flag = _cross_project_flag(a)
    if flag:
        payload['cross_project'] = flag
    out = _write_op_poc('ticket', payload, a)
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
    if op == 'sign':
        return _sign(args)
    if op == 'authorize':
        return _authorize(args)
    if op == 'ruling':
        return _ruling(args)
    if op == 'retry_qc':
        return _retry_qc(args)
    if op in ('pause', 'resume'):
        return _pause_resume(args, op)
    raise ValueError('未知 op: %r' % (op,))


# ---------- 直 spawn CLI（KI-067 根因修复） ----------
# 用法：python3 server/tools/ticket.py '{"op":"list",...}'
# 契约：任何 op 失败 = stdout 一行结构化 {ok:false,error,kind?} + 退出码 1
# （绝不空输出、绝不退出 0）；成功 = 回执 JSON + 退出码 0；无参/畸形首参 =
# 结构化报错 + 非零。无参→非零无争议；-h 也非零是防误用：本 CLI 无交互面，
# 避免打印用法后空跑被上游当成功。直 spawn 每次调用（含失败）自记 admin.log
# 一行（source=ticket.py-direct），与 client.py 行共享 call_id。

_TICKET_CLI_USAGE = ('用法：python3 server/tools/ticket.py \'<json 对象，含 op>\'\n'
                     'op: create/update/list/show/rework/sign/authorize/retry_qc'
                     '/pause/resume'
                     '（accept/advance/dispatch-next 已取消，报结构化错误）\n'
                     '失败契约：非零退出 + {ok:false,error,kind?}，绝不空输出。')


def _cli(argv):
    """直 spawn 入口，返回进程退出码。"""
    if not argv or argv[0] in ('-h', '--help', 'help'):
        print(json.dumps({'ok': False, 'error': _TICKET_CLI_USAGE}, ensure_ascii=False))
        return 2
    try:
        payload = json.loads(argv[0])
    except json.JSONDecodeError as e:
        print(json.dumps({'ok': False, 'error': '参数不是合法 JSON：%s' % e},
                         ensure_ascii=False))
        return 1
    if not isinstance(payload, dict):
        print(json.dumps({'ok': False, 'error': '参数需为 JSON 对象（含 op）'},
                         ensure_ascii=False))
        return 1
    audit = _audit_mod()
    call_id = uuid.uuid4().hex[:12]
    os.environ[audit.CALL_ID_ENV] = call_id   # 传给 _poc → client.py 行共享关联键
    try:
        res = run(payload)
        out = {'ok': True, 'result': res}
    except Exception as e:
        out = {'ok': False, 'error': '%s: %s' % (type(e).__name__, e)}
        kind = getattr(e, 'kind', None)
        if isinstance(kind, str) and kind:
            out['kind'] = kind
    # sub 记 'ticket.<op>'（带 ticket 前缀：与 client.py 行同族可检索，source 区分入口）
    audit.audit_call('ticket.%s' % (payload.get('op') or '(none)'), out,
                     call_id=call_id, source='ticket.py-direct')
    print(json.dumps(out, ensure_ascii=False))
    return 0 if out.get('ok') else 1


if __name__ == '__main__':
    import sys
    sys.exit(_cli(sys.argv[1:]))
