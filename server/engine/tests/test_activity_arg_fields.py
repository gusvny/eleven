"""P0 回归锁（260916 宿主授权的主干直修，事故源 31aaed3 / t260915-18 收口）。

事故：acceptance_walkthrough（AgentStageArgs）里写了 `args.worktree`，而
AgentStageArgs 唯一没有 worktree 字段——写成那一刻起，每一次走查都在活动里
AttributeError 直崩（t260916-02 卡死即此）。这类事故最阴的地方在于：静态看着
像「同族写法」，跑单测全绿，只有真的走到那一站才炸，且爆炸点离改动点很远。

本测试把这条不变量变成机器可判的：**所有 @activity.defn 活动，凡在函数体里
读了 `args.<字段>`，该字段就必须真在它第一个参数的 dataclass 里存在**。
纯 AST 静态检查，不跑 Temporal / 不起进程 / 不碰仓库。
"""
import ast
import dataclasses
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import shared  # noqa: E402

ENGINE = Path(__file__).resolve().parent.parent
SRC = ENGINE / "agent_activities.py"

# 引擎里以「第一个参数即 Temporal 活动入参 dataclass」为契约的模块。
SCANNED = [SRC]


def _dataclass_fields_by_name():
    out = {}
    for _, obj in vars(shared).items():
        if dataclasses.is_dataclass(obj) and isinstance(obj, type):
            out[obj.__name__] = {f.name for f in dataclasses.fields(obj)}
    return out


def _activities():
    """返回 [(函数名, 行号, 入参类型名, [读到的字段名→行号])]。"""
    tree = ast.parse(SRC.read_text(encoding="utf-8"))
    found = []
    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if not any("activity.defn" in ast.unparse(d) for d in node.decorator_list):
            continue
        if not node.args.args or node.args.args[0].annotation is None:
            continue
        argname = node.args.args[0].arg
        # 只认「注解就是一个裸类名」的入参（MergeArgs / AgentStageArgs …）；
        # Dict[str, Any] / Any 这类无 dataclass 契约的入参不属本锁范围。
        annast = node.args.args[0].annotation
        if not isinstance(annast, ast.Name):
            continue
        ann = annast.id
        reads = {}
        for sub in ast.walk(node):
            if (isinstance(sub, ast.Attribute)
                    and isinstance(sub.value, ast.Name) and sub.value.id == argname):
                reads.setdefault(sub.attr, sub.lineno)
        found.append((node.name, node.lineno, ann, reads))
    return found


def test_activities_are_discovered():
    """自锁：扫不到活动函数说明提取逻辑坏了，别让空集假绿。"""
    names = {n for n, _, _, _ in _activities()}
    assert "acceptance_walkthrough" in names
    assert len(names) >= 15, names


def test_every_arg_field_read_exists_on_the_dataclass():
    """核心不变量：activity 读的 args.<字段> 必须存在于入参 dataclass。

    反例即事故本体：acceptance_walkthrough(AgentStageArgs) 读 args.worktree。
    """
    fields = _dataclass_fields_by_name()
    problems = []
    for name, lineno, ann, reads in _activities():
        if ann not in fields:
            continue  # 无 dataclass 契约的入参（resolve_main_head(Any) 等）不属本锁范围
        for attr, at in sorted(reads.items()):
            if attr.startswith("_"):
                continue  # 私有钩子不是入参字段
            if attr not in fields[ann]:
                problems.append("agent_activities.py:%d %s(%s) 读 args.%s —— %s 无此字段"
                                % (at, name, ann, attr, ann))
    assert not problems, "活动入参字段越界（运行时必 AttributeError）：\n  " + "\n  ".join(problems)


def test_agent_stage_args_really_has_no_worktree():
    """钉住事故现场：AgentStageArgs 无 worktree，走查段的车道只能取 cwd。"""
    fields = _dataclass_fields_by_name()
    assert "worktree" not in fields["AgentStageArgs"]
    assert "workspace" in fields["AgentStageArgs"]
    # 而 MergeArgs 一族确实有——防止「顺手全局删字段」把这一类改错。
    assert "worktree" in fields["MergeArgs"]
