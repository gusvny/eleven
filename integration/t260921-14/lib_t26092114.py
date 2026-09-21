#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""t260921-14 集成场景共享夹具（ro 池，离线秒级：零真 docker、零 Temporal server、
零真全局 dsh 依赖）。

被测契约（方案 v2 §2/§3，票面 t260921-14）：
- paths.dsh_bin 声明键（契约 ①d 同族）：未声明=裸 dsh 现状逐字（回归锚）；声明=
  只钉二进制、参数保持文档化缺省逐元素；SANDBAR_AGENT_CMD 与声明并存=env 胜+
  遮蔽点名；声明面缺陷（缺失/非文件/不可执行）=fail-closed 红（developer L1 主
  覆盖，集成层不复刻词法矩阵）。
- face↔spawn 同源（方案 C1）：票面 dsh_pin_<tag>.json 与 prepare 产出的 cmd 出自
  同一次解析（KI-058「机器层安装态≠代码态」的观测解药）。
- 三面版本自检（交付③）：宿主全局 / 引擎面 / 容器面；divergent 逐对点名、
  consistent 不告警、incomplete 点名判不了的面；探针失败不挡 spawn。
- 回退（交付④）：删/注释 dsh_bin 声明行=引擎层一行回退；SANDBAR_AGENT_IMAGE 指回
  旧 tag=镜像回退；ROLLBACK.md 文档守卫。

夹具纪律：一切写面落 /tmp（SANDBAR_PROJECTS_DIR 临时注册表、DSH_HOME 指 空 home、
stub 与 fake docker 全 tmp）——绝不写真 ~/.sandbar/projects、真 ~/.dsh，不连真
docker。桩版本 token 全部版本样（semver+预发布段口径），宿主全局 dsh 缺席不影响
判定（三面里的宿主面由 PATH 注入桩承载）。驱动缝=直调 _prepare_agent_spawn（引擎
spawn 预备单点，t260902-09 sc_it01 同款先例），「被真调」用桩账本在进程级自证。
"""
import contextlib
import json
import logging
import os
import shlex
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
ENGINE = REPO / "server" / "engine"
INTEG = REPO / "integration"

# 回退面的文档化锚（票面交付④/方案 §3 Step7；字面即语义，专供文档守卫用）
OLD_IMAGE_TAG = "sandbar-agent:dsh-0.1.1-rc.2-s1"
OLD_IMAGE_VERSION = "0.1.1-rc.2"

# 本夹具族的桩/桩账本 env 注入口（子进程桩经它回写调用账本）
STUB_LEDGER_ENV = "T26092114_STUB_LEDGER"
FAKE_DOCKER_STATE_ENV = "T26092114_FAKE_DOCKER_STATE"


def import_engine():
    """导入引擎模块面（cwd 无关，从本文件位置反推仓库根）。导入失败=环境缺依赖
    （缺 temporalio 等）→ ENV_FAIL exit 2 点名修复路径，绝不静默当绿。"""
    for p in (str(INTEG), str(ENGINE)):
        if p not in sys.path:
            sys.path.insert(0, p)
    try:
        import agent_activities as aa
        import agent_runtime as ar
        import dsh_pin as dp
        import shared as sb
        return aa, ar, dp, sb
    except Exception as e:  # ImportError 及导入链上任何环境缺依赖
        import lib_env
        lib_env.env_fail(
            "引擎模块不可导入（%s）；用 server/engine/.venv/bin/python 跑本场景，"
            "或先补齐引擎依赖" % e)


class Checker:
    """子用例级三态记账：pass/fail/env_fail/na + SUMMARY 行 + 退出码优先级
    （fail > env_fail > pass；全部子用例 N/A=产品红 exit 1——lib_env 契约同款）。
    res=True 时逐条判定额外打 RES 协议行（子进程子用例回传父进程聚合用；
    值内 tab/换行拍平防串列）。"""

    def __init__(self, title, res=False):
        self.title = title
        self.res = res
        self.rows = []  # (state, name, detail)

    def _emit_res(self, state, name, detail):
        if not self.res:
            return
        flat = lambda s: str(s).replace("\t", " ").replace("\n", " ⏎ ")  # noqa: E731
        print("RES\t%s\t%s\t%s" % (state, flat(name), flat(detail)), flush=True)

    def ok(self, name, detail=""):
        self.rows.append(("pass", name, detail))
        self._emit_res("pass", name, detail)
        print("pass  %s %s" % (name, detail), flush=True)

    def fail(self, name, detail=""):
        self.rows.append(("fail", name, detail))
        self._emit_res("fail", name, detail)
        print("FAIL  %s %s" % (name, detail), flush=True)

    def env_fail_leg(self, name, detail=""):
        self.rows.append(("env_fail", name, detail))
        self._emit_res("env_fail", name, detail)
        print("ENV_FAIL %s %s" % (name, detail), flush=True)

    def na(self, name, detail=""):
        self.rows.append(("na", name, detail))
        self._emit_res("na", name, detail)
        print("N/A  %s %s" % (name, detail), flush=True)

    def check(self, cond, name, detail=""):
        """cond 为真=pass，假=fail（detail 建议带实得值，报错与事实同向）。"""
        if cond:
            self.ok(name)
        else:
            self.fail(name, detail)
        return bool(cond)

    def finish(self, silent=False):
        n_fail = sum(1 for r in self.rows if r[0] == "fail")
        n_env = sum(1 for r in self.rows if r[0] == "env_fail")
        n_na = sum(1 for r in self.rows if r[0] == "na")
        n_pass = sum(1 for r in self.rows if r[0] == "pass")
        if not silent:
            print("SUMMARY pass=%d fail=%d env_fail=%d na=%d"
                  % (n_pass, n_fail, n_env, n_na))
        if n_fail:
            return 1
        if n_env:
            return 2
        if self.rows and n_na >= len(self.rows):
            if not silent:
                print("FAIL: 全部子用例 N/A——场景无可验对象（设计/覆盖问题，修场景而非补环境）")
            return 1
        return 0


def tmp_root(tag):
    return Path(tempfile.mkdtemp(prefix="t26092114-%s-" % tag))


# ---- env 卫生 ----------------------------------------------------------------

_ENV_KNOBS = (
    "SANDBAR_AGENT_CMD", "SANDBAR_AGENT_RUNTIME", "SANDBAR_AGENT_IMAGE",
    "SANDBAR_DOCKER_BIN", "SANDBAR_DSH_EXPECTED_VERSION", "SANDBAR_DSH_STRICT",
    "SANDBAR_AGENT_RESUME", STUB_LEDGER_ENV, FAKE_DOCKER_STATE_ENV,
)


class EnvSandbox:
    """子用例级 env 隔离：进子用例=清旋钮+指临时注册表+DSH_HOME 指空 home（拷贝源走
    「响亮跳过」支，与真机 ~/.dsh 状态解耦），按子用例覆盖 extra；出子用例=逐字节还原。
    绝不让夹具读/写真机注册表与真 dsh home。"""

    def __init__(self, registry_dir, extra=None):
        self._snap = dict(os.environ)
        self._extra = dict(extra or {})
        self.registry_dir = str(registry_dir)
        self.home = None

    def __enter__(self):
        os.environ["SANDBAR_PROJECTS_DIR"] = self.registry_dir
        self.home = tempfile.mkdtemp(prefix="t26092114-empty-home-")
        os.environ["DSH_HOME"] = self.home
        for k in _ENV_KNOBS:
            os.environ.pop(k, None)
        for k, v in self._extra.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = str(v)
        return self

    def __exit__(self, *exc):
        os.environ.clear()
        os.environ.update(self._snap)
        return False


# ---- 桩工厂 ------------------------------------------------------------------

_STUB_SRC = (
    "#!/usr/bin/env python3\n"
    "import json, os, sys\n"
    "led = os.environ.get(%r, \"\")\n"
    "if led:\n"
    "    with open(led, \"a\") as f:\n"
    "        f.write(json.dumps(sys.argv[1:]) + \"\\n\")\n"
    "if \"--version\" in sys.argv[1:]:\n"
    "    print(%r)\n"
    "sys.exit(0)\n"
) % (STUB_LEDGER_ENV, "%s")


def make_stub(bin_dir, version, name="dsh_stub_t26092114.py"):
    """自执行版本桩：任何调用记 argv 进账本（T26092114_STUB_LEDGER env 指路），
    `--version` 打自报版本（版本样 token）。返回 (桩绝对路径, 账本路径)。"""
    bin_dir = Path(bin_dir)
    bin_dir.mkdir(parents=True, exist_ok=True)
    stub = bin_dir / name
    ledger = bin_dir / (name + ".calls.jsonl")
    stub.write_text(_STUB_SRC % version, "utf-8")
    os.chmod(stub, 0o755)
    return stub, ledger


def make_host_path_stub(bin_dir, version):
    """宿主全局面桩：basename 恰为 `dsh`（PATH 注入后 shutil.which("dsh") 命中），
    供三面自检的 host_global 面离线定版。"""
    return make_stub(bin_dir, version, name="dsh")


# ---- 临时注册表（契约 ①d 条目格式，真源形状=per-key project.yaml） -----------

def make_registry(registry_dir, key, dsh_bin=None):
    """建 <registry>/<key>/project.yaml（key 与目录名全等；schema v1+project.dirs+
    可选 paths.dsh_bin）。返回条目路径；改写用 rewrite_dsh_bin/comment_dsh_bin。"""
    registry_dir = Path(registry_dir)
    key_dir = registry_dir / key
    key_dir.mkdir(parents=True, exist_ok=True)
    (key_dir / "repo").mkdir(parents=True, exist_ok=True)
    lines = [
        "schema: v1",
        "project:",
        "  - key: %s" % key,
        "    name: %s" % key,
        "    dirs:",
        "      - %s" % (key_dir / "repo"),
    ]
    if dsh_bin is not None:
        lines += ["paths:", "  dsh_bin: %s" % dsh_bin]
    entry = key_dir / "project.yaml"
    entry.write_text("\n".join(lines) + "\n", "utf-8")
    return entry


def rewrite_dsh_bin(entry, dsh_bin=None):
    """原位改写条目的 paths.dsh_bin 行（None=整行删除；其余=重写该行）。
    只动 dsh_bin 键，条目其余字节保持（A/B/A 对比的「配置改回一行」语义）。"""
    entry = Path(entry)
    out = []
    for line in entry.read_text("utf-8").splitlines():
        if line.strip().startswith("dsh_bin:"):
            continue
        if line.strip() == "paths:":
            continue  # paths 节头随行重建，防留空节
        out.append(line)
    if dsh_bin is not None:
        out += ["paths:", "  dsh_bin: %s" % dsh_bin]
    entry.write_text("\n".join(out) + "\n", "utf-8")
    return entry


def comment_dsh_bin(entry):
    """把 dsh_bin 行变注释（回退的注释形态；解析口径=声明缺席）。"""
    entry = Path(entry)
    out = []
    for line in entry.read_text("utf-8").splitlines():
        if line.strip().startswith("dsh_bin:"):
            out.append("  " + "#" + line.strip())
        else:
            out.append(line)
    entry.write_text("\n".join(out) + "\n", "utf-8")
    return entry


# ---- fake docker（三面自检的容器面桩；版本输出可定版，可注入恒败） -----------

def make_fake_docker(bin_dir, state_dir):
    """假 docker CLI：`run --rm --name X <image> dsh --version` 打 state 里
    ctr-version 文件内容（容器面版本可定版）；run-fails 标记在=恒败（incomplete
    子用例用）；rm -f 幂等成功。argv 全量落 argv.log（调用形状可查）。
    state 目录路径烙进脚本正文——探针子进程不透传本夹具的 env（实测），不依赖。"""
    bin_dir = Path(bin_dir)
    state_dir = Path(state_dir)
    bin_dir.mkdir(parents=True, exist_ok=True)
    state_dir.mkdir(parents=True, exist_ok=True)
    script = bin_dir / "fake-docker"
    script.write_text(
        "#!/usr/bin/env python3\n"
        "import json, os, sys\n"
        "state = %r\n"
        "def sf(n): return os.path.join(state, n)\n"
        "def has(n): return os.path.exists(sf(n))\n"
        "with open(sf(\"argv.log\"), \"a\") as f:\n"
        "    f.write(json.dumps(sys.argv[1:]) + \"\\n\")\n"
        "a = sys.argv[1:]\n"
        "if a[:1] == [\"run\"]:\n"
        "    if has(\"run-fails\"):\n"
        "        sys.stderr.write(\"fake docker run exploded\")\n"
        "        sys.exit(1)\n"
        "    if \"--name\" in a:\n"
        "        open(sf(\"running-\" + a[a.index(\"--name\") + 1]), \"w\").write(\"true\")\n"
        "    print(open(sf(\"ctr-version\")).read().strip())\n"
        "    sys.exit(0)\n"
        "sys.exit(0)\n" % str(state_dir),
        "utf-8")
    os.chmod(script, 0o755)
    return script, state_dir


def fake_docker_state(state_dir, ctr_version=None, run_fails=False):
    state_dir = Path(state_dir)
    state_dir.mkdir(parents=True, exist_ok=True)
    if ctr_version is not None:
        (state_dir / "ctr-version").write_text(ctr_version + "\n", "utf-8")
    marker = state_dir / "run-fails"
    if run_fails:
        marker.write_text("1\n", "utf-8")
    elif marker.exists():
        marker.unlink()
    return state_dir


# ---- 告警捕获（锚语义：断言 WARNING 在场+关键词，不锁整句文案——KI-051） ------

class _WarnRecorder(logging.Handler):
    def __init__(self):
        super().__init__(level=logging.WARNING)
        self.texts = []

    def emit(self, record):
        try:
            self.texts.append(record.getMessage())
        except Exception:
            pass


@contextlib.contextmanager
def capture_warnings():
    """捕获进程 WARNING 级日志文本（根 logger 挂手；engine 走标准 logging 面）。"""
    rec = _WarnRecorder()
    root = logging.getLogger()
    old_level = root.level
    root.addHandler(rec)
    try:
        yield rec
    finally:
        root.removeHandler(rec)
        root.setLevel(old_level)


def warn_join(recorder):
    return "\n".join(recorder.texts)


# ---- spawn 预备单点驱动 -------------------------------------------------------

def run_prepare(aa, tmp, tag, project_key, extra_env=None):
    """直调引擎 spawn 预备单点（role=空 → 最小 cmd：解析出的 dsh 命令本体），
    返回 (cmd, 子进程 env, 票面 dsh_pin_<tag>.json 内容或 None)。注册表/空 home/
    旋钮全部经 EnvSandbox 隔离，子用例间互不串味。"""
    tmp = Path(tmp)
    cwd = tmp / ("lane-" + tag)
    cwd.mkdir(parents=True, exist_ok=True)
    artifacts = tmp / ("artifacts-" + tag)
    artifacts.mkdir(parents=True, exist_ok=True)
    with EnvSandbox(tmp / "registry", extra=extra_env):
        cmd, env = aa._prepare_agent_spawn(
            cwd, "", "design_it", "t26092114", artifacts, tag, project=project_key)
        pin = read_pin_json(artifacts, tag)
    return list(cmd), env, pin


def read_pin_json(artifacts, tag):
    """读票面版本面 JSON（dsh_pin_<tag>.json）；缺席返回 None（调用方点名缺席，
    报错附实有文件清单——报错与事实同向）。"""
    p = Path(artifacts) / ("dsh_pin_%s.json" % tag)
    if not p.is_file():
        return None
    return json.loads(p.read_text("utf-8"))


def legacy_default_cmd(dp):
    """文档化缺省命令（=旧 DSH_CMD 常量同字面；等值性另有既有 L1 等值测试守）。"""
    return shlex.split(dp.DEFAULT_DSH_CMD_TEXT)


def execute_prepared(cmd, env, timeout=60):
    """把 prepare 产出的命令行当真进程执行（桩无害自记），返回 CompletedProcess。
    「翻转变真用」的进程级证明：执行的就是被钉二进制本体。"""
    return subprocess.run(cmd, env=env, capture_output=True, text=True,
                          timeout=timeout)
