#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""t260910-14 场景①：模型路由表真源=声明指向文件，分层兜底留痕（宿主风险令 260910 夜口径）。

intent（登记于 run_scenarios.py，本文件为其执行体）：
真源=项目注册表条目 paths.model_routes 指向的文件，引擎读面（python 半）逐腿断言：
  腿0 仓内表在位：server/model-routes.yaml 本票保留不删（宿主令①——删除延后另开小票）；
  腿1 声明 ok：paths.model_routes 指向机器级文件 → model_route_for 读到该表内容（哨兵模型）；
  腿2 改表生效：改声明指向文件 → 下次解析拿新模型（验收 A 的解析面）；
  腿3 声明文件缺失：分态可辨（state!=ok）且**分层兜底=仓内表**（宿主令①零断供）——
      生效模型==仓内表 integration 条目，绝非静默回落 profile 默认（宿主令③）；
  腿4 声明缺失：分态可辨（decl 缺失态）+ 兜底仓内表留痕（现行行为零回归，宿主令④c）；
  腿5 内容坏：分态可辨 + 点名 path+原因，解析不炸（spawn 不被毒表打死）；
  腿6 回滚可操作（宿主令④b）：声明改回仓内相对路径 → 生效==仓内表（与腿4 同值）；
  腿7 形状：`..` 逃逸 fail-closed 拒收（点名条目+键）；`~/x` 展开到家目录（不写真 HOME）；
      空值拒收。
三态：引擎 venv（PyYAML）缺席=ENV_FAIL exit 2；断言破面=exit 1；全绿=exit 0。
实现落地前红属预期（TDD 信号，契约形状=批准方案 T2-2 的判别结果），arbitrate/merge 期必须绿。
与 t260902-07 守卫（表静态校验/查表性质，L2）与 sc_paths_contract_doc_guard G6（重写后钉新语义）
intent 不同面：本条锁「真源随声明走 + 分层兜底留痕」的系统拼装行为。
"""
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
KEY = "t26091014a"

sys.path.insert(0, HERE)


def pick_py():
    """引擎 venv（PyYAML 在场优先，路径按 t260907-10 版面契约=server/engine）；全缺=ENV_FAIL。"""
    for cand in (os.path.join(REPO, "server", "engine", ".venv", "bin", "python"),
                 "python3"):
        if cand != "python3" and not os.path.exists(cand):
            continue
        p = subprocess.run([cand, "-c", "import yaml, shared; print('ok')"],
                           capture_output=True, text=True, cwd=os.path.join(REPO, "server", "engine"))
        if p.returncode == 0:
            return cand
    return None


FAILS = []


def check(cond, msg):
    print(("PASS " if cond else "FAIL ") + msg, flush=True)
    if not cond:
        FAILS.append(msg)


def run_py(script, env):
    """在引擎解释器里跑一段探针脚本（cwd=server/engine 以 import shared），回 (rc, stdout)。"""
    p = subprocess.run([PY, "-c", script], capture_output=True, text=True,
                       cwd=os.path.join(REPO, "server", "engine"), env=env, timeout=120)
    return p.returncode, p.stdout, p.stderr


def write_registry(reg_dir, rel_or_abs_decl):
    """夹具注册表：<reg>/<key>/project.yaml，dirs→夹具仓，paths.model_routes 按参数落。"""
    d = os.path.join(reg_dir, KEY)
    os.makedirs(d, exist_ok=True)
    lines = ["schema: v1", "project:", "  - key: %s" % KEY,
             "    name: t260910-14 routes fixture", "    dirs:", "      - %s" % FIX_REPO]
    if rel_or_abs_decl is not None:
        lines += ["paths:", "  model_routes: %s" % rel_or_abs_decl]
    with open(os.path.join(d, "project.yaml"), "w") as f:
        f.write("\n".join(lines) + "\n")


PROBE = r'''
import json, os, sys
sys.path.insert(0, os.getcwd())
import shared
key = %(key)r
out = {}
def snap():
    try:
        r = shared.routes_file_for_spawn(key)
        out["shape"] = "dict" if isinstance(r, dict) else "raw"
        if isinstance(r, dict):
            out["state"] = r.get("state")
            out["path"] = str(r.get("path") or "")
            out["error"] = str(r.get("error") or "")
            rf = r.get("path")
        else:
            out["path"] = str(r)
            rf = r
        out["model"] = shared.model_route_for("integration", "", routes_file=rf)
    except shared.ProjectPathsError as e:
        out["shape"] = "error"
        out["error"] = str(e)
    except Exception as e:
        out["shape"] = "crash"
        out["error"] = "%%s: %%s" %% (type(e).__name__, str(e)[:200])
    print(json.dumps(out))
snap()
'''


def probe(env):
    rc, so, se = run_py(PROBE % {"key": KEY}, env)
    if rc != 0 or not so.strip():
        return {"shape": "probe-fail", "error": (se or so).strip()[:300]}
    return json.loads(so.strip().splitlines()[-1])


REPO_TABLE_PROBE = r'''
import json, sys, yaml
t = yaml.safe_load(open(%(repo_table)r, encoding="utf-8")) or {}
e = (t.get("roles") or {}).get("integration") or {}
if isinstance(e, dict) and e.get("model"):
    print(json.dumps([e.get("provider"), e.get("model")]))
else:
    d = t.get("default") or {}
    print(json.dumps([d.get("provider"), d.get("model")]))
'''


def repo_table_integration_model():
    rc, so, _ = run_py(REPO_TABLE_PROBE % {"repo_table": os.path.join(REPO, "server", "model-routes.yaml")},
                       dict(os.environ))
    return tuple(json.loads(so.strip().splitlines()[-1])) if rc == 0 else (None, None)


MACHINE_TABLE = """default:
  provider: sentinel-default
  model: default-model
roles:
  integration:
    provider: sentinel-machine
    model: machine-a
"""

tmp = None
try:
    PY = pick_py()
    if PY is None:
        print("ENV_FAIL: 引擎 venv（PyYAML/shared 可导入）缺席——路由真源场景无法执行（三态 exit 2）")
        sys.exit(2)
    tmp = tempfile.mkdtemp(prefix="t26091014a-")
    # 夹具仓：server/model-routes.yaml（=仓内表副本，宿主令①兜底件）+ machine 级目标（仓外）
    FIX_REPO = os.path.join(tmp, "fixrepo")
    os.makedirs(os.path.join(FIX_REPO, "server"), exist_ok=True)
    shutil.copyfile(os.path.join(REPO, "server", "model-routes.yaml"),
                    os.path.join(FIX_REPO, "server", "model-routes.yaml"))
    MACHINE_DIR = os.path.join(tmp, "machine")
    os.makedirs(MACHINE_DIR, exist_ok=True)
    MACHINE = os.path.join(MACHINE_DIR, "model-routes.yaml")
    with open(MACHINE, "w", encoding="utf-8") as f:
        f.write(MACHINE_TABLE)
    REG = os.path.join(tmp, "registry")

    base_env = dict(os.environ)
    base_env["SANDBAR_PROJECTS_DIR"] = REG

    # 腿0：仓内表在位（本票不删，宿主令①/④c 前提）
    check(os.path.isfile(os.path.join(REPO, "server", "model-routes.yaml")),
          "腿0：仓内 server/model-routes.yaml 在位（本票保留=兜底件，删除延后另票）")
    repo_model = repo_table_integration_model()
    check(bool(repo_model and repo_model[1]),
          "腿0：仓内表可解析出 integration 生效模型（%s）" % (repo_model,))

    # 腿1：声明→机器级文件（绝对路径形态），读到哨兵
    write_registry(REG, MACHINE)
    r = probe(base_env)
    check(r.get("shape") == "dict" and r.get("state") == "ok",
          "腿1：声明在位 → state=ok（实际 shape=%s state=%s err=%s）" % (r.get("shape"), r.get("state"), r.get("error", "")))
    check(r.get("model") == {"provider": "sentinel-machine", "model": "machine-a"},
          "腿1：生效模型来自声明指向文件（哨兵 machine-a，实际 %s）" % (r.get("model"),))

    # 腿2：改声明指向文件 → 新模型（验收 A 解析面）
    with open(MACHINE, "w", encoding="utf-8") as f:
        f.write(MACHINE_TABLE.replace("machine-a", "machine-b"))
    r = probe(base_env)
    check(r.get("model") == {"provider": "sentinel-machine", "model": "machine-b"},
          "腿2：改表即生效（machine-b，实际 %s）" % (r.get("model"),))

    # 腿3：声明文件缺失 → 分态可辨 + 兜底=仓内表（禁静默回落 profile 默认）
    write_registry(REG, os.path.join(MACHINE_DIR, "absent.yaml"))
    r = probe(base_env)
    check(r.get("shape") == "dict" and r.get("state") not in (None, "ok"),
          "腿3：声明文件缺失 → 分态点名非 ok（实际 state=%s）" % (r.get("state"),))
    check(r.get("model") == {"provider": repo_model[0], "model": repo_model[1]},
          "腿3：兜底生效=仓内表 integration 模型（宿主令①零断供；实际 %s）" % (r.get("model"),))
    check(bool(r.get("error")), "腿3：留痕非静默（result.error 点名 path+原因，实际 %r)" % (r.get("error") or "")[:160])

    # 腿4：声明缺失 → 分态可辨 + 仓内表兜底（现行行为零回归）
    write_registry(REG, None)
    r = probe(base_env)
    check(r.get("shape") == "dict" and r.get("state") not in (None, "ok"),
          "腿4：声明缺失 → 分态点名（实际 state=%s）" % (r.get("state"),))
    check(r.get("model") == {"provider": repo_model[0], "model": repo_model[1]},
          "腿4：未声明行为零回归=仓内表（实际 %s）" % (r.get("model"),))
    check(bool(r.get("error")) or bool(r.get("state")),
          "腿4：分态留痕在结果可辨（宿主令③禁静默）")

    # 腿5：内容坏 → 分态点名 + 解析不炸
    BAD = os.path.join(MACHINE_DIR, "bad.yaml")
    with open(BAD, "w", encoding="utf-8") as f:
        f.write("roles: [broken:\n  - :\n")
    write_registry(REG, BAD)
    r = probe(base_env)
    check(r.get("shape") == "dict" and r.get("state") not in (None, "ok"),
          "腿5：坏表 → 分态点名非 ok（实际 state=%s）" % (r.get("state"),))
    check(r.get("shape") != "crash", "腿5：毒表不炸解析面（shape=%s）" % r.get("shape"))
    check(BAD in (r.get("error") or "") or MACHINE_DIR in (r.get("error") or ""),
          "腿5：留痕点名毒表路径（error=%r）" % (r.get("error") or "")[:160])

    # 腿6：回滚=声明改回仓内相对路径（宿主令④b）
    write_registry(REG, "server/model-routes.yaml")
    r = probe(base_env)
    check(r.get("model") == {"provider": repo_model[0], "model": repo_model[1]},
          "腿6：声明改回仓内相对路径 → 生效==仓内表（回滚可操作；实际 %s）" % (r.get("model"),))

    # 腿7：形状——.. 拒收 / ~ 展开 / 空值拒收
    write_registry(REG, "../../etc/passwd")
    r = probe(base_env)
    check(r.get("shape") == "error" and ".." in (r.get("error") or "") + (r.get("state") or ""),
          "腿7a：`..` 逃逸 fail-closed 拒收（shape=%s err=%s）" % (r.get("shape"), (r.get("error") or "")[:80]))
    write_registry(REG, "~/t260910-14-absent-routes.yaml")
    r = probe(base_env)
    expanded = os.path.join(pathlib.Path.home(), "t260910-14-absent-routes.yaml")
    check(expanded in json.dumps(r, ensure_ascii=False),
          "腿7b：`~/x` 展开后的声明路径在结果可见（找 %s；result=%s）"
          % (expanded, json.dumps(r, ensure_ascii=False)[:160]))
    write_registry(REG, "   ")
    r = probe(base_env)
    check(r.get("shape") == "error" or r.get("state") not in (None, "ok"),
          "腿7c：空白声明拒收/点名（shape=%s state=%s）" % (r.get("shape"), r.get("state")))
finally:
    if tmp:
        shutil.rmtree(tmp, ignore_errors=True)

print("t260910-14 routes-truth-fallback: failed=%d" % len(FAILS))
sys.exit(1 if FAILS else 0)
