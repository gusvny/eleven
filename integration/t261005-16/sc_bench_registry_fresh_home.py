#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""t261005-16 场景①：新家注册表自足契约（灰盒 L2，integration 岗 design_integration_tests 段）。

intent（登记于 run_scenarios.py）——KI-204 / 工单 REQUIRED OUTCOME 1 的机制面钉子：
一个新家（新装/临时台/隔离台/另一台机器）的注册表装载**绝不能重播历史迁移种子**，
以致种回一个目录已不存在的退役项目（实证形态：宿主家目录下历史仓路径已删，
`server/projects.yaml` 种子仍打头 `key: suyou`，采集台新家被重播 → 新建会话
ENOENT → capture exit 1，merge_check UI 证据项恒红）。本场景把断言落在公开契约上：

- A（bench 注册表自足面）：采集台的注册表构建公开缝 `buildBenchRegistry`
  （capture-lane.mjs 导出，计划定稿的注入面）产出的新家注册表——`.migrated`
  标记在场（两侧装载器 shared.py / project-registry.ts 的跳过判据）、per-key
  project.yaml 的 key 合法（PROJECT_KEY_RE）且 dirs[0] 落在临时台目录内**且真实
  存在**（会话创建不可能 ENOENT，机器现实无关）。
- B（畸形输入面，宿主纪律）：目标位置已有垃圾文件 → 构建显式点名失败，
  不静默覆盖（写入面防呆）。
- C（装载跳过面，双侧对照）：
  - C1 带 `.migrated`：引擎装载前一致性检查 `shared.ensure_registry_migrated`
    幂等跳过，根里**不出现** suyou 条目（用户可感知：新家注册表干净）；
  - C2 阴性对照（去 marker）：同根重播种子 → suyou 条目带着死目录被种回——
    证明故障机制真实、marker 正是阻断点（修前红/修后绿的机制级对照，
    工单 OUTCOME 2「migration step alone」口径）。
- D（key 白名单面）：bench key 必须过 PROJECT_KEY_RE（防路径穿越的既有契约不弱化）。

intent 分工：capture 全旅程（真控制台+浏览器、exit 0/证据平铺）归
t261005-16-capture-fresh-home-journey；截图内容与视图族归 capture 家族既有条目；
t261005-13-evidence-layout-named 只守平铺契约文字面——本条不重复。
种子表 server/projects.yaml 为 protected 面，本场景只读。

实现落地前 A/B/D 红属预期（TDD 信号，缺导出=点名 FAIL 非 ENV_FAIL——
产品面缺失是契约红）；arbitrate/merge 期必须绿。零 docker、零端口、零 3099；
临时目录随用随收；引擎模块缺席=ENV_FAIL exit 2。
"""
import json
import os
import re
import shutil
import subprocess
import sys
import pathlib
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
ENGINE = os.path.join(REPO, "server", "engine")
sys.path.insert(0, ENGINE)
# lib_result.py lives in integration/ — sys.path[0] is this ticket dir, so the
# shared helper dir must be added explicitly (works from any cwd, any runner).
sys.path.insert(0, os.path.join(REPO, "integration"))

try:
    from lib_result import emit_case
    import shared as engine_shared  # noqa: E402
except Exception as e:  # engine module absent = environment red, named
    try:
        from lib_result import emit_case
        emit_case(name="t261005-16-bench-registry-fresh-home", status="not-checked",
                  cause="external", reason="engine shared.py import failed",
                  evidence=repr(e)[:300])
    except Exception:
        print("ENV_FAIL: engine shared.py import failed: %r" % (e,))
    sys.exit(2)

SUITE = "t261005-16-bench-fresh-home"
BENCH_KEY = "capture-bench"
_FAILS = []


def check(name, ok, reason="", evidence=""):
    emit_case(name=name, suite=SUITE,
              status="pass" if ok else "fail", cause="self",
              reason=reason, evidence=str(evidence)[:400])
    if not ok:
        _FAILS.append(name)


def run_bench_build(tmp_home):
    """Invoke the bench registry builder through the public export seam.
    Returns (ok, payload) — payload is the built root path or the error text."""
    script = (
        "import { pathToFileURL } from 'node:url';"
        "import(pathToFileURL(process.argv[2]).href).then(async (m) => {"
        "  if (typeof m.buildBenchRegistry !== 'function') {"
        "    console.log(JSON.stringify({ ok: false, error: 'export buildBenchRegistry missing' }));"
        "    return;"
        "  }"
        "  try {"
        "    const root = await m.buildBenchRegistry(process.argv[3]);"
        "    console.log(JSON.stringify({ ok: true, root: String(root) }));"
        "  } catch (e) {"
        "    console.log(JSON.stringify({ ok: false, error: String(e && e.message || e) }));"
        "  }"
        "});"
    )
    # argv layout under `node -e`: argv[1] is the FIRST trailing arg. It must NOT
    # be the module path — capture-lane's direct-invocation guard compares
    # argv[1] to its own file and would run main() on import. Park a marker
    # there; argv[2]/argv[3] carry the module path and the temp home.
    p = subprocess.run(["node", "-e", script,
                        "import-probe",
                        os.path.join(REPO, "server", "ui-check", "capture-lane.mjs"),
                        tmp_home],
                       capture_output=True, text=True, timeout=60, cwd=REPO)
    out = (p.stdout or "").strip().splitlines()
    if p.returncode != 0 or not out:
        return False, {"ok": False, "error": "node rc=%s stderr=%s" % (p.returncode, (p.stderr or "")[-200:])}
    try:
        payload = json.loads(out[-1])
    except Exception:
        return False, {"ok": False, "error": "unparseable builder output: %s" % out[-1][:200]}
    if not isinstance(payload, dict):
        payload = {"ok": False, "error": str(payload)[:200]}
    return bool(payload.get("ok")), payload


def main():
    tmp = tempfile.mkdtemp(prefix="t26100516-bench-registry-")
    try:
        tmp_home = os.path.join(tmp, "home")
        os.makedirs(tmp_home)

        # ---- A/D: the bench registry build contract ----
        ok, payload = run_bench_build(tmp_home)
        check("A1-builder-export-and-run", ok,
              "bench registry builder must exist and run on a fresh home",
              payload.get("error") or payload.get("root"))
        if not ok:
            # Pre-implement red is expected, but the remaining faces need the build.
            check("A2-marker-and-project-yaml", False,
                  "skipped: builder unavailable (see A1)", "dependent on A1")
            check("B1-junk-file-fails-loud", False,
                  "skipped: builder unavailable (see A1)", "dependent on A1")
        else:
            root = payload.get("root") or os.path.join(tmp_home, "bench-registry", "projects")
            marker = os.path.join(root, ".migrated")
            pyaml = os.path.join(root, BENCH_KEY, "project.yaml")
            check("A2-migrated-marker-present", os.path.isfile(marker),
                  ".migrated is the skip criterion on BOTH loaders; absent = seed replays",
                  marker)
            text = ""
            if os.path.isfile(pyaml):
                with open(pyaml, "r", encoding="utf-8") as fh:
                    text = fh.read()
            # schema v1 shape: top-level `schema:` + `project:` list item
            # (`  - key: ...`), byte-compatible with serializeProjectYaml —
            # a flat top-level key: is quarantined by both parsers
            # (t261005-16 arbitrate round 1 defect, pinned here).
            key_ok = bool(re.search(r"^\s*-?\s*key:\s*%s\s*$" % re.escape(BENCH_KEY), text, re.M))
            shape_ok = bool(re.search(r"^schema:\s*v1\s*$", text, re.M)) \
                and bool(re.search(r"^project:\s*$", text, re.M))
            dir_m = re.search(r"^\s*-\s*(/\S+)\s*$", text, re.M)
            first_dir = dir_m.group(1) if dir_m else ""
            check("A3-project-yaml-key-and-live-dir",
                  key_ok and shape_ok and os.path.realpath(first_dir).startswith(os.path.realpath(tmp_home))
                  and os.path.isdir(first_dir),
                  "seeded project must be the bench key in the schema-v1 project-list "
                  "shape and dirs[0] must EXIST inside the temp home (session creation "
                  "cannot ENOENT, any machine; flat top-level shape = parser quarantine)",
                  "key_ok=%s shape_ok=%s dir=%s exists=%s" % (
                      key_ok, shape_ok, first_dir, os.path.isdir(first_dir)))
            check("D1-key-passes-whitelist",
                  bool(re.match(engine_shared.PROJECT_KEY_RE.pattern, BENCH_KEY)),
                  "bench key must pass PROJECT_KEY_RE (path-traversal contract intact)",
                  engine_shared.PROJECT_KEY_RE.pattern)

            # ---- E: production load path on the bench root -> only the bench project ----
            old = os.environ.get("SANDBAR_PROJECTS_DIR")
            try:
                os.environ["SANDBAR_PROJECTS_DIR"] = root
                projects, quarantined = engine_shared.load_projects_registry()
                reg = {p["key"]: list(p["dirs"]) for p in projects}
                check("E1-load-sees-only-bench-project",
                      list(reg.keys()) == [BENCH_KEY] and len(reg[BENCH_KEY]) == 1
                      and os.path.isdir(reg[BENCH_KEY][0]) and not quarantined,
                      "production load on the bench root sees exactly the bench project "
                      "with an existing workspace dir — capture-bench is the first "
                      "project seedSessions picks, no ENOENT possible",
                      json.dumps({"registry": reg, "quarantined": quarantined}))
            except Exception as e:
                check("E1-load-sees-only-bench-project", False,
                      "production load face broken",
                      "%s: %s" % (type(e).__name__, str(e)[:200]))
            finally:
                if old is None:
                    os.environ.pop("SANDBAR_PROJECTS_DIR", None)
                else:
                    os.environ["SANDBAR_PROJECTS_DIR"] = old

            # ---- B: malformed input — junk already at the target path ----
            tmp_home2 = os.path.join(tmp, "home2")
            os.makedirs(tmp_home2)
            root2 = os.path.join(tmp_home2, "bench-registry", "projects")
            os.makedirs(os.path.join(root2, BENCH_KEY))
            junk = os.path.join(root2, BENCH_KEY, "project.yaml")
            with open(junk, "w", encoding="utf-8") as fh:
                fh.write("# pre-existing junk that must never be silently overwritten\n")
            ok2, payload2 = run_bench_build(tmp_home2)
            with open(junk, "r", encoding="utf-8") as fh:
                junk_survived = "pre-existing junk" in fh.read()
            check("B1-junk-file-fails-loud-no-overwrite",
                  (not ok2) and junk_survived,
                  "a foreign file at project.yaml must fail loud and named, never a silent overwrite",
                  "ok=%s junk_intact=%s err=%s" % (ok2, junk_survived,
                                                   (payload2.get("error") or "")[:120]))

        # ---- C: the loader skip face, with and without the marker ----
        # C1: with .migrated, ensure_registry_migrated is a no-op and NO suyou entry
        # appears; C2: same root minus the marker replays the seed and the dead
        # project IS seeded back (the mechanism, red before the fix).
        c_root = os.path.join(tmp, "loader-root")
        os.makedirs(c_root)
        with open(os.path.join(c_root, ".migrated"), "w", encoding="utf-8") as fh:
            fh.write("source: scenario\n")
        old = os.environ.get("SANDBAR_PROJECTS_DIR")
        try:
            os.environ["SANDBAR_PROJECTS_DIR"] = c_root
            engine_shared.ensure_registry_migrated(pathlib.Path(c_root))
            check("C1-marker-skips-seed-no-suyou",
                  not os.path.isdir(os.path.join(c_root, "suyou")),
                  "with the marker the engine loader must skip the seed entirely — "
                  "a fresh home stays free of the retired project",
                  sorted(os.listdir(c_root)))
        finally:
            if old is None:
                os.environ.pop("SANDBAR_PROJECTS_DIR", None)
            else:
                os.environ["SANDBAR_PROJECTS_DIR"] = old

        c2_root = os.path.join(tmp, "loader-root-nomarker")
        os.makedirs(c2_root)
        if not os.path.isfile(os.path.join(REPO, "server", "projects.yaml")):
            check("C2-nomarker-replays-dead-seed", False,
                  "seed file missing — cannot prove the mechanism", os.path.join(REPO, "server", "projects.yaml"))
        else:
            old = os.environ.get("SANDBAR_PROJECTS_DIR")
            try:
                os.environ["SANDBAR_PROJECTS_DIR"] = c2_root
                engine_shared.ensure_registry_migrated(pathlib.Path(c2_root))
                seeded = os.path.join(c2_root, "suyou", "project.yaml")
                # 死目录字面值不硬编码（L17）：从仓内真种子解析 suyou 的 dirs，
                # 断言「种回的条目带着种子声明的、且本机不存在的目录」。
                seed_projects = engine_shared.parse_legacy_registry_file(
                    open(os.path.join(REPO, "server", "projects.yaml"),
                         "r", encoding="utf-8").read(),
                    os.path.join(REPO, "server", "projects.yaml"))
                seed_dirs = [d for p in seed_projects if p["key"] == "suyou" for d in p["dirs"]]
                seeded_dirs = []
                if os.path.isfile(seeded):
                    with open(seeded, "r", encoding="utf-8") as fh:
                        text = fh.read()
                    seeded_dirs = re.findall(r"^\s*-\s*(/\S+)\s*$", text, re.M)
                dead_dir_seeded = bool(seed_dirs) and seeded_dirs == seed_dirs \
                    and not any(os.path.exists(d) for d in seed_dirs)
                check("C2-nomarker-replays-dead-seed", dead_dir_seeded,
                      "negative control: without the marker the seed replays and the "
                      "retired project comes back with its dead dir (the defect mechanism)",
                      "seed_dirs=%s exists=%s" % (
                          seed_dirs, [os.path.exists(d) for d in seed_dirs]))
            finally:
                if old is None:
                    os.environ.pop("SANDBAR_PROJECTS_DIR", None)
                else:
                    os.environ["SANDBAR_PROJECTS_DIR"] = old
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    if _FAILS:
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
