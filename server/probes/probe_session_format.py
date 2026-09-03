"""probe-session-format：会话格式面（必查项 C1/C2）。

断言：行式事件流 fixture 可逐行解 JSON；存在 `type=="assistant"` 事件且
`message.data.usage{inputTokens,outputTokens,cacheReadTokens}` 三键可取（整型）。
zstd 行式事件流（magic 28 b5 2f fd）需 zstandard 依赖——缺依赖=显式红并写明降级路径
（本仓缺省消费未压缩行式 fixture，不静默）。
fixture 畸形档：坏 JSON / 截断流（半行）→ 红。
"""

from __future__ import annotations

import json
import pathlib

from probes import ProbeResult

NAME = "probe-session-format"
_ZSTD_MAGIC = b"\x28\xb5\x2f\xfd"
_USAGE_KEYS = ("inputTokens", "outputTokens", "cacheReadTokens")


def run(session_file) -> ProbeResult:
    p = pathlib.Path(session_file) if session_file is not None else None
    if p is None or not p.is_file():
        return ProbeResult(NAME, False, "会话 fixture 不存在：%s" % p)
    try:
        raw = p.read_bytes()
    except OSError as e:
        return ProbeResult(NAME, False, "读不了 fixture：%s" % e)
    if raw.startswith(_ZSTD_MAGIC):
        try:
            import zstandard  # noqa: F401
        except ImportError:
            return ProbeResult(
                NAME, False,
                "zstd 会话流需 zstandard 依赖（未安装）。降级路径：本仓缺省消费"
                "未压缩行式 fixture；live zstd 流请先安装 zstandard 再跑 --live")
        import zstandard
        try:
            raw = zstandard.ZstdDecompressor().decompress(raw)
        except Exception as e:  # zstd 流损坏=红（截断/坏帧）
            return ProbeResult(NAME, False, "zstd 解压失败（坏流/截断）：%s" % e)
    usage, issues = None, []
    for no, line in enumerate(raw.decode("utf-8", "replace").splitlines(), 1):
        if not line.strip():
            continue
        try:
            ev = json.loads(line)
        except json.JSONDecodeError as e:
            issues.append("第 %d 行非完整 JSON（坏行/截断流）：%s" % (no, e.msg))
            continue
        if not isinstance(ev, dict):
            issues.append("第 %d 行事件不是对象" % no)
            continue
        if ev.get("type") == "assistant" and isinstance(ev.get("message"), dict):
            u = ev["message"].get("data", {}).get("usage")
            if isinstance(u, dict) and all(
                    isinstance(u.get(k), int) and not isinstance(u.get(k), bool)
                    for k in _USAGE_KEYS):
                usage = {k: u[k] for k in _USAGE_KEYS}
    if issues:
        return ProbeResult(NAME, False, "；".join(issues[:3]))
    if usage is None:
        return ProbeResult(NAME, False,
                           "未找到 assistant/message 的 data.usage 三键（C1/C2 面失配）")
    return ProbeResult(NAME, True,
                       "usage 可取：inputTokens=%d outputTokens=%d cacheReadTokens=%d"
                       % (usage["inputTokens"], usage["outputTokens"],
                          usage["cacheReadTokens"]))
