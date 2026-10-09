#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""t260905-01 场景①：收口两问防回退守卫（沉淀触发器 + 反向同步闸，灰盒 L2/L3）。

用户视角契约（工单正文验收口径）：
- 验收①：收口回执含两问记录，且**未答也是一条记录**（不答不阻塞收口有实证）；
- 验收②：矛盾登记可查——债条目落泳道 pending-doc-sync.jsonl，且回执携带条目
  本体全量（doc/claim/actual）+ 转正纪律句（债登记纪律进流程的落点）；
- 验收③：触发器/闸各带防回退——触发器被拆（acceptance 分支无判读调用/增项缝
  文案缺失）=源码锁红；闸失灵（矛盾声明但不登记/畸形即崩/改 status）=行为子用例红。

结构：扫描器自证半（stage_block 切块器干净/注入样本红绿）→ 源码契约锁半
（shared 增项缝文案 / apply_doc_gate 三件套定义与 acceptance 调用位 / 常量 /
dev_lane STAGES 两问验收项——锚名字与调用点形状，不锚行号）→ 行为半
（parse_doc_gate 桩样本三态 / register 幂等与 actual 演进 / apply 拼装与
不阻塞语义）。行为半需 temporalio：缺失=ENV_FAIL 点名收场，stdlib 链照跑。
实现落地前红属预期（TDD 信号），arbitrate/merge 期必须绿。

与 developer L1（engine/tests 纯函数白盒）不同层：本条另守源码锁（防
触发器被整段拆除而单测随之删除的共谋回退）与契约面（回执小节/转正纪律句/
去重键含 actual 的 append-only 审计语义）。
"""
import json
import os
import shutil
import stat
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from lib_t260905_01 import (  # noqa: E402
    REPO, POC, check, env_fail, summary, temporalio_available, stage_block,
)

sys.path.insert(0, str(POC))
import shared  # noqa: E402  纯标准库依赖面

SHARED_SRC = (POC / "shared.py").read_text(encoding="utf-8")
AA_SRC = (POC / "agent_activities.py").read_text(encoding="utf-8")
DL_SRC = (POC / "dev_lane.py").read_text(encoding="utf-8")

# ---------- 自证半：切块器红绿（扫描器自身有效性先证明） ----------
SAMPLE_OK = 'Stage(id="acceptance_walkthrough", desc="走查",\n acceptance=("沉淀一问", "矛盾核对"),\n      ),\nStage(id="merge_check"'
SAMPLE_NO = 'Stage(id="acceptance_walkthrough", desc="走查"),\nStage(id="merge_check"'
_blk_ok = stage_block(SAMPLE_OK, "acceptance_walkthrough")
check("S1 切块器正样本（含两问文案的块被切出）",
      "沉淀一问" in _blk_ok and "矛盾核对" in _blk_ok)
check("S2 切块器负样本（无两问文案的块不误报）",
      stage_block(SAMPLE_NO, "acceptance_walkthrough") != ""
      and "沉淀一问" not in stage_block(SAMPLE_NO, "acceptance_walkthrough"))
check("S3 切块器缺席样本（stage 不在=空串不崩）",
      stage_block(SAMPLE_NO, "ui_evidence") == "")

# ---------- 源码契约锁半（处处可跑） ----------
_extra = (shared.STAGE_ACCEPTANCE_EXTRA.get("acceptance_walkthrough") or ())
_extra_text = "；".join(_extra)
check("A1 增项缝两问文案在位（STAGE_ACCEPTANCE_EXTRA[acceptance_walkthrough] 非空）",
      bool(_extra_text))
check("A2 沉淀一问指令在位（含沉淀+从 deliverables 推预填建议依据）",
      "沉淀" in _extra_text and "deliverables" in _extra_text)
check("A3 反向同步闸指令在位（含矛盾/反向同步核对）",
      "矛盾" in _extra_text)
check("A4 债登记纪律进流程（转正纪律句在场——正文验收口径的流程落点）",
      "转正" in _extra_text)
check("A5 判读纯函数三件套定义在场（agent_activities）",
      all(("def %s(" % fn) in AA_SRC for fn in
          ("parse_doc_gate", "register_pending_doc_sync", "apply_doc_gate")))
check("A6 acceptance 返回路径调用位在场（触发器被拆=红）",
      "apply_doc_gate(res" in AA_SRC)
check("A7 债册常量在位（pending-doc-sync.jsonl 路径可查可审计）",
      "pending-doc-sync.jsonl" in (SHARED_SRC + AA_SRC))
check("A8 dev_lane STAGES 两问验收项追加（走查块含沉淀/矛盾核对项）",
      "Retention question" in stage_block(DL_SRC, "acceptance_walkthrough")
      and "Contradiction-check conclusion" in stage_block(DL_SRC, "acceptance_walkthrough"))

# ---------- 行为半（temporalio 面；缺失=ENV_FAIL） ----------
aa = None
if temporalio_available():
    try:
        sys.path.insert(0, str(POC))
        import agent_activities as aa  # noqa: E402
    except Exception as e:  # 依赖不齐（KI-039 同族）=环境红，不假绿
        env_fail("agent_activities 导入失败：%s: %s" % (type(e).__name__, e))
else:
    env_fail("temporalio 缺失：行为子用例（parse/register/apply）无法驱动——"
             "stdlib 源码锁子用例已照跑；arbitrate/merge 期（venv 在位）必须全绿")

if aa is not None:
    parse = getattr(aa, "parse_doc_gate", None)
    register = getattr(aa, "register_pending_doc_sync", None)
    apply_gate = getattr(aa, "apply_doc_gate", None)
    check("B0 行为承诺面在场（三函数可调用）",
          all(callable(f) for f in (parse, register, apply_gate)))

    if callable(parse):
        # 正常两态
        r = parse({"doc_sediment": {"want": True, "target": "docs/x.md", "reason": "有新契约"},
                   "doc_conflicts": [{"doc": "docs/a.md", "claim": "c1", "actual": "a1"}]})
        check("B1 正常样本判读（沉淀已答+矛盾 1 条）",
              isinstance(r, dict) and r.get("sediment") and
              len(r.get("conflicts") or []) == 1)
        # 显式无可沉淀=已答（want=false 不算未答）
        r2 = parse({"doc_sediment": {"want": False, "reason": "纯盘点无可沉淀"}})
        check("B2 显式无可沉淀≠未答（want=false 是答案）",
              isinstance(r2, dict) and isinstance(r2.get("sediment"), dict)
              and r2["sediment"].get("want") is False)
        # 未答（C1 条件：两问缺席各自可辨）
        r3 = parse({})
        s_absent = (r3.get("sediment") is None) or (r3.get("sediment_absent") is True)
        c_absent = not (r3.get("conflicts") or []) or (r3.get("conflicts_absent") is True)
        check("B3 两问未答各自可辨（per-question absent 留痕）",
              isinstance(r3, dict) and s_absent and c_absent)
        # 畸形输入不崩不裁决
        try:
            r4 = parse({"doc_sediment": "字符串畸形", "doc_conflicts": 42,
                        "doc_sediment_x": "x" * 100000})
            check("B4 畸形输入软降级（malformed 记录、不抛）",
                  isinstance(r4, dict))
        except Exception as e:
            check("B4 畸形输入软降级（malformed 记录、不抛）", False,
                  "parse 抛 %s: %s" % (type(e).__name__, e))

    if callable(register):
        tmp = Path(tempfile.mkdtemp(prefix="t260905-01-reg-"))
        def _pending(base):
            # 引擎按 resolve_dot_dir 粘滞语义落 doc-gate 台账：新 base 在新名目录，
            # 既有旧名泳道在旧名目录——过渡期读侧同序双探（t260907-04 目录过渡）
            for name in (".sandbar", ".suyou"):  # naming-compat
                p = base / name / "doc-gate" / "pending-doc-sync.jsonl"
                if p.is_file():
                    return p
            return base / ".sandbar" / "doc-gate" / "pending-doc-sync.jsonl"
        try:
            conf = [{"doc": "docs/a.md", "claim": "主张 X", "actual": "现实 Y"}]
            r1 = register(tmp, "t1", conf)
            jf = _pending(tmp)
            check("B5 登记→jsonl 条目本体可查（验收②）",
                  jf.is_file() and "docs/a.md" in jf.read_text(encoding="utf-8")
                  and "主张 X" in jf.read_text(encoding="utf-8"))
            register(tmp, "t1", conf)  # 同键再登记
            check("B6 幂等去重（同 ticket+doc+claim+actual 不重复）",
                  len(jf.read_text(encoding="utf-8").strip().splitlines()) == 1)
            register(tmp, "t1", [{"doc": "docs/a.md", "claim": "主张 X",
                                  "actual": "现实 Y-演进"}])
            check("B7 actual 演进=新条目（append-only latest-wins）",
                  len(jf.read_text(encoding="utf-8").strip().splitlines()) == 2)
            jf.write_text('{"torn": \n' + jf.read_text(encoding="utf-8"),
                          encoding="utf-8")  # 预置 torn 行
            try:
                register(tmp, "t1", [{"doc": "docs/b.md", "claim": "c", "actual": "a"}])
                check("B8 既有 torn 行容忍（跳行不抛）", True)
            except Exception as e:
                check("B8 既有 torn 行容忍（跳行不抛）", False, repr(e)[:120])
        finally:
            os.chmod(tmp, 0o755)
            shutil.rmtree(tmp, ignore_errors=True)
        # 写失败降级（只读目录）
        tmp2 = Path(tempfile.mkdtemp(prefix="t260905-01-ro-"))
        try:
            os.chmod(tmp2, 0o500)
            try:
                rr = register(tmp2, "t1", [{"doc": "d", "claim": "c", "actual": "a"}])
                ok = (isinstance(rr, dict) and rr.get("registered") is False) or \
                     (isinstance(rr, dict) and rr.get("error"))
                check("B9 写失败降级（registered=False/error 点名，不抛）", bool(ok))
            except Exception as e:
                check("B9 写失败降级（registered=False/error 点名，不抛）", False,
                      "register 抛 %s: %s" % (type(e).__name__, e))
        finally:
            os.chmod(tmp2, 0o755)
            shutil.rmtree(tmp2, ignore_errors=True)

    if callable(apply_gate):
        def mk_rfile(payload):
            d = Path(tempfile.mkdtemp(prefix="t260905-01-rf-"))
            f = d / "result.json"
            f.write_text(payload if isinstance(payload, str)
                         else json.dumps(payload, ensure_ascii=False),
                         encoding="utf-8")
            return d, f

        d1, f1 = mk_rfile({"status": "ok", "summary": "s", "report": "验收报告",
                           "doc_sediment": {"want": True, "target": "docs/x.md",
                                            "reason": "r"},
                           "doc_conflicts": [{"doc": "docs/a.md", "claim": "主张 X",
                                              "actual": "现实 Y"}]})
        res = shared.StageResult()
        try:
            apply_gate(res, f1, d1, "t1")
            check("B10 回执含两问小节+条目本体全量（验收①②拼装面）",
                  "收口两问" in (res.report or "") and "docs/a.md" in res.report
                  and "主张 X" in res.report and "现实 Y" in res.report)
            check("B11 转正纪律句进回执（债登记纪律进流程）",
                  "转正" in (res.report or ""))
            check("B12 evidence 机器口径行（形态/登记行数/jsonl 路径）",
                  isinstance(res.evidence, str) and len(res.evidence) > 0
                  and "pending-doc-sync" in (res.evidence + (res.report or "")))
            check("B13 deliverables 带债册路径（有登记时）",
                  any("pending-doc-sync" in x for x in res.deliverables))
            check("B14 不阻塞语义（status 不被两问改写）", res.status == "ok")
        except Exception as e:
            check("B10 回执含两问小节+条目本体全量（验收①②拼装面）", False,
                  "apply 抛 %s: %s" % (type(e).__name__, e))
        finally:
            shutil.rmtree(d1, ignore_errors=True)

        # 未答也是一条记录（不答不阻塞有实证）
        d2, f2 = mk_rfile({"status": "ok", "summary": "s", "report": "验收报告"})
        res2 = shared.StageResult()
        try:
            apply_gate(res2, f2, d2, "t1")
            check("B15 未答→回执仍含两问记录（未答留痕，验收①）",
                  "收口两问" in (res2.report or "") or
                  "未答" in ((res2.report or "") + (res2.evidence or "")))
            check("B16 未答不改 status（不阻塞）", res2.status == "ok")
        except Exception as e:
            check("B15 未答→回执仍含两问记录（未答留痕，验收①）", False,
                  "apply 抛 %s: %s" % (type(e).__name__, e))
        finally:
            shutil.rmtree(d2, ignore_errors=True)

        # 文件级畸形（KI-012 面不新增爆面：不抛、留痕、不改 status）
        d3, f3 = mk_rfile('{"status": "ok", "broken": ')
        res3 = shared.StageResult()
        try:
            apply_gate(res3, f3, d3, "t1")
            check("B17 文件级畸形软降级（不抛+留痕）",
                  len((res3.report or "") + (res3.evidence or "")) > 0)
        except Exception as e:
            check("B17 文件级畸形软降级（不抛+留痕）", False,
                  "apply 抛 %s: %s" % (type(e).__name__, e))
        finally:
            shutil.rmtree(d3, ignore_errors=True)

        # 走查 failed 轮（C2 条件）：拼装不抛、且不得把 failed 翻成 ok
        d4, f4 = mk_rfile({"status": "failed", "summary": "发现问题", "report": "问题报告"})
        res4 = shared.StageResult(status="failed")
        try:
            apply_gate(res4, f4, d4, "t1")
            check("B18 failed 轮不抛且不翻 status（不阻塞语义双态保持）",
                  res4.status == "failed")
        except Exception as e:
            check("B18 failed 轮不抛且不翻 status（不阻塞语义双态保持）", False,
                  "apply 抛 %s: %s" % (type(e).__name__, e))
        finally:
            shutil.rmtree(d4, ignore_errors=True)

sys.exit(summary())
