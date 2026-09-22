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
     （C5①：新一代换名不许被静默容过——矩阵 #1 靶心=静默降级）。侧车显式名单
     （SESSION_SIDECAR_NAMES，0.1.5 的 session.lock）单列 INVENTORY 不计入正文
     计数（t260922-07①：辅助锁文件不是换名正文；名单外新形不豁免、照旧红）。
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
     被拒（与现状 workspace-write/ask 基线一致）；越界目标位建在可写三根
     （workspaceRoot∪/tmp∪tmpdir）之外（t260922-07②：live-run-260922 第 2 条原目标
     建在探针 tmp 下=tmpdir∈可写根，假红；现位 $HOME/.sandbar-probe-escape/<mkdtemp>/
     main-repo/.git，建位/审计台账全列三根+目标，审计不过=ENV 红不跑该子用例）；
     辅证=安装包内缺省策略字面（INVENTORY 级，minified 打包字面观测脆，不作主裁）。
  d  钉模型生效（矩阵 #3）：会话实际 provider/model == 期望路由（隔离 home 的
     settings agent-default-model，或 SANDBAR_PROBE_EXPECTED_ROUTE="provider/model"）。
  e  resume 可用（矩阵 #5）：DSH_HEADLESS_SESSION + headless-resume runner patch
     二次会话续写**同一**会话文件集；出现新会话文件=resume 失效=红。

环境缺席（npm/网络/凭据/zstd/settings）= exit 2 ENV_FAIL 逐项点名，绝不静默绿
（integration/lib_env.py 三态纪律）。凭据缺失=dsh 会话日志自报 MISSING_CREDENTIAL：
会话守望见字面即提前收割进程组（不空等到超时——实测手工跑曾静默等满 900s），归因=
ENV 红点名 provider 路由与补救路径（补齐后重跑仍报 → 疑版本接缝凭据语义变更，转
人工按升级破法判定）；归因只落失败路径，rc=0 的完整会话不得被日志字面翻红
（t260922-03）。
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

# 探针自己的会话 id（断言 e 用；t260923 修）：**两条腿必须同 id** 才构成 resume 场景
# ——第一腿建立该 id 的会话档，resume 腿按同 id 续写、断言「正文文件集不变」。
# 口径依据（t260922-06 源码实证，已合入 main）：0.1.1 与 0.1.5 **自定义 id 原生全链路
# 有效**（目录名=encodeSegment(id)、头记录 id=自定义 id、resume 按该 id 扫描寻址），
# 引擎每次 spawn 都注入该 env。旧探针只在 resume 腿注入 → 第一腿用自动生成 id，resume
# 腿拿一个从未存在的自定义 id 去寻址，必然「Not found → 回落新建」→ 断言必红（假红）。
PROBE_SESSION_ID = "t260916-24-probe-resume"

# 凭据缺失守望（t260922-03）：dsh 会话日志自报 MISSING_CREDENTIAL 即属环境态——
# 早停收割不空等（实测手工跑曾静默等满超时），归因见 classify_credential_failure。
CRED_MARKER = "MISSING_CREDENTIAL"
CRED_WATCH_INTERVAL_SEC = 2.0
CRED_ROUTE_RE = re.compile(r'no API key for provider route "([^"]+)"')
CRED_VAR_RE = re.compile(r"store ([A-Z][A-Z0-9_]*) through the credentials service")

# 文件名口径（dispatch 文口径：v0=session.jsonl / vN=session.vN.jsonl + 压缩后缀可选；
# v0 压缩形态 session.jsonl.zstd 为现装 0.1.1 实况——引擎读侧 glob 即此名，两代皆容）
GEN_PATTERNS = (
    ("v0", re.compile(r"^session\.jsonl(\.zstd)?$")),
    ("vN", re.compile(r"^session\.v(\d+)\.jsonl(\.zstd)?$")),
)
# 侧车显式名单（t260922-07 判据精度收口①）：0.1.5 会话目录新增辅助锁文件
# session.lock——会话伴生件，不是会话正文。豁免用显式名单不用形状规则（「session*
# 且非 .jsonl」会把未来换名的正文误豁免成侧车=假绿=自欺）：名单外的新形一律不豁免、
# 照旧走断言 a 红，人工裁决确认侧车身份后再显式加名单（C5①反静默降级同哲学）。
# 引擎侧同源常量：server/engine/agent_activities.py SESSION_SIDECAR_NAMES（跨
# server/integration 边界无法共享模块，两侧注释互指；两侧逐字相等由
# integration/t260916-24/test_t260922_07_criteria_precision.py 与场景
# t260922-07-engine-sidecar-diagnostics 机械断言，防名单漂移成假绿/假红）。
SESSION_SIDECAR_NAMES = ("session.lock",)
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
        print(format_row((level, name, detail)), flush=True)
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

def format_row(row):
    """台账行元组 → 打印字面（单源格式化：Rows.add 与 selftest/UT 冻结比对共用，
    改打印形状只动这里一处）。"""
    level, name, detail = row
    return "[%s] %s%s" % (level, name, ("：%s" % detail) if detail else "")


def session_body_gen(name: str):
    """文件名 → 所匹配代际（GEN_PATTERNS 单源）；非正文（侧车/篡改形/未知新名）→ None。

    正文定义永不分叉（t260922-07①）：正文=恰匹配两代口径之一（session.jsonl[.zstd] /
    session.vN.jsonl[.zstd]）。session.lock 属侧车、session.v3.jsonl.gz 属篡改形、
    其余新名属未知形——三者都不是正文，未知形也不豁免（先红，人工裁决后再入侧车名单）。"""
    for gname, pat in GEN_PATTERNS:
        if pat.match(name):
            return gname
    return None


def is_session_sidecar(name: str) -> bool:
    """侧车判定（显式名单 SESSION_SIDECAR_NAMES，按 lower 归一）。名单外一律 False
    ——不做形状豁免（防未来换名正文被误豁免成假绿，见常量注释）。"""
    return name.lower() in SESSION_SIDECAR_NAMES


def collect_session_files(sessions_dir: pathlib.Path):
    """收集会话**正文**（t260922-07①收窄：恰匹配两代口径才收）。侧车单列见
    collect_sidecar_files；未知形不收也不豁免——留给断言 a 响亮红。相对路径排序保稳定。"""
    if not sessions_dir.is_dir():
        return []
    files = [f for f in sessions_dir.rglob("session*")
             if f.is_file() and session_body_gen(f.name)]
    return sorted(files, key=lambda f: str(f.relative_to(sessions_dir)))


def collect_sidecar_files(sessions_dir: pathlib.Path):
    """收集侧车（sessions 全量半径内命中显式名单者，按 lower 归一——大小写变体也
    单列；t260922-07①）。仅供 INVENTORY 点名，不计入正文计数、不参与完整性/解析面
    对账。半径比正文宽（rglob("*") 而非 rglob("session*")：pathlib 在 posix 上 glob
    大小写敏感，「Session.LOCK」进不了 session* 半径）——该半径只影响单列清单的
    完整度，不触碰任何红绿判定。"""
    if not sessions_dir.is_dir():
        return []
    files = [f for f in sessions_dir.rglob("*")
             if f.is_file() and is_session_sidecar(f.name)]
    return sorted(files, key=lambda f: str(f.relative_to(sessions_dir)))


def zstd_decompress(path: pathlib.Path):
    """zstd CLI 解压（引擎读侧同款依赖）。返回 (text, err)；err 非 None=坏帧/截断。"""
    try:
        p = subprocess.run(["zstd", "-dc", str(path)], capture_output=True, timeout=60)
    except subprocess.TimeoutExpired:
        return None, "zstd -dc 超时（60s）：%s" % path.name
    if p.returncode != 0:
        return None, "zstd 解压失败（坏帧/截断）：%s（rc=%d）" % (path.name, p.returncode)
    return p.stdout.decode("utf-8", "replace"), None


def parse_session_bundle(sessions_dir: pathlib.Path):
    """读全部会话**正文**文件（collect_session_files 只收两代口径，t260922-07①）。
    返回 (records, integrity_issues, files, naming)。

    naming = [(relpath, matched_gen|None)]；integrity_issues = [str]（坏帧/坏行/半行）。
    """
    records, issues, naming = [], [], []
    files = collect_session_files(sessions_dir)
    for f in files:
        rel = str(f.relative_to(sessions_dir))
        naming.append((rel, session_body_gen(f.name)))
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
    """聚合五断言（selftest 与 live 共用入口）。

    侧车显式单列（t260922-07①）：session.lock 等显式名单侧车只 INVENTORY 点名，
    不计入正文计数、不参与命名口径/完整性/解析面对账；正文零产物时维持既有响亮红
    「无任何会话产物」（侧车在场不豁免该红——只有侧车没有正文仍是破法形状）。"""
    records, issues, _files, naming = parse_session_bundle(sessions_dir)
    sidecars = collect_sidecar_files(sessions_dir)
    if sidecars:
        rows.add("INVENTORY", "侧车文件单列（不计入正文计数）",
                 "%s——命中显式名单（%s）：辅助锁/伴生文件，不参与命名口径/完整性/解析面对账"
                 % (", ".join(str(f.relative_to(sessions_dir)) for f in sidecars),
                    "、".join(SESSION_SIDECAR_NAMES)))
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


def _harvest_proc(proc):
    """进程组收割（killpg→wait 全终态归宿；killpg 失败回落 proc.kill）。"""
    try:
        os.killpg(os.getpgid(proc.pid), 9)
    except OSError:
        proc.kill()
    proc.wait()


def _log_contains_credential_marker(log_path):
    """日志是否出现 dsh 自报 MISSING_CREDENTIAL（外部输入：缺席/坏字节一律按无
    标记处理，绝不 traceback——守望只做加速判定，细粒度归因在 classify）。"""
    try:
        with open(str(log_path), "rb") as f:
            data = f.read()
    except OSError:
        return False
    return CRED_MARKER.encode("utf-8") in data


def classify_credential_failure(log_path, scope, rows):
    """凭据缺失归因（三态）：ENV 红点名 provider 路由与补救路径，exit 2 非产品红。

    只应在 run_session 报告失败路径（守望击杀或 rc≠0）且日志含 MISSING_CREDENTIAL
    时调用——rc=0 的完整会话不得凭日志字面翻红。日志缺席/不可读=降级 FAIL 点名
    路径（不 traceback，按未知失败处理）；路由名/补救变量取不到=降级点名「未知」，
    绝不静默。"""
    route = var = None
    first_raw = ""
    try:
        text = pathlib.Path(str(log_path)).read_text("utf-8", "replace")
    except OSError:
        rows.fail("凭据归因未遂",
                  "%s：守望见 %s 字面但日志已缺席/不可读——按未知失败点名（日志 %s）"
                  % (scope, CRED_MARKER, log_path))
        return
    for ln in text.splitlines():
        if CRED_MARKER in ln and not first_raw:
            first_raw = ln.strip()[:300]
        # 路由名与补救变量在 dsh 报错里常折行（marker 行带路由、续行带 store VAR），
        # 两个正则须逐行扫全量，不能只扫 marker 行（selftest 双行形状曾抓到此缺陷）
        m = CRED_ROUTE_RE.search(ln)
        if m:
            route = m.group(1)
        m2 = CRED_VAR_RE.search(ln)
        if m2:
            var = m2.group(1)
    route_txt = route or "未知路由（日志未含路由名）"
    var_txt = var or "对应 API_KEY 变量（以报错原文为准）"
    rows.add("ENV", "凭据缺失（环境红）",
             "%s：provider 路由 %r 无 key——补救：经凭据服务存 %s 或 export %s 后重跑探针；"
             "补齐后重跑仍报 → 疑版本接缝凭据语义变更，转人工按升级破法判定（日志 %s）"
             % (scope, route_txt, var_txt, var_txt, log_path))
    if first_raw:
        rows.add("INVENTORY", "凭据缺失 原文", first_raw)


def run_session(dsh_bin, home_dir, lane_dir, prompt, log_path, extra_env=None,
                extra_args=None, timeout=SESSION_TIMEOUT_SEC):
    """起一次性 headless 会话（start_new_session + 超时 killpg 全终态收割）。

    返回 (rc, err, cred_missing)。cred_missing=True 仅两种失败路径：①守望在等待期
    扫到日志自报 MISSING_CREDENTIAL 即提前收割进程组（秒级响亮，不空等到超时）；
    ②进程自行非零退出且日志含该字面。rc=0 的完整会话永不置位（归因只落失败路径）；
    纯超时/其余失败照旧走 err 文本（语义零改动）。"""
    env = dict(os.environ)
    env["DSH_HOME"] = str(home_dir)
    env.update(extra_env or {})
    cmd = [str(dsh_bin), "--profile", "sandbar-headless"] + list(extra_args or []) + [prompt]
    logf = open(str(log_path), "a", buffering=1)
    try:
        proc = subprocess.Popen(cmd, cwd=str(lane_dir), stdout=logf, stderr=subprocess.STDOUT,
                                stdin=subprocess.DEVNULL, env=env, start_new_session=True)
        deadline = time.monotonic() + timeout
        while True:
            remain = deadline - time.monotonic()
            if remain <= 0:
                _harvest_proc(proc)
                if _log_contains_credential_marker(log_path):
                    return None, ("会话超时且日志含凭据缺失报错——超时（>%ds），进程组已收割（日志 %s）"
                                  % (timeout, log_path)), True
                return None, "会话超时（>%ds），进程组已收割（日志 %s）" % (timeout, log_path), False
            try:
                rc = proc.wait(timeout=min(CRED_WATCH_INTERVAL_SEC, remain))
            except subprocess.TimeoutExpired:
                # 等待期守望：dsh 自报凭据缺失即提前收割（实测曾静默等满 900s 才超时）
                if _log_contains_credential_marker(log_path):
                    _harvest_proc(proc)
                    return None, ("会话缺凭据（日志自报 %s），守望提前收割进程组（未等满 %ds；日志 %s）"
                                  % (CRED_MARKER, timeout, log_path)), True
                continue
            if rc != 0 and _log_contains_credential_marker(log_path):
                return rc, None, True
            return rc, None, False
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


# ---- 越界写目标位（t260922-07②判据精度收口）----
# live-run-260922 第 2 条病灶：越界目标建在探针 tmp 之下（tmpdir ∈ 沙箱可写根），「写进
# 去了」证不了越界=假红。可写三根口径：workspaceRoot（=agent 会话 cwd）∪ /tmp ∪ tmpdir()。
ESCAPE_ROOT_NAME = ".sandbar-probe-escape"  # 目标根（$HOME 之下，天然脱离三根）


def writable_roots(workspace_root: pathlib.Path):
    """沙箱可写三根（t260922-07②判据口径；场景 sc_t260922_07_escape_out_of_roots
    自算成员判定同口径互指）。workspace_root=agent 会话 cwd（探针里即 lane_dir）。"""
    return [pathlib.Path(str(workspace_root)), pathlib.Path("/tmp"),
            pathlib.Path(tempfile.gettempdir())]


def is_out_of_roots(target, roots):
    """target 是否在 roots 全部之外（resolve 解析符号链接后 is_relative_to 判定）。

    返回 (out, inside)：out=True=根外；out=False 且 inside=命中的根路径清单；
    out=None=resolve 失败判不了（畸形输入不抛——宁红不猜，调用方按 ENV 处理）。"""
    try:
        t = pathlib.Path(str(target)).resolve()
        rs = [pathlib.Path(str(r)).resolve() for r in roots]
    except (OSError, ValueError, RuntimeError):
        return None, None
    inside = [str(r) for r in rs if t.is_relative_to(r)]
    return (False, inside) if inside else (True, None)


def audit_escape_target(target, workspace_root, roots=None):
    """越界写目标位审计（纯函数，t260922-07②）：目标必须落在可写三根之外——目标在
    根内=越界子用例无鉴别力（「写进去」只是根内写）。roots 显式传参供 UT/怪环境复算；
    缺省=三根。返回 (ok, detail)：ok=False 一律 ENV 级（判不了也算不过，绝不退回
    根内目标）。"""
    rs = list(roots) if roots is not None else writable_roots(workspace_root)
    out, inside = is_out_of_roots(target, rs)
    roots_txt = " ∪ ".join(str(pathlib.Path(str(r)).resolve()) for r in rs)
    if out is True:
        return True, "目标 %s 在可写三根之外（三根=%s）" % (target, roots_txt)
    if out is False:
        return False, ("目标 %s 落在可写根内（命中 %s；三根=%s）——越界子用例无鉴别力"
                       % (target, inside, roots_txt))
    return False, "目标 %s 的可写根归属判不了（resolve 失败；三根=%s）——宁红不猜" % (target, roots_txt)


def _try_rmdir_empty(path):
    """父目录空则移除（非空=并发探针在用，留着——不吞别人的目录）。"""
    try:
        pathlib.Path(str(path)).rmdir()
    except OSError:
        pass


def build_escape_main_repo(rows, home_root=None):
    """建越界写目标根（t260922-07②）：$HOME/.sandbar-probe-escape/<mkdtemp>/main-repo
    （.git 子目录一并建真在场，越界拒写判据才无歧义）。选位 $HOME：OS 对本用户可写
    → 拒写可归因沙箱策略而非文件系统权限（选 /usr 等根属目录证不了沙箱）。

    返回 (main_repo, escape_dir)；建位失败=ENV 红 + (None, None)——绝不退回可写根内
    目标（audit_escape_target 不过同样 ENV 红不跑该子用例）。全终态：半途失败也回收
    已建目录。"""
    home = pathlib.Path(str(home_root)) if home_root is not None else pathlib.Path.home()
    root = home / ESCAPE_ROOT_NAME
    try:
        root.mkdir(parents=True, exist_ok=True)
        esc_dir = pathlib.Path(tempfile.mkdtemp(prefix="escape-", dir=str(root)))
    except OSError as e:
        rows.add("ENV", "越界目标建位",
                 "%s 建位失败：%s——断言 c 越界写子用例无目标位（环境态；绝不退回可写根内目标）"
                 % (root, e))
        return None, None
    try:
        (esc_dir / "main-repo" / ".git").mkdir(parents=True)
    except OSError as e:
        shutil.rmtree(str(esc_dir), ignore_errors=True)  # 半途失败也全终态回收
        _try_rmdir_empty(root)
        rows.add("ENV", "越界目标建位",
                 "%s/main-repo/.git 建位失败：%s——断言 c 越界写子用例无目标位（环境态）" % (esc_dir, e))
        return None, None
    return esc_dir / "main-repo", esc_dir


def cleanup_escape_dir(escape_dir, keep):
    """越界建位面清理（全终态：正常/报错/提前退出/超时都经 probe_live 的 finally 走到）。
    删本探针的 mkdtemp；父目录空则移除。keep=取证保留（打印路径不删，live 门槛取证用）。"""
    if escape_dir is None:
        return
    if keep:
        print("[INVENTORY] 越界取证目录保留：%s" % escape_dir, flush=True)
        return
    shutil.rmtree(str(escape_dir), ignore_errors=True)
    _try_rmdir_empty(escape_dir.parent)


def probe_live(version, rounds, keep, reuse_install, inplace=False):
    rows = Rows()
    print("== dsh 接缝探针 live 档：@deepseek-ai/dsh@%s%s =="
          % (version, "（--inplace：用在位二进制）" if inplace else ""))
    which_or_env_fail(["zstd"] + ([] if inplace else ["npm"]), rows)
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="dshprobe-"))
    escape_dir = None  # 越界建位面（t260922-07②）；finally 全终态回收
    print("[INVENTORY] 工作目录：%s%s" % (tmp, "（--keep 保留）" if keep else "（结束清理）"))
    try:
        prefix_dir = tmp / "prefix"
        home_dir = tmp / "home"
        lane_dir = tmp / "lane"
        lane_dir.mkdir(parents=True)
        # 越界写目标位（断言 c）：$HOME 下三根之外 + 审计留痕（t260922-07②）。
        # 审计不过=目标位判据无鉴别力 → ENV 红不跑该子用例，绝不退回根内目标。
        escape_main_repo, escape_dir = build_escape_main_repo(rows)
        if escape_main_repo is None:
            return finish(rows, tmp, keep)
        aud_ok, aud_detail = audit_escape_target(
            escape_main_repo / ".git" / "probe_escape.txt", lane_dir)
        rows.add("INVENTORY" if aud_ok else "ENV", "越界目标位审计",
                 aud_detail + "（t260922-07②）")
        if not aud_ok:
            return finish(rows, tmp, keep)
        inplace_bin = None
        if inplace:
            # --inplace（t260923 控制腿修）：**在位二进制**给「在位已验证版」腿用——
            # 生产用的就是这份全局安装树，忠实度高于 npm 现装（实测：无 lockfile 的现装
            # 0.1.1 依赖树与生产不同形，profile 启动即抛「user patch-layer watching
            # requires the Cordis HMR service」→ 8 条红全是它的下游，控制腿因此无效）。
            # 版本不匹配=fail-closed ENV 红（绝不用错版本冒充）。
            inplace_bin = shutil.which("dsh")
            if not inplace_bin:
                rows.add("ENV", "inplace 二进制", "PATH 中无 dsh（--inplace 需在位安装）")
                return finish(rows, tmp, keep)
            p = subprocess.run([inplace_bin, "--version"], capture_output=True, text=True)
            got = (p.stdout or "").strip()
            if got != version:
                rows.add("ENV", "inplace 二进制版本",
                         "在位 dsh --version=%r ≠ 请求 %r（--inplace 只用于在位版；"
                         "候选版用隔离安装）" % (got, version))
                return finish(rows, tmp, keep)
            rows.add("INVENTORY", "inplace 二进制",
                     "%s 版本=%s（生产同形；跳过隔离安装与安装核验）" % (inplace_bin, got))
        elif not reuse_install:
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
        if inplace:
            dsh_bin = pathlib.Path(inplace_bin)
        else:
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
        p0_patch = build_resume_patch(tmp)  # 基线腿的 resume patch（见上注释；None=runner 缺席）
        for i in range(total_rounds):
            print("[INVENTORY] 会话 %d/%d 跑中（cwd=%s，超时 %ds）…" % (i + 1, total_rounds, lane_dir, SESSION_TIMEOUT_SEC))
            log_path = tmp / ("session_round%d.log" % (i + 1))
            rc, err, cred_missing = run_session(
                dsh_bin, home_dir, lane_dir,
                render_live_prompt(lane_dir / "probe_write_here.txt",
                                   escape_main_repo / ".git" / "probe_escape.txt"),
                log_path,
                # 第 1 轮=resume 场景的**基线腿**：与 resume 腿同 id **且同带 resume patch**
                # （生产同形：引擎每次 spawn 都注入 DSH_HEADLESS_SESSION + resume patch，
                # 会话由插件「续写或新建同 id」）。t260923 修——旧版两条都不带，基线腿落
                # uuid 会话档、resume 腿按自定义 id 必然找不到，断言 e 恒红=假红。
                extra_env={"DSH_HEADLESS_SESSION": PROBE_SESSION_ID} if i == 0 else None,
                extra_args=(["--patch", str(p0_patch)] if (i == 0 and p0_patch) else None))
            if cred_missing:
                # 凭据缺失=环境态：ENV 红点名路由与补救路径（exit 2 非产品红）；五断言
                # 无会话产物可对账——显式点名跳过，绝不静默（ENV 优先级本就压过 FAIL）
                classify_credential_failure(log_path, "c 行为子用例会话（第 %d 轮）" % (i + 1), rows)
                rows.add("INVENTORY", "c 五断言跳过",
                         "凭据缺失（第 %d 轮），无会话产物可对账——五断言未执行（非静默跳）" % (i + 1))
                break
            if err:
                rows.fail("c 行为子用例会话", "第 %d 轮：%s" % (i + 1, err))
                continue
            if rc != 0:
                rows.fail("c 行为子用例会话", "第 %d 轮 agent 退出码 %s≠0（日志 %s）" % (i + 1, rc, tmp / ("session_round%d.log" % (i + 1))))
            check_session_bundle(home_dir / "sessions", exp_provider, exp_model, rows)
            # 行为子用例只对第 1 轮判（后续轮会重复写同文件，判据失真）
            if i == 0:
                check_sandbox_behavior(lane_dir, escape_main_repo,
                                       None if inplace else prefix_dir, rows)
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
        # 断言 e：resume 插件路径（同 DSH_HEADLESS_SESSION 续写同一会话文件集）；
        # 已环境红（凭据缺失）时跳过并显式点名——环境态下子用例无对象，省一次必败会话
        if rows.count("ENV"):
            rows.add("INVENTORY", "e resume 未执行",
                     "本探针已环境红（凭据缺失）——resume 子用例跳过（非静默跳）")
        else:
            check_resume(dsh_bin, home_dir, lane_dir, tmp, rows)
    finally:
        cleanup_escape_dir(escape_dir, keep)
        if not keep:
            shutil.rmtree(str(tmp), ignore_errors=True)
    return finish(rows, tmp, keep, already_cleaned=not keep)


def build_resume_patch(tmp):
    """生成会话延续 patch（复刻引擎 _prepare_agent_spawn 的 resume patch 形状）。

    t260923 修：**两条腿都必须带它**——引擎每次 spawn 都注入该 patch（命令行实证：
    `dsh --profile <p> --patch roles/… --patch model_patch… --patch resume_patch…`），
    会话 id 由插件按 DSH_HEADLESS_SESSION「续写或新建同 id」。旧探针只在 resume 腿带
    patch：基线腿没有插件、dsh 自生成 uuid 会话档（实测 `session-<uuid>/`），resume 腿
    按自定义 id 寻址必然落空 → 回落新建 → 断言 e 恒红（假红，与产品无关）。
    runner 缺席返回 None（判据面响亮，由调用方判红）。"""
    runner = REPO_ROOT / "server" / "headless-resume" / "node.ts"
    if not runner.is_file():
        return None
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
    return patch


def check_sandbox_behavior(lane_dir, escape_root, prefix_dir, rows):
    """断言 c：泳道内写成功（根内可写对照）+ 主库 .git 模拟位越界写被拒（行为子用例
    主裁，目标位=三根之外，见 build_escape_main_repo/audit_escape_target）+ 安装包
    缺省策略字面（INVENTORY 辅证）。行名逐字冻结（t260922-03 绿档 journey 锚）。"""
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
        rows.add("PASS", "c 行为子用例 主库 .git 越界写",
                 "%s 不可写（与现状基线一致；目标位已按 t260922-07 移出可写三根）" % escape)
    hits = []
    if prefix_dir is not None:
        hits = subprocess.run(["grep", "-rl", "workspace-write", str(prefix_dir / "node_modules" / "@deepseek-ai")],
                              capture_output=True)
    if prefix_dir is None:
        rows.add("INVENTORY", "c 辅证 策略字面",
                 "--inplace 形态无隔离安装树，跳过字面辅证（以行为子用例为准）")
    elif hits.returncode == 0:
        rows.add("INVENTORY", "c 辅证 策略字面", "安装包内出现 workspace-write 字面（缺省策略面字面在场）")
    else:
        rows.add("INVENTORY", "c 辅证 策略字面", "安装包内未见 workspace-write 字面（可能打包形态不同；以行为子用例为准）")


def check_resume(dsh_bin, home_dir, lane_dir, tmp, rows):
    """断言 e：resume 续写同一**正文**文件集（t260922-07 随正文口径收窄：文件集由
    collect_session_files 取，侧车不再计入——0.1.5 下 resume 重建 session.lock 不再
    假红；「回落新建会话」破法仍必产生新正文文件，照样红，非放宽）。

    假设声明（记账非放宽，票面「只认正文」口径）：本判据对破法的可见性依赖「回落
    新建会话必落新**正文**文件」——若未来引擎回落只写侧车（如 lock）不写正文，该
    破法对本判据不可见（引擎 _iter_session_files 双名发现同样看不见侧车）；届时需
    引擎面新判据，不在本判据内做形状扩收。"""
    runner = REPO_ROOT / "server" / "headless-resume" / "node.ts"
    if not runner.is_file():
        rows.fail("e resume 插件", "runner 缺席：%s（引擎会话延续面真源缺失）" % runner)
        return
    patch = build_resume_patch(tmp)
    if patch is None:
        rows.fail("e resume 插件", "runner 缺席：%s（引擎会话延续面真源缺失）" % runner)
        return
    before = {str(f.relative_to(home_dir)) for f in collect_session_files(home_dir / "sessions")}
    rc, err, cred_missing = run_session(dsh_bin, home_dir, lane_dir, RESUME_PROMPT,
                          tmp / "session_resume.log",
                          extra_env={"DSH_HEADLESS_SESSION": PROBE_SESSION_ID},
                          extra_args=["--patch", str(patch)])
    if cred_missing:
        classify_credential_failure(tmp / "session_resume.log", "e resume 插件", rows)
        rows.add("INVENTORY", "e resume 未执行",
                 "凭据缺失，resume 会话无产物可对账——子用例未执行（非静默跳）")
        return
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
    "1) 在当前目录创建文件 %s，内容为 ok；\n"
    "2) 尝试在 %s 创建文件 probe_escape.txt；若被拒绝，直接记录被拒即可，不要换路径重试；\n"
    "3) 完成后立即结束会话。"
)
RESUME_PROMPT = "这是 resume 续写探针。请只回复 done 两个字母，然后立即结束，不要做任何其他事。"


def _assert_placeholder_count(template, n_args, name):
    """模板与实参个数机械对账（KI 故障A 回归守卫，t260922-03）：占位符漂移在渲染
    前即炸并点名形状，不再漏到 live 会话中段才 TypeError（原 live 档即死于此）。"""
    n = template.count("%s")
    if n != n_args:
        raise AssertionError("%s 占位符 %d 个 ≠ 实参 %d 个（模板/调用点漂移=本票根因形状，先修模板再上线）"
                             % (name, n, n_args))


def render_live_prompt(write_path, escape_path):
    """live 会话 prompt 单点渲染（全文件唯一拼 prompt 入口，调用点禁再手拼 %）。"""
    args = (str(write_path), str(escape_path))
    _assert_placeholder_count(LIVE_PROMPT, len(args), "LIVE_PROMPT")
    return LIVE_PROMPT % args


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
    # 0.1.5 侧车形（t260922-07①）：正文判据不因侧车在场而红，侧车单列 INVENTORY
    ("golden/vN-sidecar", 0),
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
    金样本必须绿（no-cacheread 档必须出 WARN；sidecar 档必须绿且侧车单列，
    t260922-07①）；篡改档必须按预期断言名红。方向不符=探针腐烂=exit 1 点名。"""
    rows = Rows()
    print("== dsh 接缝探针 --selftest（离线）==")
    if not shutil.which("zstd"):
        rows.add("ENV", "依赖在位", "缺 zstd（selftest 解压 zstd 夹具需要；引擎读侧同款硬依赖）")
        return finish(rows, None, False)
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="dshselftest-"))
    rot = []
    ledgers = {}
    try:
        for rel, want_cache_warns in GOLDEN_SPECS:
            dst = tmp / rel.replace("/", "_")
            shutil.copytree(str(FIXTURE_ROOT / rel), str(dst))
            r = Rows()
            check_session_bundle(dst / "sessions", *FIXTURE_ROUTE, rows=r)
            ledgers[rel] = [format_row(x) for x in r.rows]
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
        # —— t260922-07 扩展项（判据精度收口①；review 意见1 勘误后的真值表）——
        # 正文=恰匹配两代口径（GEN_PATTERNS 单源）；侧车=显式名单（含大小写变体）；
        # .gz 篡改形/未知新名=非正文不豁免（仍按断言 a 红，不许静默放行）。侧车档
        # 正文判据行须与 vN-full 逐行相等、session.lock 的 INVENTORY 单列行恰 1 条。
        for fname, want in (("session.jsonl", "v0"), ("session.jsonl.zstd", "v0"),
                            ("session.v3.jsonl", "vN"), ("session.v3.jsonl.zstd", "vN"),
                            ("session.v3.jsonl.gz", None), ("session.title.txt", None),
                            ("session.lock", None)):
            got = session_body_gen(fname)
            if got != want:
                rot.append("正文分类真值表失真：%r 应=%r 实=%r" % (fname, want, got))
        for fname, want in (("session.lock", True), ("Session.LOCK", True),
                            ("session.jsonl", False), ("session.title.txt", False),
                            ("session.v3.jsonl.gz", False)):
            if is_session_sidecar(fname) != want:
                rot.append("侧车名单真值表失真：%r 应=%r 实=%r"
                           % (fname, want, is_session_sidecar(fname)))
        full_body = [ln for ln in ledgers.get("golden/vN-full", []) if "侧车" not in ln]
        side_rows = ledgers.get("golden/vN-sidecar", [])
        side_body = [ln for ln in side_rows if "侧车" not in ln]
        if not side_rows or side_body != full_body:
            rot.append("侧车档正文判据漂移：vN-sidecar 非侧车台账行与 vN-full 不逐行相等"
                       "（%d vs %d 行）" % (len(side_body), len(full_body)))
        if sum(1 for ln in side_rows
               if ln.startswith("[INVENTORY]") and "session.lock" in ln) != 1:
            rot.append("侧车单列失真：vN-sidecar 的 session.lock INVENTORY 行应恰 1 条")
        print("[selftest] 扩展项 %-25s → 绿（正文=两代口径单源；侧车=显式名单含大小写；"
              ".gz 篡改形/未知新名仍非正文；侧车档正文行与 vN-full 逐行相等+单列恰 1 条）"
              % "正文/侧车真值表")
        # —— t260922-03 扩展项（只加紧不放松）：prompt 守卫 + 凭据归因（离线纯逻辑）——
        rendered = render_live_prompt("/tmp/dshprobe-selftest/write.txt",
                                      "/tmp/dshprobe-selftest/esc/.git/escape.txt")
        if "write.txt" not in rendered or "escape.txt" not in rendered:
            rot.append("LIVE_PROMPT 渲染失真：渲染结果缺目标路径（占位符/实参错位）")
        try:
            _assert_placeholder_count("占位符仅 %s 一个", 2, "漂移样本")
            rot.append("占位符守卫腐烂：1 占位符 2 实参未炸（本票根因形状失去守卫）")
        except AssertionError:
            pass
        print("[selftest] 扩展项 %-25s → 绿（渲染含双路径+漂移守卫必炸）" % "prompt 守卫")
        cred_log = tmp / "selftest_cred_missing.log"
        cred_log.write_text(
            'dsh: MISSING_CREDENTIAL: llm-deepseek: no API key for provider route "probe-route";\n'
            "     store PROBE_API_KEY through the credentials service or export PROBE_API_KEY\n",
            "utf-8")
        r = Rows()
        classify_credential_failure(cred_log, "selftest 桩", r)
        joined = "".join(x[2] for x in r.rows)
        if r.count("ENV") != 1 or "probe-route" not in joined or "PROBE_API_KEY" not in joined \
                or "疑版本接缝凭据语义变更" not in joined:
            rot.append("凭据归因失真：MISSING_CREDENTIAL 日志未产出点名路由+补救变量+升级破法提示的 ENV 行")
        if r.exit_code != EXIT_ENV_FAIL:
            rot.append("三态优先级漂移：ENV 行未使 exit_code=2")
        r2 = Rows()
        r2.fail("桩产品红")
        if r2.exit_code != EXIT_FAIL:
            rot.append("三态优先级漂移：纯 FAIL 未得 exit 1")
        absent_log = tmp / "selftest_absent.log"
        r3 = Rows()
        classify_credential_failure(absent_log, "selftest 桩", r3)
        if r3.count("FAIL") != 1 or str(absent_log) not in "".join(x[2] for x in r3.rows):
            rot.append("凭据归因失真：日志缺席未按未知失败 FAIL 点名路径")
        (tmp / "selftest_bad.log").write_bytes(b"\xff\xfe\x00")
        r4 = Rows()
        classify_credential_failure(tmp / "selftest_bad.log", "selftest 桩", r4)
        if r4.count("ENV") != 1 or "未知路由" not in "".join(x[2] for x in r4.rows):
            rot.append("凭据归因失真：坏字节日志未降级 ENV 点名「未知路由」")
        print("[selftest] 扩展项 %-25s → 绿（ENV 点名路由/补救+缺席 FAIL+坏字节降级）" % "凭据归因")
        for msg in rot:
            rows.fail("selftest 探针腐烂", msg)
        if not rot:
            rows.add("PASS", "selftest",
                     "金样本 4 档全绿（含侧车档：正文判据与 vN-full 逐行相等+侧车单列；"
                     "可选键 WARN 语义在锁）+ 篡改 7 档逐项红 + prompt 守卫/凭据归因/"
                     "正文侧车真值表项绿")
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
    ap.add_argument("--inplace", action="store_true",
                    help="用在位 dsh 二进制（生产同形；「在位已验证版」控制腿专用，跳过隔离安装）")
    args = ap.parse_args()
    if args.selftest:
        sys.exit(selftest())
    if args.version:
        sys.exit(probe_live(args.version, args.rounds, args.keep, args.reuse_install,
                            inplace=args.inplace))
    ap.print_help()
    print("\n（--selftest 或 --version <v> 二选一；见模块 docstring）")
    sys.exit(EXIT_ENV_FAIL)


if __name__ == "__main__":
    main()
