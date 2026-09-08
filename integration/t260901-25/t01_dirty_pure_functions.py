#!/usr/bin/env python3
"""t01_dirty_pure_functions.py —— KI-009 自愈纯函数黑盒（t260901-25）。

用户故事：agent 交付后迟写文件把泳道弄脏，merge_check 在红灯前要先判断
「脏是否全在工单写集内」才决定自愈补落盘。这个判断是自愈的唯一闸门：
误放行 = 把越界改动偷偷 commit 进泳道；误拒绝 = 工单又被逼回人工 commit 死路。

黑盒手法：ast 抽取 agent_activities.py 真源里的纯函数（不 import 模块——
该文件依赖 temporalio，worktree 无此环境，见 selfcheck_write_lifecycle 头注），
exec 进沙箱命名空间直测。测的是真源代码，不是复制品。

覆盖（方案 v2 测试节 1 + review gen1 实施期意见 1）：
  A. _dirty_files_from_status_z：普通行 / rename 两字段取 new / 空格与非 ASCII
     路径 / 截断容错不抛。
  B. _dirty_within_write_set：写集内放行 / 写集外拒 / 目录前缀（条目以 / 结尾）
     / 文件条目相等 / 同前缀负例（x.py 在写集、x.py.bak 拒）/ 空写集拒 /
     条目非串拒 / ? 哨兵拒 / 绝对路径与 .. 拒。

直跑：python3 integration/t260901-25/t01_dirty_pure_functions.py
末行 SUMMARY pass=<n> fail=<k>；fail>0 exit 1。
"""
import ast
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
SRC = REPO / "server" / "engine" / "agent_activities.py"

PASS = 0
FAIL = 0


def ok(cond, label):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  ok  %s" % label)
    else:
        FAIL += 1
        print("  FAIL %s" % label)


def extract_fn(name):
    """ast 抽取真源函数定义，返回可在沙箱命名空间 exec 的代码对象。"""
    tree = ast.parse(SRC.read_text("utf-8"))
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return compile(ast.Module(body=[node], type_ignores=[]), name, "exec")
    return None


NS_BASE = {"List": List, "Dict": Dict, "Any": Any, "Optional": Optional}


def load(name):
    code = extract_fn(name)
    ns = dict(NS_BASE)
    if code is None:
        return None
    exec(code, ns)
    return ns[name]


def main():
    print("== 前置：真源纯函数在位（implement 未交付则红，属预期） ==")
    parse_z = load("_dirty_files_from_status_z")
    within = load("_dirty_within_write_set")
    ok(parse_z is not None, "_dirty_files_from_status_z 已在 agent_activities.py 定义")
    ok(within is not None, "_dirty_within_write_set 已在 agent_activities.py 定义")
    if parse_z is None or within is None:
        print("SUMMARY pass=%d fail=%d" % (PASS, FAIL))
        return 1

    print("== A. _dirty_files_from_status_z（-z 规范解析） ==")
    # A1 普通行：XY 两状态字符 + 空格 + 路径，NUL 分隔
    files = parse_z("M  server/a.py\x00?? integration/new.py\x00")
    ok(isinstance(files, list) and "server/a.py" in files
       and "integration/new.py" in files, "普通行路径抽取: %r" % (files,))
    # A2 rename 两字段：-z 形态为 XY new<NUL>old<NUL>（取 new 判写集）
    files = parse_z('R  server/renamed.py\x00server/old.py\x00')
    ok("server/renamed.py" in files and "server/old.py" not in files,
       "rename 条目取新路径: %r" % (files,))
    # A3 空格与非 ASCII 路径（-z 无引号形态，原文直达）
    files = parse_z("M  server/我的 文件.py\x00")
    ok(files == ["server/我的 文件.py"], "空格/非 ASCII 路径不引号不转义: %r" % (files,))
    # A4 截断（尾缺 NUL）容错不抛
    try:
        files = parse_z("M  server/truncated.py")
        ok(isinstance(files, list), "截断输入容错不抛: %r" % (files,))
    except Exception as e:
        ok(False, "截断输入不应抛异常: %r" % e)
    # A5 空输入
    try:
        ok(parse_z("") == [], "空输入回空清单")
    except Exception as e:
        ok(False, "空输入不应抛异常: %r" % e)

    print("== B. _dirty_within_write_set（自愈闸门 fail-closed） ==")
    ws = ["server/engine/dev_lane.py",
          "server/engine/agent_activities.py",
          "integration/"]
    ok(within(["server/engine/dev_lane.py"], ws) is True, "写集内文件放行")
    ok(within(["integration/t260901-25/t01.py"], ws) is True, "目录前缀条目（integration/）放行")
    ok(within(["server/other/x.py"], ws) is not True, "写集外拒")
    # 同前缀负例（review gen1 意见 1）：文件条目不得用裸 startswith 放行兄弟路径
    ok(within(["server/engine/dev_lane.py.bak"], ws) is not True,
       "同前缀负例 dev_lane.py.bak 拒（防裸 startswith 误放行）")
    # 畸形三态 fail-closed
    ok(within([], []) is not True, "脏清单空 + 空写集：不放行（无自愈对象）")
    ok(within(["server/a.py"], []) is not True, "空写集拒")
    ok(within(["server/a.py"], [None, 3]) is not True, "write_set 条目非串拒")
    ok(within(["?"], ws) is not True, "? 哨兵（git status 失败）拒")
    ok(within(["/etc/passwd"], ws) is not True, "绝对路径拒")
    ok(within(["../escape.py"], ws) is not True, ".. 逃逸路径拒")
    ok(within(["server/a.py", None], ws) is not True, "脏清单混入非串拒")
    # 全空容忍口径：脏为空 + 写集正常 → 无自愈对象，应拒绝（无谓 settle）
    ok(within([], ws) is not True, "脏清单为空不放行（no-op 交既有幂等路径）")

    print("SUMMARY pass=%d fail=%d" % (PASS, FAIL))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
