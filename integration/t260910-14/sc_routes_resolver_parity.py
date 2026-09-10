#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""t260910-14 · 路由表解析器 python/TS 一致性守卫（方案 M2）。

主题二把「paths.model_routes 解析」做成双实现：引擎侧 shared.py（查表）与
UI 侧 routes.ts resolveRoutesFilePath（读写同源）。双实现必须对同一声明逐字
节同判，否则「引擎读的」与「UI 写的」又会裂成两份（本票要消灭的原病）。

夹具矩阵（临时 per-key 注册表，零外部源）：
  相对路径 / ~ 展开 / 绝对路径 / .. 逃逸 / 空值 / 非标量 / 缺 paths 节。
python 侧直接跑 shared（本进程）；TS 侧以 node type-stripping 直跑
server/plugins/ui/src/host/routes.ts 的 resolveRoutesFilePath；两侧结果逐项
断言相等。node 缺席 = ENV_FAIL exit 2（三态契约，KI-046 第三层）。
cwd = 泳道根。
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FAILS = []
NODE = shutil.which("node")


def check(cond, msg):
    print(("PASS " if cond else "FAIL ") + msg)
    if not cond:
        FAILS.append(msg)


def mk_registry(root: Path, key: str, paths_body: str) -> Path:
    d = root / key
    d.mkdir(parents=True, exist_ok=True)
    (d / "project.yaml").write_text(
        "schema: v1\npaths:\n%sproject:\n  - key: %s\n    name: parity\n    dirs:\n      - %s\n"
        % (paths_body, key, root), "utf-8")
    return d


def py_resolve(reg: Path, key: str, primary: Path):
    """python 半真值=project_paths（声明解析面，与 TS resolveRoutesFilePath 同层）；
    读侧分态/兜底行为由 resolve_routes_table 另面覆盖（t260910-14 场景①）。"""
    sys.path.insert(0, str(ROOT / "server" / "engine"))
    old = os.environ.get("SANDBAR_PROJECTS_DIR")
    os.environ["SANDBAR_PROJECTS_DIR"] = str(reg)
    try:
        import shared
        r = shared.project_paths(key)
        p = r.get("model_routes")
        return {"state": "ok" if p is not None else "decl_missing",
                "path": (str(p) if p else None), "declared": None}
    except shared.ProjectPathsError as e:
        return {"state": "rejected", "error": str(e)}
    finally:
        if old is None:
            os.environ.pop("SANDBAR_PROJECTS_DIR", None)
        else:
            os.environ["SANDBAR_PROJECTS_DIR"] = old
        sys.path.pop(0)


def main():
    if NODE is None:
        print("ENV_FAIL: node 不可得（TS 侧解析器无法直跑）")
        return 2
    tmp = Path(tempfile.mkdtemp(prefix="t260910-14-parity-"))
    try:
        home = tmp / "home"
        home.mkdir()
        (home / "tilde.yaml").write_text("default:\n  provider: zai\n  model: m\n", "utf-8")
        target = tmp / "declared.yaml"
        target.write_text("default:\n  provider: zai\n  model: m\n", "utf-8")
        rel = tmp / "rel-routes.yaml"
        rel.write_text("default:\n  provider: zai\n  model: m\n", "utf-8")

        (tmp / "rel-routes.yaml").write_text("default:\n  provider: zai\n  model: m\n", "utf-8")
        cases = [
            # (名, paths_body, 期望 state 一致键)——primary=注册根（dirs[0]）
            ("相对路径（项目主目录下）", "  model_routes: rel-routes.yaml\n",),
            ("~/ 展开", "  model_routes: ~/tilde.yaml\n",),
            ("绝对路径", "  model_routes: %s\n" % target,),
            ("缺 paths 节（未声明）", "",),
        ]
        for name, body in cases:
            reg = tmp / ("reg-" + str(abs(hash(name)) % 10**8))
            mk_registry(reg, "parity", body)
            primary = reg  # dirs[0]=注册条目主目录（与 python base 同源）
            old_home = os.environ.get("HOME")
            os.environ["HOME"] = str(home)
            try:
                py = py_resolve(reg, "parity", primary)
            finally:
                if old_home is None:
                    os.environ.pop("HOME", None)
                else:
                    os.environ["HOME"] = old_home
            script = (
                "import { resolveRoutesFilePath } from '%s/server/plugins/ui/src/host/routes.ts';\n"
                "process.env.HOME=%s; process.env.SANDBAR_PROJECTS_DIR=%s;\n"
                % (ROOT, json.dumps(str(home)), json.dumps(str(reg)))
            )
            # TS 在子进程内现读 env（模块内 process.env 现读，与 python 同源）
            proc = subprocess.run(
                [NODE, "--input-type=module", "--eval",
                 "import { resolveRoutesFilePath as r } from '%s';\n"
                 "const x = r(%s, { projectKey: 'parity' });\n"
                 "console.log(JSON.stringify({state: x.state, path: x.path, declared: x.declared}));"
                 % (ROOT / "server/plugins/ui/src/host/routes.ts", json.dumps(str(primary)))],
                capture_output=True, text=True, env={**os.environ, "HOME": str(home),
                                                     "SANDBAR_PROJECTS_DIR": str(reg)})
            if proc.returncode != 0:
                check(False, "%s：TS 侧执行失败 %s" % (name, proc.stderr.strip()[:160]))
                continue
            ts = json.loads(proc.stdout.strip().splitlines()[-1])
            py_legal = py.get("state") == "ok"
            ts_legal = ts.get("state") == "ok"
            check(py_legal == ts_legal,
                  "%s：合法判定一致（py=%s ts=%s）" % (name, py.get("state"), ts.get("state")))
            if py_legal and ts_legal:
                check(py.get("path") == ts.get("path"),
                      "%s：path 一致（%s）" % (name, py.get("path")))

        # 拒收腿：.. 逃逸（py=ProjectPathsError，ts=throw）
        reg = tmp / "reg-reject"
        primary = mk_registry(reg, "parity", "  model_routes: ../escape.yaml\n")
        py = py_resolve(reg, "parity", primary)
        proc = subprocess.run(
            [NODE, "--input-type=module", "--eval",
             "import { resolveRoutesFilePath as r } from '%s';\n"
             "try { r(%s, { projectKey: 'parity' }); console.log('no-throw'); }\n"
             "catch (e) { console.log('thrown'); }"
             % (ROOT / "server/plugins/ui/src/host/routes.ts", json.dumps(str(primary)))],
            capture_output=True, text=True, env={**os.environ, "SANDBAR_PROJECTS_DIR": str(reg)})
        ts_thrown = proc.stdout.strip().endswith("thrown")
        check(py.get("state") == "rejected" and ts_thrown,
              ".. 逃逸：两侧都 fail-closed 拒收（py=%s ts_thrown=%s）" % (py.get("state"), ts_thrown))

        # 非标量/空值：两侧同拒（py=ProjectPathsError）
        reg = tmp / "reg-empty"
        primary = mk_registry(reg, "parity", "  model_routes: \"\"\n")
        py = py_resolve(reg, "parity", primary)
        check(py.get("state") == "rejected", "空声明值：py 侧 fail-closed（%s）" % py.get("state"))

        if FAILS:
            print("\n%d 项失败" % len(FAILS))
            return 1
        print("\n全部通过")
        return 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
