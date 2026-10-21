"""path_gates — 阶段路径闸 + 受保护路径闸（工单 t260911-03）。

宿主令 260910：仲裁、走查，凡事不应该有代码变化的阶段，不允许改代码，要有机械闸门
检查。两道闸都在 worker 代落盘（settle）时刻判定——此时引擎已确知段 id 与本批改动
文件清单，判定是纯路径白名单、零猜测：

①【阶段路径闸】按「段 × 允许改动面」判路径白名单：做方案/审方案＝零代码改动（仅
  结果文件）；实现＝写集内；设计集成测试＝仅 integration/；仲裁＝仅测试面 + 本票
  场景（tests-fault 修测试属设计内，碰产品代码一律拒）；验收走查/合并检查/合并＝
  零代码改动。违规＝拒绝落盘（不 commit）+ 回执点名「段 X 不允许改 Y」+ 合法出路。

②【受保护路径闸】「真源与期望值文件」任何泳道不得改：共享守卫脚本、共享电池期望
  值/阈值档、配置真源（verify.yaml/model-routes.yaml/merge-checks.yaml/projects.yaml/
  project-registry.ts/roles/）、契约文档（docs/design/ 整目录）、以及闸自身
  （path_gates.py，防「各票改闸给自己发免红令」）。语义=「存在才拦」：以泳道分叉点
  （base_ref，非 HEAD——HEAD 会把本票早段 commit 里的文件误判为已存在，票内 rework
  死锁）为锚，base 已存在的名单内文件改动即红；新建（base 不存在）放行，落地后即受
  保护——闸不挡自己的出生，但挡后续任何泳道改它。出路：人审放行或回 main 侧走票。

③协议联动（t260910-13）：拒绝回执内嵌机器可辨键值 path_gate_reason=<码>，原因码走
  开放词表（不入 PREPARE_REASONS/ASSERT_REASONS），使「环境/产品/越权」三态可辨。

步 0 键集证据（运行时 settle 实际收到的 stage_id 全集，接线时逐一核对）：
  - agent_activities._run_agent_stage_impl 两处 settle（缓存命中分支 + 结果文件就绪
    分支）：stage_id = AgentStageArgs.stage_id（generic 段 = create_plan/review_plan/
    implement/design_integration_tests/integration_review（仅老票 replay）+ 已退役
    模板段 + fixture 段；新票 path_gate 只对 dev-lane 开 → 实际面为 dev-lane 段）；
  - agent_activities._merge_check_one_scope 自愈 settle：字面 "merge_check"；
  - agent_activities.settle_lane 逐树 settle：args.stage_id（dev_lane 两处派发实际
    传值 = "implement"（integ_join 汇合）与 "arbitrate"（arb_acc 并行汇合））；
  - agent_activities._stub_stage_shortcut 缓存 settle（settle_on_cache）与 arbitrate
    tests-fault 分支 settle：stage_id = "arbitrate"；
  - suggest_next/acceptance_walkthrough/ui_evidence 三个段不走 _settle_worktree_lane
    （walkthrough 报告落 .sandbar、suggest_next 只读分析、ui_evidence 截图归档）——
    规则键仍配置（fail-closed 防未来接线漏配），当前链路为防御性键。
  日志层标签（t260916-19 ④）：_settle_worktree_lane 的 face 形参区分三个入口——
  agent（_settle_with_gate，generic 段自 settle）／heal（merge_check 自愈）／join
  （settle_lane 汇合统一落盘）——日志打 `agent-settle：/heal-settle：/join-settle：`，
  免「同秒两条 settle 日志无法分辨哪层判定」的歧义（dengzhufpv t260916-11 实案）。
  未知段（键不在规则表）对 path_gate=True 一律 fail-closed 拒绝（reason=unknown_stage）；
  老在途票保护由 path_gate 缺省 False 承担（TicketInput 无此字段 → 永远 False，不追溯）。

本模块零 IO 零进程零网络（「基点已存在」由调用方注入谓词），全部纯函数——单测
（server/engine/tests/test_t260911_03_path_gates.py）与场景可直调。
"""
import posixpath
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple

# 拒绝回执的机器可辨键值：is_gate_refusal 以此辨认闸拒绝（区别于其它 settle note）。
PATH_GATE_REASON_KEY = "path_gate_reason="

# 结果/回执文件前缀：引擎运行时目录（.dsh 不进本表——SETTLE_PATHSPEC 已排除）。
# .suyou = 老泳道粘滞名（t260907-04 naming-compat）。这些目录不进 commit（settle
# add 后 reset），但会出现在 status 脏清单里，各段白名单一律放行。
RESULT_FILE_PREFIXES = (".sandbar", ".suyou")  # naming-compat

# 受保护路径名单（真源与期望值文件；匹配立场与写集一致：条目==路径 或 路径以「条目/」
# 为目录前缀）。任何泳道改名单内**且基点已存在**的文件即红（新建放行、落地即护）。
# 显式不在名单：integration/run_scenarios.py（场景登记=正常工作面，避免误伤）。
PROTECTED_PATHS: Tuple[str, ...] = (
    # 共享守卫脚本（t260910-06/-08 两票仲裁段就地改期望值的事故面）
    "integration/t260902-07/tests/test_route_table.py",
    "integration/t260902-07/tests/test_route_lookup.py",
    # 共享电池的期望值/阈值档
    "integration/baselines",
    # 已知红挂账名册（260926 独立复核洞②实锤：不在保护面时，写集含 integration/ 的票
    # 可把自己的新红写进名册并同步抬 max_entries → 下一轮「逐条在册」→ 自证豁免放行，
    # 票面还带合规审计锚。名册政策本就要求「新挂账须 integration 岗位判词 + home」，
    # 归入受保护真源与政策一致。）
    "integration/known-red-baseline.json",
    # 配置真源
    "verify.yaml",
    "server/model-routes.yaml",
    "server/merge-checks.yaml",
    "server/projects.yaml",
    "server/project-registry.ts",
    "server/roles",
    # 契约文档（定稿知识库整目录前缀，免逐文件枚举漏新契约）
    "docs/design",
    # 闸自身自保护（本票出生：新建时 base 不存在 → 放行）
    "server/engine/path_gates.py",
)

# 阶段路径闸规则表：键 = 运行时 settle 实际收到的 stage_id（见模块头「步 0 键集证据」）。
# kind 语义：
#   result_files   仅结果/回执文件（.sandbar/.suyou）——零代码改动段  # naming-compat
#   write_set      写集内 + 结果文件（implement）
#   join           写集 ∪ integration/ + 结果文件（integ_join 汇合：implement+design 两边并集）
#   prefixes       指定目录前缀 + 结果文件（design_integration_tests）
#   ui_dirs        调用方传入的 ui_evidence.dirs 声明目录 + 结果文件（ui_evidence；
#                  声明读不到=空集=fail-closed）
#   ticket_receipts 仅本票场景回执（integration/<ticket_id>/）+ 结果文件（run_integration_tests）
#   test_face      测试面（is_test_face ∪ integration/ 已登记场景脚本）∪ 本票场景
#                  + 结果文件（arbitrate；tests-fault 直接迭代 integration/ 测试集）
#   self_heal      写集 ∪ 本票场景 + 结果文件（merge_check 的 KI-009 自愈专用：收场
#                  语义=替本票未落盘的写集内改动兜底，admission 已由调用方
#                  _dirty_within_write_set 前置把关；merge_check 段自身不产生代码改动）
STAGE_PATH_RULES = {
    "create_plan": {"kind": "result_files"},
    "review_plan": {"kind": "result_files"},
    "implement": {"kind": "write_set"},
    "integ_join": {"kind": "join"},
    "design_integration_tests": {"kind": "prefixes", "prefixes": ("integration",)},
    "ui_evidence": {"kind": "ui_dirs"},
    "run_integration_tests": {"kind": "ticket_receipts"},
    "arbitrate": {"kind": "test_face"},
    "acceptance_walkthrough": {"kind": "result_files"},
    "merge_check": {"kind": "self_heal"},
    "merge": {"kind": "result_files"},
    "suggest_next": {"kind": "result_files"},
}

# 段允许面的人读描述（拒绝回执用）。
_STAGE_FACE_DESC = {
    "result_files": "result/receipt files only (zero-code-change stage)",
    "write_set": "write-set files + result files",
    "join": "write-set files ∪ integration/ + result files (parallel-join stage)",
    "ui_dirs": "ui_evidence declared dirs + result files",
    "ticket_receipts": "this ticket's scenario receipts (integration/<ticket_id>/) + result files",
    "test_face": "test face (tests/ dirs, test_*.py, integration/ scenario scripts sc_*.py/.mjs, "
                 "scenario roster integration/README.md and integration/run_scenarios.py)"
                 " ∪ this ticket's scenarios ∪ declared build-chain outputs (bundle-out-face, named)"
                 " + result files",
    "self_heal": "write-set files ∪ this ticket's scenarios + result files (self-heal closeout)",
    "prefixes": None,  # prefixes 用规则里的前缀拼
}

# 项目外置模板可声明的允许面 kind 白名单（KI-124，t260925-23）：外置模板是跨项目
# 收件面，强 kind（self_heal/test_face/ui_dirs/ticket_receipts——分别等于授权动引擎
# 自愈面/测试裁决面/UI 证据声明面/场景回执面）缺省就该关；dev-lane 走内建表不受限。
# 加载口深检（project_templates，零 shared/path_gates import、依赖参数注入）以此表
# 拒收越面声明——两表漂移由单测交叉锁（tests/test_t260925_23_template_path_gate.py：
# 本表 ⊆ STAGE_PATH_RULES 全 kind 词表）。
TEMPLATE_WEAK_KINDS: Tuple[str, ...] = ("result_files", "write_set", "join", "prefixes")

# 出路文案（按原因码分派）。t260916-19 ③A 联动：出路点名可达动作——rework 打回
# design_integration_tests 只对 integration/ 面内容成立（design 段允许面=
# prefixes("integration",)）；其它面内容（如 server/ 文件在仲裁段被改）的出路是
# 建票把文件列入写集。保持限定语，不让泛化读法误导操作员。
_OUT_Unauthorized = ("sanctioned way out: rework back to design_integration_tests to fix the "
                     "integration/ face (scenarios/registry/shared test tools), or open a ticket "
                     "listing the file in its write set, or take the main-tree ticket route")
_OUT_PROTECTED = "sanctioned way out: human-review approval, or the main-tree ticket route"
_OUT_CONFIG = "sanctioned way out: complete the configuration and rerun, or take the main-tree ticket route"


# ---------------- Ticket test face (t261004-25: a lawful path for out-of-write-set deliverables) ----------------
#
# Failure on record (three instances in one day): a ticket's own engine-side unit
# test (server/engine/tests/test_<ticket>_*.py) is not in the frozen write set, so
# the stage path gate rules it unauthorized_path and auto-quarantines the untracked
# new file (t261004-18: the test never reached a commit); a committed one is reded
# by merge_check's in-lane verify_lane write-set whitelist (t261004-19: blocked with
# everything else green). Repair stance = "the name is the proof": a test file whose
# basename embeds the ticket's own slug has a blast radius of one tests directory
# and is structurally a lawful deliverable of that ticket — the frozen write set
# must not eat it. Every pass granted this way is NAMED (green note with file and
# rule), never silent. The predicate is pure, zero IO, stdlib-only — the verify_lane
# tool subprocess can import it directly (single source, no second copy).

TICKET_TEST_FACE_NOTE = "lawful deliverable outside the write set (ticket-test-face rule)"


# ---------------- Bundle-out-face rule (t261009-38: a declared build chain's output is a lawful deliverable) ----------------
#
# Deadlock on record (three instances): a ticket's frozen write set names a build
# chain's SOURCE prefix only, the lane rebuilds the derived output, and the gates
# then eat it from both sides — the settle stage path gate refuses the out-prefix
# write (not in the write set) while merge_check's bundle_freshness red demands
# exactly that rebuild (t261009-22, t261009-35: the rebuilt lib/ never entered a
# commit). Repair stance follows the ticket-test-face precedent (t261004-25):
# the declaration is the single source (server/merge-checks.yaml bundle_pairs —
# the same list merge_check item 3.5 reads), and when the paired src prefix is
# inside the ticket's own write set, a write under the out prefix is a LAWFUL
# DELIVERABLE, admitted as a NAMED pass (note names rule + file + paired src),
# never silently. The paired src NOT covered by the write set → the out write
# stays refused (nothing widens by accident). Declaration missing / malformed /
# without usable pairs → the gate admits nothing extra (fail-closed, never
# fail-open). Everything here is pure and zero-IO like the rest of the module:
# callers read the declaration file and pass the pairs in.

BUNDLE_OUT_FACE_NOTE = ("lawful build-chain deliverable outside the write set "
                        "(bundle-out-face rule, declared in server/merge-checks.yaml)")

# ---- merge_check auto-rework policy (261019) -------------------------------
#: The declaration key that opts a project INTO self-healing merge_check reds.
#: Design: the ENGINE owns the closed set of red classes whose remedy is a
#: mechanical, idempotent act (REMEDIABLE_RED_CODES) - it is the only party that
#: knows a red is machine-actionable. The PROJECT owns the policy (which of those
#: classes it wants auto-routed, to which stage, with what bound). Neither side
#: can invent the other: an undeclared class is never auto-routed, and a declared
#: class the engine does not know is refused by name (fail-closed, never "try
#: something anyway"). An absent key keeps the previous behaviour (every red
#: blocks for a human), so a project that says nothing is byte-unchanged.
AUTO_REWORK_POLICY_KEY = "merge_check_auto_rework"

#: The engine's closed registry: red code -> what the remedy mechanically IS.
#: `stage` is where the remedy can be performed; `remedy` is written into the
#: ticket's own reason (the lane agent reads it as the instruction); `sole_red`
#: means the route fires only when NO other red is present in the round, so a
#: self-heal can never mask a second, human-worthy problem.
REMEDIABLE_RED_CODES = {
    "bundle_stale": {
        "stage": "implement",
        "max_rounds": 2,
        "sole_red": False,
        "remedy": ("run the declared build entry of the pair named in "
                   "server/merge-checks.yaml (bundle_pairs entry:) and commit the "
                   "paired out prefix, then return to merge_check. The write set "
                   "already admits the out prefix (bundle-out-face widening); no "
                   "envelope change is needed."),
    },
    # 261019 second entry, and the reason the registry exists: the LANE
    # SELF-CHECK (the in-lane verify_lane code face) is feedback, not the
    # delivery judgment - the same property is re-judged by run_integration_tests
    # and by merge_check on the delivered tree. Measured on t261019-09: one test
    # of 5,335 failed inside the lane self-check (isolated rerun of that file:
    # 24 passed), and the ticket stopped needing a human to press retry although
    # the lane could look at the red and act. Routing it back to implement is the
    # same mechanical shape as a stale bundle: no human decision is encoded.
    "verify_red": {
        "stage": "implement",
        "max_rounds": 2,
        "sole_red": False,
        "remedy": ("read the named red(s) in the lane self-check detail, reproduce "
                   "them in the lane, and act on what they actually say: fix the "
                   "code, or - when the red is a load/flake artefact - prove it by a "
                   "quiet isolated rerun and let the following merge_check re-judge "
                   "the delivered tree."),
    },
}

#: Hard ceiling on a declared max_rounds: a policy can ask for fewer, never for
#: an unbounded loop (a build that never stabilises must reach a human).
AUTO_REWORK_MAX_ROUNDS_CEILING = 3


def parse_auto_rework_policy(text):
    """Parse the optional `merge_check_auto_rework:` section of merge-checks.yaml.

    Shape (all values bare tokens, one entry per line, no nesting):

        merge_check_auto_rework:
          - code: bundle_stale
            stage: implement        # optional: default = the registry's stage
            max_rounds: 2           # optional: default = the registry's bound

    Returns (policy, diag): `policy` maps red code -> {"stage", "max_rounds"};
    `diag` is "" on success and a NAMED reason otherwise. Fail-closed rules -
    every one of them measured as a refusal, never a silent skip:
      * a line inside the section that is not one of the three keys is refused;
      * a code the engine has no remedy for is refused (a typo must not read as
        "the project asked for nothing");
      * a stage outside the closed rework vocabulary (`implement`, the only
        stage where a mechanical rebuild belongs today) is refused;
      * max_rounds that is not a positive int is refused, and anything above
        AUTO_REWORK_MAX_ROUNDS_CEILING is CLAMPED DOWN (with the clamp named in
        the returned policy) rather than honoured.
    An absent section returns ({}, "") - no policy, no behaviour change.
    """
    if not isinstance(text, str):
        return {}, "policy text is not a string (fail-closed: no auto-rework)"
    entries = []
    cur = None
    in_section = False
    for raw in text.splitlines():
        ln = raw.replace("\t", "  ").rstrip()
        s = ln.strip()
        if not s or s.startswith("#"):
            continue
        if not ln.startswith(" "):
            in_section = (s == AUTO_REWORK_POLICY_KEY + ":")
            cur = None
            continue
        if not in_section:
            continue
        if s.startswith("- code:"):
            cur = {"code": s[len("- code:"):].strip()}
            entries.append(cur)
            continue
        if cur is None:
            return {}, "%s: a line before the first '- code:' entry: %s" % (
                AUTO_REWORK_POLICY_KEY, s)
        if s.startswith("stage:"):
            cur["stage"] = s[len("stage:"):].strip()
        elif s.startswith("max_rounds:"):
            cur["max_rounds"] = s[len("max_rounds:"):].strip()
        else:
            return {}, "%s: unparseable line inside the section: %s" % (
                AUTO_REWORK_POLICY_KEY, s)
    if not in_section and not entries:
        return {}, ""
    policy = {}
    for ent in entries:
        code = str(ent.get("code") or "").strip()
        if code not in REMEDIABLE_RED_CODES:
            return {}, ("%s: red code %r has no mechanical remedy in this engine "
                        "(known: %s)" % (AUTO_REWORK_POLICY_KEY, code,
                                         ", ".join(sorted(REMEDIABLE_RED_CODES))))
        spec = REMEDIABLE_RED_CODES[code]
        stage = str(ent.get("stage") or spec["stage"]).strip()
        if stage != spec["stage"]:
            return {}, ("%s: stage %r is outside the rework vocabulary for code %r "
                        "(only %r)" % (AUTO_REWORK_POLICY_KEY, stage, code,
                                       spec["stage"]))
        try:
            rounds = int(ent.get("max_rounds") or spec["max_rounds"])
        except (TypeError, ValueError):
            return {}, ("%s: max_rounds %r for code %r is not an integer"
                        % (AUTO_REWORK_POLICY_KEY, ent.get("max_rounds"), code))
        if rounds < 1:
            return {}, ("%s: max_rounds %d for code %r is not positive"
                        % (AUTO_REWORK_POLICY_KEY, rounds, code))
        policy[code] = {"stage": stage,
                        "max_rounds": min(rounds, AUTO_REWORK_MAX_ROUNDS_CEILING)}
    return policy, ""


def auto_rework_plan(checks, policy):
    """The round's auto-rework decision, as data the WORKFLOW can act on.

    Fires only when every red of the round is covered by an opted-in remediable
    code (and, for `sole_red` codes, when it is the round's only red) - one
    stage for the whole batch, because a rework has one target. Returns
    {"stage", "code", "note"} or None. The note carries what the gate measured
    so the lane agent reads a remedy, not a symptom.
    """
    reds = [c for c in (checks or []) if isinstance(c, dict) and not c.get("green")]
    if not reds or not isinstance(policy, dict) or not policy:
        return None
    stage = None
    codes = []
    lines = []
    for c in reds:
        code = str(c.get("reason_code") or "")
        spec = policy.get(code)
        if spec is None:
            return None                       # an un-opted-in red: a human decides
        if spec["stage"] != (stage or spec["stage"]):
            return None                       # two different targets: no single route
        stage = spec["stage"]
        if code not in codes:
            codes.append(code)
        files = c.get("files") or []
        lines.append("%s%s%s" % (
            code,
            (" (%s -> %s)" % (files[0], files[1])) if len(files) >= 2 else "",
            (" — " + str(c.get("detail"))) if c.get("detail") else ""))
    for code in codes:
        if REMEDIABLE_RED_CODES[code].get("sole_red") and len(reds) > 1:
            return None                       # a sole-red remedy must not batch
    remedy = " ".join(REMEDIABLE_RED_CODES[c]["remedy"] for c in codes)
    return {"stage": stage, "code": ",".join(codes),
            "note": ("merge_check sent this back for mechanical self-heal: %s. "
                     "What to do: %s" % ("; ".join(lines), remedy))}


def parse_bundle_pairs(text: str) -> List[Tuple[str, str]]:
    """Minimal parser for the bundle_pairs section of merge-checks.yaml — the
    pure, single implementation of the declaration format (t261009-38 review C1:
    it lives here, stdlib-only and zero-IO, so the verify_lane tool subprocess
    can import it directly the way it imports is_ticket_test_face; agent_activities
    and any other face import this same symbol — no second copy).

    Accepts only the fixed shape: top-level `bundle_pairs:` followed by indented
    `- src: <prefix>` / `out: <prefix>` entries with bare-token values; comments
    and blank lines are skipped; any other indented line inside the section
    raises ValueError (callers fail closed on the raise). Returns a list of
    (src, out) prefix tuples with both members non-empty (an entry missing its
    out is dropped, never guessed). Non-string input → [] (fail-closed)."""
    if not isinstance(text, str):
        return []
    pairs: List[Dict[str, str]] = []
    in_section = False
    cur: Optional[Dict[str, str]] = None
    for raw in text.splitlines():
        ln = raw.replace("\t", "  ").rstrip()
        s = ln.strip()
        if not s or s.startswith("#"):
            continue
        if not ln.startswith(" "):
            in_section = (s == "bundle_pairs:")
            cur = None
            continue
        if not in_section:
            continue
        if s.startswith("- src:"):
            cur = {"src": s[len("- src:"):].strip(), "out": ""}
            pairs.append(cur)
        elif s.startswith("out:") and cur is not None:
            cur["out"] = s[len("out:"):].strip()
        else:
            raise ValueError("merge-checks.yaml has an unparseable line: %s" % s)
    return [(p["src"], p["out"]) for p in pairs if p["src"] and p["out"]]


def bundle_out_face(path: Any, write_set: Any, bundle_pairs: Any) -> Optional[str]:
    """Is path a lawful bundle-out-face deliverable (t261009-38)?

    Returns the paired src prefix (for the named pass note) when ALL hold:
      1. path is a safe normalized path (malformed spellings cannot bypass the
         judge — same _norm_path/_is_safe_path stance as the test face);
      2. bundle_pairs is a list/tuple and some declared pair's out prefix covers
         path; pair members that are not plain safe prefix strings are skipped,
         never guessed;
      3. that pair's src prefix is covered by the ticket's write set
         (src == entry, or src under an entry, or an entry under src),
         judged with the same _within/_entries stance as the write-set
         match itself. (t261009-65: the write set may name concrete files
         under the src prefix — `src/client/a.c` covers `src/client` —
         the src side stays bound by the write-set judge, so widening
         the out side adds nothing the src side does not guard.)
    Anything else returns None = the write stays refused. Fail-closed by
    construction: a missing/malformed/empty declaration, a malformed path, or an
    empty/missing write set all return None — the gate admits nothing extra."""
    if not isinstance(path, str) or not path.strip():
        return None
    norm = _norm_path(path.strip())
    if not _is_safe_path(norm):
        return None
    if not isinstance(bundle_pairs, (list, tuple)):
        return None
    ws_ok, ws = _entries(write_set)
    if not ws_ok:
        return None
    for pair in bundle_pairs:
        if not isinstance(pair, (list, tuple)) or len(pair) != 2:
            continue
        raw_src, raw_out = pair[0], pair[1]
        if not isinstance(raw_src, str) or not isinstance(raw_out, str):
            continue
        src = _norm_path(raw_src.strip().rstrip("/")) if raw_src.strip() else ""
        out = _norm_path(raw_out.strip().rstrip("/")) if raw_out.strip() else ""
        if not src or not out or not _is_safe_path(src) or not _is_safe_path(out):
            continue
        if not _within(norm, (out,)):
            continue
        if _within(src, ws) or any(_within(e, (src,)) for e in ws):
            return src
    return None


def bundle_out_prefixes(write_set: Any, bundle_pairs: Any) -> List[str]:
    """Declared out prefixes whose paired src prefix is covered by the ticket's
    write set (t261009-38) — the widen list a merge gate may add to the
    whitelist it hands the lane tool, so the rebuilt output can enter the
    commit. Pure; same fail-closed stance as bundle_out_face: a missing/
    malformed/empty declaration or a missing/empty write set yields [] (nothing
    widens). Normalized (trailing slash stripped, dedup) with first-seen order
    kept, so the named note lists the members deterministically."""
    ws_ok, ws = _entries(write_set)
    if not ws_ok or not isinstance(bundle_pairs, (list, tuple)):
        return []
    outs: List[str] = []
    for pair in bundle_pairs:
        if not isinstance(pair, (list, tuple)) or len(pair) != 2:
            continue
        raw_src, raw_out = pair[0], pair[1]
        if not isinstance(raw_src, str) or not isinstance(raw_out, str):
            continue
        src = _norm_path(raw_src.strip().rstrip("/")) if raw_src.strip() else ""
        out = _norm_path(raw_out.strip().rstrip("/")) if raw_out.strip() else ""
        if not src or not out or not _is_safe_path(src) or not _is_safe_path(out):
            continue
        if (_within(src, ws) or any(_within(e, (src,)) for e in ws)) and out not in outs:
            outs.append(out)
    return outs


def ticket_slug(ticket_id: Any) -> str:
    """Ticket slug (t261004-19 -> t261004_19): strip, then replace '-' with '_'.
    Malformed input (empty / path separators) returns "" = predicate always False
    (fail-closed)."""
    s = str(ticket_id or "").strip()
    if not s or "/" in s or "\\" in s:
        return ""
    return s.replace("-", "_")


def is_ticket_test_face(path: Any, ticket_id: str) -> bool:
    """Is path a lawful ticket-test-face deliverable (t261004-25)?

    All four conditions must hold (narrow by design):
      1. ticket_id yields a slug (malformed id -> False; old tickets and unknown
         ids keep byte-identical old behavior);
      2. path is safe after normalization (reuses _norm_path/_is_safe_path so
         equivalent spellings cannot bypass the judge);
      3. basename starts with `test_`, ends with `.py`, and embeds the slug;
      4. path sits on a test face: a `tests/` path segment, or under integration/.
    """
    slug = ticket_slug(ticket_id)
    if not slug or not isinstance(path, str) or not path.strip():
        return False
    norm = _norm_path(path.strip())
    if not _is_safe_path(norm):
        return False
    parts = norm.split("/")
    base = parts[-1]
    if not (base.startswith("test_") and base.endswith(".py") and slug in base):
        return False
    return "tests" in parts[:-1] or parts[0] == "integration"


# ---------------- 基础判定（立场镜像 agent_activities 写集条目匹配，测试锁漂移） ----------------

def _is_safe_path(path: Any) -> bool:
    """路径合法性（fail-closed 立场与 _dirty_within_write_set 一致）：非串/空串、
    绝对路径、含反斜杠、含 `..` 段、含 git glob 哨兵字符（?!*[]）→ 一律不安全。"""
    if not isinstance(path, str) or not path:
        return False
    if path.startswith("/") or "\\" in path or path == ".." or path.startswith("../") \
            or "/../" in path or path.endswith("/.."):
        return False
    if any(ch in path for ch in "?!*[]"):
        return False
    return True


def _norm_path(path: str) -> str:
    """路径**归一**（`./x` → `x`、`a//b` → `a/b`、`a/../b` → `b`）——纯字符串处理。

    260926 独立复核新发现（宿主批准随批修；与 KI-125 同族＝「判据认字面不认归一」）：
    `_clean_files` 此前只做安全过滤、不规范化，于是 `./integration/known-red-baseline.json`、
    `integration//integration/known-red-baseline.json`、`a/../integration/known-red-baseline.json`
    这类**等价写法**判不进受保护名单（`_within` 逐字比对）＝同族纵深缺口。今天不可达
    （清单来自 `git status/diff`，git 输出已规范化；写集侧的等价写法只会误判 unauthorized
    ＝fail-closed），但判据不该认字面而不认归一。只用 posixpath（git 路径恒 `/` 分隔，
    不受宿主平台反斜杠语义影响）；空/非串由调用方先剔除，归一后仍不安全的由
    `_is_safe_path` 照旧拒（**fail-closed 方向不变**）。"""
    try:
        return posixpath.normpath(path)
    except (TypeError, ValueError):
        return path


def _clean_files(files: Iterable[Any]) -> List[str]:
    """脏文件清单清洗：非串/空串直接丢弃不猜；其余**先归一再看安全性**（fail-closed）。

    归一的后果逐条点名（不静默改语义）：
      - 等价写法（`./x`/`x//y`/`a/../x`）现在**进判定面**且判的是归一后的真路径——
        受保护/测试面等「认字面」的判据不再被等价写法绕过；
      - 归一后**仍**不安全的（绝对路径/残留 `..` 段/反斜杠/glob 哨兵）照旧丢弃不猜
        （清洗后不安全的条目不进判定，交由「清单外即违规」的调用方立场兜底）；
      - 归一可能把「原先因含 `..` 被丢」的写法变成一条**真路径**并据此判定（例：
        `.sandbar/../evil` → `evil`：不再被丢弃，而是按仓根真路径判 unauthorized＝更严）。"""
    out: List[str] = []
    for f in files if isinstance(files, (list, tuple)) else []:
        if not isinstance(f, str) or not f.strip():
            continue
        norm = _norm_path(f.strip())
        if _is_safe_path(norm):
            out.append(norm)
    return out


def _entries(write_set: Any) -> Tuple[bool, List[str]]:
    """条目表清洗：镜像 _dirty_within_write_set 的立场——write_set 非列表/空/任一条目
    非串或空白 → (False, [])（fail-closed，调用方据此报「补配写集」类原因码）。"""
    if not isinstance(write_set, list) or not write_set:
        return (False, [])
    pats: List[str] = []
    for p in write_set:
        if not isinstance(p, str) or not p.strip():
            return (False, [])
        s = p.strip().rstrip("/")
        if s:
            pats.append(s)
    if not pats:
        return (False, [])
    return (True, pats)


def _within(path: str, entries: Sequence[str]) -> bool:
    """Entry match: path == entry, or path has the directory prefix "entry + /"
    (an entry such as `app/src` names a whole prefix; a trailing slash is equivalent).

    The trailing-slash promise must actually hold (261012 host-ordered direct fix):
    the old implementation appended "/" verbatim, so an entry written as
    `integration/baselines/` matched NOTHING — while this docstring promised the two
    forms were equivalent. The failure was silent: a recorded human authorization
    (authz_gates._match -> this function) stayed unapplied, the gate refused again and
    never said the scope had missed (KI-01M4PKH23DKWXY1KFM490S7P8F). Normalize each
    entry (strip trailing slashes) before matching; an empty or degenerate entry
    matches nothing — a miss is safer than a pass.
    """
    return any(
        s and (path == s or path.startswith(s + "/"))
        for s in (str(e).rstrip("/") for e in entries))


def _is_result_file(path: str) -> bool:
    return _within(path, RESULT_FILE_PREFIXES)


def _is_scenario_script(path: str) -> bool:
    """integration/ 下已登记场景脚本与登记表本身（t260911-03 CF2；t260916-19 ③
    声明=执法）：场景脚本=integration/ 下任意深度的 sc_*.py / sc_*.mjs——顶层场景
    （sc_check_auto_rework_trace / sc_scenarios_guard_* 等四条，均在
    run_scenarios.py SCENARIOS 登记内）与子目录场景同属测试集，仲裁 tests-fault
    直接迭代测试集是本职；integration/README.md=场景登记表（t260916-19 ③：仲裁
    改登记是本职，与 run_scenarios.py 同款「登记=正常工作面」特例）。
    integration/run_scenarios.py（场景登记=正常工作面，不受保护）同放行。
    共享资产仍由受保护闸兜底（如 t260902-07 守卫、integration/baselines）。
    integration/lint_tests.py 是共享 lint 工具，非场景非登记，不放行——内容修改
    的合法出路：rework 打回 design_integration_tests（integration/ 前缀面）或
    建票把文件列入写集。"""
    if not _is_safe_path(path):
        return False
    if path in ("integration/run_scenarios.py", "integration/README.md"):
        return True
    segs = path.split("/")
    if segs[0] != "integration" or len(segs) < 2:
        return False
    base = segs[-1]
    return base.startswith("sc_") and (base.endswith(".py") or base.endswith(".mjs"))


def is_test_face(path: str) -> bool:
    """测试面口径（定稿）：路径含 `tests/` 目录段（含仓库根 tests/ 开头），或文件名
    匹配 test_*.py / *_test.py。conftest.py 等测试辅助不在 tests/ 目录内的不算
    （口径=「tests 目录内或测试文件名」，宁窄勿宽——仲裁段改产品代码必须拦）。"""
    if not _is_safe_path(path):
        return False
    segs = path.split("/")
    if "tests" in segs[:-1] or (len(segs) >= 2 and segs[0] == "tests"):
        return True
    base = segs[-1]
    return base.startswith("test_") and base.endswith(".py") \
        or base.endswith("_test.py")


def _resolve_stage_rule(stage_id: str, template_rules: Any) -> Optional[Dict[str, Any]]:
    """段规则解析单点（KI-124）：先查本票模板声明表（TicketInput.path_gate_rules，
    建票时自模板类 PATH_GATE_RULES 钉死），再回落内建 STAGE_PATH_RULES。

    成员判断（`in`）而非 `.get() or`——声明即真源：模板声明了空/假值规则（{}、""、
    None）时**不得**静默跌回内建表（falsy 遮蔽=装死），返回 kind 为空的规则让
    judge 走「规则表内未知 kind → fail-closed」既有出口。畸形 template_rules
    （非 dict）整体忽略回内建表（fail-closed 不放大，加载口深检才是畸形声明的主拦面）。"""
    sid = str(stage_id or "")
    if isinstance(template_rules, dict) and sid in template_rules:
        raw = template_rules[sid]
        if isinstance(raw, str) and raw.strip():
            return {"kind": raw.strip()}
        if isinstance(raw, dict) and isinstance(raw.get("kind"), str) and raw.get("kind").strip():
            out = dict(raw)
            out["kind"] = raw["kind"].strip()
            return out
        return {"kind": ""}  # 声明了假值：不回落、fail-closed（unknown kind 出口）
    return STAGE_PATH_RULES.get(sid)


# ---------------- ① 阶段路径闸 ----------------

def judge_stage_paths(stage_id: str, files: Iterable[Any], write_set: Any = None,
                      ticket_id: str = "", ui_dirs: Any = None,
                      template_rules: Any = None,
                      notes_out: Optional[List[str]] = None,
                      bundle_pairs: Any = None
                      ) -> Tuple[bool, List[str], str]:
    """段 × 允许面判定。返回 (allowed, violations, reason_code)；allowed=True 时
    violations 为空、reason_code 为 ""。

    - 规则解析单点 _resolve_stage_rule：先本票模板声明表（template_rules，KI-124
      随派单钉死进 TicketInput.path_gate_rules），再回落内建 STAGE_PATH_RULES。
    - 两边皆无此段键 → fail-closed 拒绝（reason=unknown_stage），不允许
      「未知段=放行」——新段/新模板忘配规则 = 被拦 + 单测锁定（源码锁定测试断言
      DevLaneWorkflow.STAGES id 全集 ⊆ 规则键集；外置模板=加载口深检
      PATH_GATE_RULES 键 ⊆ 本模板 STAGES id 全集，声明缺失进拒绝回执文案点名补法）。
    - 写集空/缺失（write_set/write_join/self_heal 类）→ reason=write_set_missing，
      出路=补配写集（沿用既有 helper 空写集 fail-closed 立场，显式化）。
    - 结果文件（.sandbar/.suyou）对所有段放行（不进 commit，与 SETTLE_PATHSPEC 排除  # naming-compat
      现实一致）。
    - bundle_pairs (t261009-38, optional): the declaration pairs ((src, out)
      prefixes) the caller loaded from this repo's server/merge-checks.yaml.
      Default None = the judged face stays byte-identical to history; the
      write_set/join/self_heal kinds and (since t261009-65) the test_face kind
      gain a fallback: a file that misses the kind's own face tries the
      ticket-test-face fallback, then the bundle-out-face
      fallback (paired src inside the write set -> the out-prefix write is
      admitted and NAMED; declaration missing/malformed/empty -> the fallback
      judges None and nothing widens).
    """
    clean = _clean_files(files)
    rule = _resolve_stage_rule(stage_id, template_rules)
    if rule is None:
        return (False, list(clean), "unknown_stage")
    rest = [f for f in clean if not _is_result_file(f)]
    if not rest:
        return (True, [], "")
    kind = rule.get("kind")
    ws_ok, ws = _entries(write_set)
    ui_ok, ui = _entries(ui_dirs)
    receipt = ("integration/" + str(ticket_id).strip("/")) if str(ticket_id or "").strip("/" ) else ""

    def face(f: str) -> str:
        """Per-file verdict: "" (allowed) or a reason code. t261004-25: under the
        write_set / join / self_heal kinds, a ticket-test-face file that loses the
        write-set match is passed by the is_ticket_test_face fallback — and the
        pass must be named (appended to notes_out; the caller joins it into the
        settle receipt), never silent."""
        def _test_face_ok() -> bool:
            if not is_ticket_test_face(f, ticket_id):
                return False
            if notes_out is not None:
                notes_out.append("%s: %s" % (TICKET_TEST_FACE_NOTE, f))
            return True

        def _bundle_out_ok() -> bool:
            # t261009-38: after the test-face fallback misses, a declared build
            # chain's out prefix is a lawful deliverable when its paired src is
            # inside the write set — the pass is NAMED (rule + file + paired src),
            # never silent; a missing/malformed declaration admits nothing.
            src = bundle_out_face(f, write_set, bundle_pairs)
            if src is None:
                return False
            if notes_out is not None:
                notes_out.append("%s: %s (src %s)" % (BUNDLE_OUT_FACE_NOTE, f, src))
            return True
        if kind == "result_files":
            return "unauthorized_path"
        if kind == "write_set":
            if ws_ok and _within(f, ws):
                return ""
            return "" if (_test_face_ok() or _bundle_out_ok()) else \
                ("write_set_missing" if not ws_ok else "unauthorized_path")
        if kind == "join":
            if _within(f, ("integration",)):
                return ""
            if ws_ok and _within(f, ws):
                return ""
            return "" if (_test_face_ok() or _bundle_out_ok()) else \
                ("write_set_missing" if not ws_ok else "unauthorized_path")
        if kind == "prefixes":
            return "" if _within(f, rule.get("prefixes") or ()) else "unauthorized_path"
        if kind == "ui_dirs":
            return "" if (ui_ok and _within(f, ui)) else \
                ("ui_dirs_missing" if not ui_ok else "unauthorized_path")
        if kind == "ticket_receipts":
            return "" if (receipt and _within(f, (receipt,))) else "unauthorized_path"
        if kind == "test_face":
            if is_test_face(f) or _is_scenario_script(f):
                return ""
            # t261009-65: arbitrate gains the same bundle-out-face fallback the
            # write_set / join / self_heal kinds carry — a rebuilt out-prefix
            # file written during arbitrate is a NAMED pass, not an
            # "unauthorized write" (ruling 261010; held-edit from t261009-58).
            return "" if (_test_face_ok() or _bundle_out_ok()) else "unauthorized_path"
        if kind == "self_heal":
            if ws_ok and _within(f, ws):
                return ""
            if receipt and _within(f, (receipt,)):
                return ""
            return "" if (_test_face_ok() or _bundle_out_ok()) else \
                ("write_set_missing" if not ws_ok else "unauthorized_path")
        return "unknown_stage"  # 规则表内未知 kind：规则表自身配错，同样 fail-closed

    violations = [f for f in rest if face(f)]
    if not violations:
        return (True, [], "")
    return (False, violations, face(violations[0]))


# ---------------- ② 受保护路径闸 ----------------

def judge_protected_paths(files: Iterable[Any],
                          exists_at_base: Optional[Callable[[str], bool]] = None
                          ) -> Tuple[List[str], str]:
    """受保护名单判定。返回 (violations, reason_code)；无命中返回 ([], "")。

    「存在才拦」：名单内文件还要在泳道分叉点（base_ref）已存在才算改真源——新建
    （base 不存在）放行，落地后即受保护（闸不挡自己的出生）。exists_at_base 为 None
    （调用方无法锚定基点）→ 一律按已存在处理（fail-closed 拦），绝不因锚缺失放行。
    路径先经 `_clean_files` **归一**再比对（260926）：`./x`/`x//y`/`a/../x` 与真路径同判，
    等价写法不构成绕过；`exists_at_base` 收到的也是归一后的真路径（锚查询更准）。
    """
    clean = _clean_files(files)
    violations: List[str] = []
    for f in clean:
        if not _within(f, PROTECTED_PATHS):
            continue
        if exists_at_base is not None:
            try:
                if not exists_at_base(f):
                    continue
            except Exception:
                pass  # 谓词故障=锚不可知：按已存在处理（fail-closed 拦，不猜）
        violations.append(f)
    if not violations:
        return ([], "")
    return (violations, "protected_path")


# ---------------- 拒绝回执（机读键值 + 点名 + 出路） ----------------

def _fmt_files(files: Sequence[str], cap: int = 3) -> str:
    shown = list(files[:cap])
    tail = "" if len(files) <= cap else " (+%d more)" % len(files)
    return "、".join(shown) + tail


def gate_refusal_note(stage_id: str, violations: Sequence[str], reason_code: str) -> str:
    """构造单行拒绝回执：内嵌 path_gate_reason=<码>（is_gate_refusal 以此辨认）+
    点名段与文件 + 合法出路。行内不含换行（settle note 以「；」拼接进 evidence）。"""
    names = _fmt_files(violations)
    if reason_code == "protected_path":
        return ("Protected-path gate refused the write (%sprotected_path): %s is on the "
                "protected list (source of truth and expected values, baseline already "
                "exists); no lane may change it — %s"
                % (PATH_GATE_REASON_KEY, names, _OUT_PROTECTED))
    if reason_code == "unknown_stage":
        return ("Stage path gate refused the write (%sunknown_stage): stage %s has no "
                "configured allowed face (fail-closed, never silently exempted) — lawful "
                "way out: declare PATH_GATE_RULES[\"%s\"]=<allowed-face kind> on that "
                "template class (external templates accept only weak faces: %s), or use "
                "a configured stage; %s"
                % (PATH_GATE_REASON_KEY, stage_id, stage_id,
                   "/".join(TEMPLATE_WEAK_KINDS), _OUT_CONFIG))
    if reason_code == "write_set_missing":
        return ("Stage path gate refused the write (%swrite_set_missing): stage %s has "
                "no write set to judge (write set empty/missing); change %s falls "
                "outside the whitelist face — %s"
                % (PATH_GATE_REASON_KEY, stage_id, names, _OUT_CONFIG))
    if reason_code == "ui_dirs_missing":
        return ("Stage path gate refused the write (%sui_dirs_missing): stage %s cannot "
                "read the ui_evidence declared dirs; change %s has no whitelist to "
                "judge against — %s"
                % (PATH_GATE_REASON_KEY, stage_id, names, _OUT_CONFIG))
    if reason_code == "status_failed":
        return ("Path gate could not judge (%sstatus_failed): git status failed, change "
                "list unknown, fail-closed no write — way out: fix the environment and "
                "rerun (environment class, filed as the environment state of the "
                "protocol tri-state)"
                % PATH_GATE_REASON_KEY)
    rule = STAGE_PATH_RULES.get(str(stage_id or ""))
    desc = _STAGE_FACE_DESC.get(rule.get("kind")) if rule else None
    if rule and rule.get("kind") == "prefixes":
        desc = "only %s" % ", ".join(rule.get("prefixes") or ())
    return ("Stage path gate refused the write (%sunauthorized_path): stage %s does not "
            "allow changing %s (this stage allows only: %s) — %s"
            % (PATH_GATE_REASON_KEY, stage_id, names,
               desc or "faces declared by the rules table", _OUT_Unauthorized))


def is_gate_refusal(note: str) -> bool:
    """settle note 是否为闸拒绝回执（机器口径：含 path_gate_reason= 键值）。"""
    return PATH_GATE_REASON_KEY in str(note or "")


# ---------------- 结构化红灯明细（t260915-01；只结构化既有结论，零新判定） ----------------

_NEXT_ACTION_HINTS = {
    "unauthorized_path": "Out-of-scope files are auto-disposed by the engine per git "
                         "state (new files moved aside, unstaged edits rolled back and "
                         "archived; deletions and staged states left to humans); if the "
                         "content truly needs the change: integration/-face content "
                         "goes through rework back to design_integration_tests, other "
                         "faces file a ticket to add the file to the write set",
    "protected_path": "Changes to shared source of truth and guards go through a "
                      "dedicated main-side ticket; this ticket reads only, writes "
                      "nothing",
    "unknown_stage": "Declare on the template class for this stage: "
                     "PATH_GATE_RULES[\"<stage id>\"]=<allowed-face kind> (external "
                     "templates accept only weak faces result_files/write_set/join/"
                     "prefixes), or use a configured stage",
    "write_set_missing": "Ticket write set is empty/missing — return to create_plan to "
                         "restore the structured receipt before implementing",
    "ui_dirs_missing": "Add the ui_evidence.dirs declaration to verify.yaml (or supply "
                       "screenshot evidence per the project's convention)",
    "status_failed": "Repair the lane git environment (git status failure = change "
                     "list unknown, fail-closed), then send retry_qc to re-verify",
}


def next_action_hint(reason_code: str) -> str:
    """reason_code → 人话下一步动作（与 gate_refusal_note 的出路文案同向，不改 note）。"""
    return _NEXT_ACTION_HINTS.get(
        str(reason_code or ""), "Verify this refusal cause against the worker log "
        "before acting")


def gate_red_detail(stage_id: str, violations: Sequence[str],
                    reason_code: str, note: str,
                    judged_files: Optional[Sequence[str]] = None) -> Dict[str, Any]:
    """闸拒绝的结构化检查项明细（t260915-01 ②；t260916-19 ④ 加 judged_files），供
    详情页「人话红灯卡」。

    纯函数、零判定：输入=闸已算出的 violations/reason_code 与**原样** note。
    files 全量不截断——_fmt_files 的 cap 只作用于人读 note 文本，结构化面必须保真
    （「不得丢文件」验收口径）。judged_files=本次实际判定的脏文件全量清单（含未
    违规项）——拒绝回执只有违规清单时，操作员无法核对「判定面是否一致」（同秒两条
    settle 日志歧义的根源之一，t260916-11 实案）；None/畸形 → 空列表。evidence=note
    原文（与 worker 日志同一字符串，满足「与 worker 日志原文一致」）。畸形输入
    fail-visible 不抛：violations 非字符串序列→files=[]；reason_code 空→
    gate_refusal_unknown（消费侧还有 sanitize_gate_refusal 兜底）。"""
    files: List[str] = []
    if isinstance(violations, (list, tuple)):
        files = [str(v) for v in violations if isinstance(v, str) and v]
    jf: List[str] = []
    if isinstance(judged_files, (list, tuple)):
        jf = [str(f) for f in judged_files if isinstance(f, str) and f]
    rc = str(reason_code or "").strip() or "gate_refusal_unknown"
    return {
        "check_id": "path_gate@%s" % (str(stage_id or "") or "unknown_stage"),
        "item": "Protected-path gate" if rc == "protected_path" else "Stage × allowed-face path gate",
        "red": True,
        "reason_code": rc,
        "files": files,
        "judged_files": jf,
        "next_action": next_action_hint(rc),
        "evidence": str(note or ""),
    }


def sanitize_gate_refusal(raw: Any) -> Optional[Dict[str, Any]]:
    """跨活动边界来的 gate_refusal 写上票面前的校形（t260915-01 ② C7）。

    引擎侧不把未校验数据当契约面：返回 None = 不可救（非 dict / reason_code 键
    缺失或非串），消费点不写；返回 dict = 可上台面（缺 files→[]；files 非列表→
    降级可辨码 gate_refusal_malformed）。只校形不改判定语义：合法字段原样透传。"""
    if not isinstance(raw, dict):
        return None
    rc = raw.get("reason_code")
    if not isinstance(rc, str) or not rc.strip():
        return None
    files = raw.get("files")
    malformed = False
    if files is None:
        files = []
    elif not isinstance(files, list):
        files, malformed = [], True
    out = dict(raw)
    if malformed:
        out["reason_code"] = "gate_refusal_malformed"
    out["files"] = [str(f) for f in files if isinstance(f, (str, int, float))]
    return out
