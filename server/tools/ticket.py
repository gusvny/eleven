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
          acceptance?, deliverables?, id?, worktree?, branch?, workspace?, proposal_id?, book_path?,
          lane_version?, develop_line_id?}   （lane 两字段=t261009-76 逐票 opt-in，仅 dev-lane；
          缺省=legacy；未知/畸形版本、未声明 line id 在 client.py intake 具名拒收）
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
                            契约只收 who，带话走 update pending_add / ruling）。
                            行为口径（t261002-10）：重跑的是**当前机器段**，且两个机器段
                            （run_integration_tests 闸 / merge_check）在重跑前都会先把 main
                            重并进泳道——开票之后落进 main 的修复，一次 retry_qc 即达。
                            重并冲突 → 既有消解回路（回 implement）；重并不可达 → 响亮
                            blocked（点名哪个检查失败），绝不静默跳过同步继续检查。
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
  repair_hatch {project, by|who, breakage={known_issue|description}, revisions,
                expires}  → 快修口唯一 op（t261009-13 slice 1，develop-buffer 规则 26）：
      宿主授权一次认证外落地——逐字段具名拒收 + 票路径闸（ticket.py 自身 cwd 在
      .lane/ 下即拒，repair_hatch_refused_from_ticket_path）+ 锁内追加一条
      hatch-authorisation-v1 记录到项目 store（<perkey>/<key>/hatch/…jsonl，
      append-only、fail-closed 读）。slice 1 不做机械落地；expires 本层只记录
      （须在未来），落地时刻的过期复查属 T1.2。每次使用即开一条认证债（见下）。
  hatch_debts {project}  → 认证债只读面：outstanding 列表 + 覆盖状态；清债唯一
      机制=同 store 内 certification-v1 记录覆盖修订全集（推导非命令，无 clear op）
      ——认证记录由 T1.2 认证驱动写入，slice 1 只保证债可查且必在。
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
import pathlib
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
                    '/cancel（记名单票终结：残渣票清场，who/reason 必填，判据=模块头清场 runbook）'
                    '/dismiss·restore（t261009-31 人工处置失败票：who/reason 必填记名，'
                    '把失败行摘出板面/撤回摘除——只记 audit journal，非 workflow 信号，'
                    '不改状态机；人工动作，agent 角色名拒收）。'
                    'accept/advance/dispatch-next 在 v2 引擎已取消（自动推进+事后看产物）。'
                    'status 状态机 dispatched→settled→verified→closed/rework，'
                    'stage_state=running/awaiting/awaiting-human/blocked 为进度维度，两者正交。'),
    'parameters': {
        'type': 'object',
        'properties': {
            'op': {'type': 'string', 'enum': ['create', 'update', 'list', 'show', 'accept',
                                              'advance', 'dispatch-next', 'rework',
                                              'sign', 'retry_qc', 'pause', 'resume',
                                              'work_done',
                                              'authorize', 'ruling', 'cancel',
                                              'close_out', 'concurrency',
                                              'dismiss', 'restore']},
            'caller_project': {'type': 'string', 'description': '调用方项目身份（t260915-12 跨项目闸）：显式声明优先于 env/cwd 推导；写操作身份与目标票项目不符=拒收（cross_project_refused），确需跨项目带 cross_project 旗。引擎仓树内 cwd 不推导（防间接调用凭空造身份）'},
            'cross_project': {'type': 'object', 'properties': {'by': {'type': 'string', 'description': '谁在越权（记名）'}, 'reason': {'type': 'string', 'description': '为什么跨项目（理由必填入账）'}}, 'required': ['by', 'reason'], 'description': '越权豁免旗（记名留痕可查）：declared 身份跨项目写操作的显式放行钥匙；缺理由=拒收'},
            'cross_project_reason': {'type': 'string', 'description': '越权旗扁平形（理由必填；by 缺省取 by|who）——与 cross_project.reason 互斥'},
            'id': {'type': 'string', 'description': '工单 id（update/show/accept/advance/dispatch-next/rework/sign/retry_qc/pause/resume/cancel/dismiss/restore 必填；create 可指定否则自动生成）'},
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
            'reason': {'type': 'string', 'description': 'cancel=清场理由 / close_out=收口依据 / dismiss·restore=处置理由（t261009-31，必填非空，绝不默认）：终结后 admin.log 与 workflow 事件历史按此串精确对账；建议 ≤300 字符（保跨项目记名条目 cross_project_uses 全文入账；残渣票判据=模块头清场 runbook）。close_out 的理由=凭什么认定工作已完成（事后审计唯一锚点）'},
            'pending_add': {'type': 'string', 'description': '追加一条挂起项（遗留问题，不硬改交回）'},
            'to_stage': {'type': 'string', 'description': 'rework 打回目标 stage（缺省回上一段）'},
            'worktree': {'type': 'string', 'description': 'create 显式登记泳道路径（缺省 dev-lane 自动 .lane/<id>）'},
            'branch': {'type': 'string', 'description': 'create 显式登记分支名（缺省 lane/<id>）'},
            'workspace': {'type': 'object', 'description': 'create 显式登记工作空间 {type: worktree|dir, path}（缺省按模板推导：lane=worktree→泳道，模板带 workspace:dir→/tmp/sandbar-ws/<id> 隔离目录（老 base 粘滞））'},
            'lane_version': {'type': 'string', 'description': 'create 逐票 lane 版本 opt-in（t261009-76，仅 dev-lane 模板）：registry=legacy-v1|develop-buffer-v1；缺省/空=未 opt-in（legacy，绝不静默迁移）。未知/畸形名在建票口具名拒收（附 registry 清单）；校验单点=client.py'},
            'develop_line_id': {'type': 'string', 'description': 'create 声明的 develop line id（仅 dev-lane；lane_version=develop-buffer-v1 时必填）：必须已在 <develop_dir>/lines.json 声明（声明文件是唯一真源，未声明的 id 具名拒收并列出已声明 id）'},
            'by': {'type': 'string', 'description': 'rework/sign/retry_qc/pause/resume/cancel/dismiss/restore 操作人（身份注入，who 语义由调用方负责；等价别名 who 也收；pause/resume/cancel/dismiss/restore 必填非空——正规入口不落 op-local；dismiss/restore 拒收 agent 角色名）'},
            'session': {'type': 'string', 'description': 'work_done: the working session id (required, non-blank; identity guardrail - the lane records who worked on the ticket face, never a borrowed role name; falls back to by|who)'},
            'role': {'type': 'string', 'description': 'work_done: the working session role (optional; defaults to session)'},
            'note': {'type': 'string', 'description': 'work_done: completion note (optional; carried onto the ticket face in the stage handoff)'},
            'evidence_ref': {'type': 'string', 'description': 'work_done: evidence pointer (optional, e.g. result file / test name)'},
            'who': {'type': 'string', 'description': '操作人别名（=by，信号语义名；rework/sign/retry_qc/pause/resume/cancel/dismiss/restore 收）'},
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


_CONC_POC = None


def _concurrency_mod():
    """加载 engine/concurrency.py（t261004-32：项目级并发上限——声明装载/额度账本
    单一真源）。stdlib + engine.shared 依赖，可独立加载；声明拒收在这里原样上抛。"""
    global _CONC_POC
    if _CONC_POC is None:
        import importlib.util
        import sys
        spec = importlib.util.spec_from_file_location(
            '_poc_concurrency', TEMP_POC / 'concurrency.py')
        mod = importlib.util.module_from_spec(spec)
        sys.modules['_poc_concurrency'] = mod
        # concurrency.py 顶部 `import shared`——把 shared 装载单例注入该名，两侧
        # （engine 进程 / ticket.py 直 spawn）用同一份注册表装载器，不双份。
        sys.modules.setdefault('shared', _shared())
        spec.loader.exec_module(mod)
        _CONC_POC = mod
    return _CONC_POC


_AUDIT_MOD = None


def _caller_env(caller, caller_src=""):
    """身份注入 env 键（纯函数，t260930-14 单测面）。

    caller 非空时注入：SANDBAR_CALLER_PROJECT（身份）+ SANDBAR_CALLER_IDENTITY_SRC
    （推导出处 arg|env|cwd——client 侧执行器授权闸 executor_grants 据此辨认调用方
    通道；t261001-20 判据=受信会话身份：cwd 通道恒受闸，声明通道仅当调用方会话 id
    被项目声明 executor_sessions 点名才受闸，其余（夹具/light-lane/泳道 agent）豁免）。"""
    if not caller:
        return {}
    s = _shared()
    return {s.CALLER_PROJECT_ENV: caller,
            s.CALLER_IDENTITY_SRC_ENV: str(caller_src or "env")}


# 推导出处暂存（t260930-14）：_write_op_poc 在调 _poc 前写入、_poc 消费后清零。
# 不走 _poc 形参——_poc 的 (subcmd, payload, caller) 形状是场景桩/registry 面的既有
# 契约（t260922-10 等桩只认三参+裸串 caller），加形参会把桩打断（gen1 集成闸实录）。
_PENDING_CALLER_SRC = ''


def _poc(subcmd, payload, caller=None):
    """spawn engine/client.py，返回解析后的回执 dict（不判 ok）。

    子进程注入自报家门标记 SANDBAR_CLIENT_ENTRY='ticket'（普通 env，非密钥——
    client.py 据此免附 entry_hint、admin.log source 记 'ticket'）与关联键
    SANDBAR_CLIENT_CALL_ID（__main__ 直调路径生成，使双行审计可关联）。
    t260915-12：caller 非 None（写 op 的调用方项目身份推导结果）时注入
    SANDBAR_CALLER_PROJECT——client 侧跨项目闸按 env 来源消费（spawn 链注入，
    身份有出处；空串=未声明身份，不注入、由 client 按策略记名/拒收）。
    t260930-14：随身份注入推导出处 SANDBAR_CALLER_IDENTITY_SRC——出处由
    _write_op_poc 经 _PENDING_CALLER_SRC 暂存（模块级单调用面，ticket.py 每次
    CLI 调用单线程消费；_poc 被桩替换时该键天然缺席=不透传，行为同旧）。"""
    global _PENDING_CALLER_SRC
    env = dict(os.environ)
    env['SANDBAR_CLIENT_ENTRY'] = _audit_mod().ENTRY_MARK
    env.update(_caller_env(caller, _PENDING_CALLER_SRC))
    _PENDING_CALLER_SRC = ""
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

    t260930-14：返回 (key, src) 二元组——src=推导出处（arg|env|cwd），随身份经
    SANDBAR_CALLER_IDENTITY_SRC 透传给 client 侧执行器授权闸（executor_grants）。

    - 显式 caller_project / env SANDBAR_CALLER_PROJECT：须过 PROJECT_KEY_RE（形状非法
      =ValueError 显式暴露，不静默当未声明——review C2② 同口径）；
    - cwd 窄兜底：真人在项目工作区直跑时 cwd 可推导（出处=cwd×注册表）；**引擎仓树内
      一律不推导**（review C1：dsh 工具链 spawn cwd=repo、console 插件 cwd=engine 子目录，
      仓树内 cwd 标识「被调用的引擎」而非「调用方会话」）→ 返回 ''（未声明）。
    返回 (key, src) 二元组（''=未声明身份，_poc 不注入 env，client 按策略记名/拒收）。"""
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
        return v, 'arg' if explicit else 'env'
    cwd = os.path.realpath(os.getcwd())
    repo_root = os.path.realpath(str(s.REPO_ROOT))
    key = s.project_key_for_dir(cwd, _projects(), (repo_root,))
    return (key or '', 'cwd')


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
    global _PENDING_CALLER_SRC
    caller, caller_src = _resolve_caller(a)
    _PENDING_CALLER_SRC = caller_src
    try:
        return _poc(subcmd, payload, caller=caller)
    finally:
        _PENDING_CALLER_SRC = ""


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


# t261009-80: pure pause-effect prediction (mirrors the rule and copy of
# engine/client.py pause_effect_statement; wording consistency is pinned by the
# dual-load unit test — this file cannot load client.py, hard temporalio dep).
_PAUSE_BOUNDARY_EFFECT = (
    "accepted; the current segment runs to completion, then the ticket stops at the "
    "next segment boundary awaiting resume")
_PAUSE_BLOCKED_EFFECT = (
    "accepted, but this ticket is blocked waiting on a human and will not reach a "
    "segment boundary, so the pause will not take effect; the slot stays held")


def _pause_effect_of(paused, status, stage_state):
    """Not paused = empty string (never fabricated as a prediction); paused and
    unable to enter a next segment (blocked / waiting at the human gate) = the
    line naming "the pause will not take effect, the slot stays held"; any other
    pause = "stops at the next segment boundary awaiting resume". All three
    inputs must come from the same snapshot/meta read."""
    if not paused:
        return ''
    if str(status or '') == 'blocked' or str(stage_state or '') == 'awaiting-human':
        return _PAUSE_BLOCKED_EFFECT
    return _PAUSE_BOUNDARY_EFFECT


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
    # t261009-35: carry the between-segment pause pair on the detail face.
    # Source of truth = the snapshot TOP-LEVEL keys paused / paused_phase
    # (TicketPauseMixin product; orthogonal to stage_state — a pause is never
    # derived from stage_state, and a ticket between stages for any other
    # reason is not paused). Two consumer faces: the row assembly in
    # server/engine/client.py (ticket-list, both branches) and this detail
    # assembly in _v2_query (ticket show). RULE: any new pause-related key must
    # be added to BOTH faces in the same change — editing one face alone means
    # the two faces disagree silently. Absent key = False / '' (same default
    # as the row face; never fabricated as 'unknown').
    meta['paused'] = bool(snap.get('paused'))
    meta['paused_phase'] = str(snap.get('paused_phase') or '')
    # t261009-80 (KI-01M4HQ5FJ8HKGY156YCE97X0K7): effect-prediction read face —
    # when paused AND this ticket can never enter a next segment (blocked /
    # awaiting-human), show must say plainly "the pause will not take effect",
    # so "paused" and "stuck" are distinguishable from the face alone. The
    # wording truth source lives in engine/client.py (pause_effect_statement /
    # PAUSE_*_EFFECT constants); this layer cannot load that module (hard
    # temporalio dependency) so it mirrors the copy — consistency is pinned by
    # test_t261009_80_pause_honesty.py (dual-load comparison). The list row does
    # NOT carry this key (t261009-35 RULE: rows stay narrow; diagnosis happens
    # on this detail face). All three inputs come from the same meta (one
    # snapshot read); not paused = empty string.
    meta['pause_effect'] = _pause_effect_of(meta.get('paused'), meta.get('status'),
                                            meta.get('stage_state'))
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
        # t261019-32 (quickmanual lane): the evidence declaration rides verbatim —
        # thin-shell discipline, the gate lives at the quickmanual open stage.
        'evidence': dict(a['evidence']) if isinstance(a.get('evidence'), dict) else {},
        'deliverables': a.get('deliverables') or '',
        # 正文=原始用户需求（user_request 逐字保留，显式优先；缺省回落 body）
        'user_request': a.get('user_request') or '',
        'spec': a.get('spec') or '',
        'body': a.get('body') or '（无正文）',
        'created': now,
        # t261009-76: the develop-buffer opt-in rides the payload verbatim —
        # thin-shell discipline: validation single point = client.py
        # lane_optin_intake (named refusals before the workflow start).
        'lane_version': a.get('lane_version') or '',
        'develop_line_id': a.get('develop_line_id') or '',
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


def _row_int(v, default=0):
    # t261011-02：投影行的数值键防畸形（引擎行是真源，但畸形输入不外溢成
    # 垃圾类型——非数值/None/None 形串诚实落缺省，不炸列表）
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


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
    # t261011-02 单次薄壳投影（seam 收口）：client.py 行面（_row_from_meta 活行 /
    # 无快照极简收口行 / 降级行）是唯一真源，这里逐键透传、绝不重算——
    # 旧实现两次白名单重建把 paused/paused_phase/exec_status/close_health/
    # close_health_reason/lane_version/develop_line 依次削掉（t260910-04 因此
    # 绕道 console 直读 client.py；t261009-76 的 opt-in 两键在 CLI 面恒空）。
    # 本面**不故意丢弃任何引擎行键**——引擎行将来加键而此表未同步时，L1 键集
    # 断言（integration/tests/test_t261011_02_ticket_list_projection.py）会点名红。
    # 形状差异仅两处（非丢弃）：①键名沿用 CLI 既有对外名 'workflow'
    # （引擎行同名，透传即可）；②handoff_count/pending_count 引擎侧本就是计数
    # （非列表），按数透传。行缺键=老引擎/极简行，按各键诚实缺省补空，
    # 绝不从他字段反推。'updated' 引擎已按 '%m-%d %H:%M' 本地时区格式化
    # （读取点=CLI 进程），透传不重算；updated_ts 保持 epoch 秒。
    out_rows = []
    for r in v2_rows:
        if not isinstance(r, dict):
            r = {}   # 畸形行不炸列表，投影为全缺省诚实空行
        row = {
            'id': r.get('id'), 'project': r.get('project') or '',
            'epic': r.get('epic') or '',
            'role': r.get('role'), 'status': r.get('status'),
            'title': r.get('title'),
            'workflow': r.get('workflow') or '',
            'proposal_id': r.get('proposal_id') or '',
            'stage': r.get('stage'), 'stage_state': r.get('stage_state') or 'awaiting',
            'paused': bool(r.get('paused')),                       # t260908-01 段间暂停二态
            'paused_phase': str(r.get('paused_phase') or ''),      # pending / at_gate
            'engine': r.get('engine') or '',
            'handoff_count': _row_int(r.get('handoff_count')),
            'pending_count': _row_int(r.get('pending_count')),
            'worktree': r.get('worktree') or '', 'workspace': r.get('workspace'),
            'created': r.get('created'),
            'updated': r.get('updated') or '',
            'updated_ts': _row_int(r.get('updated_ts'), 0),
            'close_ts': _row_int(r.get('close_ts'), 0),
            'exec_status': r.get('exec_status') or '',             # t260921-03 收口执行态
            'close_health': r.get('close_health') or '',           # t260921-03 收口健康度
            'close_health_reason': r.get('close_health_reason') or '',
            # t260912-03：生效中的人授权条数（client.py 行内已按 expires>now 过滤）
            'authz_active': _row_int(r.get('authz_active')),
            # t261009-76：逐票 lane opt-in 上板（spec (4)）——操作员不读 workflow
            # 历史即可分辨 opt-in 票与 legacy 票；行缺键=老引擎，补空串不炸
            'lane_version': r.get('lane_version') or '',
            'develop_line': r.get('develop_line') or '',
        }
        if a.get('status') and row.get('status') != a['status']:
            continue
        if a.get('role') and row.get('role') != a['role']:
            continue
        if a.get('workflow') and row.get('workflow') != a['workflow']:
            continue
        if a.get('stage_state') and row.get('stage_state') != a['stage_state']:
            continue
        out_rows.append(row)
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


def _work_done(a):
    """Quickmanual lane (t261019-32): the working session signals done. The
    session id is mandatory and non-blank (identity guardrail: the lane records
    who worked, never a borrowed role name) - refused here so the signal never
    enters the history; role/note/evidence_ref are optional. Stamped through the
    same caller gate as sign/rework."""
    tid = a.get('id') or ''
    if not tid:
        raise ValueError('work_done requires id')
    session = str(a.get('session') or _who(a) or '').strip()
    if not session:
        raise ValueError('work_done requires session (the working session id; '
                         'the lane records who worked, never a borrowed role '
                         'name)')
    payload = {'op': 'work_done', 'ticket_id': tid, 'session': session}
    if a.get('role'):
        payload['role'] = str(a.get('role'))
    if a.get('note'):
        payload['note'] = str(a.get('note'))
    if a.get('evidence_ref'):
        payload['evidence_ref'] = str(a.get('evidence_ref'))
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


# ---------- reconcile 探活三态（t261009-74：draining ≠ dead） ----------
# 结构化 kind 是唯一分类锚（review C1）：client.py 回执 {ok:false, error, kind}，
# kind ∈ no_poller / not_found / transient / internal / …——不匹配错误文案（自由
# 文本会漂移），未识别的 kind 一律 unknown（保槽），宁可少清不可误清。
_PROBE_KIND_NO_POLLER = 'no_poller'    # client.KIND_NO_POLLER（348 行族，直 spawn 面取字面量）
_PROBE_KIND_NOT_FOUND = 'not_found'    # workflow 已消亡=唯一可证死的读侧证据

_ENGINE_DATA_DIR = TEMP_POC / 'data'   # 专用 worker pidfile/meta 家（独立全局，
                                       # 测试可注入 tmp——TEMP_POC 还要装 shared.py）


def _holder_evidence(tid):
    """holder 的本机证据面（纯读）：pidfile 状态 + 进程死活 + worker meta 状态。

    文件形状真源=engine/ticket_worker.py（data/worker-<tid>.pid，旁车
    <pidfile>.meta）；该模块不在本票写集，这里按同形状只读复刻（读不到=不判定，
    绝不当不存在）。pidfile 四态由 shared.read_pidfile_state 判（live=进程活），
    meta 由 shared.read_worker_meta_state 判（state ∈ serving/draining，缺键=旧
    worker 读 serving——保守：serving+no_poller 落 unknown，不清账）。"""
    s = _shared()
    pidfile = _ENGINE_DATA_DIR / ('worker-%s.pid' % tid)
    pf = s.read_pidfile_state(pidfile)
    meta, meta_state, _detail = s.read_worker_meta_state(str(pidfile) + '.meta')
    pf_state = str(pf.get('state') or 'unknown')
    # 进程死活：live=alive；stale/absent=gone；malformed/读不了=不可证
    #（读不懂 ≠ 没有——绝不冒充「进程已亡」）。
    if pf_state == 'live':
        process = 'alive'
    elif pf_state in ('stale', 'absent'):
        process = 'gone'
    else:
        process = 'unknown'
    return {
        'probe': '',
        'pidfile': pf_state,
        'process': process,
        'pid': pf.get('pid'),
        'meta': meta_state,
        'meta_state': str((meta or {}).get('state') or '') if isinstance(meta, dict) else '',
        'meta_pid': (meta or {}).get('pid') if isinstance(meta, dict) else None,
    }


def _probe_verdict(kind, ev):
    """探活判定（纯函数，t261009-74 三态 + fail-closed unknown）。

    kind=探针回执的结构化 kind（''=query 有答）；ev=_holder_evidence 产出。
    返回 live / draining / dead / unknown——只有 dead 进 reconcile 清账单。"""
    if kind == '':
        return 'live'
    if kind == _PROBE_KIND_NOT_FOUND:
        return 'dead'   # workflow gone：Temporal 侧唯一可证死（本机进程死活无关）
    if kind == _PROBE_KIND_NO_POLLER:
        # 停轮询 + pidfile 活 + 旁车 meta 自证 draining 且 pid 对得上 → draining
        #（meta pid 比对挡 pidfile 指向回收 pid 的「陌生人」情形：对不上=unknown）。
        if ev.get('process') == 'alive' and ev.get('meta') == 'ok' \
                and ev.get('meta_state') == 'draining' \
                and ev.get('pid') is not None \
                and str((ev.get('meta_pid') or '')) == str(ev.get('pid')):
            return 'draining'
        if ev.get('process') == 'gone':
            return 'dead'   # 没轮询者 + 本机进程确已亡：真僵尸
        return 'unknown'    # 进程活但 meta 缺/畸形/serving，或进程死活不可证：保槽
    return 'unknown'        # transient / internal / 未知 kind：不清账（fail-closed）


def _concurrency(args):
    """t261004-32：项目并发上限的只读面 + 僵尸 holder 清账（CL-2/CL-3 面板消费）。

    - 缺省（reconcile 缺省 false）：read_state——上限、在持（含 human-hold）、
      队列位次与已等时长。面板只读账，不自己算队列（规则8）。
    - reconcile=true：逐个 holder 用只读 query 探活，判 **三态**（t261009-74，
      KI-01M4HMKZQ23649NFRTTFNCTRF6 / KI-01M4K9X2Z8W1A6CVB3QD7FHS4M）：
      live（query 有答）/ draining（worker 进程活着但停轮询——pidfile 活 + meta
      state=draining，宽停窗口内是**健康态**，保槽具名）/ dead（进程已亡）。
      只有 dead 是僵尸、只清 dead；其余探活失败（瞬时 RPC 等）= unknown——
      fail-closed 的语义是「未知不清账」，不是「未知即死亡」，绝不因探针一次
      抖动把健康票的槽让出去。dropped 逐条带证据（probe/pidfile/process），
      读者永远看不到裸票号。
    - order=[ticket ids]（CL-3 写脸，t261009-03）：路由到 engine concurrency.reorder
      ——唯一实现在引擎（置换校验/锁内写/具名拒收都在那里，本壳零二次校验），
      写后回读 read_state 同脸返回（面板拿新序比对，绝不本地算队列）。reconcile 与
      order 同给时 order 胜（显式写请求）。空 order 对非空队列=非置换，引擎具名拒收。

    身份闸（KI-193 在册欠账，诚实声明）：本 op 及其写路径只经 runAdminCli 直 spawn
    边界可达（console 宿主持 console 凭据拉起本 CLI），与 reconcile 清账写、CL-2b
    set_limit 同闸——不另设第二道闸。已知欠账：插件路由本身无 token 闸（KI-193
    未收），本边界是宿主进程spawn闸而非完整身份面。
    """
    project = str(args.get('project') or '').strip()
    if not project:
        raise ValueError('op=concurrency 需要 project（项目 key，声明按项目逐份判读）')
    conc = _concurrency_mod()
    if args.get('order') is not None:
        # CL-3 写脸：引擎 reorder 是唯一实现（置换校验/锁内写/具名拒收），本壳
        # 只路由；写后回读 read_state，面板拿到与读脸同形的新序（比对即过）。
        conc.reorder(project, args.get('order'))
        return conc.read_state(project)
    if not args.get('reconcile'):
        return conc.read_state(project)
    state = conc.read_state(project)
    alive = []
    draining = []
    unknown = []
    probe_errors = {}
    dropped_evidence = []
    for h in state.get('holders') or []:
        tid = str(h.get('ticket') or '')
        ev = _holder_evidence(tid)
        try:
            receipt = _poc('query', {'workflow_id': tid})
            if isinstance(receipt, dict) and receipt.get('ok'):
                alive.append(tid)          # live: the workflow answers
                continue
            kind = str((receipt or {}).get('kind') or '')
            note = str((receipt or {}).get('error') or receipt)[:160]
        except Exception as e:  # noqa: BLE001——spawn/解析层失败：不可证死，按 unknown 保槽
            kind, note = 'unknown', '%s: %s' % (type(e).__name__, str(e)[:160])
        verdict = _probe_verdict(kind, ev)
        if verdict == 'live':
            alive.append(tid)
        elif verdict == 'draining':
            draining.append(tid)
        elif verdict == 'dead':
            ev['probe'] = kind
            ev['ticket'] = tid
            dropped_evidence.append(ev)
            probe_errors[tid] = 'dead (kind=%s) %s' % (kind, note)
        else:  # unknown：fail-closed=不清账，具名留底等人看
            unknown.append(tid)
            probe_errors[tid] = 'kept (%s) %s' % (kind, note)
    out = conc.reconcile(project, alive, draining, unknown)
    out['probe_errors'] = probe_errors
    out['dropped_evidence'] = dropped_evidence
    out['decl'] = state.get('decl')
    return out


# ---------- repair hatch（t261009-13，slice 1：授权/记录/闸/认证债——不做机械落地） ----------
#
# 设计真源：docs/design/develop-buffer-v1.md 规则 26（全流程唯一快修口：宿主授权、
# 连同所修破损一起记账、票不可达、每次使用必留认证债）+ nongoal「不做第二条紧急通道」；
# 记录形状族 docs/reference/ledger-record-models-v1.md（certification 以修订集为身份
# ——覆盖关系是唯一清债机制）。引擎侧（server/engine/）不在本工单写集，故 slice 1
# 的 store 与 op 都在本文件自足实现；记录按 ledger 形状铸形，T1.2 认证驱动落地时
# 把 store 提升到 pull interface 之后是纯接线，不改读取方。
#
# 借鉴实现的故障模式取舍（review_plan R1 在案，这里只留结论）：
# - concurrency.py：整段 append 持锁（carried）、账本损坏 fail-closed 拒收（carried）、
#   整文档写回（dropped——append-only 台账重写全文件即违约）、僵死锁清扫（不需要：
#   flock 随 fd 存亡，无陈锁可清，写清扫器才是新故障）。
# - authz_gates.validate_authorization：who 先 .strip().lower() 再比对角色名与
#   '-agent' 后缀（carried，原文录入）、who 长度上限（carried，同常量）、
#   kind 白名单（dropped：本 op 只有唯一形状，kind 字段是第二扇门的挂件）。
# - _authorize：逐字段具名拒收 + 身份注入不落 op-local（carried）；「expires 只在
#   签发时判一次、下游不再复查」是本票要修的故障，**不 carried**——slice 1 只记录
#   expires（写入原值，单测钉回读一致），机械落地（T1.2 范围）必须在落地时刻拒绝
#   对已过期授权动手；过期授权的记录留在审计台账里——过期退役的是授权，不是事实。

_HATCH_FAMILY = 'hatch-authorisation-v1'      # 本 slice 唯一会写的记录族
_HATCH_CERT_FAMILY = 'certification-v1'       # T1.2 认证记录族（清债只认它；本 slice 不写）
_HATCH_LANDING_FAMILIES = (_HATCH_FAMILY,)    # 授予「认证外落地」的记录族全集——
                                              # 唯一快修口的断言锚（spec (e)）
_HATCH_MAX_REVISIONS = 32                     # 单次授权可点名的修订数上界
_HATCH_REVISION_MAX_LEN = 64                  # 单个修订标识长度上界（短 hash/分支名足够）


def _hatch_store_path(project_key):
    """项目 store 内的快修口台账路径（<perkey_projects_root>/<key>/hatch/…jsonl）。
    路径形状与 concurrency.py 的 per-key 同族；key 形状先过 PROJECT_KEY_RE 白名单，
    畸形 key 在碰文件之前拒收（concurrency._check_key 同序）。"""
    s = _shared()
    k = str(project_key or '').strip()
    if not k or not s.PROJECT_KEY_RE.match(k):
        raise ValueError('repair_hatch 需要 project（注册表 key，白名单 %s；收到 %r）'
                         % (s.PROJECT_KEY_RE.pattern, (k or '')[:64]))
    return s.perkey_projects_root() / k / 'hatch' / 'hatch_records.jsonl'


def _hatch_mint_id(now_ms, existing_ids):
    """铸造记录 id：hatch-<毫秒>-<4hex>，与既有 id 撞号则换尾重铸（id 永不复用、
    不按位置推导——fact ledger 身份纪律；同毫秒并发由锁内串行化兜底）。"""
    import random as _random
    for _ in range(8):
        cand = 'hatch-%d-%04x' % (int(now_ms), _random.getrandbits(16))
        if cand not in existing_ids:
            return cand
    raise ValueError('repair_hatch：id 铸造连续撞号 8 次（异常环境，拒绝落账）')


def _hatch_read_records(path):
    """fail-closed 读台账：文件缺失=空列表（尚未开张是合法态）；任何一行坏 JSON /
    非对象 / 缺 v 或 id = 点名行号的结构化拒收——绝不把损坏读成空账（concurrency
    同纪律：unreadable ledger is a refusal, not an empty read）。返回 (records, ids)。"""
    p = Path(path)
    if not p.exists():
        return [], set()
    records, ids = [], set()
    with p.open('r', encoding='utf-8') as f:
        for lineno, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError as e:
                raise ValueError('repair_hatch 台账损坏：%s 第 %d 行不是合法 JSON（%s）'
                                 '——fail-closed 拒收，绝不静默当空账' % (p, lineno, e))
            if not isinstance(rec, dict) or not rec.get('v') or not rec.get('id'):
                raise ValueError('repair_hatch 台账损坏：%s 第 %d 行缺 v|id 或不是对象'
                                 '——fail-closed 拒收' % (p, lineno))
            if rec['id'] in ids:
                raise ValueError('repair_hatch 台账损坏：%s 第 %d 行 id 重复（%s）'
                                 '——id 一旦铸出永不复用' % (p, lineno, rec['id']))
            ids.add(rec['id'])
            records.append(rec)
    return records, ids


def _hatch_families(records):
    """台账里出现过的记录族集合（去重）；供唯一快修口断言与覆盖读取共用。"""
    return set(str(r.get('v') or '') for r in records)


def assert_single_hatch(families):
    """「全流程只有一扇快修口」的断言（spec (e)：asserted, not promised）。
    授予认证外落地的记录族全集=_HATCH_LANDING_FAMILIES；出现第二个此类族 =
    结构化拒收。写路径每次落账前跑一遍；单测另用伪造族表钉它的拒收分支。"""
    extra = set(families or ()) - set(_HATCH_LANDING_FAMILIES) - {_HATCH_CERT_FAMILY}
    if extra:
        raise ValueError(
            'repair_hatch：台账出现认证外落地授权族之外的未知族 %s——第二扇紧急通道'
            '就地拒收（全流程只允许一扇快修口，develop-buffer 规则 26）' % sorted(extra))


def _hatch_locked(path, exclusive=True):
    """flock 守护的台账访问：lock 文件与台账同目录同名 .lock 后缀（与 concurrency
    的 <key>/concurrency-state.lock 不同位，无碰撞面）；flock 随 fd 存亡故无陈锁、
    无清扫器；unlock+close 在 finally，正常/报错/拒收每条路径都收全终态。
    exclusive=True 供写（锁跨整个 append，不产生撕裂行）；False 供读（共享锁）。"""
    import contextlib
    import fcntl
    p = Path(path)
    @contextlib.contextmanager
    def _guard():
        p.parent.mkdir(parents=True, exist_ok=True)
        lock_fh = open(str(p) + '.lock', 'a+')
        try:
            fcntl.flock(lock_fh, fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH)
            yield lock_fh
        finally:
            fcntl.flock(lock_fh, fcntl.LOCK_UN)
            lock_fh.close()
    return _guard()


def _hatch_append(path, record):
    """锁内追加一行（整行一次 write，锁保跨写者不撕裂）；追加前跑唯一口断言——
    台账里已出现未知族时，连合法追加也一并拒收（先把第二扇门钉死再谈开门）。"""
    records, ids = _hatch_read_records(path)
    assert_single_hatch(_hatch_families(records))
    record['id'] = _hatch_mint_id(record['at'], ids)
    line = json.dumps(record, ensure_ascii=False, sort_keys=True)
    with _hatch_locked(path, exclusive=True):
        with open(str(path), 'a', encoding='utf-8') as f:
            f.write(line + '\n')
            f.flush()
    return record['id']


def _hatch_check_who(a):
    """操作人校验（authz_gates.validate_authorization 同口径的薄镜像）：by|who 双读、
    非空、≤AUTHZ_WHO_MAX_LEN；先 .strip().lower() 归一再比对 agent 角色名与 '-agent'
    后缀（Host / HOST / host-AGENT 同拒）；入账记原文不记归一形。返回原文 who。"""
    s = _shared()
    who = _who(a)
    if not who.strip():
        raise ValueError('repair_hatch 需要 by|who（宿主授权人身份由调用方注入，不得留空）')
    if len(who) > s.AUTHZ_WHO_MAX_LEN:
        raise ValueError('repair_hatch 的 by|who 超限（%d > %d 字符）'
                         % (len(who), s.AUTHZ_WHO_MAX_LEN))
    norm = who.strip().lower()
    if norm in s.AUTHZ_AGENT_ROLE_NAMES:
        raise ValueError('repair_hatch 拒收：%r 是 agent 角色名——快修口只认宿主授权，'
                         'agent 不得自授权（与既有 authorize 同一条不自我授权规则）' % who)
    if norm.endswith('-agent'):
        raise ValueError('repair_hatch 拒收：%r 落在 agent 显示名族（-agent 后缀）——'
                         '快修口只认宿主授权' % who)
    return who


def _hatch_parse_expires(raw):
    """expires 解析：epoch 秒（int/float/纯数字串）或 ISO8601；解析失败/过去时刻
    具名拒收（授权必须到期作废，且不许签发生来已过期的授权）。返回 epoch 秒 int。"""
    if raw in (None, ''):
        raise ValueError('repair_hatch 需要 expires（epoch 秒或 ISO8601——授权必须到期作废）')
    if isinstance(raw, bool):
        raise ValueError('repair_hatch 的 expires 形状非法（bool）：%r' % (raw,))
    try:
        if isinstance(raw, (int, float)) or (isinstance(raw, str) and raw.strip().isdigit()):
            exp = int(float(raw))
        else:
            import datetime
            exp = int(datetime.datetime.fromisoformat(str(raw).strip())
                      .replace(tzinfo=datetime.timezone.utc).timestamp())
    except ValueError as e:
        if 'expires' in str(e):
            raise
        raise ValueError('repair_hatch 的 expires 解析失败（epoch 秒或 ISO8601）：%r' % (raw,))
    if exp <= int(time.time()):
        raise ValueError('repair_hatch 的 expires 已是过去时刻（%d）——不许签发生来已过期的授权' % exp)
    return exp


def _hatch_check_breakage(a):
    """所修破损校验：known_issue（KI- id，两形状 KI-<n>/KI-<ULID> 皆合法身份，
    存在性对 notes/debts/known-issues.md 只读核对，未登记=具名拒收）或非空 description；
    二者恰给其一。返回 {'known_issue':…} 或 {'description':…}（入账形状）。"""
    br = a.get('breakage')
    ki = desc = None
    if isinstance(br, dict):
        ki = str(br.get('known_issue') or '').strip() or None
        desc = str(br.get('description') or '').strip() or None
    elif isinstance(br, str) and br.strip():
        # 平铺字符串缺省按 KI id 解释（以 KI- 开头），否则按描述——人话入口不设第二 op
        raw = br.strip()
        ki, desc = (raw, None) if raw.upper().startswith('KI-') else (None, raw)
    if ki is None:
        ki = str(a.get('known_issue') or '').strip() or None
    if desc is None:
        desc = str(a.get('breakage_description') or '').strip() or None
    if ki and desc:
        raise ValueError('repair_hatch 的 breakage 只收其一：known_issue 或 description（两个都给=歧义拒收）')
    if ki:
        if not re.match(r'^KI-[0-9A-Za-z]+$', ki):
            raise ValueError('repair_hatch 的 known_issue 形状非法（KI-<n> 或 KI-<ULID>）：%r' % ki[:64])
        # 261020 (host order): the ledger lives in the project store, outside git.
        # A pin file in the repo still counts (a pinned entry is a recorded fact),
        # so both are consulted; neither present = the id is not recorded.
        ki_texts = []
        for _cand in _ki_ledger_paths():
            try:
                ki_texts.append(_cand.read_text(encoding='utf-8', errors='replace'))
            except OSError:
                continue
        if not ki_texts or not any(_ki_known_in(ki, t) for t in ki_texts):
            raise ValueError('repair_hatch 拒收：known_issue %s 未在 KI 账本登记'
                             '（破损必须是已记账事实，不是口头形容；账本在项目 store 的 '
                             'kb/known-issues.md，仓内只留 pinned 条目）' % ki)
        return {'known_issue': ki}
    if desc:
        return {'description': desc}
    raise ValueError('repair_hatch 需要 breakage（known_issue: KI-… id 或 description 非空描述'
                     '——授权记录必须能回答修的是什么）')


def _ki_ledger_paths():
    """The KI ledger candidates, store first (261020): every path that exists."""
    out = []
    try:
        root = pathlib.Path(os.path.expanduser("~/.sandbar/projects"))
        for key_dir in sorted(root.iterdir()):
            for name in ("known-issues.jsonl", "known-issues.md"):
                cand = key_dir / "kb" / name
                if cand.is_file():
                    out.append(cand)
    except OSError:
        pass
    pinned = REPO / 'notes' / 'debts' / 'known-issues.md'
    if pinned.is_file():
        out.append(pinned)
    return out


def _ki_known_in(ki, text):
    """known-issues.md 登记表核对（纯函数，文本注入便于单测）：id 出现在表行首列
    （| KI-… |）即视为已登记——不解析表语义，只做存在性。"""
    for line in text.splitlines():
        stripped = line.strip()
        # a table row (the pinned/legacy shape) or a jsonl record (the store shape)
        if stripped.startswith('|') and re.match(r'^\|\s*%s\s*\|' % re.escape(ki), stripped):
            return True
        if stripped.startswith('{') and ('"id": "%s"' % ki) in stripped:
            return True
    return False


def _hatch_check_revisions(a):
    """修订（集）校验：数组或逗号串，1..N 条，逐条非空白且 ≤ 长度上界；返回去重
    有序列表（集合语义：落地的身份是修订集本身，与顺序无关）。"""
    raw = a.get('revisions')
    if isinstance(raw, str):
        parts = raw.split(',')
        if any(not p.strip() for p in parts):
            raise ValueError('repair_hatch 的 revisions 串含空段（%r）——逗号分隔须逐段非空'
                             % raw[:80])
        raw = [p.strip() for p in parts]
    if not isinstance(raw, list) or not raw:
        raise ValueError('repair_hatch 需要 revisions（数组或逗号分隔串：本次授权将落地的修订/修订集）')
    out = []
    for r in raw:
        r = str(r).strip()
        if not r:
            raise ValueError('repair_hatch 的 revisions 含空白条目')
        if len(r) > _HATCH_REVISION_MAX_LEN:
            raise ValueError('repair_hatch 的 revisions 条目超长（%d > %d）：%s…'
                             % (len(r), _HATCH_REVISION_MAX_LEN, r[:24]))
        if r not in out:
            out.append(r)
    if len(out) > _HATCH_MAX_REVISIONS:
        raise ValueError('repair_hatch 的 revisions 条目过多（%d > %d）'
                         % (len(out), _HATCH_MAX_REVISIONS))
    return out


_HATCH_TICKET_DIR_RE = re.compile(r'^t\d{6}-\d+')


def caller_from_ticket_path(cwd, repo_root, lane_roots):
    """票路径闸（spec (b)，纯函数）：调用方 cwd（realpath）命中任一形状即拒——
    ① 任一注入泳道根之下；② 本 checkout 的 .lane/ 之下；③ 路径中某段为 `.lane`
    且其下紧邻一段是票 worktree 目录名（t<n>-<n>…），而该 worktree 不是本工具
    自身所在的 checkout（集成闸在泳道 worktree 里跑本文件，cwd=checkout 根必须
    放行——闸判的是「别的票的泳道」，不是「引擎自己住的地方」）＝票会话在给
    自己开快修口，具名拒收。诚实边界：cwd 是本 slice 唯一有的出处信号——先改
    目录再调用的调用方不被此闸捕获，更强出处证明（spawn 链随行的会话身份）属
    引擎侧工作，不在本票写集（review R4 在案）。"""
    c = os.path.realpath(str(cwd or ''))
    parts = c.split(os.sep)
    for i, seg in enumerate(parts):
        if seg != '.lane':
            continue
        root = os.sep.join(parts[:i + 1])   # .lane 本体
        if i + 1 < len(parts) and _HATCH_TICKET_DIR_RE.match(parts[i + 1]):
            if os.path.realpath(str(repo_root or '')) != os.sep.join(parts[:i + 2]):
                return True                 # 别的 checkout 的票泳道（含 c 即其根）→ 拒
            continue                        # 本 checkout 自己的泳道根＝引擎家；更深路径里
                                            # 若还有 .lane，交给后续迭代判（勿 break 漏判）
        if c == root or c.startswith(root + os.sep):
            return True                     # 本 checkout .lane/ 之下（含 .lane 本体）→ 拒
    for root in list(lane_roots or []):
        r = os.path.realpath(str(root))
        if r and (c == r or c.startswith(r + os.sep)):
            return True
    return False


def _hatch_covered_by(debt_revisions, records, project_key):
    """覆盖判定（清债唯一机制，纯函数）：存在族=certification-v1 的记录，其修订集
    覆盖债的修订全集（同一项目内）→ 返回该认证 id；否则 None。cert 记录形状按
    ledger-record-models 的认证行（revisions 集合字段；T1.2 落地时同一形状入账）。"""
    want = set(debt_revisions)
    for rec in records:
        if str(rec.get('v') or '') != _HATCH_CERT_FAMILY:
            continue
        if str(rec.get('project') or '') != project_key:
            continue
        have = set(str(x) for x in (rec.get('revisions') or []))
        if want and want <= have:
            return str(rec.get('id') or '')
    return None


def _hatch_debt_view(records, project_key):
    """认证债可读面（spec d）：每条 hatch 授权=一条债，covered_by=覆盖它的认证 id
    （None=在账未清）。outstanding 列表由此派生——清债是推导不是命令，故「只有
    一种清法」是结构性质而非约定。"""
    now = int(time.time())
    out = []
    for rec in records:
        if str(rec.get('v') or '') != _HATCH_FAMILY:
            continue
        covered = _hatch_covered_by(rec.get('revisions') or [], records, project_key)
        out.append({
            'id': str(rec.get('id') or ''),
            'by': str(rec.get('by') or ''),
            'at': int(rec.get('at') or 0),
            'breakage': rec.get('breakage') if isinstance(rec.get('breakage'), dict) else {},
            'revisions': [str(x) for x in (rec.get('revisions') or [])],
            'expires': int(rec.get('expires') or 0),
            'expired': int(rec.get('expires') or 0) <= now,
            'outstanding': covered is None,
            'covered_by': covered,
        })
    return out


def _repair_hatch(a):
    """快修口唯一 op（spec a-e）：宿主授权一次认证外落地——逐字段具名拒收 →
    票路径闸 → 锁内追加一条 hatch-authorisation-v1 记录（who/所修破损/修订集/
    到期/时刻全在记录里，审计不必读对话）。slice 1 不做机械落地；expires 在本层
    只记录（签发时须在未来），落地时刻的过期复查属 T1.2（模块头注释在案）。"""
    project = str(a.get('project') or '').strip()
    if not project:
        raise ValueError('repair_hatch 需要 project（目标项目 key，无默认值）')
    who = _hatch_check_who(a)
    if caller_from_ticket_path(os.getcwd(), REPO, []):
        raise ValueError('repair_hatch_refused_from_ticket_path：调用方 cwd 在票泳道路径下'
                         '——票永不为自己开快修口（与 authorize 同一条不自我授权规则，'
                         '由宿主会话/控制台面发起）')
    breakage = _hatch_check_breakage(a)
    revisions = _hatch_check_revisions(a)
    expires = _hatch_parse_expires(a.get('expires'))
    path = _hatch_store_path(project)
    record = {'v': _HATCH_FAMILY, 'at': int(time.time() * 1000), 'project': project,
              'by': who, 'breakage': breakage, 'revisions': revisions,
              'expires': expires, 'kind': 'repair_hatch'}
    rec_id = _hatch_append(path, record)
    return {'hatch_id': rec_id, 'project': project, 'by': who, 'breakage': breakage,
            'revisions': revisions, 'expires': expires,
            'note': 'certification debt opened; the next certification must cover '
                    'these revisions (wiring lands with the certification driver, T1.2)'}


def _hatch_debts(a):
    """认证债只读面（spec d：named, queryable fact；授不了任何权）：outstanding
    列表 + 每条债的覆盖状态；T1.2 认证入账后同一张脸自动反映清账，无 clear 命令。"""
    project = str(a.get('project') or '').strip()
    if not project:
        raise ValueError('hatch_debts 需要 project（目标项目 key）')
    path = _hatch_store_path(project)
    with _hatch_locked(path, exclusive=False):
        records, _ids = _hatch_read_records(path)
    assert_single_hatch(_hatch_families(records))
    debts = _hatch_debt_view(records, project)
    return {'project': project, 'count': len(debts),
            'outstanding_count': len([d for d in debts if d['outstanding']]),
            'debts': debts}


def _dismiss_restore(a, action):
    """t261009-31 人工处置失败票：dismiss（摘出板面）/ restore（撤回摘除）。

    契约：人工动作——who/by 必填非空且非 agent 角色名、reason 必填非空（绝不默认），
    这些在 CLI 层先具名拒收一遍（引擎层同规则复核）；工单存在性走存在闸
    （t261016-10 双源人口=engine ticket-list ∪ 巡检台账：储备/被超票如 t261008-17
    只活在巡检店，单看 ticket-list 会「按了没用」；两源全不可得=拒收，绝不静默
    跳过闸）；只记 audit journal（append-only），绝不发 workflow 信号、不改状态机、
    不写票 meta——workflow 自己的历史仍是票怎么结束的真源。拒绝路径零写入。"""
    tid = str(a.get('id') or '').strip()
    if not tid:
        raise ValueError('%s 需要 id（工单 id 必填）' % action)
    who = str(a.get('by') or a.get('who') or '').strip()
    if not who:
        raise ValueError('%s 需要 who/by（人工签名必填——无签名的人工处置绝不收）' % action)
    reason = str(a.get('reason') or '').strip()
    if not reason:
        raise ValueError('%s 需要 reason（处置理由必填非空，绝不默认）' % action)
    mod = _ticket_dismiss_mod()
    known, sources = _dismiss_ticket_population()
    if known is None:
        raise ValueError('%s 拒收：无法核验工单存在（ticket-list 与巡检台账均不可得）'
                         '——存在闸宁拒不猜' % action)
    fn = mod.dismiss_ticket if action == 'dismiss' else mod.restore_ticket
    res = fn(mod.journal_dir(), ticket_id=tid, who=who, reason=reason,
             known_ticket_ids=known)
    if not res.get('ok'):
        raise ValueError(res.get('error') or '%s refused' % action)
    res['population_sources'] = sources
    return res


def _ticket_dismiss_mod():
    """engine ticket_dismiss 模块单点（lazy import，与 _poc 同目录族）。"""
    import importlib
    import sys as _sys
    engine_dir = str(TEMP_POC)
    if engine_dir not in _sys.path:
        _sys.path.insert(0, engine_dir)
    return importlib.import_module('ticket_dismiss')


def _inspection_ticketing_mod():
    """engine inspection_ticketing 模块单点（lazy import，同族纪律；读面不触发
    任何 workflow 依赖——该模块本体零 workflow import）。"""
    import importlib
    import sys as _sys
    engine_dir = str(TEMP_POC)
    if engine_dir not in _sys.path:
        _sys.path.insert(0, engine_dir)
    return importlib.import_module('inspection_ticketing')


def _dismiss_ticket_population():
    """存在闸人口（t261016-10）：engine ticket-list 全量 ∪ 巡检台账可证票号
    （shared.INSPECTION_DIR 下的 *.ticket 指针 + inspection-spawn.jsonl /
    inspection-reopen.jsonl）。返回 (population, sources)：
    population=None 仅当**两源都不可得**（ticket-list 查挂且巡检店读挂）——按 id
    fail-closed：任一源可读，人口即成立；id 不在人口由引擎层具名拒收（点名两源）。
    只读，不缓存（每次处置现查，防陈旧名单放行幽灵票）。"""
    dev = _known_ticket_ids()          # None = ticket-list 不可得
    inspection, insp_ok = set(), False
    try:
        mod = _inspection_ticketing_mod()   # 先入 sys.path，shared 才可解析
        import shared  # lazy：INSPECTION_DIR 走 SANDBAR_INSPECTION_DIR 覆盖链
        inspection = mod.inspection_known_ticket_ids(shared.INSPECTION_DIR)
        insp_ok = True
    except Exception:
        insp_ok = False                # 巡检店读挂：不炸，退化成单源闸
    if dev is None and not insp_ok:
        return None, []
    sources = (['engine-ticket-list'] if dev is not None else []) + \
              (['inspection-store'] if insp_ok else [])
    return ((dev or set()) | inspection), sources


def _known_ticket_ids():
    """存在闸人口：engine ticket-list 全量 id 集（None=列表不可得，调用方拒收）。
    只读，不缓存（每次处置现查，防陈旧名单放行幽灵票）。"""
    try:
        out = _poc('ticket-list', {})
    except Exception:
        return None
    if not out.get('ok'):
        return None
    rows = (out.get('result') or {}).get('tickets') or []
    return {str(r.get('id') or '').strip() for r in rows} - {''}


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
    if op == 'work_done':
        return _work_done(args)
    if op == 'cancel':
        return _cancel(args)
    if op == 'close_out':
        return _close_out(args)
    if op == 'cancel-audit':
        return _cancel_audit(args)
    if op in ('pause', 'resume'):
        return _pause_resume(args, op)
    if op == 'concurrency':
        return _concurrency(args)
    if op == 'repair_hatch':
        return _repair_hatch(args)
    if op == 'hatch_debts':
        return _hatch_debts(args)
    if op == 'dismiss':
        return _dismiss_restore(args, 'dismiss')
    if op == 'restore':
        return _dismiss_restore(args, 'restore')
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
                     '/pause/resume/cancel/dismiss/restore/repair_hatch/hatch_debts'
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


def _sanitize_text(obj):
    """入界消毒（宿主令 261002，与 client.py:_sanitize_text 同文同铁律）：
    调用方 payload 里的字符串先做「不可编码字符→可见转义」归一再进引擎——
    实证案例：t261001-23 的 retry_qc reason 携 lone surrogate 入史，读侧一崩
    就是整票不可读。坏字符只许变得可见（\\udcXX），不许带走整条回执/票史。"""
    if isinstance(obj, str):
        return obj.encode("utf-8", "backslashreplace").decode("utf-8")
    if isinstance(obj, list):
        return [_sanitize_text(v) for v in obj]
    if isinstance(obj, tuple):
        return tuple(_sanitize_text(v) for v in obj)
    if isinstance(obj, dict):
        return {_sanitize_text(k): _sanitize_text(v) for k, v in obj.items()}
    return obj


def _cli(argv):
    """直 spawn 入口，返回进程退出码。"""
    if not argv or argv[0] in ('-h', '--help', 'help'):
        print(json.dumps({'ok': False, 'error': _TICKET_CLI_USAGE}, ensure_ascii=False))
        return 2
    try:
        payload = _sanitize_text(json.loads(argv[0]))   # 入界消毒：坏字符不许进引擎/票史
    except json.JSONDecodeError as e:
        print(json.dumps({'ok': False, 'error': '参数不是合法 JSON：%s' % e},
                         ensure_ascii=False).encode("utf-8", "backslashreplace").decode("utf-8"))
        return 1
    if not isinstance(payload, dict):
        print(json.dumps({'ok': False, 'error': '参数需为 JSON 对象（含 op）'},
                         ensure_ascii=False).encode("utf-8", "backslashreplace").decode("utf-8"))
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
    # 回执出口做「不可编码字符→可见转义」兜底（宿主令 261002，与 client.py:_emit
    # 同族同修）：票面/历史可能带 lone surrogate，ensure_ascii=False 的 JSON 直上
    # stdout 会 UnicodeEncodeError 崩掉整条回执（t261001-23 整票不可读的第二现场）。
    # backslashreplace 把坏字符变 \udcXX 可见转义，其余内容逐字节不变。
    print(json.dumps(out, ensure_ascii=False)
          .encode("utf-8", "backslashreplace").decode("utf-8"))
    return _exit_code(out)


if __name__ == '__main__':
    import sys
    sys.exit(_cli(sys.argv[1:]))
