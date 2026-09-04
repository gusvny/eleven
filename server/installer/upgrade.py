"""sandbar upgrade：契约⑧消费面——区间展示、版本 diff、必查项命中清单。

纪律（工单正文③ + §3）：
- 只读：本命令永远只做展示与预检演练，真实升版执行归 M2-D 切换票；
- 数据源=仓内契约真源 docs/design/sandbar项目接入契约v1.md（260904 宿主裁定
  本仓为真源，见契约头部声明与变更记录 v1.8）；缺⑧节 / 无已验证点 /
  必查项不足四条 / 坏格式 = ContractError 红；
- `--to <ver>` 畸形态全 fail-closed：坏 semver / 降版本请求 / 当前 VERSION 脏（契约⑧-4）。
"""

from __future__ import annotations

import pathlib
import re

from version import VersionError, parse_semver, read_version

CONTRACT_REL = pathlib.Path("docs") / "design" / "sandbar项目接入契约v1.md"

# ⑧-2 必查项 → 探针覆盖映射（touchpoints 代号 → 探针；None=本票无探针，须人工复扫）
TOUCHPOINT_PROBES = {
    "A3": "probe-settings-resolve",
    "A4": "probe-runner-assembly",
    "A5": "probe-runner-assembly",
    "B1": "probe-home-layout",
    "C1": "probe-session-format",
    "C2": "probe-session-format",
    "D1": None,  # headless SIGTERM 语义：无 fixture 探针，升版时人工复扫
}

_SEMVERISH = re.compile(r"\b\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?\b")
_HEADING = re.compile(r"^###\s+⑧\s+.*schema:\s*(\S+?)\s*[，,）)].*$", re.M)
_CHECK_ITEM = re.compile(r"^\d+\.\s+\*\*(.+?)\*\*（([^）]*)）", re.M)
_TOUCHPOINT_CODE = re.compile(r"\b([ABCD]\d)\b")


class ContractError(RuntimeError):
    """契约副本缺失/缺⑧节/坏格式——fail-closed 红。"""


def contract_path(root) -> pathlib.Path:
    return pathlib.Path(root) / CONTRACT_REL


def load_contract_text(root, path=None) -> str:
    p = pathlib.Path(path) if path is not None else contract_path(root)
    try:
        return p.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise ContractError("契约副本缺失：%s（同源副本真源在 suyou 仓同名路径）" % p)
    except (IsADirectoryError, PermissionError, UnicodeDecodeError) as e:
        raise ContractError("契约副本不可读：%s（%s）" % (p, e))


def parse_contract(text: str) -> dict:
    """⑧节结构化：schema 版本 + 已验证点 + 必查项四条。任何缺口=ContractError。"""
    m = _HEADING.search(text)
    if not m:
        raise ContractError("契约副本缺⑧节（或标题行坏格式，应含 `### ⑧ … schema: vN …`）")
    schema = m.group(1)
    start = m.end()
    nxt = text.find("\n### ", start)
    section = text[start: nxt if nxt >= 0 else len(text)]

    m81 = re.search(r"\*\*⑧-1.*?\*\*", section)
    m82 = re.search(r"\*\*⑧-2.*?\*\*", section)
    m83 = re.search(r"\*\*⑧-3.*?\*\*", section)
    if not (m81 and m82 and m83):
        raise ContractError("⑧节残缺：⑧-1/⑧-2/⑧-3 小节标头缺失")
    block81 = section[m81.end(): m82.start()]
    points = sorted(set(_SEMVERISH.findall(block81)))
    if not points:
        raise ContractError("⑧-1 无已验证点（区间列举制不允许空区间）")
    block82 = section[m82.end(): m83.start()]
    items = []
    for title, paren in _CHECK_ITEM.findall(block82):
        # 契约原文括注形态不一：`（touchpoints A3）` / `（A4/A5）` / `（D1）`——
        # 统一抽 touchpoints 代号，抽不到=副本坏格式红。
        codes = _TOUCHPOINT_CODE.findall(paren)
        if not codes:
            raise ContractError("⑧-2 必查项括注缺 touchpoints 代号（%s）" % title[:40])
        items.append({"title": title.strip(), "touchpoints": " ".join(codes),
                      "codes": codes})
    if len(items) < 4:
        raise ContractError("⑧-2 必查项不足四条（实得 %d）——副本坏格式，fail-closed" % len(items))
    return {"schema": schema, "points": points, "checks": items}


def load_contract(root, path=None) -> dict:
    return parse_contract(load_contract_text(root, path))


def coverage(contract: dict):
    """必查项 → 探针命中清单。返回 [(check, [probe|None])]，长度恒=条数。"""
    out = []
    for check in contract["checks"]:
        probes = []
        for code in check["codes"]:
            p = TOUCHPOINT_PROBES.get(code)
            if p and p not in probes:
                probes.append(p)
        out.append((check, probes))
    return out


def precheck(target, root, version_path=None):
    """--to 预检：坏 semver / 降版本 / 当前 VERSION 脏 全红。返回 (current, target)。"""
    current = read_version(version_path) if version_path else read_version()
    cur = parse_semver(current)
    if target is None:
        return current, None
    tgt = parse_semver(target)  # 坏 semver → VersionError 红
    if tgt <= cur:
        raise VersionError(
            "降版本请求（当前 %s → 目标 %s）：升版演练不接受非升序目标" % (current, target))
    return current, target


def render_report(contract: dict, current: str, target=None, version_error="") -> list:
    """人读报告行：版本 diff + 区间 + 必查项命中清单 + ⑧-5 执行序 + 只读声明。"""
    lines = []
    if version_error:
        lines.append("[红] 当前 VERSION：%s" % version_error)
    else:
        lines.append("当前 sandbar 版本：%s" % current)
    if target is not None:
        cur, tgt = parse_semver(current), parse_semver(target)
        segs = ["升" if t > c else "平" for c, t in zip(cur, tgt)]
        lines.append("目标版本 diff：%s → %s（major %s / minor %s / patch %s）"
                     % (current, target, segs[0], segs[1], segs[2]))
    lines.append("dsh 已验证点（⑧-1 列举制，未列举=未验证不是不支持）：%s"
                 % "、".join(contract["points"]))
    lines.append("项目 schema 版本轴：%s" % contract["schema"])
    lines.append("升版必查项命中清单（⑧-2 四条）：")
    for check, probes in coverage(contract):
        if probes:
            lines.append("  ✓ %s（%s）→ 探针：%s" %
                         (check["title"], check["touchpoints"], "、".join(probes)))
        else:
            lines.append("  ✎ %s（%s）→ 无 fixture 探针覆盖，升版时人工复扫" %
                         (check["title"], check["touchpoints"]))
    lines.append("执行序（⑧-5）：探针集全绿 → ⑧-1 清单 append → sandbar 发版 → 项目跟进；"
                 "禁止跳过探针直接扩区间")
    lines.append("本命令为只读预检/演练，不改动任何状态；真实升版执行归 M2-D 切换票")
    return lines
