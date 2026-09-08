"""t260901-21 t01 —— 凭据拷贝源解析纯函数（agent_activities._resolve_credentials_source）。

全 tmp/env 桩：SANDBAR_PROJECTS_DIR、DSH_HOME、HOME 全部指向临时目录，不读真 ~/.sandbar。
覆盖：per-key 命中优先 / legacy 两级回落 / 两处皆无=null / 畸形输入（env 空串、相对
路径、穿越 key、目录冒充文件）。退出码 0=绿。
"""
import logging
import os
import sys
import tempfile
import types
from pathlib import Path

# temporalio 桩：agent_activities 模块级 `from temporalio import activity` + 各处
# @activity.defn / activity.logger —— 本单只测凭据解析纯函数，不进 Temporal 运行时
# （测试环境不装 temporalio；t260901-14 同因走 tmp 桩路线）。只挡模块级依赖，
# 不碰被测函数语义。
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

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "server" / "engine"))
import agent_activities as aa  # noqa: E402

FAILS = []


def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + (" | " + detail if detail and not cond else ""))
    if not cond:
        FAILS.append(name)


class Env:
    """tmp env 桩：with 块内 SANDBAR_PROJECTS_DIR/DSH_HOME/HOME 指向临时目录。"""

    def __init__(self):
        self.tmp = tempfile.mkdtemp(prefix="t260901-21-t01-")
        self.root = os.path.join(self.tmp, "projects")
        self.dsh = os.path.join(self.tmp, "dsh")
        self.home = os.path.join(self.tmp, "home")
        for d in (self.root, self.dsh, self.home):
            os.makedirs(d, exist_ok=True)
        self._save = {}

    def __enter__(self):
        for k, v in [("SANDBAR_PROJECTS_DIR", self.root), ("DSH_HOME", self.dsh), ("HOME", self.home)]:
            self._save[k] = os.environ.get(k)
            os.environ[k] = v
        return self

    def __exit__(self, *a):
        for k, v in self._save.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def perkey(self, key, content="version: 1\nrefs:\n  K: v\n"):
        d = os.path.join(self.root, key)
        os.makedirs(d, exist_ok=True)
        p = os.path.join(d, "credentials.yaml")
        with open(p, "w") as f:
            f.write(content)
        return p

    def legacy_dsh(self, content="version: 1\nrefs:\n  LEGACY: v\n"):
        p = os.path.join(self.dsh, ".credentials.yaml")
        with open(p, "w") as f:
            f.write(content)
        return p

    def legacy_home(self, content="version: 1\nrefs:\n  H: v\n"):
        p = os.path.join(self.home, ".dsh", ".credentials.yaml")
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w") as f:
            f.write(content)
        return p


def main():
    # 1. per-key 命中优先：两边都有 → 取 per-key
    with Env() as e:
        pk = e.perkey("suyou")
        lg = e.legacy_dsh()
        got = aa._resolve_credentials_source("suyou")
        check("per-key 优先", got == Path(pk), f"got={got}")
        check("per-key 路径正确", str(got) == pk)

    # 2. per-key 缺失 → 回落 DSH_HOME
    with Env() as e:
        lg = e.legacy_dsh()
        got = aa._resolve_credentials_source("suyou")
        check("回落 DSH_HOME legacy", got == Path(lg), f"got={got}")
        check("回落命中非 per-key", not aa._perkey_is_hit("suyou", got))

    # 3. DSH_HOME 无 → 回落 $HOME/.dsh
    with Env() as e:
        lg = e.legacy_home()
        got = aa._resolve_credentials_source("suyou")
        check("回落 HOME/.dsh legacy", got == Path(lg), f"got={got}")

    # 4. DSH_HOME 优先于 $HOME/.dsh
    with Env() as e:
        e.legacy_home()
        lg = e.legacy_dsh()
        check("DSH_HOME 先于 HOME", aa._resolve_credentials_source("suyou") == Path(lg))

    # 5. 两处皆无 → None
    with Env() as e:
        check("两处皆无=None", aa._resolve_credentials_source("suyou") is None)

    # 6. project_key 空/未知 → 跳过 per-key 首查，仍走 legacy（=M1-2 前行为）
    with Env() as e:
        e.perkey("suyou")
        lg = e.legacy_dsh()
        for key in ["", "other-proj"]:
            check(f"key={key or '空'} 仍走 legacy", aa._resolve_credentials_source(key) == Path(lg))

    # 7. 畸形输入：穿越/非法 key 一律拒（不拼出越界路径）
    with Env() as e:
        e.perkey("suyou")
        lg = e.legacy_dsh()
        for bad in ["../etc", "a/b", "..", ".hidden", "UPPER", "x" * 50, "suyou/../../x"]:
            got = aa._resolve_credentials_source(bad)
            check(f"非法 key 拒绝：{bad}", got == Path(lg), f"got={got}")

    # 8. per-key 位置是目录而非文件 → 不算命中，继续回落
    with Env() as e:
        os.makedirs(os.path.join(e.root, "suyou", "credentials.yaml"), exist_ok=True)
        lg = e.legacy_dsh()
        check("目录冒充文件→回落", aa._resolve_credentials_source("suyou") == Path(lg))

    # 9. SANDBAR_PROJECTS_DIR 空串/相对路径 = 视为未设置（与 TS 侧声明差异）：
    #    默认根（真 home 下）无凭据 → 落 legacy，而不是炸在相对路径上
    with Env() as e:
        lg = e.legacy_dsh()
        os.environ["SANDBAR_PROJECTS_DIR"] = ""
        got = aa._resolve_credentials_source("suyou")
        check("env 空串视为未设置", got == Path(lg))
        os.environ["SANDBAR_PROJECTS_DIR"] = "relative/path"
        got = aa._resolve_credentials_source("suyou")
        check("env 相对路径视为未设置", got == Path(lg))

    # 10. per-key 命中时 _perkey_is_hit 为真（迁移提示日志判定的镜像面）
    with Env() as e:
        pk = e.perkey("suyou")
        check("perkey_is_hit 命中", aa._perkey_is_hit("suyou", Path(pk)))
        check("perkey_is_hit 空 key", not aa._perkey_is_hit("", Path(pk)))

    # 11. 畸形内容不预解析：内容随便写也照常返回路径（解析交 dsh seam）
    with Env() as e:
        pk = e.perkey("suyou", content="{not yaml at all!!!")
        check("畸形内容不预解析", aa._resolve_credentials_source("suyou") == Path(pk))

    print()
    if FAILS:
        print(f"FAILED: {len(FAILS)} -> {FAILS}")
        return 1
    print("t01 all green")
    return 0


if __name__ == "__main__":
    sys.exit(main())
