"""t260922-11 夹具构建器：会话档样本类（真 zstd CLI，调用方负责落盘路径）。

UT（test_t260922_11_dsh_wedge_auto_quarantine.py）与观测工具（observe_dsh_torn.py）
共用本模块；文件名不以 test_ 开头=不入 pytest 收集面（lint L2 同意）。
UT 全程禁网络/真 Temporal/真 git；zstd 子进程为被测代码同款依赖（_session_jsonl_torn
先例），conftest 的零真 docker 网闸不受影响。

样本类（t260922-11 工单四类 + 探针盲区类 + 畸形类，kind 名即构建器键）：
  frame_torn           A 帧裂：完整帧字节截断（zstd -t 红 → 层 1 隔离）
  truncated_line       B 帧好内截断行：合法帧、末行截半（探针 True → 层 2 隔离）
  empty_file           C1 空档：0 字节文件（无 zstd magic，zstd -t 红 → 层 1 隔离）
  empty_frame          C2 空档：合法帧压缩零字节内容（探针 False，合法——
                       _session_jsonl_torn docstring「含空档=合法文件」既有口径）
  no_trailing_newline  D 无尾换行完整行（探针 False，合法——既有对照组口径）
  record_across_frames E 帧边界跨记录：两个**完整**帧拼接、一条 JSONL 记录切在帧界
                       ——整流拼接逐行全合法（引擎探针 False=盲区快照）、逐帧撕裂
                       （H1：dsh「complete frame contains a torn JSONL record」字面
                       所指形态；dsh 侧判据由观测工具实证，实证前不写死结论）
  binary_in_frame      F 帧内二进制乱流：合法帧、内容非 UTF-8 非 JSON（探针 True，
                       errors=replace 解码路径——消费外部输入的畸形输入用例）
"""
import json
import subprocess
from pathlib import Path


def zstd_bytes(raw: bytes) -> bytes:
    """zstd 压一段字节（走被测代码同款 CLI 依赖；先例 test_t260905_10_t01:45）。"""
    p = subprocess.run(["zstd", "-z", "-c"], input=raw,
                       capture_output=True, check=True)
    return p.stdout


def lines_payload(objs: list, partial_tail: bytes = b"",
                  raw_lines: list = ()) -> bytes:
    """JSONL 原始字节：objs 逐个 dumps+\\n，再拼 raw_lines 原样行，最后拼 partial_tail
    （截断尾——帧好内截断行类的核心；先例 test_t260905_10_t01:63）。"""
    out = b""
    for o in objs:
        out += (json.dumps(o) + "\n").encode()
    for ln in raw_lines:
        out += ln
    out += partial_tail
    return out


def build_bytes(kind: str) -> bytes:
    """样本类 → 会话档原始字节（多帧=帧字节依次拼接，多帧拼接是真实形态
    （workbench/node.ts:59 证实）；未识别 kind = KeyError 显式炸（fail-closed，
    不静默给空档冒充）。"""
    if kind == "frame_torn":
        payload = zstd_bytes(lines_payload([{"t": 1}, {"t": 2}]))
        return payload[:int(len(payload) * 0.6)]
    if kind == "truncated_line":
        return zstd_bytes(lines_payload(
            [{"t": 1}, {"t": 2}], partial_tail=b'{"t":3,"m":'[:10]))
    if kind == "empty_file":
        return b""
    if kind == "empty_frame":
        return zstd_bytes(b"")
    if kind == "no_trailing_newline":
        return zstd_bytes(b'{"a":1}\n\n{"c":3}')      # 裸空行跳过不判；末行无换行
    if kind == "record_across_frames":
        # 一条记录 {"b":2} 切在帧界：帧 1 尾=截半行 {"b":2，帧 2 头=该行余下 }。
        # 两帧各自完整（zstd -t 过）；拼接后逐行全合法（探针 False）；逐帧看=撕裂。
        return (zstd_bytes(b'{"a":1}\n{"b":2')
                + zstd_bytes(b'}\n{"c":3}\n'))
    if kind == "binary_in_frame":
        return zstd_bytes(b"\xff\xfe not json \x00 garbage\n")
    raise KeyError("未知夹具样本类：%r（见模块 docstring 样本类清单）" % kind)


def build(dst: Path, kind: str) -> Path:
    """样本类 → 落盘单文件（dst 父目录须已存在或调用方先 mkdir）。返回 dst。"""
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_bytes(build_bytes(kind))
    return dst


def mk_dsh_with_session(root: Path, sid: str, kinds: list,
                        fname: str = "session.jsonl.zstd",
                        slug: str = "lane1") -> Path:
    """造一个带会话档的 DSH_HOME：<root>/dsh-home/sessions/<slug>/<sid>/<fname>。

    真实布局=sessions/<slug>/<id>/<file>（_scan_integration_sessions 的 glob
    「*/<id>/*」口径，slug 中间层不硬编）；kinds 多类=依次拼接成多帧/多态档。
    返回 DSH_HOME 路径。"""
    sess_dir = root / "dsh-home" / "sessions" / slug / sid
    sess_dir.mkdir(parents=True, exist_ok=True)
    (sess_dir / fname).write_bytes(
        b"".join(build_bytes(k) for k in kinds))
    return root / "dsh-home"
