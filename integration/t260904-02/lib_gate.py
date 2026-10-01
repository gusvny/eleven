# -*- coding: utf-8 -*-
"""t260904-02 集成场景共享夹具（无 sc_ 前缀=共享代码，不登记场景清单）。

只服务本票三场景：行式断言收集器、隔离台共享库（integration/bench.py）契约装载、
引擎 client 子进程调用、审计钩子日志读取、安装器入口定位与临时 HOME。

铁律（沿 t260903-10 lib_installer 纪律）：
- 绝不向真环境（3099/7233/8233 现有占用者）发任何信号；场景对生产端口只允许
  「审计钩子自证子用例」里被钩子拦截的连接尝试（先记后抛，内核建连前被阻断）；
- 一切状态写临时目录/槽位目录；spawn 的进程收尾 TERM→KILL 兜底；
- 依赖未就位=exit 2 MISSING（环境缺失，可辨于被测红）；端口被外来者占=exit 3。

bench 契约面（integration/bench.py 须提供；t260904-19 随槽位制退役收敛，本文件为对齐真源）：
  PROD_PORTS                        # 生产端口集合（7233/8233）
  class ProductionGuardError(Exception)
  assert_not_production(host)       # host 指生产（端口/字面址）→ raise ProductionGuardError
  poc_python() -> str               # 引擎 venv 解释器（含主树 gitfile 回退）
  audit_hook_env(dir) -> (env片段, log_path)  # sitecustomize 审计钩子：被测子进程
                                    # 对 PROD_PORTS 的 socket.connect 先记 jsonl 后抛
  write_registry(dir, key, project_dir) -> registry_dir  # fixture 注册表（含 key→dirs）

temporal 引擎台（原槽位制）由 integration/stage_docker.py 供给：本文件提供
require_stage(fail, project, namespace) 帮手——up temporal-only 台，docker 缺席/
镜像缺席/起台不健康=exit 2 环境红（三态语义），StageError 直译。
批模式（t260921-06）：SANDBAR_STAGE_BATCH 在场时 require_stage 改为向批台申请
命名空间（ns-acquire，零容器开销）、stage_down 改为释放命名空间（ns-drop，
绝不 down 批台）；env 缺席时两者逐字保留逐场景台行为。
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
POC = os.path.join(REPO, "server", "engine")
NODE_TS = os.path.join(REPO, "server", "plugins", "temporal-tools", "node.ts")

MISSING_EXIT = 2       # 依赖/设施未就位（环境缺失，非被测红）
ENV_CONFLICT_EXIT = 3  # 所选端口被外来者占（不对抗）

# bench 契约面最小成员清单（缺一即视为未交付/契约漂移；t260904-19 收敛后）
BENCH_CONTRACT = ("PROD_PORTS", "ProductionGuardError", "assert_not_production",
                  "audit_hook_env", "write_registry", "poc_python")


class Fail:
    """行式断言收集器：失败输出自明（执行器只取末 6 行 tail）。"""

    def __init__(self, title):
        self.title = title
        self.fails = []

    def check(self, cond, msg):
        print(("ok    " if cond else "FAIL  ") + msg, flush=True)
        if not cond:
            self.fails.append(msg)
        return bool(cond)

    def bail(self, msg, code=1):
        print("FAIL  %s" % msg, flush=True)
        sys.exit(code)

    def finish(self):
        if self.fails:
            print("FAIL  %s：%d 项断言未过（首因：%s）" % (self.title, len(self.fails), self.fails[0]), flush=True)
            sys.exit(1)
        print("PASS  %s" % self.title, flush=True)
        sys.exit(0)


def find_sandbar_entry():
    """安装器入口定位：仓根 sandbar（bin/ 为禁用落点，.gitignore 吞交付物）。"""
    for rel in ("sandbar", os.path.join("scripts", "sandbar")):
        p = os.path.join(REPO, rel)
        if os.path.isfile(p) and os.access(p, os.X_OK):
            return p
    return None


def require_sandbar_entry(fail):
    p = find_sandbar_entry()
    if p is None:
        fail.bail("安装器入口不存在（候选 ./sandbar 或 ./scripts/sandbar 均缺或不可执行）——implement 未交付",
                  MISSING_EXIT)
    return p


def run_cli(entry, args, env, timeout=120):
    """跑安装器 CLI（cwd=仓库根）。返回 (rc, out)。"""
    p = subprocess.run([entry] + list(args), env=env, cwd=REPO,
                       capture_output=True, text=True, timeout=timeout)
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def make_temp_home():
    """临时 HOME + env（安装状态 ~/.sandbar 随 HOME 桩隔离）。"""
    tmp = tempfile.mkdtemp(prefix="sandbar-it-t26090402-")
    env = dict(os.environ)
    env["HOME"] = tmp
    env.pop("XDG_CONFIG_HOME", None)
    return tmp, env


def load_bench():
    """装载隔离台共享库并核对契约面。返回 (bench|None, 未就位原因)。"""
    integ = os.path.join(REPO, "integration")
    if integ not in sys.path:
        sys.path.insert(0, integ)
    try:
        import bench  # noqa: E402
    except ImportError as e:
        return None, "integration/bench.py 不可 import：%s" % e
    miss = [n for n in BENCH_CONTRACT if not hasattr(bench, n)]
    if miss:
        return None, "bench 契约面缺失成员：%s" % miss
    return bench, ""


def require_bench(fail):
    """隔离台库未就位=exit2 MISSING（环境缺失可辨，非被测行为红）。"""
    b, why = load_bench()
    if b is None:
        fail.bail("隔离台共享库未就位（MISSING，非被测红）：%s —— implement 段 D 块交付后本场景真跑"
                  % why, MISSING_EXIT)
    return b


# 批台登记（t260921-06）：require_stage 批模式下 project→(批台工程名, namespace)。
# stage_down 据此判「释放 ns（绝不 down 批台）」还是「拆自有台」。键=调用方传入的
# project 名（调用方 stage_down 传的正是此名；批模式下返回态的 project=批台名，
# 两者分叉——所以返回态另带 request_project 备查）。
_BATCH_REG = {}

#: 批台工程名前缀（单点，与 run_scenarios._batch_project_name() 同源）：形状即批台 ⇒
#: stage_down 绝不 do_down（261001 KI-169：误拆批台=整池环境红）。
BATCH_PROJECT_PREFIX = "batch-"


def require_stage(fail, project, namespace):
    """起 temporal-only docker 舞台（stage_docker 单点入口）。

    批模式（t260921-06 批级共享）：SANDBAR_STAGE_BATCH 在场 ⇒ 不起台——向批台
    ns-acquire 申请本场景命名空间（零容器开销，秒级），返回态形状与起台同族
    （project=批台名、namespace=本场景 ns、ports/sa_registered 齐全），另带
    request_project=本调用原始 project 名。ns 名/批台名非法=usage（场景代码 bug，
    按 1 红）；批台不在位/注册失败=exit 2 环境红（要求⑤：绝不静默回落「没跑」）。
    env 缺席 ⇒ 逐场景台行为逐字保留。

    退出码直译：env（docker 缺席/镜像缺席/不健康/端口段耗尽/批台不在位/ns 注册
    失败）→ exit 2 环境红；conflict → exit 3；usage → 场景代码 bug 按 1 红处理
    （不该发生，发生了就是场景错）。
    sa_registered=False（temporal CLI 不可得，KI-020③ 同源）→ exit 2 点名——
    本族场景的 ticket-start 带 project 需要 ProjectKey SA，没注册=后续子用例全跑不真。"""
    sys.path.insert(0, os.path.join(REPO, "integration"))
    import stage_docker  # noqa: E402
    batch_project = os.environ.get("SANDBAR_STAGE_BATCH")
    if batch_project:
        try:
            state = stage_docker.ns_acquire(batch_project, namespace)
        except stage_docker.StageError as e:
            fail.bail("批台命名空间申请失败（%s）：%s" % (e.kind, e),
                      stage_docker.EXIT_ENV if e.kind == "env"
                      else stage_docker.EXIT_CONFLICT if e.kind == "conflict" else 1)
        state["request_project"] = project
        _BATCH_REG[project] = (batch_project, namespace)
        return stage_docker, state
    try:
        state = stage_docker.do_up_public(project, ["temporal"],
                                          {"namespace": namespace},
                                          stage_docker.DEFAULT_TIMEOUT)
    except stage_docker.StageError as e:
        fail.bail("docker 舞台 up 失败（%s）：%s" % (e.kind, e),
                  stage_docker.EXIT_ENV if e.kind == "env"
                  else stage_docker.EXIT_CONFLICT if e.kind == "conflict" else 1)
    if not state.get("sa_registered"):
        try:
            stage_docker.do_down(project)
        except Exception:
            pass
        fail.bail("docker 舞台 namespace/SA 未注册（temporal CLI 不可得？%s）——"
                  "ticket 场景需要 ProjectKey SA，环境缺供 exit 2" % state.get("sa_note"),
                  MISSING_EXIT)
    return stage_docker, state


def stage_down(stage_mod, project):
    """拆台/释放（幂等）。批模式（t260921-06）：require_stage 登记过的 project ⇒
    ns-drop 释放命名空间并**绝不 down 批台**（批台生命周期归 runner）；未登记
    （旧模式/直跑）⇒ do_down 拆自有台，逐字旧行为。project 可传 require_stage
    的原始 project 名，或其返回态 dict（取 request_project）。返回结果 JSON
    （down 形态含 residue 面供场景断言零残留；ns-drop 形态含 dropped 面）。"""
    if isinstance(project, dict):
        project = project.get("request_project") or project.get("project")
    batch = _BATCH_REG.pop(project, None)
    if batch is None:
        # 宽容面（261001 实案，KI-169）：调用方直接回传 require_stage **返回态的 project**
        # ——批模式下那个值是**批台工程名**，旧实现据此查不到登记 ⇒ 落到 do_down(批台名)
        # ⇒ **把 runner 的批台拆了** ⇒ 同一轮里后续每条批模式消费者全部 env_fail
        # 「批台不在位（runner 未预起/已收口/中途亡）」。巡检全量轮实测：429 条里 25 条
        # 同一具名原因，engine+exclusive 整整一面看不见（KI-169）。
        # 判据补两条：①按**值**在登记表里找（不只看键）；②形状即批台（batch- 前缀）时
        # **绝不 do_down**——拿不到命名空间就只报不拆。方向=宁可多认，不可漏认。
        for k, v in list(_BATCH_REG.items()):
            if v[0] == project:
                batch = _BATCH_REG.pop(k, None)
                break
    if batch is not None:
        return stage_mod.ns_drop(batch[0], batch[1])
    if str(project or "").startswith(BATCH_PROJECT_PREFIX):
        sys.stderr.write("[lib_gate] stage_down 收到批台工程名 %r——不拆（批台生命周期归 runner；"
                         "本次调用未持有其命名空间，只报不拆）\n" % project)
        return {"skipped": True, "project": project, "residue": [],
                "note": "批台工程名不拆（生命周期归 runner；见 KI-169）"}
    return stage_mod.do_down(project)


def poc_python(bench):
    """引擎 venv 解释器路径（bench 契约成员；缺失由 require_bench 兜住）。"""
    return bench.poc_python()


def run_poc_client(py, sub, args, env, timeout=180):
    """spawn <py> client.py <sub> <argsJSON>（node.ts cli 同款口径）。返回 (rc, out)。"""
    p = subprocess.run([py, os.path.join(POC, "client.py"), sub, json.dumps(args)],
                       env=env, cwd=REPO, capture_output=True, text=True, timeout=timeout)
    return p.returncode, ((p.stdout or "") + (p.stderr or ""))


def parse_out_json(out):
    """从输出中取第一行 JSON 对象（client.py 单行回执口径）；取不到返回 {}。"""
    for ln in (out or "").splitlines():
        ln = ln.strip()
        if ln.startswith("{"):
            try:
                return json.loads(ln)
            except Exception:
                continue
    return {}


def first_json_object(text):
    """输出里第一个可解析的 JSON 对象（**跨行**也认）；取不到返回 {}。

    为什么要跨行：多数 client.py 回执是单行，但有的 op（带 describe 明细的）会**缩进
    多行**打印——此时 `parse_out_json` 逐行解析会整条落空，场景若据此判「受理」就会
    假红/假绿。这里用 `raw_decode` 从每个 `{` 处试解析，单行与多行两种口径一视同仁。
    """
    s = text or ""
    dec = json.JSONDecoder()
    for i, ch in enumerate(s):
        if ch != "{":
            continue
        try:
            obj, _ = dec.raw_decode(s[i:])
        except Exception:                              # noqa: BLE001 —— 该处不是合法 JSON 起点
            continue
        if isinstance(obj, dict):
            return obj
    return {}


def accepted(out, tid=""):
    """裸入口**写 op** 的受理判据（KI-142）：受理 ⇔ 回执 `ok is True`。

    为什么不能只判 `rc == 0 and tid in out`：**拒收回执同样 rc=0，而且会把票号回显在
    错误文案里**（实测原文 `{"ok": false, "error": "跨项目闸：调用方项目身份未声明…",
    "kind": "cross_project_refused", …（目标票 tXXXX，属项目 Y）"}`）。于是「被拒收」
    会被读成「受理成功」，场景继续往下跑，最终以「票没推进」的假象报红——260927
    KI-142 实案（sc_detail_lane_reds 干等 240s、worker 整段 workflow not found，
    在会被跳过的池里烂了很久没人知道）。

    返回 `(bool, why)`；`why` 逐项点名失败原因（消费外部输入纪律：报错要说清哪个检查
    失败），可直接进断言文案。
    """
    r = parse_out_json(out) or first_json_object(out)   # 单行优先，多行回执回落跨行解析
    if not r:
        return False, "回执不可解析（非 JSON/空输出）"
    if r.get("ok") is not True:
        kind = str(r.get("kind") or "")
        err = str(r.get("error") or "")[:200]
        return False, "ok≠true%s%s" % ((" kind=%s" % kind) if kind else "",
                                      ("：%s" % err) if err else "")
    got = str(r.get("ticket_id") or r.get("workflow_id") or "")
    if tid and got and tid not in got:
        return False, "回执票号不符（期望 %s，实得 %r）" % (tid, got)
    if tid and not got and tid not in (out or ""):
        # 有的 op 回执不带票号键（只回 ok/明细）——此时以**原文回显**为准（旧口径那半），
        # 绝不放行「既无票号键、原文也没有票号」的含糊回执。
        return False, "回执既无票号键、原文也未回显票号 %s" % tid
    return True, "ok=true%s" % (("，ticket_id=%s" % tid) if tid else "")


def check_accepted(fail, out, tid="", label="受理"):
    """`accepted` 的断言封装：`fail.check(受理, label（why）)`。返回判据布尔。"""
    good, why = accepted(out, tid)
    fail.check(good, "%s（%s）" % (label, why))
    return good


def read_audit_jsonl(path):
    """读审计钩子 jsonl（不存在=空列表）。"""
    if not os.path.isfile(path):
        return []
    rows = []
    with open(path, encoding="utf-8") as f:
        for ln in f:
            ln = ln.strip()
            if ln:
                try:
                    rows.append(json.loads(ln))
                except Exception:
                    rows.append({"_raw": ln})
    return rows


def port_listening(port, host="127.0.0.1"):
    """槽端口探活（connect_ex；只用于槽端口，绝用于生产端口）。"""
    import socket
    s = socket.socket()
    s.settimeout(1.0)
    try:
        return s.connect_ex((host, port)) == 0
    finally:
        s.close()


def wait_port_released(port, timeout_s=10.0, interval=0.25, host="127.0.0.1"):
    """等待槽端口释放（有界宽限窗）。

    为什么需要：stop() 发 SIGTERM 后，服务进程退出与内核回收 listener 存在秒级
    延迟窗——拆解后**立即**断言「端口已释放」会偶发假红（20260904 t260904-08
    arbitrate 实测：同场景内槽A 输槽B 赢的时序竞态）。本 helper 让契约更准而非
    更松：释放仍是硬性断言，只是给了有界窗；超时仍占用则尽力点名占用者 pid
    （报错必须精确——不说「没释放」就完事，要说谁还占着）。"""
    import time
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        if not port_listening(port, host):
            return True, None
        time.sleep(interval)
    if not port_listening(port, host):
        return True, None
    held_pid = None
    try:
        import subprocess
        out = subprocess.run(["lsof", "-ti", "tcp:%d" % port],
                             capture_output=True, text=True, timeout=10).stdout.split()
        held_pid = int(out[0]) if out else None
    except Exception:
        held_pid = None
    return False, held_pid


def read_rows_compat(path):
    """宽容读兼容矩阵行集合（沿 t260903-10 口径）：顶层 list 即行；顶层 dict 取
    rows/list 类字段。返回 (ok, rows)。"""
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return False, []
    if isinstance(data, list):
        return True, data
    if isinstance(data, dict):
        for key in ("rows", "matrix", "entries", "data"):
            if isinstance(data.get(key), list):
                return True, data[key]
        for v in data.values():
            if isinstance(v, list) and v and isinstance(v[0], dict):
                return True, v
    return True, []


def cleanup(tmpdir, *procs):
    """夹具收尾：进程 TERM→KILL 兜底 + 临时目录必清。"""
    for pr in procs:
        if pr is None:
            continue
        try:
            pr.terminate()
            pr.wait(timeout=10)
        except Exception:
            try:
                pr.kill()
            except Exception:
                pass
    shutil.rmtree(tmpdir, ignore_errors=True)
