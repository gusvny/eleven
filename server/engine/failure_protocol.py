#!/usr/bin/env python3
"""失败分类协议 v1（t260910-13）——纯函数核心：解析/分类/指纹/归属判定/汇总。

背景（260910 三误判实证）：失败信息非结构化（文本行+退出码）→ 只能人读猜；
ENV_FAIL 是天然「免责标签」，无证据也无人拦。本模块把协议做成**可机械执行**
的真值表，闸（verify_lane lane=integ / 引擎 activity）只消费不另立策略。

协议面（唯一规范，不做 junit 适配、不引中间格式）：
- 一行 JSON = 一个用例，行首字符 `{` 即规范行（旧文本行永不以 `{` 开头，
  双解析以此分流，兼容期文本行忽略并记 deprecation）。
- 用例最小必需字段：name/suite/status(pass|fail|not-checked)/cause(
  self|external|unknown)/reason/dur_s/attempt/started/git_sha/evidence/artifacts[]。
- 汇总行由闸生成（执行器产计数/耗时/并发/指纹，闸补 baseline_ref 并以明细
  重算复核——复核权威=闸重算）；测试不写汇总。

判定纪律（宿主 260910 拍板口径）：
- 三态语义收紧：未跑到断言即失败=not-checked，不许报 fail；
  **无证据的 not-checked 一律按 fail 处理**（fail-closed，治免责标签滥用）。
- 违约行：status=fail × reason∈prepare 型 → 改判 not-checked + violation=true
  + 计入闸红（报错态本身是协议违约，不因 main 也红而放行）。
- 机械归属：闸在 main 上跑同一命令取基线，红名单**只收 checked fail
  （断言级）**——基线侧 not-checked=基线根本没检验到=答不了锅（宿主口径
  「基线只答『谁的锅』，不答『是不是环境』」），其泳道对应用例归属降级
  unknown，绝不计入「main 红」（封死 t260910-10 形态从基线侧复发）。
- 指纹闭环：env_fingerprint(lane) == env_fingerprint(baseline) 才采信差集；
  键集只收**运行语境不变面**（工具链版本/声明文件哈希），排除工单语境键
  （SANDBAR_TASK_QUEUE 等）与临时路径——键集选成永 diff 面=归属恒 unknown。
  不等 → 全部归属降级 unknown + 键级差异面显式声明，不静默采信。

本模块零 IO 零进程零网络（指纹取键值由调用方传入），全部纯函数——单测
（server/engine/tests/test_t260910_13_failure_protocol.py）无需任何环境。
"""
import hashlib
import json

# 状态词表（封闭）
STATUSES = ("pass", "fail", "not-checked")
# 责任线索词表（封闭）
CAUSES = ("self", "external", "unknown")
# prepare 型原因码（进入违约判定的面；开放词表的其余 reason 只分类不判违约）
PREPARE_REASONS = frozenset(
    {"connect_refused", "lock_busy", "missing_asset", "self_precheck"})
# 断言型原因码（产品/测试类的机械面）
ASSERT_REASONS = frozenset({"assert_mismatch"})

REQUIRED_FIELDS = ("name", "status")


# ---------------- 解析 ----------------

def evidence_one_line(text):
    """evidence 一行原文：换行/回车机械压平（JSON 层的引号转义交给
    json.dumps——这里保证语义层面 evidence 永不含换行）。None/空 → ""。"""
    if text is None:
        return ""
    return str(text).replace("\\", "\\\\").replace("\r", "").replace("\n", "\\n")


def parse_spec_line(line):
    """解析一行规范行（首字符 `{`）。返回 dict；任何畸形（非 JSON/非对象/
    缺必需字段/字段错型）返回 {"__malformed__": <原文裁断>}，不抛不吞——
    畸形行由闸计为违约面，绝不静默跳过（消费外部输入的 fail-closed 纪律）。"""
    line = (line or "").strip()
    if not line[:1] in ("{", "["):
        return None
    try:
        obj = json.loads(line)
    except (json.JSONDecodeError, ValueError):
        return {"__malformed__": line[:200]}
    if not isinstance(obj, dict):
        return {"__malformed__": line[:200]}
    missing = [f for f in REQUIRED_FIELDS if not isinstance(obj.get(f), str)
               or not obj.get(f)]
    if missing:
        return {"__malformed__": line[:200]}
    if obj.get("status") not in STATUSES:
        return {"__malformed__": line[:200]}
    return obj


def normalize_case(obj, attempt_default=1):
    """规范行 → 规范化用例（缺省补齐；attempt 缺省 1，producer=发射器，
    闸/引擎侧可盖 rework 代数——不许双写者并存，闸盖写是显式覆盖）。"""
    return {
        "name": obj["name"],
        "suite": str(obj.get("suite") or ""),
        "status": obj["status"],
        "cause": obj.get("cause") if obj.get("cause") in CAUSES else "unknown",
        "reason": str(obj.get("reason") or ""),
        "dur_s": float(obj["dur_s"]) if isinstance(obj.get("dur_s"), (int, float))
                 and not isinstance(obj.get("dur_s"), bool) else None,
        "attempt": int(obj["attempt"]) if isinstance(obj.get("attempt"), int)
                   and not isinstance(obj.get("attempt"), bool) else attempt_default,
        "started": str(obj.get("started") or ""),
        "git_sha": str(obj.get("git_sha") or ""),
        "evidence": str(obj.get("evidence") or ""),
        "artifacts": obj["artifacts"] if isinstance(obj.get("artifacts"), list) else [],
    }


# ---------------- 三态收紧（fail-closed） ----------------

def enforce_semantics(case):
    """三态语义收紧，返回 (case, violations[list[str]])：
    - fail × prepare 型 reason → 改判 not-checked + violation（协议违约独立拦）；
    - not-checked 无 evidence → 按 fail 处理（fail-closed，治免责标签）。"""
    violations = []
    if case["status"] == "fail" and case["reason"] in PREPARE_REASONS:
        case = dict(case, status="not-checked", violation=True)
        violations.append(
            "violation: status=fail with a prepare-type reason=%s (a case that never "
            "reached its assertions must not report fail)"
            % case["reason"])
        case = dict(case, reason=case["reason"])  # reason 原样保留供归属
    if case["status"] == "not-checked" and not case["evidence"].strip():
        case = dict(case, status="fail", unbacked_env_fail=True)
        violations.append(
            "violation: not-checked without evidence (an unevidenced environment red "
            "is treated as FAIL, fail-closed)")
    return case, violations


# ---------------- 指纹（运行语境不变面） ----------------

# 排除键（每次运行必异/工单语境/临时路径）——进指纹必造成 lane/基线恒 diff，
# 归属恒 unknown，锚死「真红必拦」正路径。
FP_EXCLUDED_KEYS = frozenset({
    "SANDBAR_TASK_QUEUE", "SANDBAR_WATCH_WORKFLOW", "SANDBAR_TICKET_ID",
    "SANDBAR_STAGE_ID", "SANDBAR_TARGET_HOST", "SANDBAR_NAMESPACE",
    "SANDBAR_STAGE_LOCK_DIR", "TMPDIR", "PWD", "OLDPWD", "HOME", "PATH",
    "SANDBAR_POOL_CONC", "SANDBAR_CONC_POOLS",  # 并发面=口径非环境，基线强制 =1
})


def env_fingerprint(parts):
    """parts: {key: value}（调用方收集：工具链版本/声明文件哈希等）。
    排除 FP_EXCLUDED_KEYS 后排序键拼接哈希。返回 {value, keys}（键级结构
    供 diff 出差异面声明）。值统一 str()。"""
    keys = {k: str(v) for k, v in sorted(parts.items())
            if k not in FP_EXCLUDED_KEYS and v is not None}
    blob = "\n".join("%s=%s" % (k, keys[k]) for k in sorted(keys))
    return {"value": hashlib.sha256(blob.encode("utf-8")).hexdigest(),
            "keys": keys}


def fingerprint_diff(lane_fp, baseline_fp):
    """键级差异面声明（只对 lane/baseline 键集并集做 diff）。"""
    lk = (lane_fp or {}).get("keys") or {}
    bk = (baseline_fp or {}).get("keys") or {}
    diffs = []
    for k in sorted(set(lk) | set(bk)):
        if lk.get(k) != bk.get(k):
            diffs.append({"key": k, "lane": lk.get(k), "baseline": bk.get(k)})
    return diffs


# ---------------- 机械归属判定（决策表） ----------------

def _baseline_red_set(baseline_cases):
    """基线红名单：**只收 checked fail（断言级）**（C1 口径）。基线
    not-checked 不进红名单（答不了锅）。返回 {name: case}（evidence 在场
    随名单落——K2：环境伪装成断言红时有人审兜底面）。"""
    red = {}
    for c in baseline_cases:
        if c["status"] == "fail":
            red[c["name"]] = c
    return red


def decide(case, baseline_red, fp_equal=True, fp_diffs=None):
    """单用例归属判定（决策表，闸不懂场景名）。返回：
    {name, verdict: block|record|unknown, why, violation?}
    verdict=block → 闸拦；record → 记录不堵；unknown → 记录不裁（降级显式）。
    保守方向（真红必拦不因基线缺席松绑）：fail（断言级）除「基线红名单在册」
    外一律拦；violation 独立拦；not-checked 在指纹不等时降 unknown（差集
    不可比，不裁锅）。"""
    name = case["name"]
    if case.get("violation"):
        return {"name": name, "verdict": "block",
                "why": "protocol_violation(%s)" % (case.get("reason") or "?"),
                "violation": True}
    in_baseline = name in baseline_red
    if case["status"] == "fail":
        if in_baseline:
            return {"name": name, "verdict": "record",
                    "why": "baseline_red(existing debt)"}
        return {"name": name, "verdict": "block",
                "why": "regression(main green or baseline not comparable; block conservatively)"}
    # not-checked（带证据）
    if not fp_equal:
        return {"name": name, "verdict": "unknown", "why": "fingerprint_mismatch",
                "fp_diffs": fp_diffs or []}
    if case["cause"] == "self":
        return {"name": name, "verdict": "record" if in_baseline else "block",
                "why": "not_checked_self(main%s)" % ("red" if in_baseline else "green")}
    if case["cause"] == "external":
        return {"name": name, "verdict": "record",
                "why": "not_checked_external(record for governance; does not block)"}
    return {"name": name, "verdict": "unknown", "why": "cause_unknown"}


def baseline_answers(lane_cases, baseline_cases, lane_fp, baseline_fp, baseline_ok):
    """活基线主跑的**逐名答案**（{"红名": "red"|"green"}）——只读派生物，不改任何判定。

    KI-122①（260926 洞①「加保险」）：采纳面要问「这条红在活基线里是什么状态」。
    与 `_baseline_answer` 同一判据（单写者：基线缺席/指纹不等=无答案；基线 not-checked
    不算答案 C1；red=checked fail / green=跑过且 pass）——本函数只是把它**逐名取出来**
    放进回执，供采纳面与票面审计，不参与闸的 block/record 判定（判据零改动）。

    `lane_cases` 传**红面**（非 pass）即可：全绿用例进不进答案表对采纳无意义，且回执
    尺寸更小。名字畸形/非 dict 条目逐项跳过（不抛）。"""
    fp_equal = bool(baseline_ok) and (
        (lane_fp or {}).get("value") == (baseline_fp or {}).get("value"))
    baseline_red = _baseline_red_set(baseline_cases or [])
    baseline_by_name = {c["name"]: c for c in (baseline_cases or [])
                        if isinstance(c, dict) and c.get("name")}
    out = {}
    for raw in (lane_cases or []):
        name = raw.get("name") if isinstance(raw, dict) else None
        if not isinstance(name, str) or not name.strip():
            continue
        ans = _baseline_answer(name, baseline_red, baseline_by_name, baseline_ok, fp_equal)
        if ans in ("red", "green"):
            out[name.strip()] = ans
    return out


def apply_affiliation(lane_cases, baseline_cases, lane_fp, baseline_fp,
                      baseline_ok, baseline_seen=True):
    """整批归属：逐用例语义收紧 → 决策表。返回
    {cases, verdicts, affiliation_confidence, fp_diffs, blockers, records,
     unknowns, violations}。
    baseline_ok=False（基线缺席/超时/崩溃/关闸）→ fail 保守拦（真红必拦
    不因基线缺席松绑）、not-checked 降 unknown（答不了锅不硬裁）、
    violation 照拦；全绿用例永不受降级牵连。"""
    fp_equal = bool(baseline_ok) and (
        (lane_fp or {}).get("value") == (baseline_fp or {}).get("value"))
    fp_diffs = None if fp_equal else fingerprint_diff(lane_fp, baseline_fp)
    baseline_red = _baseline_red_set(baseline_cases or [])
    verdicts, cases, violations_all = [], [], []
    for raw in lane_cases:
        case, viols = enforce_semantics(raw)
        violations_all.extend({"name": case["name"], "msg": v} for v in viols)
        if case["status"] == "pass":
            verdicts.append({"name": case["name"], "verdict": "pass", "why": "green"})
        else:
            verdicts.append(decide(case, baseline_red, fp_equal, fp_diffs))
        cases.append(case)
    blockers = [v["name"] for v in verdicts if v["verdict"] == "block"]
    records = [v["name"] for v in verdicts if v["verdict"] == "record"]
    unknowns = [v["name"] for v in verdicts if v["verdict"] == "unknown"]
    confidence = ("ok" if (baseline_ok and fp_equal)
                  else "unknown(baseline_unavailable)" if not baseline_ok
                  else "unknown(fingerprint_mismatch)")
    return {"cases": cases, "verdicts": verdicts,
            "affiliation_confidence": confidence,
            "fp_diffs": fp_diffs or [],
            "blockers": blockers, "records": records, "unknowns": unknowns,
            "violations": violations_all}


# ---------------- 归属前复验（KI-182，t261002-02）----------------
# 「lane 红 + main 绿 ⇒ 本票的账」这条归属规则假定 lane 与 main 的差异来自本票改动；
# 但同一轮的台面抖动（轮内并发多台/浏览器抢内存端口、夹具播种竞争）同样能造出
# lane-only 红，于是真账假账混记、放行口径被迫靠重跑碰绿（261001 夜 t261001-19/21/
# 22/23 实证，KI-182/184）。本节把 KI-182 的出路落成纯函数机制：**归因前先复验**——
# 对「本票的账」家族逐条以同树单跑回执复验，全绿 ⇒ 降级 unattributable（不记本票
# 的账），未证全绿 ⇒ 维持 block（fail-closed：拦不松、账不丢）。
# 判定纪律（不变式）：unattributable **不等于绿**——轮仍红、仍转人，闸的拦面一个
# 不放；它只改账本（不冤枉），不改放行口径（不碰绿）。

#: 只对这一族 block 做复验：why 以此开头 = lane 红 + main 绿/基线不可比 → 原规则
#: 记成本票的账。协议违约 block（violation）与 not-checked 家族不走复验：前者是
#: 铁拦（报错态本身违约），后者基线本就答不了锅、不是「被冤枉」的形状。
RECHECK_BLOCK_WHY_PREFIX = "regression("

#: 复验后降级档（KI-182 出路②，带复验回执）：同树单跑全绿 ⇒ 本轮该名不可归因
#: （台面族），不记本票的账。
VERDICT_UNATTRIBUTABLE = "unattributable"


def reprobe_receipt_all_green(receipt):
    """复验回执 → 全绿布尔。判据与 shared.ReprobeRedResult.all_green 同源（五条同时
    成立：零 error、真跑 ≥1、零产品红、零环境红、零不在册）——这里收 dict/对象两种
    形状（活动回执过 workflow 边界后可能是任一形态）。任何缺键/错型/畸形 → False
    （fail-closed：未证全绿就不降级，绝不因回执读不懂而洗账）。"""
    if receipt is None or isinstance(receipt, (str, bytes, int, float, bool, list)):
        return False
    if isinstance(receipt, dict):
        def get(k, d=None):
            return receipt.get(k, d)
    elif hasattr(receipt, "get") or hasattr(receipt, "__dict__"):
        def get(k, d=None):
            return getattr(receipt, k, d)
    else:
        return False

    def _int(k):
        v = get(k)
        return v if isinstance(v, int) and not isinstance(v, bool) else None

    ran, failed, env_fail = _int("ran"), _int("failed"), _int("env_fail")
    if ran is None or failed is None or env_fail is None:
        return False
    error = get("error")
    missing = get("missing")
    if not isinstance(error, str):
        return False
    if not isinstance(missing, (list, tuple)):
        return False
    return (error == "" and ran >= 1 and failed == 0 and env_fail == 0
            and not list(missing))


def apply_reprobe_recheck(verdicts, reprobe=None):
    """归属前复验（KI-182 出路①②）：对「本票的账」家族（verdict=block × why 以
    RECHECK_BLOCK_WHY_PREFIX 开头）以同树单跑回执逐条复验：
    - 回执全绿（reprobe_receipt_all_green）→ 该条降级 verdict=unattributable，
      why=reprobe_green(...)，条内带 recheck 回执面（ran/缺失面）；
    - 未证全绿 / 回执畸形 / 缺席 → 该条判定**逐字节不动**（fail-closed：探针缺席
      绝不放行、也绝不洗账），why 追加 reprobe 证据便于人审。
    只碰该族 block；pass/record/unknown/violation 与非该族 block 一概不动（全绿
    用例永不受牵连）。reprobe=None（探针没跑）→ 全部原样 + recheck.available=False。
    返回 {verdicts, unattributable, rechecked, ticket_account, recheck}：
    - unattributable = 降级名单；rechecked = 复验过（无论方向）的名单；
    - ticket_account = 复验后仍记本票的账的名单；
    - recheck = 票面/明细共用的面摘要（available/all_green/ran/error/计数）。"""
    green = reprobe_receipt_all_green(reprobe)
    available = reprobe is not None
    ran = error = None
    if available:
        getter = reprobe.get if isinstance(reprobe, dict) else (
            lambda k, d=None: getattr(reprobe, k, d))
        ran = getter("ran")
        error = str(getter("error") or "")
    out, unattr, rechecked, kept = [], [], [], []
    for v in verdicts or []:
        if (not isinstance(v, dict) or v.get("verdict") != "block"
                or not str(v.get("why") or "").startswith(RECHECK_BLOCK_WHY_PREFIX)):
            out.append(v)
            continue
        name = v.get("name")
        rechecked.append(name)
        if green:
            unattr.append(name)
            nv = dict(v, verdict=VERDICT_UNATTRIBUTABLE,
                      why="reprobe_green(standalone re-run in this lane: all green)",
                      recheck={"ran": ran, "error": ""})
        else:
            kept.append(name)
            nv = dict(v,
                      why="%s | reprobe_not_green(%s)"
                          % (v.get("why"), error or "reds remain on the re-run"),
                      recheck={"error": error})
        out.append(nv)
    return {
        "verdicts": out,
        "unattributable": unattr,
        "rechecked": rechecked,
        "ticket_account": kept,
        "recheck": {"available": bool(available), "all_green": bool(green),
                    "ran": int(ran) if isinstance(ran, int)
                    and not isinstance(ran, bool) else 0,
                    "error": error or "",
                    "unattributable": list(unattr),
                    "ticket_account": list(kept)},
    }


def unattributable_face_sentence(unattributable, ticket_account):
    """票面句子（英文，界面口径）：复验降级了谁、谁复验后仍红、轮仍红仍转人——
    把「unattributable ≠ 绿、不自动放行」说在票面上（防「靠重跑碰绿」被误读成放行）。
    unattributable 空 → 空串（票面零扰动）。"""
    un = [str(n) for n in (unattributable or []) if str(n)]
    kept = [str(n) for n in (ticket_account or []) if str(n)]
    if not un:
        return ""
    parts = ["Re-check: %d red(s) re-ran standalone in this lane and passed → "
             "unattributable (bench-family), NOT booked as this ticket's account"
             % len(un)]
    if kept:
        parts.append("%d red(s) stayed red on the re-run (still this ticket's account)"
                     % len(kept))
    parts.append("the round is still red — a human decides")
    return "; ".join(parts) + "."


# ---------------- 汇总（闸重算复核权威） ----------------

def recount(cases):
    """以规范行明细重算计数（C6/C8：闸复核权威；协议内没有独立 env 态——
    带证据环境红=not-checked；无证据环境红已被 enforce 改判 fail）。"""
    return {"ran": len(cases),
            "pass": sum(1 for c in cases if c["status"] == "pass"),
            "fail": sum(1 for c in cases if c["status"] == "fail"),
            "not_checked": sum(1 for c in cases if c["status"] == "not-checked")}


def summarize(cases, wall_s, concurrency, pool_config, env_fp=None,
              baseline_ref=None):
    """闸汇总行：recount + wall/concurrency/pool_config/env_fingerprint/
    baseline_ref。指纹与 baseline_ref 都是闸补的运行语境值（执行器产不出），
    用例行里不含指纹——不发假字段。"""
    out = recount(cases)
    out.update({"wall_s": round(float(wall_s), 1) if wall_s is not None else None,
                "concurrency": concurrency, "pool_config": pool_config,
                "env_fingerprint": env_fp, "baseline_ref": baseline_ref})
    return out


def dedupe_cases(cases):
    """「一行=一个用例」不变式的闸侧兜底：同名用例重复出现 → 保留最后一条
    （重跑语义），重复名单返回给调用方计违约面。"""
    index_by_name, out, dupes = {}, [], []
    for c in cases:
        if c["name"] in index_by_name:
            dupes.append(c["name"])
            out[index_by_name[c["name"]]] = c
        else:
            index_by_name[c["name"]] = len(out)
            out.append(c)
    return out, sorted(set(dupes))


def apply_gate_blockers(failed, env_fail, case_status, blockers):
    """闸拦名单 → 回执计数的机械换算（纯函数，供引擎 activity 用；验收走查
    gen1 问题七：本换算不得只活在 activity 内联无测试覆盖）。规则：blocker 若
    原态 not-checked → failed+1 且 env_fail-1（被改判的拦面从环境红挪进产品红）；
    原态 fail 已在 failed 里不动；计数外的拦面（防御性）failed+1 不静默。
    返回 (failed, env_fail)。"""
    for b in blockers:
        st = case_status.get(b)
        if st == "not-checked":
            failed += 1
            env_fail = max(0, env_fail - 1)
        elif st != "fail":
            failed += 1
    return failed, env_fail


# ---------------- 结果台账（t260922-12）：采信边界与归属组合（纯函数，零 IO） ----------------
# 台账本体=~/.sandbar/projects/sandbar/ledger/scenario-results.jsonl（append-only
# JSONL，行=一次场景判定；唯一写者=闸 verify_lane，IO 在项目侧
# integration/scenario_ledger.py）。本节只做两件纯事：①采信边界四条逐条判；
# ②「台账×活基线」归属组合判定。零 IO 零进程零网络（祖先关系由调用方以
# git merge-base --is-ancestor 判成布尔传入）。

# 台账行 verdict 封闭词表。与协议三态的映射由闸做：pass→pass、fail→fail、
# not-checked→env_fail；skip 为保留位（协议内无 skip，封闭防 typo 混入）。
LEDGER_VERDICTS = ("pass", "fail", "env_fail", "skip")
# 采信边界③：时效 ≤7 天（票据一字定死，不设旋钮——判据零放宽）。
LEDGER_TRUST_MAX_AGE_DAYS = 7
# 采信前提：verdict 必须是「检验到」的面。env_fail=没检验到（答不了锅，同基线
# not-checked 口径，绝不入「main 红/绿」证据）；skip 同理。只有 pass（main 绿
# 证据）/fail（main 红证据）可采信。
_LEDGER_TRUSTABLE_VERDICTS = frozenset({"pass", "fail"})
# 时钟漂移容差（秒）：记录来自「未来」超过容差=时钟倒挂污染，不采信。
_LEDGER_TS_FUTURE_TOLERANCE_S = 300


def ledger_ts_epoch(value):
    """台账 ts（ISO8601）→ epoch 秒。非字符串/解析失败/无时区（naive）→ None
    ——不猜时区：判不了的行不采信（fail-closed）。"""
    import datetime as _dt
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        d = _dt.datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if d.tzinfo is None:
        return None
    return d.timestamp()


def ledger_trust(record, env_fp, base_is_ancestor, conc_width, now_epoch):
    """采信边界四条（票据③，缺一不可）+「检验到」前提，逐条给 reason：
    0) record 本身可判（dict、verdict∈{pass,fail}——env_fail/skip=没检验到）；
    1) 指纹相等：record.env_fp == env_fp（lane 现指纹；与基线指纹无关——
       基线缺席/裸树起不来的依赖型场景正是靠这条独立翻案）；
    2) 记录 commit 是当前 base 的祖先或相同（base_is_ancestor 布尔）；
    3) 时效 ≤7 天（ts 距 now_epoch；超期不采信；来自未来超容差不采信）；
    4) conc_width 一致（并发口径面，见 FP_EXCLUDED_KEYS 注）。
    record 畸形（缺键/类型错/width 不可解析）→ 不采信并点名 reason——读取面
    不可信时宁可回退实跑（无「查不到当绿」分支）。返回 {trusted, reason}。"""
    if not isinstance(record, dict):
        return {"trusted": False, "reason": "ledger_record_not_dict"}
    verdict = record.get("verdict")
    if verdict not in _LEDGER_TRUSTABLE_VERDICTS:
        return {"trusted": False,
                "reason": "verdict_unusable(%s)" % (verdict,)}
    if record.get("env_fp") != env_fp:
        return {"trusted": False, "reason": "fingerprint_mismatch"}
    if not base_is_ancestor:
        return {"trusted": False, "reason": "commit_not_ancestor_of_base"}
    ts = ledger_ts_epoch(record.get("ts"))
    if ts is None:
        return {"trusted": False, "reason": "ts_unusable"}
    age = float(now_epoch) - ts
    if age > LEDGER_TRUST_MAX_AGE_DAYS * 86400:
        return {"trusted": False,
                "reason": "expired(>%dd)" % LEDGER_TRUST_MAX_AGE_DAYS}
    if age < -_LEDGER_TS_FUTURE_TOLERANCE_S:
        return {"trusted": False, "reason": "ts_in_future"}
    w = record.get("conc_width")
    if isinstance(w, bool) or not isinstance(w, int) or w < 1:
        return {"trusted": False, "reason": "conc_width_unusable"}
    if w != conc_width:
        return {"trusted": False, "reason": "conc_width_mismatch"}
    return {"trusted": True, "reason": "trusted"}


def _baseline_answer(name, baseline_red, baseline_by_name, baseline_ok, fp_equal):
    """活基线对该名有没有给出 checked 答案：red（checked fail）/green（跑过且
    pass）/None（缺席=没跑（含定点复跑未点名）或 not-checked=没检验到，或基线
    整体缺席/指纹不等=不可比）。基线 not-checked 不算答案（C1：答不了锅）。"""
    if not baseline_ok or not fp_equal:
        return None
    if name in baseline_red:
        return "red"
    c = baseline_by_name.get(name)
    if c is None:
        return None
    return "green" if c["status"] == "pass" else None


def apply_affiliation_ledger(lane_cases, baseline_cases, lane_fp, baseline_fp,
                             baseline_ok, ledger_answers):
    """「台账×活基线」组合归属（t260922-12③）：apply_affiliation 的台账增广版，
    返回形状一致（另带 ledger 面）。判定序（逐用例）：
    a) violation 照拦（先于一切，继承决策表）；
    b) 活基线 checked 结果权威（red→record / green→原方向），不改；
    c) 基线答不了（缺席/超时/指纹不等/该名未跑到或 not-checked）且台账可信：
       ledger=fail → record「ledger_red(既有欠账·台账)」（t260922-08 病灶的
       机械解：基线裸树起不来的依赖型场景由台账补答「main 同红」）；
       ledger=pass → 维持「main 绿」方向（原判定不动——拦/unknown 口径照旧）；
    d) 台账不可信/无记录 → apply_affiliation 原行为逐字节（fail 保守拦、
       not-checked 按 cause 表；「真红必拦不因基线缺席松绑」的松绑只来自 c 的
       可信台账，不来自任何缺席）；
    e) 已是 record 的判定（促治理不堵）不被台账改写：原 why 保留、不记
       overridden（P3：台账红只进 hits_red 佐证面——归因叙事不被台账覆盖）。
    ledger_answers: {name: ledger_trust 回执 + verdict/ts/source}。全绿用例永
    不受牵连；返回值 ledger 面：{consulted, hits_red, hits_green, overridden}。"""
    out = apply_affiliation(lane_cases, baseline_cases, lane_fp, baseline_fp,
                            baseline_ok=baseline_ok)
    fp_equal = bool(baseline_ok) and (
        (lane_fp or {}).get("value") == (baseline_fp or {}).get("value"))
    baseline_red = _baseline_red_set(baseline_cases or [])
    baseline_by_name = {c["name"]: c for c in (baseline_cases or [])}
    cases_by_name = {c["name"]: c for c in out["cases"]}
    hits_red, hits_green, overridden = [], [], []
    for idx, v in enumerate(out["verdicts"]):
        name = v["name"]
        if v["verdict"] == "pass" or v.get("violation"):
            continue
        la = (ledger_answers or {}).get(name) or {}
        if not la.get("trusted"):
            continue
        if la.get("verdict") == "fail":
            hits_red.append(name)
        elif la.get("verdict") == "pass":
            hits_green.append(name)
        if _baseline_answer(name, baseline_red, baseline_by_name,
                            baseline_ok, fp_equal) is not None:
            continue  # b) 活基线已答：权威优先，台账只佐证
        if la.get("verdict") != "fail":
            continue  # c) 只有台账红改判；台账绿只佐证（方向与原判定一致）
        if v["verdict"] == "record":
            continue  # P3（仲裁 gen1）：本就 record（如 not-checked×external，
            # 促治理不堵）不改判不记 overridden——原 why 承载 external 归因，
            # 被 ledger_red 叙事覆盖会把诊断面引向错误方向（报错必须精确）；
            # 判定类未变也非「改判」（与 overridden 语义自相矛盾）。台账红仍记
            # hits_red 佐证面（上方已记），只是不动判定本体。
        case = cases_by_name.get(name) or {}
        out["verdicts"][idx] = {
            "name": name, "verdict": "record",
            "why": "ledger_red(existing debt · ledger)",
            "ledger": {"ts": str(la.get("ts") or ""),
                       "source": str(la.get("source") or "")},
            "lane_status": case.get("status", ""),
        }
        overridden.append(name)
    out["blockers"] = [v["name"] for v in out["verdicts"] if v["verdict"] == "block"]
    out["records"] = [v["name"] for v in out["verdicts"] if v["verdict"] == "record"]
    out["unknowns"] = [v["name"] for v in out["verdicts"] if v["verdict"] == "unknown"]
    out["ledger"] = {"consulted": sorted((ledger_answers or {}).keys()),
                     "hits_red": sorted(hits_red),
                     "hits_green": sorted(hits_green),
                     "overridden": sorted(overridden)}
    return out
