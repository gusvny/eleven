#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成 integration/batch_stage_exceptions.json（t260921-06 要求4 例外清单机器真源）。

纪律（review gen1 条件3）：
- entry 名/池**机械取自注册表**（import run_scenarios.SCENARIOS 唯一匹配断言），
  绝不手抄草案——手抄漂移=看守⑤匹配失效；
- 落盘前机械自检：
  ① 全部行 entry 在册且唯一匹配、pool=注册表池（与 sc_batch_manifest_contract 同判据）；
  ② 清点判据不变式预检：文件级消费候选（cmd 引用文件命中
     require_stage|do_up_public|stageUp(|stage_docker.py up|ensure|up_stage，含 *.sh——
     gen1 review 条件1）∧ pool ∉ {engine, exclusive} ⇒ 必须在清单在册（否则看守红，
     本脚本先红，清单先补）；
  ③ project_pattern 逐一过合法前缀形 ^[a-z][a-z0-9*-]*$。

契约注（manifest 是裸对象数组，schema 见看守场景；本注落 README 与此处注释）：
- project_pattern 语义=**本泳道 compose 工程名前缀**（该例外条目在批内自管私台时
  可能新建的工程名集合；窗口形态看守按前缀匹配，含重试改名面如 t260910-04 的 -r1）。
- 零台行（zero-boot）不新建任何工程，pattern 为占位形（不匹配任何真工程）。

跑法：PYTHONPYCACHEPREFIX=out/pycache python3 integration/t260921-06/gen_batch_stage_exceptions.py
"""
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
INTEG = REPO / "integration"
MANIFEST = INTEG / "batch_stage_exceptions.json"
CONSUMER_PAT = re.compile(r"require_stage|do_up_public|stageUp\(|stage_docker\.py (up|ensure)|up_stage")
PATTERN_OK = re.compile(r"^[a-z][a-z0-9*-]*$")

# ---- 例外行（reason/evidence 人工撰写=要求4「逐条目声明+写明理由」；entry/pool 机械核对） ----
ROWS = [
    # Canonicalized in t261026-24: ROWS is the machine truth mirrored 1:1 from
    # integration/batch_stage_exceptions.json (writer/reader lockstep; the
    # t261026-24-manifest-matches-generator guard fails on any drift). Section
    # comments retired with the canonicalization — reasons carry the intent.
    {"entry": "t260904-19-stage-docker-cli-contract", "pool": "engine",
     "project_pattern": "t26090419-*",
     "reason": "被测对象=stage_docker up/ensure/down CLI 契约本体（退出码/JSON 形/幂等面），须对全新工程名逐字驱动起拆台全链；批台复用会换掉被测对象本身。",
     "evidence": "integration/t260904-19/sc_stage_docker_cli_contract.py 直呼 stage_docker CLI 『t26090419-contract-*』工程名（grep 实证）"},
    {"entry": "t260904-19-stage-docker-parallel-zero-residue", "pool": "engine",
     "project_pattern": "t26090419-*",
     "reason": "被测对象=并发起台互不串扰与零残留机械（多台同时起、容器/卷/网归零）——批台恰是「不拆的共享台」，会直接破坏被测断言。",
     "evidence": "integration/t260904-19/sc_stage_docker_parallel_zero_residue.py 多工程并发起台『t26090419-par-probe*』（grep 实证）"},
    {"entry": "t260910-12-cwd-independence", "pool": "engine",
     "project_pattern": "t26091012-*",
     "reason": "被测对象=工程名/锁根与 cwd 无关性——须在不同 cwd 起同名台；批台名由 runner 定，与被测语义无关。",
     "evidence": "integration/t260910-12 用例『t26091012-cwd』跨 cwd 起台断言"},
    {"entry": "t260910-12-full-capacity-queue", "pool": "engine",
     "project_pattern": "t26091012-*",
     "reason": "被测对象=端口/容量满员时的排队与滑档（占位语义）——须占满档位观察；批台占用面与被测占位面互染。",
     "evidence": "integration/t260910-12 用例『t26091012-cap』占满档位断言排队"},
    {"entry": "t260910-12-herd-no-crosstalk", "pool": "engine",
     "project_pattern": "t26091012-*",
     "reason": "被测对象=ensure 雷群互斥（同工程名并发 ensure 只起一台）——需多工程名同时在场；批台注入会掩盖雷群形态（被测对象消失）。",
     "evidence": "integration/t260910-12/lib_herd_case.py ensure_leg 多工程驱动『t26091012-*』"},
    {"entry": "t260910-12-holder-kill-reclaim", "pool": "engine",
     "project_pattern": "t26091012-*",
     "reason": "被测对象=holder 进程被 kill 后租约判死回收（起台持有者语义）——须自建台并杀 holder 观察回收；批台 hold 归 runner，形态不可注入。",
     "evidence": "integration/t260910-12/sc_*holder* 用例『t26091012-*』杀 holder 断言回收"},
    {"entry": "t260910-12-idempotent-reup", "pool": "engine",
     "project_pattern": "t26091012-*",
     "reason": "被测对象=同工程名 ensure 幂等重入（reused 语义）——台身份前后一致是断言本体；批台复用语义不同面。",
     "evidence": "integration/t260910-12 用例『t26091012-reup』container_ids 前后一致断言"},
    {"entry": "t260910-12-lease-unit", "pool": "ro",
     "project_pattern": "none-zero-boot-*",
     "reason": "零台行：租约状态机单元电池（内存态断言），零 docker 零起台。",
     "evidence": "integration/t260910-12 租约单元场景 cmd 直呼测试脚本，无起台调用"},
    {"entry": "t260912-02-burst-managed-subnets", "pool": "exclusive",
     "project_pattern": "t26091202-*",
     "reason": "被测对象=网段突发占用（多台同时抢网段）——须真实多台并发建网；批台=恰一网，形态互斥。",
     "evidence": "integration/t260912-02/sc_stage_burst_managed_subnets.py『t26091202-burst』"},
    {"entry": "t260912-02-fuse-headroom-resident", "pool": "exclusive",
     "project_pattern": "t26091202-*",
     "reason": "被测对象=保险丝对常驻台余量判定（本票 churn 实证样本）——被测=保险丝机械，须常驻台在场；批台恰是保险丝要保护的形态不可混用。",
     "evidence": "integration/t260912-02/sc_stage_fuse_headroom_resident.py『t26091202-headroom』（dockerd 实证 9 连台样本出处）"},
    {"entry": "t260912-02-fuse-runaway-named-stop", "pool": "exclusive",
     "project_pattern": "t26091202-*",
     "reason": "被测对象=保险丝失控刹停与点名停（churn 实证样本）——被测=保险丝机械，须自造失控台；批台不可成为被刹停对象。",
     "evidence": "integration/t260912-02/sc_stage_fuse_runaway_named_stop.py『t26091202-runaway』"},
    {"entry": "t260912-02-net-table-contract", "pool": "engine",
     "project_pattern": "t26091202-*",
     "reason": "被测对象=网络档位表契约（网段分配/禁区面）——须自建台核网络面；批台网络由 runner 档位定，与断言无关面。",
     "evidence": "integration/t260912-02/sc_stage_net_table_contract.py『t26091202-nettable』"},
    {"entry": "t260912-02-sweep-cost-failure", "pool": "exclusive",
     "project_pattern": "t26091202-*",
     "reason": "被测对象=清扫失败成本面（docker 故障注入下清扫不静默）——故障注入面需自管台；批台不在被测路径。",
     "evidence": "integration/t260912-02/sc_stage_sweep_cost_failure.py『t26091202-sweepcost』"},
    {"entry": "t260912-02-sweep-owner-gone", "pool": "engine",
     "project_pattern": "t26091202-*",
     "reason": "被测对象=清扫判死（owner 亡→回收孤儿台）——须制造 owner 亡的孤台；批台 owner=runner 恒活，形态不可注入。",
     "evidence": "integration/t260912-02/sc_stage_sweep_owner_gone.py『t26091202-gone-』族"},
    {"entry": "t260913-05-teardown-residue-visible", "pool": "engine",
     "project_pattern": "t26091305-*",
     "reason": "被测对象=拆台残留可见性（down 失败/半途残留的观测面）——须真拆台并验残留计数；批台绝不拆（拆了=毁同批），语义互斥。",
     "evidence": "integration/t260913-05/sc_t260913_05_teardown_residue_visible.py:63 STAGE_PROJ='t26091305-rv'+RUN_SUFFIX 直调拆台面"},
    {"entry": "t260913-05-teardown-scope-contract", "pool": "ro",
     "project_pattern": "none-zero-boot-*",
     "reason": "零台行：拆台作用域契约测试（判定面），零起台。",
     "evidence": "integration/t260913-05/sc_*teardown_scope* 契约场景，无起台调用"},
    {"entry": "t260915-01-detail-face-journey", "pool": "engine",
     "project_pattern": "none-zero-boot-*",
     "reason": "零台行：t260915-01 旅程已迁到进程台（integration/process_bench.py 纯进程 Temporal），不再消费 docker 台也不再自建台——列册即宣告非批消费者（host order 261022：这两条不起 docker 台，点名轮也不预起共享批台）。",
     "evidence": "integration/t260915-01/tests/sc_detail_face_journey.py 只 import lib_bench_stage（process_bench），零 require_stage/stage_docker 调用"},
    {"entry": "t260917-09-tests-false-escalation-guard", "pool": "engine",
     "project_pattern": "none-zero-boot-*",
     "reason": "零台行：t260917-09 三相共用进程台（integration/process_bench.py 纯进程 Temporal），不再消费 docker 台也不再自建台——列册即宣告非批消费者（host order 261022）。",
     "evidence": "integration/t260917-09/tests/sc_tests_false_escalation_guard.py 只 import lib_bench_stage（process_bench），零 require_stage/stage_docker 调用"},
    {"entry": "t260921-06-batch-manifest-contract", "pool": "ro",
     "project_pattern": "none-zero-boot-*",
     "reason": "zero-boot sentinel：本清单的静态契约看守（离线 ro 哨兵）——源码内嵌清点判据正则字面量导致一级判据自匹配，声明豁免（其本身零起台零消费）。",
     "evidence": "integration/t260921-06/sc_batch_manifest_contract.py 自身含 CONSUMER_PAT 字面量（自匹配），cmd 直呼本场景脚本零起台"},
    {"entry": "t260924-04-project-template-journey", "pool": "main",
     "project_pattern": "t26092404-*",
     "reason": "被测对象=项目外置模板的建票全链＋续跑＋拒收面（真 Temporal＋真 worker＋桩大脑的 L3 旅程）：场景自持工程名 t260924-04-<pid> 调 require_stage（lib_gate 单点）——批模式下该调用走批台 ns-acquire 申请本场景命名空间（t260921-06 批级共享，零容器开销），批台不在位=exit 2 环境红（绝不静默回落）。故它是**批台消费者候选**，但注册池=main（第 4 元 serial=无池标注的串行条目，pool_of 归 main）：按清点判据「候选 ⊆ engine/exclusive ∪ 例外清单」在此显式登记豁免（不擅自改他人条目的池=不改变闸的跑法范围），工程名前缀沿用清单既有约定。",
     "evidence": "integration/t260924-04/sc_project_template_ticket_journey.py:203 stage_mod, stage = require_stage(fail, \"t260924-04-%d\" % os.getpid(), \"t260924-04\")；require_stage=integration/t260904-02/lib_gate.py:137（SANDBAR_STAGE_BATCH 在场 ⇒ 不起台、向批台申请 ns）"},
    {"entry": "t260905-02-worker-lifecycle", "pool": "engine",
     "project_pattern": "t26090502-*",
     "reason": "被测对象=worker 起/退生命周期，且断言**拆台后零残留容器与 temporal 端口已释放**（三处读 down 回执 residue + 端口面）。批台恰是「不拆的共享台」：批模式下既无自有台可拆、批台端口也不会释放 ⇒ 断言与被测形态互斥，须自持台。",
     "evidence": "261001 实测：--only t260904-02-worker-fingerprint-gate,t260905-02-worker-lifecycle → 本条目走批模式后 FAIL「舞台 down 后零残留容器（实得 None）／temporal 端口已释放（仍被占用）」；单独跑（旧缝面会 do_down 批台）才「过」。"},
    {"entry": "t260905-02-ticket-worker-watch-exit", "pool": "engine",
     "project_pattern": "t26090502-*",
     "reason": "同族：断言语义落在「自有台已拆」上（residue + 端口释放），批模式无此事实可测。",
     "evidence": "同 t260905-02-worker-lifecycle（同目录同断言族，grep residue/端口 命中 3 处）；261001 加入本清单，切片实测 8 条 0 环境红。"},
    {"entry": "t260905-02-console-duplicate-guard", "pool": "engine",
     "project_pattern": "t26090502-*",
     "reason": "同族：断言语义落在「自有台已拆」上（residue + 端口释放），批模式无此事实可测。",
     "evidence": "同 t260905-02-worker-lifecycle（同目录同断言族）；261001 加入本清单，切片实测本条目 PASS。"},
    {"entry": "t261005-13-receipt-port-contract", "pool": "ro",
     "project_pattern": "sc-t26100513-*",
     "reason": "被测对象=receipt-port 契约本体：场景自驱 stage_docker CLI、自有临时工程名（sc_t26100513_receipt_port_contract.py 头注与 :91 直呼实证）——批台复用会换掉被测对象本身，与清单既有三条 engine 池 stage-docker 契约条目同族。注册池=ro，按清点判据「候选 ⊆ engine/exclusive ∪ 例外清单」在此显式登记豁免。",
     "evidence": "integration/t261005-13/sc_t26100513_receipt_port_contract.py:8,91 自驱 stage_docker.py CLI；261005 登记（t261005-10 arbitrate gen8 首入，gen9 复核；本条为 implement gen7 确定性重加——worker squash 曾两次丢弃该条目，KI 候选 F7）"},
    {"entry": "t261006-03-engine-path-mount-contract", "pool": "ro",
     "project_pattern": "sc-t26100603-*",
     "reason": "被测对象=engine-path mount 契约本体（t261006-03）：场景自驱 stage_docker CLI / 自有临时工程名，批台复用会换掉被测对象——与清单既有 stage-docker 契约条目同族。注册池=ro，按清点判据在此显式登记豁免。",
     "evidence": "integration/t261006-03/sc_engine_path_mount_contract.py 直呼 stage_docker CLI（grep 实证）；t261005-10 arbitrate gen17 首入；F7 丢失史：23ca6a0 merge 解析取 main 侧版本第三次丢弃，implement gen20 确定性重加。"},
    {"entry": "t261006-03-engine-path-capture-journey", "pool": "browser",
     "project_pattern": "sc-t26100603-*",
     "reason": "被测对象=engine 自有采集链全旅程（run_capture_stage services=flat -> capture-lane --stage-json，t261006-03）：自带工程名起拆台，批台不在位/复用都会换掉被测链。注册池=browser，同族豁免。",
     "evidence": "integration/t261006-03/sc_engine_path_capture_journey.py 自驱采集链（场景头注与 run 体）；F7 丢失史同上，gen20 重加。"},
    {"entry": "t261008-46-supply-working-peer-ceiling", "pool": "ro",
     "project_pattern": "t26100846-*",
     "reason": "被测对象=供给争用等待的两层上界契约本体（t261008-46）：场景自驱 stage_docker CLI、自有临时工程名 t26100846-ceiling（:86-88 直呼实证）+tmp 隔离锁根——批台复用会换掉被测的锁根/工程名，与清单既有 ro 池 stage-docker 契约条目同族。注册池=ro，按清点判据「候选 ⊆ engine/exclusive ∪ 例外清单」在此显式登记豁免。",
     "evidence": "integration/t261008-46/sc_supply_working_peer_ceiling.py:7,86-88 自驱 stage_docker.py ensure、PROJECT='t26100846-ceiling'（grep 实证）；t261009-10 arbitrate gen0-gen4 连续五轮确认 settle 确定性丢弃本条目，implement gen2 确定性重加（KI 候选：settle 枚举丢 integration/ 写集面文件）。"},
    {"entry": "t260915-20-project-identity-realchain", "pool": "exclusive",
     "project_pattern": "insa-*",
     "reason": "261024 宿主令「换到 process bench」：本用例的在线面对 Temporal 前端的要求由 integration/process_bench.py 的纯进程台自供给（lib_proc_bench.ensure），不需要 docker 台，也就不需要批台预起。",
     "evidence": "integration/t260915-20/sc_inspection_project_identity.py main() 首步 lib_proc_bench.ensure(modules=(lib,))；无 docker 台时实测 PASS 22/0（process bench on 127.0.0.1:17233, namespace default）"},
    {"entry": "t260916-02-relocation-realchain", "pool": "exclusive",
     "project_pattern": "rlxa-*",
     "reason": "同上：真链旅程只要求 Temporal 前端，process bench 自供给，不起批台。",
     "evidence": "integration/t260916-02/sc_inspection_decl_relocation.py main() 首步 lib_proc_bench.ensure(modules=(lr, lib_inspection))；无 docker 台时实测 PASS 29/0"},
    {"entry": "t260916-22-verdict-cli", "pool": "exclusive",
     "project_pattern": "verdict-cli-*",
     "reason": "同上：裁定旅程只要求 Temporal 前端，process bench 自供给，不起批台。",
     "evidence": "integration/t260916-22/sc_inspection_verdict_cli.py main() 首步 lib_proc_bench.ensure(modules=(lib, lib_inspection))；无 docker 台时实测跑满全部子用例（余一红属 KI-337 产品面，非环境）"},
]



def main():
    sys.path.insert(0, str(INTEG))
    import run_scenarios as rs
    reg = {}
    for e in rs.SCENARIOS:
        reg.setdefault(e[0], []).append(e)
    fails = []

    def check(name, cond, detail=""):
        print("%s %s%s" % ("ok   " if cond else "FAIL ", name,
                           ("" if cond else " —— %s" % str(detail)[:300])), flush=True)
        if not cond:
            fails.append(name)

    # ---- ① 行级机械核对：entry 唯一在册 + pool=注册表池 + pattern 合法 ----
    for row in ROWS:
        hits = reg.get(row["entry"], [])
        if not check("entry 在册唯一：%s" % row["entry"], len(hits) == 1,
                     "命中 %d" % len(hits)):
            continue
        real_pool = rs.pool_of(hits[0])
        check("pool=注册表池：%s（%s）" % (row["entry"], real_pool),
              row["pool"] == real_pool, "行=%s" % row["pool"])
        check("pattern 合法前缀形：%s" % row["project_pattern"],
              bool(PATTERN_OK.match(row["project_pattern"])), row["project_pattern"])
        check("reason/evidence 非空：%s" % row["entry"],
              bool(row.get("reason", "").strip()) and bool(row.get("evidence", "").strip()))

    # ---- ② 清点判据不变式预检（与看守同判据，先红于看守） ----
    cand_files = set()
    for base in (INTEG, REPO / "server" / "engine"):
        for p in base.rglob("*"):
            if p.suffix in (".py", ".mjs", ".sh") and p.is_file():
                try:
                    if CONSUMER_PAT.search(p.read_text(encoding="utf-8", errors="replace")):
                        cand_files.add(str(p.relative_to(REPO)))
                except OSError:
                    continue

    def cmd_files(entry):
        out = []
        for tok in str(entry[2]).split():
            tok = tok.strip("'\"")
            if tok.startswith("integration/") and (REPO / tok).exists():
                out.append(tok)
        return out

    def is_candidate(entry):
        for f in cmd_files(entry):
            if f in cand_files:
                return True
            try:
                if f.endswith(".py") and CONSUMER_PAT.search(
                        (REPO / f).read_text(encoding="utf-8", errors="replace")):
                    return True
            except OSError:
                continue
        return False

    names = {r["entry"] for r in ROWS}
    outside = [e[0] for e in rs.SCENARIOS
               if is_candidate(e) and rs.pool_of(e) not in ("engine", "exclusive")
               and e[0] not in names]
    check("清点不变式：非两池候选 ⊆ 清单（否则看守⑤红，先补清单）", not outside, outside[:5])

    # ---- ③ 幂等落盘（内容不变不写，保 mtime） ----
    rows = sorted(ROWS, key=lambda r: r["entry"])
    text = json.dumps(rows, ensure_ascii=False, indent=2) + "\n"
    old = MANIFEST.read_text(encoding="utf-8") if MANIFEST.exists() else None
    if old != text:
        MANIFEST.write_text(text, encoding="utf-8")
        print("清单已写入：%s（%d 行）" % (MANIFEST, len(rows)), flush=True)
    else:
        print("清单内容无变化（幂等跳过写）：%s（%d 行）" % (MANIFEST, len(rows)), flush=True)
    print("MANIFEST_SUMMARY rows=%d fails=%d" % (len(rows), len(fails)), flush=True)
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
