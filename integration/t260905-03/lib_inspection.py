"""t260905-03 巡检票①场景共享夹具与驱动（无 sc_ 前缀=共享子检查代码，不登记场景清单）。

三态纪律（t260904-12，闸内不设第三态）：exit 0=PASS / 1=FAIL（产品红，缺什么点名什么）/
2=ENV_FAIL（环境缺供点名，不假绿不静默）。缺三方依赖=engine/.venv 可入则重入，
否则 ENV_FAIL——依赖缺席是环境红；模块/入口未交付是产品红，两不相冒充（KI-051 教训：
环境红不得捂产品真红）。

绑定面（全部为已交付/已声明的对外契约，场景侧不再发明）：
- 扫描器 CLI：`python3 server/engine/inspection_scan.py --repo-root <dir>`
  stdout 单行 JSON {ok, result:{face,findings,summary,heartbeat,meta}|error}；
  finding 六键 {id,scan,severity,subject,evidence,suggestion}，severity∈{high,med,low}。
- 触发面 CLI（已交付，运维通道）：`inspection_trigger.py trigger --instance <id>
  [--period P] [--repo-root R] [--decl-path F]` / `sign --instance <id> --who <人>
  [--decision approve|reject]` / `describe` / `decl` / `schedule-up --note …`，
  stdout 单行 JSON {ok, result|error}；校验先于网络（拒绝腿可离线）。
- 声明覆盖 env：SANDBAR_INSPECTION_DECL / SANDBAR_INSPECTION_DIR（implement 段已按
  宿主令 5「suyou 之名退役」以 sandbar 前缀命名新变量；场景不经 env 注入，用
  --decl-path/--repo-root 显式传参，此处仅登记绑定名备查）。
- 人门：client.py ticket op=sign，gate=inspection-close（InspectionPeriodicWorkflow
  的门 id），who 由调用方注入且不用 agent 角色名。

夹具=仓形树（repo-shaped）：integration/run_scenarios.py + integration/sc_* 守卫 +
server/** 生产方——与扫描器的真实收集口径同构（PRODUCER_ROOTS/GUARD_EXTS），
不靠 mock 缝合。
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TP_DIR = os.path.join(REPO, "server", "engine")
VENV_PY = os.path.join(TP_DIR, ".venv", "bin", "python")
SCANNER = os.path.join(TP_DIR, "inspection_scan.py")
TRIGGER = os.path.join(TP_DIR, "inspection_trigger.py")
CLIENT = os.path.join(TP_DIR, "client.py")
WORKER = os.path.join(TP_DIR, "worker.py")

# KI-051 原案字面锚（notes/debts/known-issues.md L65：capture-chat 守卫断言的旧措辞）。
# 片段=「隔离台」「新建会话」：med 形态=生产方留前缀换措辞（真实 capture.mjs 案）；
# high 形态=纯重写（核心片段全缺）。
KI051_OLD_ANCHOR = "隔离台『+ 新建会话』"

FINDING_KEYS = {"id", "scan", "severity", "subject", "evidence", "suggestion"}


def die_fail(msg: str) -> None:
    print("FAIL_REASON: " + msg, flush=True)
    sys.exit(1)


def die_env(msg: str) -> None:
    print("ENV_FAIL: " + msg, flush=True)
    sys.exit(2)


def require_entry(path: str, what: str) -> None:
    """产品入口未交付=产品红（红属预期：实现段落地前），点名退出。"""
    if not os.path.exists(path):
        die_fail("%s 未交付（%s 不存在）——红属预期（实现段落地前 TDD 信号）" % (what, path))


def py_runner() -> str:
    return VENV_PY if os.path.exists(VENV_PY) else sys.executable


def _missing_third_party(text: str) -> str:
    if "ModuleNotFoundError" not in text:
        return ""
    for mod in ("temporalio", "yaml"):
        if ("No module named '%s'" % mod) in text or ('No module named "%s"' % mod) in text:
            return mod
    return ""


def reexec_venv_if_missing(mods=("temporalio",)) -> None:
    missing = []
    for m in mods:
        try:
            __import__(m)
        except Exception:
            missing.append(m)
    if not missing:
        return
    if os.path.exists(VENV_PY) and os.path.realpath(VENV_PY) != os.path.realpath(sys.executable):
        os.execv(VENV_PY, [VENV_PY, __file__])
    die_env("python 三方依赖缺席：%s（server/engine/.venv 缺席或不可用）" % ",".join(missing))


# ── 测试腿隔离生产 Temporal（t260910-11 红线）──
# 事故形态（260910 实证）：本 lib 从不注入 SANDBAR_TARGET_HOST，trigger/worker/client
# 子进程全落 shared.py 默认 127.0.0.1:7233 生产台——全套件每跑一次即向生产写两张巡检
# 票，私有 worker 死亡后票永久 RUNNING，真实期次号被「一票一期」锁占住。
# 口径（review 钉死）：子进程 env 一律由 spawn_env 单点构造（TEST_TARGET_HOST 常量），
# 构造后自检「已设且 ==17233 且 namespace==测试台存量名（TEST_NAMESPACE）」；ambient 为空→注入隔离台；
# ambient 指生产 7233 或任何第三方值→die_fail 点名失败的检查项；ambient 的
# SANDBAR_* 不得静默穿透进子进程（构造时显式覆盖/剔除）。
TEST_TARGET_HOST = "127.0.0.1:17233"
TEST_NAMESPACE = "sandbar-test"  # 绑定存量 docker 测试台命名空间（docker-compose.test.yml 定义）。t260917-02 勘误：终切 d342b46 已把台命名空间改 sandbar-test，此处漏改残留 suyou-test——旧持久卷里恰好有死命名空间故今晨前未暴露，新卷台（无 suyou-test）一律 ENV_FAIL「Namespace suyou-test is not found」；对齐存量台定义（宿主令 260908 suyou 退役同向），如需回摆随专门迁移票
_ENV_OVERRIDES = ("SANDBAR_TARGET_HOST", "SANDBAR_NAMESPACE")  # 红线键：绝不穿透


def spawn_env(extra=None):
    """子进程 env 构造单点（白名单 fail-closed，见上注）。"""
    ambient = os.environ.get("SANDBAR_TARGET_HOST")
    if ambient:
        if ":7233" in ambient:
            die_fail("测试腿目标指向生产 Temporal（SANDBAR_TARGET_HOST=%s）——拒跑："
                     "巡检测试禁止写生产台 7233（260910 事故回归；请用 docker 隔离台 %s，"
                     "sh server/docker-compose.test.yml up -d）" % (ambient, TEST_TARGET_HOST))
        if ambient != TEST_TARGET_HOST:
            die_fail("SANDBAR_TARGET_HOST=%s 既非隔离台 %s 亦非生产值——第三方值语境不明，"
                     "fail-closed 拒跑（失败的检查项：目标白名单）" % (ambient, TEST_TARGET_HOST))
    # 队列不属红线面：ambient 的 SANDBAR_TASK_QUEUE 照认（场景以 ambient 传私有队列），
    # extra 显式覆盖；目标/namespace 两键绝不穿透（红线单点）
    env = {k: v for k, v in os.environ.items()
           if k not in ("SANDBAR_TARGET_HOST", "SANDBAR_NAMESPACE")}
    env["SANDBAR_TARGET_HOST"] = TEST_TARGET_HOST
    env["SANDBAR_NAMESPACE"] = TEST_NAMESPACE
    if extra:
        env.update(extra)
    # 构造后自检（不许 fail-open）：任一不满足即点名失败项
    if env.get("SANDBAR_TARGET_HOST") != TEST_TARGET_HOST:
        die_fail("spawn_env 自检失败：SANDBAR_TARGET_HOST=%r ≠ 隔离台 %r"
                 % (env.get("SANDBAR_TARGET_HOST"), TEST_TARGET_HOST))
    if ":7233" in env.get("SANDBAR_TARGET_HOST", ""):
        die_fail("spawn_env 自检失败：目标含生产台 7233")
    if env.get("SANDBAR_NAMESPACE") != TEST_NAMESPACE:
        die_fail("spawn_env 自检失败：SANDBAR_NAMESPACE=%r ≠ %r"
                 % (env.get("SANDBAR_NAMESPACE"), TEST_NAMESPACE))
    return env


# 本进程经 run_trigger 开出的巡检票登记（退出自清的账本；pid 戳见各场景实例名）
STARTED_TICKETS = []


def note_started_ticket(ticket_id: str) -> None:
    if ticket_id and ticket_id not in STARTED_TICKETS:
        STARTED_TICKETS.append(ticket_id)


def cleanup_tickets(per_call_timeout: float = 20.0) -> None:
    """退出自清：对本进程开过的巡检票逐个 cancel（幂等——已终态的票 cancel 报错即
    忽略）。每次调用自带超时（防退出路径挂死）；失败只 WARN 放行退出，不吞不炸
    （残留只可能落隔离台 17233，非生产风险）。已知边界（与 journey pid 戳做法一致的
    两条）：①pid 复用+同日残留票可能撞「一票一期」去重——pid 戳把概率压到可忽略，
    撞了也是隔离台内的去重回执，非生产污染；②进程被硬杀（SIGKILL）时本清理不执行，
    残留同样只落隔离台。"""
    for tid in list(STARTED_TICKETS):
        try:
            run_cmd([py_runner(), CLIENT, "cancel", json.dumps({"workflow_id": tid}, ensure_ascii=False)],
                    timeout=per_call_timeout)
        except Exception as e:  # noqa: BLE001——清理失败 WARN 后放行退出（不吞细节也不炸退出路径）
            print("WARN: 退出自清 cancel %s 失败（%s）——残留落在隔离台 %s"
                  % (tid, e, TEST_TARGET_HOST), flush=True)
        finally:
            STARTED_TICKETS.remove(tid)


def run_cmd(cmd, env=None, timeout=180):
    # env 一律过 spawn_env 单点（t260910-11 隔离红线；调用方 extra 显式覆盖）
    full_env = spawn_env(env)
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                          cwd=REPO, env=full_env)


def env_fail_if_missing_dep(proc) -> None:
    mod = _missing_third_party((proc.stdout or "") + (proc.stderr or ""))
    if mod:
        die_env("被测入口缺三方依赖 %s（装配腿环境红，本场景无法验到产品行为）" % mod)


def last_json(text: str):
    lines = [ln for ln in (text or "").strip().splitlines() if ln.strip()]
    if not lines:
        return None
    try:
        return json.loads(lines[-1])
    except Exception:
        return None


def run_scanner(repo_root: str):
    """跑扫描器（--repo-root 注入仓形夹具树），返回 (proc, parsed)。"""
    require_entry(SCANNER, "扫描器")
    proc = run_cmd([py_runner(), SCANNER, "--repo-root", repo_root])
    env_fail_if_missing_dep(proc)
    return proc, last_json(proc.stdout)


def run_trigger(action_args, env=None):
    """跑触发面 CLI（如 ["trigger", "--instance", "integration-tests"]），返回 (proc, parsed)。
    放行回执带票号时登记进 STARTED_TICKETS（退出自清账本）。"""
    require_entry(TRIGGER, "巡检触发入口")
    proc = run_cmd([py_runner(), TRIGGER] + list(action_args), env=env)
    env_fail_if_missing_dep(proc)
    parsed = last_json(proc.stdout)
    res = scanner_result(parsed)
    if res:
        note_started_ticket(str(res.get("ticket_id") or ""))
    return proc, parsed


def run_client(sub: str, args: dict, env=None):
    """跑 client.py 子命令（JSON 参数），返回 (proc, parsed)。缺 temporalio=ENV_FAIL。
    env=spawn_env 的 extra（显式覆盖/追加，如 SANDBAR_INSPECTION_DECL 夹具声明缝）。"""
    proc = run_cmd([py_runner(), CLIENT, sub, json.dumps(args, ensure_ascii=False)], env=env)
    env_fail_if_missing_dep(proc)
    return proc, last_json(proc.stdout)


def ensure_inspection_search_attributes(timeout=20):
    """t260916-02 迁移步：测试台幂等注册巡检去重两 SA（InspectionInstance/
    InspectionPeriod=Keyword）。已注册=tolerate（与 stage_docker.register_namespace
    同口径）；CLI 缺席/注册失败=返回 (False, note) 如实上报——不静默：调用方把 note
    记进场景日志，SA 真缺时 trigger 会以「SA 未注册」显式报错（R3 归因）二次点名。
    只对隔离台（TEST_TARGET_HOST/TEST_NAMESPACE）操作，绝不触生产。"""
    import subprocess as _sp
    cli = os.environ.get("SANDBAR_TEMPORAL_BIN") or ""
    if not cli:
        cand = os.path.join(TP_DIR, "bin", "temporal")
        cli = cand if os.path.exists(cand) else ""
    if not cli:
        return False, "temporal CLI 不可得（server/engine/bin/temporal 缺失，env SANDBAR_TEMPORAL_BIN 可指路）"
    notes = []
    for name in ("ProjectKey", "EpicCode", "InspectionInstance", "InspectionPeriod"):
        try:
            p = _sp.run([cli, "operator", "search-attribute", "create",
                         "--namespace", TEST_NAMESPACE, "--name", name,
                         "--type", "Keyword", "--address", TEST_TARGET_HOST],
                        capture_output=True, text=True, timeout=timeout)
        except (OSError, _sp.SubprocessError) as e:
            return False, "SA %s 注册失败：%s" % (name, e)
        low = ((p.stdout or "") + (p.stderr or "")).lower()
        if p.returncode != 0 and not any(t in low for t in
                                         ("already exist", "already defined", "already registered")):
            return False, "SA %s 注册失败（rc=%s）：%s" % (name, p.returncode, low.strip()[:160])
        notes.append(name)
    return True, "SA 就绪：%s" % ",".join(notes)


class StageWorker:
    """场景自供给 worker（仓内先例：ticket-lifecycle 起 worker 起票）。

    存在理由一（注册面）：本票 workflow 未合并进主仓前，测试台常驻 worker 的注册面
    来自已合并代码，不认识 InspectionPeriodicWorkflow——票开得出（start 不需要
    worker）但 query/sign 后的收口无人执行。理由二（队列赛跑，arbitrate 实证）：
    常驻生产 worker 与本 worker 若共队列，新 workflow/activity 类对生产 worker 未
    注册，谁先领活谁打回（历史事件 WF_TASK_FAIL/ACT_FAIL「not registered」铁证，
    同套件两腿一成一败=非确定竞态）——故必须**私有队列**：queue 由调用方给定，
    trigger 子进程与 worker 同队列（activities 跟随 workflow 启动队列），生产
    worker 永不沾手。同时剥离 supervisor 缠绕变量（SANDBAR_WORKER_META 指向主仓
    data 目录会跨仓写指纹；SANDBAR_WATCH_* 会让 worker 收口自退/被宿主生命周期绑走）。
    用法：

        with lib.StageWorker("suyou-insp-journey-12345") as w:
            ...  # 触发/轮询/签字（trigger 子进程须继承同一 SANDBAR_TASK_QUEUE）
        # __exit__ 必回收：TERM→等→KILL（资源生命周期纪律）
    """

    READY_MARK = "worker 起来了"   # worker.py 就绪日志行
    ENTANGLED = ("SANDBAR_WORKER_META", "SANDBAR_WATCH_WORKFLOW", "SANDBAR_WATCH_PPID")

    def __init__(self, queue: str, ready_timeout: float = 30.0,
                 extra_env: "dict | None" = None):
        self.queue = queue
        self.ready_timeout = ready_timeout
        # t260916-02（arbitrate gen2 T4 根因）：workflow 运行期决议（resolve_inspection_plan，
        # 「读当前声明」机制）在 worker 进程重读声明来源——夹具注册表/覆盖层/台账目录若
        # 只随 trigger 子进程走（TRIGGER_ENV 形态），worker 会按真实注册表解析出
        # 「实例未在任何项目声明中」fail-closed blocked。extra_env=调用方把同一夹具
        # env 也喂给 worker（与 trigger 子进程同源，仍经 spawn_env 单点构造）。
        self.extra_env = dict(extra_env or {})
        self.proc = None
        self.log_path = None
        self._log = None

    def _ready(self) -> bool:
        try:
            with open(self.log_path, "r", encoding="utf-8", errors="replace") as f:
                return self.READY_MARK in f.read()
        except OSError:
            return False

    def __enter__(self):
        import time as _time
        # t260916-02：起 worker 前先幂等注册巡检去重 SA（失败只记日志不拦 worker——
        # SA 真缺时 trigger 的 R3 报错会显式点名，不在这里静默也不在这里假红）
        sa_ok, sa_note = ensure_inspection_search_attributes()
        fd, self.log_path = tempfile.mkstemp(prefix="sandbar-insp-worker-", suffix=".log")
        os.close(fd)
        self._sa_note = "[%s] %s" % ("ok" if sa_ok else "WARN", sa_note)
        # t260910-11 隔离红线：worker 子进程 env 同样只从 spawn_env 单点出（私有队列
        # 经 extra 显式传入；目标/namespace 白名单自检在 spawn_env 内）
        env = spawn_env({"SANDBAR_TASK_QUEUE": self.queue, **self.extra_env})
        for k in self.ENTANGLED:
            env.pop(k, None)
        self._log = open(self.log_path, "a", encoding="utf-8")
        self._log.write("[lib] %s\n" % getattr(self, "_sa_note", ""))  # SA 注册结果留痕
        self._log.flush()
        self.proc = subprocess.Popen(
            [py_runner(), WORKER], cwd=TP_DIR, env=env,
            stdout=self._log, stderr=subprocess.STDOUT,
            start_new_session=True)
        deadline = _time.time() + self.ready_timeout
        while _time.time() < deadline:
            if self.proc.poll() is not None:
                die_env("自供给 worker 秒退（exit=%s），日志尾：%s"
                        % (self.proc.returncode, self._tail()))
            if self._ready():
                return self
            _time.sleep(1.0)
        # 就绪标记超时：不假绿——worker 可能仍在注册，如实上报但继续（票会排队等它）
        print("WARN: StageWorker %ds 内未见就绪标记，继续（票排队等 worker）" % self.ready_timeout,
              flush=True)
        return self

    def _tail(self, n: int = 600) -> str:
        try:
            with open(self.log_path, "r", encoding="utf-8", errors="replace") as f:
                return f.read()[-n:]
        except OSError:
            return "<日志不可读>"

    def __exit__(self, exc_type, exc, tb):
        import time as _time
        try:
            if self.proc is not None and self.proc.poll() is None:
                self.proc.terminate()
                try:
                    self.proc.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    self.proc.kill()
                    self.proc.wait(timeout=10)
        finally:
            if self._log is not None:
                self._log.close()
            # 退出自清（t260910-11）：worker 回收后对本进程开过的巡检票逐个 cancel——
            # 正常/报错/超时/取消四条退出路径都过 __exit__（with 保证）；cleanup 内部
            # 每调用自带超时、失败 WARN 放行（不挂死退出路径、不在隔离台留僵尸票）
            try:
                cleanup_tickets()
            except Exception as e:  # noqa: BLE001——自清失败不炸 __exit__
                print("WARN: 退出自清异常（%s）" % e, flush=True)
        return False


def inspection_ledger(ticket_id: str):
    """读巡检票落账（out/inspection/<票号>.json，顶格=face dict：findings/summary/
    heartbeat/…直挂）。收口后 workflow 已关闭、query 随之不可达——**留存面=落账**
    （write_inspection_report 收口时再写终态，同票覆盖）。缺文件/坏 JSON 返回 None。"""
    base = os.environ.get("SANDBAR_INSPECTION_DIR") or os.path.join(TP_DIR, "out", "inspection")
    path = os.path.join(base, "%s.json" % ticket_id)
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def scanner_result(parsed):
    """取 {ok:true} 回执的 result；形状不符返回 None。"""
    if not isinstance(parsed, dict) or parsed.get("ok") is not True:
        return None
    res = parsed.get("result")
    return res if isinstance(res, dict) else None


def scanner_findings(parsed):
    res = scanner_result(parsed)
    if res is None:
        return None
    fs = res.get("findings")
    return fs if isinstance(fs, list) else None


def scenarios_module_text(entries) -> str:
    """生成仓形夹具的 run_scenarios.py（SCENARIOS 三元组字面量，ast 可解析）。"""
    lines = ["SCENARIOS = ["]
    for name, intent, cmd in entries:
        lines.append("    (%r,\n     %r,\n     %r)," % (name, intent, cmd))
    lines.append("]")
    return "\n".join(lines) + "\n"


class RepoTree:
    """仓形夹具树：integration/run_scenarios.py + sc_* 守卫 + server/** 生产方。"""

    def __init__(self, label: str):
        self.label = label
        self.root = tempfile.mkdtemp(prefix="sandbar-insp-%s-" % label)
        self._before = None

    def write(self, rel: str, text: str) -> str:
        path = os.path.join(self.root, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        return path

    def write_bytes(self, rel: str, data: bytes) -> str:
        path = os.path.join(self.root, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            f.write(data)
        return path

    def write_scenarios(self, entries) -> None:
        self.write("integration/run_scenarios.py", scenarios_module_text(entries))

    def snapshot_checksums(self):
        out = {}
        for base, _dirs, files in os.walk(self.root):
            for fn in files:
                p = os.path.join(base, fn)
                with open(p, "rb") as f:
                    out[os.path.relpath(p, self.root)] = f.read()
        return out

    def keep_checksums(self) -> None:
        self._before = self.snapshot_checksums()

    def tree_unchanged(self) -> str:
        """红线可判定：扫描前后逐字节一致；不一致返回差异描述，一致返回空串。"""
        after = self.snapshot_checksums()
        diffs = [k for k in sorted(set(self._before) | set(after))
                 if self._before.get(k) != after.get(k)]
        return "" if not diffs else "被扫描树被改动：%s" % ",".join(diffs)

    def cleanup(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)


# ---------------------------------------------------------------- KI-051 形态夹具族

PRODUCER_REL = "server/plugins/workbench/src/client/capture.mjs"


def _ui_guard_mjs(anchor: str, producer_rel: str = PRODUCER_REL) -> str:
    """UI 捕获型守卫夹具（KI-051 实案形态：capture-chat 浏览器守卫断言 UI 文案）。
    含 page./locator( 标记——扫描器 S2 范围闸（is_ui_guard）只索引 UI 捕获守卫。"""
    return (
        "// 守卫：隔离台新建会话锚（KI-051 形态夹具，capture-chat 形态）\n"
        "// 守卫对象生产方: %s\n" % producer_rel +
        "const label = await page.locator('.session-create').innerText();\n"
        'assert(label.includes("%s"), "守卫锚缺失");\n' % anchor
    )


def ki051_high_tree(label: str = "ki051-high") -> RepoTree:
    """纯重写漂移（③ high 支路）：生产方在位、锚字面与核心片段（隔离台/新建会话）全缺。"""
    t = RepoTree(label)
    t.write_scenarios([("t-fix-guard", "隔离台新建会话锚守卫夹具", "true")])
    t.write("integration/sc_guard_sample.mjs", _ui_guard_mjs(KI051_OLD_ANCHOR))
    # 纯重写：核心片段「隔离台」「新建会话」零残留
    t.write(PRODUCER_REL,
            'const section = "项目行";\n'
            'const label = section + "『+ 钮』";\n'
            "export function buttonLabel() { return label; }\n")
    return t


def ki051_med_tree(label: str = "ki051-med") -> RepoTree:
    """真实 capture.mjs 案形态（④ med 支路）：留共享前缀「隔离台」、锚措辞已换（模板拼接）。"""
    t = RepoTree(label)
    t.write_scenarios([("t-fix-guard", "隔离台新建会话锚守卫夹具", "true")])
    t.write("integration/sc_guard_sample.mjs", _ui_guard_mjs(KI051_OLD_ANCHOR))
    t.write(PRODUCER_REL,
            'const section = "隔离台项目行";\n'
            'const label = section + "『+ " + "钮』";\n'
            "export function buttonLabel() { return label; }\n")
    return t


def ki051_healthy_tree(label: str = "ki051-healthy") -> RepoTree:
    """健康对照：锚措辞字面在场——不得出任何锚发现。"""
    t = RepoTree(label)
    t.write_scenarios([("t-fix-guard", "隔离台新建会话锚守卫夹具", "true")])
    t.write("integration/sc_guard_sample.mjs", _ui_guard_mjs(KI051_OLD_ANCHOR))
    t.write(PRODUCER_REL,
            'const label = "%s";\n'
            "export function buttonLabel() { return label; }\n" % KI051_OLD_ANCHOR)
    return t


def ki051_orphan_tree(label: str = "ki051-orphan") -> RepoTree:
    """上下文定位不到：守卫只引用不存在的生产方——锚必须让位不出发现（防误报满屏）。"""
    t = RepoTree(label)
    t.write_scenarios([("t-fix-guard", "隔离台新建会话锚守卫夹具", "true")])
    t.write("integration/sc_guard_orphan.mjs",
            _ui_guard_mjs(KI051_OLD_ANCHOR, "server/plugins/workbench/src/client/definitely_absent.mjs"))
    return t


# ---------------------------------------------------------------- 契约面夹具

def duplicate_tree(label: str = "dup") -> RepoTree:
    """重复场景夹具：高重叠对（intent 近逐字）+ 独立条目（不同守护面）。"""
    t = RepoTree(label)
    intent_a = "项目会话区账册生命周期守卫：新建续号、关闭不回收、active 恰一、跨键一致"
    t.write_scenarios([
        ("t-fix-alpha", intent_a, "node baselines/a.mjs"),
        ("t-fix-alpha-copy", intent_a + "（副本）", "node baselines/a.mjs"),
        ("t-fix-gamma", "度量面板陈旧缓存自愈：TTL 过期重算、双视图收敛、自愈不自锁", "node baselines/b.mjs"),
    ])
    return t


def stale_tree(label: str = "stale") -> RepoTree:
    """过时断言夹具：引用资产缺席（已挪）+ 引用行号越界，两类各自可报。"""
    t = RepoTree(label)
    t.write_scenarios([("t-fix-stale", "过时断言夹具：引用缺席与行号越界", "true")])
    t.write("integration/sc_guard_moved.py",
            'cmd_target = "node integration/baselines/definitely_missing_asset.mjs"  # 小写赋值：真仓路径断言形态\n'
            'check_line("server/capture.mjs", 999)  # L999 越界：目标不足 999 行\n')
    t.write("server/capture.mjs", "export const ok = true;\n")
    return t


def clean_tree(label: str = "clean") -> RepoTree:
    """全绿夹具：守卫锚字面在场、引用全存、清单无重复——零发现+heartbeat true。"""
    t = RepoTree(label)
    t.write_scenarios([
        ("t-fix-clean", "干净夹具：锚在场引用全存零发现", "true"),
        ("t-fix-clean-2", "另一守护面：调度声明门与触发回执契约", "true"),
    ])
    t.write("integration/sc_clean_guard.py",
            "# 干净守卫\n"
            "# 守卫对象生产方: server/capture.mjs\n"
            'PRODUCER = "server/capture.mjs"\n'
            'assert "面板标题口径" in body, "锚缺失"\n')
    t.write("server/capture.mjs", 'export const label = "面板标题口径";\n')
    return t


def malformed_guard_tree(label: str = "malformed") -> RepoTree:
    """畸形被扫输入：守卫文件为二进制乱码——不崩、结构化回执。"""
    t = RepoTree(label)
    t.write_scenarios([("t-fix-malformed", "畸形输入夹具", "true")])
    t.write_bytes("integration/sc_garbage.py", b"\x00\x01\xff binary garbage \xfe")
    return t


def malformed_manifest_tree(label: str = "bad-manifest") -> RepoTree:
    """清单畸形：SCENARIOS 含残缺元组——逐条降级 med 点名，不崩不静默。"""
    t = RepoTree(label)
    t.write("integration/run_scenarios.py",
            'SCENARIOS = [\n'
            '    ("t-fix-ok", "正常条目意图", "true"),\n'
            '    ("bad",),\n'
            ']\n')
    return t
