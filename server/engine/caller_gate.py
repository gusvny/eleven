"""caller_gate — 跨项目写操作闸：调用方身份解析与判定矩阵（t260915-12）。

层次与真源：
  - 常量与 workflow 侧纯判定在 shared.py（CALLER_PROJECT_ENV / CALLER_UNDECLARED_MARK /
    UNDECLARED_POLICY / 上限常量 / cross_project_judge）——worker 沙箱只依赖 shared；
  - 本模块=**client 侧**的解析与判定：身份解析顺序（显式参数 > env > cwd 窄兜底 >
    未声明）。cwd 兜底带**仓树排除**（shared.project_key_for_dir）：client 直跑于真实
    项目工作区时 cwd 可推导身份（出处=cwd×注册表）；cwd 落在引擎仓树内（dsh 工具链
    spawn、console 插件等间接调用）一律不推导——仓内 cwd 标识「被调用的引擎」而非
    「调用方会话」，宁 undeclared 不凭空造身份（review C1 行为红线）。纯函数为主，
    shared 以外零依赖（KI-032 单一真源纪律）。

口径（工单验收与 review 条件的落点）：
  - 身份不许凭空自认：值必须过 PROJECT_KEY_RE 形状白名单；形状非法的显式声明/env
    =结构化拒收（误配显式暴露，不静默当 undeclared）。
  - 形状合法但注册表查无此 key：**仍按 declared 处理**（review C2②：不匹配即拒、
    误配显式暴露，fail-closed 方向），回执附 caller_project_registered=false 观测键。
  - 目标票 project 读取失败≠越权（KI-025）：瞬时失败=KIND_TRANSIENT 可重试，不存在=
    KIND_NOT_FOUND，闸不把抖动当越权（客户端把这些归 client.py 的既有分级）。
  - undeclared 策略：shared.undeclared_policy()（旋钮 SANDBAR_UNDECLARED_POLICY，缺省
    "refuse"——t260925-08 翻严；record=旋钮显式选入的过渡记名）。
"""
from typing import Any, Dict, Optional, Tuple

import os

import shared


def _norm(path: str) -> str:
    """路径归一（realpath）；空/异常→空串（探测路径坏掉=不推导，不炸）。"""
    try:
        return os.path.realpath(str(path or ""))
    except Exception:  # noqa: BLE001
        return ""

# 判定决策（judge_caller 返回值 decision 字段）：
#   pass             放行（declared 同项目 / 无比对对象）
#   pass_override    放行+越权记名（declared 异项目+旗）
#   record_undeclared 放行+undeclared 记名（哨兵盖章，workflow 侧落账）
#   refuse           拒收（declared 异项目无旗 / 畸形旗 / undeclared 且策略=refuse）


class CallerIdentityError(ValueError):
    """调用方身份声明形状非法（显式参数/env 值不过 PROJECT_KEY_RE）。fail-closed：
    误配显式暴露给人话，不静默回落 undeclared。"""


def _check_shape(value: str, origin: str) -> str:
    v = str(value or "").strip()
    if not v:
        raise CallerIdentityError(
            "调用方项目身份（%s）为空/纯空白——要么删除该声明（=未声明身份，按策略记名/拒收），"
            "要么给合法项目 key（白名单：小写字母/数字/中划线）" % origin)
    if len(v) > 64 or not shared.PROJECT_KEY_RE.match(v):
        raise CallerIdentityError(
            "调用方项目身份形状非法：%r（来自 %s；白名单 %s）——修正 %s 或调用方注入链后重试"
            % (v[:64], origin, shared.PROJECT_KEY_RE.pattern, origin))
    return v


def resolve_identity(explicit: str, env_raw: str,
                     cwd: str = "", exclude_trees: Tuple[str, ...] = (),
                     projects: Optional[list] = None) -> Dict[str, Any]:
    """调用方身份解析（单一入口）。优先级：显式参数 > env > cwd 窄兜底（cwd 落在
    排除树（引擎仓树）内=不推导）> 未声明。

    返回 {"value": key|shared.CALLER_UNDECLARED_MARK 对应前的原始空, "src": "arg"|"env"|"cwd"|"none",
          "identity_class": "declared"|"undeclared"}——value 为 "" 即 undeclared（盖章时
    由调用方换成 shared.CALLER_UNDECLARED_MARK 哨兵）。形状非法即刻 raise（fail-closed）。"""
    if str(explicit or "").strip():
        return {"value": _check_shape(explicit, "显式参数 caller_project"),
                "src": "arg", "identity_class": "declared"}
    if str(env_raw or "").strip():
        return {"value": _check_shape(env_raw, "env %s" % shared.CALLER_PROJECT_ENV),
                "src": "env", "identity_class": "declared"}
    if str(cwd or "").strip():
        key = shared.project_key_for_dir(_norm(cwd), projects or [],
                                         tuple(_norm(t) for t in exclude_trees))
        if key:
            return {"value": key, "src": "cwd", "identity_class": "declared"}
    return {"value": "", "src": "none", "identity_class": "undeclared"}


def validate_override(args: Dict[str, Any]) -> Tuple[Optional[Dict[str, str]], str]:
    """越权旗归一与校验（review C3/C4：by/reason 必填非空+上限；畸形旗=拒收不静默）。

    接受两形：args["cross_project"]={"by","reason"}（结构形，schema 主形——**by 严格
    必填，不从 args.who 兜底**：旗在场却缺记名人=畸形，fail-closed 拒收，防「who 是
    操作人、by 是越权人」两个语义被悄悄合并）或 args["cross_project_reason"]（扁平形，
    CLI 人体工学；by 缺省取 args["by"]|args["who"]——同一次调用里操作人与越权人显式
    合一，由调用方自认）。
    返回 ({"by","reason"}|None, err)；旗不在场=(None, "")。"""
    flag = args.get("cross_project")
    flat_reason = str(args.get("cross_project_reason") or "").strip()
    if flag is None and not flat_reason:
        return None, ""
    by, reason = "", ""
    if isinstance(flag, dict):
        by = str(flag.get("by") or "").strip()
        reason = str(flag.get("reason") or "").strip()
    elif flag is not None:
        return None, ("越权旗 cross_project 需为对象 {by, reason}（收到 %s）——"
                      % type(flag).__name__)
    if flat_reason:
        if reason:
            return None, "越权旗理由重复：cross_project.reason 与 cross_project_reason 只给其一"
        reason = flat_reason
        by = str(args.get("by") or args.get("who") or "").strip()  # 扁平形才兜底
    if not by:
        return None, "越权旗缺 by（谁在越权——旗必须记名）；也可用 flat 形 cross_project_reason 让 by 取操作人 by|who"
    if not reason:
        return None, "越权旗缺 reason（为什么跨项目——理由必填，记名留痕可查）"
    if len(by) > shared.CROSS_PROJECT_BY_LIMIT:
        return None, "越权旗 by 超限（%d > %d 字符）" % (len(by), shared.CROSS_PROJECT_BY_LIMIT)
    if len(reason) > shared.CROSS_PROJECT_NOTE_LIMIT:
        return None, ("越权旗 reason 超限（%d > %d 字符）——拆条后在目标票 ruling/pending 补充"
                      % (len(reason), shared.CROSS_PROJECT_NOTE_LIMIT))
    return {"by": by, "reason": reason}, ""


def judge_caller(identity: Dict[str, Any], target: str,
                 override: Optional[Dict[str, str]]) -> Dict[str, Any]:
    """客户端判定矩阵（唯一权威实现；README 的矩阵表是它的文档投影）。

    identity=resolve_identity 输出；target=目标票 project（""=引擎件无项目面）；
    override=validate_override 输出。返回：
      {"decision", "why", "stamp", "notice", "override_used"}
      stamp=应盖进信号载荷的 caller_project 值（declared=key；undeclared=哨兵；
      拒收路径无意义）。target=""（engine-internal）时恒 pass——调用量身记
      identity_class=engine-internal 由调用方（client.py）覆写。"""
    value = str(identity.get("value") or "")
    iclass = str(identity.get("identity_class") or "undeclared")
    target = str(target or "")
    if iclass == "undeclared":
        # target=""（引擎件无项目面）=无比对对象，恒放行（与 declared 同项目口径一致；
        # t260925-08 零回归：cancel 打在无 ProjectKey SA 的引擎件上仍是 pass，stamp 用
        # 哨兵保留身份信息面，identity_class=engine-internal 由调用方覆写）。策略解析
        # 只对有比对对象的写生效——引擎件不该被「调用方没声明项目」卡死。
        if not target:
            return {"decision": "pass", "why": "", "stamp": shared.CALLER_UNDECLARED_MARK,
                    "notice": "", "override_used": False}
        # t260925-08：策略走 undeclared_policy() 单点（旋钮 env；缺省=refuse）。
        # 旋钮畸形值不外抛——转结构化拒收（人话点名误配原文），client 侧同形状回执（N3）。
        try:
            policy = shared.undeclared_policy()
        except ValueError as e:
            return {"decision": "refuse",
                    "why": "跨项目闸：%s（策略误配 fail-closed 拒收）" % e,
                    "stamp": "", "notice": "", "override_used": False}
        if policy == "refuse":
            return {"decision": "refuse",
                    "why": "跨项目闸：调用方项目身份未声明（%s 未注入且无显式参数），"
                           "引擎策略=拒收——经注入链/包装层声明调用方项目后再操作"
                           % shared.CALLER_PROJECT_ENV,
                    "stamp": "", "notice": "", "override_used": False}
        return {"decision": "record_undeclared", "why": "",
                "stamp": shared.CALLER_UNDECLARED_MARK,
                "notice": ("未声明调用方项目身份（%s 未注入且无显式参数），本次写操作按"
                           "记名放行策略处理（经旋钮 %s=record 显式选入；缺省策略=拒收；"
                           "注入契约见 server/engine/README.md）"
                           % (shared.CALLER_PROJECT_ENV, shared.UNDECLARED_POLICY_ENV)),
                "override_used": False}
    # declared
    if not target:
        return {"decision": "pass", "why": "", "stamp": value,
                "notice": "", "override_used": False}
    if value == target:
        return {"decision": "pass", "why": "", "stamp": value,
                "notice": "", "override_used": False}
    if override is None:
        return {"decision": "refuse",
                "why": "跨项目写操作拒收：调用方项目身份 %s 与目标票所属项目 %s 不符，"
                       "且未带越权旗——只操作本项目的票；确需跨项目走显式越权旗"
                       " cross_project={by, reason 必填}（记名留痕可查）" % (value, target),
                "stamp": "", "notice": "", "override_used": False}
    return {"decision": "pass_override", "why": "",
            "stamp": value,
            "notice": ("跨项目越权记名：调用方项目 %s 操作项目 %s 的票（by=%s，理由=%s）"
                       % (value, target, override["by"], override["reason"][:120])),
            "override_used": True}


def identity_receipt(identity: Dict[str, Any], verdict: Dict[str, Any],
                     identity_class: str = "") -> Dict[str, Any]:
    """回执身份键（单一构造点；admin.log 行键由 _emit 从回执同键提取，audit.py 落账）。

    injected_by（t260925-08）：**尽力面标签，非安全断言**——只当 identity_src=env 时给，
    值域 {lane-agent, external-env}：env 伴随 CALLER_SURFACE_ENV="lane-agent"（引擎
    spawn 链注入时设置）→ lane-agent，否则 external-env（手工旁路设 env 也落此值）。
    标签只回答「身份从哪个面进来」，不回答「谁注入的」——审计不得单凭此键下
    「谁操作」断言（安全断言归 spawn 链注入 + 越权旗 by/reason 必填两机制）。"""
    iclass = identity_class or str(identity.get("identity_class") or "undeclared")
    keys = {
        "caller_project": str(verdict.get("stamp") or identity.get("value") or ""),
        "identity_src": str(identity.get("src") or "none"),
        "identity_class": iclass,
    }
    if keys["identity_src"] == "env":
        keys["injected_by"] = shared.CALLER_SURFACE_LANE_AGENT \
            if str(os.environ.get(shared.CALLER_SURFACE_ENV) or "").strip() \
            == shared.CALLER_SURFACE_LANE_AGENT else "external-env"
    if keys["caller_project"] == shared.CALLER_UNDECLARED_MARK:
        keys["caller_project"] = ""  # 回执面向人：undeclared 用空值+identity_class 表达
    if verdict.get("override_used"):
        keys["cross_project_used"] = True
    if verdict.get("notice"):
        keys["cross_project_notice"] = verdict["notice"]
    return keys
