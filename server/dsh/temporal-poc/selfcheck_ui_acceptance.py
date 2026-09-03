#!/usr/bin/env python3
"""UI 验收机制自测（t260828-09）：口径 + 证据闸 + 截图通道桩跑。

零 Temporal server / 零模型。覆盖：
  A. is_ui_write_set 口径：命中各前缀 / 精确文件（app/index.html）/ 未命中 /
     空集与 None / 畸形输入（None 元素、非字符串、首尾空白）；
  B. merge_check UI 证据闸（纯机械段，不走 Temporal）：构造 UI 票 write_set +
     空 screenshots 目录 → 检查项红且文案含处置指引；有 png → 绿。
     实现方式：import merge_check 所在模块直接调 activity 函数会拉起 Temporal
     装饰器依赖，故本自测对闸段做**逻辑等价**断言——调 shared.is_ui_write_set
     判票 + glob png 计数，与 agent_activities.merge_check 3.6 段同一口径；
     再用源码文本断言锁死闸确实挂在 merge_check 内（防漂移）；
  C. prepare_ui_evidence 桩跑：SUYOU_UI_CAPTURE_STUB=1 环境下直接调 activity
     函数（activity.defn 装饰过的函数本体可直接调用），断言两张 png 落盘、
     shot_lines 带 mtime；畸形输入：脚本不存在 → ok=False 回执不抛；
  D. capture.mjs --selftest 干跑（子进程，不起浏览器）；--bogus / 缺 --out
     畸形参数 → 非零退出；
  E. dev_lane 接线源码断言：UI_EVIDENCE_PATCH_ID 布尔门、prepare_ui_evidence
     插在 integration_review 之前（implement 分支内）、MergeCheckArgs 传 write_set。

退出码 0=全绿；非 0=有红灯（stderr 打明细）。
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

POC = Path(__file__).resolve().parent
REPO = POC.parent.parent.parent          # 仓库根（worktree 根）
sys.path.insert(0, str(POC))

from shared import (  # noqa: E402
    UI_EVIDENCE_DIR,
    UiEvidenceArgs,
    is_ui_write_set,
)

PASS = 0
FAIL = 0
FAILURES = []


def ok(cond: bool, label: str) -> None:
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  ok  %s" % label)
    else:
        FAIL += 1
        FAILURES.append(label)
        print("  RED %s" % label, file=sys.stderr)


def section(name: str) -> None:
    print("\n== %s ==" % name)


# ---------- A. is_ui_write_set 口径 ----------
section("A is_ui_write_set 口径")
ok(is_ui_write_set(["server/dsh/workbench/src/client/App.tsx"]), "命中 workbench src/client")
ok(is_ui_write_set(["server/dsh/workbench/lib/workbench.js"]), "命中 workbench lib 产物")
ok(is_ui_write_set(["server/dsh/providers/src/client/a.ts"]), "命中 providers src/client")
ok(is_ui_write_set(["app/src/main.ts"]), "命中 app/src")
ok(is_ui_write_set(["app/index.html"]), "命中 app/index.html（精确文件）")
ok(is_ui_write_set(["app/src"]), "命中目录前缀本身（无尾斜杠）")
ok(is_ui_write_set(["server/dsh/temporal-poc/dev_lane.py",
                    "server/dsh/workbench/lib/x.js"]), "混合写集，任一命中即 UI 票")
ok(not is_ui_write_set(["server/dsh/workbench/src/server/main.py"]), "workbench 服务端不算 UI")
ok(not is_ui_write_set(["server/dsh/temporal-poc/shared.py"]), "纯引擎改动不算 UI")
ok(not is_ui_write_set([]), "空写集 → False")
ok(not is_ui_write_set(None), "None → False")
ok(not is_ui_write_set([None, 123, True]), "非字符串元素全忽略 → False")
ok(is_ui_write_set(["  app/src/main.ts  "]), "首尾空白 strip 后命中")

# ---------- B. merge_check UI 证据闸（口径等价断言） ----------
section("B merge_check UI 证据闸")
with tempfile.TemporaryDirectory() as td:
    wt = Path(td)
    shots = wt / UI_EVIDENCE_DIR
    # UI 票 + 无截图目录 → 红（等价 merge_check 3.6 段判定逻辑）
    is_ui = is_ui_write_set(["app/src/main.ts"])
    pngs = sorted(shots.glob("*.png")) if shots.is_dir() else []
    ok(is_ui and not pngs, "UI 票 + 空 screenshots → 闸红条件成立")
    # 落一张 png → 绿
    shots.mkdir(parents=True)
    (shots / "console-default.png").write_bytes(b"png")
    pngs = sorted(shots.glob("*.png"))
    ok(bool(pngs), "有 png → 闸绿条件成立")
    # 非 UI 票 → 不出项
    ok(not is_ui_write_set(["server/dsh/temporal-poc/x.py"]), "非 UI 票 → 闸不出项")
# 源码文本断言：闸确实挂在 merge_check 内且给处置指引（防后续挪位/删文案漂移）
src = (POC / "agent_activities.py").read_text("utf-8")
ok("is_ui_write_set(args.write_set)" in src, "merge_check 内调 is_ui_write_set（源码锁）")
ok("ui-check/capture.mjs" in src and "UI_EVIDENCE_DIR" in src,
   "红灯文案带 capture.mjs 处置指引（源码锁）")
# merge_check 自身可编译导入（register 路径无残缺）
import agent_activities  # noqa: E402
ok(hasattr(agent_activities, "prepare_ui_evidence"), "prepare_ui_evidence 已定义")
ok(agent_activities.prepare_ui_evidence in agent_activities.ALL_AGENT_ACTIVITIES,
   "prepare_ui_evidence 已进 worker 注册清单")

# ---------- C. prepare_ui_evidence 桩跑 ----------
section("C prepare_ui_evidence 桩跑（SUYOU_UI_CAPTURE_STUB=1）")
with tempfile.TemporaryDirectory() as td, tempfile.TemporaryDirectory() as ed:
    wt = Path(td)
    os.environ["SUYOU_UI_CAPTURE_STUB"] = "1"
    os.environ["SUYOU_EVIDENCE_DIR"] = ed  # 归档指向临时目录（t260829-02），不污染真主树
    try:
        res = asyncio.run(agent_activities.prepare_ui_evidence(
            UiEvidenceArgs(ticket_id="t-selftest", worktree=str(wt))))
    finally:
        os.environ.pop("SUYOU_UI_CAPTURE_STUB", None)
        os.environ.pop("SUYOU_EVIDENCE_DIR", None)
    ok(res.ok and len(res.shots) == 2, "桩跑 ok 且两张截图（%s）" % res.shots)
    ok((wt / UI_EVIDENCE_DIR / "console-default.png").is_file() and
       (wt / UI_EVIDENCE_DIR / "console-chat.png").is_file(), "png 落盘 <worktree>/%s" % UI_EVIDENCE_DIR)
    ok(len(res.shot_lines) == 2 and all("（" in ln for ln in res.shot_lines),
       "shot_lines 带 mtime：%s" % res.shot_lines)
    # 幂等：再跑一遍覆盖写不炸
    os.environ["SUYOU_UI_CAPTURE_STUB"] = "1"
    os.environ["SUYOU_EVIDENCE_DIR"] = ed
    try:
        res2 = asyncio.run(agent_activities.prepare_ui_evidence(
            UiEvidenceArgs(ticket_id="t-selftest", worktree=str(wt))))
    finally:
        os.environ.pop("SUYOU_UI_CAPTURE_STUB", None)
    ok(res2.ok, "桩跑幂等重入 ok")

# 畸形输入：capture.mjs 不存在（主树路径 patch 到空临时目录模拟）→ ok=False 回执不抛
with tempfile.TemporaryDirectory() as td:
    saved = agent_activities.REPO_ROOT
    agent_activities.REPO_ROOT = Path(td)  # 主树无 ui-check/capture.mjs（t260829-02：脚本查主树）
    try:
        res = asyncio.run(agent_activities.prepare_ui_evidence(
            UiEvidenceArgs(ticket_id="t-selftest", worktree=td)))
    finally:
        agent_activities.REPO_ROOT = saved
    ok(not res.ok and "不存在" in (res.detail or ""), "capture.mjs 不存在 → ok=False 回执（不抛）")

# ---------- D. capture.mjs selftest / 畸形参数 ----------
section("D capture.mjs --selftest 与畸形参数")

def _find_capture_dir():
    """选可跑 selftest 的 ui-check 目录：playwright-core 的 node_modules 只在装过的
    树里有（t260829-01 根因：泳道 checkout 没有也不装）。本树没有 → 落主树
    （git common-dir 反推），与 prepare_ui_evidence 的主树化口径同源。"""
    dirs = [REPO / "server" / "dsh" / "ui-check"]
    try:
        gd = subprocess.run(
            ["git", "rev-parse", "--path-format=absolute", "--git-common-dir"],
            capture_output=True, text=True, timeout=10, cwd=str(POC)).stdout.strip()
        if gd:
            dirs.append(Path(gd).parent / "server" / "dsh" / "ui-check")
    except Exception:
        pass
    with_dep = [d for d in dirs if (d / "capture.mjs").is_file()
                and (d / "node_modules" / "playwright-core").exists()]
    plain = [d for d in dirs if (d / "capture.mjs").is_file()]
    return (with_dep or plain or [None])[0]

cap_dir = _find_capture_dir()
cap = cap_dir / "capture.mjs" if cap_dir else None
ok(cap is not None and cap.is_file(), "capture.mjs 可寻址（%s）" % (cap_dir or "无"))
if cap is not None and cap.is_file():
    has_dep = (cap_dir / "node_modules" / "playwright-core").exists()
    ok(has_dep, "playwright-core 依赖在位（%s）" % cap_dir)
    r = subprocess.run(["node", str(cap), "--selftest", "--out", tempfile.mkdtemp()],
                       capture_output=True, text=True, timeout=60, cwd=str(cap_dir))
    ok(r.returncode == 0, "--selftest 退出 0（依赖在位）：%s" % (r.stdout or r.stderr).strip()[:80])
    r = subprocess.run(["node", str(cap), "--bogus"], capture_output=True, text=True, timeout=60)
    ok(r.returncode != 0, "未知参数 → 非零退出")
    r = subprocess.run(["node", str(cap)], capture_output=True, text=True, timeout=60)
    ok(r.returncode != 0, "缺 --out → 非零退出")
    r = subprocess.run(["node", str(cap), "--url", "", "--out", str(cap)],
                       capture_output=True, text=True, timeout=60)
    ok(r.returncode != 0, "--out 指向文件（非目录）→ 非零退出")

# ---------- E. dev_lane 接线源码断言 ----------
section("E dev_lane 接线")
dl = (POC / "dev_lane.py").read_text("utf-8")
ok("UI_EVIDENCE_PATCH_ID" in dl and "workflow.patched(UI_EVIDENCE_PATCH_ID)" in dl,
   "UI 证据包 workflow.patched 布尔门")
ok("prepare_ui_evidence" in dl and "UI_EVIDENCE_TO" in dl, "新步 + 独立超时在位")
# 超时叠超时防回归（review 意见 1）：activity 超时必须明显大于子进程超时，
# 否则 Temporal 先杀 activity，子进程超时回收路径走不到
import dev_lane  # noqa: E402
ok(dev_lane.UI_EVIDENCE_TO.total_seconds() >=
   agent_activities.UI_CAPTURE_TIMEOUT_SEC + 30,
   "UI_EVIDENCE_TO(%ss) > 子进程超时(%ss)+30s"
   % (dev_lane.UI_EVIDENCE_TO.total_seconds(), agent_activities.UI_CAPTURE_TIMEOUT_SEC))
ok("write_set=list(self.meta.get(\"write_set\") or [])" in dl,
   "merge_check 调用点传 write_set")
ok('is_ui_write_set(list(self.meta.get("write_set") or []))' in dl,
   "仅 UI 票执行 prepare_ui_evidence")
ok('target in ("suggest_next", "ui_evidence")' in dl,
   "ui_evidence 非主链步，rework 拒绝守卫在位")
ok("审读必看" in dl and "无截图证据=打回" in dl.replace("「", "").replace("」", ""),
   "审读 prompt 注入截图清单")
ok("【UI 截图证据缺失】" in dl, "截图失败也注入缺失提示（审读按打回处理）")

# ---------- F. 证据归档口径（t260829-02） ----------
section("F 证据归档（泳道 screenshots → 主树 .suyou/evidence/<ticket>）")
with tempfile.TemporaryDirectory() as td, tempfile.TemporaryDirectory() as ed:
    wt = Path(td)
    os.environ["SUYOU_UI_CAPTURE_STUB"] = "1"
    os.environ["SUYOU_EVIDENCE_DIR"] = ed  # 归档基目录指向临时目录（防污染真主树）
    try:
        res = asyncio.run(agent_activities.prepare_ui_evidence(
            UiEvidenceArgs(ticket_id="t-selftest", worktree=str(wt))))
    finally:
        os.environ.pop("SUYOU_UI_CAPTURE_STUB", None)
        os.environ.pop("SUYOU_EVIDENCE_DIR", None)
    ev = Path(ed) / "t-selftest"
    ok(res.ok, "桩跑 ok")
    for n in res.shots:
        src = wt / UI_EVIDENCE_DIR / n
        dst = ev / n
        ok(dst.is_file() and dst.read_bytes() == src.read_bytes(),
           "归档 %s 与泳道截图同字节" % n)
    ok("已归档" in (res.detail or ""), "detail 带归档留痕：%s" % (res.detail or "")[-60:])
    # 归档重入覆盖不炸（copy2 语义）
    os.environ["SUYOU_UI_CAPTURE_STUB"] = "1"
    os.environ["SUYOU_EVIDENCE_DIR"] = ed
    try:
        res2 = asyncio.run(agent_activities.prepare_ui_evidence(
            UiEvidenceArgs(ticket_id="t-selftest", worktree=str(wt))))
    finally:
        os.environ.pop("SUYOU_UI_CAPTURE_STUB", None)
        os.environ.pop("SUYOU_EVIDENCE_DIR", None)
    ok(res2.ok, "归档幂等重入 ok")
    # 畸形：归档目标路径被普通文件占位（mkdir 失败）→ ok 仍 True（软失败不翻），detail 带失败说明
    import shutil as _shutil
    blocked = Path(ed) / "t-selftest"
    _shutil.rmtree(blocked)           # 拆掉目录
    blocked.write_text("占用")        # 同名普通文件占位 → dst.mkdir 抛 OSError
    os.environ["SUYOU_UI_CAPTURE_STUB"] = "1"
    os.environ["SUYOU_EVIDENCE_DIR"] = ed
    try:
        res3 = asyncio.run(agent_activities.prepare_ui_evidence(
            UiEvidenceArgs(ticket_id="t-selftest", worktree=str(wt))))
    finally:
        os.environ.pop("SUYOU_UI_CAPTURE_STUB", None)
        os.environ.pop("SUYOU_EVIDENCE_DIR", None)
        blocked.unlink()
    ok(res3.ok and "归档失败" in (res3.detail or ""), "归档失败 → ok 不翻 + detail 留痕")
# 源码锁：脚本固定主树（capture 主树化，t260829-01 软失败根因）
src = (POC / "agent_activities.py").read_text("utf-8")
ok('script = REPO_ROOT / "server" / "dsh" / "ui-check" / "capture.mjs"' in src,
   "capture 脚本路径固定主树 REPO_ROOT（源码锁）")
ok("wt / \"server\" / \"dsh\" / \"ui-check\"" not in src,
   "泳道拼 capture 路径的旧写法已清除（源码锁）")

# ---------- G. capture 输出仍落泳道（口径不变） ----------
section("G capture 输出目录口径")
ok("--out" in src and "shots_dir" in src and "UI_EVIDENCE_DIR" in src,
   "--out=泳道 screenshots 口径保留（证据闸/审读仍看泳道）")

# ---------- H. workbench 宿主半冒烟（node 直测 TS：evidence 白名单 + next-hint） ----------
# 写集约束：workbench/smoke/*.mjs 不在本票写集，冒烟脚本由本自测生成到临时目录再
# node 直跑（node ≥22.18 原生 type-stripping 直接 import .ts，smoke/epic-precache.mjs
# 同款先例）。覆盖：图片端点文件名白名单（../ 穿越/非 png/大写后缀）+ readPrecacheHint
# 命中/state_key 漂移不命中 + dismissPrecache 删除/幂等/防穿/备份。
section("H workbench 宿主半冒烟（evidence 白名单 + next-hint 两态）")
NODE_SNIPPET = r"""
import { mkdtemp, writeFile, mkdir, readFile, readdir, rm } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { readPrecacheHint, stateKeyFromRows, dismissPrecache } from '<WB>/src/host/epic-next.ts'
import { isEvidenceFileName } from '<WB>/src/host/epics.ts'

let failed = 0
const ok = (cond, label) => { console.log((cond ? '  ok ' : '  FAIL ') + label); if (!cond) failed++ }

// 1) evidence 文件名白名单（node.ts handleTicketEvidence 同口径纯函数）
ok(isEvidenceFileName('console-default.png'), '白名单内 png 通过')
ok(isEvidenceFileName('a.b-c_d.png'), '多点/连字符/下划线 png 通过')
ok(!isEvidenceFileName('../evil.png'), '../ 穿越拒绝')
ok(!isEvidenceFileName('sub/evil.png'), '/ 穿越拒绝')
ok(!isEvidenceFileName('shot.txt'), '非 png 拒绝')
ok(!isEvidenceFileName('shot.PNG'), '大写后缀拒绝（口径=严格 .png）')
ok(!isEvidenceFileName(''), '空文件名拒绝')

// 2) readPrecacheHint 两态（state_key 现算比对）
const cacheDir = await mkdtemp(join(tmpdir(), 'wb-hint-'))
const rows = [{ id: 't-a', closed: true }, { id: 't-b', closed: false }]
const sk = stateKeyFromRows(rows, '')
const wfIds = ['dev-lane']
await mkdir(join(cacheDir, 'ep-x'), { recursive: true })
await writeFile(join(cacheDir, 'ep-x', 'pre.json'), JSON.stringify({
  epic: 'ep-x', state_key: sk,
  suggestion: { status: 'ok', workflow: 'dev-lane', title: '下一单', body: 'b', rationale: 'r' },
}), 'utf8')
const hit = await readPrecacheHint(cacheDir, 'ep-x', sk, wfIds)
ok(hit !== null && hit.status === 'ok' && hit.title === '下一单' && hit.rationale === 'r',
  'state_key 对齐 → hint 命中')
const sk2 = stateKeyFromRows([{ id: 't-a', closed: true }, { id: 't-b', closed: true }], '')
ok(await readPrecacheHint(cacheDir, 'ep-x', sk2, wfIds) === null, 'state_key 漂移 → 未命中')
ok(await readPrecacheHint(cacheDir, 'ep-x', '', wfIds) === null, '空 state_key → 未命中')
ok(await readPrecacheHint(cacheDir, 'ep-y', sk, wfIds) === null, '无缓存代号 → 未命中')
await rm(join(cacheDir, 'ep-x', 'pre.json'))
await writeFile(join(cacheDir, 'ep-x', 'pre.json'), '{bad json', 'utf8')
ok(await readPrecacheHint(cacheDir, 'ep-x', sk, wfIds) === null, '坏 JSON → 当未命中')

// 3) dismissPrecache：删除 + /tmp 备份 + 幂等 + 防穿
await mkdir(join(cacheDir, 'ep-d'), { recursive: true })
await writeFile(join(cacheDir, 'ep-d', 'pre.json'), '{"epic":"ep-d"}', 'utf8')
const d1 = await dismissPrecache(cacheDir, 'ep-d')
ok(d1.ok === true, 'dismiss 成功')
let gone = false
try { await readFile(join(cacheDir, 'ep-d', 'pre.json')) } catch { gone = true }
ok(gone, 'pre.json 已删除')
const backups = await readdir('/tmp/epic-next-backup').catch(() => [])
ok(backups.some((f) => f.startsWith('ep-d-')), '删除前已备份 /tmp/epic-next-backup')
const d2 = await dismissPrecache(cacheDir, 'ep-d')
ok(d2.ok === true, '重复 dismiss 幂等 ok')
const d3 = await dismissPrecache(cacheDir, '../evil')
ok(d3.ok === false && d3.status === 400, '非法代号 400 防穿')
const d4 = await dismissPrecache(cacheDir, 'no-such-code')
ok(d4.ok === true, '不存在的代号也幂等 ok')
console.log(failed === 0 ? 'NODE_SMOKE_GREEN' : 'NODE_SMOKE_RED')
process.exit(failed === 0 ? 0 : 1)
""".replace("<WB>", str(REPO / "server" / "dsh" / "workbench"))
with tempfile.TemporaryDirectory() as td:
    mjs = Path(td) / "_hint_smoke.mjs"
    mjs.write_text(NODE_SNIPPET, "utf8")
    r = subprocess.run(["node", str(mjs)], capture_output=True, text=True, timeout=120)
    print(r.stdout.strip())
    ok(r.returncode == 0 and "NODE_SMOKE_GREEN" in r.stdout,
       "workbench 宿主半冒烟全绿（node 直测 TS）")
    if r.returncode != 0:
        FAILURES.append("workbench 宿主半冒烟: %s" % (r.stderr or r.stdout)[-300:])

# 汇总
print("\n%d 绿 / %d 红" % (PASS, FAIL))
if FAILURES:
    print("红灯：", *FAILURES, sep="\n  - ", file=sys.stderr)
    sys.exit(1)
