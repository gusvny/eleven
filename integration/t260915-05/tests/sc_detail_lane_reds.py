#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""sc_detail_lane_reds.py — 详情观测面三红旅程（t260915-05 验收①③，灰盒 L3＋契约锁）。

Intent（用户可感知面，一张真票走完 mock ①③ 的完整旅程）：
  ① merge_check 红灯票面（验收①「合并检查红」子用例）：越写集探针提交进泳道分支（场景
     直构探针路径；真判定=merge_check 的 verify_lane_code 全量在场）→ merge_check
     第 1 轮 verify_lane_code 红（reason_code=verify_red）→
     非冲突红不自动返工、转 blocked——blocked_detail={check_id=verify_lane_code, red,
     reason_code=verify_red, files 列表, next_action, evidence 点名越界文件}＋gate_runs
     尾轮红（轮次带数据源）＋正规入口 ticket.py show 投影面同可达（跨组件缝）。
  ② 人门等待（验收①「人门等待」子用例＋蓝卡数据源）：人清探针（revert）+retry_qc →
     merge_check 第 2 轮全绿（gate_runs 红→绿两轮留痕＝逐轮格真实数据）→ merge 人门
     awaiting-human：human_context.merge.context_text＋stage_acceptance 在场（蓝卡
     「签什么」数据源）；blocked_detail 已清（R2 生命周期）。
  ③ 关单全量可见（验收③ KI-027 关单半）：正规入口 sign approve → 落账 COMPLETED →
     ticket.py show 经 result() 终态快照仍可读 timeline/gens/gate_runs/topology 全套，
     topology 过投影白名单可达（引擎→ticket.py 跨组件缝——快照半到不了 UI 则本断言红）
     且 merge kind=human（泳道图人门虚线圈数据源不灭）。
  路径闸拒绝子用例**不在此造**：t260915-01 journey 已真构造并逐字段断言 blocked_detail
  全字段（intent 本体属彼），本条零重复断言。

分工（防 intent 级重复）：t260915-01 journey＝blocked 唤醒清态/结构化明细回执/轮次维度
（本条不复断其字段，只在 merge/人门/关单三子用例上补观测面）；t260911-05＝merge 分类
（conflict/脏工作区）与 KI-048 红卡 DOM 呈现（本条的 verify_red 族非其分类面，DOM 呈现
归彼与同票 DOM 场景）；t260908-01 系＝仲裁超限/暂停语义；t260912-03＝authorize 例外
通道（本条只用 plain sign 正规入口）；developer L1（纯函数/源码锁矩阵）不同层。

契约锁（stdlib 恒跑，docker 台外可守的跨组件缝；通道锚定，不锚引擎内部函数名——灰盒
绑定要浅）：经 tools list 通道验拓扑导出结构（merge kind=human、两组成员与 run() 两真
分叉一致、组相位键与 meta.parallel_phase 契约串一致、ui_evidence 以 optional 表达、
边含单向流末端 merge_check→merge）、fixture 环境门出没（SANDBAR_FIXTURE_TEMPLATES=1
时 fixture-two-step 行带线性 topology＝渲染器通用性对拍通道；无门不出列=收窄守卫零
扰动）、dev_lane snapshot 透传 topology（终态快照同源 _snapshot→snapshot，关单可达）、
ticket.py 投影白名单带 topology（跨组件缝：缺=快照半到不了 UI，KI-046/049「测试在场
≠缝接通」形状的正向锁）。

执行契约（t260910-13 三态）：stdlib 锁恒跑；docker/镜像/舞台/venv 缺供=exit 2
ENV_FAIL（旅程子用例不跑，锁已跑）；被测行为破面=exit 1。pool=engine（真起台+真票）。
实现段落地前红属预期（TDD 信号），arbitrate/merge 期必须绿。
红线：一切 git/票写入只发生在 tempfile 夹具仓与一次性隔离台；对仓库工作区零写入
（ticket.py show 的 admin.log 钉场景临时目录）；被测子进程 Temporal 地址只指一次性
舞台；审计钩子自证零生产面接触（7233/8233/3099）。

借用清单（岗位纪律：借什么/带过来什么/不带什么）：
  - 借 t260915-01 lib_detail_journey＋t260908-01 lib_ki061 台架——带过来：tempfile
    夹具仓、专属 worker（新旧双前缀队列）、SANDBAR_ADMIN_LOG 钉
    临时目录、审计钩子、TERM→KILL 收尾、blocked/fork 轮询helper；不带：journey 的
    路径闸 blocked→唤醒清态断言（intent 本体属彼，防重复）。
  - 借 t260912-03 正规入口 op=sign 先例——带：input 载荷形状（who/gate/decision/note）
    与审计同源；不带：authorize 例外通道（本票无受保护路径/超限场景）。降级锚：若
    隔离台 sign 面行为有出入，该子用例断言到 awaiting-human 为止并在输出点名，不造假绿。
  - 夹具仓分支名归一 main：_merge_base_ref 硬编码 `merge-base main <branch>`
    （agent_activities._merge_base_ref）——不归一＝merge_base_failed 环境性假红。
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
sys.path.insert(0, os.path.dirname(HERE))                    # 票目录根（lib）
sys.path.insert(0, os.path.join(REPO, "integration"))
sys.path.insert(0, os.path.join(REPO, "integration", "t260904-02"))
sys.path.insert(0, os.path.join(REPO, "integration", "t260908-01"))
sys.path.insert(0, os.path.join(REPO, "integration", "t260915-01"))
sys.path.insert(0, os.path.join(REPO, "server", "engine"))

from lib_env import clean_narrowing_env  # noqa: E402  (261022: the import went missing
# in an earlier refactor; the call below kept compiling only until it ran)
from lib_gate import (Fail, parse_out_json, poc_python, read_audit_jsonl,  # noqa: E402
                      require_bench, require_stage, run_poc_client, stage_down)
from lib_ki061 import (make_fixture_repo, stage_env, spawn_worker, send_signal,  # noqa: E402
                       query_snapshot, poll, wait_worker_alive)
from lib_detail_journey import (ticket_show_face,  # noqa: E402
                                wait_fork_window, wait_stage_running)

TID = "t26091505r1"
PROJ = "t26091505"
WRITE_SET = ["docs/"]

# 桩脑（改自 t260915-01 DETAIL_STUB）：files_changed 带 docs 改动（merge_check 第 1 项
# 「泳道分支有 commit」需泳道有 commit；探针提交由场景另行入轨），分叉两 Edge 各睡数秒
# 拉宽并行窗（探针提交窗口）。
LANE_RED_STUB = r"""
import json, os, re, sys, time
prompt = sys.argv[-1] if len(sys.argv) > 1 else ""
m = re.search(r"阶段：([a-z_]+)（", prompt)
stage = m.group(1) if m else "unknown"
with open(os.environ["KI061_STUB_LOG"], "a", encoding="utf-8") as f:
    f.write(json.dumps({"stage": stage, "ts": time.time()},
                       ensure_ascii=False) + "\n")
if stage in ("implement", "design_integration_tests",
             "arbitrate", "acceptance_walkthrough"):
    time.sleep(6)  # 拉宽并行分叉窗（探针提交窗口）
m = re.search(r"干完把结果写到 (\S+?\.json)", prompt)
if m:
    rfile = m.group(1)
    # arbitrate 段 summary 必须带 verdict= 契约标记（缺=仲裁结论 4 轮打回超限
    # blocked，旅程到不了 merge_check——260915 implement 段自测首跑实证）。
    # 修桩：本旅程恒走 pass 边（verdict=pass）。
    if stage == "arbitrate":
        summary = "[t26091505-stub] arbitrate 完成 verdict=pass（集成测试集全绿，可进验收）"
    else:
        summary = "[t26091505-stub] %s 完成" % stage
    body = {"status": "ok", "summary": summary,
            "report": "[t26091505-stub] 桩回执", "deliverables": [],
            "files_changed": ["docs/ticket-notes.md"], "files_changed_shape": "ok",
            "evidence": "t26091505-stub"}
    with open(rfile, "w", encoding="utf-8") as f:
        json.dump(body, f, ensure_ascii=False)
"""


# ---------------- stdlib 契约锁（docker 台外可守的跨组件缝，恒跑） ----------------

def _read(rel):
    with open(os.path.join(REPO, rel), encoding="utf-8") as f:
        return f.read()


def _between(src, start, end):
    i = src.find(start)
    if i < 0:
        return ""
    j = src.find(end, i + 1)
    return src[i:j] if j > i else src[i:]


def _run_py(py, code, env_extra=None):
    # 260930：这些片段跑的是执行器/闸链（L12 判据）——剥掉继承来的收窄/策略旋钮再注入夹具档
    e = clean_narrowing_env(env_extra or {})
    p = subprocess.run([py, "-c", code], cwd=REPO, env=e,
                       capture_output=True, text=True, timeout=180)
    return p.returncode, p.stdout, p.stderr


def stdlib_locks(fail, py):
    """跨组件缝契约锁（通道锚定，不锚引擎内部函数名——灰盒绑定要浅）。

    锁①经 tools list 通道验拓扑导出结构（真通道：workflow.py 直跑）；
    锁②验 fixture 环境门（渲染器通用性对拍通道）；锁③验 snapshot 透传与
    ticket.py 投影白名单（引擎→台面缝）。"""
    expected_ids = ["create_plan", "review_plan", "implement", "design_integration_tests",
                    "ui_evidence", "run_integration_tests", "arbitrate",
                    "acceptance_walkthrough", "merge_check", "merge"]

    def _list_rows(env_extra):
        rc, out, err = _run_py(py,
                               "import subprocess,sys,os;"
                               "p=subprocess.run([sys.executable,'server/tools/workflow.py'],"
                               "capture_output=True,text=True);print(p.stdout)", env_extra)
        if rc != 0 or not out.strip():
            return None, "rc=%s err尾=%s" % (rc, (err or "")[-160:])
        try:
            return json.loads(out.strip()).get("workflows") or [], ""
        except Exception as exc:
            return None, "回执不可解析（%s）" % exc

    # ---- 锁①：list 通道 dev-lane topology 结构（模板级导出＝KI-027 拓扑半＋mock ④ F）----
    rows, why = _list_rows(None)
    if rows is None:
        fail.check(False, "契约锁：workflow.py list 可直跑（%s）" % why)
    else:
        devrow = [r for r in rows if r.get("id") == "dev-lane"]
        topo = (devrow[0].get("topology") if devrow else None)
        if not (devrow and isinstance(topo, dict)):
            fail.check(False, "契约锁：list 通道 dev-lane 行带 topology（模板级导出半；"
                              "实得行=%r）" % [r.get("id") for r in rows])
        else:
            nodes = topo.get("nodes") or []
            ids = [n.get("id") for n in nodes]
            kinds = {n.get("id"): n.get("kind") for n in nodes}
            fail.check(all(e in ids for e in expected_ids),
                       "契约锁：拓扑节点集盖全 STAGES（缺=%r）"
                       % [e for e in expected_ids if e not in ids])
            fail.check(kinds.get("merge") == "human",
                       "契约锁：merge 节点 kind=human（人门标记真源，%r）" % kinds.get("merge"))
            groups = topo.get("groups") or []
            members = {frozenset(g.get("members") or []) for g in groups}
            fail.check(len(groups) == 2
                       and frozenset({"implement", "design_integration_tests"}) in members
                       and frozenset({"arbitrate", "acceptance_walkthrough"}) in members,
                       "契约锁：两组真并行成员与 run() 两真分叉一致（%r）"
                       % [sorted(g.get("members") or []) for g in groups])
            phases = {str(g.get("phase") or "") for g in groups}
            fail.check({"parallel_impl_design", "arb_acc_parallel"} <= phases,
                       "契约锁：组相位键与 meta.parallel_phase 契约串一致（%r）" % sorted(phases))
            ui = [n for n in nodes if n.get("id") == "ui_evidence"]
            fail.check(bool(ui) and bool(ui[0].get("optional")),
                       "契约锁：ui_evidence 条件段带 optional 注记（渲染器虚节点＋注记"
                       "数据源；布尔位或注记串均可辨，实得=%r）"
                       % (ui[0].get("optional") if ui else None))
            fail.check(["merge_check", "merge"] in (topo.get("edges") or []),
                       "契约锁：边含 merge_check→merge（单向流末端；%r尾）"
                       % (topo.get("edges") or [])[-3:])
        fail.check(not [r for r in rows if r.get("id") == "fixture-two-step"],
                   "契约锁：无环境门时 fixture-two-step 不出列（收窄守卫零扰动）")

    # ---- 锁②：SANDBAR_FIXTURE_TEMPLATES 门出没（渲染器通用性对拍通道）----
    rows3, why3 = _list_rows({"SANDBAR_FIXTURE_TEMPLATES": "1"})
    if rows3 is None:
        fail.check(False, "契约锁：环境门下 workflow.py list 可直跑（%s）" % why3)
    else:
        fxrow = [r for r in rows3 if r.get("id") == "fixture-two-step"]
        ftopo = (fxrow[0].get("topology") if fxrow else None)
        if not (fxrow and isinstance(ftopo, dict)):
            fail.check(False, "契约锁：SANDBAR_FIXTURE_TEMPLATES=1 时 fixture-two-step 行"
                              "带 topology（渲染器通用性对拍通道；实得=%r）"
                              % [r.get("id") for r in rows3])
        else:
            fnodes = ftopo.get("nodes") or []
            fail.check(len(fnodes) == 2 and not (ftopo.get("groups") or [])
                       and len(ftopo.get("edges") or []) == 1,
                       "契约锁：fixture 拓扑=线性两段（nodes=%r edges=%d groups=%d）"
                       % ([n.get("id") for n in fnodes], len(ftopo.get("edges") or []),
                          len(ftopo.get("groups") or [])))

    # ---- 锁③：snapshot 透传 + ticket.py 投影白名单（跨组件缝）----
    dl = _read(os.path.join("server", "engine", "dev_lane.py"))
    snap_body = _between(dl, "def snapshot(", "def sign_face(")
    fail.check(bool(snap_body) and '"topology"' in snap_body,
               "契约锁：dev_lane snapshot 透传 topology（终态快照同源 _snapshot→snapshot，"
               "关单可达；KI-027 数据半前提）")
    tp = _read(os.path.join("server", "tools", "ticket.py"))
    wl_lines = [ln for ln in tp.splitlines() if "for k in (" in ln and "gate_runs" in ln]
    fail.check(bool(wl_lines), "契约锁：ticket.py 投影白名单元组在位（gens 先例形状）")
    if wl_lines:
        i = tp.find(wl_lines[0])
        j = tp.find(")", i)
        seg = tp[i:j + 1] if j > i else tp[i:i + 400]
        fail.check("'topology'" in seg or '"topology"' in seg,
                   "契约锁：投影白名单带 topology（引擎→台面跨组件缝；缺=快照 topology 半"
                   "到不了 UI，「快照有则用快照」成死代码）")


# ---------------- docker 旅程子用例（真台真票真 worker） ----------------

def journey(fail, bench):
    py = poc_python(bench)
    tmp = tempfile.mkdtemp(prefix="t26091505-")
    audit_dir = os.path.join(tmp, "audit")
    os.makedirs(audit_dir, exist_ok=True)
    audit_env, audit_log = bench.audit_hook_env(audit_dir)
    stage_mod = None
    worker = None
    try:
        stage_mod, stage = require_stage(fail, "%s-%d" % (PROJ, os.getpid()),
                                         PROJ)
        repo = make_fixture_repo(tmp)
        # 分支名归一 main：_merge_base_ref 硬编码 `merge-base main <branch>`，
        # 环境 git 默认分支名不确定——不归一＝merge_base_failed 环境性假红。
        # 已在 main 的环境（init.defaultBranch=main）零操作（checkout -b 会 fatal）。
        _cur = subprocess.run(["git", "-C", repo, "rev-parse", "--abbrev-ref", "HEAD"],
                              capture_output=True, text=True).stdout.strip()
        if _cur != "main":
            try:
                subprocess.run(["git", "-C", repo, "branch", "-m", "main"],
                               check=True, capture_output=True, text=True)
            except subprocess.CalledProcessError as e:
                fail.bail("夹具仓分支归一 main 失败（现分支=%s stderr尾=%s）——"
                          "merge 子用例的环境前提立不住" % (_cur, (e.stderr or "")[-140:]))
        # 最小 verify.yaml（t260907-06 lib 先例）：lanes.code 在场=道开放——缺失态
        # 关闭会让写集白名单检查整个跳过，越写集探针畅通无阻，merge 失败分支不成立
        # （260915 implement 段自测首跑实证：probe 提交后 merge_check 全绿直进人门）。
        # write_allow=docs/（桩 settle 的 docs/ticket-notes.md 合法）；checks 带 sanity 恒绿命令（空列表=verify fail-closed「须非空」；
        # 命令制检查，快的）。须在 ticket-start 前落 main——泳道从 base 分叉时带上。
        with open(os.path.join(repo, "verify.yaml"), "w", encoding="utf-8") as f:
            f.write("schema: v1\nlanes:\n  code:\n    write_allow:\n      - docs/\n"
                    "    checks:\n      - id: sanity\n        cmd: \"true\"\n")
        subprocess.run(["git", "-C", repo, "add", "-A"], check=True,
                       capture_output=True, text=True)
        subprocess.run(["git", "-C", repo, "commit", "-qm",
                        "verify.yaml：code 道开放（写集粗判据=docs/）"],
                       check=True, capture_output=True, text=True)
        reg_dir = bench.write_registry(os.path.join(tmp, "registry"), PROJ, repo)
        env = stage_env(stage, reg_dir, audit_env)
        # 260927（integration 岗）：**整条旅程的调用方身份**（=夹具项目自身）在 env 里
        # 一次声明，覆盖本场景所有写 op（ticket-start / sign / …）。原因：t260925-08 把
        # undeclared 策略由 record 翻成 refuse 之后，凡经裸入口的写 op 都会被跨项目闸
        # fail-closed 拒收（kind=cross_project_refused，回执 rc=0 却 ok=false）——只补
        # ticket-start 会造成「前面绿、③sign 又红」的逐点打地鼠。env 声明对
        # 「引擎跑」（env 里带的是运行票自己的项目）与手工单跑都稳：显式参数优先于 env，
        # 逐调用点若另给了 caller_project 仍以它为准。
        env["SANDBAR_CALLER_PROJECT"] = PROJ
        stub_path = os.path.join(tmp, "lane_red_stub.py")
        with open(stub_path, "w", encoding="utf-8") as f:
            f.write(LANE_RED_STUB)
        stub_log = os.path.join(tmp, "stub.jsonl")
        worker = spawn_worker(py, TID, env, os.path.join(tmp, "worker.log"),
                              stub_path, stub_log)
        wlog = os.path.join(tmp, "worker.log")
        fail.check(worker.poll() is None, "旅程 worker 已拉起 pid=%s" % worker.pid)

        rc, out = run_poc_client(py, "ticket-start", {
            "ticket_id": TID, "template_id": "dev-lane", "project": PROJ,
            "title": "t260915-05 详情观测面三红旅程", "write_set": list(WRITE_SET),
            "base_ref": "main",
            # 260927：**必须显式声明调用方项目**（=夹具项目自身）。t260925-08 把
            # undeclared 策略由 record 翻成 refuse 之后，裸入口建票会被跨项目闸
            # fail-closed 拒收（kind=cross_project_refused）；显式参数优先于 env，
            # 所以「引擎跑」（env 里带的是运行票自己的项目）与手工单跑都稳。原缺陷
            # 被「断言漏判」藏住：拒收回执 rc=0 且回显票号，旧断言 rc==0 and TID in out
            # 于是假绿 → 票根本没建出来，worker 只能干等 240s 报 workflow not found。
            # 断言同时收紧为「受理必须 ok=True」。
            "caller_project": PROJ}, env)
        _receipt = parse_out_json(out)
        fail.check(rc == 0 and TID in out and _receipt.get("ok") is True,
                   "ticket-start 受理（ok 必须为真；rc=%s ok=%r out尾=%s）"
                   % (rc, _receipt.get("ok"), out[-160:]))

        snap0 = wait_stage_running(py, env, TID, worker, wlog, fail,
                                   "create_plan", 240)
        fail.check(bool(snap0), "create_plan running（桩脑链启动）")
        # 越写集探针路径：场景直构（docs/ 写集之外、且不触 create_plan 段的
        # 「仅结果/回执文件」路径闸——真判定在 merge_check 的 verify_lane_code，
        # 本场景不借 judge_violation_probe（那是 t260915-01 拒绝子用例的机制：把越界
        # 路径写进结果文件会在 settle 期把票挡死在 create_plan，merge 失败分支不成立）。
        rel = "server/zz_t26091505_probe.py"
        fail.check(True, "探针路径构造（%s，越 %r 写集；判定器=merge_check 全量在场）"
                   % (rel, WRITE_SET))

        # ---- 并行分叉窗：把越写集探针提交进泳道分支（verify_lane 白名单 diff 的红源；
        #      fork 窗由桩拉宽，提交窗口稳定；settle 代落盘 commit 在其后，probe=基内历史）
        snap_f = wait_fork_window(py, env, TID, worker, wlog, fail, 300)
        if snap_f is None:
            fail.bail("未到并行分叉窗（stub 已拉宽窗口，仍错过=红）")
        ws = snap_f.get("workspace")
        lane = ws.get("path") if isinstance(ws, dict) else ws
        fail.check(bool(lane) and os.path.isdir(str(lane)),
                   "泳道工作区路径可得（%r）" % lane)

        def g(*a):
            """泳道内 git 助手：失败=点名 bail（命令+stderr尾），绝不裸 traceback。"""
            p = subprocess.run(["git", "-C", str(lane)] + list(a),
                               capture_output=True, text=True)
            if p.returncode != 0:
                fail.bail("泳道内 git %s 失败 rc=%s：%s"
                          % (a[0], p.returncode, ((p.stderr or p.stdout) or "").strip()[-200:]))
            return p

        probe_abs = os.path.join(str(lane), rel)
        os.makedirs(os.path.dirname(probe_abs), exist_ok=True)
        with open(probe_abs, "w", encoding="utf-8") as f:
            f.write("# t260915-05 越写集探针（集成场景写入，revert 清场）\n")
        # 点名单文件 add（不用 -A）：泳道工作区可能被运行时物化 .dsh/ 等运行时残留
        # （260915 三跑实证：add -A 把它们扫进分支→verify「敏感路径入库」22 条红
        # 盖掉探针红、落账也被污染）——探针提交只含探针，分支历史保持最小。
        g("add", "--", rel)
        g("commit", "-qm", "t260915-05 probe: out-of-write-set")
        probe_sha = subprocess.run(["git", "-C", str(lane), "rev-parse", "HEAD"],
                                   capture_output=True, text=True).stdout.strip()
        fail.check(bool(probe_sha), "越写集探针已提交进泳道分支（%s）" % probe_sha[:7])

        # ---- ① merge_check 第 1 轮：verify_red → blocked（非冲突红不自动返工）
        # 261022 (integration gate): wait_blocked alone polls blind for the whole
        # 420s — when the gate decides GREEN the ticket walks on to the merge human
        # gate and the wait can only expire, so the failure names no check. Stop
        # the wait the moment the ticket is seen PAST merge_check (merge gate /
        # terminal) or the last gate round is green, and bail naming that round's
        # items: the red card this sub-case exists to read never existed, and which
        # gate item let the probe through must be readable in the failure line.
        # The assertion itself is unchanged — it still demands blocked+verify_red.
        def _blocked_or_past():
            if worker.poll() is not None:
                wait_worker_alive(fail, worker, wlog)
            s = query_snapshot(py, env, TID) or {}
            if s.get("stage_state") == "blocked":
                return ("blocked", s)
            _gr = s.get("gate_runs") or []
            _last = _gr[-1] if _gr else {}
            if str(s.get("stage") or "") in ("merge", "closed") \
                    or (str(_last.get("stage") or "") == "merge_check" and _last.get("green")):
                return ("past", s)
            return None

        _hit = poll(_blocked_or_past, 420)
        if _hit is None:
            _s = query_snapshot(py, env, TID) or {}
            fail.bail("①merge_check 420s 内既未 blocked 也未走完闸（stage=%s state=%s）"
                      % (_s.get("stage"), _s.get("stage_state")))
        _how, snap_b = _hit
        if _how != "blocked":
            _gr = snap_b.get("gate_runs") or []
            _last = _gr[-1] if _gr else {}
            _items = "；".join(
                "%s=%s（%s）" % (str(c.get("id") or c.get("item")),
                                "green" if c.get("green") else "red",
                                str(c.get("detail"))[:200])
                for c in (_last.get("checks") or []))
            fail.bail("①越写集探针 %s 未被判红：merge_check 本轮 green=%r（ticket stage=%s "
                      "state=%s）——闸轮逐项：[%s]"
                      % (rel, _last.get("green"), snap_b.get("stage"),
                         snap_b.get("stage_state"), _items or "无轮次明细"))
        bd = snap_b.get("blocked_detail") or {}
        fail.check(bd.get("check_id") == "verify_lane_code",
                   "①blocked_detail.check_id=verify_lane_code（首红项既有结论结构化，%r）"
                   % bd.get("check_id"))
        fail.check(bd.get("reason_code") == "verify_red" and bd.get("red") is True,
                   "①reason_code=verify_red 且 red（%r/%r）"
                   % (bd.get("reason_code"), bd.get("red")))
        fail.check(bool(bd.get("next_action")),
                   "①next_action 人话下一步在场（%r)" % str(bd.get("next_action"))[:80])
        fail.check(isinstance(bd.get("files"), list),
                   "①files 为结构化列表（verify_red 族文件归因在 evidence 文本=契约现状，"
                   "UI 不翻译它没拿到的信息）：%r" % bd.get("files"))
        fail.check(rel in str(bd.get("evidence") or ""),
                   "①evidence 点名越界文件（G2：按文件名可追查）：%r"
                   % str(bd.get("evidence"))[:140])
        gr = snap_b.get("gate_runs") or []
        fail.check(bool(gr) and gr[-1].get("stage") == "merge_check"
                   and gr[-1].get("green") is False and gr[-1].get("red_count", 0) >= 1,
                   "①gate_runs 尾轮=merge_check 红（red_count≥1，轮次带数据源；%d 轮）"
                   % len(gr))
        rc2, face, raw = ticket_show_face(py, env, TID,
                                          admin_log=os.path.join(tmp, "admin.log"))
        fail.check(rc2 == 0 and isinstance(face, dict)
                   and (face.get("blocked_detail") or {}).get("reason_code") == "verify_red",
                   "①正规入口投影面同可达（ticket.py show 的 blocked_detail；rc=%s raw尾=%s）"
                   % (rc2, (raw or "")[-160:]))

        # ---- ② 人清探针（revert，不改写历史）→ retry_qc → 第 2 轮绿 → merge 人门
        g("revert", "--no-edit", probe_sha)
        rc3, _o = send_signal(py, stage, TID, "retry_qc",
                              "t260915-05 集成场景：探针已清")
        fail.check(rc3 == 0, "retry_qc 发信受理（rc=%s）" % rc3)

        def _human():
            if worker.poll() is not None:
                wait_worker_alive(fail, worker, wlog)
            s = query_snapshot(py, env, TID)
            if (s or {}).get("stage_state") == "awaiting-human":
                return s
            return None

        snap_h = poll(_human, 420)
        if snap_h is None:
            s = query_snapshot(py, env, TID)
            fail.bail("未到 merge 人门（现 stage=%s state=%s blocked=%r）"
                      % (s.get("stage"), s.get("stage_state"),
                         str(s.get("blocked_reason"))[:140]))
        hc = (snap_h.get("human_context") or {}).get("merge") or {}
        fail.check(bool(hc.get("context_text")),
                   "②人门上下文 context_text 在场（蓝卡「签什么」数据源）：%r"
                   % str(hc.get("context_text"))[:80])
        fail.check(bool(snap_h.get("stage_acceptance")),
                   "②stage_acceptance 在场（「签前看什么」数据源）")
        gr2 = snap_h.get("gate_runs") or []
        fail.check(len(gr2) >= 2 and gr2[0].get("green") is False
                   and gr2[-1].get("green") is True,
                   "②gate_runs 红→绿两轮留痕（轮次带逐轮格真实数据，%d 轮）" % len(gr2))
        fail.check(snap_h.get("blocked_detail") is None,
                   "②非 blocked 推进 blocked_detail 已清（R2 生命周期）：%r"
                   % (snap_h.get("blocked_detail"),))

        # ---- ③ 正规入口 sign approve → 落账 COMPLETED → 关单全量可见
        rc4, out4 = run_poc_client(py, "ticket", {
            "op": "sign", "ticket_id": TID,
            "input": {"who": "t26091505-integration", "gate": "merge",
                      "decision": "approve", "note": "集成场景签字"}}, env)
        fail.check(rc4 == 0 and '"delivered"' in out4,
                   "③sign 正规入口受理（rc=%s out尾=%s）" % (rc4, out4[-140:]))

        def _closed():
            # 关单读取走独立命令 ticket-query（describe+result()，无 worker 依赖）；
            # op=query 走工作流 query 句柄——票 closed 后无 worker 重放查询，恒挂
            # （260915 七跑实证：merge/closed 后轮询空转 420s）。
            rcq, outq = run_poc_client(py, "ticket-query",
                                       {"ticket_id": TID}, env)
            o = parse_out_json(outq)
            r = o.get("result") or {}
            # 契约字段=回执顶层 exec_status（client.py cmd_ticket_query 封装）
            if r.get("exec_status") == "COMPLETED":
                return o
            return None

        closed = poll(_closed, 420)
        if closed is None:
            fail.check(False, "③sign 后 420s 未 COMPLETED（merge 落账/拆道未收口）")
        else:
            rc5, face5, raw5 = ticket_show_face(py, env, TID,
                                                admin_log=os.path.join(tmp, "admin.log"))
            fail.check(rc5 == 0 and isinstance(face5, dict),
                       "③关单后 ticket.py show 经 result() 终态快照可读（rc=%s raw尾=%s）"
                       % (rc5, (raw5 or "")[-160:]))
            topo = face5.get("topology") if isinstance(face5, dict) else None
            fail.check(isinstance(topo, dict) and (topo.get("nodes") or []),
                       "③关单后投影面 topology 可达（KI-027 拓扑半＋跨组件缝白名单透传；"
                       "实得=%r）" % (type(topo).__name__,))
            if isinstance(topo, dict):
                kid = {n.get("id"): n.get("kind") for n in topo.get("nodes") or []}
                fail.check(kid.get("merge") == "human",
                           "③关单面拓扑 merge=human（泳道图人门虚线圈数据源不灭）")
            fail.check(bool(face5.get("gens")) and bool(face5.get("timeline")),
                       "③关单后 gens/timeline 终态可读（轮次带关单可见数据半）")
            gr5 = face5.get("gate_runs") or []
            fail.check(len(gr5) >= 2, "③关单后 gate_runs 全史可读（%d 轮）" % len(gr5))
            sig_txt = json.dumps(face5.get("signatures") or [], ensure_ascii=False)
            fail.check("merge" in sig_txt and "approve" in sig_txt,
                       "③签字记录在终态票面")

        audit = read_audit_jsonl(audit_log)
        fail.check(not audit, "审计账本为空（未触碰生产 7233/8233/3099）：%d 条"
                   % len(audit))
    finally:
        if worker is not None and worker.poll() is None:
            worker.terminate()
            try:
                worker.wait(timeout=15)
            except subprocess.TimeoutExpired:
                worker.kill()
        if stage_mod is not None:
            stage_down(stage_mod, "%s-%d" % (PROJ, os.getpid()))
        if os.environ.get("T26091505_KEEP_TMP") == "1":
            print("TMP preserved（T26091505_KEEP_TMP=1）: %s" % tmp)
        else:
            shutil.rmtree(tmp, ignore_errors=True)


def main():
    # 环境卫生：PYTHONPYCACHEPREFIX 若指进泳道相对路径（如操作手 shell 里的
    # out/pycache），桩进程会在泳道内落字节码缓存——settle 路径闸会把这撮
    # 「段外写入」如实拦下（闸行为正确，票被环境噪声挡死在 create_plan）。
    # 场景侧清场：桩的 pycache 落 stub 所在 tmp 目录，零泳道写入。
    os.environ.pop("PYTHONPYCACHEPREFIX", None)
    fail = Fail("t260915-05 详情观测面三红旅程（merge 红票面＋人门蓝卡源＋关单全量可见）")
    py = os.path.join(REPO, "server", "engine", ".venv", "bin", "python")
    if not os.path.exists(py):
        py = "python3"
    stdlib_locks(fail, py)
    try:
        bench = require_bench(fail)
        journey(fail, bench)
    except SystemExit as e:
        code = e.code if isinstance(e.code, int) else 1
        if code in (2, 3):
            print("ENV_FAIL 隔离台/镜像/台库缺供（exit %s）——旅程子用例不跑，stdlib 契约锁已跑"
                  % code, flush=True)
        raise
    fail.finish()


if __name__ == "__main__":
    main()
