#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""t260916-02 集成场景（聚合声明门，离线半张）：声明来源改「遍历注册项目」后的 fail-closed 契约。

intent（登记于 run_scenarios.py，名 t260916-02-decl-gate-aggregate）：
  口径①③④的声明维 + 验收④⑤离线证据，全部纯 stdlib 离线（拒网络）：
  子用例0 迁移静态面（R1 grep 子用例，验收2「旧形状零残留」）：铸号函数调用形全仓零命中；
      铸号字面在 server/engine 零命中（落账键/legacy 只读探测两类合法保留精确豁免）；
      run_server.sh 注册两新 SA；ALL_WORKFLOWS 含 spawner；client.py 带 legacy 查询路径与
      type_only_fallback 降级记号。
  子用例1 聚合视图逐项目状态可读：ok 项目列实例（验收⑤「遍历非单文件」）、absent 项目=
      无巡检面不冒充错误、error 项目点名 key+路径+事由（fail-closed 红三要素）；
      enabled_instances=各项目实例之并。
  子用例2 未知实例报错列出已扫项目与状态（绝不冒充网络错）。
  子用例3 指路三态（paths.inspection_decl）：相对形态（拼 dirs[0]）取到指路文件；
      绝对形态取到指路文件；指向不存在 fail-closed 点名声明路径；「..」逃逸不进
      聚合（配置事故不猜）。
  子用例4 跨项目实例 id 重复 fail-closed：歧义实例从聚合白名单剔除且点名两处
      （trigger 面多命中同样报错——两路口径一致，绝不猜归属）。
  子用例5 引擎侧零回落：引擎仓旧声明已删（迁移交付本体）+空注册表显式报错+
      docs/inspection-sample.yaml 在场但样例实例不进聚合。
  子用例6 覆盖层兼容（口径①）：env SANDBAR_INSPECTION_DECL 降级为测试覆盖——生效时
      单文件整体替代聚合（env 独有实例可解析、聚合实例不可解析=整体替代非并集），
      撤掉恢复聚合（兼容层可开可关）。

绑定面（全部为已交付对外契约）：inspection_trigger.py decl（单/聚合双模式）、
inspection_decl.iter_project_decls / load_decl_for_instance / enabled_instance_whitelist、
lib_relocation 夹具（write_registry / decl_yaml）。分工：t260905-03-decl-gate 守单文件
声明门通用行为（其 --decl-path 注入面=本票迁移对象）；t260915-20-decl-project-identity
守实例级身份字段门；t260916-02-relocation-realchain 守真链行为。
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, os.path.join(REPO, "integration", "t260905-03"))
sys.path.insert(0, os.path.join(REPO, "integration"))

import lib_inspection as lib  # noqa: E402
import lib_relocation as rl  # noqa: E402

TRIGGER = os.path.join(rl.TP_DIR, "inspection_trigger.py")
ENGINE_DECL = os.path.join(rl.TP_DIR, "inspection.yaml")   # 引擎旧位（迁移后必须已删）
SAMPLE_DECL = os.path.join(REPO, "docs", "inspection-sample.yaml")

failures: list = []
notes: list = []


def check(name, ok, detail=""):
    (notes if ok else failures).append("ok: %s" % name if ok
                                       else "%s | %s" % (name, detail))


def run_trig(env_extra, *args):
    env = lib.spawn_env(env_extra)
    p = subprocess.run([lib.py_runner(), TRIGGER] + list(args), capture_output=True,
                       text=True, timeout=60, env=env, cwd=rl.TP_DIR)
    out = (p.stdout or "").strip().splitlines()
    try:
        return json.loads(out[-1]) if out else {}
    except Exception:  # noqa: BLE001
        return {"_raw": (p.stdout or "")[-160:], "_stderr": (p.stderr or "")[-120:]}


DECL_X = rl.decl_yaml([("inst-x", "proj-a", "0 3 * * *", "test")])
DECL_Y = rl.decl_yaml([("inst-y", "proj-b", "0 9 * * 1", "doc")])


def leg0_static():
    mint_pat = re.compile(r'inspection-%s-%s"\s*%')
    ledger_pat = re.compile(r'inspection-%s-%s\.json')
    fn_hits, mint_hits = [], []
    for root, dirs, files in os.walk(REPO):
        dirs[:] = [d for d in dirs if d not in (".git", ".venv", "__pycache__",
                                                ".sandbar", "node_modules")]
        for f in files:
            path = os.path.join(root, f)
            if not f.endswith((".py", ".sh", ".ts", ".js")):
                continue
            try:
                text = open(path, encoding="utf-8", errors="replace").read()
            except OSError:
                continue
            if "inspection_ticket_id" + "(" in text:
                fn_hits.append(os.path.relpath(path, REPO))
            if f.endswith(".py") and path.startswith(os.path.join(REPO, "server", "engine")):
                lines = [ln for ln in text.splitlines()
                         if "legacy 只读" not in ln]   # 豁免②：legacy 只读探测行
                if f == "inspection_flow.py":
                    lines = [ledger_pat.sub("", ln) for ln in lines]  # 豁免①：落账键
                if mint_pat.search("\n".join(lines)):
                    mint_hits.append(os.path.relpath(path, REPO))
    check("子用例0a 铸号函数调用形全仓零命中（已退役）", not fn_hits, "命中=%s" % fn_hits[:6])
    check("子用例0b 铸号字面零命中（落账键/legacy 探测两类豁免）", not mint_hits,
          "命中=%s" % mint_hits[:6])
    sh = open(os.path.join(rl.TP_DIR, "run_server.sh"), encoding="utf-8").read()
    check("子用例0c run_server.sh 注册两新 SA",
          "InspectionInstance=Keyword" in sh and "InspectionPeriod=Keyword" in sh)
    wf = open(os.path.join(rl.TP_DIR, "workflows.py"), encoding="utf-8").read()
    check("子用例0d ALL_WORKFLOWS 含 spawner", "InspectionPeriodicSpawnWorkflow" in wf)
    cli = open(os.path.join(rl.TP_DIR, "client.py"), encoding="utf-8").read()
    check("子用例0e 板面 legacy 查询路径+降级记号在场",
          'STARTS_WITH "inspection-' in cli and "type_only_fallback" in cli)


def leg1_aggregate_states(workdir):
    root = os.path.join(workdir, "reg1")
    ha, hb, hc, hd = (os.path.join(root, "home-%s" % x) for x in "abcd")
    for h in (ha, hb, hc, hd):
        os.makedirs(h)
    rl.write_registry(root, "proj-a", "A", [ha])
    rl.write_registry(root, "proj-b", "B", [hb])
    rl.write_registry(root, "proj-c", "C", [hc])
    rl.write_registry(root, "proj-d", "D", [hd],
                      paths_lines=["inspection_decl: nofile.yaml"])  # error 态夹具
    rl.write_file(os.path.join(ha, "inspection.yaml"), DECL_X)
    rl.write_file(os.path.join(hb, "inspection.yaml"), DECL_Y)
    out = run_trig({"SANDBAR_PROJECTS_DIR": root}, "decl")
    res = out.get("result") or {}
    if out.get("ok") is not True or res.get("mode") != "aggregate":
        failures.append("子用例1 decl 聚合未放行/模式错：%s" % json.dumps(out, ensure_ascii=False)[:220])
        return
    states = {i.get("project"): i for i in res.get("projects", [])}
    check("子用例1a ok 项目列实例", states.get("proj-a", {}).get("state") == "ok"
          and any(i.get("id") == "inst-x" for i in states.get("proj-a", {}).get("instances", [])),
          "proj-a=%s" % json.dumps(states.get("proj-a"), ensure_ascii=False)[:140])
    check("子用例1b absent 项目=无巡检面（不冒充错误）",
          states.get("proj-c", {}).get("state") == "absent",
          "proj-c=%s" % json.dumps(states.get("proj-c"), ensure_ascii=False)[:120])
    d_err = states.get("proj-d", {})
    check("子用例1c error 项目点名 key+路径+事由",
          d_err.get("state") == "error" and "nofile.yaml" in str(d_err.get("error")),
          "proj-d=%s" % json.dumps(d_err, ensure_ascii=False)[:160])
    check("子用例1d enabled_instances=各项目实例之并",
          res.get("enabled_instances") == ["inst-x", "inst-y"],
          "enabled=%s" % res.get("enabled_instances"))
    check("子用例1e schedule_specs 带 project 来源",
          {s.get("project") for s in res.get("schedule_specs", [])} == {"proj-a", "proj-b"},
          "specs=%s" % json.dumps(res.get("schedule_specs"), ensure_ascii=False)[:160])


def leg2_unknown_instance(workdir):
    root = os.path.join(workdir, "reg1")   # 复用子用例1 夹具
    out = run_trig({"SANDBAR_PROJECTS_DIR": root}, "trigger", "--instance", "ghost-x",
                   "--period", "20260916")
    err = str(out.get("error") or "")
    check("子用例2 未知实例报错列出逐项目状态且不冒充网络错",
          out.get("ok") is False and "ghost-x" in err and "proj-a=ok" in err
          and "proj-c=absent" in err and "未在任何项目声明中" in err,
          "err=%s" % err[:260])


def leg3_pointer_paths(workdir):
    root = os.path.join(workdir, "reg3")
    home = os.path.join(root, "home-p")
    os.makedirs(home)
    rl.write_registry(root, "proj-p", "P", [home],
                      paths_lines=["inspection_decl: my-insp.yaml"])   # 相对（拼 dirs[0]）
    rl.write_file(os.path.join(home, "my-insp.yaml"), DECL_X)
    out = run_trig({"SANDBAR_PROJECTS_DIR": root}, "decl")
    states = {i.get("project"): i for i in ((out.get("result") or {}).get("projects") or [])}
    st = states.get("proj-p", {})
    check("子用例3a 相对指路拼 dirs[0] 取到声明",
          st.get("state") == "ok" and str(st.get("decl_path", "")).endswith("my-insp.yaml"),
          "proj-p=%s" % json.dumps(st, ensure_ascii=False)[:160])
    abs_target = rl.write_file(os.path.join(workdir, "abs-insp.yaml"), DECL_Y)
    rl.write_file(os.path.join(root, "proj-p", "project.yaml"),
                  open(os.path.join(root, "proj-p", "project.yaml")).read().replace(
                      "  inspection_decl: my-insp.yaml",
                      "  inspection_decl: %s" % abs_target))
    out2 = run_trig({"SANDBAR_PROJECTS_DIR": root}, "decl")
    st2 = {i.get("project"): i for i in ((out2.get("result") or {}).get("projects") or [])}.get("proj-p", {})
    check("子用例3b 绝对指路取到声明",
          st2.get("state") == "ok" and st2.get("decl_path") == abs_target,
          "proj-p=%s" % json.dumps(st2, ensure_ascii=False)[:160])
    rl.write_file(os.path.join(root, "proj-p", "project.yaml"),
                  open(os.path.join(root, "proj-p", "project.yaml")).read().replace(
                      "  inspection_decl: %s" % abs_target,
                      "  inspection_decl: ../esc-insp.yaml"))
    out3 = run_trig({"SANDBAR_PROJECTS_DIR": root}, "decl")
    st3 = {i.get("project"): i for i in ((out3.get("result") or {}).get("projects") or [])}.get("proj-p", {})
    check("子用例3c .. 逃逸指路不进聚合（点名不猜）",
          st3.get("state") == "error" and ".." in str(st3.get("error")),
          "proj-p=%s" % json.dumps(st3, ensure_ascii=False)[:160])


def leg4_cross_project_dup(workdir):
    root = os.path.join(workdir, "reg4")
    h1, h2 = os.path.join(root, "h1"), os.path.join(root, "h2")
    os.makedirs(h1); os.makedirs(h2)
    rl.write_registry(root, "pa", "PA", [h1])
    rl.write_registry(root, "pb", "PB", [h2])
    rl.write_file(os.path.join(h1, "inspection.yaml"), DECL_X)
    rl.write_file(os.path.join(h2, "inspection.yaml"), DECL_X)   # 同实例 id=撞名
    out = run_trig({"SANDBAR_PROJECTS_DIR": root}, "decl")
    res = out.get("result") or {}
    degraded = json.dumps(res.get("degraded") or [], ensure_ascii=False)
    check("子用例4a 撞名实例从聚合白名单剔除",
          out.get("ok") is True and res.get("enabled_instances") == [],
          "enabled=%s" % res.get("enabled_instances"))
    check("子用例4b 撞名点名两处（项目+路径）",
          "pa" in degraded and "pb" in degraded and "inst-x" in degraded,
          "degraded=%s" % degraded[:220])
    out2 = run_trig({"SANDBAR_PROJECTS_DIR": root}, "trigger", "--instance", "inst-x")
    err2 = str(out2.get("error") or "")
    check("子用例4c trigger 面多命中报错点名两项目",
          out2.get("ok") is False and "pa" in err2 and "pb" in err2,
          "err=%s" % err2[:200])


def leg5_no_fallback(workdir):
    check("子用例5a 引擎旧声明已删（迁移交付本体）", not os.path.exists(ENGINE_DECL),
          "旧位仍在：%s" % ENGINE_DECL)
    check("子用例5b 样例模板在场（照 model-routes-sample 同款做法）",
          os.path.exists(SAMPLE_DECL), SAMPLE_DECL)
    # 空注册表（零项目条目）=显式报错（不冒充全绿无巡检面）。夹具走 legacy 单文件
    # 空 projects: 形态——env 目录形态会被装载器种子迁移注入条目（设计如此），造不出
    # 「真空」；legacy 装载器的显式报错即本断言面。
    empty_yaml = rl.write_file(os.path.join(workdir, "empty-reg.yaml"), "projects:\n")
    out = run_trig({"SANDBAR_PROJECTS_YAML": empty_yaml}, "decl")
    err = str(out.get("error") or "")
    check("子用例5c 空注册表显式报错（不冒充全绿无巡检面）",
          out.get("ok") is False
          and ("没有任何项目条目" in err or "注册表为空" in err),
          "out=%s" % json.dumps(out, ensure_ascii=False)[:160])
    root = os.path.join(workdir, "reg1")   # 子用例1 夹具：proj-a/b/c/d，无样例实例
    out2 = run_trig({"SANDBAR_PROJECTS_DIR": root}, "decl")
    enabled = (out2.get("result") or {}).get("enabled_instances") or []
    sample_ids = []
    if os.path.exists(SAMPLE_DECL):
        sample_ids = re.findall(r"-\s*id:\s*(\S+)", open(SAMPLE_DECL, encoding="utf-8").read())
    check("子用例5d 样例实例不进聚合白名单",
          out2.get("ok") is True and not (set(sample_ids) & set(enabled)),
          "sample=%s enabled=%s" % (sample_ids, enabled))


def leg6_coverage_overlay(workdir):
    root = os.path.join(workdir, "reg1")   # 聚合夹具：inst-x/inst-y
    ov = rl.write_file(os.path.join(workdir, "overlay.yaml"),
                       rl.decl_yaml([("inst-ov", "proj-ov", "0 5 * * *", "test")]))
    env = {"SANDBAR_PROJECTS_DIR": root, "SANDBAR_INSPECTION_DECL": ov}
    out = run_trig(env, "decl")
    res = out.get("result") or {}
    ids = [i.get("id") for i in res.get("instances", [])]
    check("子用例6a 覆盖层生效=单文件整体替代聚合（mode=single）",
          res.get("mode") == "single" and ids == ["inst-ov"],
          "mode=%s ids=%s" % (res.get("mode"), ids))
    out2 = run_trig(env, "trigger", "--instance", "inst-x")   # 聚合实例在覆盖层下不可见
    check("子用例6b 整体替代非并集（聚合实例不可解析）",
          out2.get("ok") is False and "inst-x" in str(out2.get("error")),
          "err=%s" % str(out2.get("error"))[:160])
    out3 = run_trig({"SANDBAR_PROJECTS_DIR": root}, "decl")   # 撤 env 恢复聚合
    check("子用例6c 撤覆盖层恢复聚合",
          (out3.get("result") or {}).get("mode") == "aggregate",
          "mode=%s" % (out3.get("result") or {}).get("mode"))


def main() -> int:
    workdir = tempfile.mkdtemp(prefix="sandbar-t26091602-gate-")
    os.environ["SANDBAR_TARGET_HOST"] = lib.TEST_TARGET_HOST
    os.environ["SANDBAR_NAMESPACE"] = lib.TEST_NAMESPACE
    try:
        leg0_static()
        leg1_aggregate_states(workdir)
        leg2_unknown_instance(workdir)
        leg3_pointer_paths(workdir)
        leg4_cross_project_dup(workdir)
        leg5_no_fallback(workdir)
        leg6_coverage_overlay(workdir)
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
    if failures:
        print("FAIL_REASON: " + "；".join(failures), flush=True)
        return 1
    print("PASS_REASON: 聚合声明门 %d 断言全绿（遍历/指路/撞名/零回落/覆盖层）" % len(notes),
          flush=True)
    return 0


if __name__ == "__main__":
    lib.reexec_venv_if_missing()
    sys.exit(main())
