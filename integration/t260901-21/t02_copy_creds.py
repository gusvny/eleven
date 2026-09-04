"""t260901-21 t02 —— 凭据拷贝行为（agent_activities._copy_creds）。

覆盖：per-key 拷贝字节等值 / legacy 回落 / null 不拷 / 目标已存在按 refs 叶子
合并刷新（KI-016，t260902-09 起取代旧「整段不覆盖」契约；同名叶子 dst 值胜出
的守卫意图保留）/ 不可读文件 fail-closed 报错含源路径 / 拷贝保留源 mode（0600）。
全 tmp/env 桩，不读真 ~/.sandbar。退出码 0=绿。合并用例依赖 PyYAML
（temporal-poc venv；manifest 用 venv 回落链跑），缺失时该用例干净 SKIP。
"""
import logging
import os
import sys
import tempfile
import types
from pathlib import Path

try:
    import yaml
except ImportError:  # 裸 python3：合并用例 SKIP，拷贝类用例照跑
    yaml = None

HAVE_YAML = yaml is not None


_tmod = types.ModuleType("temporalio")
_amod = types.ModuleType("temporalio.activity")


class _ActivityStub:
    logger = logging.getLogger("temporalio-stub")

    def defn(self, fn=None, **kw):
        return (lambda f: f) if fn is None else fn

    def heartbeat(self, *a, **kw):
        pass


_amod.activity = _ActivityStub()
_tmod.activity = _ActivityStub()
sys.modules.setdefault("temporalio", _tmod)
sys.modules.setdefault("temporalio.activity", _amod)

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "server" / "dsh" / "temporal-poc"))
import agent_activities as aa  # noqa: E402

FAILS = []
CRED = "version: 1\nrefs:\n  DEEPSEEK_API_KEY: sk-test\n"
# 合并用例夹具（真实嵌套格式，同 ~/.dsh/.credentials.yaml）
CRED_STAGED = ("version: 1\nrefs:\n"
               "  DEEPSEEK_API_KEY: sk-dst\n"
               "  KIMI_CODING_API_KEY: sk-kimi-dst\n")
CRED_SRC_NEW = ("version: 2\nrefs:\n"
                "  DEEPSEEK_API_KEY: sk-src\n"
                "  ZAI_CODING_CN_API_KEY: sk-zai-cn\n")


def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + ((" | " + str(detail)) if detail and not cond else ""))
    if not cond:
        FAILS.append(name)


class Env:
    def __init__(self):
        self.tmp = tempfile.mkdtemp(prefix="t260901-21-t02-")
        self.root = os.path.join(self.tmp, "projects")
        self.dsh = os.path.join(self.tmp, "dsh")
        self.home = os.path.join(self.tmp, "home")
        self.dst = Path(self.tmp) / "ws" / ".dsh"
        os.makedirs(self.root, exist_ok=True)
        os.makedirs(self.dsh, exist_ok=True)
        os.makedirs(self.dst, exist_ok=True)
        self._save = {}

    def __enter__(self):
        for k, v in [("SANDBAR_PROJECTS_DIR", self.root), ("DSH_HOME", self.dsh),
                     ("HOME", self.home)]:
            self._save[k] = os.environ.get(k)
            os.environ[k] = v
        return self

    def __exit__(self, *a):
        for k, v in self._save.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def write(self, p, content=CRED, mode=None):
        with open(p, "w") as f:
            f.write(content)
        if mode is not None:
            os.chmod(p, mode)
        return p

    def perkey(self, key="suyou", **kw):
        d = os.path.join(self.root, key)
        os.makedirs(d, exist_ok=True)
        return self.write(os.path.join(d, "credentials.yaml"), **kw)

    def legacy(self, **kw):
        return self.write(os.path.join(self.dsh, ".credentials.yaml"), **kw)


def main():
    # 1. per-key 命中：内容字节等值落到 dst
    with Env() as e:
        pk = e.perkey(mode=0o600)
        aa._copy_creds(e.dst, "suyou")
        out = e.dst / ".credentials.yaml"
        check("per-key 拷贝落位", out.is_file())
        check("per-key 字节等值", out.read_text() == CRED)
        check("mode 0600 保留", stat_mode(out) == 0o600, oct(stat_mode(out)))

    # 2. legacy 回落拷贝
    with Env() as e:
        lg = e.legacy()
        aa._copy_creds(e.dst, "suyou")
        check("legacy 回落拷贝", (e.dst / ".credentials.yaml").read_text() == CRED)

    # 3. 两处皆无 → 不拷贝不报错（MISSING_CREDENTIAL 口径由引擎报，读侧静默跳过）
    with Env() as e:
        aa._copy_creds(e.dst, "suyou")
        check("无源不拷", not (e.dst / ".credentials.yaml").exists())

    # 4. 目标已存在 → refs 叶子级合并刷新（KI-016，t260902-09 起的新契约，取代
    #    旧「整段不覆盖」）：源新增叶子追加；同名叶子 dst 值胜出（守卫意图保留：
    #    不抹工单中途换 key 现场）；version 等 seam 自管字段不动；源未被改写。
    #    需 PyYAML（合并路径软依赖，t260902-09 plan.md）；缺失时干净 SKIP。
    if not HAVE_YAML:
        print("skip 目标已存在合并刷新（PyYAML 不可用，见 t260902-09 plan.md）")
    else:
        with Env() as e:
            pk = e.perkey(content=CRED_SRC_NEW)
            e.write(str(e.dst / ".credentials.yaml"), CRED_STAGED)
            aa._copy_creds(e.dst, "suyou")
            text = (e.dst / ".credentials.yaml").read_text()
            data = yaml.safe_load(text) or {}
            refs = data.get("refs") or {}
            check("已存在快照：源新增叶子追加",
                  refs.get("ZAI_CODING_CN_API_KEY") == "sk-zai-cn", text)
            check("已存在快照：同名叶子 dst 值胜出",
                  refs.get("DEEPSEEK_API_KEY") == "sk-dst")
            check("已存在快照：dst 独有叶子保留",
                  refs.get("KIMI_CODING_API_KEY") == "sk-kimi-dst")
            check("已存在快照：version 不动", data.get("version") == 1)
            check("源未被改写", Path(pk).read_text() == CRED_SRC_NEW)

    # 5. 不可读文件 → fail-closed，报错含源路径（root 下跑不掉权限限制；非 root 专用）
    if os.geteuid() != 0:
        with Env() as e:
            pk = e.perkey(mode=0o000)
            try:
                aa._copy_creds(e.dst, "suyou")
                check("不可读 fail-closed", False, "未抛错")
            except RuntimeError as err:
                check("不可读 fail-closed", str(pk) in str(err), err)
            finally:
                os.chmod(pk, 0o644)  # 拆桩：tmp 目录清理需要
    else:
        print("skip 不可读 fail-closed（当前 euid=0，权限不生效）")

    # 6. project_key 空 = legacy 照拷（=M1-2 前行为，R3 口径）
    with Env() as e:
        e.perkey()
        lg = e.legacy(content="legacy-content\n")
        aa._copy_creds(e.dst, "")
        check("空 key 走 legacy 照拷", (e.dst / ".credentials.yaml").read_text() == "legacy-content\n")

    print()
    if FAILS:
        print(f"FAILED: {len(FAILS)} -> {FAILS}")
        return 1
    print("t02 all green")
    return 0


def stat_mode(p):
    return os.stat(p).st_mode & 0o777


if __name__ == "__main__":
    sys.exit(main())
