#!/usr/bin/env python3
"""走查/仲裁段全量套件守卫·归位回执契约（t260924-09，registry: t260924-09-suite-guard-receipt）。

意图（灰盒 L2/L3，ro 池离线秒级，零网络零 docker；真引擎模块 × 真会话档夹具，
判据锚公开回执面——结果文件键 / status / summary 语义，不锚守卫内部实现）：
走查（acceptance_walkthrough）与仲裁（arbitrate）等 integration 角色 agent 段
把全量套件当复现工具时（KI-117 实案：两趟全量 374 条≈81 分钟），用户可感知终态
必须是「响亮红 + 票面点名」，且三类取证面各归各位：

- A 定点豁免：`--only <名>` 复现单条红不触守卫（工单必做①「复现单条只跑该条」的
  正面通道必须畅通——守卫不许把定点复跑也拦死）；
- B 口径漂移：无 `--only` 且未与闸同口径（裸全量）→ status=failed + 结果文件
  `full_suite_violations` 键 + summary 点名首条命令（必做② fail-loud 不静默）；
- C 非法 token 与漂移分诊：`--exclude-pools engin`（拼错池名——执行器
  parse_exclude_pools 对违规 token 只剥离不判红，实际=零排除全量，t260924 方案
  C2 读码结论）→ 照样命中，且 summary/report 语义须含「非法」字样分诊——
  不得与「零排除裸全量」混成同一句归因把诊断引向错误方向（review T1：报错精确）；
- D 次数上限：与闸同口径（--exclude-pools engine,exclusive）的合法全量第一趟
  豁免、同段第二趟命中「超上限」点名（review R2：上限不限裸全量，合规形态同样
  入计数——纯文案纪律升级为机械执法）；
- E 幂等与畸形既有结果文件：文件已带 full_suite_violations 重入不重写；既有
  结果文件非 dict（坏档）不抛不崩（畸形输入三态——不静默绿也不假红）；
- F 角色边界：developer 段的 run_scenarios 调用不进本守卫（禁跑执法另有
  integration_violations 通道，两通道不互替不串味）；同段归属=最后 user/message
  帧之后（T2：上限计数范围=本段回合，与前段历史回合互不追溯）。

intent 分工：developer L1（server/engine/tests）守分类纯函数真值表与命令形态
矩阵——本条守「拼起来通不通」：真会话档 → 真扫描 → 真结果文件回写的整链回执
契约（单测过≠归位接了线）。t260921-04 场景族守 developer 段禁跑执法面，本条
只守 integration 段取证面瘦身新契约，不互替。t260913-03 场景守执行器池排除
旋钮本体（含违规 token 剥离 WARN）——本条不重复执行器行为，只消费其「违规
token 静默剥离」事实作为守卫必须复算 token 的前提。
实现落地前 B/C/D 红属预期（TDD 信号），arbitrate/merge 期必须全绿。
zstd 缺席 / 引擎模块不可导入 = ENV_FAIL exit 2 点名。
"""
import importlib
import json
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile

REPO = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "server" / "engine"))
sys.path.insert(0, str(REPO / "integration"))
from lib_env import env_fail  # noqa: E402

TICKET = "t26092409x"
RUN = "python3 integration/run_scenarios.py"
GATE = RUN + " --exclude-pools engine,exclusive"   # 闸口径全量（合规形态）
FULL = RUN                                          # 裸全量（口径漂移）


def _zstd_bytes(raw: bytes) -> bytes:
    return subprocess.run(["zstd", "-z", "-c"], input=raw,
                          capture_output=True, check=True).stdout


def _frame(seq, ftype, data):
    return {"type": ftype, "seq": seq, "time": 1789956469345, "data": data}


def _user(seq):
    return _frame(seq, "user/message",
                  {"content": [{"type": "text",
                                "text": "【派活指令】阶段（角色=integration）"}]})


def _bash(seq, cmd):
    return _frame(seq, "tool/call",
                  {"turn": 1, "step": seq, "callId": "c%d" % seq,
                   "name": "bash", "arguments": json.dumps({"command": cmd})})


def _write_session(root: pathlib.Path, role, frames):
    d = root / ".dsh" / "sessions" / "ws" / ("%s-%s" % (TICKET, role))
    d.mkdir(parents=True, exist_ok=True)
    raw = b"".join((json.dumps(f) + "\n").encode() for f in frames)
    (d / "session.jsonl.zstd").write_bytes(_zstd_bytes(raw))


def _apply(aa, shared, root, role="integration", rfile_text=None):
    """真缝调取证面护栏归位入口（引擎挂点同款双返回点的被调方），返回
    (StageResult, 结果文件 dict|None)。"""
    rf = root / "stage_walkthrough_gen0.json"
    if rfile_text is not None:
        rf.write_text(rfile_text, "utf-8")
    else:
        # 真缝对齐（仲裁 gen1）：引擎流程里 agent 段回写时结果文件必已存在——
        # _stamp 对不可读文件的静默跳过是幂等立场，不是缺席豁免。夹具预写壳，
        # 否则 B2/C1/D2/D3 测的是夹具缺席而非守卫回写（gen1 闸红的事故面）。
        rf.write_text(json.dumps({"status": "ok", "summary": "s", "report": "r",
                                  "evidence": "e"}, ensure_ascii=False), "utf-8")
    args = shared.AgentStageArgs(ticket_id=TICKET, stage_id="acceptance_walkthrough",
                                 role=role, prompt="p", workspace=None,
                                 result_file=str(rf), log_file="")
    apply_fn = getattr(aa, "_apply_suite_budget", None)
    if apply_fn is None:
        env_fail("引擎缺 _apply_suite_budget 归位入口（守卫未落地——此为产品红，"
                 "非环境红；此处按契约显式点名）")
    res = apply_fn(shared.StageResult(
        status="ok", summary="s", report="r", evidence="e"), root, args)
    raw = None
    try:
        raw = json.loads(rf.read_text("utf-8"))
    except Exception:
        raw = None
    return res, raw


def main():
    if not shutil.which("zstd"):
        env_fail("缺 zstd（引擎会话档解压读侧硬依赖，夹具同款）")
    try:
        import agent_activities as aa  # noqa: E402
        import shared  # noqa: E402
    except Exception as e:  # noqa: BLE001
        env_fail("引擎模块不可导入：%s: %s（registry cmd 应经引擎 venv 回落链执行）"
                 % (type(e).__name__, e))

    legs = []

    def check(name, ok, detail=""):
        legs.append(bool(ok))
        print("[%s] %s%s" % ("PASS" if ok else "FAIL", name,
                             ("：" + detail) if detail else ""))

    def note_of(res):
        """扫描注记透传（零静默：扫描异常/未判成必须能在输出里看见为什么）。"""
        return str(getattr(res, "integration_scan_note", "") or "")

    tmp = pathlib.Path(tempfile.mkdtemp(prefix="t26092409-guard-"))
    try:
        # ---- G 接线面：守卫归位入口已挂进 agent 段双返回点（拼起来通不通） ----
        aa_src = (REPO / "server/engine/agent_activities.py").read_text("utf-8")
        calls = len(re.findall(r"=\s*_apply_suite_budget\(", aa_src))
        check("G1 守卫已挂 agent 段返回点（缓存命中/真 spawn 双挂点）", calls >= 2,
              "接线调用 %d 处（0=函数定义了没接线=护栏整体空转）" % calls)

        # ---- A 定点豁免（必做①正面通道） ----
        t = pathlib.Path(tempfile.mkdtemp(prefix="t26092409-a-"))
        _write_session(t, "integration", [_user(0), _bash(1, RUN + " --only x")])
        res, raw = _apply(aa, shared, t)
        check("A1 定点 --only 复跑不翻红", res.status == "ok",
              "status=%s（定点复现被拦=正面通道堵死）" % res.status)
        check("A2 定点复跑不落守卫键", not (raw or {}).get("full_suite_violations"),
              "结果文件出现 full_suite_violations=守卫误伤定点")

        # ---- B 裸全量=口径漂移（fail-loud） ----
        t = pathlib.Path(tempfile.mkdtemp(prefix="t26092409-b-"))
        _write_session(t, "integration", [_user(0), _bash(1, FULL)])
        res, raw = _apply(aa, shared, t)
        v = (raw or {}).get("full_suite_violations")
        check("B1 裸全量翻红 status=failed", res.status == "failed",
              "status=%s（TDD：守卫未落地时此子用例红）｜扫描注记=%s"
              % (res.status, note_of(res) or "无"))
        check("B2 结果文件落 full_suite_violations 且点名命令",
              bool(v) and FULL in json.dumps(v, ensure_ascii=False),
              "键缺席或未点名首条命令=票面无据")
        check("B3 summary 点名首条命令（人读面）", FULL in (res.summary or ""),
              "summary 未含命令串")

        # ---- C 非法 token 分诊（T1：不与裸全量混同归因） ----
        t = pathlib.Path(tempfile.mkdtemp(prefix="t26092409-c-"))
        _write_session(t, "integration",
                       [_user(0), _bash(1, RUN + " --exclude-pools engin")])
        res, raw = _apply(aa, shared, t)
        v = (raw or {}).get("full_suite_violations")
        check("C1 拼错池名照样命中（执行器只剥离不判红，守卫必须复算）",
              res.status == "failed" and bool(v),
              "status=%s 键=%s（凭『传了 exclude』豁免=零排除全量漏网）｜扫描注记=%s"
              % (res.status, bool(v), note_of(res) or "无"))
        allface = json.dumps(v, ensure_ascii=False) + (res.summary or "") + \
            (res.report or "")
        check("C2 归因含『非法 token』分诊语义（不与裸全量同级混诊）",
              "非法" in allface,
              "报告面无非法 token 分诊=归因把诊断引向『零排除裸全量』错误方向（T1）")

        # ---- D 次数上限（R2：合规全量同样入计数） ----
        t = pathlib.Path(tempfile.mkdtemp(prefix="t26092409-d1-"))
        _write_session(t, "integration", [_user(0), _bash(1, GATE)])
        res, raw = _apply(aa, shared, t)
        check("D1 同口径全量第一趟豁免", res.status == "ok"
              and not (raw or {}).get("full_suite_violations"),
              "首趟即红=上限错位（每段许 1 趟）")
        t = pathlib.Path(tempfile.mkdtemp(prefix="t26092409-d2-"))
        _write_session(t, "integration",
                       [_user(0), _bash(1, GATE), _bash(2, GATE)])
        res, raw = _apply(aa, shared, t)
        v = (raw or {}).get("full_suite_violations")
        check("D2 同口径全量第二趟命中超上限", res.status == "failed" and bool(v),
              "status=%s 键=%s（合规形态不计数=护栏对 KI-117 实案形态零拦截，R2）｜扫描注记=%s"
              % (res.status, bool(v), note_of(res) or "无"))
        check("D3 超上限归因含『上限/超』语义点名",
              bool(v) and any(k in json.dumps(v, ensure_ascii=False) + (res.summary or "")
                              for k in ("上限", "超")),
              "命中但未说为什么红=报错不精确")

        # ---- E 幂等 + 畸形既有结果文件 ----
        t = pathlib.Path(tempfile.mkdtemp(prefix="t26092409-e-"))
        seeded = json.dumps({"status": "failed", "summary": "【已带红】x",
                             "full_suite_violations": [{"cmd": "old"}]}, ensure_ascii=False)
        _write_session(t, "integration", [_user(0), _bash(1, FULL)])
        res, raw = _apply(aa, shared, t, rfile_text=seeded)
        check("E1 文件已带守卫键重入不重写",
              (raw or {}).get("full_suite_violations") == [{"cmd": "old"}]
              and (raw or {}).get("summary") == "【已带红】x",
              "重入覆盖=幂等锚被破坏")
        t = pathlib.Path(tempfile.mkdtemp(prefix="t26092409-e2-"))
        _write_session(t, "integration", [_user(0), _bash(1, FULL)])
        try:
            res, raw = _apply(aa, shared, t, rfile_text="[1,2,3]")  # 非 dict 坏档
            check("E2 畸形既有结果文件不抛", True)
        except Exception as e:  # noqa: BLE001
            check("E2 畸形既有结果文件不抛", False, "异常 %s: %s"
                  % (type(e).__name__, e))

        # ---- F 角色边界与段归属（T2） ----
        t = pathlib.Path(tempfile.mkdtemp(prefix="t26092409-f1-"))
        _write_session(t, "developer", [_user(0), _bash(1, FULL)])
        res, raw = _apply(aa, shared, t, role="developer")
        check("F1 developer 段不进本守卫（禁跑执法另有通道不串味）",
              not (raw or {}).get("full_suite_violations"),
              "developer 档落 full_suite_violations=两执法通道串味")
        t = pathlib.Path(tempfile.mkdtemp(prefix="t26092409-f2-"))
        _write_session(t, "integration",
                       [_user(0), _bash(1, FULL),          # 前段回合（最后 user 之前）
                        _user(2), _bash(3, RUN + " --only y")])
        res, raw = _apply(aa, shared, t)
        check("F2 段归属=最后 user 帧之后：前段历史回合不追溯计数",
              res.status == "ok" and not (raw or {}).get("full_suite_violations"),
              "历史回合被翻旧账=段归属判定引入第二口径（T2）")
    finally:
        subprocess.run(["rm", "-rf", str(tmp)], capture_output=True)

    n_fail = legs.count(False)
    print("SUMMARY t260924-09-suite-guard-receipt: %d/%d 绿"
          % (len(legs) - n_fail, len(legs)))
    sys.exit(0 if n_fail == 0 else 1)


if __name__ == "__main__":
    importlib.import_module("lib_env")  # noqa: F401 —— 显式依赖自检
    main()

# probe comment
