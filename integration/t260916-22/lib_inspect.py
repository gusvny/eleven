"""t260916-22 inspect 段场景共享夹具与驱动（无 sc_ 前缀=共享代码，不登记场景清单）。

三态纪律（t260904-12）：exit 0=PASS / 1=FAIL（产品红点名）/ 2=ENV_FAIL（环境缺供点名）。
实现段落地前红属预期（TDD 信号），arbitrate/merge 期必须绿。

复用面（步骤级共享合法，不重复造夹具）：基础 harness（三态出口/隔离台 spawn_env/
StageWorker/RepoTree/落账读取）一律来自 t260905-03/lib_inspection；本 lib 只加
inspect 段专属面——围栏 JSON 伪造器、证据锚夹具树、上期台账/verdicts 播种器、
离线活动驱动器（stub temporalio，先例=t260915-08 board_rows / t260901-23 桩）。

桩缝契约（方案 §3 明文，场景↔实现接缝）：
- SANDBAR_INSPECT_STUB=1 + SANDBAR_INSPECT_STUB_FILE=<文件>：桩文件内容=agent 最终
  消息全文，末尾恰一块 ```json 围栏 {"findings":[…]}——走引擎真解析纪律，不旁路。
- SANDBAR_INSPECT_CMD=<脚本>：真进程链子用例（假脚本 echo 围栏 JSON）。
- 发现条目 schema（设计稿 §4.2 + 方案 §2.3）：subject/severity(high|med|low)/
  evidence[{path,line,quote≤200字}]（非空）/why/suggestion/confidence(0~1)；
  id 不由 agent 提供（机械按内容哈希铸造，agent 报的 id 一律忽略）。
"""
from __future__ import annotations

import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
sys.path.insert(0, os.path.join(os.path.dirname(_HERE), "t260905-03"))

from lib_inspection import (  # noqa: E402,F401  共享 harness 单点复用
    REPO, TP_DIR, CLIENT, TRIGGER, WORKER,
    die_fail, die_env, require_entry, py_runner, spawn_env,
    run_cmd, run_client, run_trigger, last_json, scanner_result,
    StageWorker, RepoTree, inspection_ledger, cleanup_tickets,
)

# ---------------------------------------------------------------- 发现条目与围栏消息伪造器


def finding(subject, path, line, quote, *, severity="med", why="语义审查判断",
            suggestion="无需修，仅记录", confidence=0.9, **extra):
    """按设计稿 §4.2 schema 造一条发现（id 不带——机械铸，agent 报的 id 被忽略）。"""
    d = {
        "scan": "agent",
        "severity": severity,
        "subject": subject,
        "evidence": [{"path": path, "line": line, "quote": quote}],
        "why": why,
        "suggestion": suggestion,
        "confidence": confidence,
    }
    d.update(extra)
    return d


def fenced_message(findings, *, n_blocks=1, outer_json_valid=True, preamble="审查完成。"):
    """造 agent 最终消息文本：末尾恰 n_blocks 块 ```json 围栏。

    n_blocks=0/≥2 与 outer_json_valid=False 用于畸形解析子用例（0/≥2 围栏块、坏 JSON）。
    """
    import json as _json
    body = ""
    if outer_json_valid:
        body = _json.dumps({"findings": findings}, ensure_ascii=False)
    else:
        body = '{"findings": [not-json'
    parts = [preamble + "\n"]
    for i in range(max(0, n_blocks)):
        parts.append("```json\n%s\n```\n" % body)
    return "".join(parts)


# ---------------------------------------------------------------- 桩缝名（方案 §3 明文，单点）

SANDBAR_INSPECT_STUB = "SANDBAR_INSPECT_STUB"
SANDBAR_INSPECT_STUB_FILE = "SANDBAR_INSPECT_STUB_FILE"
SANDBAR_INSPECT_CMD = "SANDBAR_INSPECT_CMD"


def stub_env(stub_file_path):
    """桩模式 worker env（缝名单点构造，防字面漂移；场景可自行展开同形字典）。"""
    return {SANDBAR_INSPECT_STUB: "1", SANDBAR_INSPECT_STUB_FILE: stub_file_path}


def write_stub_file(workdir, name, text):
    path = os.path.join(workdir, name)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    return path


# ---------------------------------------------------------------- 证据锚夹具树（真实文件行）

GUARD_REL = "integration/sc_guard_sample.mjs"
PRODUCER_REL = "server/plugins/workbench/src/client/capture.mjs"

_GUARD_LINES = [
    "// 守卫：隔离台新建会话锚（inspect 证据锚夹具）",
    "const label = await page.locator('.session-create').innerText();",
    'assert(label.includes("隔离台『+ 新建会话』"), "守卫锚缺失");',
]
_PRODUCER_LINES = [
    "export const section = '项目行';",
    "export const buttonLabel = section + '『+ 钮』';",
    "// 生产方措辞已改：锚字面「隔离台『+ 新建会话』」在本文件零残留（漂移现场）",
]


class InspectTree(RepoTree):
    """仓形夹具树 + 固定行号访问器：evidence 的 path/line/quote 全部锚真实文件行，
    机械复核（文件存在/行号在范围/引文匹配）才有「真过」与「真不过」两子用例可断。"""

    def line_text(self, rel, lineno):
        path = os.path.join(self.root, rel)
        with open(path, "r", encoding="utf-8") as f:
            return f.read().splitlines()[lineno - 1]

    def write_guard(self):
        return self.write(GUARD_REL, "\n".join(_GUARD_LINES) + "\n")

    def write_producer(self):
        return self.write(PRODUCER_REL, "\n".join(_PRODUCER_LINES) + "\n")

    def seed_scenarios(self):
        self.write("integration/run_scenarios.py",
                   'SCENARIOS = [("t-fix-inspect", "inspect 证据锚夹具守卫", "true")]\n')


def evidence_tree(label="inspect-evidence"):
    """三件套证据锚树：guard（锚字面在场）/ producer（锚已漂移）/ scenarios 清单。"""
    t = InspectTree(label)
    t.write_guard()
    t.write_producer()
    t.seed_scenarios()
    return t


# ---------------------------------------------------------------- 上期台账 / verdicts 播种

VERDICTS_SUFFIX = "-verdicts.json"


def ledger_name(instance, period, suffix=""):
    """台账文件名；suffix 是「.json 前的尾巴」（-suite / -verdicts，不带 .json）——
    与 engine 单源常量对齐：inspection_inspect.VERDICTS_RECEIPT_SUFFIX 带 .json，
    这里剥掉后缀尾巴复用，杜绝 -verdicts.json.json 双后缀漂移。"""
    tail = suffix[:-len(".json")] if suffix.endswith(".json") else suffix
    return "inspection-%s-%s%s.json" % (instance, period, tail)


def seed_prev_ledger(ledger_dir, instance, period, findings):
    """播上期台账（跨期去重对照源）：out/inspection/inspection-<实例>-<期>.json。"""
    os.makedirs(ledger_dir, exist_ok=True)
    path = os.path.join(ledger_dir, ledger_name(instance, period))
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"instance_id": instance, "period": period,
                   "findings": findings, "summary": {}, "heartbeat": True}, f,
                  ensure_ascii=False)
    return path


def seed_verdicts(ledger_dir, instance, period, entries):
    """播裁定台账：inspection-<实例>-<期>-verdicts.json（append entries 全留痕）。"""
    os.makedirs(ledger_dir, exist_ok=True)
    path = os.path.join(ledger_dir, ledger_name(instance, period, VERDICTS_SUFFIX))
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"instance_id": instance, "period": period, "entries": entries},
                  f, ensure_ascii=False)
    return path


def seed_prev_ledger_raw(ledger_dir, instance, period, raw_text):
    """播坏台账（坏 JSON/缺 findings/非列表→prev_ledger_error 点名子用例用）。"""
    os.makedirs(ledger_dir, exist_ok=True)
    path = os.path.join(ledger_dir, ledger_name(instance, period))
    with open(path, "w", encoding="utf-8") as f:
        f.write(raw_text)
    return path


# ---------------------------------------------------------------- 离线活动驱动（stub temporalio）

_STUB_READY = False


def load_engine_modules():
    """stub temporalio 先装（t260901-23 桩，先于一切 temporalio 导入）再导引擎活动模块。

    返回 (activities_mod, agent_activities_mod, inspect_mod)。实现未落地时抛
    AttributeError 由调用方转 FAIL（TDD 信号点名缺失面）。"""
    global _STUB_READY
    sys.path.insert(0, os.path.join(os.path.dirname(_HERE), "t260901-23"))
    if not _STUB_READY:
        import _stub_temporalio  # noqa: E402
        _stub_temporalio.install()
        _STUB_READY = True
    if TP_DIR not in sys.path:
        sys.path.insert(0, TP_DIR)
    import activities  # noqa: E402
    import agent_activities  # noqa: E402
    import inspection_inspect  # noqa: E402
    return activities, agent_activities, inspection_inspect


def run_coro(coro):
    import asyncio
    return asyncio.run(coro)


# ---------------------------------------------------------------- 断言容差访问器（行为锚定，不锚键名实现）

_STATE_KEYS = ("verified", "status", "state", "verification")


def finding_state(entry):
    """从发现条目取核验态（verified/unverified/recurring/suppressed/false-positive）。

    契约=方案 §2.4 的状态语义；字段名容差（verified 布尔 / status|state 字符串），
    状态语义本身是承诺面，不许含糊。取不到返回 None（由断言侧点名为缺口）。"""
    if not isinstance(entry, dict):
        return None
    for k in _STATE_KEYS:
        if k in entry:
            v = entry[k]
            if isinstance(v, bool):
                return "verified" if v else "unverified"
            if isinstance(v, str) and v:
                return v.lower()
    if entry.get("recurring") is True:
        return "recurring"
    for k in ("verdict", "suppressed"):
        if entry.get(k):
            return str(entry[k]).lower()
    return None


def entry_reason(entry):
    """复核不过的逐项点名 reason（方案 §2.4：任一不过=unverified+逐项 reason，不静默丢）。"""
    if not isinstance(entry, dict):
        return ""
    for k in ("reason", "unverified_reason", "recheck_reason", "why_not",
              "unverified_reasons"):
        v = entry.get(k)
        if isinstance(v, list) and v:
            joined = "；".join(x for x in v if isinstance(x, str) and x.strip())
            if joined:
                return joined
        if isinstance(v, str) and v.strip():
            return v
    ev = entry.get("evidence")
    if isinstance(ev, list):
        for e in ev:
            if isinstance(e, dict):
                for k in ("reason", "recheck_reason"):
                    v = e.get(k)
                    if isinstance(v, str) and v.strip():
                        return v
    return ""


def result_payload(parsed):
    """活动回执 {ok:…} 的宽容取面：dict 本体或 result/face 子面（剥壳保留 ok/error
    顶层判定面——成功回执={ok,result}，剥壳后断言仍能读 ok）。"""
    if not isinstance(parsed, dict):
        return None
    inner = None
    for k in ("result", "face", "payload"):
        v = parsed.get(k)
        if isinstance(v, dict):
            inner = v
            break
    if inner is None:
        return parsed
    if "ok" in parsed or "error" in parsed:
        merged = dict(inner)
        merged.setdefault("ok", parsed.get("ok"))
        merged.setdefault("error", parsed.get("error"))
        return merged
    return inner


def meta_of(payload):
    if not isinstance(payload, dict):
        return {}
    m = payload.get("meta")
    return m if isinstance(m, dict) else {}


# ---------------------------------------------------------------- 活动参构造（方案语义的超集别名，防键名漂移假红）

def inspect_args(instance, period, base, **extra):
    """run_inspection_inspect 活动参：语义超集（实例/期/审查基座/预算），键名取方案
    §2/§3 用词并带同义别名——活动只取它需要的键，多余键无害；若实现键名两不沾，
    场景 FAIL 点名（仲裁对齐面），绝不假绿。"""
    d = {
        "ticket_id": "t-contract-%s-%s" % (instance, period),
        "instance_id": instance, "instance": instance,
        "period": period,
        "base_dir": base, "repo_root": base, "scan_root": base,
        "max_findings": 40, "inspect_timeout_min": 30,
        "decl": None, "scan_face": "test",
    }
    d.update(extra)
    return d


def verify_args(instance, period, base, inspect_payload, **extra):
    """verify_inspection_findings 活动参：inspect 回执 + 实例/期/基座/预算。
    上期台账/verdicts 由活动壳自读（IO 是壳的职责，SANDBAR_INSPECTION_DIR 注入）。"""
    d = inspect_args(instance, period, base)
    d.pop("inspect_timeout_min", None)
    findings = None
    if isinstance(inspect_payload, dict):
        for k in ("findings", "result", "payload"):
            v = inspect_payload.get(k)
            if isinstance(v, dict) and isinstance(v.get("findings"), list):
                findings = v["findings"]
                break
            if isinstance(v, list):
                findings = v
                break
    d.update({
        "inspect": inspect_payload, "inspect_result": inspect_payload,
        "findings": findings,
        "suite_green": True,   # 非 suite 期无套件面，心跳合成的套件子用例缺省绿
    })
    d.update(extra)
    return d


def _walk_face(payload):
    """payload / payload.face / payload.result 中取「票面样」子面（findings/summary 所在层）。"""
    if not isinstance(payload, dict):
        return {}
    for cand in (payload, payload.get("face"), payload.get("result"), payload.get("payload")):
        if isinstance(cand, dict) and isinstance(cand.get("findings"), (list, type(None))):
            return cand
    return payload if isinstance(payload, dict) else {}


def payload_findings(payload):
    """取复核后的发现清单（缺键=None，由断言侧点名缺口）。"""
    face = _walk_face(payload)
    fs = face.get("findings")
    return fs if isinstance(fs, list) else None


def payload_fixes(payload):
    """建议面（suggested_fix_tickets）；缺席返回 None=「workflow 侧合成」信号。"""
    face = _walk_face(payload)
    v = face.get("suggested_fix_tickets")
    return v if isinstance(v, list) else None


def tally_of(payload):
    """取 (summary, heartbeat, truncated)：键名按方案 §2.4 语义面容差搜索。"""
    face = _walk_face(payload)
    meta = meta_of(payload)
    summary = None
    for src in (face, payload if isinstance(payload, dict) else {}):
        v = src.get("summary")
        if isinstance(v, (dict, int)):
            summary = v
            break
    heartbeat = None
    for src in (face, meta, payload if isinstance(payload, dict) else {}):
        v = src.get("heartbeat")
        if isinstance(v, bool):
            heartbeat = v
            break
    truncated = None
    for src in (meta, face, payload if isinstance(payload, dict) else {}):
        for k in ("truncated", "truncated_count", "truncation"):
            if k in src:
                truncated = src[k]
                break
        if truncated is not None:
            break
    return summary, heartbeat, truncated


def agent_home_dir(ledger_dir):
    """agent-home 落点探测：ledger_dir/agent-home/（方案 §2.2.3：DSH_HOME 与审查基座解耦）。"""
    p = os.path.join(ledger_dir, "agent-home")
    return p if os.path.isdir(p) else None
