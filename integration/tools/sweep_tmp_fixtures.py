#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""sweep_tmp_fixtures — 一次性、可复核的「测试夹具临时物料」清扫器（宿主令 260926／260927）。

背景：`$TMPDIR` 顶层实测 407,294 个目录，其中 401,578 个 >6 小时未动（98.6%）——大头是
各测试面 `mkdtemp` 出来的夹具（`integ-e2e-fixture-*` 1,086 个 / ~391GB、`t260907-06-ut-*`
1.7 万、`sandbar-agent-presets-*` 2 万……）。生产者侧已逐个修（见同日各票：注册表 +
退出钩子 + 拆台回收），本脚本是**存量止血**与「SIGKILL 类终态」的兜底网。

判据（两条同时满足才删，缺一不删）：
  ① 顶层条目名以**白名单前缀**开头（TMP_FIXTURE_PREFIXES；白名单之外一律不碰——
     宿主 temp 目录里可能有别的程序的东西）；
  ② 该条目 `mtime` 距今 ≥ `--max-age-h`（缺省 6 小时；年龄不足的一律不碰，可能在跑）。
另按**条目类型**分流（260927 全族清扫新增）：
  - 真目录 → `rmtree`；**常规文件** → `unlink`（锁档 `*-integ-run-*.lock`、影子
    `sandbar-admin-log-*.log`、凭据副本 `sandbar-credentials-*.yaml` 都是**文件**族，
    上一轮「只碰真目录」把它们整族漏掉了）；
  - 符号链接 / FIFO / socket 等一律跳过（`rmtree` 跟符号链接会删错东西）——逐条点名；
  - **在用即不动**（260927 新增的第三条文件族判据）：删文件前先试 `flock(LOCK_EX|LOCK_NB)`
    ——抢得到 = 没人持有 = 可删；抢不到 = 有活进程正握着这把锁 = **保留并点名**
    （绝不删活锁档；无 `fcntl` 的平台跳过该判据并留痕）；
  - **活载体即不动**（261001 新增，自递归风暴的机械网）：越龄白名单条目里若还有**活进程**
    的 cwd 落在其中，该条目**保留、逐条点名**；`--kill-carriers` 才先收进程再删。
    判据按 **cwd** 判而不是按命令行（风暴里那些进程的 args 是相对路径，按名字杀一律打偏）；
    探测面（`pgrep`/`lsof`）缺席时**具名留痕**，绝不当「没有载体」——「扫不到」与「没有」
    是两件事，混同会给出「机器干净」的假结论。
  - `EXCLUDED_PREFIXES` 里的族**永不参与**（别的程序的/别的项目的，如
    `com.google.Chrome.*`；以及 dsh 运行时自己的 spill 目录）——判据里**排除优先**，
    且在报告里逐族计数可见（不静默、也不误删）。

安全：默认 dry-run（只报数不删），`--apply` 才删；`--apply` 的年龄闸有 1 小时硬地板
（拒绝更激进的取值）。日志一行一动作，失败逐条点名。

Family declaration is DATA (t261029-78): each `DECLARED_FAMILIES` record carries the
prefix, the entry kind, the producing project, the reason, the producer file:line, the
sample measured for this ticket, and the ticket that declared it. The effective whitelist
= the engine-mirrored core `TMP_FIXTURE_PREFIXES` (unchanged; the drift lock still pins it)
+ the declared extension. `declaration_errors()` is fail-closed on that data itself: an
empty field, a collision with `EXCLUDED_PREFIXES`, a prefix shadowed by a core prefix, or
a duplicate is a NAMED refusal — a half-written record is exactly the gap the next sweep
would fall into.

The receipt is PER FAMILY (t261029-78): dry-run and `--apply` share ONE printer
(`family_receipt()`), so both modes print the same lines — count / d,f / live / oldest /
est≈ / swept (dry-run "would-sweep", apply the real count) / freed≈ / kept: live·lock·
carrier·failed plus the names and reasons of what was kept. A declared family adds `why:`
(reason) and `who:` (project + producer + declaring ticket + measured sample). `--json`
carries the same rows as `per_family`. A swept family therefore stays visible on the
applied receipt instead of collapsing into one total.

Known gap, named on every run rather than left silent: the engine water line
(`server/engine/inspection_lane_watchdog.py::TMP_FIXTURE_PREFIXES`) is drift-locked to the
core list in this file, and the families added by t261029-78 live only on the sweeper side
(server/ is outside this lane's write set). The `ENGINE MIRROR GAP:` line names the
families this tool reclaims but the alarm face does not count yet; closing it needs its own
ticket on the server/ side (not this one).

用法（cwd=仓库根）：
  python3 integration/tools/sweep_tmp_fixtures.py                  # dry-run：各前缀命中数 + 占用估算
  python3 integration/tools/sweep_tmp_fixtures.py --json           # 机器可读
  nohup python3 integration/tools/sweep_tmp_fixtures.py --apply \
        > /tmp/sweep-tmp-fixtures.log 2>&1 &                       # 真删（宿主已明确要清）

摘要行（两种模式同形，dry-run 带 DRY-RUN 前缀）：
  swept N (dirs D / files F) | kept M live | failed X | locks kept L | freed≈Y
其中 `freed≈Y` 是**估算**（目录族：每前缀最多 `--sample` 个实测平均 × 命中数；文件族：
实删文件的实际字节累计）——估算值只进报告，**绝不参与「删不删」的判据**。
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from collections import namedtuple

#: 白名单里的条目形态（`kind` = "dir" | "file"）
FixtureEntry = namedtuple("FixtureEntry", "name mtime kind")

#: ONE declaration of the temp-fixture families (t261029-81): `tmp_fixture_families.json`,
#: next to this file. Both consumers read it - this sweeper (which deletes) and the engine
#: alarm face (`server/engine/inspection_lane_watchdog.py`, which counts the water level) -
#: and neither keeps a prefix list of its own. A family cannot be declared for sweeping on
#: one side and stay invisible on the other, because there is no second list to write it
#: into. Adding a family = appending one record to the file.
#:
#: Dependency direction (why this cannot form an import cycle): the file belongs to this
#: directory. The sweeper is the deleting side, so its declaration IS the delete surface;
#: the engine only reads the same file by path. A data file imports nothing, and this script
#: never imports the engine (`import`s below are standard library only - the sweeper must run
#: on a machine where the engine does not install), so the seam carries no import edge in
#: either direction.
#:
#: Absence is fail-closed, never "no families": a missing or malformed file returns no
#: families plus named errors, and `run()` refuses to sweep a surface it could not read (the
#: engine side names the same state as `absent`/`malformed` and refuses to judge the water
#: level).
DECLARATION_FILENAME = "tmp_fixture_families.json"
DECLARATION_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), DECLARATION_FILENAME)

#: One declared family (t261029-78 shape, kept). Every field is carried by the receipt, so no
#: reader has to guess why an entry is sweepable:
#:   prefix    the top-level name prefix the producer mints (this IS the safety property)
#:   kind      what the producer leaves behind: "dir" | "file" | "dir+file"
#:   project   who mints it: "sandbar" (this repo), a sibling project key, or "unknown"
#:   reason    short answer to "why is this entry ours to reclaim?"
#:   producer  producer file:line inside that project ("" = no owner recorded: rendered as
#:             owner=unknown, never guessed)
#:   measured  the sample that put this family on the list ("" = not measured)
#:   added_by  the ticket or sweep round that declared it
FixtureFamily = namedtuple(
    "FixtureFamily", "prefix kind project reason producer measured added_by")
#: The record fields, in receipt order (the data file uses the same names).
FAMILY_FIELDS = FixtureFamily._fields
#: Allowed `kind` values (what the producer leaves behind).
FAMILY_KINDS = ("dir", "file", "dir+file")


def load_families(path=None):
    """Read the family declaration file -> (families, status dict, structural errors).

    Structural only: a record must be an object with a non-empty `prefix`, and the file must
    hold at least one record. Semantic rules (kind, provenance, collisions, unreachable
    prefixes) are `declaration_errors()`.
    """
    p = path or DECLARATION_PATH
    status = {"path": p, "status": "absent", "detail": ""}
    try:
        with open(p, "r", encoding="utf-8") as fh:
            raw = fh.read()
    except FileNotFoundError:
        status["detail"] = "the declaration file is absent"
        return (), status, ["%s: absent (the swept surface cannot be read)" % p]
    except OSError as exc:
        status["status"] = "malformed"
        status["detail"] = "cannot read the declaration: %s: %s" % (type(exc).__name__, exc)
        return (), status, [status["detail"]]
    try:
        data = json.loads(raw)
    except ValueError as exc:
        status["status"] = "malformed"
        status["detail"] = "the declaration is not valid JSON: %s" % exc
        return (), status, [status["detail"]]
    records = data.get("families") if isinstance(data, dict) else None
    if not isinstance(records, list):
        status["status"] = "malformed"
        status["detail"] = "the declaration carries no `families` list"
        return (), status, [status["detail"]]
    families, errors = [], []
    for i, rec in enumerate(records):
        if not isinstance(rec, dict):
            errors.append("family #%d is not an object" % i)
            continue
        values = {k: str(rec.get(k) or "").strip() for k in FAMILY_FIELDS}
        if not values["prefix"]:
            errors.append("family #%d has no prefix" % i)
            continue
        families.append(FixtureFamily(**values))
    if not families and not errors:
        errors.append("the declaration lists no family (an empty surface would sweep nothing "
                      "and say nothing)")
    status["status"] = "malformed" if errors else "loaded"
    if errors:
        status["detail"] = "; ".join(errors[:8])
    return tuple(families), status, errors


#: The declared families, the declaration status (path/loaded|absent|malformed/detail) and the
#: structural errors (empty tuple = usable). Read once at import: a running sweep must not see
#: its delete surface change, and a caller that needs another file calls `load_families(path)`.
FAMILIES, DECLARATION, DECLARATION_ERRORS = load_families()
#: The prefix gate: every family the sweeper may delete, in attribution order (the first
#: matching prefix wins). Derived from the declaration - never written by hand here.
TMP_FIXTURE_PREFIXES = tuple(f.prefix for f in FAMILIES)

#: **明确排除**的族：判据里排除优先（连白名单计数都不进），永不删——逐条给理由，
#: 因为「不碰」本身也得是可复核的判定，而不是「恰好没写进白名单」的偶然：
EXCLUDED_PREFIXES = (
    "com.google.Chrome.",     # Chrome 自己的 profile 临时目录（宿主浏览器的东西）
    "com.apple.",             # 系统服务（triald / tipsd / avconferenced…）
    "BlobRegistryFiles",      # 系统/其它进程
    "playwright",             # 浏览器 profile / artifacts（不是本仓夹具族）
    "TemporaryItems", "TemporaryDirectory.",
    "vscode-git-",            # 编辑器 socket
    "docker_cli_",            # docker CLI socket
    "dsh-subprocess-",        # **dsh 运行时自己的 spill 目录**：@deepseek-ai/dsh-subprocess-local
                              # 的 `lib/runner-launch-*.js:683`（`defaultSpillDir ??=
                              # mkdtempSync(join(tmpdir(), "dsh-subprocess-"))`）。260926 普查把它
                              # 归成「本仓 dsh 子进程探针族」——**归因是错的**（本仓 grep 零命中）；
                              # 删活会话的 spill 目录 = 弄坏在飞的 agent 子进程，一律不碰。
    "dsh-spill-",             # 同族（dsh 侧的 spill 目录）
    "tmp",                    # BSD `mktemp` 缺省模板（`tmpXXXXXXXX`）：归因不到本仓，不碰
)

#: One declared family (t261029-78). Fields, all printed on the receipt and carried by
#: `--json`, so no reader has to guess why an entry is sweepable:
#:   prefix    the top-level name prefix the producer mints (this IS the safety property)
#:   kind      what the producer leaves behind: "dir" | "file" | "dir+file"
#:   project   who mints it: "sandbar" (this repo) or the sibling project key
#:   reason    short answer to "why is this entry ours to reclaim?"
#:   producer  producer file:line inside that project (repository-relative; "" = unknown)
#:   measured  the sample that put this family on the list (host temp dir, 2026-10-29)
#:   added_by  the ticket that declared it (so the evidence can be re-read)
FixtureFamily = namedtuple(
    "FixtureFamily", "prefix kind project reason producer measured added_by")

#: The declared families (t261029-78's name, t261029-81's single source). There is no core
#: list / extension split any more: that split was the structure in which one side could hold a
#: family the other never saw, so both sides now derive from the same records.
DECLARED_FAMILIES = FAMILIES
DECLARED_PREFIXES = TMP_FIXTURE_PREFIXES
#: Declared family by prefix (receipt lookup).
DECLARED_BY_PREFIX = {f.prefix: f for f in FAMILIES}
#: The effective default whitelist. It equals the declaration by construction (kept as its own
#: name because the CLI, the receipt and the pre-existing scenario cases read it).
SWEEP_PREFIXES = TMP_FIXTURE_PREFIXES


def families_outside_engine_mirror():
    """Families the alarm face cannot count - none by construction (t261029-81).

    Before t261029-81 this returned the declared families that the engine's own tuple did not
    list, i.e. the "swept but never alarmed" gap of t261029-78. Both consumers now read the
    same declaration file, so the swept surface and the counted surface are one list; a
    non-empty answer here would mean somebody re-introduced a copy (the drift lock in
    server/engine/tests/test_t260926_tmp_fixture_water.py bites on that). A failing READ on the
    alarm side is named by the alarm itself (`status=absent`/`malformed`), not here.
    """
    return ()


def declaration_errors(families=None, excluded=None):
    """Named defects in the family declaration (pure; [] = clean).

    A record with a missing field is a trap, not a style issue: the family is then swept with
    no answer to "why", or never swept at all. An unreachable prefix is the same hole seen from
    the other side (declared, but an earlier prefix claims every entry). Every defect is
    returned as a string, so the caller refuses with the whole list rather than the first one.

    `producer`/`measured` may be empty: the 260926/260927 census never recorded an owner for
    several families, and inventing one would be worse than the explicit `owner=unknown` the
    receipt already prints. `reason` may not be empty - that is the field that says why the
    family is ours to reclaim.
    """
    fams = FAMILIES if families is None else tuple(families)
    excl = EXCLUDED_PREFIXES if excluded is None else tuple(excluded)
    errs = list(DECLARATION_ERRORS) if families is None else []
    # Duplicates are judged inside the list being validated. Reachability is judged against
    # every EARLIER prefix: the ones already visited here, plus the shipped declaration when a
    # caller passes its own list (a validator probe) - a candidate that the live list shadows
    # would never own an entry either.
    shipped = [f.prefix for f in FAMILIES] if families is not None else []
    seen = []
    for f in fams:
        if not f.prefix:
            errs.append("empty prefix")
            continue
        if f.prefix in seen:
            errs.append("%s: declared twice" % f.prefix)
        for field in ("kind", "project", "reason", "added_by"):
            if not str(getattr(f, field) or "").strip():
                errs.append("%s: empty %s" % (f.prefix, field))
        if f.kind and f.kind not in FAMILY_KINDS:
            errs.append("%s: unknown kind %r (want %s)"
                        % (f.prefix, f.kind, " | ".join(FAMILY_KINDS)))
        hit = next((x for x in excl if f.prefix.startswith(x)), "")
        if hit:
            errs.append("%s: collides with EXCLUDED_PREFIXES %r (excluded must win)"
                        % (f.prefix, hit))
        shadow = next((s for s in (shipped + seen)
                       if s != f.prefix and f.prefix.startswith(s)), "")
        if shadow:
            errs.append("%s: shadowed by the earlier prefix %r (every entry would be "
                        "attributed to it, so this family would never own one)"
                        % (f.prefix, shadow))
        seen.append(f.prefix)
    if not fams:
        errs.append("the declaration lists no family")
    return errs


DEFAULT_MAX_AGE_H = 6.0
DEFAULT_SAMPLE = 10
DEFAULT_SAMPLE_BUDGET_S = 8.0
#: --apply 的年龄硬地板（小时）：比这更激进的取值一律拒（正在跑的夹具必须活着）
APPLY_MIN_AGE_H = 1.0
#: 报告里逐条点名的上限（失败/跳过/在册锁档各自截断，但计数不截断）
NAMED_CAP = 40
#: How many kept-entry names one family's receipt detail line carries (the counts above it
#: are never truncated - only the printed names are).
RECEIPT_KEPT_CAP = 5


def human(n: float) -> str:
    """字节 → 人读（B/K/M/G/T，一位小数）。"""
    v = float(n)
    for unit in ("B", "K", "M", "G", "T", "P"):
        if v < 1024 or unit == "P":
            return ("%dB" % int(v)) if unit == "B" else ("%.1f%s" % (v, unit))
        v /= 1024.0
    return "%.1fP" % v


def age_h(now: float, mtime: float) -> float:
    return max(0.0, (now - mtime) / 3600.0)


def match_prefix(name: str, prefixes) -> str:
    """名称命中哪个前缀（按给定顺序取首个；无命中=空串）。扫描/分组/删除三处同一判据。"""
    for p in prefixes:
        if name.startswith(p):
            return p
    return ""


def scan(root: str, prefixes, max_age_h: float, now: float = None,
         excluded=EXCLUDED_PREFIXES):
    """扫 `root` 顶层一次（**唯一一次遍历**）：白名单命中的真目录/常规文件按年龄分桶。

    返回 dict：
      - `stale` / `live`：`[FixtureEntry]`（按名称排序，**删除顺序可复核**）；
      - `entries`（顶层条目总数）、`untouched`（白名单外）；
      - `excluded_by_prefix` / `excluded_count` / `excluded_named`（明确排除族：只可见、可删不着）；
      - `not_swept_named` / `not_swept`（符号链接、FIFO、stat 失败——逐条点名，绝不当 stale 删）。
    """
    now = time.time() if now is None else now
    stale, live, not_swept_named = [], [], []
    entries = untouched = 0
    locked = 0
    excluded_by_prefix = {p: 0 for p in excluded}
    excluded_named = []
    with os.scandir(root) as it:
        for ent in it:
            entries += 1
            name = ent.name
            ep = match_prefix(name, excluded)
            if ep:                       # 排除优先：明确排除的族永不参与（也不进白名单计数）
                excluded_by_prefix[ep] += 1
                if len(excluded_named) < 5:
                    excluded_named.append(name)
                continue
            if not match_prefix(name, prefixes):
                untouched += 1
                continue
            try:
                if ent.is_symlink():
                    # 符号链接：不碰（rmtree 跟链接会删到链接目标=别人的东西）
                    not_swept_named.append("%s (symlink — not followed)" % name)
                    continue
                if ent.is_dir(follow_symlinks=False):
                    kind = "dir"
                elif ent.is_file(follow_symlinks=False):
                    kind = "file"        # 文件族单独判定（锁档/影子/凭据副本）
                else:
                    not_swept_named.append("%s (not a real directory or regular file)" % name)
                    continue
                mtime = ent.stat(follow_symlinks=False).st_mtime
            except OSError as e:
                locked += 1
                not_swept_named.append("%s (stat failed: %s)" % (name, e))
                continue
            (stale if age_h(now, mtime) >= max_age_h else live).append(
                FixtureEntry(name, mtime, kind))
    stale.sort()
    live.sort()
    return {"entries": entries, "untouched": untouched, "stale": stale, "live": live,
            "not_swept_named": not_swept_named, "not_swept": locked,
            "excluded_by_prefix": excluded_by_prefix,
            "excluded_count": sum(excluded_by_prefix.values()),
            "excluded_named": excluded_named}


def by_prefix(items, prefixes):
    """[FixtureEntry] → {prefix: [items]}（按白名单顺序；同名多前缀取首个匹配，与 scan 同判据）。"""
    out = {p: [] for p in prefixes}
    for e in items:
        p = match_prefix(e.name, prefixes)
        if p:
            out[p].append(e)
    return out


def bounded_size(path: str, budget_s: float) -> tuple:
    """有界目录体积（不跟符号链接；预算用尽标 truncated）。返回 (bytes, truncated)。"""
    total = 0
    walked = 0
    deadline = time.monotonic() + budget_s
    stack = [path]
    truncated = False
    while stack:
        if time.monotonic() > deadline:
            truncated = True
            break
        cur = stack.pop()
        try:
            with os.scandir(cur) as it:
                for ent in it:
                    walked += 1
                    if walked > 200000:
                        truncated = True
                        stack = []
                        break
                    try:
                        if ent.is_symlink():
                            continue
                        if ent.is_dir(follow_symlinks=False):
                            stack.append(ent.path)
                        else:
                            total += ent.stat(follow_symlinks=False).st_size
                    except OSError:
                        continue
        except OSError:
            continue
    return total, truncated


def file_size(path: str) -> int:
    """常规文件字节（读不到算 0——估算面不猜，也绝不因此改判据）。"""
    try:
        return os.stat(path, follow_symlinks=False).st_size
    except OSError:
        return 0


def lock_held(path: str):
    """该文件是否正被某个进程 `flock` 持有？True/False；平台无 fcntl 或打不开=None（不判）。

    「在用即不动」的实现（文件族第三条判据）：先试着抢独占锁——抢得到 = 没人持有 =
    可以删；抢不到（EWOULDBLOCK）= 有活进程握着它（正是 `*-integ-run-*.lock` 的形态）
    = 保留并点名。`O_RDONLY` 打开即可 flock（不需要写权限），拿完立刻解锁。
    """
    try:
        import fcntl
    except ImportError:
        return None
    try:
        fd = os.open(path, os.O_RDONLY)
    except OSError:
        return None
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            return True
        fcntl.flock(fd, fcntl.LOCK_UN)
        return False
    finally:
        os.close(fd)


def _all_pids():
    """全机 pid 列表（`pgrep -f .`）。取不到 → (None, 原因串)：**具名留痕，绝不静默当 0**。

    「扫不到」与「没有载体」是两件事：前者会让人以为机器干净（261001 风暴里正是这个幻觉
    让人以为收口了）。所以工具缺席一律把原因写进报告。
    """
    try:
        r = subprocess.run(["pgrep", "-f", "."], capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError) as e:
        return None, "pgrep unavailable: %s: %s" % (type(e).__name__, e)
    if r.returncode not in (0, 1):
        return None, "pgrep exit=%d" % r.returncode
    pids = tuple(int(x) for x in r.stdout.split() if x.strip().isdigit())
    return pids, None


def _pid_cwd(pid: int):
    """该进程的 cwd（`lsof -a -p PID -d cwd -Fn`）；取不到=None（进程已死/无权限）。"""
    try:
        r = subprocess.run(["lsof", "-a", "-p", str(pid), "-d", "cwd", "-Fn"],
                           capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return None
    for line in r.stdout.splitlines():
        if line.startswith("n"):
            return line[1:]
    return None


def live_carriers(root: str, entries):
    """越龄夹具条目里还活着的进程（**载体**）→ ({条目名: [pid…]}, 扫描面错误或 None)。

    为什么按 **cwd** 判、不按命令行：261001 自递归风暴里那些进程的 args 是**相对路径**
    （`integration/run_scenarios.py --only …`，cwd 落在夹具泳道目录里），所以「按名字杀」
    三轮都打偏——实测杀完还剩 156 个，且越杀越多（杀掉 worker 反而触发它自己的
    supervisor 重拉）。**判据 = cwd 落在 `root/<白名单条目>/` 之下**，这才与「这条夹具里
    是谁在跑」同义。

    扫描面只取**越龄条目**（调用方传进来的是 `scan()` 的 stale 集合）：鲜条目里的活进程是
    正常现场（场景/running 套件），报它只会把报告刷成噪音，判据就没人看了。

    返回的第二种情况（错误串非 None）= 探测面不可用：**报告里必须具名**，
    且此刻**不算「没有载体」**（宁可保守：条目按「可能有载体」处置）。
    """
    pids, err = _all_pids()
    if err or not pids:
        return {}, (err or "pgrep returned no pids (unexpected on a live machine)")
    # 两侧都按 realpath 归一后再比（t261002-13 仲裁实锤的失真点）：`--root` 是调用方
    # 给的字面路径（macOS 上 `tempfile.gettempdir()` 给 `/var/folders/...`），而 pid cwd
    # 报的是**已解析**路径（`/private/var/folders/...`）——字面对字面永远比不中，
    # 「活载体保留」这条安全轨就在 symlinked temp 根下整条失效（而且静默失效）。
    # 归一用 `realpath`：两侧同一种解析，`/var/...` 与 `/private/var/...` 折到同一条真路径；
    # 不存在的条目 realpath 也能给出规范化形态（cwd 不可能落在不存在的目录里，无误伤）。
    dirs = {}
    root_real = os.path.realpath(root)
    for e in entries:
        if e.kind == "dir":
            dirs[os.path.realpath(os.path.join(root_real, e.name)).rstrip("/") + os.sep] = e.name
    if not dirs:
        return {}, None
    hits = {}
    for pid in pids:
        cwd = _pid_cwd(pid)
        if not cwd:
            continue
        cwd_real = os.path.realpath(cwd)
        for prefix_path, name in dirs.items():
            if cwd_real == prefix_path[:-1] or cwd_real.startswith(prefix_path):
                hits.setdefault(name, []).append(pid)
                break
    return hits, None


def kill_carriers(pids, grace_s: float = 5.0):
    """TERM → 等 grace_s → KILL。返回 {"termed","killed","failed"}（逐条点名，不静默）。

    **只由 `--kill-carriers` 显式开启**：杀进程不属于「清扫临时物料」的缺省语义——
    白名单目录很容易正好是某个真在跑的套件的夹具，误杀就是把别人的跑打红。
    调用点必须已确认「条目越龄」（与删除判据同一条线）。
    """
    import signal as _signal
    res = {"termed": 0, "killed": 0, "failed": []}
    alive = []
    for pid in list(pids):
        try:
            os.kill(pid, _signal.SIGTERM)
            res["termed"] += 1
            alive.append(pid)
        except ProcessLookupError:
            continue
        except OSError as e:
            res["failed"].append("%d: TERM %s: %s" % (pid, type(e).__name__, e))
    deadline = time.monotonic() + grace_s
    while alive and time.monotonic() < deadline:
        time.sleep(0.2)
        alive = [p for p in alive if _pid_alive(p)]
    for pid in alive:
        try:
            os.kill(pid, _signal.SIGKILL)
            res["killed"] += 1
        except ProcessLookupError:
            pass
        except OSError as e:
            res["failed"].append("%d: KILL %s: %s" % (pid, type(e).__name__, e))
    return res


def _pid_alive(pid: int) -> bool:
    """liveness（`os.kill(pid, 0)`）：权限不允许时也算活着（保守——不假装杀掉了）。"""
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except OSError:
        return True


def estimate(root: str, per_prefix: dict, sample: int, budget_s: float):
    """每前缀采样估占用（目录族：最多 sample 个实测平均 × 命中数；文件族：实际字节求和）。

    返回 (per_prefix_rows, est_total_bytes, notes)。采样与估算是**观测**，删除判据只有
    「前缀 + 年龄（+ 文件在用即不动）」——估算值绝不参与「删不删」的决定。
    """
    rows = []
    est_total = 0.0
    notes = []
    now = time.time()
    for prefix, items in per_prefix.items():
        dirs = [e for e in items if e.kind == "dir"]
        files = [e for e in items if e.kind == "file"]
        if not items:
            rows.append({"prefix": prefix, "count": 0, "dirs": 0, "files": 0,
                         "oldest_h": 0.0, "est_bytes": 0, "sampled": 0,
                         "dir_avg_bytes": 0.0, "truncated": False})
            continue
        picks = dirs[:sample] if sample > 0 else []
        sizes = []
        truncated = False
        for e in picks:
            b, t = bounded_size(os.path.join(root, e.name), budget_s)
            sizes.append(b)
            truncated = truncated or t
        dir_avg = (sum(sizes) / float(len(sizes))) if sizes else 0.0
        if dirs and not sizes:
            notes.append("%s: no dir sample taken (dir estimate omitted)" % prefix)
        if truncated:
            notes.append("%s: dir size estimate truncated by the %ss budget (underestimate)"
                         % (prefix, budget_s))
        file_bytes = sum(file_size(os.path.join(root, e.name)) for e in files)
        est = dir_avg * len(dirs) + file_bytes
        est_total += est
        oldest = max(age_h(now, e.mtime) for e in items)
        rows.append({"prefix": prefix, "count": len(items), "dirs": len(dirs),
                     "files": len(files), "oldest_h": oldest, "est_bytes": est,
                     "sampled": len(sizes), "dir_avg_bytes": dir_avg,
                     "truncated": truncated})
    return rows, est_total, notes


def _empty_row(prefix: str) -> dict:
    """Zero row, shaped like an `estimate()` row (a declared family with no hits)."""
    return {"prefix": prefix, "count": 0, "dirs": 0, "files": 0, "oldest_h": 0.0,
            "est_bytes": 0, "sampled": 0, "dir_avg_bytes": 0.0, "truncated": False}


def _kept_bucket(kept_by: dict, prefix: str) -> dict:
    """Per-family "kept" counters (live/lock/carrier/failed/unverified)."""
    return kept_by.setdefault(prefix, {"live": 0, "lock": 0, "carrier": 0,
                                       "failed": 0, "unverified": 0})


def _note_kept(kept_names_by: dict, prefix: str, text: str) -> None:
    """Record one kept entry (name + reason) for the per-family receipt detail line."""
    kept_names_by.setdefault(prefix, []).append(text)


def family_receipt(prefixes, rows, live_rows, swept_by, freed_by, kept_by, kept_names_by,
                   label, kept_cap=None):
    """Per-family receipt rows — ONE builder for dry-run and `--apply` (t261029-78).

    Why one builder: the applied mode used to collapse into a single total, so "which
    family was swept, and what did it cost" was unreadable exactly when it mattered. Both
    modes now print the same line layout; only the swept column's label differs
    (`would-sweep` = candidates in a dry-run, `swept` = really deleted).

    Families with no candidates and no live entries are skipped — except declared ones,
    which always print (at zero too), so the reader sees the declared coverage.

    Returns a list of dicts; each has `line` (preformatted) and the raw numbers, and the
    same list is exported as `per_family` in the JSON receipt.
    """
    cap = RECEIPT_KEPT_CAP if kept_cap is None else kept_cap
    est_by = {r["prefix"]: r for r in rows}
    out = []
    for p in prefixes:
        r = est_by.get(p) or _empty_row(p)
        live_n = len(live_rows.get(p) or [])
        decl = DECLARED_BY_PREFIX.get(p)
        if not (r["count"] or live_n or decl):
            continue
        kept = _kept_bucket(kept_by, p)
        kept["live"] = live_n
        swept_n = swept_by.get(p, 0)
        freed = freed_by.get(p, 0.0)
        names = kept_names_by.get(p) or []
        line = ("  family %-22s stale=%-6d (d=%-6d f=%-5d) live=%-5d oldest=%-8s "
                "est≈%-9s %s=%-6d freed≈%-9s | kept: live=%-5d lock=%-4d carrier=%-4d "
                "failed=%d%s"
                % (p, r["count"], r["dirs"], r["files"], live_n,
                   ("%.1fh" % r["oldest_h"]) if r["count"] else "-",
                   human(r["est_bytes"]) if r["count"] else "-",
                   label, swept_n, human(freed) if swept_n else "-",
                   live_n, kept["lock"], kept["carrier"], kept["failed"],
                   (" unverified=%d" % kept["unverified"]) if kept["unverified"] else ""))
        out.append({"prefix": p, "declared": bool(decl),
                    "stale": r["count"], "dirs": r["dirs"], "files": r["files"],
                    "live": live_n, "oldest_h": r["oldest_h"],
                    "est_bytes": r["est_bytes"], "swept": swept_n,
                    "freed_bytes": freed, "kept": dict(kept),
                    "kept_names": names,
                    "reason": decl.reason if decl else "",
                    "producer": decl.producer if decl else "",
                    "project": decl.project if decl else "",
                    "measured": decl.measured if decl else "",
                    "added_by": decl.added_by if decl else "",
                    "line": line})
    return out


def make_tree_writable(path: str) -> None:
    """把一棵树里的目录/文件补上写位（**只在常规删除失败时**走这条路）。

    为什么需要：fixture 里「只读形态」是常见被测面（260927 实况：`t260925-15-inst-*`
    的 `content/releases/v000001/` 是 `dr-xr-xr-x`——删它里面的文件需要父目录可写，
    `rmtree` 于是报 `PermissionError: entries.json`，21 个目录成了**永久残留**）。补权限
    只改 mode 位，不动内容、不碰树外任何东西；失败照旧逐条点名（不静默、不假装成功）。
    """
    for root, dirs, files in os.walk(path):
        for n in dirs + files:
            try:
                os.chmod(os.path.join(root, n), 0o700)
            except OSError:
                pass
        try:
            os.chmod(root, 0o700)
        except OSError:
            pass


def _delete(root: str, entry) -> int:
    """真删一个条目（目录 rmtree / 文件 unlink）→ 返回该条目字节数（失败上抛给调用点）。"""
    path = os.path.join(root, entry.name)
    if entry.kind == "file":
        n = file_size(path)
        os.unlink(path)
        return n
    try:
        shutil.rmtree(path)
    except PermissionError:
        make_tree_writable(path)      # 只读 fixture 形态：补写位后重试一次
        shutil.rmtree(path)
    return 0


def run(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Sweep leaked test-fixture entries under $TMPDIR "
                                            "(dry-run by default; --apply deletes)")
    ap.add_argument("--apply", action="store_true",
                    help="actually delete (default = dry-run, report only)")
    ap.add_argument("--root", default=None, help="temp root (default: tempfile.gettempdir())")
    ap.add_argument("--max-age-h", type=float, default=DEFAULT_MAX_AGE_H,
                    help="delete only entries idle >= this many hours (default 6)")
    ap.add_argument("--prefix", action="append", default=None,
                    help="override the whitelist prefix (repeatable; default = built-in whitelist)")
    ap.add_argument("--sample", type=int, default=DEFAULT_SAMPLE,
                    help="dirs sampled per prefix for the size estimate (default 10)")
    ap.add_argument("--sample-budget-s", type=float, default=DEFAULT_SAMPLE_BUDGET_S,
                    help="per-dir size-walk budget in seconds (default 8)")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    ap.add_argument("--kill-carriers", action="store_true",
                    help="kill orphan processes whose cwd still lives inside an aged-out "
                         "whitelisted fixture entry, then sweep it (default = report only)")
    args = ap.parse_args(argv)

    root = os.path.abspath(args.root or tempfile.gettempdir())
    # 空串前缀 = 形同没有前缀闸（`match_prefix` 对空串恒真）——一律剔除，宁严不松：
    # 剔除后若白名单为空，下面 `--apply` 的空白名单闸会拒收。
    # The default is the effective whitelist = engine-mirrored core + declared families
    # (t261029-78); `--prefix` still overrides both, for tests and for a narrow sweep.
    prefixes = tuple(p for p in args.prefix if p) if args.prefix else SWEEP_PREFIXES
    decl_errors = declaration_errors()
    out = {"mode": "apply" if args.apply else "dry-run", "root": root,
           "max_age_h": args.max_age_h, "prefixes": list(prefixes),
           "declaration": dict(DECLARATION, family_count=len(FAMILIES)),
           "declared_families": [f._asdict() for f in DECLARED_FAMILIES],
           "families_outside_engine_mirror": list(families_outside_engine_mirror())}
    log = (lambda m: print(m, file=sys.stderr, flush=True)) if args.json \
        else (lambda m: print(m, flush=True))

    def bail(msg, code=2):
        out["error"] = msg
        if args.json:
            print(json.dumps(out, ensure_ascii=False))
        else:
            print("REFUSED: " + msg)
        return code

    if decl_errors:
        # Fail-closed on the declaration itself: a half-written record (no reason, no
        # producer, shadowed prefix) is the trap the next reader walks into, so it is a
        # named refusal instead of a family that silently never matches.
        return bail("declared family list is malformed: %s" % "; ".join(decl_errors[:8]))
    if not os.path.isdir(root):
        return bail("root is not a directory: %s" % root)
    if args.max_age_h <= 0:
        return bail("--max-age-h must be > 0 (a sweep without an age gate could kill a running suite)")
    if args.apply and args.max_age_h < APPLY_MIN_AGE_H:
        return bail("--apply with --max-age-h %s < hard floor %sh refused"
                    % (args.max_age_h, APPLY_MIN_AGE_H))
    if args.apply and not prefixes:
        return bail("whitelist is empty — refusing to sweep with no prefix gate")

    if not args.apply:
        log("DRY-RUN (nothing is deleted; pass --apply to delete)")
    log("root=%s max-age=%sh prefixes=%d" % (root, args.max_age_h, len(prefixes)))
    log("declaration=%s (%d families, status=%s; the same file the alarm face reads)"
        % (DECLARATION.get("path") or "?", len(FAMILIES), DECLARATION.get("status") or "?"))

    t0 = time.monotonic()
    sc = scan(root, prefixes, args.max_age_h)
    rows, est_total, notes = estimate(root, by_prefix(sc["stale"], prefixes), args.sample,
                                      args.sample_budget_s)
    live_rows = by_prefix(sc["live"], prefixes)
    n_dirs = sum(1 for e in sc["stale"] if e.kind == "dir")
    n_files = len(sc["stale"]) - n_dirs
    # 载体（第三条判据，261001 自递归风暴新增）：**越龄**夹具里还活着的进程。它们是
    # 「宿主点名的实报」的承载者——树是死的、进程是活的，按名字杀打不中，只有按 cwd 才认得出。
    carriers, carrier_err = live_carriers(root, sc["stale"])
    carriers_n = sum(len(v) for v in carriers.values())
    log("scanned %d top-level entries in %.1fs: %d whitelisted stale (>=%sh: %d dirs / %d files), "
        "%d whitelisted live, %d untouched (outside whitelist), %d not swept"
        % (sc["entries"], time.monotonic() - t0, len(sc["stale"]), args.max_age_h,
           n_dirs, n_files, len(sc["live"]), sc["untouched"], len(sc["not_swept_named"])))
    if carrier_err:
        log("CARRIER SCAN UNAVAILABLE: %s —— 这批条目按「可能有载体」处置（不当作没有）" % carrier_err)
    elif carriers:
        log("LIVE CARRIERS: %d process(es) inside %d aged-out fixture entr(ies) —— 条目按在册"
            "保留（不删）；这形态=生产者收口漏了后代进程（被 SIGKILL 掉的场景不跑 finally）"
            % (carriers_n, len(carriers)))
        for name in sorted(carriers)[:NAMED_CAP]:
            log("  carrier %s: %d pid(s) %s" % (name, len(carriers[name]),
                                                ",".join(str(p) for p in carriers[name][:8])))
        if len(carriers) > NAMED_CAP:
            log("  ... (%d more carrier entries suppressed; see the count)" % (len(carriers) - NAMED_CAP))
    if sc["excluded_count"]:
        log("excluded by policy (never swept): %d entries — %s"
            % (sc["excluded_count"],
               ", ".join("%s=%d" % (p, c) for p, c in sorted(sc["excluded_by_prefix"].items())
                         if c)))
    # Honest face of the extension (t261029-78): families this tool reclaims but the water
    # line does not count are NAMED every run. "Swept but never alarmed" is the silent gap
    # the drift lock exists to prevent; closing it means writing server/ (outside this
    # lane's write set), so this run reports it instead of hiding it.
    mirror_gap = () if args.prefix else families_outside_engine_mirror()
    if not args.prefix:
        # Single source (t261029-81): the alarm face counts the same declaration file, so the
        # swept surface and the counted surface cannot diverge. This line states the coverage
        # instead of the old gap report - and it stays a measurement, not a promise: the count
        # is read from the file both sides read.
        log("ENGINE MIRROR: %d families declared in %s; the alarm face counts the same file "
            "(single source, t261029-81) - families outside it: %d"
            % (len(FAMILIES), DECLARATION.get("path") or "?", len(mirror_gap)))
    if mirror_gap:
        log("ENGINE MIRROR GAP: %d declared famil(ies) are not in the engine water-line "
            "mirror (server/engine/inspection_lane_watchdog.TMP_FIXTURE_PREFIXES): %s — this"
            " tool reclaims them, the alarm face does not count them yet (closing that needs"
            " a ticket that may write server/)" % (len(mirror_gap), ", ".join(mirror_gap)))
    freed = 0.0
    failed, failed_named = 0, []
    done = 0
    done_dirs = done_files = 0
    locked_kept, locked_named = 0, []
    carriers_kept, carriers_killed, carriers_named, unverified_kept = 0, 0, [], 0
    # Per-family bookkeeping, feeding the shared receipt (t261029-78). Counts are complete;
    # only the printed names are capped.
    swept_by, freed_by, kept_by, kept_names_by = {}, {}, {}, {}
    stale_by = by_prefix(sc["stale"], prefixes)
    if args.apply:
        # 目录族的实际释放量按「逐前缀实测平均 × 实删条数」重算（不直接抄全量估算）；
        # 文件族按实删字节累计（精确，无需采样）。
        dir_avg_by_prefix = {}
        for r in rows:
            if r["dirs"] and r["sampled"]:
                dir_avg_by_prefix[r["prefix"]] = r["dir_avg_bytes"]
        log("APPLY: deleting %d entries (>=%sh, whitelist only, live locks kept, "
            "carrier entries kept unless --kill-carriers) ..." % (len(sc["stale"]), args.max_age_h))
        for entry in sc["stale"]:
            p = match_prefix(entry.name, prefixes)
            bucket = _kept_bucket(kept_by, p)
            if carrier_err and entry.kind == "dir":
                # 探测面不可用 = **不知道**有没有载体。不知道就不删目录（树里有活进程时删树
                # 只留更脏的半态）；文件族与目录的判据不同（活锁判据独立可查），照旧处置。
                unverified_kept += 1
                bucket["unverified"] += 1
                _note_kept(kept_names_by, p, "%s (carrier scan unavailable)" % entry.name)
                if len(carriers_named) < NAMED_CAP:
                    carriers_named.append("%s (carrier scan unavailable: %s)" % (entry.name, carrier_err))
                log("  KEPT %s (carrier scan unavailable — refusing to assume 'no carriers')"
                    % entry.name)
                continue
            if carriers.get(entry.name):
                pids = carriers[entry.name]
                if not args.kill_carriers:
                    # 有活载体的条目**不删**：删树不杀进程 = 留下更脏的半态（进程继续在
                    # 已被 unlink 的目录里跑，报告却显示「已清」）。这与文件族的活锁同一条纪律。
                    carriers_kept += 1
                    bucket["carrier"] += 1
                    _note_kept(kept_names_by, p, "%s (%d live carrier pid(s))"
                               % (entry.name, len(pids)))
                    if len(carriers_named) < NAMED_CAP:
                        carriers_named.append("%s (%d live pid(s) %s; --kill-carriers to reap)"
                                              % (entry.name, len(pids),
                                                 ",".join(str(x) for x in pids[:8])))
                    log("  KEPT %s (%d live carrier pid(s); pass --kill-carriers to reap)"
                        % (entry.name, len(pids)))
                    continue
                kr = kill_carriers(pids)
                carriers_killed += kr["termed"]
                if kr["failed"]:
                    for m in kr["failed"][:NAMED_CAP]:
                        if len(failed_named) < NAMED_CAP:
                            failed_named.append("%s carrier reap failed: %s" % (entry.name, m))
                log("  REAPED %s carriers: termed=%d killed=%d failed=%d"
                    % (entry.name, kr["termed"], kr["killed"], len(kr["failed"])))
            if entry.kind == "file":
                held = lock_held(os.path.join(root, entry.name))
                if held is True:      # 在用的锁档绝不删（第三条文件族判据）
                    locked_kept += 1
                    bucket["lock"] += 1
                    _note_kept(kept_names_by, p, "%s (lock held by a live process)" % entry.name)
                    if len(locked_named) < NAMED_CAP:
                        locked_named.append("%s (lock held by a live process)" % entry.name)
                    log("  KEPT %s (flock held by a live process)" % entry.name)
                    continue
            try:
                if entry.kind == "dir":
                    _delete(root, entry)
                    got = dir_avg_by_prefix.get(p, 0.0)
                    done_dirs += 1
                else:
                    got = _delete(root, entry)
                    done_files += 1
                freed += got
                freed_by[p] = freed_by.get(p, 0.0) + got
                swept_by[p] = swept_by.get(p, 0) + 1
                done += 1
            except Exception as e:            # noqa: BLE001 —— 单条失败不中断全局清扫
                failed += 1
                bucket["failed"] += 1
                _note_kept(kept_names_by, p, "%s (delete failed: %s)" % (entry.name, type(e).__name__))
                if len(failed_named) < NAMED_CAP:
                    failed_named.append("%s: %s: %s" % (entry.name, type(e).__name__, e))
                elif len(failed_named) == NAMED_CAP:
                    failed_named.append("... (further failures suppressed; see the count)")
                log("  FAILED %s: %s: %s" % (entry.name, type(e).__name__, e))
            if done and done % 500 == 0:
                log("  progress: %d/%d deleted, %d failed, %.1fs elapsed, freed≈%s"
                    % (done, len(sc["stale"]), failed, time.monotonic() - t0, human(freed)))
    else:
        # dry-run: the candidate set must EQUAL what `--apply` would delete, so the same
        # three judgments run here read-only: the carrier cwd probe already happened above,
        # the lock probe is one flock(LOCK_NB) peek that holds nothing, and an unavailable
        # carrier probe still keeps every DIR family (unknown is not "none"). Otherwise the
        # dry-run would promise N deletions and --apply would do N-M.
        carriers_kept = len(carriers)
        if carrier_err:
            carriers_kept = 0
        est_by = {r["prefix"]: r["est_bytes"] for r in rows}
        for entry in sc["stale"]:
            p = match_prefix(entry.name, prefixes)
            bucket = _kept_bucket(kept_by, p)
            share = est_by.get(p, 0.0) / len(stale_by[p]) if stale_by.get(p) else 0.0
            if carrier_err and entry.kind == "dir":
                unverified_kept += 1
                bucket["unverified"] += 1
                _note_kept(kept_names_by, p, "%s (carrier scan unavailable)" % entry.name)
                continue
            if carriers.get(entry.name) and not args.kill_carriers:
                carriers_kept += 1
                bucket["carrier"] += 1
                _note_kept(kept_names_by, p, "%s (%d live carrier pid(s))"
                           % (entry.name, len(carriers[entry.name])))
                continue
            if entry.kind == "file" and lock_held(os.path.join(root, entry.name)) is True:
                locked_kept += 1
                bucket["lock"] += 1
                _note_kept(kept_names_by, p, "%s (lock held by a live process)" % entry.name)
                if len(locked_named) < NAMED_CAP:
                    locked_named.append("%s (lock held by a live process)" % entry.name)
                continue
            done += 1
            if entry.kind == "dir":
                done_dirs += 1
            else:
                done_files += 1
            swept_by[p] = swept_by.get(p, 0) + 1
            freed_by[p] = freed_by.get(p, 0.0) + share
        freed = sum(freed_by.values())

    # ---- per-family receipt: ONE shared printer, both modes (t261029-78) --------------
    label = "swept" if args.apply else "would-sweep"
    receipt = family_receipt(prefixes, rows, live_rows, swept_by, freed_by, kept_by,
                             kept_names_by, label)
    log("PER-FAMILY RECEIPT (%s; the same lines in both modes):" % label)
    for row in receipt:
        log(row["line"])
        if row["declared"]:
            log("      why: %s" % row["reason"])
            log("      who: %s:%s (declared by %s; measured %s)"
                % (row["project"], row["producer"], row["added_by"], row["measured"]))
        if row["kept_names"]:
            shown = row["kept_names"][:RECEIPT_KEPT_CAP]
            more = len(row["kept_names"]) - len(shown)
            log("      kept: %s%s" % ("; ".join(shown), (" (+%d more)" % more) if more else ""))
    for n in notes:
        log("  note: %s" % n)
    summary = ("%sswept %d (dirs %d / files %d) | kept %d live | carriers %d in %d entr(ies) "
               "(reaped %d, kept %d, unverified %d) | failed %d | locks kept %d | freed≈%s"
               % ("" if args.apply else "DRY-RUN: ", done, done_dirs, done_files,
                  len(sc["live"]), carriers_n, len(carriers), carriers_killed, carriers_kept,
                  unverified_kept, failed, locked_kept, human(freed)))
    log(summary)
    log("done in %.1fs" % (time.monotonic() - t0))
    out.update({"entries": sc["entries"], "untouched": sc["untouched"],
                "swept": done, "swept_dirs": done_dirs, "swept_files": done_files,
                "candidate_dirs": n_dirs, "candidate_files": n_files,
                "kept_live": len(sc["live"]), "failed": failed,
                "failed_named": failed_named,
                "locks_kept": locked_kept, "locks_kept_named": locked_named,
                "carriers": {k: sorted(v) for k, v in carriers.items()},
                "carriers_count": carriers_n, "carriers_entries": len(carriers),
                "carriers_scan_error": carrier_err, "carriers_reaped": carriers_killed,
                "carriers_kept": carriers_kept, "carriers_unverified_kept": unverified_kept,
                "carriers_named": carriers_named,
                "kill_carriers": bool(args.kill_carriers),
                "freed_est_bytes": freed, "swept_is_estimate": not args.apply,
                "per_prefix": rows,
                # Same rows the human receipt printed (t261029-78): per-family counts, the
                # swept column, kept-with-reason buckets and the declaration fields.
                "per_family": [{k: v for k, v in row.items() if k != "line"}
                               for row in receipt],
                "per_family_receipt": [row["line"] for row in receipt],
                "receipt_label": label,
                "live_per_prefix": {p: len(v) for p, v in live_rows.items()},
                "excluded_by_prefix": {p: c for p, c in sc["excluded_by_prefix"].items() if c},
                "excluded_named": sc["excluded_named"],
                "not_swept_named": sc["not_swept_named"][:NAMED_CAP], "notes": notes,
                "summary": summary})
    if args.json:
        print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(run())
