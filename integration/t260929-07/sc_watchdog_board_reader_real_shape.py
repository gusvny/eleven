#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""sc_watchdog_board_reader_real_shape.py — 看板读取器真形锁（t260929-07，灰盒 L2/L3）。

背景（t260928-28 合并件真机核验实报缺陷）：makeBoardReader 只认
`{result:{ok,tickets}}` 信封，而真实入口 `client.py ticket-list {}` 打印的是信封但内层无 ok 键
（`{ok:true,result:{count,tickets}}`，t260929-07 实现期实证修正——初判「裸结果」
不准，真形锁已按实证契约钉死）⇒ 生产里 reconcile 永远 degraded。该面既有五条场景
（t260928-28-watchdog-*）全部经 harness 桩注入已解析看板——桩形状由实现自身假设
塑形，不可能与实现分歧（KI-148/150 自证夹具族）——所以套件全绿而功能全死。本条
是补上的那把**真形锁**：让实现机器读真入口的**实际 stdout**，而不是我们假设的形状。

intent（工单验收口径，用户可感知行为）：
- A 真入口在场探针：真跑一次 `client.py ticket-list {}`（cwd=server/engine），拿其
  精确 stdout。引擎不可达（spawn 失败/非零退出/stdout 非 JSON）=ENV_FAIL exit 2
  ——绝不静默放过（工单铁律：Temporal 不可达⇒ENV_FAIL，never a silent pass）。
- B 真形锁（本票核心）：把 A 的**逐字节原样 stdout** 喂进实现导出的解析路径
  （node.ts parseTicketListDoc——review 意见落地后的共享纯函数，读器与锁同一条
  出货代码路径，杜绝测试侧重抄实现假设）→ 断言 ok=true、tickets>0、每行有 id；
  且形状契约半：真入口是**信封形但内层 result 无 ok 键**（{ok:true,
  result:{count,tickets}}——旧代码 res.ok!==true 因此永不通过；本锁钉死这条契约，
  引擎内层补出 ok 键翻契约时有意识翻红，而非被双形状容忍静默吞掉）。
- C 读器端到端：makeBoardReader(repo)() → ok=true 且 rows>0（A 已证引擎可达，
  此刻 ok=false=产品红而非环境红——正是出货代码在真机上坏掉的形状）。
- D 畸形输入矩阵（外部输入三态纪律 + review 意见①②）：非 JSON / 空 stdout /
  缺 tickets / tickets 非数组 / 信封 ok:false / `result` 在场但为 null ——全部
  结构化 ok:false + 带原因，绝不抛裸异常、绝不把解析失败误报成「引擎不可达」。
- E 信封正形回归：`{result:{ok:true,tickets:[…]}}` 仍被接受（双形状容忍不丢旧契约）。

三态：node 缺席 / 引擎不可达 = ENV_FAIL exit 2；实现未落地（无 parseTicketListDoc
导出 / 读器仍只认信封）= FAIL exit 1 点名（TDD 期红属预期，arbitrate/merge 期必须
绿）。反证（anti-proof）：本场景 B/C 两段打在 pre-fix 代码上必红（TDD 红即反证，
实现交接报告须记录该反证跑）。
intent 分工：t260928-28-watchdog-reconcile-board-truth 守对账语义（看板为真源/
缺行留痕/降级显式，看板经桩注入）；本条只守「读器能机器读真入口的实际形状」这一
条缝——对账逻辑零涉及，互不顶替。离线秒级、零 docker、零 3099/7233 接触（只读
spawn 引擎 client.py，不改任何状态）。
Run directly: python3 integration/t260929-07/sc_watchdog_board_reader_real_shape.py（cwd=仓根）。
"""
from __future__ import annotations

import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent.parent
ENGINE = ROOT / "server" / "engine"
NODE_TS = ROOT / "server" / "plugins" / "watchdog" / "node.ts"

PASS = 0
FAIL = 0


def ok(cond, label, detail=None):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  ✓ %s" % label)
    else:
        FAIL += 1
        print("  ✗ %s" % (label if detail is None else "%s :: %r" % (label, detail)))


def section(title):
    print("\n%s" % title)


def env_fail(reason):
    print("ENV_FAIL: %s" % reason)
    sys.exit(2)


def pick_python():
    venv = ENGINE / ".venv" / "bin" / "python"
    if venv.is_file():
        return str(venv)
    fallback = shutil.which("python3")
    if fallback:
        return fallback
    env_fail("server/engine/.venv/bin/python 与 python3 均缺席（引擎运行面无法探针）")


def main():
    if not NODE_TS.is_file():
        env_fail("server/plugins/watchdog/node.ts 缺席（本仓非预期形态）")
    if not (ENGINE / "client.py").is_file():
        env_fail("server/engine/client.py 缺席（引擎入口不在位）")
    node = shutil.which("node")
    if not node:
        env_fail("node 缺席（守望者宿主半运行面无法装载）")

    # ---------- A 真入口在场探针（拿逐字节原样 stdout） ----------
    section("A 真入口探针：client.py ticket-list {}（只读）")
    py = pick_python()
    # 身份纪律（t261004-26，-0023）：本子用例读的是「真入口实际 stdout 形状」，与调用方
    # 身份无关——继承旋钮/身份走清理单点剥净（先剥后注入；本探针零声明=中性 env）。
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
    from lib_env import clean_narrowing_env
    probe_env = clean_narrowing_env(base=dict(os.environ))
    try:
        proc = subprocess.run(
            [py, "client.py", "ticket-list", json.dumps({})],
            cwd=str(ENGINE), env=probe_env, capture_output=True, text=True, timeout=90,
        )
    except subprocess.TimeoutExpired:
        env_fail("client.py ticket-list 超时 90s（引擎/Temporal 不可达）")
    except OSError as e:
        env_fail("client.py 无法 spawn：%s" % e)
    if proc.returncode != 0:
        env_fail("client.py ticket-list 退出码 %d（引擎/Temporal 不可达）：%s"
                 % (proc.returncode, (proc.stderr or proc.stdout or "")[:300]))
    raw = proc.stdout
    try:
        live_doc = json.loads(raw)
    except ValueError:
        env_fail("client.py ticket-list stdout 不是合法 JSON（引擎/Temporal 不可达形态）：%r"
                 % raw[:200])
    ok(isinstance(live_doc, dict), "A 真入口 stdout 是 JSON 对象", type(live_doc))

    # ---------- B/C/D/E 经 node 装载出货 node.ts 一次跑齐 ----------
    section("B/C/D/E 经实现导出解析路径的真形锁与端到端")
    node_script = r"""
const m = await import(new URL('file://' + process.env.NODE_TS, import.meta.url).href);
const fs = await import('node:fs');
const raw = fs.readFileSync(process.env.RAW_FILE, 'utf8');
const out = { hasParse: typeof m.parseTicketListDoc === 'function' };
if (out.hasParse) {
  out.live = m.parseTicketListDoc(raw);
  out.env_ok = m.parseTicketListDoc('{"result":{"ok":true,"tickets":[{"id":"a"}]}}');
  out.env_err = m.parseTicketListDoc('{"result":{"ok":false,"error":"boom"}}');
  out.bad_json = m.parseTicketListDoc('<html>not json');
  out.empty = m.parseTicketListDoc('');
  out.no_tickets = m.parseTicketListDoc('{"count":1}');
  out.tickets_not_array = m.parseTicketListDoc('{"tickets":"nope"}');
  out.result_null = m.parseTicketListDoc('{"result":null,"tickets":[{"id":"a"}]}');
}
out.reader = await m.makeBoardReader(process.env.REPO)();
console.log(JSON.stringify(out));
"""
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as tf:
        tf.write(raw)
        raw_path = tf.name
    try:
        env_vars = dict(os.environ, NODE_TS=str(NODE_TS), RAW_FILE=raw_path,
                        REPO=str(ROOT))
        nproc = subprocess.run(
            [node, "--input-type=module", "-e", node_script],
            capture_output=True, text=True, timeout=120, env=env_vars,
        )
    except subprocess.TimeoutExpired:
        env_fail("node 装载 node.ts 超时 120s")
    except OSError as e:
        env_fail("node 无法 spawn：%s" % e)
    finally:
        os.unlink(raw_path)  # tmp 回收（L8 纪律）
    if nproc.returncode != 0:
        # 装载失败=实现面坏（不是环境缺）——FAIL 点名，不 ENV_FAIL
        ok(False, "node 装载出货 node.ts 并执行探针脚本",
           (nproc.stderr or nproc.stdout or "")[:400])
        print("\nSUMMARY pass=%d fail=%d env_fail=0 na=0" % (PASS, FAIL))
        sys.exit(1)
    try:
        out = json.loads(nproc.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        ok(False, "node 探针脚本输出可解析", nproc.stdout[:300])
        print("\nSUMMARY pass=%d fail=%d env_fail=0 na=0" % (PASS, FAIL))
        sys.exit(1)

    ok(out.get("hasParse") is True,
       "B 实现导出共享解析路径 parseTicketListDoc（读器与锁同一条出货代码路径）",
       "parseTicketListDoc 未导出（TDD 红：实现未落地）")
    if not out.get("hasParse"):
        print("\nSUMMARY pass=%d fail=%d env_fail=0 na=0" % (PASS, FAIL))
        sys.exit(1)

    live = out.get("live") or {}
    ok(live.get("ok") is True, "B 真入口原样 stdout 过出货解析路径 → ok=true", live)
    rows = live.get("tickets") or []
    ok(len(rows) > 0, "B tickets>0（引擎当前 >200 票）", len(rows))
    ok(all(isinstance(r, dict) and r.get("id") for r in rows),
       "B 每行带 id", rows[:2])
    # 形状契约（真形锁实测钉死，t260929-07 实证）：真入口是**信封形但内层无 ok 键**
    # ——{ok:true,result:{count,tickets}}，旧代码 res.ok!==true 因此永不通过。
    # 内层一旦补出 ok 键（引擎翻契约），本锁有意识翻红而非被容忍静默吞掉。
    ok("result" in live_doc and isinstance(live_doc.get("result"), dict)
       and "ok" not in live_doc["result"],
       "B 形状契约：真文档信封内层 result 无 ok 键（引擎翻契约时本锁有意识翻红）",
       {k: (list(v.keys()) if isinstance(v, dict) else type(v).__name__)
        for k, v in live_doc.items()})

    reader = out.get("reader") or {}
    ok(reader.get("ok") is True,
       "C makeBoardReader(repo)() 端到端 ok=true（A 已证引擎可达，此刻 ok=false=产品红）",
       reader)
    ok(len(reader.get("rows") or []) > 0, "C 读器端到端 rows>0",
       len(reader.get("rows") or []))

    def bad(name, label, require_error=True):
        r = out.get(name) or {}
        good = r.get("ok") is False and isinstance(r.get("error"), str) \
            and (r.get("error") != "" or not require_error)
        ok(good, label, r)

    bad("bad_json", "D 非 JSON stdout → 结构化 ok:false + 带原因（不抛裸异常）")
    bad("empty", "D 空 stdout → 结构化 ok:false")
    bad("no_tickets", "D 缺 tickets → 结构化 ok:false")
    bad("tickets_not_array", "D tickets 非数组 → 结构化 ok:false")
    bad("result_null", "D result 在场但为 null → 结构化 ok:false（不误报引擎不可达）")
    env_err = out.get("env_err") or {}
    ok(env_err.get("ok") is False and "boom" in str(env_err.get("error")),
       "D 信封 ok:false → 透传引擎错误文本", env_err)

    env_ok = out.get("env_ok") or {}
    ok(env_ok.get("ok") is True and (env_ok.get("tickets") or [{}])[0].get("id") == "a",
       "E 信封正形 {result:{ok:true,tickets}} 仍被接受（双形状不丢旧契约）", env_ok)

    print("\nSUMMARY pass=%d fail=%d env_fail=0 na=0" % (PASS, FAIL))
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
