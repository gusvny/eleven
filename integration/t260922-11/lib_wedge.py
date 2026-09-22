# -*- coding: utf-8 -*-
"""t260922-11 场景族共享垫层（前置与基础步骤复用；两场景 intent 各自独立）。

提供：
- EXIT_FAIL / EXIT_ENV：三态契约退出码（闸内无跳过态——环境缺失一律 exit 2 点名）。
- load_activities()：引擎活动模块装载（temporalio 真 SDK / 桩双通路）+ 进程内垫层
  （票项目查询软失败垫、心跳垫——活动直驱不在 worker 上下文，心跳无消费者，
  垫 no-op 不改变被测失败路径语义；attempt 探针给常量 1）。
- build_torn_frames()：E 类撕裂会话档字节（帧边界跨记录：整流全合法=引擎探针判净、
  逐帧撕裂=dsh 判拒——即本票立票形态，KI-059 家族今日现场实证）。
- make_stub()：假 dsh 桩脚本（运行次序账本：成功次之前=撕裂拒读退出；成功次=落合法
  回执 exit 0；--version 探测短路应答）。
- make_lane() / make_args() / drive()：泳道夹具（.dsh 三件套预置，_copy_profile/
  _copy_creds/_copy_settings 的 exists 守卫使夹具可控）与活动直驱。
- knob_guard()：环境旋钮保存/恢复（不污染调用方环境）。

设计立场（灰盒）：断言只落用户可感知面——盘面（原位/隔离区/事件记录）、失败文案
（raise 语义与不谎报）、回执（幂等返回与注记可见）；不锚引擎内部私有命名与行号，
判据不随契约不变的实现重构漂移。
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import subprocess
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

REPO = Path(__file__).resolve().parents[2]
EXIT_OK, EXIT_FAIL, EXIT_ENV = 0, 1, 2

TEAR_LINE = "corrupt Zstandard session log: complete frame contains a torn JSONL record"


class Fail:
    """行式断言收集器（t260905-10 lib_lane.Fail 同款口径：失败输出自明）。"""

    def __init__(self, title: str):
        self.title = title
        self.passed = 0
        self.fails: list = []

    def check(self, cond, msg: str) -> bool:
        cond = bool(cond)
        print(("ok    " if cond else "FAIL  ") + msg, flush=True)
        if cond:
            self.passed += 1
        else:
            self.fails.append(msg)
        return cond

    def summary_line(self) -> str:
        return "SUMMARY pass=%d fail=%d env_fail=0 na=0" % (self.passed, len(self.fails))

    def exit_code(self) -> int:
        print("\n%s：ok=%d FAIL=%d" % (self.title, self.passed, len(self.fails)), flush=True)
        print(self.summary_line(), flush=True)
        return EXIT_FAIL if self.fails else EXIT_OK


def tmp_dir(prefix: str) -> Path:
    return Path(tempfile.mkdtemp(prefix=prefix))


def zstd_available() -> bool:
    return shutil.which("zstd") is not None


def zstd_frames(chunks) -> bytes:
    """把多段字节各自压成 zstd 帧后拼接（多帧拼接=真实会话档形态）。"""
    outs = []
    for ch in chunks:
        p = subprocess.run(["zstd", "-q", "-f", "-c", "-"],
                           input=ch, capture_output=True, timeout=30)
        if p.returncode != 0:
            raise RuntimeError("zstd 压缩失败：%s" % p.stderr[:200])
        outs.append(bytes(p.stdout))
    return b"".join(outs)


def build_torn_frames() -> bytes:
    """E 类撕裂档字节：帧 1=完整行+半行前段、帧 2=半行后段+完整行。

    整流后逐行全合法（引擎探针判净=zstd -t 过 + 逐行 JSON 过），逐帧看记录跨帧界
    （dsh 判拒文案同型）——正是「dsh 判 torn 而引擎探针判干净」的立票形态，
    夹具确定性构造，不依赖真 dsh。"""
    line1 = b'{"i":1,"role":"user"}\n'
    half_a = '{"i":2,"role":"assistant","content":"说到一半'.encode("utf-8")
    half_b = '被杀于帧界"}\n'.encode("utf-8")
    line3 = b'{"i":3,"role":"user"}\n'
    return zstd_frames([line1 + half_a, half_b + line3])


def _install_temporalio_stub() -> None:
    """temporalio 桩（t260901-21 同款口径：只挡模块级依赖，不碰被测函数语义）。

    首跑两轮实拉教训（本票仲裁轮 1/2）：
    - 轮 1：桩缺 `defn` → agent_activities 顶层 @activity.defn 装饰面 AttributeError；
    - 轮 2：defn 写成「返回恒等装饰器」→ 裸 @activity.defn 装饰后函数名被绑成装饰器
      工厂本身（协程活动变成返回入参的同步 lambda）→ asyncio.run 报
      「a coroutine was expected, got AgentStageArgs」。正解=defn 直接以 fn 为参
      返回 fn（裸用）/@activity.defn(name=…) 形态返回恒等装饰器（两吃）——真 SDK
      的 defn 装饰后函数本体可直接调用，语义同形。
    桩面五件：defn（上）/cancellation_details（非停机常量，停机守卫归因面不在被测
    路径）/logger/heartbeat/info（直驱垫，heartbeat/info 会被 load_activities 再覆写）。"""
    if "temporalio" in sys.modules:
        return
    t = types_module("temporalio")
    a = types_module("temporalio.activity")
    sys.modules["temporalio"] = t
    sys.modules["temporalio.activity"] = a


def types_module(name: str):
    import types
    m = types.ModuleType(name)
    if name.endswith("activity"):
        m.logger = logging.getLogger("temporalio-stub-wedge")
        m.heartbeat = lambda *args, **kwargs: None
        m.info = lambda *args, **kwargs: SimpleNamespace(attempt=1)
        m.defn = lambda fn=None, **kw: fn if fn is not None else (lambda f: f)
        m.cancellation_details = lambda *args, **kwargs: SimpleNamespace(
            worker_shutdown=False)
    return m


def _reexec_under_engine_venv() -> None:
    """yaml 缺供时自救：改用 engine venv 解释器重执行本场景（同 argv，不返回）。

    背景（merge_check 实红归因）：场景注册 cmd=裸 python3，而引擎 spawn 链真实
    依赖 PyYAML（shared.resolve_routes_table 延迟 import）——裸解释器在此必 ENV_FAIL，
    注册面与 lib 自述「正确跑法=engine venv 解释器」失配。这里按候选链
    （<泳道根>/server/engine/.venv → <泳道根>/.venv）self-exec 换解释器，跑法与
    注册解耦；WEDGE_REEXEC 哨兵保证只自救一次。候选都不在/仍缺 yaml → 回落
    ENV_FAIL exit 2 点名（诚实环境红，不假绿）。"""
    if os.environ.get("WEDGE_REEXEC") == "1":
        return
    # 只在「解释器+脚本文件」形态下可忠实重放（python3 <script>.py：argv=脚本+参数，
    # 原样拼进新解释器即可）。-c/-m/stdin 形态的脚本体不在 argv 里（-c 的 argv[0]
    # 就是字面 "-c"，实参脚本体拿不回来）——重放会变成空 -c 假跑，不如回落 ENV_FAIL
    # 点名，不哑改执行语义（首验实锤：-c 形态 execve 后新解释器报
    # 「Argument expected for the -c option」exit 2）。
    script = sys.argv[0] if sys.argv else ""
    if not script or script.startswith("-") or not Path(script).is_file():
        return
    for cand in (REPO / "server" / "engine" / ".venv" / "bin" / "python",
                 REPO / ".venv" / "bin" / "python"):
        if cand.is_file():
            os.execve(str(cand), [str(cand)] + sys.argv,
                      dict(os.environ, WEDGE_REEXEC="1"))  # 不返回


def load_activities():
    """装载引擎活动模块 + 进程内垫层。装载/供给失败=ENV_FAIL exit 2 点名（不假红）。

    环境前提（轮 2 实拉实锚）：引擎 spawn 链真实依赖 PyYAML（shared.resolve_routes_table
    延迟 import yaml）——裸 python3 缺 PyYAML 时 drive 深处才炸，误象=产品败。这里
    前置探测：先尝试换 engine venv 解释器自救重执行（_reexec_under_engine_venv），
    自救不成再点名退出（不往被测链路注假数据——yaml 桩会把路由表注入空表=改变被测
    数据流）。"""
    try:
        import yaml  # noqa: F401——与 shared.resolve_routes_table 同一供给面
    except ImportError:
        _reexec_under_engine_venv()
        print("ENV_FAIL: PyYAML 缺供且 venv 自救未成（已试 <泳道根>/server/engine/.venv "
              "与 <泳道根>/.venv）——须用 engine venv 解释器跑本场景，裸 python3 不构成"
              "忠实执行环境")
        sys.exit(EXIT_ENV)
    try:
        import temporalio  # noqa: F401
    except ImportError:
        _install_temporalio_stub()
    sys.path.insert(0, str(REPO / "server" / "engine"))
    try:
        import agent_activities as aa  # noqa: E402
    except Exception as e:
        print("ENV_FAIL: 引擎活动模块不可装载（%s: %s）——依赖缺供，环境红" % (type(e).__name__, e))
        sys.exit(EXIT_ENV)

    async def _fake_fetch(ticket_id, *args, **kwargs):
        return ""  # 软失败合法值（与真实现的降级语义同形，不弄挂 spawn 链）

    aa._fetch_ticket_project = _fake_fetch
    try:
        # 心跳垫：活动直驱无 worker 上下文，真 SDK 的 heartbeat 会炸；attempt 探针
        # 给常量 1（隔离留痕的 attempt 来源面，值本身不进任何判定）。
        aa.activity.heartbeat = lambda *args, **kwargs: None
        aa.activity.info = lambda *args, **kwargs: SimpleNamespace(attempt=1)
    except Exception:
        pass
    return aa


def make_lane(prefix: str, ticket: str, stage: str, role: str,
              session_fname: str = "session.v3.jsonl.zstd"):
    """泳道夹具：tmp 目录 + .dsh 三件套预置 + E 类撕裂会话档落位。

    返回 (work, dsh_home, session_dir, torn_path, session_id)。"""
    work = tmp_dir(prefix)
    (work / ".sandbar").mkdir()  # 新名协调目录预建（resolve_dot_dir 规则 1=权威位）
    dsh = work / ".dsh"
    (dsh / "profiles" / "sandbar-headless").mkdir(parents=True)
    (dsh / "profiles" / "sandbar-headless" / "package.json").write_text("{}", encoding="utf-8")
    (dsh / "settings.yaml").write_text("{}\n", encoding="utf-8")
    (dsh / ".credentials.yaml").write_text("{}\n", encoding="utf-8")
    sid = "%s-%s" % (ticket, role)
    sdir = dsh / "sessions" / "proj" / sid
    sdir.mkdir(parents=True)
    torn = sdir / session_fname
    torn.write_bytes(build_torn_frames())
    return work, dsh, sdir, torn, sid


def make_stub(work: Path, success_at: int):
    """假 dsh 桩脚本 + 账本目录。返回 (script_path, state_dir)。

    第 N 次运行：N>=success_at → 把 $WEDGE_STUB_RESULT_FILE 落成合法回执并 exit 0；
    否则 stderr 打「恢复会话 $WEDGE_STUB_SID 失败（回落新建同 id 会话）：…」+
    $WEDGE_STUB_EXTRA_LINE 后 exit 1（撕裂拒读形态，文案=现场实证两行）。
    会话 id 经环境变量传入——不注入即空 id=「日志无有效点名行」形态（双缺子用例用）。
    --version 探测短路应答。"""
    state = work / "stub-state"
    state.mkdir(exist_ok=True)
    (state / "result_ok.json").write_text(json.dumps({
        "status": "ok", "summary": "集成夹具回执（重试后恢复）", "report": "夹具回执",
        "deliverables": ["integration/t260922-11/"], "files_changed": ["integration/README.md"],
        "evidence": "stub receipt"}, ensure_ascii=False), encoding="utf-8")
    script = work / "fake-dsh.sh"
    body = "#!/bin/sh\n"
    body += 'for a in "$@"; do\n'
    body += '  if [ "$a" = "--version" ]; then echo "dsh 0.0.0-wedge-stub"; exit 0; fi\n'
    body += "done\n"
    # --version 探测不计入 spawn 次序账本（face 探测每次 spawn 都跑，非会话回合）
    body += 'echo "$$" >> "%s/calls.log"\n' % state
    body += 'N=$(cat "%s/count" 2>/dev/null || echo 0); N=$((N+1)); echo "$N" > "%s/count"\n' % (state, state)
    body += 'if [ "$N" -ge %d ]; then\n' % success_at
    body += '  cp "%s/result_ok.json" "$WEDGE_STUB_RESULT_FILE"\n' % state
    body += "  exit 0\nfi\n"
    body += ('printf \'dsh-headless-resume: 恢复会话 %s 失败（回落新建同 id 会话）：'
             'session "%s" not found\\n\' "$WEDGE_STUB_SID" "$WEDGE_STUB_SID" >&2\n')
    body += 'if [ -n "$WEDGE_STUB_EXTRA_LINE" ]; then printf \'%s\\n\' "$WEDGE_STUB_EXTRA_LINE" >&2; fi\n'
    body += "exit 1\n"
    script.write_text(body, encoding="utf-8")
    script.chmod(0o755)
    return script, state


def make_args(aa, work: Path, ticket: str, stage: str, role: str):
    """活动入参夹具（skip_settle=True：直驱场景无 worker 结算面，结算不在被测面）。"""
    return aa.AgentStageArgs(
        ticket_id=ticket, stage_id=stage, role=role,
        prompt="集成夹具 prompt（t260922-11 场景）",
        workspace={"type": "dir", "path": str(work)},
        result_file=str(work / ".sandbar" / ("stage_%s_gen0.json" % stage)),
        log_file=str(work / ".sandbar" / ("agent_%s_gen0.log" % stage)),
        gen=0, max_polls=50, skip_settle=True, workflow_id="sandbar-classic")


def drive(aa, args):
    """活动直驱（事件循环内跑完，失败以异常浮出=与 Temporal RETRY 同语义）。"""
    return asyncio.run(aa._run_agent_stage_impl(args))


@contextmanager
def knob_guard(**values):
    """环境旋钮保存/恢复（夹具隔离，不污染调用方与后续子用例）。"""
    saved = {k: os.environ.get(k) for k in values}
    for k, v in values.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v
    try:
        yield
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
