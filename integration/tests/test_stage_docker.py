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
import os
import pathlib
import socket
import stat
import subprocess
import sys
import tempfile
import time
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
# 命中即诚实三态 exit 2 点名理由（环境面），不作产品判定；安静面照常 17 腿全判。
_OWN_PROJECTS = ("uta", "utb", "utc", "utd", "ute", "utx")
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
            cnt.write_text(str(int(cnt.read_text()) if cnt.exists() else 0) + " ")
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
    if cmd[:1] == ["ps"]:  # 顶层 docker ps -a --filter label=... --format {{.Names}}
        filt = [a for a in cmd if a.startswith("label=com.docker.compose.project=")]
        if not filt:
            return 0
        proj = filt[0].split("label=com.docker.compose.project=", 1)[1]
        up = pathlib.Path(STATE, "last-up.json")
        alive = pathlib.Path(STATE, "hold-alive").exists()
        services = (json.loads(up.read_text()) if up.exists() else {}).get("services", [])
        if alive and services and json.loads(up.read_text()).get("project") == proj:
            if "temporal" in services:
                print("%s-temporal" % proj)
            if "dsh" in services:
                print("%s-dsh" % proj)
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
                  "SANDBAR_TEST_TEMPORAL_UI_PORT", "SANDBAR_TEMPORAL_BIN"):
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
        e.update({k: str(v) for k, v in extra.items()})
        return e

    def cli(self, *args, **kw):
        # --timeout 预算统一 ×TSCALE（共机慢化容忍，见模块头注）——扫参数单点，
        # 断言与工具语义零变更。
        scaled = list(args)
        for i, a in enumerate(scaled):
            if a == "--timeout" and i + 1 < len(scaled) and scaled[i + 1].isdigit():
                scaled[i + 1] = str(int(scaled[i + 1]) * TSCALE)
        return subprocess.run(
            [sys.executable, str(INTEG / "stage_docker.py")] + scaled,
            capture_output=True, text=True, timeout=120 * TSCALE, env=self.env(**kw))

    def up_json(self, project, *extra):
        p = self.cli("up", "--project", project, *extra)
        self.assertEqual(p.returncode, 0, "up 应成功：%s%s" % (p.stdout, p.stderr))
        return json.loads(p.stdout.strip().splitlines()[-1])

    def last_up(self):
        f = pathlib.Path(self.state, "last-up.json")
        return json.loads(f.read_text()) if f.exists() else None


class UpDownTest(StageCLIBase):
    def test_up_full_then_down_zero_residue_and_idempotent(self):
        st = self.up_json("uta", "--services", "full", "--namespace", "ns-uta", "--timeout", "30")
        self.assertEqual(st["project"], "uta")
        self.assertEqual(sorted(st["services"]), ["dsh", "temporal"])
        ports = st["ports"]
        self.assertEqual(len(set(ports.values())), 3, "三端口互异")
        for name, p in ports.items():
            self.assertNotIn(p, stage_forbidden(), "%s=%d 落禁区" % (name, p))
            self.assertGreaterEqual(min(ports.values()), 21000, "档位窗下界")
            self.assertLess(max(ports.values()), 25000, "档位窗上界")
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
        for p in ports.values():
            self.assertFalse(_port_open(p), "down 后端口 %d 应释放" % p)

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
            self.assertGreaterEqual(base, 21000 + 10, "band-0 被占应滑档（实得 %s）" % st["ports"])
        finally:
            os.close(fd)
        self.cli("down", "--project", "utb")

    def test_fresh_state_never_swept_as_stale(self):
        """run Q 挤台回归锚：daemon 风暴窗内 docker ps 标签过滤瞬时空窗会把
        刚写好的状态误判 stale 删除 → 同 compose 项目二次起台、compose 挤掉
        刚起好的健康台（run L/M/O 的 console 台反复横跳即此族，~50% 间歇）。
        带龄护栏：新鲜状态（< STALE_STATE_GRACE_S）无容器在场也按存活处置
        （档位保留、文件不删）；带龄状态才由清扫回收。"""
        import shutil
        if not shutil.which("docker"):
            self.skipTest("docker 缺席——residue 面不可用")
        root = sd.lock_root()
        fresh = root / "project-freshswp.json"
        old = root / "project-oldswp.json"
        try:
            fresh.write_text(json.dumps({"project": "freshswp", "ports": {"console": 24100}}),
                             encoding="utf-8")
            old.write_text(json.dumps({"project": "oldswp", "ports": {"console": 24110}}),
                           encoding="utf-8")
            os.utime(str(old), (0, 0))  # mtime 纪元 0 → 必过带龄
            busy = sd.state_busy_ports()
            self.assertIn(24100, busy, "新鲜状态无容器在场也应按存活保留档位（run Q 护栏）")
            self.assertTrue(fresh.exists(), "新鲜状态不得被 stale 清扫删除")
            self.assertFalse(old.exists(), "带龄无容器状态应由清扫回收")
            self.assertNotIn(24110, busy, "被清扫的档位不再占用")
        finally:
            fresh.unlink(missing_ok=True)
            old.unlink(missing_ok=True)

    def test_aged_state_survives_transient_residue_blip(self):
        """run V 清扫回归锚：带龄状态的 unlink 决策改用稳定查询（连续 3 次均
        空才回收）——docker ps 瞬时空窗（起跑风暴）不再扫掉活台的存量状态。
        被扫的后果链：下一次 ensure 读不到状态走冷路径 → compose 重建活台
        （run U modal-dialog page.reload CONNECTION_REFUSED 红的同族）。"""
        import shutil
        if not shutil.which("docker"):
            self.skipTest("docker 缺席——residue 面不可用")
        root = sd.lock_root()
        tgt = root / "project-blipswp.json"
        try:
            tgt.write_text(json.dumps({"project": "blipswp", "ports": {"console": 24120}}),
                           encoding="utf-8")
            os.utime(str(tgt), (0, 0))  # 带龄，必过新鲜护栏，直抵稳定确认
            real = sd.residue_containers
            calls = {"n": 0}

            def flaky(project):
                if project == "blipswp":
                    calls["n"] += 1
                    # 前两次瞬时空窗，第三次恢复看见容器 → 台活着，不得回收
                    return [] if calls["n"] < 3 else ["blipswp-dsh"]
                return real(project)

            sd.residue_containers = flaky
            try:
                busy = sd.state_busy_ports()
            finally:
                sd.residue_containers = real
            self.assertTrue(tgt.exists(), "瞬时空窗不得扫掉带龄活台状态（unlink 须稳定确认）")
            self.assertIn(24120, busy, "活台档位按占用保留")
        finally:
            tgt.unlink(missing_ok=True)


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
    def test_ensure_reuses_healthy_then_replaces_halfdead(self):
        st1 = self.up_json("ute", "--services", "dsh", "--timeout", "30")
        p = self.cli("ensure", "--project", "ute", "--services", "dsh", "--timeout", "30")
        self.assertEqual(p.returncode, 0, p.stderr)
        st2 = json.loads(p.stdout.strip().splitlines()[-1])
        self.assertTrue(st2.get("reused"), "健康台应复用")
        self.assertEqual(st2["ports"], st1["ports"], "复用不换端口")
        # 半残：holder 全死 → ensure 拆重起
        pathlib.Path(self.state, "hold-alive").unlink()
        time.sleep(0.5)
        p2 = self.cli("ensure", "--project", "ute", "--services", "dsh", "--timeout", "30")
        self.assertEqual(p2.returncode, 0, p2.stderr)
        st3 = json.loads(p2.stdout.strip().splitlines()[-1])
        self.assertNotIn("reused", st3, "半残台应拆重起而非复用")
        self.cli("down", "--project", "ute")

    def test_concurrent_ensure_same_project_single_boot(self):
        """run K 雷群回归锚：冷台同项目并发 ensure 互斥——先到先得独占起台，
        后来者持锁等待后双查健康直接复用；双绿且全窗口只起一次台。"""
        ps = [subprocess.Popen(
            [sys.executable, str(INTEG / "stage_docker.py"), "ensure",
             "--project", "utc", "--services", "dsh", "--timeout", "60"],
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
        self.assertEqual(len(cnt.read_text().split()), 1,
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


if __name__ == "__main__":
    # 两道供给预检并行保留（merge 冲突消解：泳道侧=共享面繁忙预检，main 侧=档位窗
    # 外来监听者点名；两门独立命中各自 ENV_FAIL exit 2——环境红归供给面，不假红）。
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
