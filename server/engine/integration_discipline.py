"""developer 段集成禁跑执法的单点真源（宿主令 260921，票 t260921-04）。

声明=执法：本模块同时供两侧消费，两侧改动必须同批（票面验收④）——
- 文案侧：prompt_clause() 渲染 developer 段派活纪律（dev_lane.FLOW_BRIEF 注入
  create_plan/implement 两键），入口名单从 FORBIDDEN_ENTRIES 渲染，不手写；
- 执法侧：scan_bash_command() 执行锚定匹配器（agent_activities 的段会话扫描调用），
  判据=同一张 FORBIDDEN_ENTRIES。

判「跑」不判「读」（票面验收③防误伤）：只有执行动词（python/node/bash/sh/pytest/…、
直接执行、-m 模块形）之后的实参 basename 命中入口表才算执行；grep/cat/sed/ls 等
只读动词的参数提及、prompt 回显帧不算违规。

执法面边界（口径诚实，落字防漂移；review K1/C3 意见收口）：
- `bash/sh -c "<串>"`：引号内串按同规则**递归**判（K1 推荐路线）——
  `bash -c 'python3 integration/run_scenarios.py'` 判红；
  `bash -c 'ls integration/baselines'` 不判（递归后只读动词照样豁免）；
- `python3 -c "<代码>"`：内联代码不解析（导入式间接执行不可静态判定）——已知局限；
- `pytest <目录形>`（如 `pytest integration/`、`pytest integration/tests`）：不判——
  pytest 默认只收集 test_ 前缀文件，目录形实参 basename 不命中入口表
  （integration/tests 是集成库自身单测面）；pytest 仅在实参 basename 命中入口表时判
  （收集即 import 执行场景模块=真跑）；
- `xargs` 二段式不追——已知局限；
- heredoc 正文按行进入分段器：以注释 # 开头的提及行不判（# 非执行动词）；
- `bench.py`/`cache_probe.py`/`stage_docker.py`/`lib_*` 等集成**辅助**工具面不在执法面
  （如需收口宿主另票）。

纯函数零 IO；畸形输入（None/非串/空/引号不平衡/超长）不抛，按兜底切词照常判。
"""
import fnmatch
import re
import shlex
from typing import Any, Dict, List, Optional

# 集成执行入口规范表：(判据键, 人话名)。文案与匹配器同源（声明=执法）。
FORBIDDEN_ENTRIES = (
    ("run_scenarios.py", "integration/run_scenarios.py"),
    ("sc_*", "integration/**/sc_*.py|.mjs"),
    ("baselines", "integration/baselines/*"),
    ("with_stage.sh", "integration/with_stage.sh"),
    ("verify_lane", "verify_lane（含 admin.py call verify_lane）"),
)

# 执行动词（小写比较）：动词之后的非 flag 实参 basename 才参与入口表匹配。
EXEC_VERBS = frozenset({
    "python", "python2", "python3", "pypy", "pypy3",
    "node", "nodejs", "npx", "bun", "deno",
    "bash", "sh", "zsh", "dash", "source", ".",
    "pytest",
})
# shell 类动词：其 -c 实参=嵌套命令串，按同规则递归（K1）。
SHELL_VERBS = frozenset({"bash", "sh", "zsh", "dash"})
# 透明包装 token（跳过）：其后直至程序 token 之前的 flag/数字/VAR=… 一并跳过。
WRAPPER_TOKENS = frozenset({
    "sudo", "nohup", "env", "timeout", "time", "nice", "stdbuf", "exec",
})
_RECURSION_DEPTH_MAX = 3
_CMD_EXCERPT_MAX = 200
_SEGMENT_EXCERPT_MAX = 120
# 段分隔：&& 优先于 &（正则交替序），含 ; | 换行。
_SEGMENT_SPLIT_RE = re.compile(r"&&|\|\||[;|&\n]")
_ASSIGN_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")


def _basename(token):
    return token.rsplit("/", 1)[-1]


def _match_entry_token(token):
    """实参 token → 命中入口的判据键；None=未命中。basename 锚定（防目录形误伤）。"""
    base = _basename(token)
    if base == "run_scenarios.py":
        return "run_scenarios.py"
    if fnmatch.fnmatch(base, "sc_*.py") or fnmatch.fnmatch(base, "sc_*.mjs"):
        return "sc_*"
    if base == "with_stage.sh":
        return "with_stage.sh"
    if base in ("verify_lane", "verify_lane.py"):
        return "verify_lane"
    segs = [s for s in token.split("/") if s]
    if "baselines" in segs and base.endswith((".py", ".mjs", ".sh")):
        return "baselines"
    return None


def _match_entry_module(module):
    """-m 模块名（integration.run_scenarios 形）→ 判据键；None=未命中。"""
    tail = module.rsplit(".", 1)[-1]
    if tail == "run_scenarios":
        return "run_scenarios.py"
    if fnmatch.fnmatch(tail, "sc_*"):
        return "sc_*"
    return None


def _hit(command, entry, segment):
    return {"cmd": command[:_CMD_EXCERPT_MAX], "entry": entry,
            "segment": segment[:_SEGMENT_EXCERPT_MAX]}


def _program_index(tokens):
    """程序 token 下标：跳过前置 VAR=… 赋值与透明包装（含其 flag/数字/VAR=…）。"""
    i = 0
    n = len(tokens)
    while i < n:
        tok = tokens[i]
        if _ASSIGN_RE.match(tok):
            i += 1
            continue
        if tok.lower() in WRAPPER_TOKENS:
            i += 1
            # 包装器自身的参数（timeout 300 / nice -n 5 / env A=1 / stdbuf -oL）
            while i < n and (tokens[i].startswith("-") or tokens[i].isdigit()
                             or _ASSIGN_RE.match(tokens[i])):
                i += 1
            continue
        return i
    return None


def _scan_tokens(tokens, segment, command, depth):
    """单段 token 流 → 命中清单（纯函数）。"""
    if not tokens:
        return []
    i = _program_index(tokens)
    if i is None:
        return []
    prog = tokens[i]
    # 直接执行：程序 token 本身命中入口表（./integration/run_scenarios.py 形）。
    direct = _match_entry_token(prog)
    if direct:
        return [_hit(command, direct, segment)]
    if prog.lower() not in EXEC_VERBS:
        # 只读动词（grep/cat/sed/ls/…）与未知动词不执法——参数提及不算违规（验收③）。
        return []
    hits = []
    k = i + 1
    n = len(tokens)
    while k < n:
        arg = tokens[k]
        # shell -c 递归（K1）：下一实参即嵌套命令串（shlex 已去引号）；
        # python -c 内联不解析（docstring 边界清单），走 startswith("-") 跳过。
        if arg == "-c" and prog.lower() in SHELL_VERBS and k + 1 < n:
            hits.extend(scan_bash_command(tokens[k + 1], depth + 1))
            k += 2
            continue
        # -m 模块形（integration.run_scenarios / …sc_x）。
        if arg == "-m" and k + 1 < n:
            entry = _match_entry_module(tokens[k + 1])
            if entry:
                hits.append(_hit(command, entry, segment))
            k += 2
            continue
        if arg.startswith("-"):
            k += 1
            continue
        entry = _match_entry_token(arg)
        if entry:
            hits.append(_hit(command, entry, segment))
        k += 1
    return hits


def scan_bash_command(command, _depth=0):
    """一条 bash 命令串 → 命中清单（每条 {cmd,entry,segment}）；空 list=未命中。

    畸形输入（None/非串/空）→ []，不抛；引号不平衡→空白切分兜底照常判；
    递归深度（-c 嵌套）封顶防病态输入。"""
    if not isinstance(command, str) or not command.strip():
        return []
    if _depth > _RECURSION_DEPTH_MAX:
        return []
    hits = []
    for segment in _SEGMENT_SPLIT_RE.split(command):
        seg = segment.strip()
        if not seg:
            continue
        try:
            tokens = shlex.split(seg)
        except ValueError:
            tokens = seg.split()
        hits.extend(_scan_tokens(tokens, seg, command, _depth))
    return hits


def prompt_clause():
    """developer 段派活纪律文案（人话+可执行；从 FORBIDDEN_ENTRIES 渲染——
    声明=执法同源，dev_lane.FLOW_BRIEF 注入 create_plan/implement 两键；
    文案改这里，匹配器改入口表，两侧同批）。"""
    entries = "、".join(name for _key, name in FORBIDDEN_ENTRIES)
    return (
        "验证纪律（宿主令 260921：单测可跑、集成禁跑；声明=执法——本段会话流水"
        "会被机械扫描，执行过集成入口=段结果红+票面点名该命令）。"
        "【单测可跑】受影响面 pytest（指定文件/--lf，勿全量）、"
        "python3 integration/lint_tests.py（秒级静态检查）、"
        "只读侦察（read/grep/cat/sed/ls/git log/diff）——"
        "读集成代码/文档做诊断合法，不算违规；"
        "【集成禁跑】不得在本段执行集成入口（点名）：" + entries + "——"
        "集成验证由引擎集成闸 run_integration_tests 段机械跑，developer 段只交付、"
        "不自跑集成。"
    )
