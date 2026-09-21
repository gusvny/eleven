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
    # ~~ A. engine/exclusive 真台例外：被测对象=stage/多台/保险丝机械本身 ~~
    {"entry": "t260904-19-stage-docker-cli-contract", "pool": "engine",
     "project_pattern": "t26090419-*",
     "reason": "被测对象=stage_docker up/ensure/down CLI 契约本体（退出码/JSON 形/幂等面），"
               "须对全新工程名逐字驱动起拆台全链；批台复用会换掉被测对象本身。",
     "evidence": "integration/t260904-19/sc_stage_docker_cli_contract.py 直呼 stage_docker CLI "
                 "『t26090419-contract-*』工程名（grep 实证）"},
    {"entry": "t260904-19-stage-docker-parallel-zero-residue", "pool": "engine",
     "project_pattern": "t26090419-*",
     "reason": "被测对象=并发起台互不串扰与零残留机械（多台同时起、容器/卷/网归零）——"
               "批台恰是「不拆的共享台」，会直接破坏被测断言。",
     "evidence": "integration/t260904-19/sc_stage_docker_parallel_zero_residue.py 多工程并发起台"
                 "『t26090419-par-probe*』（grep 实证）"},
    {"entry": "t260910-12-herd-no-crosstalk", "pool": "engine",
     "project_pattern": "t26091012-*",
     "reason": "被测对象=ensure 雷群互斥（同工程名并发 ensure 只起一台）——需多工程名同时"
               "在场；批台注入会掩盖雷群形态（被测对象消失）。",
     "evidence": "integration/t260910-12/lib_herd_case.py ensure_leg 多工程驱动『t26091012-*』"},
    {"entry": "t260910-12-holder-kill-reclaim", "pool": "engine",
     "project_pattern": "t26091012-*",
     "reason": "被测对象=holder 进程被 kill 后租约判死回收（起台持有者语义）——须自建台并"
               "杀 holder 观察回收；批台 hold 归 runner，形态不可注入。",
     "evidence": "integration/t260910-12/sc_*holder* 用例『t26091012-*』杀 holder 断言回收"},
    {"entry": "t260910-12-full-capacity-queue", "pool": "engine",
     "project_pattern": "t26091012-*",
     "reason": "被测对象=端口/容量满员时的排队与滑档（占位语义）——须占满档位观察；批台"
               "占用面与被测占位面互染。",
     "evidence": "integration/t260910-12 用例『t26091012-cap』占满档位断言排队"},
    {"entry": "t260910-12-idempotent-reup", "pool": "engine",
     "project_pattern": "t26091012-*",
     "reason": "被测对象=同工程名 ensure 幂等重入（reused 语义）——台身份前后一致是断言"
               "本体；批台复用语义不同面。",
     "evidence": "integration/t260910-12 用例『t26091012-reup』container_ids 前后一致断言"},
    {"entry": "t260910-12-cwd-independence", "pool": "engine",
     "project_pattern": "t26091012-*",
     "reason": "被测对象=工程名/锁根与 cwd 无关性——须在不同 cwd 起同名台；批台名由 "
               "runner 定，与被测语义无关。",
     "evidence": "integration/t260910-12 用例『t26091012-cwd』跨 cwd 起台断言"},
    {"entry": "t260912-02-sweep-owner-gone", "pool": "engine",
     "project_pattern": "t26091202-*",
     "reason": "被测对象=清扫判死（owner 亡→回收孤儿台）——须制造 owner 亡的孤台；批台 "
               "owner=runner 恒活，形态不可注入。",
     "evidence": "integration/t260912-02/sc_stage_sweep_owner_gone.py『t26091202-gone-』族"},
    {"entry": "t260912-02-net-table-contract", "pool": "engine",
     "project_pattern": "t26091202-*",
     "reason": "被测对象=网络档位表契约（网段分配/禁区面）——须自建台核网络面；批台网络"
               "由 runner 档位定，与断言无关面。",
     "evidence": "integration/t260912-02/sc_stage_net_table_contract.py『t26091202-nettable』"},
    {"entry": "t260913-05-teardown-residue-visible", "pool": "engine",
     "project_pattern": "t26091305-*",
     "reason": "被测对象=拆台残留可见性（down 失败/半途残留的观测面）——须真拆台并验"
               "残留计数；批台绝不拆（拆了=毁同批），语义互斥。",
     "evidence": "integration/t260913-05/sc_t260913_05_teardown_residue_visible.py:63 "
                 "STAGE_PROJ='t26091305-rv'+RUN_SUFFIX 直调拆台面"},
    {"entry": "t260910-04-console-paused-list", "pool": "exclusive",
     "project_pattern": "t26091004-*",
     "reason": "被测对象=console 面真引擎 pause 列表（独占台+瞬态重试）；重试路径会把 "
               "工程名改『-r1』后缀自管私台（前缀通配覆盖）。",
     "evidence": "integration/t260910-04/sc_console_paused_list.mjs:195,208-211 STAGE_PROJECT="
                 "'t26091004-sc-'+pid，重试改 '-r1'"},
    {"entry": "t260912-02-burst-managed-subnets", "pool": "exclusive",
     "project_pattern": "t26091202-*",
     "reason": "被测对象=网段突发占用（多台同时抢网段）——须真实多台并发建网；批台=恰一"
               "网，形态互斥。",
     "evidence": "integration/t260912-02/sc_stage_burst_managed_subnets.py『t26091202-burst』"},
    {"entry": "t260912-02-sweep-cost-failure", "pool": "exclusive",
     "project_pattern": "t26091202-*",
     "reason": "被测对象=清扫失败成本面（docker 故障注入下清扫不静默）——故障注入面需"
               "自管台；批台不在被测路径。",
     "evidence": "integration/t260912-02/sc_stage_sweep_cost_failure.py『t26091202-sweepcost』"},
    {"entry": "t260912-02-fuse-headroom-resident", "pool": "exclusive",
     "project_pattern": "t26091202-*",
     "reason": "被测对象=保险丝对常驻台余量判定（本票 churn 实证样本）——被测=保险丝"
               "机械，须常驻台在场；批台恰是保险丝要保护的形态不可混用。",
     "evidence": "integration/t260912-02/sc_stage_fuse_headroom_resident.py『t26091202-headroom』"
                 "（dockerd 实证 9 连台样本出处）"},
    {"entry": "t260912-02-fuse-runaway-named-stop", "pool": "exclusive",
     "project_pattern": "t26091202-*",
     "reason": "被测对象=保险丝失控刹停与点名停（churn 实证样本）——被测=保险丝机械，"
               "须自造失控台；批台不可成为被刹停对象。",
     "evidence": "integration/t260912-02/sc_stage_fuse_runaway_named_stop.py『t26091202-runaway』"},
    # ~~ B. 零台契约哨兵（一级判据自匹配/契约测试零起台；声明防看守不变式误伤） ~~
    {"entry": "t260910-12-transient-retry-contract", "pool": "ro",
     "project_pattern": "none-zero-boot-*",
     "reason": "零台行：瞬态重试白名单契约测试（lib_transient_retry 纯判定面），零起台"
               "零消费——在册以防「源码含消费模式字面量」的一级判据误接。",
     "evidence": "integration/t260910-12 瞬态契约场景 cmd 直呼 lib_transient_retry.py，"
                 "无 stage_docker 起台调用"},
    {"entry": "t260910-12-lease-unit", "pool": "ro",
     "project_pattern": "none-zero-boot-*",
     "reason": "零台行：租约状态机单元电池（内存态断言），零 docker 零起台。",
     "evidence": "integration/t260910-12 租约单元场景 cmd 直呼测试脚本，无起台调用"},
    {"entry": "t260913-05-teardown-scope-contract", "pool": "ro",
     "project_pattern": "none-zero-boot-*",
     "reason": "零台行：拆台作用域契约测试（判定面），零起台。",
     "evidence": "integration/t260913-05/sc_*teardown_scope* 契约场景，无起台调用"},
    {"entry": "t260921-06-batch-manifest-contract", "pool": "ro",
     "project_pattern": "none-zero-boot-*",
     "reason": "零台行：本清单的静态契约看守（离线 ro 哨兵）——源码内嵌清点判据正则"
               "字面量导致一级判据自匹配，声明豁免（其本身零起台零消费）。",
     "evidence": "integration/t260921-06/sc_batch_manifest_contract.py 自身含 CONSUMER_PAT "
                 "字面量（自匹配），cmd 直呼本场景脚本零起台"},
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
