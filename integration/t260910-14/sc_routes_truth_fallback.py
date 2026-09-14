#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""t260910-14 场景①：模型路由表真源=声明指向文件（t260914-05 兜底腿退役后的无表三态口径）。

intent（登记于 run_scenarios.py，本文件为其执行体）：
真源=项目注册表条目 paths.model_routes 指向的文件，引擎读面（python 半）逐腿断言：
  腿0 仓内表在位（(b) 降级口径：本票不删仓内文件、只退役读腿）——并以此为反毒前提：
      它在场也绝不被静默读（见腿4）；
  腿1 声明 ok：paths.model_routes 指向机器级文件 → model_route_for 读到该表内容（哨兵模型）；
  腿2 改表生效：改声明指向文件 → 下次解析拿新模型（验收 A 的解析面）；
  腿3 声明文件缺失：state=file_missing 分态可辨、**无表**（生效模型=None=profile 默认），
      引擎面单点告警点名 state+路径+指纹（t260914-05：绝无「兜底=仓内表」腿）；
  腿4 声明缺失：state=decl_missing、path=""、无表；**反毒断言**：仓内表即使在位，
      生效模型也不是它的值（现场 A/B「过期表被静默用错」的机械反证）+ 引擎面点名；
  腿5 内容坏：state=bad_content 分态可辨 + 字节指纹（sha256:12hex）+ 点名 path+原因，
      解析不炸（spawn 不被毒表打死）；
  腿6 显式声明仓内相对路径 → state=ok、生效==仓内表（(b) 口径下文件在=显式声明合法；
      (a) 删表后此腿自动退化为「声明指向缺失→file_missing」，语义仍自洽）；
  腿7 形状：`..` 逃逸 fail-closed 拒收（点名条目+键）；`~/x` 展开到家目录（不写真 HOME）；
      空值拒收。
三态：引擎 venv（PyYAML）缺席=ENV_FAIL exit 2；断言破面=exit 1；全绿=exit 0。
与 t260902-07 守卫（表静态校验/查表性质，L2）与 sc_paths_contract_doc_guard G6
intent 不同面：本条锁「真源随声明走 + 无表三态点名不静默」的系统拼装行为。
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
    """在引擎解释器里跑一段探针脚本（cwd=server/engine 以 import shared），回 (rc, stdout, stderr)。"""
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
try:
    r = shared.routes_file_for_spawn(key)
    out["shape"] = "dict"
    out["state"] = r.get("state")
    out["path"] = str(r.get("path") or "")
    out["error"] = str(r.get("error") or "")
    out["fingerprint"] = str(r.get("fingerprint") or "")
    if r.get("table") is None:
        out["model"] = None  # 无表=本轮模型来 profile 默认（消费方面同构：不打 patch）
    else:
        out["model"] = shared.model_route_for("integration", "",
                                              table=r.get("table"), routes_file=r.get("path"))
except shared.ProjectPathsError as e:
    out["shape"] = "error"
    out["error"] = str(e)
except Exception as e:
    out["shape"] = "crash"
    out["error"] = "%%s: %%s" %% (type(e).__name__, str(e)[:200])
print(json.dumps(out))
'''


def probe(env):
    rc, so, se = run_py(PROBE % {"key": KEY}, env)
    if rc != 0 or not so.strip():
        return {"shape": "probe-fail", "error": (se or so).strip()[:300]}
    r = json.loads(so.strip().splitlines()[-1])
    r["stderr"] = se or ""  # 引擎单点告警走 stderr（lastResort handler），父进程可断言
    return r


def has_named_warning(stderr, state):
    """引擎面单点点名：[model_route] + state=<态> + 指纹段。"""
    return "[model_route]" in stderr and ("state=%s" % state) in stderr and "指纹=" in stderr


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
    # 夹具仓：server/model-routes.yaml（仓内表副本——(b) 口径下它在场，用作反毒/显式声明腿）
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

    # 腿0：仓内表在位（(b) 口径保留；它是腿4 反毒与腿6 显式声明的前提，不是兜底件）
    repo_table = os.path.join(REPO, "server", "model-routes.yaml")
    check(os.path.isfile(repo_table),
          "腿0：仓内 server/model-routes.yaml 在位（(b) 降级口径：不删文件、只退役读腿）")
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

    # 腿3：声明文件缺失 → file_missing 点名 + 无表（不再有兜底腿）
    write_registry(REG, os.path.join(MACHINE_DIR, "absent.yaml"))
    r = probe(base_env)
    check(r.get("shape") == "dict" and r.get("state") == "file_missing",
          "腿3：声明文件缺失 → state=file_missing 分态可辨（实际 state=%s）" % (r.get("state"),))
    check(r.get("model") is None,
          "腿3：无表=生效模型 None（=profile 默认；实际 %s）" % (r.get("model"),))
    check(os.path.join(MACHINE_DIR, "absent.yaml") in (r.get("error") or ""),
          "腿3：留痕点名声明路径（error=%r）" % (r.get("error") or "")[:160])
    check(has_named_warning(r.get("stderr", ""), "file_missing"),
          "腿3：引擎面单点告警含 state=file_missing+指纹（stderr=%r）" % (r.get("stderr", "") or "")[:200])

    # 腿4：声明缺失 → decl_missing + 无表 + 反毒（仓内表在场也不被读）
    write_registry(REG, None)
    r = probe(base_env)
    check(r.get("shape") == "dict" and r.get("state") == "decl_missing" and r.get("path") == "",
          "腿4：声明缺失 → state=decl_missing 且 path=\"\"（实际 state=%s path=%r）"
          % (r.get("state"), r.get("path")))
    check(r.get("model") is None and repo_model[1] not in json.dumps(r.get("model")),
          "腿4：反毒——仓内表在位但生效模型不是它的值（model=%s，仓内表=%s）"
          % (r.get("model"), repo_model))
    check(has_named_warning(r.get("stderr", ""), "decl_missing"),
          "腿4：引擎面单点告警含 state=decl_missing+指纹（stderr=%r）" % (r.get("stderr", "") or "")[:200])

    # 腿5：内容坏 → bad_content + 字节指纹 + 点名路径，解析不炸
    BAD = os.path.join(MACHINE_DIR, "bad.yaml")
    with open(BAD, "w", encoding="utf-8") as f:
        f.write("roles: [broken:\n  - :\n")
    write_registry(REG, BAD)
    r = probe(base_env)
    check(r.get("shape") == "dict" and r.get("state") == "bad_content",
          "腿5：坏表 → state=bad_content 分态可辨（实际 state=%s）" % (r.get("state"),))
    check(r.get("shape") != "crash", "腿5：毒表不炸解析面（shape=%s）" % r.get("shape"))
    check(BAD in (r.get("error") or ""),
          "腿5：留痕点名毒表路径（error=%r）" % (r.get("error") or "")[:160])
    check(re.match(r"^sha256:[0-9a-f]{12}$", r.get("fingerprint") or "") is not None,
          "腿5：可读字节的坏文件带内容指纹（fingerprint=%s）" % (r.get("fingerprint"),))
    check("sha256:" in (r.get("stderr") or ""),
          "腿5：引擎面告警含指纹段（stderr=%r）" % (r.get("stderr", "") or "")[:200])

    # 腿6：显式声明仓内相对路径 → state=ok、生效==仓内表（显式声明合法，非兜底）
    write_registry(REG, "server/model-routes.yaml")
    r = probe(base_env)
    check(r.get("state") == "ok" and r.get("model") == {"provider": repo_model[0], "model": repo_model[1]},
          "腿6：显式声明仓内相对路径 → 生效==仓内表（state=%s，实际 %s）"
          % (r.get("state"), r.get("model")))

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
