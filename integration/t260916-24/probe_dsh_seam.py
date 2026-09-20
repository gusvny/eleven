#!/usr/bin/env python3
"""dsh 升级接缝探针（t260916-24，方案 gen1 §2 步骤2）——把「升级会不会 break」变成可判定判据。

对接缝矩阵（notes/epics/dsh-upgrade.md，主检出）的 5 条待证面出**可重跑**判据；
任一拦停级红 → exit 1 逐项点名，升级流程（runbook §1 门槛）据此拦停。

用法：
  python3 probe_dsh_seam.py --selftest
      离线自检（金样本绿 + 篡改档逐项红；零网络/零 npm/秒级）。已登记为场景
      t260916-24-dsh-probe-selftest（ro 池）防探针腐烂。
  python3 probe_dsh_seam.py --version 0.1.5-rc.2
      live 档：隔离前缀显式钉版安装（npm install --prefix <tmp> @deepseek-ai/dsh@<版本>，
      装后核对 package.json 版本防 dist-tag 漂移）+ 隔离 DSH_HOME 跑一次性真会话
      → 五断言。需网络 + npm + 模型凭据 + zstd CLI；分钟级。**不入默认跑分面**
      （验收④），升级门槛时显式调用。
  --rounds N    延伸子用例：同一隔离 home 连跑 N 轮会话，汇总 cacheReadTokens 观测
                （矩阵 #2 开放问号）。**非门槛判据**——缓存命中是否发生依赖 provider
                行为，观测不确定，不拦停；结论行供人工回填矩阵 #2。
  --keep        保留临时目录取证（打印路径）
  --reuse-install 跳过安装（复用已装前缀，调试用；仍核 .bin/dsh 与版本）

断言（exit 1 拦停级，除注明外）：
  a  文件名口径：产出必匹配两代口径之一（v0=session.jsonl / vN=session.vN.jsonl，
     压缩后缀 .zstd 可选）；对账输出**必录实际文件名→所匹配代际**；两代均不匹配=红
     （C5①：新一代换名不许被静默容过——矩阵 #1 靶心=静默降级）。
  b  解析面必填：provider/model 可得（request/context 主、request/header 备，引擎
     读侧同款主备合一语义）+ assistant/message.usage.{inputTokens,outputTokens} 整型
     → 缺=红。可选面 cacheReadTokens：在场必整型（非整型=红）；缺席=WARN 逐行点名
     矩阵 #2 开放问号、不拦停（C2：0.1.5 该字段可选，单轮样本缺席≠破法——把工具的
     观测局限做成拦停判据=对已知可用版本假红）。
  b+ 记录类型族清单：观测类型集合对照 v0.1.1/v0.1.5 族声明表（矩阵 #10）。判红只看
     消费必需型（assistant/message、request/*）；族内漂移型（assistant/chunk、
     reasoning-chunks、assistant/attempt、system/message…）逐行 INVENTORY 不拦停，
     底册交 T5（t260916-25）消费。
  完整性：dsh 进程已退出后样本仍含坏 JSON 行/截断半行/zstd 坏帧=红（C1b，KI-059
     「撕裂→resume 必炸」族第一道网）。与引擎读侧「跳坏行」的边界：引擎容的是
     **写中尾帧**（active append），本探针验的是**已收口成品**。
  c  沙箱不变量（矩阵 #4）：行为子用例=泳道内写必须成功 + 主库 .git 模拟位越界写必须
     被拒（与现状 workspace-write/ask 基线一致）；辅证=安装包内缺省策略字面
     （INVENTORY 级，minified 打包字面观测脆，不作主裁）。
  d  钉模型生效（矩阵 #3）：会话实际 provider/model == 期望路由（隔离 home 的
     settings agent-default-model，或 SANDBAR_PROBE_EXPECTED_ROUTE="provider/model"）。
  e  resume 可用（矩阵 #5）：DSH_HEADLESS_SESSION + headless-resume runner patch
     二次会话续写**同一**会话文件集；出现新会话文件=resume 失效=红。

环境缺席（npm/网络/凭据/zstd/settings）= exit 2 ENV_FAIL 逐项点名，绝不静默绿
（integration/lib_env.py 三态纪律）。
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile
import time

EXIT_PASS, EXIT_FAIL, EXIT_ENV_FAIL = 0, 1, 2
PROBE_DIR = pathlib.Path(__file__).resolve().parent
REPO_ROOT = PROBE_DIR.parents[1]
FIXTURE_ROOT = PROBE_DIR / "fixtures"
SESSION_TIMEOUT_SEC = int(os.environ.get("SANDBAR_PROBE_SESSION_TIMEOUT_SEC") or 900)
# 安装超时可调（SANDBAR_PROBE_INSTALL_TIMEOUT_SEC，缺省 600s）：慢网/代理环境
# npm 拉 registry 可能超 600s——超时=ENV_FAIL 点名（三态不假绿），调大重跑即可。
INSTALL_TIMEOUT_SEC = int(os.environ.get("SANDBAR_PROBE_INSTALL_TIMEOUT_SEC") or 600)

# 文件名口径（dispatch 文口径：v0=session.jsonl / vN=session.vN.jsonl + 压缩后缀可选；
# v0 压缩形态 session.jsonl.zstd 为现装 0.1.1 实况——引擎读侧 glob 即此名，两代皆容）
GEN_PATTERNS = (
    ("v0", re.compile(r"^session\.jsonl(\.zstd)?$")),
    ("vN", re.compile(r"^session\.v(\d+)\.jsonl(\.zstd)?$")),
)
CONSUMER_REQUIRED_TYPES = ("assistant/message", "request/context", "request/header")
# 族声明表（矩阵 #10 底册；观测到表外类型=INVENTORY 记录，不拦停）
FAMILIES = {
    "v0.1.1 族": {"request/context", "request/header", "assistant/message",
                  "assistant/chunk", "reasoning-chunks"},
    "v0.1.5 族": {"request/context", "request/header", "assistant/message",
                  "assistant/attempt", "system/message"},
}


class Rows:
    """断言台账：逐行打印 + 计数；level ∈ PASS/FAIL/WARN/INVENTORY/ENV。"""

    def __init__(self):
        self.rows = []

    def add(self, level, name, detail=""):
        line = "[%s] %s%s" % (level, name, ("：%s" % detail) if detail else "")
        print(line, flush=True)
        self.rows.append((level, name, detail))

    def fail(self, name, detail=""):
        self.add("FAIL", name, detail)

    def count(self, level):
        return sum(1 for r in self.rows if r[0] == level)

    @property
    def exit_code(self):
        if self.count("ENV"):
            return EXIT_ENV_FAIL
        if self.count("FAIL"):
            return EXIT_FAIL
        return EXIT_PASS


# ---------------------------------------------------------------- 记录读取

def zstd_decompress(path: pathlib.Path):
    """zstd CLI 解压（引擎读侧同款依赖）。返回 (text, err)；err 非 None=坏帧/截断。"""
    try:
        p = subprocess.run(["zstd", "-dc", str(path)], capture_output=True, timeout=60)
    except subprocess.TimeoutExpired:
        return None, "zstd -dc 超时（60s）：%s" % path.name
    if p.returncode != 0:
        return None, "zstd 解压失败（坏帧/截断）：%s（rc=%d）" % (path.name, p.returncode)
    return p.stdout.decode("utf-8", "replace"), None


def collect_session_files(sessions_dir: pathlib.Path):
    """收集会话产物（sessions 下所有 session* 文件，相对路径排序保稳定）。"""
    if not sessions_dir.is_dir():
        return []
    files = [f for f in sessions_dir.rglob("session*") if f.is_file()]
    return sorted(files, key=lambda f: str(f.relative_to(sessions_dir)))


def parse_session_bundle(sessions_dir: pathlib.Path):
    """读全部会话文件。返回 (records, integrity_issues, files, naming)。

    naming = [(relpath, matched_gen|None)]；integrity_issues = [str]（坏帧/坏行/半行）。
    """
    records, issues, naming = [], [], []
    files = collect_session_files(sessions_dir)
    for f in files:
        rel = str(f.relative_to(sessions_dir))
        gen = None
        for gname, pat in GEN_PATTERNS:
            if pat.match(f.name):
                gen = gname
                break
        naming.append((rel, gen))
        if f.name.endswith(".zstd"):
            text, err = zstd_decompress(f)
            if err:
                issues.append(err)
                continue
        else:
            text = f.read_text("utf-8", "replace")
        for no, line in enumerate(text.splitlines(), 1):
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except ValueError as e:
                issues.append("%s 第 %d 行非完整 JSON（坏行/截断半行）：%s"
                              % (f.name, no, str(e)[:80]))
                continue
            if isinstance(obj, dict):
                records.append(obj)
    return records, issues, files, naming


def usage_of(rec):
    """引擎读侧同款取法：type=assistant/message → data.usage（assistant/chunk 同名
    usage 是同一份，引擎只加总 message——本探针同口径）。"""
    if rec.get("type") != "assistant/message":
        return None
    d = rec.get("data") or {}
    u = d.get("usage")
    return u if isinstance(u, dict) else None


def model_of(records):
    """引擎读侧主备合一：request/context.{provider,model} 主，request/header→
    data.header.config.{provider,model} 备（顺序扫描，后者仅在主缺失时补）。"""
    provider = model = ""
    for rec in records:
        t, d = rec.get("type"), rec.get("data") or {}
        if t == "request/context" and "provider" in d:
            if isinstance(d.get("provider"), str):
                provider = d["provider"]
            if isinstance(d.get("model"), str):
                model = d["model"]
        elif t == "request/header":
            c = (d.get("header") or {}).get("config") or {}
            if model == "" and isinstance(c.get("model"), str):
                if isinstance(c.get("provider"), str):
                    provider = c["provider"]
                model = c["model"]
    return provider, model


def _is_int(x):
    return isinstance(x, int) and not isinstance(x, bool)


# ---------------------------------------------------------------- 断言组

def check_naming(naming, rows):
    """断言 a：恰匹配一代=PASS 并显式记录代际；两代均不匹配=FAIL（C5①）。"""
    if not naming:
        rows.fail("a 文件名口径", "无任何会话产物（agent 未落会话文件？）")
        return
    for rel, gen in naming:
        if gen:
            rows.add("PASS", "a 文件名口径", "%s → %s 代口径" % (rel, gen))
        else:
            rows.fail("a 文件名口径",
                      "%s 两代口径均不匹配（期望 session.jsonl[.zstd] 或 session.vN.jsonl[.zstd]）"
                      "——新一代换名=矩阵 #1 静默降级破法" % rel)


def check_integrity(issues, rows):
    """成品完整性：坏行/半行/坏帧=红（dsh 进程已退出后不该有；KI-059 族）。"""
    if not issues:
        rows.add("PASS", "完整性（坏行/半行/坏帧）", "全部记录可解析")
        return
    for i in issues:
        rows.fail("完整性（坏行/半行/坏帧）", i)


def check_parse_face(records, rows):
    """断言 b：必填面（provider/model + in/out 整型）拦停级；可选面 cacheRead=WARN。"""
    provider, model = model_of(records)
    if provider or model:
        rows.add("PASS", "b 必填面 provider/model", "provider=%r model=%r（context 主/header 备）"
                 % (provider, model))
    else:
        rows.fail("b 必填面 provider/model",
                  "request/context 与 request/header 均未取得（引擎读侧主备合一面失配）")
    usages = [u for u in (usage_of(r) for r in records) if u is not None]
    if not usages:
        rows.fail("b 必填面 usage", "无 assistant/message.usage 记录（token 统计会静默归零）")
        return
    missing = [k for k in ("inputTokens", "outputTokens")
               if not any(_is_int(u.get(k)) for u in usages)]
    if missing:
        rows.fail("b 必填面 usage", "必填键缺席（0 会话含整型值）：%s" % ", ".join(missing))
    else:
        rows.add("PASS", "b 必填面 usage", "inputTokens/outputTokens 均可取整型")
    if any("cacheReadTokens" in u for u in usages):
        bad = [u["cacheReadTokens"] for u in usages if "cacheReadTokens" in u
               and not _is_int(u["cacheReadTokens"])]
        if bad:
            rows.fail("b 可选面 cacheReadTokens", "在场但非整型：%r（缓存读统计会算不进去）" % bad[:2])
        else:
            rows.add("PASS", "b 可选面 cacheReadTokens",
                     "在场且整型（max=%d）" % max(u["cacheReadTokens"] for u in usages))
    else:
        rows.add("WARN", "b 可选面 cacheReadTokens",
                 "全样本缺席（0.1.5 该字段可选；矩阵 #2 开放问号：缓存读计数是否仍上报"
                 "待缓存命中样本实证）——不拦停，结论供回填矩阵 #2；延伸子用例 --rounds N 可深查")


def check_record_family(records, rows):
    """断言 b+：记录类型族清单（矩阵 #10 底册）。必需型缺=红；漂移型=INVENTORY。"""
    observed = {}
    for rec in records:
        t = rec.get("type")
        if isinstance(t, str):
            observed[t] = observed.get(t, 0) + 1
    if not observed:
        rows.fail("b+ 记录类型族", "零记录可解析")
        return
    for t in CONSUMER_REQUIRED_TYPES:
        if t in observed:
            rows.add("PASS", "b+ 消费必需型", "%s ×%d" % (t, observed[t]))
        else:
            rows.fail("b+ 消费必需型", "%s 缺席（引擎/工作台读侧必需）" % t)
    known = set().union(*FAMILIES.values())
    for t, n in sorted(observed.items()):
        if t in CONSUMER_REQUIRED_TYPES:
            continue
        fams = [name for name, fam in FAMILIES.items() if t in fam]
        if fams:
            rows.add("INVENTORY", "b+ 族内类型", "%s ×%d（属于 %s；漂移不影响本票判据，底册交 T5）"
                     % (t, n, "/".join(fams)))
        else:
            rows.add("INVENTORY", "b+ 未入册类型", "%s ×%d（两代声明表均无；记录给 T5 底册）" % (t, n))


def check_model_pin(records, expected_provider, expected_model, rows):
    """断言 d：实际 provider/model == 期望路由（矩阵 #3 钉模型生效）。"""
    provider, model = model_of(records)
    if provider == expected_provider and model == expected_model:
        rows.add("PASS", "d 钉模型生效", "实际 provider/model == 期望（%s/%s）" % (provider, model))
    else:
        rows.fail("d 钉模型生效",
                  "实际 %r/%r ≠ 期望 %r/%r（260826「钉不上」事故族：settings 层被盖/schema 变）"
                  % (provider, model, expected_provider, expected_model))


def check_session_bundle(sessions_dir, expected_provider, expected_model, rows):
    """聚合五断言（selftest 与 live 共用入口）。"""
    records, issues, _files, naming = parse_session_bundle(sessions_dir)
    check_naming(naming, rows)
    check_integrity(issues, rows)
    check_parse_face(records, rows)
    check_record_family(records, rows)
    check_model_pin(records, expected_provider, expected_model, rows)


# ---------------------------------------------------------------- 环境与 live

def which_or_env_fail(names, rows):
    """依赖在位性检查（缺=ENV 行；三态纪律：环境红永不 exit 0）。"""
    missing = [n for n in names if not shutil.which(n)]
    for n in names:
        if not shutil.which(n):
            rows.add("ENV", "依赖在位", "缺 %s——先安装（zstd 为引擎读侧同款硬依赖；npm 为隔离安装必需）" % n)
    return missing


def mini_parse_agent_default_model(settings_path: pathlib.Path):
    """mini yaml 解析：只取 settings.yaml 的 agent-default-model 段 provider/model
    （探针自含，不引第三方 yaml；段缺失返回 None）。"""
    if not settings_path.is_file():
        return None
    provider = model = None
    in_section = False
    for raw in settings_path.read_text("utf-8", "replace").splitlines():
        line = raw.rstrip()
        if re.match(r"^agent-default-model:", line):
            in_section = True
            continue
        if in_section:
            if line and not line[:1] in (" ", "\t", "#"):
                break  # 下一顶格 key = 段结束
            m = re.match(r"^\s+(provider|model):\s*(.+?)\s*$", line)
            if m:
                val = m.group(2).strip().strip("'\"")
                if m.group(1) == "provider":
                    provider = val
                else:
                    model = val
    if provider and model:
        return provider, model
    return None


def build_home(home_dir: pathlib.Path, rows):
    """隔离 DSH_HOME 组装（复刻引擎 _copy_profile/_copy_settings/_copy_creds 语义）。"""
    src_home = pathlib.Path.home() / ".dsh"
    profile_src = src_home / "profiles" / "sandbar-headless"
    settings_src = src_home / "settings.yaml"
    creds_src = src_home / ".credentials.yaml"
    ok = True
    if profile_src.is_dir():
        shutil.copytree(str(profile_src), str(home_dir / "profiles" / "sandbar-headless"), symlinks=True)
    else:
        rows.add("ENV", "隔离 home 组装", "缺 %s（sandbar-headless profile；dsh 起不来）" % profile_src)
        ok = False
    if settings_src.is_file():
        shutil.copy2(str(settings_src), str(home_dir / "settings.yaml"))
    else:
        rows.add("ENV", "隔离 home 组装", "缺 %s（钉模型断言 d 无期望来源）" % settings_src)
        ok = False
    if creds_src.is_file():
        shutil.copy2(str(creds_src), str(home_dir / ".credentials.yaml"))
    else:
        rows.add("ENV", "隔离 home 组装", "缺 %s（模型凭据；会话必 MISSING_CREDENTIAL）" % creds_src)
        ok = False
    return ok


def resolve_expected_route(home_dir: pathlib.Path, rows):
    """期望路由：env 显式 > settings agent-default-model 段；皆无=ENV 点名。"""
    override = (os.environ.get("SANDBAR_PROBE_EXPECTED_ROUTE") or "").strip()
    if override and "/" in override:
        p, m = override.split("/", 1)
        rows.add("INVENTORY", "期望路由", "env SANDBAR_PROBE_EXPECTED_ROUTE 显式指定 %s/%s" % (p, m))
        return p, m
    parsed = mini_parse_agent_default_model(home_dir / "settings.yaml")
    if parsed:
        rows.add("INVENTORY", "期望路由", "取自隔离 home settings agent-default-model：%s/%s" % parsed)
        return parsed
    rows.add("ENV", "期望路由",
             "无法确定：settings.yaml 无 agent-default-model 段且未设 SANDBAR_PROBE_EXPECTED_ROUTE"
             "（断言 d 需要期望值；先在真 dsh 配好默认模型或用 env 显式给）")
    return None


def run_session(dsh_bin, home_dir, lane_dir, prompt, log_path, extra_env=None,
                extra_args=None, timeout=SESSION_TIMEOUT_SEC):
    """起一次性 headless 会话（start_new_session + 超时 killpg 全终态收割）。"""
    env = dict(os.environ)
    env["DSH_HOME"] = str(home_dir)
    env.update(extra_env or {})
    cmd = [str(dsh_bin), "--profile", "sandbar-headless"] + list(extra_args or []) + [prompt]
    logf = open(str(log_path), "a", buffering=1)
    try:
        proc = subprocess.Popen(cmd, cwd=str(lane_dir), stdout=logf, stderr=subprocess.STDOUT,
                                stdin=subprocess.DEVNULL, env=env, start_new_session=True)
        try:
            rc = proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(os.getpgid(proc.pid), 9)
            except OSError:
                proc.kill()
            proc.wait()
            return None, "会话超时（>%ds），进程组已收割（日志 %s）" % (timeout, log_path)
        return rc, None
    finally:
        logf.close()


def verify_install(prefix_dir, version, rows):
    """装后核版本（防 dist-tag 漂移——runbook §2 步骤0 同款纪律）。"""
    pkg = prefix_dir / "node_modules" / "@deepseek-ai" / "dsh" / "package.json"
    if not pkg.is_file():
        rows.add("ENV", "安装核验", "未找到 %s（安装未完成或包名/版本不存在）" % pkg)
        return False
    try:
        got = json.loads(pkg.read_text("utf-8")).get("version")
    except ValueError as e:
        rows.add("ENV", "安装核验", "package.json 不可解析：%s" % e)
        return False
    if got != version:
        rows.add("ENV", "安装核验", "版本漂移：请求 %s 实装 %s（dist-tag 漂移；必须显式钉版重装）"
                 % (version, got))
        return False
    rows.add("INVENTORY", "安装核验", "实装版本 == 请求版本（%s）" % version)
    return True


def probe_live(version, rounds, keep, reuse_install):
    rows = Rows()
    print("== dsh 接缝探针 live 档：@deepseek-ai/dsh@%s ==" % version)
    which_or_env_fail(["zstd", "npm"], rows)
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="dshprobe-"))
    print("[INVENTORY] 工作目录：%s%s" % (tmp, "（--keep 保留）" if keep else "（结束清理）"))
    try:
        prefix_dir = tmp / "prefix"
        home_dir = tmp / "home"
        lane_dir = tmp / "lane"
        lane_dir.mkdir(parents=True)
        # 模拟「主库 .git」位（断言 c 越界写目标）：目录真在场，越界拒写判据才无歧义
        (tmp / "escape-main-repo" / ".git").mkdir(parents=True, exist_ok=True)
        if not reuse_install:
            print("[INVENTORY] npm 隔离安装中（--prefix %s，最长 %ds）…" % (prefix_dir, INSTALL_TIMEOUT_SEC))
            try:
                p = subprocess.run(
                    ["npm", "install", "--prefix", str(prefix_dir),
                     "@deepseek-ai/dsh@%s" % version, "--cache", str(tmp / "npm-cache"),
                     "--no-audit", "--no-fund"],
                    capture_output=True, text=True, timeout=INSTALL_TIMEOUT_SEC)
                if p.returncode != 0:
                    rows.add("ENV", "npm 隔离安装", "rc=%d：%s" % (
                        p.returncode, (p.stderr or p.stdout or "")[-300:]))
            except subprocess.TimeoutExpired:
                rows.add("ENV", "npm 隔离安装", "超时（>%ds；网络/registry 慢）" % INSTALL_TIMEOUT_SEC)
        else:
            rows.add("INVENTORY", "npm 隔离安装", "--reuse-install：复用已装前缀")
        if not verify_install(prefix_dir, version, rows):
            return finish(rows, tmp, keep)
        dsh_bin = prefix_dir / "node_modules" / ".bin" / "dsh"
        if not dsh_bin.exists():
            rows.add("ENV", "dsh bin", "缺 %s（.bin 实际：%s）" % (
                dsh_bin, ", ".join(x.name for x in (prefix_dir / "node_modules" / ".bin").glob("*"))[:200]))
            return finish(rows, tmp, keep)
        if not build_home(home_dir, rows):
            return finish(rows, tmp, keep)
        route = resolve_expected_route(home_dir, rows)
        if not route:
            return finish(rows, tmp, keep)
        exp_provider, exp_model = route

        # 延伸子用例 --rounds N：同一 home 连跑 N 轮（无 resume），汇总 cacheRead 观测（不拦停）
        total_rounds = max(1, rounds)
        cache_seen = []
        for i in range(total_rounds):
            print("[INVENTORY] 会话 %d/%d 跑中（cwd=%s，超时 %ds）…" % (i + 1, total_rounds, lane_dir, SESSION_TIMEOUT_SEC))
            rc, err = run_session(dsh_bin, home_dir, lane_dir,
                                  LIVE_PROMPT % (lane_dir / "probe_write_here.txt",
                                                 tmp / "escape-main-repo" / ".git" / "probe_escape.txt"),
                                  tmp / ("session_round%d.log" % (i + 1)))
            if err:
                rows.fail("c 行为子用例会话", "第 %d 轮：%s" % (i + 1, err))
                continue
            if rc != 0:
                rows.fail("c 行为子用例会话", "第 %d 轮 agent 退出码 %s≠0（日志 %s）" % (i + 1, rc, tmp / ("session_round%d.log" % (i + 1))))
            check_session_bundle(home_dir / "sessions", exp_provider, exp_model, rows)
            # 行为子用例只对第 1 轮判（后续轮会重复写同文件，判据失真）
            if i == 0:
                check_sandbox_behavior(lane_dir, tmp / "escape-main-repo", prefix_dir, rows)
            for u in (usage_of(r) for r in parse_session_bundle(home_dir / "sessions")[0]):
                if u is not None and _is_int(u.get("cacheReadTokens")) and u["cacheReadTokens"] > 0:
                    cache_seen.append(u["cacheReadTokens"])
            if rows.exit_code != EXIT_PASS:
                break  # 首轮已红：后续轮只会在红面上重复，省时退出
        if total_rounds >= 2:
            if cache_seen:
                rows.add("INVENTORY", "延伸子用例 cacheRead 实证", "%d 轮中出现正值 %r → 缓存读计数仍上报（矩阵 #2 问号可闭合）"
                         % (total_rounds, cache_seen[:5]))
            else:
                rows.add("INVENTORY", "延伸子用例 cacheRead 实证",
                         "%d 轮均未观察到 cacheReadTokens>0 → 问号保持（可能无缓存命中；非破法证据，回填矩阵 #2）" % total_rounds)
        # 断言 e：resume 插件路径（同 DSH_HEADLESS_SESSION 续写同一会话文件集）
        check_resume(dsh_bin, home_dir, lane_dir, tmp, rows)
    finally:
        if not keep:
            shutil.rmtree(str(tmp), ignore_errors=True)
    return finish(rows, tmp, keep, already_cleaned=not keep)


def check_sandbox_behavior(lane_dir, escape_root, prefix_dir, rows):
    """断言 c：泳道内写成功 + 主库 .git 模拟位越界写被拒（行为子用例主裁）+
    安装包缺省策略字面（INVENTORY 辅证）。"""
    here = lane_dir / "probe_write_here.txt"
    escape = escape_root / ".git" / "probe_escape.txt"
    if here.is_file():
        rows.add("PASS", "c 行为子用例 泳道内写", "%s 落盘成功（workspace-write 授予面在）" % here.name)
    else:
        rows.fail("c 行为子用例 泳道内写", "%s 未落盘——比现状更严（阶段产物会写不出，矩阵 #4 破法）" % here)
    if escape.exists():
        rows.fail("c 行为子用例 主库 .git 越界写", "%s 竟然可写——比现状更松（「worker 代落盘」前提失效，"
                  "settle 语义可能重复提交，矩阵 #4 最隐蔽破法）" % escape)
    else:
        rows.add("PASS", "c 行为子用例 主库 .git 越界写", "%s 不可写（与现状基线一致）" % escape.parent.name + "/")
    hits = subprocess.run(["grep", "-rl", "workspace-write", str(prefix_dir / "node_modules" / "@deepseek-ai")],
                          capture_output=True)
    if hits.returncode == 0:
        rows.add("INVENTORY", "c 辅证 策略字面", "安装包内出现 workspace-write 字面（缺省策略面字面在场）")
    else:
        rows.add("INVENTORY", "c 辅证 策略字面", "安装包内未见 workspace-write 字面（可能打包形态不同；以行为子用例为准）")


def check_resume(dsh_bin, home_dir, lane_dir, tmp, rows):
    runner = REPO_ROOT / "server" / "headless-resume" / "node.ts"
    if not runner.is_file():
        rows.fail("e resume 插件", "runner 缺席：%s（引擎会话延续面真源缺失）" % runner)
        return
    patch = tmp / "resume_patch.yml"
    patch.write_text(
        "# 探针生成的会话延续 patch（复刻引擎 _prepare_agent_spawn 的 resume patch 形状）\n"
        "- id: headless-runner\n"
        "  disabled: true\n"
        "- insert:\n"
        "    - id: headless-resume\n"
        "      name: '%s'\n"
        "      inject: [headlessStartup]\n"
        "      config:\n"
        "        task: !!js ctx.headlessStartup.task\n" % runner, "utf-8")
    before = {str(f.relative_to(home_dir)) for f in collect_session_files(home_dir / "sessions")}
    rc, err = run_session(dsh_bin, home_dir, lane_dir, RESUME_PROMPT,
                          tmp / "session_resume.log",
                          extra_env={"DSH_HEADLESS_SESSION": "t260916-24-probe-resume"},
                          extra_args=["--patch", str(patch)])
    if err:
        rows.fail("e resume 插件", err)
        return
    if rc != 0:
        rows.fail("e resume 插件", "resume 会话退出码 %s≠0（dsh 版本接缝处硬崩？日志 %s）" % (rc, tmp / "session_resume.log"))
        return
    after = {str(f.relative_to(home_dir)) for f in collect_session_files(home_dir / "sessions")}
    grown = after - before
    if grown:
        rows.fail("e resume 插件", "resume 会话另起新会话文件 %s——续写失败（stock one-shot 回落=插件静默不生效）"
                  % sorted(grown)[:3])
    else:
        rows.add("PASS", "e resume 插件", "同 DSH_HEADLESS_SESSION 续写，会话文件集不变（%d 个）" % len(after))


LIVE_PROMPT = (
    "这是 dsh 升级兼容性探针会话。请严格按序执行并尽快结束，不要做任何其他事：\n"
    "1) 在当前目录创建文件 probe_write_here.txt，内容为 ok；\n"
    "2) 尝试在 %s 创建文件 probe_escape.txt；若被拒绝，直接记录被拒即可，不要换路径重试；\n"
    "3) 完成后立即结束会话。"
)
RESUME_PROMPT = "这是 resume 续写探针。请只回复 done 两个字母，然后立即结束，不要做任何其他事。"


def finish(rows, tmp, keep, already_cleaned=False):
    print("== SUMMARY：PASS=%d WARN=%d INVENTORY=%d FAIL=%d ENV=%d ==" % (
        rows.count("PASS"), rows.count("WARN"), rows.count("INVENTORY"),
        rows.count("FAIL"), rows.count("ENV")))
    if keep and not already_cleaned:
        print("[INVENTORY] 取证目录保留：%s" % tmp)
    code = rows.exit_code
    print("== 探针结论：%s ==" % {EXIT_PASS: "全绿", EXIT_FAIL: "拦停级红（升级门槛据此拦停）",
                                  EXIT_ENV_FAIL: "环境红（缺依赖/凭据，本轮未验）"}[code])
    return code


# ---------------------------------------------------------------- selftest

GOLDEN_SPECS = [
    ("golden/v0-full", 0),
    ("golden/vN-full", 0),
    ("golden/vN-no-cacheread", 1),  # 必须恰有 ≥1 条 cacheRead WARN（可选键语义自锁，C2）
]
TAMPERED_SPECS = [
    ("tampered/bad-filename", "a 文件名口径"),
    ("tampered/missing-required", "b 必填面 usage"),
    ("tampered/cacheread-nonint", "b 可选面 cacheReadTokens"),
    ("tampered/model-mispin", "d 钉模型生效"),
    ("tampered/bad-json-line", "完整性"),
    ("tampered/truncated-half-line", "完整性"),
    ("tampered/zstd-bad-frame", "完整性"),
]
FIXTURE_ROUTE = ("probe-provider", "probe-model-X")


def selftest():
    """离线自检（V3 纪律：全程 /tmp 副本操作，不改仓内 fixtures）：
    金样本必须绿（no-cacheread 档必须出 WARN）；篡改档必须按预期断言名红。
    方向不符=探针腐烂=exit 1 点名。"""
    rows = Rows()
    print("== dsh 接缝探针 --selftest（离线）==")
    if not shutil.which("zstd"):
        rows.add("ENV", "依赖在位", "缺 zstd（selftest 解压 zstd 夹具需要；引擎读侧同款硬依赖）")
        return finish(rows, None, False)
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="dshselftest-"))
    rot = []
    try:
        for rel, want_cache_warns in GOLDEN_SPECS:
            dst = tmp / rel.replace("/", "_")
            shutil.copytree(str(FIXTURE_ROOT / rel), str(dst))
            r = Rows()
            check_session_bundle(dst / "sessions", *FIXTURE_ROUTE, rows=r)
            cache_warns = [x for x in r.rows if x[0] == "WARN" and "cacheReadTokens" in x[1]]
            fails = [x for x in r.rows if x[0] == "FAIL"]
            envs = [x for x in r.rows if x[0] == "ENV"]
            verdict = "绿" if not fails and not envs else "红"
            if verdict != "绿":
                rot.append("金样本 %s 应绿实红：%s" % (rel, [f[1] for f in fails]))
            if want_cache_warns and not cache_warns:
                rot.append("金样本 %s 应出 cacheRead WARN 实未出（可选键语义腐烂）" % rel)
            if not want_cache_warns and cache_warns:
                rot.append("金样本 %s 不应有 WARN 实出：%s" % (rel, [c[2] for c in cache_warns]))
            print("[selftest] 金样本 %-26s → 绿（PASS=%d WARN=%d）" % (rel, r.count("PASS"), r.count("WARN")))
        for rel, expect_fail_name in TAMPERED_SPECS:
            dst = tmp / rel.replace("/", "_")
            shutil.copytree(str(FIXTURE_ROOT / rel), str(dst))
            r = Rows()
            check_session_bundle(dst / "sessions", *FIXTURE_ROUTE, rows=r)
            fails = [x[1] for x in r.rows if x[0] == "FAIL"]
            hit = any(expect_fail_name in f for f in fails)
            if not hit:
                rot.append("篡改档 %s 应红（预期断言 %r）实未红：%s" % (rel, expect_fail_name, fails))
            print("[selftest] 篡改档 %-26s → 红（命中 %r；FAIL=%d）" % (rel, expect_fail_name, len(fails)))
        for msg in rot:
            rows.fail("selftest 探针腐烂", msg)
        if not rot:
            rows.add("PASS", "selftest", "金样本 3 档全绿（含可选键 WARN 语义）+ 篡改 7 档逐项红")
    finally:
        shutil.rmtree(str(tmp), ignore_errors=True)
    return finish(rows, tmp, False, already_cleaned=True)


def main():
    ap = argparse.ArgumentParser(description="dsh 升级接缝探针（t260916-24）")
    ap.add_argument("--selftest", action="store_true", help="离线自检（金样本绿+篡改档红）")
    ap.add_argument("--version", help="live：被测 dsh 版本（必须显式钉，如 0.1.5-rc.2）")
    ap.add_argument("--rounds", type=int, default=1, help="延伸子用例：会话轮数（≥2 汇总 cacheRead 观测）")
    ap.add_argument("--keep", action="store_true", help="保留临时目录取证")
    ap.add_argument("--reuse-install", action="store_true", help="跳过 npm 安装（复用已装前缀，调试用）")
    args = ap.parse_args()
    if args.selftest:
        sys.exit(selftest())
    if args.version:
        sys.exit(probe_live(args.version, args.rounds, args.keep, args.reuse_install))
    ap.print_help()
    print("\n（--selftest 或 --version <v> 二选一；见模块 docstring）")
    sys.exit(EXIT_ENV_FAIL)


if __name__ == "__main__":
    main()
