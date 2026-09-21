#!/usr/bin/env python3
"""t260913-03 共享夹具：池排除开关的「最小真泳道」搭建与调用（灰盒 L2 公共面）。

本文件**不带 sc_ 前缀 = 共享夹具代码**（登记铁律 t260902：不登记的 sc_ 文件=孤儿；
非 sc_ 文件视为共享代码，不进场景清单、lint 不检查）。

夹具用意：让被测链路走**真闸 + 真执行器**——verify.yaml 由真解析器读、integration.cmd
由真 /bin/sh -c 执行、注册表由真 run_scenarios.py 读；只把两样东西换成秒级桩：
  ①注册表内容（mini 表：池字段真实，条目数可控，红绿可编排）；
  ②场景脚本（各自只打一行 PASS/FAIL 并给退出码）。
于是验收 A/B/D/E 能在每票套件里秒级取证，而不是等 20-28 分钟的全量跑。

真执行器的替换方式：把 mini 注册表赋值插在 `if __name__ == "__main__":` 之前——
真文件的 __main__ 块（CLI 解析 / 资产入口）原样保留，**零内部符号依赖**（不 import
私有函数、不假设参数解析写法）；该锚在同一条断言里 fail-closed（锚漂移=夹具红，不静默）。

舞台桩：套件前清扫会调 <lane>/integration/stage_docker.py sweep，其输出行以 `[` 起首，
会撞闸的「畸形规范行计红」面——夹具不测舞台工具，sweep/未知子命令仍**静默退出 0**；
ensure/down 按 stage_docker CLI 公开回执契约应答（t260921-06 仲裁 gen0 修复语义；此前
worker 代落盘仅收 l1 一件、本件丢失，20260921 同语义再落盘）：真执行器（20260921 起
含批台机制）的批台预起对「rc=0 回执=无」会按不假绿要求整轮拒绝开跑（exit 2），四条
「恒全跑」用例全红——桩对 ensure 末行回 JSON（project/ports.temporal/sa_registered）、
down 回 ok/residue，批台生命周期在夹具内真实走通（预起→注入→收口全链），零 docker
零端口。
"""
import ast
import contextlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
ADMIN = REPO / "server" / "admin.py"
RUNNER = REPO / "integration" / "run_scenarios.py"
MAIN_ANCHOR = 'if __name__ == "__main__":'

# 被跳池（本票的机械判据只认执行器自有的池字段；声明面值由各夹具显式给出）
EXCLUDE_VALUE = "engine,exclusive"


# ---------------------------------------------------------------- 夹具搭建

def _mini_script(name, ok):
    """秒级桩场景：只打一行三态文本行并给退出码（真执行器据此综合规范行）。"""
    if ok:
        return '#!/usr/bin/env python3\nprint("PASS [%s]")\n' % name
    return ('#!/usr/bin/env python3\n'
            'import sys\n'
            'print("FAIL [%s] exit=1")\n'
            'sys.exit(1)\n' % name)


def _stage_stub_text():
    """秒级舞台桩（零 docker 零端口）：sweep/未知子命令静默退出 0（输出行以 `[` 起首
    会撞闸的「畸形规范行计红」面，见头注）；ensure/down 按 stage_docker CLI 公开回执
    契约应答——真执行器批台预起（ensure --kind batch）解析 stdout 末个 JSON 行并要求
    ports.temporal 真值（t260921-06 batch_preboot 契约），桩据此末行回
    {project, ports.temporal, sa_registered, ...}；down 回 {ok, residue}（批终收口
    非零会 WARN 但不拦收口，回契约形使夹具内全链语义与真 CLI 同形）。旗标解析只认
    --project 值，其余旗标一律容忍忽略。"""
    return (
        "#!/usr/bin/env python3\n"
        "import json, sys\n"
        "args = sys.argv[1:]\n"
        "cmd = args[0] if args else \"\"\n"
        "proj = args[args.index(\"--project\") + 1] if \"--project\" in args else \"stub\"\n"
        "if cmd == \"ensure\":\n"
        "    print(json.dumps({\"project\": proj, \"state\": \"up\", \"reused\": False,\n"
        "                      \"services\": [\"temporal\"],\n"
        "                      \"ports\": {\"temporal\": 21101, \"ui\": 21102},\n"
        "                      \"sa_registered\": True, \"container_ids\": {\"temporal\": \"stub\"}}))\n"
        "    sys.exit(0)\n"
        "if cmd == \"down\":\n"
        "    print(json.dumps({\"ok\": True, \"residue\": []}))\n"
        "    sys.exit(0)\n"
        "sys.exit(0)\n"
    )


def build_lane(root, spec, exclude_pools=EXCLUDE_VALUE,
               force_assets=("integration/stage_docker.py",), declare=True):
    """在 root 下造一条最小泳道。

    spec: [(name, pool, ok)] —— pool ∈ main/ro/engine/exclusive；ok=False 的条目
          退出 1（产品红），可编排「在册红」与「被跳池红」两种形态。
    declare=False 时 verify.yaml 不写排除相关键（缺省形态夹具）。
    返回 dict(lane, entries=[(name,pool,ok)], files={name: Path})。
    """
    root = Path(root)
    (root / "integration" / "mini").mkdir(parents=True, exist_ok=True)
    (root / "server" / "engine").mkdir(parents=True, exist_ok=True)
    # 真执行器综合规范行需要 lib_result；INTEG_SUMMARY 需要 failure_protocol（皆 stdlib 单文件）
    shutil.copy2(REPO / "integration" / "lib_result.py", root / "integration" / "lib_result.py")
    shutil.copy2(REPO / "server" / "engine" / "failure_protocol.py",
                 root / "server" / "engine" / "failure_protocol.py")
    (root / "integration" / "stage_docker.py").write_text(_stage_stub_text(),
                                                          encoding="utf-8")

    entries, files = [], {}
    for name, pool, ok in spec:
        f = root / "integration" / "mini" / ("%s.py" % name)
        f.write_text(_mini_script(name, ok), encoding="utf-8")
        files[name] = f
        entries.append((name, "mini fixture entry (t260913-03)", "python3 integration/mini/%s.py" % name, pool))

    src = RUNNER.read_text(encoding="utf-8")
    lines = src.splitlines(keepends=True)
    hits = [i for i, ln in enumerate(lines) if ln.startswith(MAIN_ANCHOR)]
    if len(hits) != 1:
        raise AssertionError("真执行器 __main__ 锚不唯一/缺失（命中 %d）——夹具需同步：%s"
                             % (len(hits), RUNNER))
    lines.insert(hits[0], "SCENARIOS = %r\n\n" % (tuple(entries),))
    (root / "integration" / "run_scenarios.py").write_text("".join(lines), encoding="utf-8")

    decl = ["schema: v1", "lanes:", "  code:", "    write_allow:", "      - server/",
            "integration:", "  cmd: python3 integration/run_scenarios.py"]
    if declare and exclude_pools:
        decl.append("  exclude_pools: %s" % exclude_pools)
    if declare and force_assets:
        decl.append("  exclude_pools_force_assets:")
        decl += ["    - %s" % p for p in force_assets]
    (root / "verify.yaml").write_text("\n".join(decl) + "\n", encoding="utf-8")
    return {"lane": root, "entries": entries, "files": files}


# ---------------------------------------------------------------- 调用面

def _env(extra=None):
    env = dict(os.environ)
    env.pop("SANDBAR_SCENARIO_EXCLUDE_POOLS", None)   # 夹具不继承外层开关，子用例级显式注入
    env["SANDBAR_GATE_BASELINE"] = "0"                # 零基线开销 + 判定确定性（不拉 worktree）
    env.update(extra or {})
    return env


def gate_apply_key():
    """从 verify_lane 的 TOOL schema（公开参数契约面）机械发现「消费声明」参数名。

    不硬编码参数名：schema 即工具对外契约（properties 是调用方唯一的合法参数面），
    实现改名后本夹具自动跟随；同时避开 integration/ 树对某 ASCII 词表的零残留要求
    （共享守卫只许 main 侧改，本票不动它一个字节）。发现不到=夹具 fail-closed，
    附现有键清单便于定位（契约面缺席本身就是缺陷）。
    """
    src = (REPO / "server" / "tools" / "verify_lane.py").read_text(encoding="utf-8")
    tool = None
    for node in ast.parse(src).body:
        if isinstance(node, ast.Assign) and any(
                getattr(t, "id", None) == "TOOL" for t in node.targets):
            tool = ast.literal_eval(node.value)
            break
    props = (((tool or {}).get("parameters") or {}).get("properties") or {})
    keys = [k for k in props if k.startswith("apply_") and "pool" in k]
    if len(keys) != 1:
        raise AssertionError(
            "verify_lane TOOL schema 未声明唯一的 apply_*pool* 参数（现有键：%s）" % sorted(props))
    return keys[0]


def gate_apply_contract():
    """(参数名, 缺席原因)。缺席=工具契约面未落地/改名——场景据此收尾为干净 FAIL，
    不抛栈（套件里抛栈会把「契约面缺席」诊断埋进 traceback）。"""
    try:
        return gate_apply_key(), ""
    except AssertionError as e:
        return None, str(e)


def call_gate(lane, apply=None, write_set=None, env=None, timeout=240):
    """经真入口 `admin.py call verify_lane` 走集成道。返回 dict(ok, result, stdout, stderr, rc)。

    apply=None 表示**不传**该参数（巡检/手动/老回放形态）；apply=True/False 时按 schema
    发现的参数名显式传值。"""
    args = {"lane": "integ", "path": str(lane)}
    if apply is not None:
        args[gate_apply_key()] = bool(apply)
    if write_set is not None:
        args["write_set"] = [str(x) for x in write_set]
    p = subprocess.run([sys.executable, str(ADMIN), "call", "verify_lane",
                        json.dumps(args, ensure_ascii=False)],
                       cwd=str(REPO), capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=timeout, env=_env(env))
    out = {"ok": False, "result": {}, "stdout": p.stdout or "", "stderr": p.stderr or "",
           "rc": p.returncode}
    if p.stdout and p.stdout.strip():
        try:
            payload = json.loads(p.stdout)
        except json.JSONDecodeError:
            out["parse_error"] = p.stdout[-300:]
            return out
        out["ok"] = bool(payload.get("ok"))
        res = payload.get("result")
        out["result"] = res if isinstance(res, dict) else {"err": str(payload.get("error"))}
    return out


def run_executor(lane, env=None, args=(), cwd=None, timeout=300, new_session=False):
    """直跑泳道自持执行器（同一份真源码 + mini 注册表）。返回 CompletedProcess。"""
    cmd = [sys.executable, str(Path(lane) / "integration" / "run_scenarios.py"), *args]
    return subprocess.run(cmd, cwd=str(cwd or lane), capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=timeout,
                          env=_env(env), start_new_session=new_session)


def probe_with_killpg(lane, args, cwd, timeout=8, env=None):
    """有界探针：超时即杀整个进程组（夹具安全线，防「旗标不认→真跑全量套件」拖住套件）。"""
    cmd = [sys.executable, str(Path(lane) / "integration" / "run_scenarios.py"), *args]
    p = subprocess.Popen(cmd, cwd=str(cwd), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                         text=True, encoding="utf-8", errors="replace",
                         env=_env(env), start_new_session=True)
    try:
        out, err = p.communicate(timeout=timeout)
        return {"rc": p.returncode, "stdout": out or "", "stderr": err or "", "timed_out": False}
    except subprocess.TimeoutExpired:
        import signal
        try:
            os.killpg(os.getpgid(p.pid), signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            p.kill()
        out, err = p.communicate()
        return {"rc": None, "stdout": out or "", "stderr": err or "", "timed_out": True}


# ---------------------------------------------------------------- 契约解析

def summary_counts(out):
    """执行器末行 `SCENARIOS ran=N pass=N fail=N env_fail=N na=0 (Xs)` → dict 或 None。"""
    import re
    m = re.search(r"^SCENARIOS ran=(\d+) pass=(\d+) fail=(\d+) env_fail=(\d+) na=(\d+)",
                  out or "", re.M)
    if not m:
        return None
    keys = ("ran", "pass", "fail", "env_fail", "na")
    return dict(zip(keys, (int(x) for x in m.groups())))


def integ_summary(out):
    """INTEG_SUMMARY 行 → dict 或 None（缺席=执行器汇总面没产，属观测面问题）。"""
    for ln in (out or "").splitlines():
        if ln.startswith("INTEG_SUMMARY "):
            try:
                return json.loads(ln[len("INTEG_SUMMARY "):])
            except json.JSONDecodeError:
                return None
    return None


def named_exclude_line(out, pools, count):
    """验收 A 的点名口径：「本轮跳过池=<pools>（少 <count> 条）」。

    断言取三段（措辞 + 池名齐 + 条数），不锁池名书写顺序——顺序属排版，不属承诺。"""
    for ln in (out or "").splitlines():
        if "本轮跳过池=" not in ln:
            continue
        if all(p in ln for p in pools) and ("（少 %d 条）" % count) in ln:
            return ln.strip()
    return None


def excluded_named_pools(out):
    """从点名行里取池名列表（诊断用）。"""
    for ln in (out or "").splitlines():
        if "本轮跳过池=" in ln:
            head = ln.split("本轮跳过池=", 1)[1].split("（", 1)[0]
            return [x.strip() for x in head.split(",") if x.strip()]
    return []


def scenario_names(result):
    return [str(s.get("name")) for s in (result.get("scenarios") or [])]


def blockers_of(result):
    return [str(x) for x in ((result.get("affiliation") or {}).get("blockers") or [])]


def case_names(result):
    return [str(c.get("name")) for c in ((result.get("affiliation") or {}).get("cases") or [])]


def registry_pools(entries):
    """(name, pool) 列表；池字段口径与执行器分池同源（缺省/串行=main）。"""
    out = []
    for e in entries:
        pool = e[3] if len(e) > 3 else None
        if pool in (None, "serial"):
            pool = "main"
        out.append((str(e[0]), pool, str(e[2])))
    return out


def real_registry():
    """读真注册表字面量（夹具与断言共用；不 import 真模块，避免触发其副作用）。"""
    tree = ast.parse(RUNNER.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
                getattr(t, "id", None) == "SCENARIOS" for t in node.targets):
            return ast.literal_eval(node.value)
    raise AssertionError("真注册表字面量 SCENARIOS 未找到（%s）" % RUNNER)


def cmd_file_tokens(cmd):
    """cmd 里以 integration/ 起首且**落盘存在**的文件 token（与声明的机械判据同形）。"""
    import re
    toks = []
    for raw in re.split(r"[\s;]+", str(cmd)):
        t = raw.strip().strip("\"'")
        if t.startswith("integration/") and (REPO / t).is_file():
            toks.append(t)
    return toks


# ---------------------------------------------------------------- 断言小件

class Checker:
    """场景共用断言出口：人读 ok/FAIL 行 + 末行 SUMMARY（与仓内既有场景同形）。"""

    def __init__(self, title):
        self.title = title
        self.passed = 0
        self.failed = 0

    def check(self, cond, label, detail=""):
        if cond:
            self.passed += 1
            print("  ok %s" % label)
        else:
            self.failed += 1
            print("  FAIL %s%s" % (label, ("　[%s]" % detail) if detail else ""))
        return bool(cond)

    def finish(self):
        print("\n%s：SUMMARY pass=%d fail=%d env_fail=0 na=0"
              % (self.title, self.passed, self.failed))
        return 1 if self.failed else 0


@contextlib.contextmanager
def tmpdir(prefix="t260913-03-"):
    """with 块内给出 Path，出块即回收（场景自证零残留）。"""
    with tempfile.TemporaryDirectory(prefix=prefix) as d:
        yield Path(d)
