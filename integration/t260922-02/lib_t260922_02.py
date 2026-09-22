# -*- coding: utf-8 -*-
"""t260922-02 场景族共享夹具（本票目录自含，不跨票目录 import——t260913-03
资产闭包守卫只认同目录/integration 顶层可解析者；lib_face.py 同款纪律）。

提供：
- EXIT_OK / EXIT_FAIL / EXIT_ENV：三态契约退出码（闸内无中间态——环境缺失一律
  ENV_FAIL=2，绝不装绿；t260904-12）。
- ensure_engine_python()：temporalio 缺席时按回落链重执行（lib_face 同款：
  server/engine/.venv → 主树 .venv；重跑目标=调用方入口脚本 sys.argv[0]）。
- zstd_available() / zstd_bytes()：zstd CLI 探针与帧构造（真实会话档形态）。
- build_workspaces(target)：<target> 下造 7 个独立工作空间树（双代会话档，
  真实三层布局 .dsh/sessions/<slug>/<sub>/），返回 {kind: [zstd 路径]}。
  夹具形状锚=方案 v2 §0.1（两代 known-event-types.js 底册 + .d.ts 形状）；
  0.1.1 夹具覆盖本泳道真会话观测型全集（噪声守卫：健康档注记必须恒空）。
- judge_json(path)：py 侧判据 CLI（解压→_judge_session_lines→_session_face_s1_text
  →单行 JSON），供 mjs 镜像场景同档对拍。

夹具与断言的关系：本 lib 只造档与供判据，不持断言——断言在 sc_ 场景里。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
EXIT_OK, EXIT_FAIL, EXIT_ENV = 0, 1, 2

SLUG = "itest-slug"
SUB = "t260922-02-itest"


class Fail:
    """行式断言收集器（失败清单自明，exit 码只看有无失败）。"""

    def __init__(self, title: str):
        self.title = title
        self.passed = 0
        self.fails = []

    def check(self, cond, msg: str) -> bool:
        cond = bool(cond)
        print(("ok    " if cond else "FAIL  ") + msg, flush=True)
        if cond:
            self.passed += 1
        else:
            self.fails.append(msg)
        return cond

    def exit_code(self) -> int:
        print("\n%s：ok=%d FAIL=%d" % (self.title, self.passed, len(self.fails)), flush=True)
        return EXIT_FAIL if self.fails else EXIT_OK


def ensure_engine_python() -> None:
    """temporalio 不可导入时按回落链重执行；无候选 → ENV_FAIL exit 2 点名。
    重执行目标=调用方入口脚本（sys.argv[0]）——把 lib 当脚本重跑时 argv[0]=本
    lib，main() 按 action 分发，同样成立。"""
    try:
        import temporalio  # noqa: F401
        return
    except ImportError:
        pass
    entry = Path(sys.argv[0]).resolve() if sys.argv[0] else None
    if entry is None or not entry.exists():
        print("ENV_FAIL: temporalio 不可导入且入口脚本不可辨（argv0=%r）——无法回落重执行"
              % (sys.argv[0],), flush=True)
        sys.exit(EXIT_ENV)
    cands = []
    venv = REPO / "server/engine/.venv/bin/python"
    if venv.exists():
        cands.append(venv)
    parts = REPO.parts
    for marker in (".lane", ".worktrees"):
        if marker in parts:
            main = Path(*parts[: parts.index(marker)])
            cands.append(main / "server/engine/.venv/bin/python")
            break
    for c in cands:
        if c.exists() and str(c) != sys.executable:
            os.execv(str(c), [str(c), str(entry)] + sys.argv[1:])
    print("ENV_FAIL: temporalio 不可导入且回落链无候选解释器"
          "（试过 %s）——先在主树建 server/engine/.venv" % [str(c) for c in cands],
          flush=True)
    sys.exit(EXIT_ENV)


def zstd_available() -> bool:
    try:
        subprocess.run(["zstd", "--version"], capture_output=True, timeout=10)
        return True
    except Exception:
        return False


def zstd_bytes(data: bytes) -> bytes:
    """zstd 帧构造（CLI 通路，与会话档真实落盘形态同源）。"""
    p = subprocess.run(["zstd", "-z", "-c", "-q"], input=data,
                       capture_output=True, timeout=30)
    if p.returncode != 0:
        raise RuntimeError("zstd 压缩失败: %s" % p.stderr[:200])
    return p.stdout


def line(obj) -> bytes:
    return (json.dumps(obj, ensure_ascii=False) + "\n").encode("utf-8")


def _req_header(model):
    return {"type": "request/header",
            "data": {"header": {"config": {"provider": "deepseek", "model": model}}}}


# ---- 双代夹具行集（形状锚=方案 v2 §0.1；0.1.1 集=真会话观测型全集缩样） ----

V011_LINES = [
    {"type": "session", "version": 0, "id": "s-011", "createdAt": 1758000000},
    {"type": "request/context", "data": {"provider": "deepseek", "model": "m-gold-011"}},
    _req_header("m-gold-011"),
    {"type": "user/message", "data": {"content": [{"type": "text", "text": "帮我看一下 t260922-02 的会话面"}]}},
    {"type": "step/start", "data": {"turn": 1, "step": 1}},
    {"type": "tool/call", "data": {"name": "read_file", "arguments": "{\"path\":\"server/engine/agent_activities.py\"}"}},
    {"type": "tool/result", "data": {"message": {"content": [{"type": "text", "text": "ok: 42 行"}]}}},
    {"type": "text-chunks", "data": {"text": "流式文本行"}},
    {"type": "reasoning-chunks", "data": {"text": "思考行"}},
    {"type": "assistant/chunk", "data": {"turn": 1, "step": 1, "chunk": {"type": "text", "text": "正在输出：第一段"}}},
    {"type": "assistant/message", "data": {"turn": 1, "step": 1,
        "message": {"role": "assistant", "content": [{"type": "text", "text": "最终回答"}]},
        "usage": {"inputTokens": 10, "outputTokens": 20, "cacheReadTokens": 5}}},
    {"type": "turn/end", "data": {"turn": 1}},
]

V015_LINES = [
    {"type": "session", "version": 3, "id": "s-015", "createdAt": 1759000000},
    {"type": "request/context", "data": {"provider": "deepseek", "model": "m-gold-015"}},
    _req_header("m-gold-015"),
    {"type": "system/message", "data": {"turn": 1, "step": 0,
        "message": {"role": "system", "content": [{"type": "text", "text": "系统提示词（渲染后）"}]}}},
    {"type": "user/message", "data": {"content": [{"type": "text", "text": "0.1.5 会话面探针"}]}},
    {"type": "turn/start", "data": {"turn": 1}},
    {"type": "step/start", "data": {"turn": 1, "step": 1}},
    {"type": "assistant/attempt", "data": {"turn": 1, "step": 1,
        "stream": [{"type": "text", "text": "第一次尝试的输出（未转正）"}]}},
    {"type": "llm/retry", "data": {"provider": "deepseek"}},
    {"type": "assistant/message", "data": {"turn": 1, "step": 1,
        "message": {"role": "assistant", "content": [{"type": "text", "text": "0.1.5 最终回答"}]},
        "usage": {"inputTokens": 100, "outputTokens": 200, "cacheReadTokens": 50, "reasoningTokens": 7}}},
    {"type": "assistant/message", "data": {"turn": 1, "step": 2,
        "message": {"role": "assistant", "content": [{"type": "text", "text": "补充段"}]},
        "usage": {"inputTokens": 30, "outputTokens": 40}}},
    {"type": "tool/call", "data": {"name": "grep", "arguments": "{\"pattern\":\"SESSION_KNOWN_TYPES\"}"}},
    {"type": "tool/result", "data": {"message": {"content": [{"type": "text", "text": "6 处命中"}]}}},
    {"type": "agent/inbox/spliced", "data": {"count": 2}},
    {"type": "session/title-llm-request", "data": {}},
    {"type": "session/title", "data": {"title": "0.1.5 探针"}},
    {"type": "approval/policy", "data": {}},
    {"type": "deliverables/presented", "data": {}},
    {"type": "model/selection", "data": {}},
    {"type": "subagent/catalog", "data": {}},
    {"type": "tool/ptc-dispatch", "data": {}},
    {"type": "session/end-seed", "data": {}},
    {"type": "permission/preset", "data": {}},
    {"type": "sandbox/mode", "data": {}},
    {"type": "step/end", "data": {"turn": 1, "step": 1}},
    {"type": "turn/end", "data": {"turn": 1}},
]

# CC1 修正推荐形态（review_plan gen1）：预派发中止会话，无 session 头行——
# 旧词表下 known_types==0 → 假 S1；新词表下 system/message+assistant/attempt 已识 → 不假 S1。
ABORT_LINES = [
    {"type": "turn/start", "data": {"turn": 1}},
    {"type": "step/start", "data": {"turn": 1, "step": 1}},
    {"type": "system/message", "data": {"turn": 1, "step": 0,
        "message": {"role": "system", "content": [{"type": "text", "text": "中止会话的系统行"}]}}},
    {"type": "assistant/attempt", "data": {"turn": 1, "step": 1,
        "stream": [{"type": "text", "text": "中止前的尝试输出"}]}},
]

UNKNOWN_LINES = V015_LINES + [{"type": "v9/whatever", "data": {}}]

CAP_EXTRA = [{"type": "v9/t%02d" % i, "data": {}} for i in range(1, 26)]  # 25 个词表外类型
CAP_LINES = V011_LINES + CAP_EXTRA

CORRUPT_BYTES = b"this-is-not-a-zstd-frame\n" * 4


def _put_session(ws: Path, sub: str, filename: str, payload: bytes) -> Path:
    p = ws / ".dsh" / "sessions" / SLUG / sub / filename
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(payload)
    return p


def build_workspaces(target: Path) -> dict:
    """<target> 下造独立工作空间树（每 kind 一个 wt，互不串扰），返回归档路径表。
    kind→构成：
      v011     0.1.1 真形档（观测型全集，健康）
      v015     0.1.5 真形档（11 独有型全覆盖，健康；usage 含无 cacheRead 变体）
      abort    预派发中止形态（无 session 头行；CC1 推荐构成）
      unknown  0.1.5 + 1 个词表外类型（缺得不静默的注入面）
      cap      0.1.1 + 25 个词表外类型（类型级封顶压力）
      mixed    损坏档 + unknown 档共存（note 多源聚合面）
      both     0.1.1 + 0.1.5 共存（健康零注记守卫 + 双代总额）
    """
    target = Path(target)
    out = {}

    def wt(kind):
        w = target / ("w-" + kind)
        w.mkdir(parents=True, exist_ok=True)
        return w

    out["v011"] = [str(_put_session(wt("v011"), SUB, "session.jsonl.zstd",
                                    zstd_bytes(b"".join(line(o) for o in V011_LINES))))]
    out["v015"] = [str(_put_session(wt("v015"), SUB, "session.v3.jsonl.zstd",
                                    zstd_bytes(b"".join(line(o) for o in V015_LINES))))]
    out["abort"] = [str(_put_session(wt("abort"), SUB, "session.v3.jsonl.zstd",
                                     zstd_bytes(b"".join(line(o) for o in ABORT_LINES))))]
    out["unknown"] = [str(_put_session(wt("unknown"), SUB, "session.v3.jsonl.zstd",
                                       zstd_bytes(b"".join(line(o) for o in UNKNOWN_LINES))))]
    out["cap"] = [str(_put_session(wt("cap"), SUB, "session.jsonl.zstd",
                                   zstd_bytes(b"".join(line(o) for o in CAP_LINES))))]
    w = wt("mixed")
    out["mixed"] = [
        str(_put_session(w, SUB + "-a", "session.jsonl.zstd", CORRUPT_BYTES)),
        str(_put_session(w, SUB + "-b", "session.v3.jsonl.zstd",
                         zstd_bytes(b"".join(line(o) for o in UNKNOWN_LINES)))),
    ]
    w = wt("both")
    out["both"] = [
        str(_put_session(w, SUB + "-a", "session.jsonl.zstd",
                         zstd_bytes(b"".join(line(o) for o in V011_LINES)))),
        str(_put_session(w, SUB + "-b", "session.v3.jsonl.zstd",
                         zstd_bytes(b"".join(line(o) for o in V015_LINES)))),
    ]
    return out


def tmp_root(prefix: str) -> Path:
    return Path(tempfile.mkdtemp(prefix=prefix))


def judge_payload(archive: str) -> dict:
    """py 侧判据单档 JSON（镜像场景的 py 半边）。解压→judge→S1 文案。"""
    ensure_engine_python()
    sys.path.insert(0, str(REPO / "server" / "engine"))
    import agent_activities  # noqa: E402
    p = subprocess.run(["zstd", "-dc", archive], capture_output=True, timeout=30)
    if p.returncode != 0:
        return {"ok": False, "error": "解压失败: %s" % p.stderr[:160]}
    j = agent_activities._judge_session_lines(p.stdout.decode("utf-8", "replace").split("\n"))
    s1 = agent_activities._session_face_s1_text(Path(archive).name, j)
    return {
        "ok": True,
        "blank": j.get("blank"),
        "parsed": j.get("parsed"),
        "known_types": j.get("known_types"),
        "usage_records": j.get("usage_records"),
        "usage_without_known_keys": j.get("usage_without_known_keys"),
        "s1": s1,
        # 新判据键：实现落地前缺省（镜像对拍此键=新契约子用例，红属预期）
        "uncovered_types": j.get("uncovered_types"),
    }


def main() -> int:
    action = sys.argv[1] if len(sys.argv) > 1 else ""
    if action == "build":
        target = Path(sys.argv[2])
        if not zstd_available():
            print("ENV_FAIL: zstd CLI 缺席（会话档构造/解析通路依赖 zstd，环境缺供）")
            return EXIT_ENV
        print(json.dumps({"ok": True, "workspaces": build_workspaces(target)},
                         ensure_ascii=False))
        return EXIT_OK
    if action == "judge":
        archive = sys.argv[2]
        if not zstd_available():
            print("ENV_FAIL: zstd CLI 缺席（会话档解析通路依赖 zstd，环境缺供）")
            return EXIT_ENV
        print(json.dumps(judge_payload(archive), ensure_ascii=False))
        return EXIT_OK
    print("未知 action: %r（可用 build/judge）" % action)
    return EXIT_FAIL


if __name__ == "__main__":
    sys.exit(main())
