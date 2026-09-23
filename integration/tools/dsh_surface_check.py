#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""dsh_surface_check.py —— 「我们的插件/配置面」对「目标 dsh 版本真实定义」的机械对账。

为什么存在（260923 三次事故的共同病根）：升级 dsh 时，**平台面**变了而我们这边没人对账——
  ① 客户端服务迁移：`workspaces.startSession` → `uiWorkspace.startSession`（0.1.5 拆服务），
     旧调用在全项目「新建会话」上抛 TypeError；
  ② cordis 属性访问纪律：未写进 `inject` 的服务**不能以属性形式访问**（抛
     `cannot get property "X" without inject`），实弹把整条侧栏条目打崩；
  ③ 配置键改名：`dsh-persona` 的 `text:` → `prefix:`（required）、
     `dsh-system-prompt` 的 `persona:` → `personaPrefix/personaSuffix`（有默认值＝**静默丢弃**）；
  ④ 槽注册选项：`kind: list` 的槽注册必须带 `id`（我们的度量入口因此被静默降级）。

本脚本把这四类做成可在**升级前**跑的一次性对账（只读、零网络、零 dsh 启动）：
  A 服务面：我们插件 inject 的服务名必须存在于目标 dsh；
  B 访问纪律：插件里 `ctx.X` 的属性访问必须已在 inject 里声明；
  C 槽选项：往 `kind: list` 的槽注册必须带 `id`；
  D 配置键：roles patch / profile patch / GUI preset 里对某平台包用的 config 键，
    必须在该包目标版的 Config schema 里（没有＝会被静默忽略或挂载即抛）；
  E 客户端模块：插件 package.json 的 `dsh.client.inject` 点名的包必须存在。

用法：
  python3 integration/tools/dsh_surface_check.py                 # 目标 = project.yaml 的 paths.dsh_bin（回退 PATH 上的 dsh）
  python3 integration/tools/dsh_surface_check.py --dsh-root /path/to/@deepseek-ai/dsh
  python3 integration/tools/dsh_surface_check.py --json          # 机读输出（给场景/CI 用）
退出码：0=全过；1=有★项（打印逐条原因与定位）；2=用法/环境错（目标 dsh 找不到）。
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

REPO = pathlib.Path(__file__).resolve().parents[2]


# ── 目标 dsh 定位 ────────────────────────────────────────────────────────────
def dsh_root_from_project_yaml() -> pathlib.Path | None:
    """读 <projects>/sandbar/project.yaml 的 paths.dsh_bin，定位其安装根。"""
    cands = [
        pathlib.Path.home() / ".sandbar" / "projects" / "sandbar" / "project.yaml",
    ]
    for f in cands:
        if not f.is_file():
            continue
        m = re.search(r"^\s*dsh_bin:\s*(\S+)\s*$", f.read_text(encoding="utf-8"), re.M)
        if not m:
            continue
        return pkg_root_of(pathlib.Path(m.group(1)).expanduser())
    return None


def pkg_root_of(bin_path: pathlib.Path) -> pathlib.Path | None:
    """从 bin 路径定位 `<root>/lib/node_modules/@deepseek-ai/dsh`（软链先解）。"""
    p = bin_path
    seen = 0
    while p.is_symlink() and seen < 10:
        t = os.readlink(p)
        p = (p.parent / t).resolve() if not os.path.isabs(t) else pathlib.Path(t)
        seen += 1
    m = re.match(r"^(.*/node_modules/@deepseek-ai/dsh)(/.*)?$", str(p))
    return pathlib.Path(m.group(1)) if m else None


def resolve_dsh_root(explicit: str | None) -> pathlib.Path:
    if explicit:
        p = pathlib.Path(explicit).expanduser()
        root = p if p.name == "dsh" and "node_modules" in str(p) else pkg_root_of(p)
        if root is None or not root.is_dir():
            print(f"用法红：--dsh-root 不是有效的 dsh 安装（{explicit}）", file=sys.stderr)
            sys.exit(2)
        return root
    root = dsh_root_from_project_yaml()
    if root is None or not root.is_dir():
        which = shutil.which("dsh")
        root = pkg_root_of(pathlib.Path(which)) if which else None
    if root is None or not root.is_dir():
        print("环境红：找不到目标 dsh（project.yaml 无 paths.dsh_bin，PATH 上也没有 dsh）", file=sys.stderr)
        sys.exit(2)
    return root


# ── 目标 dsh 的「平台真实定义」提取（全部文本近似，够用且零依赖）────────────
def platform_pkgs(root: pathlib.Path) -> pathlib.Path:
    return root / "node_modules" / "@deepseek-ai"


def provided_services(root: pathlib.Path) -> dict[str, set[str]]:
    """服务名 → 提供它的包（扫 super(ctx,"X") / new Service(ctx,"X")）。"""
    out: dict[str, set[str]] = {}
    pat = re.compile(r"(?:super|new\s+Service)\(\s*(?:this\.)?ctx\s*,\s*[\"']([A-Za-z][\w]*)[\"']\s*\)")
    for f in list(platform_pkgs(root).glob("*/lib/*.js")):
        for m in pat.finditer(f.read_text(encoding="utf-8", errors="ignore")):
            out.setdefault(m.group(1), set()).add(f.parent.parent.name)
    return out


def slot_kinds(root: pathlib.Path) -> dict[str, str]:
    """槽名 → kind（扫 `"<name>": { kind: "list|single" ... }`）。"""
    out: dict[str, str] = {}
    pat = re.compile(r"[\"']([a-zA-Z][\w.\-]*\.[\w.\-]+)[\"']\s*:\s*\{\s*kind:\s*[\"'](list|single)[\"']")
    for f in list(platform_pkgs(root).glob("*/lib/*.js")):
        for m in pat.finditer(f.read_text(encoding="utf-8", errors="ignore")):
            out.setdefault(m.group(1), m.group(2))
    return out


def config_keys(root: pathlib.Path) -> dict[str, set[str]]:
    """平台包名 → 其 Config schema 的键集合（从 `z.object({...})` 平衡括号截取）。"""
    out: dict[str, set[str]] = {}
    for d in sorted(platform_pkgs(root).iterdir()):
        if not d.is_dir():
            continue
        keys: set[str] = set()
        for f in list(d.glob("lib/*.js")):
            src = f.read_text(encoding="utf-8", errors="ignore")
            for m in re.finditer(r"(?:static\s+Config\s*=\s*)?[A-Za-z_$][\w$]*\s*=\s*z\.object\(\s*\{", src):
                i = src.index("{", m.start())
                depth, j = 0, i
                while j < len(src):
                    if src[j] == "{":
                        depth += 1
                    elif src[j] == "}":
                        depth -= 1
                        if depth == 0:
                            break
                    j += 1
                body = src[i + 1 : j]
                # 只取顶层键：按行首缩进近似（schema 字面量一般一格一键一行）
                for km in re.finditer(r"^\s*([A-Za-z_$][\w$]*)\s*:", body, re.M):
                    keys.add(km.group(1))
        if keys:
            out[d.name] = keys
    return out


# ── 我们这一侧 ───────────────────────────────────────────────────────────────
def strip_comments(s: str) -> str:
    s = re.sub(r"/\*.*?\*/", "", s, flags=re.S)
    return re.sub(r"^\s*//.*$", "", s, flags=re.M)


CTX_METHODS = {
    "get", "set", "on", "off", "emit", "effect", "logger", "fiber", "scope", "slots", "remote",
    "plugin", "inject", "provide", "isolate", "extend", "waterfall", "bail", "parallel", "serial",
    "start", "stop", "update", "root", "baseUrl",
}


def our_plugins() -> list[pathlib.Path]:
    return sorted(p for p in (REPO / "server" / "plugins").glob("*/src/client") if p.is_dir())


def scan_plugin(d: pathlib.Path) -> dict:
    src = "\n".join(
        strip_comments(f.read_text(encoding="utf-8", errors="ignore"))
        for f in list(d.glob("*.tsx")) + list(d.glob("*.ts"))
    )
    m = re.search(r"export const inject\s*=\s*\[([^\]]*)\]", src)
    inject = {s.strip().strip("'\"") for s in m.group(1).split(",")} if m else set()
    inject = {s for s in inject if s}
    accesses = set(re.findall(r"\bctx\.([a-z][A-Za-z0-9_]*)", src))
    regs = []
    for m in re.finditer(r"register\(\s*\{(.{0,400}?)\}\s*,", src, re.S):
        body = m.group(1)
        nm = re.search(r"name:\s*'([^']+)'", body)
        if nm:
            regs.append({"slot": nm.group(1), "has_id": bool(re.search(r"\bid:", body))})
    pkgjson = d.parent.parent / "package.json"
    client_inject = []
    if pkgjson.is_file():
        try:
            client_inject = (json.loads(pkgjson.read_text(encoding="utf-8")).get("dsh", {})
                             .get("client", {}) or {}).get("inject", []) or []
        except Exception:
            pass
    return {
        "name": d.parent.parent.name,
        "dir": str(d.parent.parent.relative_to(REPO)),
        "inject": sorted(inject),
        "property_accesses": sorted(accesses - inject - CTX_METHODS),
        "registrations": regs,
        "client_inject": client_inject,
    }


def our_configs(repo: pathlib.Path) -> list[dict]:
    """收集我们写的、会被 dsh 解析的配置（roles patch / profile patch / GUI preset）。"""
    found: list[dict] = []
    files: list[tuple[pathlib.Path, str]] = []
    for f in sorted((repo / "server" / "roles").glob("*.yml")):
        files.append((f, "roles patch（headless agent 的角色说明书载体）"))
    for f in sorted((repo / "server").glob("profile*/cordis.patch.yml")):
        files.append((f, "profile patch（控制台/worker 挂插件）"))
    presets = pathlib.Path.home() / ".dsh" / ".agent-presets"
    if presets.is_dir():
        for d in sorted(presets.iterdir()):
            f = d / "agent.cordis.yml"
            if f.is_file():
                tag = "GUI preset（机器级，升级后需重建）" + ("【备份目录】" if ".bak" in d.name else "")
                files.append((f, tag))
    for f, tag in files:
        text = f.read_text(encoding="utf-8", errors="ignore")
        lines = text.split("\n")
        for i, ln in enumerate(lines):
            m = re.match(r"^(\s*)name:\s*'(@deepseek-ai/[^']+)'", ln)
            if not m:
                continue
            name_indent, pkg = len(m.group(1)), m.group(2).split("/")[-1]
            # 条目边界：`name:` 之后、第一条「缩进 ≤ name 缩进」的非空行之前（防把下一个
            # 条目的 config 记到本条头上——260923 实证过这个误报：出厂 preset 里
            # thresholdChars 属于 tool-result-pruner，却算给了前一个 compaction-basic）
            block: list[str] = []
            for nxt in lines[i + 1:]:
                if nxt.strip() == "":
                    block.append(nxt)
                    continue
                ind = len(nxt) - len(nxt.lstrip())
                # 新条目（同级 `- `）或整体左出条目缩进 → 条目结束；
                # 同级非列表键（如 config:）仍属本条目
                if ind < name_indent or (ind == name_indent and re.match(r"^\s*-\s", nxt)):
                    break
                block.append(nxt)
            body = "\n".join(block)
            cm = re.search(r"^\s*config:\s*$\n((?:[ \t]+.*\n|\s*\n)*)", body, re.M)
            if not cm:
                continue
            base = len(cm.group(0).split("\n")[0]) - len(cm.group(0).split("\n")[0].lstrip())
            keys = sorted({k for ind, k in re.findall(r"^(\s*)([A-Za-z_$][\w$]*)\s*:", cm.group(1), re.M)
                           if len(ind) > base and not ind.lstrip().startswith("-")})
            if keys:
                found.append({"file": str(f), "tag": tag, "pkg": pkg, "keys": keys})
    return found


# ── 检查 ────────────────────────────────────────────────────────────────────
def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dsh-root")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    root = resolve_dsh_root(args.dsh_root)
    services = provided_services(root)
    kinds = slot_kinds(root)
    schemas = config_keys(root)
    pkgdir = platform_pkgs(root)
    have_pkgs = {p.name for p in pkgdir.iterdir() if p.is_dir()}

    findings: list[str] = []
    report: dict = {"dsh_root": str(root), "checks": {}, "findings": findings}

    def line(ok: bool, text: str) -> None:
        if not args.json:
            print(("  ok   " if ok else "  ★    ") + text)

    if not args.json:
        print(f"== 目标 dsh：{root} ==")
        print(f"   平台服务名 {len(services)} 个 / 槽 {len(kinds)} 个 / 有 schema 的包 {len(schemas)} 个\n")
        print("A/B/C. 插件面（服务名、访问纪律、槽选项）")

    for p in our_plugins():
        info = scan_plugin(p)
        report["checks"].setdefault("plugins", {})[info["name"]] = info
        # A 服务面
        unknown = [s for s in info["inject"] if s not in services]
        if unknown:
            findings.append(f"[A] {info['name']} inject 了目标 dsh 不提供的服务：{unknown}")
        line(not unknown, f"{info['name']}: inject {info['inject']} 全部存在" if not unknown
             else f"{info['name']}: ★ inject 含目标版没有的服务 {unknown}（entry 会永久 pending）")
        # B 访问纪律
        if info["property_accesses"]:
            findings.append(f"[B] {info['name']} 以属性形式访问未 inject 的服务：{info['property_accesses']}"
                            "（cordis 抛 cannot get property … without inject；抛在渲染期会打崩整条槽条目）")
        line(not info["property_accesses"],
             f"{info['name']}: 无未 inject 的属性访问" if not info["property_accesses"]
             else f"{info['name']}: ★ 未 inject 的属性访问 {info['property_accesses']}")
        # C 槽选项
        for r in info["registrations"]:
            kind = kinds.get(r["slot"])
            need_id = kind == "list"
            bad = need_id and not r["has_id"]
            if bad:
                findings.append(f"[C] {info['name']} 往 list 槽 {r['slot']} 注册未带 id（平台要求 options.id，否则静默降级）")
            label = f"{info['name']}: 槽 {r['slot']}（kind={kind or '未知'}）" + ("带 id" if r["has_id"] else "未带 id")
            line(not bad, label if not bad else label + " ★ list 槽必须带 id")
        # E 客户端模块声明
        missing = [c for c in info["client_inject"]
                   if c.startswith("@deepseek-ai/") and c.split("/")[-1] not in have_pkgs]
        if missing:
            findings.append(f"[E] {info['name']} package.json 的 dsh.client.inject 点名目标版已不存在的包：{missing}")
        line(not missing, f"{info['name']}: client.inject 点名的包都在" if not missing
             else f"{info['name']}: ★ client.inject 点名不存在的包 {missing}")

    if not args.json:
        print("\nD. 配置键（roles patch / profile patch / GUI preset × 目标版 schema）")
    for c in our_configs(REPO):
        allowed = schemas.get(c["pkg"])
        if allowed is None:
            line(True, f"{c['file'].split('/')[-1]}: 包 {c['pkg']} 未取到 schema（跳过键对账）")
            continue
        bad = [k for k in c["keys"] if k not in allowed]
        report["checks"].setdefault("configs", []).append({**c, "unknown_keys": bad})
        if bad:
            findings.append(f"[D] {c['file']} 对 {c['pkg']} 用了目标版 schema 里没有的键 {bad}"
                            f"（有默认值＝静默丢弃；required＝挂载即抛）；该文件用途＝{c['tag']}")
        line(not bad, f"{c['file'].replace(str(pathlib.Path.home()), '~')} → {c['pkg']} 键 {c['keys']} 全在 schema"
             if not bad else
             f"{c['file'].replace(str(pathlib.Path.home()), '~')} → ★ {c['pkg']} 不认识 {bad}（用途：{c['tag']}）")

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(f"\n== 结果：{'绿' if not findings else '红'}（{len(findings)} 条待处置）==")
        for f in findings:
            print("   ★ " + f)
        print("\n提示：A/B/C/D/E 任一条红都属「升级前必须对账」项——它们的共同特征是"
              "**上游改了平台面，我们这边不会有编译错误、也不会有测试红**。")
    return 0 if not findings else 1


if __name__ == "__main__":
    sys.exit(main())
