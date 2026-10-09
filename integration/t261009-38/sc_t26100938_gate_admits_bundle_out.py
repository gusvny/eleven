#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""t261009-38 场景①：声明的 build chain 产物 = 合法交付——段路径闸不再吞掉它。

intent（工单不变量②④⑥「src 在写集内 → out 前缀写入被点名放行；src 不在 → 拒；
声明缺失/畸形 fail-closed；其余面一律不放宽」的用户可感知面）：
- G1 写集只含 src 前缀、泳道脏文件落在声明的 out 前缀下 → settle 放行、文件原地在场、
  回执**点名**规则与文件（named, never silent）；真实死结形态（t261009-22/-35）。
- G2 src 不在写集 → 同一 out 写入照旧拒（ unauthorized_path，不因声明意外放宽）。
- G3 声明缺失 → out 写入拒（fail-closed：没声明就没有放行）。
- G4 声明畸形 → out 写入拒且 settle 正常完成（不崩、不静默放行）。
- G5 受保护真源照旧拦：声明文件自身（server/merge-checks.yaml，基线已存在）被改 →
  protected_path 拒——bundle 规则不是保护闸的旁路。
- G6 窄缝不失效：同一批次里声明外的越权件照旧拒。

与相邻场景 intent 分界：
- sc_t26100938_mergecheck_pair_agreement：彼锁**合并闸白名单面**（verify_lane code 道
  diff 面），本条锁**段路径闸**（settle 时刻脏清单）——同一声明、两个执法点；
- bundle_freshness 红（src 改了没重建仍红）本票不触碰、不重判（工单规格⑥：只放行
  重建产物进 commit，不弱化红）——其真值表归既有 merge_check 面与 developer L1；
- developer L1（谓词真值表、畸形输入矩阵）白盒随实现，不在本条重铺。

跑法：PY=server/engine/.venv/bin/python; [ -x "$PY" ] || PY=python3; "$PY" -B
      integration/t261009-38/sc_t26100938_gate_admits_bundle_out.py（cwd=仓根）
三态：PASS exit 0 / FAIL exit 1 / ENV_FAIL exit 2。实现落地前 G1 类新契约子用例红属
预期（TDD 信号），arbitrate/merge 期必须绿。
"""
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
os.environ["SANDBAR_TARGET_HOST"] = "127.0.0.1:9"  # 红线桩：先钉再 import
os.environ.pop("SANDBAR_NAMESPACE", None)
sys.path.insert(0, str(HERE))
from lib_t26100938 import (  # noqa: E402
    MALFORMED_CHECKS_YAML, OUT, SRC, TID, archive_find, check, dirty,
    engine_modules, env_fail, git_ok, mk_bundle_lane, quarantine_root, rmtree, settle,
    summary,
)
from pathlib import Path as _P  # noqa: E402  (archive_find 断言用)

OUTFILE = OUT + "client.js"
OUT_BASELINE = "old bundle\n"  # 夹具基线内容（mk_bundle_lane 写入）
_shared = None  # 由 main() 注入（engine_modules 结果），供 refused_file 取隔离档根

def refused_file(lane, rel, note, baseline_content):
    """Per-file refusal evidence（读者侧磁盘真貌优先）：越权 M 件被**回滚**（工作区
    内容回基线）或被挪档（隔离档留档），或整批被闸拒（path_gate_reason）。
    不锚处置通道的目录形状（实现细节），锚「写入没有落地」这个用户可感知终态。"""
    qroot = quarantine_root(lane, shared) if False else None  # noqa: F841
    p = lane / rel
    restored = p.is_file() and p.read_text(encoding="utf-8") == baseline_content
    flattened = rel.replace("/", "__")
    archived = bool(archive_find(quarantine_root(lane, _shared), Path(rel).name)) \
        or bool(archive_find(quarantine_root(lane, _shared), flattened + ".diff"))
    return restored or archived or "path_gate_reason=" in note


def committed_files(r):
    return str(getattr(r, "lane_commits", "") or "")


def main():
    (mods, why) = engine_modules()
    if mods is None:
        env_fail("引擎模块不可用（%s）——段路径闸无 stdlib 替代子用例" % why)
    shared, aa = mods
    globals()["_shared"] = shared

    # ---- G1 真实死结形态：src 在写集、out 重建件被点名放行 ----
    print("\n== G1 src 在写集：out 重建件放行 + 回执点名（named, never silent）")
    tmp, mainrepo, lane, fork = mk_bundle_lane("t26100938-g1-")
    dirty(lane, OUTFILE, "rebuilt bundle\n")
    qroot = quarantine_root(lane, shared)
    r1 = settle(shared, aa, lane, TID, "implement", 1, fork,
                write_set=[SRC])
    check("G1a settle 放行（不再 unauthorized_path 死锁）", not getattr(r1, "gate_refusal", None),
          "note=%r err=%r" % ((getattr(r1, "note", "") or "")[:300],
                              (getattr(r1, "error", "") or "")[:200]))
    check("G1b 重建件原地在场（lawful path to land，不被挪档）",
          (lane / OUTFILE).is_file()
          and not archive_find(qroot, _P(OUTFILE).name),
          "gone=%s" % (lane / OUTFILE).is_file())
    check("G1c 回执点名规则与文件（不静默）",
          OUTFILE in (getattr(r1, "note", "") or "")
          and "bundle" in (getattr(r1, "note", "") or "").lower(),
          "note=%r" % (getattr(r1, "note", "") or "")[:300])
    rmtree(tmp)

    # ---- G2 src 不在写集：同一 out 写入照旧拒 ----
    print("\n== G2 src 不在写集：out 写入不放宽")
    tmp, mainrepo, lane, fork = mk_bundle_lane("t26100938-g2-")
    dirty(lane, OUTFILE, "rebuilt bundle\n")
    r2 = settle(shared, aa, lane, TID, "implement", 1, fork,
                write_set=["docs/"])
    note2 = getattr(r2, "note", "") or ""
    check("G2a out 写入被处置（挪档留档，不因声明放宽）",
          refused_file(lane, OUTFILE, note2, OUT_BASELINE),
          "note=%r" % note2[:300])
    check("G2b 越权件不在 commit 面（lane_commits 不含 out 件）",
          OUTFILE not in committed_files(r2), "commits=%r" % committed_files(r2)[:200])
    rmtree(tmp)

    # ---- G3 声明缺失：fail-closed 拒 ----
    print("\n== G3 声明缺失：无声明=无放行")
    tmp, mainrepo, lane, fork = mk_bundle_lane("t26100938-g3-", checks=None)
    dirty(lane, OUTFILE, "rebuilt bundle\n")
    r3 = settle(shared, aa, lane, TID, "implement", 1, fork,
                write_set=[SRC])
    note3 = getattr(r3, "note", "") or ""
    check("G3a 声明缺失时 out 写入被拒（挪档/闸拒）",
          refused_file(lane, OUTFILE, note3, OUT_BASELINE),
          "note=%r" % note3[:300])
    rmtree(tmp)

    # ---- G4 声明畸形：fail-closed 拒且不崩 ----
    print("\n== G4 声明畸形：fail-closed，settle 完成")
    tmp, mainrepo, lane, fork = mk_bundle_lane("t26100938-g4-",
                                               checks=MALFORMED_CHECKS_YAML)
    dirty(lane, OUTFILE, "rebuilt bundle\n")
    try:
        r4 = settle(shared, aa, lane, TID, "implement", 1, fork, write_set=[SRC])
        crashed = False
        note4 = getattr(r4, "note", "") or ""
    except Exception as e:  # 崩溃本身就是 FAIL 面
        crashed = True
        note4 = "crash: %s" % e
    check("G4a 畸形声明不炸 settle", not crashed, "note=%r" % note4[:300])
    check("G4b 畸形声明时 out 写入被拒（不静默放行）", crashed
          or refused_file(lane, OUTFILE, note4, OUT_BASELINE),
          "note=%r" % note4[:300])
    rmtree(tmp)

    # ---- G5 保护闸不被 bundle 规则旁路 ----
    print("\n== G5 受保护真源照旧拦（声明文件自身被改）")
    tmp, mainrepo, lane, fork = mk_bundle_lane("t26100938-g5-")
    dirty(lane, "server/merge-checks.yaml",
          "bundle_pairs:\n  - src: evil/\n    out: everything/\n")
    r5 = settle(shared, aa, lane, TID, "implement", 1, fork,
                write_set=[SRC])
    note5 = getattr(r5, "note", "") or ""
    check("G5a 声明文件（基线已存在的受保护真源）被改 → 拒",
          bool(getattr(r5, "gate_refusal", None)) or ("path_gate_reason=" in note5),
          "note=%r" % note5[:300])
    # 观测（261009 实跑）：段闸先于受保护闸判定，拒因=unauthorized_path；
    # intent 只要求「被拒且具名」，两闸谁先到都算守住——不锚执法顺序（实现细节）。
    check("G5b 拒面点名被改文件本身（bundle 规则不构成保护闸旁路）",
          "merge-checks.yaml" in note5, "note=%r" % note5[:300])
    rmtree(tmp)

    # ---- G6 窄缝：同批次声明外越权件照旧拒 ----
    print("\n== G6 同批次混入声明外越权件：照旧拒")
    tmp, mainrepo, lane, fork = mk_bundle_lane("t26100938-g6-")
    dirty(lane, OUTFILE, "rebuilt bundle\n")
    dirty(lane, "server/engine/rogue_helper.py", "not lawful\n")
    q6 = quarantine_root(lane, shared)
    r6 = settle(shared, aa, lane, TID, "implement", 1, fork,
                write_set=[SRC])
    note6 = getattr(r6, "note", "") or ""
    check("G6a 声明外越权件照旧被处置（挪档；放行是按文件窄缝不是闸失效）",
          bool(archive_find(q6, "rogue_helper.py")) or "rogue_helper.py" in note6,
          "note=%r archive=%s" % (note6[:300], archive_find(q6, "rogue_helper.py")))
    ok_log, log_out = git_ok(["log", "-1", "--name-only", "--pretty=%h"], lane)
    check("G6b 合法 out 件照常落 commit + 点名（窄缝不误伤；读者侧 git log 真路径）",
          ok_log and OUTFILE in log_out and OUTFILE in note6,
          "log=%r note=%r" % (log_out[-200:], note6[:200]))
    rmtree(tmp)

    sys.exit(summary())


if __name__ == "__main__":
    main()
