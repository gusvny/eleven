#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""t260916-24 场景①：dsh 版本面启动可观测——「本 worker 用的 dsh 版本与路径」可查。

intent（登记于 run_scenarios.py SCENARIOS，本文件为其执行体）：
工单验收③+②（缺省半）的用户可感知面——真 worker 起跑链（docker 台 temporal-only，
非夹具注入）上，归属 meta 落 dsh 版本面，四腿：
- 缺省腿：不设任何 dsh 旋钮 → face source=default、cmd 与文档化缺省口径逐元素
  等值、version 与宿主 `dsh --version` 实测一致（版本是探测来的不是抄配置的）
  ——「缺省不破现状」在真启动链上可查证（验收②）；
- 钉路径腿：SANDBAR_AGENT_CMD 指版本桩 → face source=env、version=桩自报版本、
  二进制路径解析到桩本体——「显式钉路径生效」，版本从被钉二进制实测（KI-058
  「机器层安装态≠代码态」的对症观测：机器实际在跑什么，meta 说什么）；
- 预期不符可查腿：桩版本≠SANDBAR_DSH_EXPECTED_VERSION → face expected/
  expected_state=mismatch 可查、worker 仍起（缺省 off 仅记录不拦）——验收③
  「可查」半边；
- 探测失败不挡启动腿：SANDBAR_AGENT_CMD 指不存在路径 → meta 照落、face
  version_state=error 且 detail 点名（不静默）、worker 仍起——best-effort 契约
  （探测失败不挡启动），坏机器态显形而非静默或启动炸（KI-058 族）。

intent 分工（防 intent 级重复）：
- t260905-02-worker-lifecycle＝归属指纹 meta 的生命周期面（起/退/异常输入）；
  本条＝meta 里 dsh 版本面的内容契约（版本/路径/来源/预期态），同表面不同字段族；
- sc_dsh_probe_selftest（本票探针离线自检腿，implement 段交付）＝探针工具自身
  的正负自检；本条＝引擎启动链对版本面的记录行为，被测对象不同；
- t260913-04-image-supervisor＝镜像内 dsh 本体在场；本条＝引擎对「用的是哪个
  dsh」的自报面。钉路径 UT（developer L1）锚解析函数，本条锚真启动链接线。

三态契约：docker/镜像/bench 缺席=ENV_FAIL exit 2（点名缺件）；宿主无 dsh 或
`dsh --version` 失效=ENV_FAIL（被测前提不在，非被测红）。实现段落地前红属预期
（TDD 信号：meta 无 dsh 面=FAIL 点名），arbitrate/merge 期必须绿。
断言全落公开产物（meta JSON/进程终态），实现重构不改契约不得打破本场景。

红线（testing-guide）：被测 worker 子进程经 bench.audit_hook_env 审计钩子护体
（连生产 7233/8233=先记后抛），终局断言审计账本为空；一切状态写临时目录。
"""
import json
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, os.path.join(REPO, "integration"))
sys.path.insert(0, os.path.join(REPO, "integration", "t260904-02"))
sys.path.insert(0, HERE)
from lib_gate import (MISSING_EXIT, Fail, poc_python, read_audit_jsonl,  # noqa: E402
                      require_bench, require_stage, stage_down)
from lib_t26091624 import (DEFAULT_DSH_CMD_STR, STUB_VERSION, make_stub,  # noqa: E402
                           spawn_worker, stage_env, terminate_worker, wait_meta)

QUEUE = "t26091624-face"
EXPECTED_OK = "0.1.1-rc.2"  # 宿主现装版本（expected 不符腿的预期值）
DSH_KNOBS = ("SANDBAR_AGENT_CMD", "SANDBAR_DSH_EXPECTED_VERSION", "SANDBAR_DSH_STRICT")


def real_dsh_version(fail):
    """宿主真 dsh 版本（face 对账的地真源）；缺席/失效=环境红 exit 2。"""
    if not shutil.which("dsh"):
        fail.bail("ENV_FAIL: 宿主 PATH 上无 dsh——本场景被测前提（引擎缺省面）不在，"
                  "非被测红", MISSING_EXIT)
    p = subprocess.run(["dsh", "--version"], capture_output=True, text=True, timeout=30)
    ver = (p.stdout or "").strip().splitlines()
    if p.returncode != 0 or not ver:
        fail.bail("ENV_FAIL: `dsh --version` 失效（rc=%s out=%r err=%r）——版本对账地真源缺席"
                  % (p.returncode, (p.stdout or "")[:80], (p.stderr or "")[:80]), MISSING_EXIT)
    return ver[0].strip()


def get_face(fail, meta, tag):
    """取 meta 的 dsh 面（契约漂移/未落地=FAIL 点名，不静默 KeyError）。"""
    if not fail.check(isinstance(meta, dict) and "dsh" in meta,
                      "%s：归属 meta 含 dsh 版本面（实得 keys=%s；缺=实现未落地或 meta 契约漂移）"
                      % (tag, sorted(meta.keys()) if isinstance(meta, dict) else type(meta).__name__)):
        return None
    return meta["dsh"] or {}


def main():
    fail = Fail("t260916-24 ①dsh 版本面启动可观测（缺省/钉路径/预期不符/探测失败四腿）")
    bench = require_bench(fail)
    py = poc_python(bench)
    host_ver = real_dsh_version(fail)
    default_cmd = shlex.split(DEFAULT_DSH_CMD_STR)
    tmp = tempfile.mkdtemp(prefix="sandbar-it-t26091624-face-")
    audit_dir = os.path.join(tmp, "audit")
    os.makedirs(audit_dir, exist_ok=True)
    audit_env, audit_log = bench.audit_hook_env(audit_dir)
    stub, stub_log = make_stub(tmp)
    stage_mod = None
    stage = None
    workers = []
    try:
        stage_mod, stage = require_stage(fail, "t26091624-face-%d" % os.getpid(),
                                         "t26091624-face")

        def boot(tag, extra):
            """起一个 worker（meta/日志各腿独立），返回 (proc, meta_path, log_path)。"""
            meta_path = os.path.join(tmp, "%s.meta" % tag)
            log_path = os.path.join(tmp, "%s.log" % tag)
            env = stage_env(stage, audit_env=audit_env, extra={
                "SANDBAR_TASK_QUEUE": QUEUE,
                "SANDBAR_WORKER_META": meta_path,
                "DSH_STUB_LOG": stub_log,  # 版本桩两种调用都记账（--version 也记）
            })
            for k in DSH_KNOBS:  # 防外部环境泄入：先剥再按腿注入
                env.pop(k, None)
            env.update(extra or {})
            w = spawn_worker(py, env, log_path)
            workers.append(w)
            return w, meta_path, log_path

        def src_of(face):
            """来源语义锚（字段拼写不锁——KI-051：方案写 source，实现名 cmd_source，
            语义同为 env|default）。"""
            return face.get("source") or face.get("cmd_source")

        # ---------- 腿① 缺省：来源=default、cmd 等值、version=宿主实测 ----------
        w, meta_path, _ = boot("leg1-default", None)
        meta = wait_meta(meta_path)
        face = get_face(fail, meta, "腿①缺省")
        if face is not None:
            fail.check(src_of(face) == "default",
                       "腿①：无旋钮时来源=default（实得 %r）" % src_of(face))
            fail.check(face.get("cmd") == default_cmd,
                       "腿①：缺省 cmd 与文档化口径逐元素等值 %r（实得 %r）——缺省不破现状"
                       % (default_cmd, face.get("cmd")))
            fail.check(face.get("version") == host_ver,
                       "腿①：version 与宿主 `dsh --version` 实测一致（meta=%r 实测=%r）"
                       "——版本是探测来的不是抄配置" % (face.get("version"), host_ver))
        terminate_worker(w)

        # ---------- 腿② 钉路径：stub 生效、版本从被钉二进制实测 ----------
        # （stub 自执行单 token：引擎以 cmd[0] 为被钉二进制做 real_bin 解析与
        #   `<dsh> --version` 实证——wrapper 形态会探到解释器而非桩）
        w, meta_path, _ = boot("leg2-pin", {"SANDBAR_AGENT_CMD": stub})
        meta = wait_meta(meta_path)
        face = get_face(fail, meta, "腿②钉路径")
        if face is not None:
            fail.check(src_of(face) == "env",
                       "腿②：显式 SANDBAR_AGENT_CMD 时来源=env（实得 %r）" % src_of(face))
            fail.check(face.get("version") == STUB_VERSION,
                       "腿②：version=桩自报 %s（实得 %r）——显式钉路径生效且版本实测于被钉二进制"
                       % (STUB_VERSION, face.get("version")))
            pinned = os.path.realpath(face.get("real_bin") or face.get("bin") or "")
            fail.check(pinned == os.path.realpath(stub),
                       "腿②：二进制路径解析到桩本体（实得 %r）——「用的哪个 dsh」可查"
                       % (face.get("real_bin") or face.get("bin")))
        terminate_worker(w)

        # ---------- 腿③ 预期不符可查：expected/expected_state=mismatch 且不拦 ----------
        w, meta_path, log_path = boot("leg3-mismatch", {
            "SANDBAR_AGENT_CMD": stub,
            "SANDBAR_DSH_EXPECTED_VERSION": EXPECTED_OK})
        meta = wait_meta(meta_path)
        face = get_face(fail, meta, "腿③预期不符")
        if face is not None:
            fail.check(face.get("expected") == EXPECTED_OK,
                       "腿③：expected 记录在案 %s（实得 %r）" % (EXPECTED_OK, face.get("expected")))
            fail.check(face.get("expected_state") == "mismatch",
                       "腿③：expected_state=mismatch 可查（实得 %r）——版本与预期不符有账"
                       % face.get("expected_state"))
        time.sleep(2.0)
        fail.check(w.poll() is None,
                   "腿③：缺省（STRICT off）不符仅记录不拦——worker 仍起（rc=%s）" % w.returncode)
        terminate_worker(w)

        # ---------- 腿④ 探测失败不挡启动：state=error 点名 + meta 照落 + 仍起 ----------
        bogus = os.path.join(tmp, "no-such-dsh")
        w, meta_path, log_path = boot("leg4-broken", {"SANDBAR_AGENT_CMD": bogus})
        meta = wait_meta(meta_path)
        face = get_face(fail, meta, "腿④探测失败")
        if face is not None:
            fail.check(face.get("version_state") == "error",
                       "腿④：二进制不存在 → version_state=error（实得 %r）——坏机器态显形不静默"
                       % face.get("version_state"))
            fail.check(bool(face.get("version_state") == "error") and
                       bool(str(face.get("version_detail") or face.get("detail") or "").strip()),
                       "腿④：error 附 detail 点名（非裸 error）——报错精确纪律")
        time.sleep(2.0)
        fail.check(w.poll() is None,
                   "腿④：探测失败不挡启动（best-effort 契约）——worker 仍起（rc=%s）" % w.returncode)
        terminate_worker(w)

        # ---------- 红线：被测子进程零触碰生产端口 ----------
        rows = read_audit_jsonl(audit_log)
        fail.check(not rows, "审计账本为空：被测子进程零连生产端口（实得 %d 条）" % len(rows))
    finally:
        for w in workers:
            terminate_worker(w)
        if stage is not None:
            try:
                stage_down(stage_mod, stage["project"])
            except Exception:
                pass
        shutil.rmtree(tmp, ignore_errors=True)
    fail.finish()


if __name__ == "__main__":
    main()
