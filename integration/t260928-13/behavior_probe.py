#!/usr/bin/env python3
"""behavior_probe.py — child probe of sc_event_ledger_projection (t260928-13).

Runs INSIDE the engine venv (temporalio importable). Drives the real
server/engine/event_ledger.py through its public entry points against real
files in a tmp dir (SANDBAR_EVENT_LEDGER_DIR). Prints per-assertion ✓/✗ and
ends with BEHAVIOR_PASS=<n> / BEHAVIOR_FAIL=<n>. Exit 0 always (the parent
counts ENV_FAIL via its own temporalio probe); exit 2 only when temporalio
itself is missing.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import time
from pathlib import Path

try:
    import temporalio  # noqa: F401
except Exception as exc:  # pragma: no cover
    print("ENV_FAIL: temporalio 不可导入：%r" % (exc,))
    sys.exit(2)

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "server"))
sys.path.insert(0, str(ROOT / "server/engine"))

PASS = 0
FAIL = 0


def ok(cond, label):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  ✓ %s" % label)
    else:
        FAIL += 1
        print("  ✗ %s" % label)


def load_module():
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "event_ledger_under_test", ROOT / "server/engine/event_ledger.py")
    if spec is None or not (ROOT / "server/engine/event_ledger.py").exists():
        ok(False, "event_ledger.py 缺席：行为半未跑（TDD 红属预期）")
        print("BEHAVIOR_PASS=%d" % PASS)
        print("BEHAVIOR_FAIL=%d" % FAIL)
        sys.exit(0)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def payload(elp, **over):
    p = {
        "project": "demo", "scope": "project", "ticket": "t-1",
        "workflow": "DevLaneWorkflow", "template": "dev-lane",
        "stage": "implement", "state": "running", "reason": "进入本步",
        "gen": 1, "seq": 1, "run_id": "run-A",
    }
    p.update(over)
    # idem is stamped workflow-side (review [R3] shape): the probe supplies it
    # exactly as the mixin would.
    p.setdefault("idem", "%s|%s|%s|%s" % (p["project"], p["ticket"],
                                          p["run_id"], p["seq"]))
    return p


def read_lines(path: Path):
    if not path.exists():
        return []
    return [json.loads(x) for x in
            path.read_text("utf-8").splitlines() if x.strip()]


def owner_yaml(extra=""):
    """A registry entry that GENUINELY owns the engine repo.

    Config is engine-project-scoped (scope ⑧), and "engine project" means an
    entry whose `dirs` cover the engine repo root (audit._dirs_cover_engine
    semantics) — NOT "any entry carrying a paths: block". Writing the loose
    shape here is how t260928-13 shipped a resolver bug behind 24 green unit
    tests: the fixture encoded the wrong predicate. Keep this exact.
    """
    return ("schema: v1\n"
            "project:\n  - key: sandbar-demo\n    dirs:\n      - %s\n"
            "paths:\n  - /tmp/sandbar-demo\n%s" % (ROOT, extra))


def decoy_yaml():
    """A non-owner entry (alphabetically EARLIER) that declares the ledger on.

    Its declaration must never be adopted by the engine ledger writer.
    """
    return ("schema: v1\n"
            "project:\n  - key: aaa-decoy\n    dirs:\n      - /tmp/aaa-decoy\n"
            "paths:\n  - /tmp/aaa-decoy\n"
            "event_ledger:\n  enabled: true\n  keep_days: 1\n  max_mb: 1\n")


def call_append(elp, name_candidates, *args, **kw):
    """Call the append entry point by the first existing candidate name.

    The writer is a temporalio activity, hence async: driving the returned
    coroutine via asyncio.run is the public execution shape (what the worker
    does); a sync function passes through unchanged.
    """
    for n in name_candidates:
        fn = getattr(elp, n, None)
        if fn is not None:
            r = fn(*args, **kw)
            if hasattr(r, "__await__"):
                import asyncio
                return asyncio.run(r)
            return r
    raise AssertionError("append 入口缺席（候选：%s）" % (name_candidates,))


def main():
    elp = load_module()
    ok(hasattr(elp, "WRITE_FAILURES") or hasattr(elp, "write_failures"),
       "写失败计数器可观测（LOUD 的机器面）")

    # module-level int counter: read it LIVE via getattr each time (a bound
    # int would be a stale snapshot — the counter is mutated in the module)
    counter_get = (lambda: getattr(elp, "WRITE_FAILURES",
                                   getattr(elp, "write_failures", None))
                   if (hasattr(elp, "WRITE_FAILURES")
                       or hasattr(elp, "write_failures")) else None)

    with tempfile.TemporaryDirectory() as td:
        os.environ["SANDBAR_EVENT_LEDGER_DIR"] = td
        # Scope ⑧: undeclared => zero behaviour. So sections 1-6 must run with
        # the project DECLARED and ENABLED in an isolated registry root. The
        # declaration must sit in an entry whose dirs COVER the engine repo
        # (owner_yaml), otherwise the engine ledger is off by design.
        reg_root = Path(td) / "projects"
        os.environ["SANDBAR_PROJECTS_DIR"] = str(reg_root)
        demo_yaml = reg_root / "sandbar-demo" / "project.yaml"
        demo_yaml.parent.mkdir(parents=True, exist_ok=True)
        demo_yaml.write_text(owner_yaml("event_ledger:\n  enabled: true\n"),
                             "utf-8")

        # ---- 1 happy path: one line, complete field set, <4KB ----
        led = Path(td) / "demo.jsonl"  # env override IS the ledger dir
        try:
            call_append(elp, ("append_event_ledger", "append_event", "_append"),
                        payload(elp))
            lines = read_lines(led)
            ok(len(lines) == 1, "一条转移=恰一行台账")
            if lines:
                line = lines[0]
                need = {"project", "scope", "ticket", "workflow", "template",
                        "stage", "state", "reason", "gen", "ts", "seq",
                        "idem", "engine"}
                have = set(line) if isinstance(line, dict) else set()
                # schema version key name may be `v` or `schema_version`
                ok(bool(have & {"v", "schema_version"}), "schema 版本字段在位")
                ok(need <= have, "声明字段集全在位（缺=%s）" % sorted(need - have))
                raw = led.read_bytes().splitlines()
                ok(all(len(x) < 4096 for x in raw), "每行 <4KB")
        except AssertionError as exc:
            ok(False, "happy path 入口缺席/形状不符：%s" % exc)

        # ---- 2 idempotency: same payload re-delivered => still one line ----
        try:
            call_append(elp, ("append_event_ledger", "append_event", "_append"),
                        payload(elp))
            ok(len(read_lines(led)) == 1, "at-least-once 重投：同 idem 不出第二行")
        except AssertionError as exc:
            ok(False, "幂等重投入口缺席：%s" % exc)

        # ---- 3 cold-cache dedupe: fresh process state, file has key ----
        # (we simulate cold start by re-importing into a fresh module object)
        try:
            elp2 = load_module()
            call_append(elp2, ("append_event_ledger", "append_event", "_append"),
                        payload(elp2))
            ok(len(read_lines(led)) == 1, "冷进程（缓存空）文件扫描兜底：仍一行")
        except AssertionError as exc:
            ok(False, "冷缓存幂等探针缺席：%s" % exc)

        # ---- 4 run-id collision: same ticket+seq, new run => TWO lines ----
        try:
            call_append(elp, ("append_event_ledger", "append_event", "_append"),
                        payload(elp, run_id="run-B"))
            ok(len(read_lines(led)) == 2, "新 run_id 同票同 seq：新行不被误吞")
        except AssertionError as exc:
            ok(False, "run-id 维度探针缺席：%s" % exc)

        # ---- 5 malformed inputs: never raise, line bounded ----
        for name, bad in (("非 dict 载荷", "not-a-dict"),
                          ("缺关键键", {"project": "demo"}),
                          ("超长 reason", payload(elp, seq=9, reason="x" * 99999)),
                          ("非字符串 reason", payload(elp, seq=10, reason=12345))):
            try:
                call_append(elp, ("append_event_ledger", "append_event", "_append"),
                            bad)
                raw = led.read_bytes().splitlines()
                ok(all(len(x) < 4096 for x in raw),
                   "畸形输入不炸且行有界（%s）" % name)
            except AssertionError as exc:
                ok(False, "畸形输入探针缺席（%s）：%s" % (name, exc))
            except Exception as exc:
                ok(False, "畸形输入炸出（%s）：%r" % (name, exc))

        # ---- 6 fail-open + LOUD: unwritable LEDGER, writable dir (so the
        # opportunistic gaps.jsonl surface CAN land; a read-only DIR would
        # take out both surfaces by design — that face is covered by the
        # both-fail expectation in stderr, not by a gap file) ----
        ro = Path(td) / "ro"
        ro.mkdir()
        (ro / "demo.jsonl").write_text("", "utf-8")
        os.chmod(ro / "demo.jsonl", 0o444)
        before = counter_get() if counter_get else 0
        try:
            os.environ["SANDBAR_EVENT_LEDGER_DIR"] = str(ro)
            call_append(elp, ("append_event_ledger", "append_event", "_append"),
                        payload(elp, run_id="run-RO"))
            ok(True, "写失败不 raise（fail-open）")
        except AssertionError as exc:
            ok(False, "只读面入口缺席：%s" % exc)
        except Exception:
            ok(False, "写失败 raise 出来了（fail-open 破约）")
        finally:
            os.chmod(ro / "demo.jsonl", 0o644)
            os.environ["SANDBAR_EVENT_LEDGER_DIR"] = td
        after = counter_get() if counter_get else None
        if counter_get is None:
            ok(False, "计数器不可读（LOUD 机器面缺席）")
        else:
            ok(after is not None and after > before, "写失败计数器递增（LOUD）")
        gaps = list(ro.glob("demo.gaps.jsonl")) or \
            list(Path(td).glob("**/*gaps*"))
        ok(bool(gaps), "gap 记录面在盘（reconcile 可检测）")

        # ---- 7 config: malformed values => per-key defaults, still emits;
        # disabled => zero behaviour (config is engine-project-scoped, so both
        # faces are driven through the SAME engine project.yaml) ----
        demo_yaml.write_text(
            owner_yaml("event_ledger:\n  enabled: true\n"
                       "  keep_days: not-a-number\n  max_mb: -3\n"), "utf-8")
        try:
            r = call_append(elp, ("append_event_ledger", "append_event", "_append"),
                            payload(elp, run_id="run-CFG"))
            emitted = r.get("emitted", True) if isinstance(r, dict) else True
            ok(emitted, "畸形声明值不弃写（per-key 回落内置缺省，fail-open）")
        except AssertionError as exc:
            ok(False, "畸形声明探针缺席：%s" % exc)
        demo_yaml.write_text(
            owner_yaml("event_ledger:\n  enabled: false\n"), "utf-8")
        nf = Path(td) / "demo.jsonl"
        n_before = len(read_lines(nf))
        try:
            r = call_append(elp, ("append_event_ledger", "append_event", "_append"),
                            payload(elp, seq=99, run_id="run-OFF"))
            emitted = (r or {}).get("emitted", True) if isinstance(r, dict) else True
            ok(not emitted and len(read_lines(nf)) == n_before,
               "disabled（未声明/显式关）零文件行为（scope ⑧）")
        except AssertionError as exc:
            ok(False, "disabled 探针缺席：%s" % exc)
        # restore enabled for the rotation/rebuild sections
        demo_yaml.write_text(owner_yaml("event_ledger:\n  enabled: true\n"),
                             "utf-8")

        # ---- 7b owner resolution: a declaration living in a NON-owner entry
        # (alphabetically earlier, with its own paths: block) must NOT switch
        # the engine ledger on. This is the real-module lock for the
        # t260928-13 resolver bug: the shipped predicate was "has paths: +
        # any '- item'", which adopted the decoy's keep_days/max_mb.
        try:
            demo_yaml.write_text(owner_yaml(), "utf-8")     # owner declares nothing
            (reg_root / "aaa-decoy").mkdir(exist_ok=True)
            (reg_root / "aaa-decoy" / "project.yaml").write_text(
                decoy_yaml(), "utf-8")
            n_before = len(read_lines(nf))
            r = call_append(elp, ("append_event_ledger", "append_event", "_append"),
                            payload(elp, seq=77, run_id="run-DECOY"))
            emitted = (r or {}).get("emitted", True) if isinstance(r, dict) else True
            ok(not emitted and len(read_lines(nf)) == n_before,
               "非所属项目的声明不启账本（引擎所属项目=dirs 覆盖引擎仓根）")
            picked = getattr(elp, "_find_engine_project_yaml", None)
            if picked is not None:
                ok(picked(reg_root) == demo_yaml,
                   "解析器选中真所属条目（不选字母序更早的干扰条目）")
        except AssertionError as exc:
            ok(False, "所属项目解析探针缺席：%s" % exc)
        except Exception as exc:
            ok(False, "所属项目解析炸出：%r" % (exc,))
        finally:
            demo_yaml.write_text(owner_yaml("event_ledger:\n  enabled: true\n"),
                                 "utf-8")
            (reg_root / "aaa-decoy" / "project.yaml").unlink(missing_ok=True)

        # ---- 8 rotation: >=max_mb renames to a dated archive (naming-plane
        # only); sweep drops archives older than keep_days, keeps fresh ones
        try:
            big = "\n".join(json.dumps(payload(elp, seq=60 + i))
                            for i in range(20000))          # > 1MB
            led.write_text(big + "\n", "utf-8")
            cfg = {"enabled": True, "keep_days": 14, "max_mb": 1}
            elp._maybe_rotate(led, cfg)      # 实现面入口（activity 体内调用点）
            arch = [p for p in led.parent.iterdir()
                    if p.name.startswith("demo.jsonl.") and
                    elp._parse_archive_day(p.name, "demo.jsonl")]
            ok(bool(arch), "轮转产出归档件（naming-plane only）")
            old = led.parent / "demo.jsonl.20200101-000000-deadbe"
            old.write_text("{}\n", "utf-8")
            elp._sweep("demo", cfg, Path(td))
            ok(not old.exists(), "超窗归档被 sweep 清除（keep_days 判据）")
            ok(bool([p for p in led.parent.iterdir()
                     if p.name.startswith("demo.jsonl.") and p != old]),
               "窗内归档不被 sweep 误删")
        except AssertionError as exc:
            ok(False, "轮转入口缺席（rotate/sweep）：%s" % exc)
        except Exception as exc:
            ok(False, "轮转炸出：%r" % exc)

        # ---- 9 rebuild: derived projection ----
        # timeline entries carry the mixin's ledger_seq/ledger_run markers
        # (expected_lines only consumes marked transition entries)
        try:
            rebuild = getattr(elp, "ledger_rebuild", None) or \
                getattr(elp, "rebuild_ticket_lines")
            RUN = "run-R"
            timeline = [
                {"stage": "implement", "state": "running", "reason": "进入本步",
                 "gen": 1, "at": "2026-09-28T10:00:00+08:00",
                 "ledger_seq": 1, "ledger_run": RUN},
                {"stage": "implement", "state": "done", "reason": "完成",
                 "gen": 1, "at": "2026-09-28T10:01:00+08:00",
                 "ledger_seq": 2, "ledger_run": RUN},
                {"stage": "review_plan", "state": "running", "reason": "审方案",
                 "gen": 1, "at": "2026-09-28T10:02:00+08:00",
                 "ledger_seq": 3, "ledger_run": RUN},
            ]
            # seed the projection with the same idem shape, then damage it:
            # drop the first line, duplicate an idem
            seed = []
            for t in timeline:
                ev = {"project": "demo", "ticket": "t-1", "run_id": RUN,
                      "seq": t["ledger_seq"], "stage": t["stage"],
                      "state": t["state"], "reason": t["reason"],
                      "gen": t["gen"], "ts": t["at"],
                      "idem": "demo|t-1|%s|%d" % (RUN, t["ledger_seq"])}
                seed.append(json.dumps(ev))
            keep = seed[1:]
            keep.append(keep[0])
            led.write_text("\n".join(keep) + "\n", "utf-8")
            before_n = len(read_lines(led))
            r = rebuild("demo", "t-1", timeline, ledger_dir=Path(td))
            after_lines = read_lines(led)
            ok(isinstance(r, dict), "rebuild 回执是结构化报告")
            ok(len(after_lines) == before_n + 1, "缺行被恰补一次")
            idems = [x.get("idem") for x in after_lines if isinstance(x, dict)]
            ok(len(idems) != len(set(idems)), "重复 idem 被报告而非再补（重复计数在回执）")
            dup_key = (r or {}).get("duplicate_idem")
            ok(dup_key is not None and dup_key >= 1,
               "回执点名 duplicate_idem（派生投影的报告面）")
        except AssertionError as exc:
            ok(False, "rebuild 探针缺席：%s" % exc)
        except Exception as exc:
            ok(False, "rebuild 炸出：%r" % exc)

    print("BEHAVIOR_PASS=%d" % PASS)
    print("BEHAVIOR_FAIL=%d" % FAIL)


if __name__ == "__main__":
    main()
