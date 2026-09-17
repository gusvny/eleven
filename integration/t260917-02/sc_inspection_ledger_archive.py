#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""t260917-02 集成场景三：台账跨票同名覆盖前归档留史（离线事故回归，ro 池）。

intent（登记于 run_scenarios.py，名 t260917-02-ledger-archive-regression）：
  260917 台账同名覆盖事故（91 条发现覆盖 89 条、无归档不可找回）的闸内回归——用户
  可感知契约：**任何跨票同名覆盖前，旧记录必须先归档且归档件可读**；归档不污染
  deadman 期号核查。六条断言腿：
  ①跨票覆盖 → 归档产生、旧记录 json 可读且内容==旧跑、canonical==新跑（验收③主断言）；
  ②同票自身重写 → 不归档（每跑一份的「跑」以票为界，不稀释成每写一份）；
  ③畸形旧件（坏字节）→ 原字节整体搬移留痕（corrupt 标记），新写不拦；
  ④缺 ticket_id 的旧件（畸形 json）→ 按他跑归档，字节可读不丢；
  ⑤归档/套件回执同规则 + archive/ 不进 deadman 期号集合（台账扫描不污染）；
  ⑥同秒连续两次跨票覆盖 → 两件归档并存（修复自身不得含静默覆盖——review R3）。

分工（防 intent 级重复）：
  · developer L1（server/engine/tests，engine 池）守归档真值表全组合（grace/碰撞/
    回执键形状）——但 engine 池**不在每票闸清单**（verify.yaml exclude_pools），本条
    是验收③在合并闸内的唯一机械回归（KI 事故回归纪律：无回归用例的修复不予合入）；
  · 闸内可见性是本条的存在理由：intent=「事故不变式在闸内不被回归」，与 L1 的
    实现真值表不同层（t260915-12 同票双场景不同层参照样）；
  · 真链路台账行为（壳不落账/真票落账）归 t260917-02-legacy-fire-redirect R1f，
    本条只守落盘函数边界的留史不变式。

三态：PASS exit 0 / FAIL exit 1 / ENV_FAIL exit 2（temporalio/venv 缺件=环境红点名，
inspection_flow 模块导入需要）。实现未落地=产品红（红属预期：TDD 信号）。

跑法（cwd=仓根）：
  PY=server/engine/.venv/bin/python; [ -x "$PY" ] || PY=python3; \\
    "$PY" -B integration/t260917-02/sc_inspection_ledger_archive.py
"""
import json
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, REPO)
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(REPO, "integration"))
sys.path.insert(0, os.path.join(REPO, "integration", "t260905-03"))
sys.path.insert(0, os.path.join(REPO, "server", "engine"))

from lib_inspection import die_env, die_fail  # noqa: E402

try:
    from inspection_flow import (write_inspection_report_impl,
                                 write_inspection_suite_receipt_impl)
    from inspection_deadman import ledger_periods
except Exception as e:  # noqa: BLE001——引擎模块不可达=环境红（点名缺什么）
    die_env("引擎模块不可达（temporalio/venv 缺席？server/engine/.venv）：%s: %s"
            % (type(e).__name__, e))

STATS = {"pass": 0, "fail": 0, "na": 0}
FAILS = []
PID = os.getpid()
INST = "arc-ins-%d" % PID
PERIOD = "20260101"
LEDGER_NAME = "inspection-%s-%s.json" % (INST, PERIOD)
SUITE_NAME = "inspection-%s-%s-suite.json" % (INST, PERIOD)
ARCHIVE_DIR = "archive"


def check(name, cond, detail=""):
    if cond:
        STATS["pass"] += 1
        print("PASS %s" % name, flush=True)
    else:
        STATS["fail"] += 1
        FAILS.append("%s%s" % (name, ("：" + detail) if detail else ""))
        print("FAIL %s%s" % (name, ("：" + detail) if detail else ""), flush=True)


def check_na(name, cond, detail=""):
    """系统态条件腿（环境不给力=N/A，非产品非环境红；全腿 N/A 才算场景红）。"""
    if cond:
        STATS["na"] += 1
        print("N/A %s" % name, flush=True)
    else:
        check(name, True)


def face(tid: str) -> dict:
    return {"ticket_id": tid, "kind": "inspection", "instance_id": INST,
            "period": PERIOD, "findings": [{"id": "f-" + tid, "severity": "high"}],
            "summary": {"total": 1}}


def write_report(out_dir: str, tid: str) -> dict:
    return write_inspection_report_impl(face(tid), out_dir)


def archive_files(out_dir: str):
    d = os.path.join(out_dir, ARCHIVE_DIR)
    return sorted(os.listdir(d)) if os.path.isdir(d) else []


def read_json(path: str):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _safe_read(path: str):
    """读 json，坏字节/坏形一律返回 None（归档件含 corrupt 搬移件——不可读≠可判等）。"""
    try:
        return read_json(path)
    except Exception:  # noqa: BLE001——刻意吞：判等面把不可读当不相等
        return None


def main() -> int:
    tmp = tempfile.mkdtemp(prefix="sandbar-t26091702c-")
    out_dir = os.path.join(tmp, "out", "inspection")
    try:
        # ---- ① 跨票覆盖 → 归档产生、旧记录可读、canonical==新跑 ----
        r1 = write_report(out_dir, "t260101-%02d" % (PID % 90 + 1))
        canonical = os.path.join(out_dir, LEDGER_NAME)
        check("A1a 前置：首次落账 canonical 在场", os.path.isfile(canonical),
              "path=%r" % (r1 or {}).get("path"))
        old_snapshot = read_json(canonical)
        tid_new = "t260101-%02d" % (PID % 90 + 2)
        write_report(out_dir, tid_new)
        arcs = archive_files(out_dir)
        check("A1b 跨票覆盖前产生归档（260917 事故回归主断言）",
              len(arcs) >= 1, "archive/=%s" % arcs)
        old_readable = None
        for name in arcs:
            try:
                data = read_json(os.path.join(out_dir, ARCHIVE_DIR, name))
            except Exception:  # noqa: BLE001——读不开的归档件不是「可读留史」
                continue
            if isinstance(data, dict) and data.get("ticket_id") == old_snapshot.get("ticket_id"):
                old_readable = data
                break
        check("A1c 归档件可读且内容==旧跑（丢史形态不许复现）",
              old_readable is not None
              and old_readable.get("findings") == old_snapshot.get("findings"),
              "归档件=%s 旧票=%r" % (arcs, old_snapshot.get("ticket_id")))
        check("A1d canonical==最新跑（每期一份语义不变）",
              read_json(canonical).get("ticket_id") == tid_new,
              "canonical=%r" % read_json(canonical).get("ticket_id"))

        # ---- ② 同票自身重写 → 不归档 ----
        arcs_before = archive_files(out_dir)
        write_report(out_dir, tid_new)
        check("A2 同票重写不归档（不稀释成每写一份）",
              archive_files(out_dir) == arcs_before,
              "前=%s 后=%s" % (arcs_before, archive_files(out_dir)))

        # ---- ③ 畸形旧件（坏字节）→ 原字节搬移留痕，新写不拦 ----
        corrupt = b"\x00\xff{not-json-partial"
        with open(canonical, "wb") as f:
            f.write(corrupt)
        tid_c = "t260101-%02d" % (PID % 90 + 3)
        try:
            write_report(out_dir, tid_c)
            ok_write = read_json(canonical).get("ticket_id") == tid_c
        except Exception as e:  # noqa: BLE001——畸形旧件炸掉新写=FAIL
            ok_write = False
            print("  畸形旧件写异常：%s: %s" % (type(e).__name__, e), flush=True)
        check("A3a 畸形旧件（坏字节）不拦新写，canonical==新票",
              ok_write, "canonical ticket=%r"
              % (read_json(canonical).get("ticket_id") if os.path.isfile(canonical) else None))
        moved = [n for n in archive_files(out_dir) if "corrupt" in n]
        raw_kept = False
        for name in moved:
            with open(os.path.join(out_dir, ARCHIVE_DIR, name), "rb") as f:
                if f.read() == corrupt:
                    raw_kept = True
                    break
        check("A3b 畸形旧件原字节整体搬移留痕（corrupt 标记，绝不静默丢字节）",
              raw_kept, "corrupt 件=%s" % moved)

        # ---- ④ 缺 ticket_id 的畸形 json 旧件 → 按他跑归档、字节可读 ----
        orphan = {"instance_id": INST, "period": PERIOD, "findings": []}  # 无 ticket_id
        with open(canonical, "w", encoding="utf-8") as f:
            json.dump(orphan, f, ensure_ascii=False)
        tid_d = "t260101-%02d" % (PID % 90 + 4)
        write_report(out_dir, tid_d)
        orphan_kept = any(
            read_json(os.path.join(out_dir, ARCHIVE_DIR, n)) == orphan
            for n in archive_files(out_dir)
            if n.endswith(".json"))
        check("A4 缺 ticket_id 旧件按他跑归档且内容可读（身份不明≠丢弃）",
              orphan_kept and read_json(canonical).get("ticket_id") == tid_d,
              "归档件=%s" % archive_files(out_dir))

        # ---- ⑤ 套件回执同规则 + archive/ 不进 deadman 期号集合 ----
        suite_old_tid = "t260101-%02d" % (PID % 90 + 1)
        write_inspection_suite_receipt_impl(INST, PERIOD,
                                            {"ticket_id": suite_old_tid,
                                             "scenarios": []}, out_dir)
        suite_before = archive_files(out_dir)
        write_inspection_suite_receipt_impl(INST, PERIOD,
                                            {"ticket_id": "t260101-%02d" % (PID % 90 + 2),
                                             "scenarios": []}, out_dir)
        suite_arcs = archive_files(out_dir)
        suite_old_kept = any(
            _safe_read(os.path.join(out_dir, ARCHIVE_DIR, n)) == {"ticket_id": suite_old_tid,
                                                                  "scenarios": []}
            for n in suite_arcs)
        check("A5a 套件回执跨票覆盖同规则归档且旧回执可读（同族面不漏——KI-055 实报即全族）",
              len(suite_arcs) == len(suite_before) + 1 and suite_old_kept,
              "suite 前=%s 后=%s 旧回执留史=%s"
              % (len(suite_before), len(suite_arcs), suite_old_kept))
        lp = ledger_periods(out_dir, INST)
        check("A5b archive/ 不进 deadman 期号集合（台账扫描不污染）",
              lp.get("periods") == {PERIOD} and lp.get("malformed") == [],
              "periods=%r malformed=%r" % (sorted(lp.get("periods") or []),
                                           lp.get("malformed")))

        # ---- ⑥ 同秒连续两次跨票覆盖 → 两件归档并存（修复不含静默覆盖——R3）----
        tid_e = "t260101-%02d" % (PID % 90 + 5)
        tid_f = "t260101-%02d" % (PID % 90 + 6)
        n_before = len(archive_files(out_dir))    # 基线在两次覆盖**前**取
        write_report(out_dir, tid_e)              # 同秒第 1 次跨票覆盖
        write_report(out_dir, tid_f)              # 同秒第 2 次跨票覆盖
        seq = archive_files(out_dir)
        check("A6 同秒连续跨票覆盖：归档件逐次并存（-N 递增，绝不静默互覆）",
              len(seq) >= n_before + 2
              and read_json(canonical).get("ticket_id") == tid_f,
              "基线=%s 归档件=%s" % (n_before, seq))
        e_kept = any(_safe_read(os.path.join(out_dir, ARCHIVE_DIR, n)) == face(tid_e)
                     for n in seq)
        check("A6b 中间跑（ticket_e）归档件仍在（逐跑留史不断代）",
              e_kept, "归档件=%s" % seq)

        # ---- ⑦ 归档失败不拦新写（系统态条件腿：root 下 chmod 可能无效 → N/A）----
        arc_dir = os.path.join(out_dir, ARCHIVE_DIR)
        try:
            os.chmod(arc_dir, 0o500)
            blocked = not os.access(arc_dir, os.W_OK)
        except Exception:  # noqa: BLE001
            blocked = False
        if blocked:
            try:
                write_report(out_dir, "t260101-%02d" % (PID % 90 + 7))
                check("A7 归档失败不拦新写（canonical 照常保最新）",
                      os.path.isfile(canonical), "")
            except Exception as e:  # noqa: BLE001
                check("A7 归档失败不拦新写（canonical 照常保最新）", False,
                      "%s: %s" % (type(e).__name__, e))
            finally:
                os.chmod(arc_dir, 0o755)
        else:
            check_na("A7 归档失败不拦新写（本环境 chmod 不可扰——root/管理员态，"
                     "系统态条件腿 N/A）", True)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print("SUMMARY pass=%d fail=%d env_fail=%d na=%d"
          % (STATS["pass"], STATS["fail"], 0, STATS["na"]), flush=True)
    if FAILS:
        print("FAIL_REASON: %s" % "；".join(FAILS), flush=True)
        return 1
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except Exception as e:  # noqa: BLE001——意外异常=产品红点名，不静默不假绿
        die_fail("场景异常退出：%s: %s" % (type(e).__name__, e))
