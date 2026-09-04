# -*- coding: utf-8 -*-
"""t260904-02 集成场景共享夹具（无 sc_ 前缀=共享代码，不登记场景清单）。

只服务本票三场景：行式断言收集器、隔离台共享库（integration/bench.py）契约装载、
引擎 client 子进程调用、审计钩子日志读取、安装器入口定位与临时 HOME。

铁律（沿 t260903-10 lib_installer 纪律）：
- 绝不向真环境（3099/7233/8233 现有占用者）发任何信号；场景对生产端口只允许
  「审计钩子自证腿」里被钩子拦截的连接尝试（先记后抛，内核建连前被阻断）；
- 一切状态写临时目录/槽位目录；spawn 的进程收尾 TERM→KILL 兜底；
- 依赖未就位=exit 2 MISSING（环境缺失，可辨于被测红）；端口被外来者占=exit 3。

bench 契约面（integration/bench.py 须提供；implement 段 D 块对齐，本文件为对齐真源）：
  PROD_PORTS                        # 生产端口集合（含 7233/8233）
  class ProductionGuardError(Exception)
  assert_not_production(host)       # host 指生产（端口/字面址）→ raise ProductionGuardError
  class BenchBusy(Exception)        # 满槽排队超 deadline（文案含「槽满」可辨）
  acquire_slot(index=None, deadline_s=None) -> Slot   # flock 抢槽；崩溃自释
  Slot 属性面：index / frontend_port / ui_port / metrics_port / namespace /
              db_path / slot_dir / lock_path / argv / temporalite_pid / stopped
  Slot 行为面：start_temporalite() / stop()（幂等；TERM 进程组→KILL 兜底→端口
              释放核验→删 db/日志，lock 文件保留=槽锚）
  poc_python() -> str               # 引擎 venv 解释器（含主树 gitfile 回退）
  audit_hook_env(dir) -> (env片段, log_path)  # sitecustomize 审计钩子：被测子进程
                                    # 对 PROD_PORTS 的 socket.connect 先记 jsonl 后抛
  write_registry(dir, key, project_dir) -> registry_dir  # fixture 注册表（含 key→dirs）
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
POC = os.path.join(REPO, "server", "dsh", "temporal-poc")
NODE_TS = os.path.join(REPO, "server", "dsh", "temporal-tools", "node.ts")

MISSING_EXIT = 2       # 依赖/设施未就位（环境缺失，非被测红）
ENV_CONFLICT_EXIT = 3  # 所选端口被外来者占（不对抗）

# bench 契约面最小成员清单（缺一即视为未交付/契约漂移）
BENCH_CONTRACT = ("PROD_PORTS", "ProductionGuardError", "assert_not_production",
                  "BenchBusy", "acquire_slot", "audit_hook_env",
                  "write_registry", "poc_python")
SLOT_CONTRACT = ("index", "frontend_port", "ui_port", "metrics_port", "namespace",
                 "db_path", "slot_dir", "lock_path", "argv", "temporalite_pid",
                 "stopped", "start_temporalite", "stop")


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


def check_slot_contract(fail, slot, label):
    """槽对象契约面核对（契约漂移=红并点名缺失成员，防静默半交付）。"""
    miss = [n for n in SLOT_CONTRACT if not hasattr(slot, n)]
    fail.check(not miss, "%s Slot 契约面完整（缺：%s）" % (label, miss or "∅"))


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
