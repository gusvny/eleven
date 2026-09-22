#!/usr/bin/env python3
"""observe-dsh-torn：用真 dsh 对会话档样本观测其对端判据（t260922-11 要求①）。

非 test_ 前缀=不入 pytest 收集面（lint L2 同意）；**手动运行**（非集成入口、不碰
run_scenarios/verify_lane）：
    python3 server/engine/tests/observe_dsh_torn.py [--dsh <dsh命令>] [--timeout 30] [--keep]

流程：临时 DSH_HOME（profile/settings/credentials 三件套同源拷贝，缺源=响亮降级）
→ 生成 resume_patch（headless-resume 插件经 dsh --patch 注入，spawn 链 :2532-2543
同款——缺它 dsh 走全新会话，样本档不被读）→ 逐类样本建档（dsh_torn_fixtures 共用
构建器，与 UT 同一份字节）→ DSH_HEADLESS_SESSION=<样本 id> 跑真 dsh（短超时 + 进程
组 SIGTERM→SIGKILL 全终态回收）→ 抓判据行打印对照表。
判据行真源=server/headless-resume/node.ts（已恢复会话/恢复会话…失败/同 id 新建…）
与 dsh 读侧（corrupt Zstandard session log: …）。

成本边界：撕裂类必死于会话装载（零模型调用）；健康类判据行同样出现在装载层，
判据行抓到即判、超时兜底回收。**结论回填**：跑完后把对照表誊进
agent_activities._session_jsonl_torn 的 docstring（实测表+日期+本命令）。
"""
import argparse
import json
import os
import signal
import subprocess
import sys
import tempfile
from pathlib import Path

_ENGINE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ENGINE))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import dsh_torn_fixtures as fx  # noqa: E402

# 判据行特征（dsh/runner 输出里「对这档怎么看」的可观测出口）
JUDGE_MARKERS = (
    "已恢复会话", "恢复会话", "corrupt Zstandard", "torn JSONL",
    "同 id 新建", "全新", "session log",
)

# 最小任务（仲裁轮 3 实拉归因：dsh headless 调用形态=`dsh --profile sandbar-headless
# "<prompt>"`（agent_activities.py:7/:2737 同源）——不带 prompt 位置参数，dsh 直接
# usage 报错秒退 rc=1，七类样本全部「无判据行」=两轮无效观测的根因）。判据行出自
# 会话装载层（headless-resume 插件 stderr，node.ts:104-121）：撕裂类装载即死秒回；
# 健康类打「已恢复会话」后进模型阶段，由 timeout 兜底回收（工具既有成本口径）。
OBS_PROMPT = "观测探针（t260922-11 判据观测，非真实任务）：收到请回复 ok。"

KINDS = (
    "frame_torn", "truncated_line", "empty_file", "empty_frame",
    "no_trailing_newline", "record_across_frames", "binary_in_frame",
)


def _build_home(root: Path) -> Path:
    """临时 DSH_HOME：profile + settings + credentials 三件套同源拷贝（launch 链
    同款供给，agent_activities spawn 面同三件——缺 creds/settings 时 dsh 换一种
    死法=观测全空，acceptance 段独立归因同方向）。缺源不炸（响亮降级——观测表仍
    出，分段点名缺哪件）。"""
    home = root / "dsh-home"
    home.mkdir(parents=True)
    try:
        import agent_activities as aa  # noqa: PLC0415（工具内延迟导入）
    except Exception as e:  # noqa: BLE001
        print("WARN agent_activities 不可装载（%s: %s）——裸 home 继续，判据行可能失真"
              % (type(e).__name__, e))
        return home
    for label, fn in ((
            "profile", lambda: aa._copy_profile(home)),
            ("settings", lambda: aa._copy_settings(home)),
            ("creds", lambda: aa._copy_creds(home))):
        try:
            fn()
            print("拷贝就绪：%s" % label)
        except Exception as e:  # noqa: BLE001——观测面降级不炸，点名缺哪件
            print("WARN %s 拷贝失败（%s: %s）——判据行可能失真"
                  % (label, type(e).__name__, e))
    return home


def _run_dsh(cmd: list, home: Path, sid: str, timeout: int):
    """跑一次真 dsh（独立进程组；超时 SIGTERM→SIGKILL 全终态回收——spawn/监听
    纪律：正常/报错/超时/取消每条路径都走到清理）。返回 (rc, 判据行清单, 输出头)。"""
    env = dict(os.environ)
    env["DSH_HOME"] = str(home)
    env["DSH_HEADLESS_SESSION"] = sid
    proc = subprocess.Popen(cmd, cwd=str(home.parent), env=env,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            start_new_session=True)
    out = b""
    try:
        out, _ = proc.communicate(timeout=timeout)
        rc = proc.returncode
    except subprocess.TimeoutExpired:
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
            out, _ = proc.communicate(timeout=10)
        except subprocess.TimeoutExpired:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            out, _ = proc.communicate()
        rc = "timeout(%ss)" % timeout
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()
    text_lines = out.decode("utf-8", errors="replace").splitlines()
    lines = [ln for ln in text_lines if any(m in ln for m in JUDGE_MARKERS)]
    # 输出头=诊断面（无判据行时直接看 dsh 死于哪句话，终结「盲跑等下轮」）
    head = [ln.strip() for ln in text_lines if ln.strip()][:2]
    return rc, lines[:6], head


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dsh", default=os.environ.get("SANDBAR_INSPECT_CMD", "") or "dsh",
                    help="dsh 命令（缺省裸 dsh；可用 shlex 形态传全命令需自行加引号）")
    ap.add_argument("--timeout", type=int, default=30,
                    help="单样本超时秒（缺省 30；撕裂类数秒内即出判据行）")
    ap.add_argument("--keep", action="store_true", help="保留临时 DSH_HOME 供复查")
    ap.add_argument("--out", default="",
                    help="结果对照表 JSON 落盘路径（可选；轮 8 起：stdout 回执易被截断，"
                    "完整七类表落台面供 docstring 回填引用，如 --out .sandbar/observe.json）")
    args = ap.parse_args()
    cmd = args.dsh.split() if isinstance(args.dsh, str) else list(args.dsh)
    root = Path(tempfile.mkdtemp(prefix="observe-dsh-torn-"))
    # resume 面注入（轮 5 实拉归因：裸 profile 无 headless-resume 插件——该插件是
    # spawn 链每次生成的 resume_patch 经 dsh --patch 注入的（agent_activities:2532-2543
    # 同款），缺它 dsh 直接走全新会话，样本档根本不被读（七类 rc=0 回复 ok 的败象））。
    # 观测跑在宿主（venv python），runner 宿主路径可见，无需泳道内物化。
    runner = _ENGINE.parent / "headless-resume" / "node.ts"
    if runner.is_file():
        resume_patch = root / "resume_patch_observe.yml"
        resume_patch.write_text(
            "# 本文件由 observe_dsh_torn 生成（判据观测，形态=spawn 链 resume_patch 同款）。\n"
            "- id: headless-runner\n"
            "  disabled: true\n"
            "- insert:\n"
            "    - id: headless-resume\n"
            "      name: '%s'\n"
            "      inject: [headlessStartup]\n"
            "      config:\n"
            "        task: !!js ctx.headlessStartup.task\n" % runner, "utf-8")
        # 参数序对齐 spawn 链：--patch 在 prompt 位置参数**之前**（:2543 先于 :2737
        # append(prompt)——轮 6 实拉：--patch 放 prompt 后=dsh 报「unknown option
        # '--patch'」，CLI 解析器遇位置参数后不再吃选项）。
        cmd += ["--patch", str(resume_patch)]
        print("resume 注入就绪：patch=%s（runner=%s）" % (resume_patch, runner))
    else:
        print("WARN headless-resume runner 不在（%s）——无 resume 面，样本档不会被读，"
              "观测无效" % runner)
    cmd.append(OBS_PROMPT)   # 缺 prompt=dsh usage 秒退 rc=1（七类无判据，两轮实拉教训）
    home = _build_home(root)
    print("临时 DSH_HOME：%s%s" % (root, "（--keep 保留）" if args.keep else ""))
    print("样本类".ljust(22), "rc".ljust(12), "判据行")
    print("-" * 100)
    results = []
    for kind in KINDS:
        sid = "obs-%s" % kind
        f = home / "sessions" / "lane1" / sid / "session.jsonl.zstd"
        fx.build(f, kind)
        rc, lines, head = _run_dsh(cmd, home, sid, args.timeout)
        if lines:
            verdict = " | ".join(lines)
        else:
            verdict = "（无判据行｜输出头: %s）" % (" ⏎ ".join(head) if head else "（无输出）")
        print(kind.ljust(22), str(rc).ljust(12), verdict)
        results.append({"kind": kind, "rc": str(rc), "judge_lines": lines,
                        "output_head": head})
    print("-" * 100)
    print("回填口径：把上表逐类结论誊进 agent_activities._session_jsonl_torn "
          "docstring（实测表+日期+本命令）；撕裂类期望看到 corrupt Zstandard 行，"
          "健康类期望「已恢复会话」或模型层报错（装载已过=判干净）。")
    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps({
            "cmd": cmd, "dsh_head_note": "判据行真源=server/headless-resume/node.ts"
            "（已恢复会话/恢复会话…失败/同 id 新建仍失败）+ dsh 读侧 corrupt 行",
            "results": results}, ensure_ascii=False, indent=1) + "\n", "utf-8")
        print("对照表已落盘：%s（%d 类）" % (out_path, len(results)))
    if not args.keep:
        import shutil
        shutil.rmtree(str(root), ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
