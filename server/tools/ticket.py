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
  cancel {id, by(who), reason(必填非空), cross_project?}  → 记名单票终结（t260922-10，
      清场 runbook 判据见下节）：先 signal cancel_notice 留痕（who+reason 入票面
      log/timeline 与跨项目记名面 cross_project_uses）后 terminate（reason 同串）；
      已终态=幂等回执零改动；拒绝零副作用（who/reason 空在本层结构化拒收）
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

清场 runbook（残渣票/永久推不动票的判据与处置，宿主令 260922「给 ops 一个记名入口，
或把处置写进 runbook」——docs/ 不在本票写集，判据以本工具帮助文本承载；未来成篇可挂
docs/ops/ 同族操作手册）：
  判据（全部满足才 cancel）：① 票 stage_state=blocked，且根因属「工作空间/夹具已物理
  不存在、重跑必然再失败」类（如多仓夹具 /tmp 临时目录已被系统清理）；② 至少一次
  retry_qc 实测复现失败（不是猜）；③ 票面无在飞价值（交付不依赖该票跑完）。
  处置：先 show 留证 → ticket cancel（by|who + reason 写明根因证据，如「工作空间
  /var/folders/…/t260910-* 已不存在，retry_qc 复现失败」）→ 异项目票带
  cross_project={by,reason} 旗 → 终结后对账：admin.log 与 Temporal 事件历史 grep
  同一 reason 串（终态票 show 不可查——快照不可得，事件历史是权威对账面；票面
  log/timeline/cross_project_uses 是终结前窗口尽力面）。巡检票 cancel 仅事件历史+
  admin.log 留痕（inspection workflow 无 cancel_notice handler）。
  边界：只做记名单票终结；不批量清理、不自动清理历史票（自动清历史=危险默认）。

全部调用经 admin.log 审计：registry.call 路径=run-id 审计（tools_registry）；
直 spawn 路径（__main__，t260910-06）=本文件自记 source=ticket.py-direct 一行 +
client.py 记 source=ticket 一行（call_id 关联）——双行形状是契约不是重复 bug。

跨项目写操作闸（t260915-12，契约详见 server/engine/README.md §11）：写 op（create/
update/rework/sign/retry_qc/pause/resume/authorize/ruling/cancel）带调用方项目身份
与越权旗——身份推导=显式 caller_project > env SANDBAR_CALLER_PROJECT > cwd 窄兜底（引擎仓树内
一律不推导，防间接调用凭空造身份）；形状非法/越权旗缺 by|reason/超上限在本层
fail-fast。declared 身份与目标票项目不符由 client.py 闸拒收（cross_project_refused）；
确需跨项目带 cross_project={by, reason 必填}（记名留痕，show 出口可对账）。undeclared
=拒收（t260925-08 翻严缺省；过渡期经旋钮 SANDBAR_UNDECLARED_POLICY=record 显式回记名
放行，契约见 README §11.2）。读 op 不带闸上下文。

直 spawn 形态（KI-067 根因修复）：本文件历史上没有 CLI 入口，任何直接
`python3 ticket.py '{...}'` 都是空输出+退出 0+admin.log 无痕（260910 两实证）。
现提供 __main__：首参 JSON（含 op）→ run() → 结构化回执；任何失败**非零退出**+
{ok:false,error,kind?}，绝不空输出。
"""
import json
import os
import re
import subprocess
import sys
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
                    '/pause·resume（段间暂停·恢复，t260914-04）'
                    '/cancel（记名单票终结：残渣票清场，who/reason 必填，判据=模块头清场 runbook）。'
                    'accept/advance/dispatch-next 在 v2 引擎已取消（自动推进+事后看产物）。'
                    'status 状态机 dispatched→settled→verified→closed/rework，'
                    'stage_state=running/awaiting/awaiting-human/blocked 为进度维度，两者正交。'),
    'parameters': {
        'type': 'object',
        'properties': {
            'op': {'type': 'string', 'enum': ['create', 'update', 'list', 'show', 'accept',
                                              'advance', 'dispatch-next', 'rework',
                                              'sign', 'retry_qc', 'pause', 'resume',
                                              'authorize', 'ruling', 'cancel',
                                              'close_out']},
            'caller_project': {'type': 'string', 'description': '调用方项目身份（t260915-12 跨项目闸）：显式声明优先于 env/cwd 推导；写操作身份与目标票项目不符=拒收（cross_project_refused），确需跨项目带 cross_project 旗。引擎仓树内 cwd 不推导（防间接调用凭空造身份）'},
            'cross_project': {'type': 'object', 'properties': {'by': {'type': 'string', 'description': '谁在越权（记名）'}, 'reason': {'type': 'string', 'description': '为什么跨项目（理由必填入账）'}}, 'required': ['by', 'reason'], 'description': '越权豁免旗（记名留痕可查）：declared 身份跨项目写操作的显式放行钥匙；缺理由=拒收'},
            'cross_project_reason': {'type': 'string', 'description': '越权旗扁平形（理由必填；by 缺省取 by|who）——与 cross_project.reason 互斥'},
            'id': {'type': 'string', 'description': '工单 id（update/show/accept/advance/dispatch-next/rework/sign/retry_qc/pause/resume/cancel 必填；create 可指定否则自动生成）'},
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
            'reason': {'type': 'string', 'description': 'cancel=清场理由 / close_out=收口依据（两者皆必填非空）：终结后 admin.log 与 workflow 事件历史按此串精确对账；建议 ≤300 字符（保跨项目记名条目 cross_project_uses 全文入账；残渣票判据=模块头清场 runbook）。close_out 的理由=凭什么认定工作已完成（事后审计唯一锚点）'},
            'pending_add': {'type': 'string', 'description': '追加一条挂起项（遗留问题，不硬改交回）'},
            'to_stage': {'type': 'string', 'description': 'rework 打回目标 stage（缺省回上一段）'},
            'worktree': {'type': 'string', 'description': 'create 显式登记泳道路径（缺省 dev-lane 自动 .lane/<id>）'},
            'branch': {'type': 'string', 'description': 'create 显式登记分支名（缺省 lane/<id>）'},
            'workspace': {'type': 'object', 'description': 'create 显式登记工作空间 {type: worktree|dir, path}（缺省按模板推导：lane=worktree→泳道，模板带 workspace:dir→/tmp/sandbar-ws/<id> 隔离目录（老 base 粘滞））'},
            'by': {'type': 'string', 'description': 'rework/sign/retry_qc/pause/resume/cancel 操作人（身份注入，who 语义由调用方负责；等价别名 who 也收；pause/resume/cancel 必填非空——正规入口不落 op-local）'},
            'who': {'type': 'string', 'description': '操作人别名（=by，信号语义名；rework/sign/retry_qc/pause/resume/cancel 收）'},
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
    client.py kind=not_found（describe 命中 NotFoundFailure）一个入水口。

    face（260930 批次 B，dengzhufpv E5）：终态票的**可渲染失败面**随异常上送（additive：
    缺省 None，老消费方零感知）。为什么加：终态后票面快照不可查（引擎有意如此），复盘
    「谁终结的/终结前有没有留痕」此前只能自己写 Temporal SDK 脚本读历史；face 里带
    terminate 理由原文 + **最后一个信号名**（`_terminal_failure_face` 现算），让正规入口
    （ticket show）就能读到，不再要求人写脚本。"""

    def __init__(self, msg, kind="internal", face=None):
        super().__init__(msg)
        self.kind = kind
        self.face = face


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
        # 终态票：把引擎侧现算的失败面（含 terminate 理由与最后信号名）一并带出（260930）
        raise QueryError('工单查询失败（%s）：%s' % (kind, out.get('error') or '未知错误'),
                         kind, face=out.get('face') if kind == 'terminal' else None)
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
    # t260927-05：外置模板拓扑回落——dev-lane/巡检等内置模板快照自带 topology；
    # 项目外置模板（t260924-04 加载口）的 workflow 类不产该键 → show 空拓扑、
    # 控制台泳道图缺席。改：快照缺拓扑时经 template-faces 权威面取该模板的
    # STAGES 线性拓扑（与 create 闸同源；真未知模板 id=权威面也无 → 保持 None
    # 不 fake）。faces 通道故障=show 不炸，stderr 一行点名后回落 None（缺席有痕，
    # 绝不静默冒充有拓扑）。
    if not meta.get('topology') and meta.get('workflow_id'):
        try:
            _tv = (_template_faces().get('templates') or {}).get(meta['workflow_id'])
            if isinstance(_tv, dict):
                meta['topology'] = _tv.get('topology')
        except Exception as _e:
            print('ticket: 模板拓扑回落不可达（template-faces 故障，回落 None）：%s: %s'
                  % (type(_e).__name__, _e), file=sys.stderr)
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
    """当天短 id 自增序号（t<yymmdd>-<NN>）：扫 Temporal 同前缀 id 取最大序号 +1
    （workflow id 就是票 id，全局唯一、不分项目）。
    t260916-02：巡检票号统一成工单号形式后，工单与巡检票**共享同一日序号空间**——
    只扫工单店会让两族各发同一个号、起票撞 workflow id（现成缺陷）。改走
    ticket-list id_prefix 全类型前缀扫描（巡检票一并入扫），序号判定核心 =
    shared.next_ticket_seq_from_ids 单点（与 inspection_ticketing 同一份实现）。"""
    out = _poc('ticket-list', {'id_prefix': prefix})
    if not out.get('ok'):
        raise ValueError('Temporal 不可达，无法分配工单序号: %s' % (out.get('error') or out))
    ids = [str((r or {}).get('id') or '')
           for r in (out.get('result') or {}).get('tickets') or []]
    return _shared().next_ticket_seq_from_ids(prefix, ids)


def _check_paths_under_project(proj, ws, worktree):
    """显式给的绝对路径必须落在该项目注册目录之一（防把别的项目的目录登记进来）；
    相对路径不拦（执行侧对项目主目录解析）。（t260904-02 起委托 shared 同名函数，
    client.py ticket-start 硬闸共用同一判定。）"""
    _shared().check_paths_under_project(proj, ws, worktree)


# ---------- 操作 ----------

# ---- create 模板闸：权威模板面查询（t260926-03，KI-123）----
# 根因：类面合并（project_template_classes_merged）只在引擎进程 import workflows_v2
# 时一次性执行，结果进程本地；本文件 create 原只读本进程名面表（_shared().
# TEMPLATE_CLASS_NAMES，stdlib glue），类面拒收/空转对建票方完全不可见 → 「既不
# accepted 也不 rejected」的静默空转，项目模板的票建不出来。改法：非内置模板 id
# 经 client.py template-faces（引擎 venv 子进程，每次现算类面，不连 Temporal）取
# 权威面判定；拒收/不可达一律 fail-closed 点名，绝不静默回落内置面。
# _poc 通道故障模式取舍（review 拍板清单）：子进程异常与非 JSON 回执——捕获后换壳
# 重抛「权威模板面不可达（<原因>）」，原异常串保留括号内可追因（不带 Temporal 措辞）；
# ok:false——不走 _poc_ok（那是「Temporal 拒绝」措辞面），自行判壳；回执畸形（缺键/
# 类型错）——闸侧形状校验 fail-closed 点名缺什么；timeout=900/审计双行留痕——照带。

def _template_faces():
    """权威模板面回执（裸 _poc + 自判壳；任何失败路径 fail-closed 点名，无静默空表）。"""
    try:
        out = _poc('template-faces', {})
    except ValueError as e:  # 子进程异常（timeout/解释器缺失）与非 JSON 回执同门换壳
        raise ValueError('权威模板面不可达（template-faces 子进程故障）：%s' % e)
    if not isinstance(out, dict) or not out.get('ok'):
        raise ValueError('权威模板面不可达（client 回执 ok=false：%s）'
                         % ((out or {}).get('error') if isinstance(out, dict) else out))
    faces = out.get('result')
    if not isinstance(faces, dict):
        raise ValueError('权威模板面不可达（回执 result 非对象：%s）'
                         % type(faces).__name__)
    _validate_faces_shape(faces)
    return faces


def _validate_faces_shape(faces):
    """回执形状校验（外部输入畸形用例纪律）：畸形即点名缺什么，不静默当空表。"""
    bad = None
    if not isinstance(faces.get('class_available'), list) or not all(
            isinstance(x, str) for x in faces['class_available']):
        bad = 'class_available 须为字符串列表'
    elif not isinstance(faces.get('names'), dict):
        bad = 'names 须为对象（id → 类名）'
    elif not isinstance(faces.get('rejections'), list) or any(
            not isinstance(r, dict) or not {'project', 'module', 'check', 'detail'} <= set(r)
            for r in faces['rejections']):
        bad = 'rejections 须为对象列表（每条含 project/module/check/detail）'
    elif not isinstance(faces.get('builtin'), list):
        bad = 'builtin 须为字符串列表'
    elif not isinstance(faces.get('declared_projects'), int) or \
            not isinstance(faces.get('projects_scanned'), int):
        bad = 'declared_projects/projects_scanned 须为整数（扫描可判别性字段缺失）'
    if bad:
        raise ValueError('权威模板面回执畸形（%s），fail-closed 拒收不静默回落内置面' % bad)


def _template_gate_verdict(wid, faces, project_key=''):
    """纯函数判定（可注入单测）：返回 (是否放行, 拒收文案)。三态可判别——
    扫了但拒（附明细）/ 注册根空转没扫（declared_projects=0 点名根路径）/
    已声明但该 id 未登记（点名已登记集）。明细段恒置于「可用：」段之前
    （收窄守卫 C 半按 rsplit('可用：') 判列表面）。"""
    if wid in set(faces.get('class_available') or []):
        return True, ''
    rejs = [r for r in faces.get('rejections') or []
            if not project_key or r.get('project') == project_key]
    if rejs:
        detail = '；项目模板拒收明细：' + '；'.join(
            '[%s/%s] %s：%s' % (r.get('project', ''), r.get('module', ''),
                                r.get('check', ''), r.get('detail', ''))
            for r in rejs)
    elif not faces.get('declared_projects'):
        detail = ('；项目模板扫描未发现任何 workflow_modules 声明'
                  '（projects_scanned=%s，注册根=%s）——该 id 未登记'
                  % (faces.get('projects_scanned'), faces.get('projects_root') or '?'))
    else:
        detail = ('；项目模板已声明但该 id 未在类面登记（已登记：%s）'
                  % ('、'.join(sorted(faces.get('class_available') or [])) or '（无）'))
    avail = sorted(set(faces.get('names') or {}) | set(faces.get('class_available') or []))
    return False, 'create 需要 workflow（模板 id%s，可用：%s）' % (detail, '、'.join(avail))


def _template_view(wid, wfmod, faces):
    """模板定义视图（t260926-03 第 2 轮，KI-123 残余缺陷实锤）：_create 原无条件
    `wfmod.load(server/workflows/<id>.yaml)`——yaml 快照只随内置模板生成，项目外置
    模板在引擎仓无 yaml → 闸放行后仍「模板不存在」，票建不出来。改：yaml 在则照旧
    （内置/夹具路径零行为变化）；不在则吃权威面回执的 templates 视图（类属性推导，
    与 client.py ticket-start 同源），缺视图/字段不合= fail-closed 点名，不静默。"""
    ypath = wfmod.DIR / (wid + '.yaml')
    if ypath.is_file():
        return wfmod.load(ypath)
    tpl = ((faces or {}).get('templates') or {}).get(wid)
    if not isinstance(tpl, dict):
        raise ValueError('模板不存在: %s（且权威模板面回执无该模板定义视图'
                         '——类面/回执漂移，fail-closed 拒收）' % ypath)
    lane = tpl.get('lane')
    if lane not in ('main', 'worktree'):
        raise ValueError('模板 %s 声明 lane 非法 %r（须 main/worktree）——'
                         'fail-closed 拒收' % (wid, lane))
    stages = tpl.get('stages')
    if not isinstance(stages, list) or not stages or \
            not (stages[0] or {}).get('role'):
        raise ValueError('模板 %s 权威面定义视图缺最小段表（stages[0].role 不可辨）'
                         '——fail-closed 拒收' % wid)
    return {'id': wid, 'name': tpl.get('name') or wid, 'lane': lane,
            'workspace': 'dir' if tpl.get('workspace_dir') else None,
            'stages': stages}


def _create(a):
    now = int(time.time())
    proj = _project(a.get('project') or '')  # 必传，无默认值（260823 用户拍板）
    wid = a.get('workflow')
    # t260924-04：未知模板文案附项目外置模板拒收明细（fail-closed 点名：检查项＋
    # 双方/缺什么；明细段置于「可用：」段之前——收窄守卫 C 半按 rsplit('可用：') 判
    # 列表面，明细段不得落到其后）。
    # t260926-03（KI-123）：内置∪夹具快路径（本进程名面表即可判，零 spawn）；其余 id
    # 一律走权威模板面（引擎 venv 现算类面）——类面通过的放行，拒收/空转/不可达点名。
    if not wid:
        raise ValueError('create 需要 workflow（模板 id，可用：%s）'
                         % '、'.join(sorted(_shared().TEMPLATE_CLASS_NAMES)))
    if wid not in _shared().BUILTIN_TEMPLATE_KEYS:
        faces = _template_faces()
        ok, msg = _template_gate_verdict(wid, faces,
                                         proj.get('key') if isinstance(proj, dict) else '')
        if not ok:
            raise ValueError(msg)
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
    wf = _template_view(wid, wfmod, faces if wid not in _shared().BUILTIN_TEMPLATE_KEYS else None)
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


def _cancel(a):
    """记名单票终结（t260922-10，宿主令「给 ops 一个记名入口」）：blocked 残渣票/
    永久推不动票的清场出口——把 terminate 包装成带身份、带理由的**记名**操作（裸
    client.py cancel 的记名只在 admin.log，票面查不到是谁、为什么）。who/reason 必填
    非空本层 fail-fast（D1 同族：正规入口不落 op-local；reason 是终结后的对账锚，
    空=结构化拒收）。跨项目闸与既有写 op 同链：_resolve_caller 身份注入 +
    _cross_project_flag 越权旗（异项目无旗由 client.py 闸拒收 cross_project_refused，
    带旗 cross_project_uses 记名可查）。幂等：已终态票由 client 侧回 already_terminal
    ok 回执，零改动。清场判据（何时允许 cancel）见本文件头「清场 runbook」节。
    次序纪律在 client.py ticket-cancel 单点：先 signal cancel_notice（who+reason 入
    票面可见面）后 terminate（reason 同串）——本薄壳不第二真源。"""
    tid = a.get('id')
    if not tid:
        raise ValueError('cancel 需要 id')
    who = _who(a).strip()
    if not who:
        raise ValueError('cancel 需要 by|who（操作人身份由调用方注入，不得留空）'
                         '——正规入口不落 op-local')
    raw_reason = a.get('reason')
    if raw_reason is not None and not isinstance(raw_reason, str):
        # 非串 reason 不做 str() 静默归一（t260922-10 场景②R4）：['x'] 归一会变成
        # "['x']" 非空放行——清场理由是对账锚，必须逐字可信，类型畸形=结构化拒收。
        raise ValueError('cancel 的 reason 需为字符串（收到 %s）——清场理由必须逐字'
                         '可对账，非串不做静默归一' % type(raw_reason).__name__)
    reason = str(raw_reason or '').strip()
    if not reason:
        raise ValueError('cancel 需要 reason（清场理由必填非空——终结后在 admin.log 与 '
                         'workflow 事件历史按此串精确对账；残渣票判据见本文件头清场 '
                         'runbook 节）')
    payload = {'op': 'cancel', 'ticket_id': tid, 'who': who, 'reason': reason}
    flag = _cross_project_flag(a)
    if flag:
        payload['cross_project'] = flag
    out = _write_op_poc('ticket-cancel', payload, a)
    return _poc_ok(out)


def _cancel_audit(a):
    """终结票「留痕对账」只读审计（260930 批次 B；dengzhufpv E4/E5 合并需求）。

    转发 engine/client.py cancel-audit。为什么要有：跨项目会话此前**没有读事件历史的
    工具入口**，遇到「terminate 理由写着宿主当面决定、历史里却只有 pause」这种不实归因，
    只能自己写 SDK 脚本翻历史（E5 原文）。本 op 把它变成一条命令，且**只读**：不发信号、
    不写状态、不推进任何票。

    判定口径：留痕机制（cancel_notice／close_out_notice）上线日 2026-09-23 之后，终结票
    若既无 notice 留痕、理由串也对不上，即计入 missing_notice 违规；机制上线前的旧账单列
    legacy_pre_mechanism（结构上无法留痕，记而不告警）。alarmed=true 时本 CLI 退出码 1。
    """
    payload = {k: a[k] for k in ('limit', 'days', 'cutoff') if k in a}
    return _poc_ok(_poc('cancel-audit', payload))


def _close_out(a):
    """人工记名收口（t260927，宿主实报④）：把「票被误判 blocked、工作其实已完成」的
    完成态**记名收口**——一条 op 同时做三件：记名（who/reason 必填非空，进不可变事件
    历史与 admin.log）、置票面终态（closed）、终止工作流。与 cancel 的分工：cancel 是
    **清场**（理由=为什么废掉），close_out 是**收口**（理由=凭什么认定工作已完成）。

    为什么需要：A3.5 护栏（blocked 态只允许 dispatched/settled/rework）把「置 closed」
    这条正路也堵死了，于是完成态只能靠 dispatched→settled 变通、工作流仍挂在 blocked，
    看板永不归零。判据/次序纪律全在 client.py ticket-close-out 单点（先 signal
    close_out_notice 留痕、后 terminate，reason 带固定前缀可辨）——本薄壳不第二真源。"""
    tid = a.get('id')
    if not tid:
        raise ValueError('close_out 需要 id')
    who = _who(a).strip()
    if not who:
        raise ValueError('close_out 需要 by|who（操作人身份由调用方注入，不得留空）')
    raw_reason = a.get('reason')
    if raw_reason is not None and not isinstance(raw_reason, str):
        raise ValueError('close_out 的 reason 需为字符串（收到 %s）——收口理由必须逐字'
                         '可对账，非串不做静默归一' % type(raw_reason).__name__)
    reason = str(raw_reason or '').strip()
    if not reason:
        raise ValueError('close_out 需要 reason（收口依据必填非空：说清凭什么认定工作'
                         '已完成——这是事后审计的唯一锚点）')
    payload = {'op': 'close_out', 'ticket_id': tid, 'who': who, 'reason': reason}
    flag = _cross_project_flag(a)
    if flag:
        payload['cross_project'] = flag
    out = _write_op_poc('ticket-close-out', payload, a)
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
    → workflow refused」语义仍由裸入口承载（场景 L3.1 子用例，不重复设防）。"""
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
    if op == 'cancel':
        return _cancel(args)
    if op == 'close_out':
        return _close_out(args)
    if op == 'cancel-audit':
        return _cancel_audit(args)
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
                     '/pause/resume/cancel'
                     '（accept/advance/dispatch-next 已取消，报结构化错误）\n'
                     '失败契约：非零退出 + {ok:false,error,kind?}，绝不空输出。')


def _exit_code(out):
    """CLI 退出码：失败=1；成功但回执带 alarmed=true（告警类只读命令）=1。

    fail-loud 的意义：巡检/自动化靠退出码踩闸，不能只靠人去读 JSON——「查出来有问题却
    退出 0」等于没查（同一语义见 inspection_trigger 的 deadman）。
    """
    if not out.get('ok'):
        return 1
    res = out.get('result')
    if isinstance(res, dict) and res.get('alarmed'):
        return 1
    return 0


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
        face = getattr(e, 'face', None)
        if isinstance(face, dict) and face:
            out['face'] = face        # 260930 批次 B：终态票失败面随回执上送（缺省不写）
    # sub 记 'ticket.<op>'（带 ticket 前缀：与 client.py 行同族可检索，source 区分入口）
    audit.audit_call('ticket.%s' % (payload.get('op') or '(none)'), out,
                     call_id=call_id, source='ticket.py-direct')
    print(json.dumps(out, ensure_ascii=False))
    return _exit_code(out)


if __name__ == '__main__':
    import sys
    sys.exit(_cli(sys.argv[1:]))
