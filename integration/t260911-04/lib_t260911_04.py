#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""t260911-04 集成场景共享夹具（无 sc_ 前缀=共享代码，不进 SCENARIOS）。

服务本票全链多仓旅程场景：行式断言三态契约、git 帮手、混合形态夹具项目、
轮询等待。形态对齐 t260907-06/lib_t260907_06.py 与 t260910-08（桩脑全链手法）。

环境三态契约：fail>0→exit 1（产品红）；env_fail>0→exit 2（环境红，可辨于被测红）；
否则 0。夹具红线：假多仓项目只在测试 tmp 目录自建，不碰真实项目数据。
"""
import json
import subprocess
import time
from pathlib import Path

passed = 0
failed = 0
env_fail_n = 0


def check(name, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
        print("ok    " + name, flush=True)
    else:
        failed += 1
        print("FAIL  " + name + (("：" + detail) if detail else ""), flush=True)


def env_fail(reason):
    global env_fail_n
    env_fail_n += 1
    print("ENV_FAIL " + reason, flush=True)


def summary():
    """套件输出约定（三态 §7.3）。"""
    print("SUMMARY pass=%d fail=%d env_fail=%d na=0" % (passed, failed, env_fail_n))
    if failed > 0:
        return 1
    if env_fail_n > 0:
        return 2
    return 0


def git(*args, cwd):
    p = subprocess.run(["git", "-c", "core.quotepath=false"] + list(args), cwd=str(cwd),
                       capture_output=True, text=True)
    if p.returncode != 0:
        raise AssertionError("git %s 失败 rc=%s: stderr=%r stdout=%r"
                             % (" ".join(args), p.returncode,
                                (p.stderr or "")[-300:], (p.stdout or "")[-300:]))
    return p.stdout


def git_ok(*args, cwd):
    """不抛版 git：返回 (rc, stdout, stderr)。"""
    p = subprocess.run(["git", "-c", "core.quotepath=false"] + list(args), cwd=str(cwd),
                       capture_output=True, text=True)
    return p.returncode, p.stdout, p.stderr


def wait_until(fn, deadline_s, interval=2.0):
    """轮询至 fn() 为真或超时（返回最后一次 fn() 值；fn 抛错视为未就绪）。"""
    t0 = time.time()
    while time.time() - t0 < deadline_s:
        try:
            if fn():
                return True
        except Exception:
            pass
        time.sleep(interval)
    try:
        return bool(fn())
    except Exception:
        return False


def main_count(repo):
    """main 分支提交计数（逐仓独立，终态比对基线）。"""
    return int(git("rev-list", "--count", "main", cwd=repo).strip())


def show_json(meta):
    """show 读面整体序列化（红灯文案咬合断言的搜索面）。"""
    try:
        return json.dumps(meta, ensure_ascii=False, default=str)
    except Exception:
        return str(meta)


def init_repo(path, rel_file, content="base\n"):
    """最小 git 仓夹具：init -b main + 单文件基线提交。"""
    path = Path(path)
    path.mkdir(parents=True, exist_ok=True)
    git("init", "-b", "main", cwd=path)
    git("config", "user.email", "ut@example.com", cwd=path)
    git("config", "user.name", "ut", cwd=path)
    f = path / rel_file
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(content, encoding="utf-8")
    git("add", "-A", cwd=path)
    git("commit", "-m", "base", cwd=path)
    return path


def build_mixed_project(base, name="mixed"):
    """混合形态夹具（dengzhufpv 缺陷现场同款）：根亦 git 仓 + repo_a/repo_b 子仓
    （.gitignore 忽略子仓）。写集命中根+repo_a，repo_b=不串仓对照面。"""
    root = Path(base) / name
    root.mkdir(parents=True, exist_ok=True)
    init_repo(root, "docs/root.md")
    # .suyou/.sandbar 一并忽略（naming-compat：.suyou=清单镜像旧名，产品路径）：引擎泳道元数据目录落在根树（清单/预置回执）内，
    # 不忽略=merge_check「工作区干净」把产品自产元数据计为越界脏文件（见结果文件
    # 缺陷上报：该判据未排除产品自有元数据目录，真仓靠 .gitignore 巧合盖住）
    (root / ".gitignore").write_text(
        # naming-compat：.suyou/=旧名清单镜像目录（引擎读侧回落面），fixture 照造
        "repo_a/\nrepo_b/\n.suyou/\n.sandbar/\n.dsh/\n", encoding="utf-8")  # naming-compat：.suyou/=旧名清单镜像目录
    git("add", "-A", cwd=root)
    git("commit", "-m", "gitignore", cwd=root)
    init_repo(root / "repo_a", "src/a.py")
    init_repo(root / "repo_b", "lib/b.py")
    return root
