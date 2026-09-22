#!/usr/bin/env python3
"""引擎两诊断面·侧车豁免收窄（t260922-07，registry: t260922-07-engine-sidecar-diagnostics）。

意图（灰盒 L2，ro 池离线秒级，零网络零 docker；判据锚行为面——哪些文件被点名/被隔离，
不锚内部结构与私有命名细节）：
sessions 树注入 0.1.5 侧车形与响亮面对照形（真文件树注入，非 mock），断言
agent_activities 两处诊断清单（unknown 点名 / 检疫盲区点名）：

- ① 侧车退出：session.lock 与大小写变体 Session.LOCK 不再入 unknown/盲区（票面验收③
  「不再把 session.lock 算作会话本体」；改前实测两面均收入=TDD 红依据，见结果文件）；
- ② 响亮面不误伤：双不识 strange.session.bin 仍入 unknown、假想新代名 session.jsonl.zst
  仍入盲区（收窄不许把「豁免名单」做成「吞掉一切 session 字样」的反向放宽——验收⑤）；
- ③ 正文与目录形态语义不变：正文双名不入点名（既有豁免）、目录形态 session.lock/ 不入
  （is_file 守卫既有语义）；
- ④ 检疫动作零改动：撕裂 session.v3.jsonl.zstd 仍被隔离挪入 quarantine/torn-*
  （「隔离点名口径不受影响」的机械锚——收窄只许动两处诊断清单，不许碰检疫动作）；
- ⑤ 两侧名单机械同源（review 意见2 的锁）：探针与引擎各自的 SESSION_SIDECAR_NAMES
  按路径载入两侧模块断言逐字相等且含 session.lock——跨 server/integration 边界无法
  共享模块，注释互指只是文字，机械断言才防名单漂移成假绿/假红。

intent 分工：t260917-05 场景守会话发现面整行为（note 串/三态分流/封顶，无侧车形注入）；
developer L1 UT 守判据真值表与 OSError 边界；本条守本票收窄的注入面与名单同源缝。
实现落地前红属预期（TDD 信号：①⑤），arbitrate/merge 期必须绿。
zstd 缺席 / 引擎模块不可导入 = ENV_FAIL exit 2 点名（registry cmd 已用引擎 venv 回落链）。
"""
import importlib.util
import pathlib
import shutil
import sys
import tempfile

REPO = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "server" / "engine"))
sys.path.insert(0, str(REPO / "integration"))
sys.path.insert(0, str(REPO / "integration" / "t260916-24"))
from lib_env import EXIT_FAIL, EXIT_PASS, env_fail  # noqa: E402

PROBE = REPO / "integration" / "t260916-24" / "probe_dsh_seam.py"
TICKET = "myslug"


def _rel_have(names, rel):
    """点名清单里是否存在末端段恰为 rel 的条目（按文件名判，不按整路径——诊断面的
    用户可感知语义是「这个文件被点名了」）。"""
    return any(pathlib.PurePosixPath(x).name == rel for x in names)


def main():
    if not shutil.which("zstd"):
        env_fail("缺 zstd（检疫动作子用例 zstd -t 同款依赖，引擎读侧硬依赖）")
    if not PROBE.is_file():
        env_fail("缺被测探针 %s（名单同源子用例需要）" % PROBE)
    try:
        import agent_activities as aa  # noqa: E402
    except Exception as e:  # noqa: BLE001 —— 导入失败=环境面（venv 依赖），点名退出
        env_fail("引擎模块不可导入：%s: %s（registry cmd 应经引擎 venv 回落链执行）"
                 % (type(e).__name__, e))

    legs = []

    def check(name, ok, detail=""):
        legs.append(bool(ok))
        print("[%s] %s%s" % ("PASS" if ok else "FAIL", name, ("：" + detail) if detail else ""))

    # ---- 注入树：本票会话正文 + 0.1.5 侧车两形 + 目录形 + 响亮面对照形 ----
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="t26092207-engine-"))
    try:
        sess = tmp / ".dsh" / "sessions"
        dev = sess / TICKET / (TICKET + "-developer")
        dev.mkdir(parents=True)
        (dev / "session.v3.jsonl.zstd").write_text('{"type":"assistant/message"}\n')  # 正文 vN
        (dev / "session.lock").write_text("")                                        # 侧车
        # 大小写变体放独立会话目录：macOS APFS 大小写不敏感，同目录与 session.lock
        # 会撞成同一文件，变体子用例必须跨目录才真有鉴别力（Linux 敏感面两形并存）
        integrator = sess / TICKET / (TICKET + "-integration")
        integrator.mkdir(parents=True)
        (integrator / "Session.LOCK").write_text("")                                 # 大小写变体
        (dev / "strange.session.bin").write_text("junk")                             # 双不识
        reviewer = sess / TICKET / (TICKET + "-reviewer")
        reviewer.mkdir(parents=True)
        (reviewer / "session.lock").mkdir()                                          # 目录形态
        (sess / "session.jsonl.zst").write_text("junk")                              # 假想新代名

        unknown = aa._session_suspect_unmatched(sess, TICKET)["unknown"]
        blind = aa._session_quarantine_blindspots(tmp / ".dsh")

        # ① 侧车退出（改前实测两面均收 → 改前本组红=TDD 信号）
        lock_leak_u = _rel_have(unknown, "session.lock")
        lock_leak_b = _rel_have(blind, "session.lock")
        check("侧车 session.lock 退出 unknown 点名", not lock_leak_u,
              "仍被点名=TDD 红（判据未收口）" if lock_leak_u else "")
        check("侧车 session.lock 退出检疫盲区点名", not lock_leak_b,
              "仍被点名=TDD 红（判据未收口）" if lock_leak_b else "")
        case_leak = _rel_have(unknown, "Session.LOCK") or _rel_have(blind, "Session.LOCK")
        check("大小写变体 Session.LOCK 同样豁免（名单判按名不按形）", not case_leak,
              "仍被点名=豁免实现漏大小写归一" if case_leak else "")

        # ② 响亮面不误伤（改前已绿 → 改后必须保持绿：反向放宽在此落网）
        check("双不识 strange.session.bin 仍在 unknown 点名", _rel_have(unknown, "strange.session.bin"),
              "收窄误伤响亮面=反向放宽" if not _rel_have(unknown, "strange.session.bin") else "")
        check("假想新代名 session.jsonl.zst 仍在盲区点名", _rel_have(blind, "session.jsonl.zst"),
              "收窄误伤盲区=反向放宽" if not _rel_have(blind, "session.jsonl.zst") else "")

        # ③ 正文与目录形态语义不变（改前已绿 → 回归锚）
        body_leak = _rel_have(unknown, "session.v3.jsonl.zstd") or _rel_have(blind, "session.v3.jsonl.zstd")
        check("正文 session.v3.jsonl.zstd 不入两面点名（既有豁免不变）", not body_leak)
        dir_leak = any(x.endswith("myslug-reviewer/session.lock") for x in list(unknown) + list(blind))
        check("目录形态 session.lock/ 不入点名（is_file 守卫既有语义）", not dir_leak)

        # ---- ④ 检疫动作零改动：独立树注入撕裂正文，验收「挪入 quarantine/torn-*」----
        qroot = pathlib.Path(tempfile.mkdtemp(prefix="t26092207-quarantine-"))
        try:
            qsess = qroot / ".dsh" / "sessions" / TICKET / (TICKET + "-developer")
            qsess.mkdir(parents=True)
            torn = qsess / "session.v3.jsonl.zstd"
            torn.write_bytes(b"this is definitely not a zstd frame")
            aa._quarantine_torn_sessions(qroot / ".dsh")
            qdir = None
            for dot in (".sandbar", ".suyou"):  # naming-compat：新名优先，老泳道粘滞
                cand = qroot / dot / "quarantine"
                if cand.is_dir():
                    qdir = cand
                    break
            moved = sorted(q.name for q in qdir.glob("torn-*")) if qdir else []
            check("撕裂正文仍被检疫挪入 quarantine/torn-*（动作面零改动）",
                  not torn.exists() and bool(moved),
                  "原文件还在=%s；隔离区=%s" % (torn.exists(), moved or "空"))
        finally:
            shutil.rmtree(str(qroot), ignore_errors=True)
    finally:
        shutil.rmtree(str(tmp), ignore_errors=True)

    # ---- ⑤ 名单机械同源（两侧模块各自载入，断言逐字相等；改前两侧常量均缺席=TDD 红）----
    spec = importlib.util.spec_from_file_location("probe_dsh_seam_under_test", PROBE)
    probe = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(probe)
    pn = getattr(probe, "SESSION_SIDECAR_NAMES", None)
    en = getattr(aa, "SESSION_SIDECAR_NAMES", None)
    if pn is None or en is None:
        check("探针/引擎两侧 SESSION_SIDECAR_NAMES 机械同源", False,
              "缺席侧=%s（票面验收①③的名单面未落地=TDD 红）"
              % ("引擎" if pn is not None else "探针" if en is not None else "两侧"))
    else:
        same = tuple(pn) == tuple(en)
        has_lock = "session.lock" in tuple(pn)
        check("探针/引擎两侧 SESSION_SIDECAR_NAMES 机械同源", same and has_lock,
              "probe=%r engine=%r%s" % (tuple(pn), tuple(en),
                                        "" if has_lock else "（名单不含 session.lock）"))

    print("== SUMMARY：PASS=%d FAIL=%d ==" % (legs.count(True), legs.count(False)))
    sys.exit(EXIT_PASS if all(legs) else EXIT_FAIL)


if __name__ == "__main__":
    main()
