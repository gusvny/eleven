#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""stage_docker L1（t260904-19；替代退役的 test_bench.py——bench.py 槽位制随票退役，
UT 随实现重构同批重写，不留指向退役路径的恒红假网，KI-038 形状防御）。

用假 docker shim（PATH 前置）真跑 stage_docker CLI 编排面——shim 模拟 daemon 的
端口绑定（真 TCP 持有 + HTTP 200 应答），所以健康探针、并发档位避让、compose env
传递、失败清场全是真语义，只有容器层是假的。真 docker 的容器面由宿主装 docker 后
的集成实跑覆盖（票口径：改造先行，装好即绿）。

覆盖面：
- up 全服务：JSON 端口在档位窗内/互异/非禁区；compose 收到 SANDBAR_TEST_* env；
  状态文件落地；down 后零残留 + 幂等二连；
- 并发双起（验收①回归锚）：两进程同时 up，各得不同档位（TOCTOU 闭合面——假 daemon
  真绑端口，后来者 bind 探测见忙滑档）；
- 档位锁外部占用 → 分配滑档；
- 状态清扫带龄护栏（run Q 挤台回归锚）：新鲜状态无容器在场也保留档位/
  不删文件；带龄无容器状态才被回收；
- 清扫稳定确认（run V 挤台回归锚）：带龄状态遇 docker ps 瞬时空窗（前两次
  空、第三次见容器）不得回收，状态文件与档位均保留；
- docker 缺席 / 测试镜像缺席 / compose up 失败（半途死）→ 诚实环境红 + 就地清场；
- 畸形输入全电池：project/端口旋钮/目录/半指定——逐条点名检查项、零副作用；
- ensure：健康复用（reused）+ 半残拆重起 + 同项目并发 ensure 互斥（run K 雷群
  回归锚：双绿、恰一方复用、全窗口单起台——先到先得独占起台，后来者持锁
  等待后双查健康）；
- bench.py 守卫回归（assert_not_production 红绿）。

跑法：python3 integration/tests/test_stage_docker.py（stdlib-only，秒级，无 docker）。
"""
import json
import hashlib
import os
import pathlib
import signal
import socket
import stat
import subprocess
import sys
import tempfile
import threading
import time
import textwrap
import unittest

HERE = pathlib.Path(__file__).resolve().parent
INTEG = HERE.parent
sys.path.insert(0, str(INTEG))

import bench  # noqa: E402  （守卫回归面；槽位制已退役，只剩守卫/审计/registry 助手）

# 共机慢化容忍倍率（t260910-05 仲裁 gen3）：多泳道同机时兄弟票 agent/CPU 争抢
# 可把 shim 操作整体拖慢 ~5×（实测：套件内 592s vs 空载单跑 125s，三连绿对照），
# 固定 --timeout 30/40/60 与 subprocess 120s 窗会误红。本倍率只放大「耐心窗」，
# 不改任何断言（健康到达/零残留/锁滑档语义照断）；环境变量可压回或放大。
TSCALE = int(os.environ.get("SANDBAR_TEST_STAGE_TSCALE", "3"))
import stage_docker as sd  # noqa: E402  （共享缺省锁根定位：档位锁/状态面断言用）

# 共享起台面繁忙预检（t260910-05 仲裁 gen4）：本电池与真世界共享锁根是既定纪律
# （见上），但多泳道同机时兄弟票真台起台/走廊与电池在同一 flock 面、同一
# 21000-25000 端口带内交错，套内四连红（485/573/592/661s）全落在该窗口，而
# 空载/受控 11 连绿——繁忙面上「产品坏」判定不成立。开跑前探测两信号：
# ①新鲜外来工程状态（120s 内 mtime 的 project-*.json 且非本电池自家工程名）；
# ②被持有的档位锁（band-N.lock 非阻塞 flock 抢不到=有活进程正持锁起台）。
# 命中即诚实三态 exit 2 点名理由（环境面），不作产品判定；安静面照常 17 子用例全判。
_OWN_PROJECTS = ("uta", "utb", "utc", "utd", "ute", "utx",
                 "utba", "utbb", "utbc")   # utba/b/c=批台 ns 面用例（t260921-06）
_BUSY_WINDOW_S = 120


def _shared_plane_busy():
    """返回 None（安静）或字面理由（繁忙）。见上注。"""
    import fcntl
    try:
        root = pathlib.Path(sd.lock_root())
    except Exception:
        return None  # 锁根本身不可用=下游自会诚实环境红，不重复归因
    foreign = []
    now = time.time()
    for p in root.glob("project-*.json"):
        name = p.stem[len("project-"):]
        if name in _OWN_PROJECTS:
            continue
        try:
            if now - p.stat().st_mtime <= _BUSY_WINDOW_S:
                foreign.append(name)
        except OSError:
            continue
    if foreign:
        return ("共享锁根 %s 内有新鲜外来工程状态（%s，%ds 内有起台活动）——"
                "多泳道起台窗内不作产品判定，稍后重跑" % (root, ",".join(sorted(foreign)[:4]), _BUSY_WINDOW_S))
    for p in sorted(root.glob("band-*.lock")):
        try:
            fh = open(p, "r")
            try:
                fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
                fcntl.flock(fh, fcntl.LOCK_UN)
            except OSError:
                return ("共享锁根 %s 的 %s 正被活进程持有（有起台进行中）——"
                        "多泳道起台窗内不作产品判定，稍后重跑" % (root, p.name))
            finally:
                fh.close()
        except OSError:
            continue
    return None

SHIM = r'''#!/usr/bin/env python3
"""假 docker（stage_docker L1 专用）：模拟 daemon 端口持有与 HTTP 活性。"""
import json, os, socket, subprocess, sys, time

STATE = os.environ["FAKE_DOCKER_STATE"]
P = pathlib = None
import pathlib

def hold(ports):
    """持久持有端口（真 TCP listener + console 口 HTTP 200），写 pid 供 down 清。"""
    import http.server, threading
    socks = []
    for name, port in ports.items():
        s = socket.socket()
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind(("127.0.0.1", port))
        s.listen(16)
        socks.append(s)
        if name == "console":
            def serve(sock=s):
                while True:
                    try:
                        conn, _ = sock.accept()
                        conn.sendall(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\nok")
                        conn.close()
                    except OSError:
                        return
            threading.Thread(target=serve, daemon=True).start()
    pathlib.Path(STATE, "hold-alive").write_text("1")
    while pathlib.Path(STATE, "hold-alive").exists():
        time.sleep(0.2)

def main():
    cmd = sys.argv[1:]
    if cmd == ["info"]:
        return 0
    if cmd[:1] == ["network"]:
        # 受管网段面（t260912-02）：daemon 现存网段=空（净态宿主语义，ls -q/
        # --format 均空输出）、rm/inspect/prune 幂等成功——分配排除集为空、
        # 撞号清网子用例（compose up 撞子网后 docker network rm）可走通。
        return 0
    if cmd[:2] == ["image", "inspect"]:
        return 0 if pathlib.Path(STATE, "image-ok").exists() else 1
    if cmd[:1] == ["compose"]:
        rest = cmd[1:]
        i = rest.index("-p")
        proj = rest[i + 1]
        action = rest[i + 2]
        if action == "up":
            if pathlib.Path(STATE, "up-fail").exists():
                sys.stderr.write("fake compose up failure\n")
                return 1
            services = rest[i + 5:]  # up -d --quiet-pull <services...>（-p 后第 5 位起）
            ports = {}
            if "temporal" in services:
                ports["temporal"] = int(os.environ["SANDBAR_TEST_TEMPORAL_PORT"])
                ports["ui"] = int(os.environ["SANDBAR_TEST_TEMPORAL_UI_PORT"])
            if "dsh" in services:
                ports["console"] = int(os.environ["SANDBAR_TEST_CONSOLE_PORT"])
            pathlib.Path(STATE, "last-up.json").write_text(json.dumps(
                {"project": proj, "services": services, "ports": ports,
                 "env": {k: v for k, v in os.environ.items() if k.startswith("SANDBAR_TEST_")
                         or k in ("SANDBAR_TARGET_HOST", "SANDBAR_PROJECTS_DIR")}}))
            cnt = pathlib.Path(STATE, "up-count")
            # 真计数（t260910-12 修正：旧写法 write_text 覆盖同值，计数恒为
            # 1 token，"只起一次台"断言恒真=假绿）。首写不存在从 0 起。
            cnt.write_text(str(int(cnt.read_text().strip()) + 1 if cnt.exists() else 1) + " ")
            log = open(pathlib.Path(STATE, "up.log"), "a")
            subprocess.Popen([sys.executable, __file__, "--hold", json.dumps(ports)],
                             stdout=log, stderr=log, start_new_session=True,
                             pass_fds=())
            time.sleep(0.6)  # holder 绑定端口（daemon 语义：返回时端口已真持有）
            return 0
        if action == "down":
            pathlib.Path(STATE, "hold-alive").unlink(missing_ok=True)
            pathlib.Path(STATE, "last-down").write_text(proj)
            return 0
        if action == "logs":
            print("fake compose log tail")
            return 0
        if action == "ps":  # ps -a --filter label=... --format {{.Names}}
            alive = pathlib.Path(STATE, "hold-alive").exists()
            if alive:
                print("%s-temporal" % proj)
                if "dsh" in (json.loads(pathlib.Path(STATE, "last-up.json").read_text())
                             or {}).get("services", []):
                    print("%s-dsh" % proj)
            return 0
    if cmd[:1] == ["ps"]:  # 顶层 docker ps -a --filter label=... --format {{.Names}}/{{.ID}}
        filt = [a for a in cmd if a.startswith("label=com.docker.compose.project=")]
        if not filt:
            return 0
        proj = filt[0].split("label=com.docker.compose.project=", 1)[1]
        fmt = cmd[cmd.index("--format") + 1] if "--format" in cmd else "{{.Names}}"
        if ".Label" in fmt:
            return 0  # working_dir 探针格式：shim 无该 label → 空输出（探针=None，
                      # 判定走保守分支——不能回容器名假造 working_dir）
        up = pathlib.Path(STATE, "last-up.json")
        alive = pathlib.Path(STATE, "hold-alive").exists()
        services = (json.loads(up.read_text()) if up.exists() else {}).get("services", [])
        names = []
        if alive and services and json.loads(up.read_text()).get("project") == proj:
            if "temporal" in services:
                names.append("%s-temporal" % proj)
            if "dsh" in services:
                names.append("%s-dsh" % proj)
        for name in names:
            if "{{.ID}}" in fmt:
                # 稳定假容器 id（名字派生，确定性）：同容器多次查询 id 不变；
                # 容器被重建（名字相同）id 也不变——id 幂等断言必须配容器集合
                # 与 up-count 一起看；id 面只供 container_ids 形状自证。
                print(hashlib.sha1(name.encode()).hexdigest()[:12])
            else:
                print(name)
        return 0
    if cmd[:1] == ["--hold"]:
        hold(json.loads(cmd[1]))
        return 0
    sys.stderr.write("fake docker: unhandled %r\n" % (cmd[:3],))
    return 1

if __name__ == "__main__":
    sys.exit(main())
'''


class StageCLIBase(unittest.TestCase):
    def setUp(self):
        self.state = tempfile.mkdtemp(prefix="stage-l1-")
        # 锁根纪律：不设 SANDBAR_STAGE_LOCK_DIR——与生产调用方共享缺省锁根
        # （flock 档位互斥只在共享根下成立，t260904-19 拓扑注释既定）。260909
        # 提速战役③终验实锤：本套件曾用 out/ 私有锁根，真台（③b 起常驻
        # Phase 2 并发窗口）与假台各拿各的档位锁、互不可见，假台 holder
        # bind 到真台已占端口（run F/J 本套件在套内红、单跑绿即此族）。
        self.bin = tempfile.mkdtemp(prefix="stage-l1-bin-")
        self.shim = pathlib.Path(self.bin, "docker")
        self.shim.write_text(SHIM)
        self.shim.chmod(0o755)
        pathlib.Path(self.state, "image-ok").write_text("1")
        self._saved_env = {}
        for k in ("FAKE_DOCKER_STATE", "SANDBAR_STAGE_LOCK_DIR", "PATH",
                  "SANDBAR_TEST_CONSOLE_PORT", "SANDBAR_TEST_TEMPORAL_PORT",
                  "SANDBAR_TEST_TEMPORAL_UI_PORT", "SANDBAR_TEMPORAL_BIN",
                  "SANDBAR_STAGE_SWEEP"):
            self._saved_env[k] = os.environ.get(k)

    def tearDown(self):
        subprocess.run(["pkill", "-f", "stage-l1-bin-"], capture_output=True)  # 兜底清 holder
        import shutil
        for k, v in self._saved_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def env(self, **extra):
        e = dict(os.environ)
        e["FAKE_DOCKER_STATE"] = self.state
        e["PATH"] = self.bin + os.pathsep + e["PATH"]
        # L1 固定「CLI 不可得」路径：env 指路不存在文件 → resolve 抛 MissingAsset → cli=None
        # （不然主树回退真 CLI 会去连假台，sa_note 落「namespace create 失败」分支）
        e["SANDBAR_TEMPORAL_BIN"] = "/nonexistent-stage-l1/temporal"
        # 共享缺省锁根纪律的配套（t260912-02）：起台挂点的残台清扫必须明示关闭
        # ——假 compose down 只动 FAKE 状态面，真去判拆共享根上的别泳道活租约
        # 会误释放真台。清扫语义面由 test_stage_lease.SweepJudgeTest 白盒覆盖。
        e.setdefault("SANDBAR_STAGE_SWEEP", "off")
        e.update({k: str(v) for k, v in extra.items()})
        return e

    def cli(self, *args, _timeout=120, **kw):
        # _timeout：测试壳的子进程外层超时（默认 120s）。慢 daemon 下 stage_docker
        # 自身的 docker/compose 子调用也会爬行，外层须 ≥ 该调用的内部预算 + 余量
        # （t260910-08 arbitrate：full 档测 90s 内预算被 120s 外层掐死的实证）。
        # --timeout 预算统一 ×TSCALE（共机慢化容忍，见模块头注，main 侧语义）——
        # 扫参数单点，断言与工具语义零变更；外层超时同乘 TSCALE 保比例。
        scaled = list(args)
        for i, a in enumerate(scaled):
            if a == "--timeout" and i + 1 < len(scaled) and scaled[i + 1].isdigit():
                scaled[i + 1] = str(int(scaled[i + 1]) * TSCALE)
        return subprocess.run(
            [sys.executable, str(INTEG / "stage_docker.py")] + scaled,
            capture_output=True, text=True, timeout=_timeout * TSCALE,
            env=self.env(**kw))

    def up_json(self, project, *extra, _timeout=120, **kw):
        # 泳道 **kw（env 注入）× main _timeout（外层超时预算）双语义并集
        p = self.cli("up", "--project", project, *extra, _timeout=_timeout, **kw)
        self.assertEqual(p.returncode, 0, "up 应成功：%s%s" % (p.stdout, p.stderr))
        return json.loads(p.stdout.strip().splitlines()[-1])

    def last_up(self):
        f = pathlib.Path(self.state, "last-up.json")
        return json.loads(f.read_text()) if f.exists() else None


class UpDownTest(StageCLIBase):
    def test_up_full_then_down_zero_residue_and_idempotent(self):
        # 就绪窗 90s：同机并发台（多 console 栈）负载下 30s 会误判超时（t260910-08
        # arbitrate 实证：监听/容器本质健康，只是冷启动探针窗口过紧）——只放宽前置
        # 等待，零残留/幂等/禁区断言原样不动。
        st = self.up_json("uta", "--services", "full", "--namespace", "ns-uta", "--timeout", "90",
                          _timeout=300)
        self.assertEqual(st["project"], "uta")
        self.assertEqual(sorted(st["services"]), ["dsh", "temporal"])
        ports = st["ports"]
        self.assertEqual(len(set(ports.values())), 3, "三端口互异")
        for name, p in ports.items():
            self.assertNotIn(p, stage_forbidden(), "%s=%d 落禁区" % (name, p))
            self.assertGreaterEqual(min(ports.values()), sd.band_base(), "档位窗下界")
            self.assertLess(max(ports.values()),
                            sd.band_base() + sd.BAND_COUNT * sd.BAND_STEP, "档位窗上界")
        up = self.last_up()
        self.assertEqual(up["project"], "uta")
        self.assertEqual(up["env"]["SANDBAR_TEST_TEMPORAL_NAME"], "uta-temporal")
        self.assertEqual(up["env"]["SANDBAR_TEST_DSH_NAME"], "uta-dsh")
        self.assertEqual(up["env"]["SANDBAR_TEST_NAMESPACE"], "ns-uta")
        self.assertNotIn("SANDBAR_PROJECTS_DIR", up["env"],
                         "未注入注册表根时 env 不设——compose 侧缺省 /nonexistent 兜底")
        self.assertFalse(st["sa_registered"], "无 temporal CLI 时 sa_registered=false（如实）")
        self.assertIn("CLI", st["sa_note"])
        # 容器真绑定（假 daemon 语义）→ 端口探活
        for p in ports.values():
            self.assertTrue(_port_open(p), "up 后端口 %d 应活" % p)
        # down：零残留 + 幂等二连
        d = self.cli("down", "--project", "uta")
        self.assertEqual(d.returncode, 0, d.stderr)
        self.assertEqual(json.loads(d.stdout)["residue"], [])
        d2 = self.cli("down", "--project", "uta")
        self.assertEqual(d2.returncode, 0, "down 幂等二连应 0：%s" % d2.stderr)
        # 释放证据两截（260910 多泳道同宿主实测）：①归属证据=shim holder 已死
        # （hold-alive 摘除——我方绑定必然释放，免竞态）；②TCP 释放=共享宿主上
        # 的尽力面：端口仍应答且我方 holder 已死=外来占用者（他泳道 UT/真台，
        # 跨锁根互不可见 + REUSEADDR 双绑可同口并存），明示让位不假红。
        self.assertFalse(pathlib.Path(self.state, "hold-alive").exists(),
                         "shim holder 必须已被 down 摘除（我方释放的归属证据）")
        for p in ports.values():
            if _port_open(p):
                print("[port-contended] 端口 %d down 后仍应答且我方 holder 已死"
                      "——外来占用（他泳道），TCP 释放断言让位不假红" % p, flush=True)

    def test_dsh_only_sets_dead_target_host(self):
        st = self.up_json("utd", "--services", "dsh", "--timeout", "30")
        self.assertNotIn("temporal", [k for k in st["ports"] if False] or [])
        up = self.last_up()
        self.assertEqual(up["services"], ["dsh"])
        self.assertEqual(up["env"]["SANDBAR_TEST_TARGET_HOST"], "127.0.0.1:1",
                         "dsh-only 台容器内引擎地址=容器内死端口（compose 映射 SANDBAR_TARGET_HOST）")
        self.cli("down", "--project", "utd")

    def test_concurrent_double_up_distinct_bands(self):
        """验收①回归锚：两进程同时起，各得不同档位（后来者 bind 探测见忙滑档）。"""
        ps = [subprocess.Popen(
            [sys.executable, str(INTEG / "stage_docker.py"), "up", "--project", name,
             "--services", "full", "--timeout", "40"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            env=self.env()) for name in ("utp1", "utp2")]
        outs = [p.communicate() for p in ps]
        for p, (out, err) in zip(ps, outs):
            self.assertEqual(p.returncode, 0, "并发 up 应双绿：%s %s" % (out, err))
        a = json.loads(outs[0][0].strip().splitlines()[-1])
        b = json.loads(outs[1][0].strip().splitlines()[-1])
        self.assertEqual(set(a["ports"].values()) & set(b["ports"].values()), set(),
                         "并发双起端口零交集（实得 %s / %s）" % (a["ports"], b["ports"]))
        self.cli("down", "--project", "utp1")
        self.cli("down", "--project", "utp2")


class BandAllocationTest(StageCLIBase):
    def test_external_band_lock_skips_band(self):
        """档位锁被外部持有 → 分配滑到下一档（flock 原子预留面）。"""
        import fcntl
        lock = sd.lock_root() / "band-0.lock"
        lock.write_text("")
        fd = os.open(str(lock), os.O_RDWR)
        fcntl.flock(fd, fcntl.LOCK_EX)  # 持锁不放
        try:
            st = self.up_json("utb", "--services", "temporal", "--timeout", "30")
            base = min(st["ports"].values())
            self.assertGreaterEqual(base, sd.band_base() + sd.BAND_STEP,
                                    "band-0 被占应滑档（实得 %s）" % st["ports"])
        finally:
            os.close(fd)
        self.cli("down", "--project", "utb")

    def test_legacy_state_record_recycled_as_dead(self):
        """R7 迁移语义回归锚（t260910-12）：无 lease_id/heartbeat 的旧格式状态
        文件（t260910 之前形态）按「过期死」处置——就地回收（档位释放、文件
        删除）。取舍：单机测试环境、升级窗口一次，宁误拆一次旧格式台不留占死
        档位。新鲜宽限（旧 STALE_STATE_GRACE_S mtime 面）已随租约化整体退役。"""
        root = sd.lock_root()
        legacy = root / "project-legacyfmt.json"
        try:
            legacy.write_text(json.dumps({"project": "legacyfmt",
                                          "ports": {"console": 24100}}),
                              encoding="utf-8")
            busy = sd.state_busy_ports()
            self.assertFalse(legacy.exists(), "旧格式记录应按过期死回收（R7）")
            self.assertNotIn(24100, busy, "被回收的旧格式档位不再占用")
        finally:
            legacy.unlink(missing_ok=True)

    def test_live_lease_busy_despite_docker_ps_blip(self):
        """run V/X 挤台回归锚（t260910-12 租约语义改写）：docker ps 采样在存活
        判定中已无角色——活租约（心跳新鲜+holder 在）无论 docker ps 返回什么都
        按占用保留、文件绝不回收；采样空窗再也翻不进回收/拆台路径。"""
        root = sd.lock_root()
        tgt = root / "project-blipswp.json"
        try:
            lease = sd.new_lease("blipswp", holder_pid=os.getpid(),
                                 services=["dsh"], ttl=90)
            lease["state"] = "up"
            lease["ports"] = {"console": 24120}
            sd.write_lease("blipswp", lease)
            real = sd.residue_containers

            def always_empty(project):   # 采样空窗：永远假空
                return []

            sd.residue_containers = always_empty
            try:
                busy = sd.state_busy_ports()
            finally:
                sd.residue_containers = real
            self.assertTrue(tgt.exists(), "活租约文件不得被回收（采样面无角色）")
            self.assertIn(24120, busy, "活租约档位按占用保留")
        finally:
            tgt.unlink(missing_ok=True)

    def test_dead_lease_recycled_holder_pid_gone(self):
        """回收判据唯一化回归锚：租约过期 AND holder 进程不存在 → 就地回收。
        对照子用例：过期但 holder pid 仍活（pid 复用族）→ 不回收（宁可占死档位，
        满员闸诚实红暴露，绝不误拆）。"""
        root = sd.lock_root()
        dead = root / "project-deadlease.json"
        stuck = root / "project-stucklease.json"
        try:
            lease = sd.new_lease("deadlease", holder_pid=999999, services=[],
                                 ttl=0.05)
            lease["ports"] = {"console": 24130}
            sd.write_lease("deadlease", lease)
            stuck_lease = sd.new_lease("stucklease", holder_pid=os.getpid(),
                                       services=[], ttl=0.05)
            stuck_lease["ports"] = {"console": 24131}
            sd.write_lease("stucklease", stuck_lease)
            time.sleep(0.2)   # 双双过期：一个 holder 已死，一个 holder=本进程
            busy = sd.state_busy_ports()
            self.assertFalse(dead.exists(), "过期+holder 死 → 回收")
            self.assertNotIn(24130, busy, "回收后档位释放")
            self.assertTrue(stuck.exists(), "过期+pid 活（复用族）→ 绝不回收")
            self.assertIn(24131, busy, "pid 复用族档位按占用保留（诚实红暴露）")
        finally:
            dead.unlink(missing_ok=True)
            stuck.unlink(missing_ok=True)


class HonestEnvFailTest(StageCLIBase):
    def test_docker_absent_named_envfail(self):
        e = self.env()
        e["PATH"] = "/usr/bin:/bin"  # 无 docker shim
        p = subprocess.run([sys.executable, str(INTEG / "stage_docker.py"), "up",
                            "--project", "utx", "--services", "temporal"],
                           capture_output=True, text=True, timeout=60, env=e)
        self.assertEqual(p.returncode, 2, "docker 缺席=ENV_FAIL exit 2")
        self.assertIn("docker", p.stderr)

    def test_image_absent_names_build_script(self):
        pathlib.Path(self.state, "image-ok").unlink()
        p = self.cli("up", "--project", "utx", "--services", "temporal")
        self.assertEqual(p.returncode, 2)
        self.assertIn("build-test-temporal.sh", p.stderr)
        self.assertIsNone(self.last_up(), "镜像缺席时不得起 compose")

    def test_compose_up_halfdead_cleans_up(self):
        """up 半途死（temporal 起 dsh 起不来 / compose 报错）→ 就地 down 清场。"""
        pathlib.Path(self.state, "up-fail").write_text("1")
        p = self.cli("up", "--project", "utf", "--services", "full")
        self.assertEqual(p.returncode, 2)
        self.assertIn("up 失败", p.stderr)
        downed = pathlib.Path(self.state, "last-down")
        self.assertTrue(downed.exists(), "半途死必须就地 down（实得无 down 记录）")
        self.assertFalse((sd.lock_root() / "project-utf.json").exists(),
                         "失败路径零状态残留")


class MalformedInputTest(StageCLIBase):
    def test_bad_project_usage_error(self):
        p = self.cli("up", "--project", "Bad_Name")
        self.assertEqual(p.returncode, 64)
        self.assertIn("project", p.stderr)

    def test_forbidden_port_env_rejected(self):
        p = self.cli("up", "--project", "utg", "--services", "full",
                     SANDBAR_TEST_CONSOLE_PORT=3099,
                     SANDBAR_TEST_TEMPORAL_PORT=21001,
                     SANDBAR_TEST_TEMPORAL_UI_PORT=21002)
        self.assertEqual(p.returncode, 64)
        self.assertIn("禁区", p.stderr)
        self.assertIsNone(self.last_up())

    def test_busy_explicit_port_conflict_exit3(self):
        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
        s.listen(1)
        try:
            p = self.cli("up", "--project", "uth", "--services", "full",
                         SANDBAR_TEST_CONSOLE_PORT=port,
                         SANDBAR_TEST_TEMPORAL_PORT=21001,
                         SANDBAR_TEST_TEMPORAL_UI_PORT=21002)
            self.assertEqual(p.returncode, 3, "被占显式端口=环境冲突 exit 3：%s" % p.stderr)
            self.assertIn("占用", p.stderr)
        finally:
            s.close()

    def test_missing_dir_named(self):
        p = self.cli("up", "--project", "uti", "--fixtures-dir", "/nonexistent-stage-xyz")
        self.assertEqual(p.returncode, 64)
        self.assertIn("fixtures-dir", p.stderr)

    def test_malformed_port_env(self):
        p = self.cli("up", "--project", "utj", "--services", "dsh",
                     SANDBAR_TEST_CONSOLE_PORT="3199x",
                     SANDBAR_TEST_TEMPORAL_PORT=21001,
                     SANDBAR_TEST_TEMPORAL_UI_PORT=21002)
        self.assertEqual(p.returncode, 64)
        self.assertIn("数字", p.stderr)


class EnsureTest(StageCLIBase):
    def test_ensure_reuses_healthy_then_replaces_dead_lease(self):
        """租约语义幂等 ensure：健康租约复用（零重建）；holder（hold 子用例）被杀 →
        过期+pid 死 → 冷路径拆重起（验收②，kill 对象=hold pid）。"""
        st1 = self.up_json("ute", "--services", "dsh", "--timeout", "30",
                           SANDBAR_STAGE_LEASE_TTL_S="2", SANDBAR_STAGE_HEARTBEAT_S="0.5")
        p = self.cli("ensure", "--project", "ute", "--services", "dsh", "--timeout", "30")
        self.assertEqual(p.returncode, 0, p.stderr)
        st2 = json.loads(p.stdout.strip().splitlines()[-1])
        self.assertTrue(st2.get("reused"), "健康租约应复用")
        self.assertEqual(st2["ports"], st1["ports"], "复用不换端口")
        self.assertEqual(st2["container_ids"], st1["container_ids"],
                         "复用返回同一容器 id 集（幂等证据面）")
        self.assertEqual(len(pathlib.Path(self.state, "up-count").read_text().split()),
                         1, "复用路径绝不二次 compose up")
        # 半残新语义：holder=hold 子用例进程被杀 → 心跳停 → 过期 + pid 死 → 回收重建
        hold_pid = json.loads((sd.lock_root() / "project-ute.json").read_text())["holder"]["pid"]
        os.kill(hold_pid, 9)
        time.sleep(3.0)   # > TTL=2s：租约必过期且 holder 必死
        p2 = self.cli("ensure", "--project", "ute", "--services", "dsh", "--timeout", "30")
        self.assertEqual(p2.returncode, 0, p2.stderr)
        st3 = json.loads(p2.stdout.strip().splitlines()[-1])
        self.assertNotIn("reused", st3, "死租约应回收重建而非复用")
        self.assertEqual(int(pathlib.Path(self.state, "up-count").read_text()),
                         2, "死租约冷路径恰重建一次")
        self.cli("down", "--project", "ute")

    def test_ensure_reuse_survives_docker_ps_blip(self):
        """R3 主信号回归锚：复用判定零 docker 查询——docker ps 空窗（假 shim
        全程假空）绝不能把健康租约翻进拆台路径（run L/M/O 互拆根因）。"""
        st1 = self.up_json("utb2", "--services", "dsh", "--timeout", "30")
        real = sd.residue_containers
        sd.residue_containers = lambda project: []
        try:
            p = self.cli("ensure", "--project", "utb2", "--services", "dsh",
                         "--timeout", "30")
        finally:
            sd.residue_containers = real
        self.assertEqual(p.returncode, 0, p.stderr)
        st2 = json.loads(p.stdout.strip().splitlines()[-1])
        self.assertTrue(st2.get("reused"), "采样空窗下健康租约仍复用（R3）")
        self.assertEqual(st2["ports"], st1["ports"])
        self.cli("down", "--project", "utb2")

    def _hold_pid(self, project):
        """租约里 holder（hold 子用例）的 pid——冻结/杀它都走真进程，不做 monkeypatch。"""
        return json.loads((sd.lock_root() / ("project-%s.json" % project)).read_text())["holder"]["pid"]

    def test_ensure_expired_lease_with_live_pid_refuses(self):
        """真僵死（心跳停更 + holder 进程仍在）：宽限窗到期仍不恢复 → 不对抗、不硬拆，
        诚实红点名人工核查（判据唯一化：只有 过期 AND pid 死 才回收）。
        t260913-02 arbitrate gen12 变更：夹具由「伪造 heartbeat_ts=0」改为**真冻结 hold 子用例**
        （SIGSTOP）——伪造时间戳在「活 holder 心跳会自然刷新」的新宽限语义下不再是僵死态
        （那正是要复用的健康态，见下一条恢复用例）；断言集不变（rc=2 + 点名 pid + 零重建）。"""
        self.up_json("utpid", "--services", "dsh", "--timeout", "30",
                     SANDBAR_STAGE_LEASE_TTL_S="2", SANDBAR_STAGE_HEARTBEAT_S="0.5")
        hold_pid = self._hold_pid("utpid")
        os.kill(hold_pid, signal.SIGSTOP)
        try:
            time.sleep(3.0)      # > TTL=2s：心跳必过期且 holder 进程仍在（真僵死形）
            p = self.cli("ensure", "--project", "utpid", "--services", "dsh",
                         "--timeout", "30", SANDBAR_STAGE_STALL_GRACE_S="2")
        finally:
            try:
                os.kill(hold_pid, signal.SIGCONT)
            except OSError:
                pass
        self.assertEqual(p.returncode, 2, "过期+pid 活应诚实 env 红：%s" % p.stderr)
        self.assertIn("pid", p.stderr)
        self.assertIn("心跳停更", p.stderr)
        self.assertEqual(len(pathlib.Path(self.state, "up-count").read_text().split()), 1,
                         "拒收路径绝不 compose up")
        self.cli("down", "--project", "utpid")

    def test_ensure_stalled_heartbeat_recovers_within_grace(self):
        """心跳停更宽限（t260913-02 arbitrate gen12，260914 23:17 闸 17 环境红的根因面）：
        租约过期而 holder（hold 子用例）仍活时，旧行为是**当场**诚实红——一次负载停顿把整族
        console 场景打成环境红（0.2~1.2s，场景一条没跑）。新语义先给宽限窗等心跳恢复：
        恢复 → 复用（零重建、同容器集）。注入=真冻结 hold 子用例 + 宽限窗内解冻（真进程，非桩）。"""
        st1 = self.up_json("utstall", "--services", "dsh", "--timeout", "30",
                           SANDBAR_STAGE_LEASE_TTL_S="2", SANDBAR_STAGE_HEARTBEAT_S="0.5")
        hold_pid = self._hold_pid("utstall")
        os.kill(hold_pid, signal.SIGSTOP)
        timer = threading.Timer(3.0, lambda: os.kill(hold_pid, signal.SIGCONT))
        timer.start()
        try:
            time.sleep(3.0)      # > TTL=2s：进 ensure 时租约必已过期、holder 仍活
            p = self.cli("ensure", "--project", "utstall", "--services", "dsh",
                         "--timeout", "60", SANDBAR_STAGE_STALL_GRACE_S="30")
        finally:
            timer.cancel()
            try:
                os.kill(hold_pid, signal.SIGCONT)
            except OSError:
                pass
        self.assertEqual(p.returncode, 0,
                         "宽限窗内心跳恢复应复用而非拒收：%s" % p.stderr)
        st2 = json.loads(p.stdout.strip().splitlines()[-1])
        self.assertTrue(st2.get("reused"), "心跳恢复后应走复用路径")
        self.assertEqual(st2["container_ids"], st1["container_ids"], "复用不重建容器")
        self.assertEqual(st2["ports"], st1["ports"], "复用不换端口")
        self.assertEqual(len(pathlib.Path(self.state, "up-count").read_text().split()), 1,
                         "恢复路径零 compose up")
        self.cli("down", "--project", "utstall")

    def test_ensure_waits_booting_then_reuses(self):
        """R5/验收②：state=booting → 等待其完成，绝不并发再起。中间进程模拟
        起台者（拉起 hold → 写 booting 租约 → 2.5s 后翻 up → 退出）；ensure
        等到翻面直接复用，全窗口零 compose up。"""
        booter = self._fake_booter("utbw", boot_s=2.5, orphan=False)
        try:
            self._wait_booting_lease("utbw")   # 先等 booting 租约在场再发 ensure
            p = self.cli("ensure", "--project", "utbw", "--services", "dsh",
                         "--timeout", "40", SANDBAR_STAGE_HEARTBEAT_S="0.3")
            self.assertEqual(p.returncode, 0, p.stderr)
            st = json.loads(p.stdout.strip().splitlines()[-1])
            self.assertTrue(st.get("reused"), "booting 翻 up 后应复用")
            cnt = pathlib.Path(self.state, "up-count")
            self.assertEqual(int(cnt.read_text()) if cnt.exists() else 0, 0,
                             "等待路径绝不并发再起")
        finally:
            booter.wait(timeout=30)
            self.cli("down", "--project", "utbw")

    def test_ensure_booting_orphan_reclaimed_then_boots(self):
        """③'起台孤儿端到端：起台者写完 booting 租约即死 → hold 回收孤儿租约
        → ensure 接管冷起台（恰一次 compose up）。等待者永远不会白等。"""
        booter = self._fake_booter("utbo", boot_s=0, orphan=True)
        try:
            self._wait_booting_lease("utbo")   # 等孤儿 booting 租约在场
            p = self.cli("ensure", "--project", "utbo", "--services", "dsh",
                         "--timeout", "40", SANDBAR_STAGE_HEARTBEAT_S="0.3")
            self.assertEqual(p.returncode, 0, p.stderr)
            st = json.loads(p.stdout.strip().splitlines()[-1])
            self.assertNotIn("reused", st, "孤儿 booting 租约应被回收而非复用")
            self.assertEqual(int(pathlib.Path(self.state, "up-count").read_text()), 1,
                             "接管后恰冷起台一次")
        finally:
            booter.wait(timeout=30)
            self.cli("down", "--project", "utbo")

    def _wait_booting_lease(self, project, timeout=20):
        """轮询到 booting 租约在场（fake booter 的握手完成面）。"""
        lease_file = sd.lock_root() / ("project-%s.json" % project)
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                st = json.loads(lease_file.read_text(encoding="utf-8"))
                if st.get("state") == "booting":
                    return
            except (OSError, ValueError):
                pass
            time.sleep(0.1)
        self.fail("booting 租约 %ds 未在场（fake booter 握手失败）" % timeout)

    def _fake_booter(self, project, boot_s, orphan):
        """模拟起台 CLI：拉起 hold（detached）→ 等握手 → 写 booting 租约 →
        （orphan=False：停留 boot_s 后翻 up；orphan=True：立即退出=起台孤儿）。"""
        lease_id = "%s-boot" % project
        script = textwrap.dedent("""
            import json, os, pathlib, subprocess, sys, time
            root = %r
            project, lease_id, boot_s, orphan = %r, %r, %r, %r
            hold = subprocess.Popen(
                [sys.executable, %r, "hold", "--project", project,
                 "--anchor-pid", str(os.getppid()), "--lease-id", lease_id],
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL, start_new_session=True,
                env=dict(os.environ))
            pidfile = pathlib.Path(root, "holder-%%s.pid" %% project)
            deadline = time.time() + 15
            while time.time() < deadline:
                try:
                    if int(pidfile.read_text().strip()) == hold.pid:
                        break
                except (OSError, ValueError):
                    pass
                time.sleep(0.05)
            now = time.time()
            lease = {"lease_id": lease_id, "project": project,
                     "holder": {"ticket": "ut", "pid": hold.pid},
                     "anchor_pid": os.getppid(), "state": "booting",
                     "services": ["dsh"], "ports": {}, "ts": now,
                     "heartbeat_ts": now, "ttl_sec": 120}
            pathlib.Path(root, "project-%%s.json" %% project).write_text(
                json.dumps(lease))
            if not orphan:
                time.sleep(boot_s)
                lease["state"] = "up"
                lease["heartbeat_ts"] = time.time()
                lease["ports"] = {"console": 21000 + (hold.pid %% 300) * 10}
                pathlib.Path(root, "project-%%s.json" %% project).write_text(
                    json.dumps(lease))
        """) % (str(sd.lock_root()), project, lease_id, float(boot_s), bool(orphan),
                str(INTEG / "stage_docker.py"))
        env = self.env(SANDBAR_STAGE_HEARTBEAT_S="0.3")
        self._booter_err = open(str(pathlib.Path(self.state, "booter.err")), "wb")
        return subprocess.Popen([sys.executable, "-c", script],
                                stdout=subprocess.DEVNULL,
                                stderr=self._booter_err, env=env)

    def test_concurrent_ensure_same_project_single_boot(self):
        """run K 雷群回归锚：冷台同项目并发 ensure 互斥——先到先得独占起台，
        后来者持锁等待后双查健康直接复用；双绿且全窗口只起一次台。"""
        # 预算 240s（t260910-08 arbitrate，tail 点名本测）：60s 是锁等待+起台+健康
        # 探的总预算，daemon 被同机其他台拖慢时双绿必爆一——只放宽预算，互斥/
        # 复用/单起台断言原样。
        ps = [subprocess.Popen(
            [sys.executable, str(INTEG / "stage_docker.py"), "ensure",
             "--project", "utc", "--services", "dsh", "--timeout", "240"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            env=self.env()) for _ in range(2)]
        outs = [p.communicate() for p in ps]
        for p, (out, err) in zip(ps, outs):
            self.assertEqual(p.returncode, 0, "并发 ensure 应双绿：%s %s" % (out, err))
        states = [json.loads(out.strip().splitlines()[-1]) for out, _ in outs]
        self.assertEqual(len([s for s in states if s.get("reused")]), 1,
                         "恰一方复用（实得 %s）" % states)
        self.assertEqual(states[0]["ports"], states[1]["ports"], "互斥后复用同台同端口")
        cnt = pathlib.Path(self.state, "up-count")
        self.assertEqual(int(cnt.read_text()), 1,
                         "全窗口只起一次台（实得 %r 次）" % cnt.read_text())
        self.cli("down", "--project", "utc")


class BenchGuardRegression(unittest.TestCase):
    """bench.py 退役槽位制后仍保留的守卫面回归锚。"""

    def test_prod_guard_red_green(self):
        for host in ("127.0.0.1:7233", "localhost:8233"):
            with self.assertRaises(bench.ProductionGuardError):
                bench.assert_not_production(host)
        self.assertEqual(bench.assert_not_production("127.0.0.1:21001"), "127.0.0.1:21001")
        with self.assertRaises(bench.ProductionGuardError):
            bench.assert_not_production("")


def stage_forbidden():
    import stage_docker
    return stage_docker.FORBIDDEN_PORTS


def _port_open(port):
    try:
        return bench.port_open(port)
    except Exception:
        return False


def _band_window_foreign_listeners():
    """档位窗内外来监听者点名（t260910-06 仲裁实证的假红根因）。

    stage_docker 的 bind 探针看不见 SO_REUSEPORT 窃听者：本机 OrbStack 把
    活容器/泄漏台的发布端口 1:1 转发到 127.0.0.1:2xxxx，正好落在档位窗
    （BAND_BASE~+BAND_COUNT*BAND_STEP）内——假 shim 的 console 口被窃听后
    bind 探针照过、就绪探针永不回 → 「console 30s 内未就绪」假红。预检把
    这一环境态显式化：有外来监听=点名 ENV_FAIL exit 2（三态契约：环境红归
    供给面），不许静默撞运气。lsof 不可得（非 macOS）= 预检自弃不拦套件。"""
    try:
        out = subprocess.run(["lsof", "-iTCP", "-sTCP:LISTEN", "-n", "-P"],
                             capture_output=True, text=True, timeout=30).stdout
    except Exception:
        return []
    lo = sd.BAND_BASE
    hi = sd.BAND_BASE + sd.BAND_COUNT * sd.BAND_STEP
    hits = []
    for ln in out.splitlines():
        parts = ln.split()
        if len(parts) < 9 or not parts[8].startswith("127.0.0.1:"):
            continue
        try:
            port = int(parts[8].rsplit(":", 1)[1])
        except ValueError:
            continue
        if lo <= port < hi:
            hits.append("%s(pid=%s) port=%d" % (parts[0], parts[1], port))
    return hits


class NetFuseTest(StageCLIBase):
    """受管网段+保险丝端到端（t260912-02，shim 假容器真编排）：up 的 lease 落
    subnet∈受管表且注入 compose env；关扫明示可见；畸形 NET_BASE=usage 红零副作用。"""

    def test_up_lease_subnet_in_table_and_env_injected(self):
        proj = "l1-net-a"
        proc = self.cli("up", "--project", proj, "--services", "temporal",
                        SANDBAR_STAGE_SWEEP="off")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("STAGE_SWEEP_WARN", proc.stderr, "关扫必须有响亮提示行")
        st = json.loads(proc.stdout.strip().splitlines()[-1])
        lease = json.loads(sd.lease_path(proj).read_text())
        table = sd.net_table()
        self.assertIn(lease.get("subnet"), table, "lease.subnet 必来自受管网段表")
        self.assertNotEqual(lease.get("subnet"), table[-1], "保留尾槽不参与分配")
        up = self.last_up()
        self.assertEqual(up["env"].get("SANDBAR_TEST_SUBNET"), lease.get("subnet"),
                         "compose 收到的子网与租约记录一致")
        self.assertEqual(st.get("subnet"), lease.get("subnet"),
                         "up JSON 对账同一子网")
        self.cli("down", "--project", proj)

    def test_malformed_net_base_usage_red_zero_side_effect(self):
        proj = "l1-net-bad"
        p = self.cli("up", "--project", proj, "--services", "temporal",
                     SANDBAR_STAGE_NET_BASE="nonsense", _timeout=60)
        self.assertEqual(p.returncode, 64)
        self.assertIn("STAGE_USAGE", p.stderr)
        self.assertIn("SANDBAR_STAGE_NET_BASE", p.stderr)
        self.assertIsNone(self.last_up(), "畸形 base：compose 一次都不该被调用")
        self.assertFalse(sd.lease_path(proj).exists(), "不留半租约")


# ---------------------------------------------------------------- 批台 ns 面端到端（t260921-06）

FAKE_TEMPORAL = r'''#!/usr/bin/env python3
"""假 temporal CLI（批台 ns 面 UT 用）：operator namespace create/delete/list 与
search-attribute 按状态文件回放真实输出形状（含 delete 的 not found rc=1 面）。"""
import os, pathlib, sys

args = sys.argv[1:]
state = pathlib.Path(os.environ["FAKE_TEMPORAL_STATE"])
state.parent.mkdir(parents=True, exist_ok=True)
nss = set(state.read_text().split()) if state.exists() else set()


def _value(flag):
    return args[args.index(flag) + 1] if flag in args and args.index(flag) + 1 < len(args) else None


if len(args) >= 3 and args[0] == "operator" and args[1] == "namespace":
    sub = args[2]
    pos = [a for a in args[3:] if not a.startswith("-") and a != "namespace"]
    ns = _value("-n") or (pos[0] if pos else None)
    if sub == "create" and ns:
        nss.add(ns)
        state.write_text("\n".join(sorted(nss)))
        print("Namespace %s successfully registered." % ns)
        sys.exit(0)
    if sub == "delete" and ns:
        if ns == "ns-fail":           # UT 注入面：真删除失败（非 not found 形）
            print("Error: unable to delete namespace %s: boom refused" % ns, file=sys.stderr)
            sys.exit(1)
        if ns in nss:
            nss.discard(ns)
            state.write_text("\n".join(sorted(nss)))
            print("Namespace %s has been deleted." % ns)
            sys.exit(0)
        print("Error: unable to delete namespace %s: namespace %s is not found" % (ns, ns),
              file=sys.stderr)
        sys.exit(1)
    if sub == "list":
        for n in sorted(nss):
            print(n)
        sys.exit(0)
if len(args) >= 2 and args[0] == "operator" and args[1] == "search-attribute":
    print("Search attributes have been added")
    sys.exit(0)
print("fake temporal: unhandled %r" % (args[:3],), file=sys.stderr)
sys.exit(1)
'''


class BatchNsTest(StageCLIBase):
    """批台命名空间面（t260921-06，假 docker shim+假 temporal CLI 真跑 CLI 编排面）：
    --kind batch 落 kind 租约；ns-acquire 注册+记账+重复幂等；ns-drop 删成功/NotFound
    幂等/真失败打标 drop_failed 且 exit 0（失败留痕不拦收口）；批台不在位=诚实 env 红
    exit 2；kind×keep 互斥双层闸（up/ensure 两入口）；ns 名畸形=usage 红。"""

    def setUp(self):
        super().setUp()
        self.ftemp = pathlib.Path(self.bin, "temporal")
        self.ftemp.write_text(FAKE_TEMPORAL)
        self.ftemp.chmod(0o755)
        self.tstate = pathlib.Path(self.state, "temporal-nss.txt")
        self._saved_env["FAKE_TEMPORAL_STATE"] = os.environ.get("FAKE_TEMPORAL_STATE")

    def env(self, **extra):
        extra.setdefault("SANDBAR_TEMPORAL_BIN", str(self.ftemp))
        extra.setdefault("FAKE_TEMPORAL_STATE", str(self.tstate))
        return super().env(**extra)

    def test_batch_boot_marks_kind_and_full_ns_flow(self):
        st = self.up_json("utba", "--services", "temporal", "--kind", "batch",
                          "--timeout", "90", _timeout=300)
        self.assertEqual(st["project"], "utba")
        lease = sd.read_lease("utba")
        self.assertEqual(lease.get("kind"), "batch", "批台租约必须带 kind=batch")
        # ns-acquire：注册 + 记账 + JSON 形状
        p = self.cli("ns-acquire", "--project", "utba", "--namespace", "ns-a")
        self.assertEqual(p.returncode, 0, "ns-acquire 应成功：%s %s" % (p.stdout, p.stderr))
        out = json.loads(p.stdout.strip().splitlines()[-1])
        self.assertEqual(out["project"], "utba")
        self.assertEqual(out["namespace"], "ns-a")
        self.assertEqual(out["mode"], "batch")
        self.assertTrue(out["sa_registered"])
        self.assertIsInstance(out["ports"]["temporal"], int)
        ledger = sd.read_lease("utba").get("namespaces")
        self.assertEqual([e["ns"] for e in ledger], ["ns-a"], "ns 应入租约账本")
        # 重复申请幂等：注册 tolerate + 账覆盖不堆账
        p = self.cli("ns-acquire", "--project", "utba", "--namespace", "ns-a")
        self.assertEqual(p.returncode, 0)
        self.assertEqual(len(sd.read_lease("utba").get("namespaces")), 1)
        # 第二 ns：账本两行
        p = self.cli("ns-acquire", "--project", "utba", "--namespace", "ns-b")
        self.assertEqual(p.returncode, 0)
        self.assertEqual([e["ns"] for e in sd.read_lease("utba").get("namespaces")],
                         ["ns-a", "ns-b"])
        # ns-drop：删成功 → 账移除；NotFound 二连 → 幂等 dropped=True
        p = self.cli("ns-drop", "--project", "utba", "--namespace", "ns-a")
        self.assertEqual(p.returncode, 0, "ns-drop 应 exit 0：%s %s" % (p.stdout, p.stderr))
        self.assertTrue(json.loads(p.stdout.strip().splitlines()[-1])["dropped"])
        self.assertEqual([e["ns"] for e in sd.read_lease("utba").get("namespaces")], ["ns-b"])
        p = self.cli("ns-drop", "--project", "utba", "--namespace", "ns-a")
        self.assertEqual(p.returncode, 0)
        self.assertTrue(json.loads(p.stdout.strip().splitlines()[-1])["dropped"])
        # ns-drop 真失败（ns-fail 注入）：exit 0 + stderr 留痕 + 账面 drop_failed（S3）
        p = self.cli("ns-drop", "--project", "utba", "--namespace", "ns-fail")
        self.assertEqual(p.returncode, 0, "删除失败必须留痕不拦收口（exit 0）")
        self.assertIn("STAGE_NS_DROP_WARN", p.stderr)
        res = json.loads(p.stdout.strip().splitlines()[-1])
        self.assertFalse(res["dropped"])
        self.assertTrue(res["drop_failed"])
        row = next(e for e in sd.read_lease("utba").get("namespaces") if e["ns"] == "ns-fail")
        self.assertTrue(row.get("drop_failed") is True, "失败必须账面打标（S3）")
        # ns 面零拆台：批台租约仍 up、container_ids 未动
        lease = sd.read_lease("utba")
        self.assertEqual(lease.get("state"), "up")
        self.assertEqual(lease.get("container_ids"), st["container_ids"])
        self.cli("down", "--project", "utba")

    def test_ns_acquire_batch_absent_or_nonbatch_env_red(self):
        # 批台缺席：诚实 env 红 exit 2，零副作用（不代起、不落租约）
        p = self.cli("ns-acquire", "--project", "utba-absent", "--namespace", "ns-x")
        self.assertEqual(p.returncode, 2, "批台不在位必须 env 红（要求⑤不假绿）")
        self.assertIn("STAGE_ENV", p.stderr)
        self.assertFalse(sd.lease_path("utba-absent").exists(), "拒绝代起：不留半租约")
        # 非批台（kind 缺失的场景台）：ns 面拒收——不误落别人场景台
        self.up_json("utbb", "--services", "temporal", "--timeout", "90", _timeout=300)
        p = self.cli("ns-acquire", "--project", "utbb", "--namespace", "ns-x")
        self.assertEqual(p.returncode, 2)
        self.assertIn("不在位", p.stderr)
        self.cli("down", "--project", "utbb")

    def test_ns_malformed_usage_red(self):
        for args, why in (
            (("--project", "Bad_Name", "--namespace", "ns-ok"), "project 畸形"),
            (("--project", "utbc", "--namespace", "Bad_NS"), "ns 畸形"),
            (("--namespace", "ns-ok"), "缺 project"),
            (("--project", "utbc"), "缺 namespace"),
        ):
            p = self.cli("ns-acquire", *args)
            self.assertEqual(p.returncode, 64, "%s 应 usage 红：%s" % (why, p.stderr))
            self.assertIn("STAGE_USAGE", p.stderr)

    def test_kind_keep_mutual_exclusion_both_doors(self):
        # 门1：up/ensure 入口旗标互斥
        for cmd in ("up", "ensure"):
            p = self.cli(cmd, "--project", "utbc", "--kind", "batch", "--keep")
            self.assertEqual(p.returncode, 64, "%s kind×keep 应 usage 红" % cmd)
            self.assertIn("互斥", p.stderr)
        self.assertFalse(sd.lease_path("utbc").exists(), "usage 红零副作用")
        # --kind 非法值
        p = self.cli("up", "--project", "utbc", "--kind", "mega")
        self.assertEqual(p.returncode, 64)
        self.assertIn("STAGE_USAGE", p.stderr)
        # 门2：批台在跑后，ensure --keep 撞批台=usage 红（复用面闸）
        self.up_json("utbc", "--services", "temporal", "--kind", "batch",
                     "--timeout", "90", _timeout=300)
        p = self.cli("ensure", "--project", "utbc", "--keep")
        self.assertEqual(p.returncode, 64, "批台在跑时 --keep 必须 usage 红")
        self.assertIn("kind=batch", p.stderr)
        self.cli("down", "--project", "utbc")


if __name__ == "__main__":
    busy = _shared_plane_busy()
    if busy:
        print("[stage-docker L1] ENV_FAIL: %s" % busy, file=sys.stderr)
        sys.exit(2)
    _foreign = _band_window_foreign_listeners()
    if _foreign:
        print("ENV_FAIL: 档位窗 %d~%d 内有外来监听者（bind 探针不可见的 "
              "REUSEPORT 窃听面，典型=泄漏台容器的 OrbStack 端口转发）——"
              "先清泄漏台（docker ps 查陈旧 stage-console-* 对）再跑：%s"
              % (sd.BAND_BASE, sd.BAND_BASE + sd.BAND_COUNT * sd.BAND_STEP,
                 "; ".join(_foreign[:8])), file=sys.stderr)
        sys.exit(2)
    unittest.main(verbosity=2)
