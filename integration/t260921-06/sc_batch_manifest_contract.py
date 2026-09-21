#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""t260921-06 场景③：例外清单机器契约与起台清点判据不变式（L2/L3 看守，要求4+防 C1 回潮）。

intent（工单要求4「例外通道显式」的执法面 + gen0 拒因 C1 的永久化回归网）：
- 例外清单（integration/batch_stage_exceptions.json）是批台机器真源：schema 完整
  （entry/pool/project_pattern/reason/evidence 五键，reason/evidence 非空）、条目名
  必须逐字在注册表在册（机械取自注册表，防手抄漂移——gen1 review 条件3）、记录池与
  注册表池一致、project_pattern 是合法工程名前缀形；
- 清点判据不变式（本票核心回归网）：按机械清点判据（源码面 grep
  require_stage/do_up_public/stageUp(/stage_docker up|ensure/up_stage，**含 *.sh**
  ——gen1 review 条件1）× 注册表条目 cmd 引用文件交叉，得「批消费者候选条目集」；
  断言**每个候选条目要么 pool ∈ {engine, exclusive}（分类器可接），要么在例外清单
  在册（显式豁免）**——两头都不占 = 分类器漏接 = 每票段假环境红/全轮漏注入（C1 事故
  形态的机械化身）。新增场景用了消费缝却注册进 ro/main 池 → 在此红；
- manifest 自身不得把非消费者条目豁免成「注入排除」假象：清单条目的 pool 记录与
  注册表一致 + 条目在册即可（理由质量归人审，机器只守结构面）。

与相邻场景 intent 分界：
- sc_batch_runner_form：守动态窗口形态（真 docker）；本条纯静态离线（ro，每票集测段
  必跑的廉价哨兵），守清单结构与判据不变式；
- lint_tests L4/L5：守注册结构完整（重名/悬空/orphan）；本条守「消费者↔池↔清单」
  三角一致性（L4/L5 无此语义）。

纯离线零 docker 零 ENV_FAIL 段（被看守文件缺损=产品红点名）。实现落地前红属预期
（TDD：清单未落=红），arbitrate/merge 期必须绿。
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


def main():
    fails = []

    def check(name, cond, detail=""):
        print("%s %s%s" % ("ok   " if cond else "FAIL ", name,
                           ("" if cond else " —— %s" % str(detail)[:400])), flush=True)
        if not cond:
            fails.append(name)

    # ---- 注册表与 pool_of（真源导入，与执行器同一份） ----
    if str(INTEG) not in sys.path:
        sys.path.insert(0, str(INTEG))
    import run_scenarios as rs  # noqa: E402
    reg = {e[0]: e for e in rs.SCENARIOS}

    def pool_of(entry):
        return rs.pool_of(entry)

    # ---- 清单 schema ----
    if not MANIFEST.exists():
        check("例外清单在册（batch_stage_exceptions.json）", False, "机器真源缺席=批台契约无执法面")
        print("SUMMARY pass=0 fail=1 env_fail=0 na=0")
        sys.exit(1)
    try:
        manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    except Exception as e:
        check("例外清单 JSON 可解析", False, str(e)[:200])
        print("SUMMARY pass=0 fail=1 env_fail=0 na=0")
        sys.exit(1)
    check("清单是对象数组", isinstance(manifest, list) and bool(manifest),
          "type=%s" % type(manifest).__name__)
    keys = {"entry", "pool", "project_pattern", "reason", "evidence"}
    schema_bad = []
    for it in manifest if isinstance(manifest, list) else []:
        if not isinstance(it, dict) or not keys.issubset(it):
            schema_bad.append(str(it)[:80])
        elif not str(it.get("reason", "")).strip() or not str(it.get("evidence", "")).strip():
            schema_bad.append("%s（reason/evidence 空）" % it.get("entry"))
    check("清单 schema 完整（五键+reason/evidence 非空）", not schema_bad, schema_bad[:4])

    # ---- 条目在册性 + 池一致性（防手抄漂移：entry 名机械取自注册表） ----
    unknown = [it.get("entry") for it in manifest if it.get("entry") not in reg]
    check("清单条目逐字在册（entry 名=注册表真源）", not unknown, unknown[:5])
    pool_bad = []
    for it in manifest:
        e = reg.get(it.get("entry"))
        if e is not None and it.get("pool") != pool_of(e):
            pool_bad.append("%s 清单=%s 注册表=%s" % (it.get("entry"), it.get("pool"), pool_of(e)))
    check("清单记录池=注册表池", not pool_bad, pool_bad[:4])
    pat_bad = []
    for it in manifest:
        pat = str(it.get("project_pattern", ""))
        if not PATTERN_OK.match(pat):
            pat_bad.append("%s → %r" % (it.get("entry"), pat))
    check("project_pattern 为合法工程名前缀形（小写/数字/中划线/尾部通配）", not pat_bad, pat_bad[:4])

    # ---- 清点判据不变式（C1 回潮网；判据含 *.sh —— gen1 条件1） ----
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
                if f.endswith(".py") and CONSUMER_PAT.search((REPO / f).read_text(encoding="utf-8", errors="replace")):
                    return True
            except OSError:
                continue
        return False

    manifest_names = {it.get("entry") for it in manifest if isinstance(it, dict)}
    pool_misses, manifest_misses = [], []
    for e in rs.SCENARIOS:
        if not is_candidate(e):
            continue
        if pool_of(e) in ("engine", "exclusive"):
            continue
        if e[0] in manifest_names:
            manifest_misses.append(e[0])
        else:
            pool_misses.append("%s（pool=%s，既非 engine/exclusive 也未声明例外）" % (e[0], pool_of(e)))
    check("批消费者候选 ⊆ engine/exclusive ∪ 例外清单（分类器漏接=C1 形态）",
          not pool_misses, pool_misses[:5])

    # ---- 清单条目起台面哨兵（注记不判红）：本判据是一级源码面（cmd 引用文件自身命中
    # 消费模式）；经 lib 二级消费的正当例外（herd/fuse/burst 族走 lib_herd_case 等）
    # 一级看不见——判红会假伤。豁免对象是否真消费者由人审 reason/evidence 承担，机器
    # 只守结构面与上方硬不变式。
    ghost = [it.get("entry") for it in manifest
             if it.get("entry") in reg and not is_candidate(reg[it.get("entry")])]
    if ghost:
        print("NOTE  清单一极判据未命中（若系 lib 二级消费=正当；若系零台条目=请删行）：%s"
              % ghost[:6], flush=True)

    print("SUMMARY pass=%d fail=%d env_fail=0 na=0" % (6 - len(fails), len(fails)))
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
