"""developer 段集成禁跑执法的单点真源（宿主令 260921，票 t260921-04）。

声明=执法：本模块同时供两侧消费，两侧改动必须同批（票面验收④）——
- 文案侧：prompt_clause() 渲染 developer 段派活纪律（dev_lane.FLOW_BRIEF 注入
  create_plan/implement 两键），入口名单从 FORBIDDEN_ENTRIES 渲染，不手写；
- 执法侧：scan_bash_command() 执行锚定匹配器（agent_activities 的段会话扫描调用），
  判据=同一张 FORBIDDEN_ENTRIES。

判「跑」不判「读」（票面验收③防误伤）：只有执行动词（python/node/bash/sh/pytest/…、
直接执行、-m 模块形）之后的实参 basename 命中入口表才算执行；-m 形另有静态工具
白名单豁免（t260922-08，语义见下方边界清单）；grep/cat/sed/ls 等只读动词的参数
提及、prompt 回显帧不算违规。

切段解析（t260922-14）：切段是引号/转义感知的——旧正则切段不认引号，`grep -E
"…|verify_lane…"` 引号内的 `|` 被当管道，`|` 之间的裸片段（恰为 `verify_lane`）撞
入口表误红，现场两例均沉淀为 UT 夹具（t260922-12 原命令、t260922-14 会话档探针，
后者为 heredoc 正文被逐行判=第三类误红载体）。现由 `_split_segments()` 状态机切段：
引号外才认段分隔 `;|&` 与换行（`&&`/`||`/`;;`/`|&` 连写同作一处边界），引号内与
`\` 转义的分隔符不切；`\`+换行按 bash 续行吞并（续行后动词保持锚定）；词首 `#` 到
行尾按注释不判。hit 的 segment 摘要仍是原文切片（引号保留）、cmd 摘要不变——对外
可观测字段零漂移。

执法面边界（口径诚实，落字防漂移；review K1/C3 意见收口）：
- `bash/sh -c "<串>"`：引号内串按同规则**递归**判（K1 推荐路线）——
  `bash -c 'python3 integration/run_scenarios.py'` 判红；
  `bash -c 'ls integration/baselines'` 不判（递归后只读动词照样豁免）；
- `python3 -c "<代码>"`：内联代码不解析（导入式间接执行不可静态判定）——已知局限；
- `-m` 模块形（t260922-08）：模块名命中入口表（run_scenarios/sc_* 尾名）→ 判红
  （`-m run_scenarios`、`-m pytest <入口文件>`——pytest 收集即 import 执行，真跑）；
  `-m <STATIC_TOOL_MODULES 成员>`（py_compile/compileall/ast/tokenize/dis）→ 其后
  实参是被读/编译而非执行，本段剩余实参不判（静态自检合法；此前已记命中保留）；
  连写形（`-mpy_compile`，CPython 接受无空格连写）仅对静态白名单成员同样豁免；
  连写执行器模块名（`python3 -mrun_scenarios` 等）走泛化 flag 跳过分支**不判红**
  ——既有已知漏判（与 -c 内联、xargs 同级），非本票引入、本票不收口；
- `pytest <目录形>`（如 `pytest integration/`、`pytest integration/tests`）：不判——
  pytest 默认只收集 test_ 前缀文件，目录形实参 basename 不命中入口表
  （integration/tests 是集成库自身单测面）；pytest 仅在实参 basename 命中入口表时判
  （收集即 import 执行场景模块=真跑）；
- `xargs` 二段式不追——已知局限；
- heredoc 正文=数据（t260922-14）：body 不再无条件逐行判——同逻辑行组内任一段的
  程序词（剥括号后）属于解释/执行动词（bash/sh/zsh/dash/source/./eval/xargs，含
  `cat <<EOF | bash` 这类**管道下游消费方**、`xargs python3 <<EOF` 实参执行形）时，
  body=真 shell 输入照旧逐行判（判据不松）；整行组无此类动词才按数据放行
  （`python3 - <<'PYEOF'` 探针正文、`cat <<EOF` 直挂数据）；下游为非 shell 解释器
  （python3/node 等）时 body 按 python/node 代码执行，bash 执法器不判（与 `-c`
  内联不解析同族）。真值注记（t260922-14 实测）：eval 直挂无实参不消费 stdin、
  source/. 直挂需文件实参、裸 xargs 默认 echo 仅回显——三者按执法原则**保守纳入**
  照判（现状亦判，只紧不松），不夸大其真跑语义。delimiter 终止行与 delimiter
  逐字一致（`<<-` 仅去行首 tab）；delimiter 行未出现→余文全按 body 处置不抛；
  CRLF/尾随空白不特判；
- `bench.py`/`cache_probe.py`/`stage_docker.py`/`lib_*` 等集成**辅助**工具面不在执法面
  （如需收口宿主另票）；
- 既有已知漏判补全（落字防静默翻红；非本票引入、本票不收口，t260922-14）：反引号/
  `$( )` 内藏跑、进程替换 `bash <(python3 …)` 形（尾括号粘 basename）、子壳括号内
  多词 prog 的 heredoc 形（如 `(cd x && bash) <<EOF`——括号组内 prog 提取不追；
  单词形 `(bash`/`(python3` 已由剥括号覆盖）。与 `-c` 内联/`xargs` 二段式/连写
  `-mrun_scenarios` 同族同级。

纯函数零 IO；畸形输入（None/非串/空/引号不平衡/超长/heredoc 未闭合）不抛，按兜底
切词照常判。
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
# -m 静态工具模块（t260922-08）：模块名零执行语义，其后实参是被读/编译/反汇编
# 而非被执行——`-m <成员>` 之后本段剩余实参不再参与入口表匹配（误伤收窄）。
# 只收静态分析面；执行器（pytest/unittest/timeit/cProfile/pdb/runpy…）禁入——
# 扩展本表须同批带 UT + docstring 落字（声明=执法）。
STATIC_TOOL_MODULES = frozenset({
    "py_compile", "compileall", "ast", "tokenize", "dis",
})
# 透明包装 token（跳过）：其后直至程序 token 之前的 flag/数字/VAR=… 一并跳过。
WRAPPER_TOKENS = frozenset({
    "sudo", "nohup", "env", "timeout", "time", "nice", "stdbuf", "exec",
})
_RECURSION_DEPTH_MAX = 3
_CMD_EXCERPT_MAX = 200
_SEGMENT_EXCERPT_MAX = 120
# heredoc body 的解释/执行动词（组级保守分流，t260922-14 取代旧 _SEGMENT_SPLIT_RE
# 正则切段——正则不认引号，`grep -E "a|b"` 的 `|` 被当管道切段，裸片段撞入口表误红）。
# bash 族直挂/管道下游真执行 body；source/. 直挂需文件实参、eval 直挂无实参不消费
# stdin、裸 xargs 默认 echo 仅回显（t260922-14 真值实测）——后三者按执法保守原则
# 一并纳入照判（现状亦判，只紧不松）。扩展本表须同批带 UT + docstring 落字。
_HEREDOC_EXEC_TARGETS = frozenset({
    "bash", "sh", "zsh", "dash", "source", ".", "eval", "xargs",
})
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


def _seg_prog(segment):
    """段文本 → 小写程序词（跳过赋值/透明包装，prog 剥括号）；无程序词返回 None。"""
    try:
        tokens = shlex.split(segment)
    except ValueError:
        tokens = segment.split()
    idx = _program_index(tokens)
    if idx is None:
        return None
    prog = tokens[idx].strip("()").lower()
    return prog or None


def _parse_heredoc_delim(command, i, n):
    """command[i] 指向 `<<`；返回 (delimiter, dash, next_i)。

    `<<-` 容行首 tab，delimiter 可引号包裹或裸词（遇空白/`;|&<>()`/反引号止）；
    `<<<`（here-string，非行消费）由调用方排除，不在此处理。"""
    j = i + 2
    dash = False
    if j < n and command[j] == "-":
        dash = True
        j += 1
    while j < n and command[j] in " \t":
        j += 1
    if j >= n:
        return "", dash, j
    ch = command[j]
    if ch in "'\"":
        k = command.find(ch, j + 1)
        if k == -1:
            return command[j + 1:], dash, n
        return command[j + 1:k], dash, k + 1
    k = j
    while k < n and command[k] not in " \t\n;|&<>()`":
        k += 1
    return command[j:k], dash, k


def _split_segments(command):
    """引号/转义感知切段 + heredoc body 组级分流（纯函数，全路径不抛）。

    规则（t260922-14）：
    - 引号外才认段分隔 `;` `|` `&` 换行（`&&`/`||`/`;;`/`|&` 连写同作一处边界）；
      引号内与 `\` 转义的分隔符不切；`\`+换行按 bash 续行吞并（逻辑行拼接）；
    - 词首 `#` 到行尾按注释不判（与 shlex commenter 行为等价）；
    - heredoc（`<<`/`<<-`，`<<<` 非行消费）：body 按**同逻辑行组级**保守分流——
      组内任一段程序词 ∈ _HEREDOC_EXEC_TARGETS → body=真 shell 输入，逐行走本
      切段器照判（管道下游消费方/直挂真跑不松）；整行组无 → body=数据放行
      （python3/cat 等直挂）；delimiter 行未出现→余文全按 body 处置。
    返回段文本列表（原文切片，引号保留——hit 的 segment 摘要语义不变）。"""
    segments, cur = [], []
    seg_delims, line_delims = [], []   # (delimiter, dash)：段内收集，行级消费
    line_progs = []                    # 本逻辑行（顶层换行之间）各段程序词
    quote = None
    prev = ""
    i, n = 0, len(command)

    def _flush():
        text = "".join(cur)
        del cur[:]
        prog = _seg_prog(text)
        if prog is not None:
            line_progs.append(prog)
        if seg_delims:
            line_delims.extend(seg_delims)
            del seg_delims[:]
        if text.strip():
            segments.append(text)

    def _emit_body(body, is_shell):
        if is_shell:
            for line in body.split("\n"):
                segments.extend(_split_segments(line))

    def _consume_bodies(start, is_shell):
        pos = start
        for delim, dash in line_delims:
            j = pos
            while True:
                k = command.find("\n", j)
                line = command[j:] if k == -1 else command[j:k]
                probe = line.lstrip("\t") if dash else line
                if probe == delim:
                    _emit_body(command[pos:j], is_shell)
                    pos = n if k == -1 else k + 1
                    break
                if k == -1:
                    _emit_body(command[pos:], is_shell)
                    pos = n
                    break
                j = k + 1
        del line_delims[:]
        del line_progs[:]
        return pos

    while i < n:
        ch = command[i]
        if quote == "'":
            cur.append(ch)
            if ch == "'":
                quote = None
            prev = ch
            i += 1
        elif quote == '"':
            cur.append(ch)
            if ch == "\\" and i + 1 < n:
                cur.append(command[i + 1])
                i += 2
                continue
            if ch == '"':
                quote = None
            prev = ch
            i += 1
        else:
            if ch in "'\"":
                quote = ch
                cur.append(ch)
                prev = ch
                i += 1
            elif ch == "\\" and i + 1 < n:
                if command[i + 1] == "\n":
                    i += 2
                else:
                    cur.append(ch)
                    cur.append(command[i + 1])
                    i += 2
                    prev = command[i - 1]
            elif ch == "<" and i + 1 < n and command[i + 1] == "<":
                if i + 2 < n and command[i + 2] == "<":
                    cur.append("<<<")
                    i += 3
                    prev = "<"
                else:
                    delim, dash, j = _parse_heredoc_delim(command, i, n)
                    seg_delims.append((delim, dash))
                    cur.append(command[i:j])
                    i = j
                    prev = " "
            elif ch in ";|&\n":
                _flush()
                if ch == "\n":
                    i += 1
                    if line_delims:
                        is_shell = any(p in _HEREDOC_EXEC_TARGETS for p in line_progs)
                        i = _consume_bodies(i, is_shell)
                    else:
                        del line_progs[:]
                    while i < n and command[i] in ";|&\n":
                        i += 1
                    prev = " "
                else:
                    while i < n and command[i] in ";|&\n":
                        i += 1
                    prev = " "
            elif ch == "#" and (prev == "" or prev.isspace() or prev in ";|&"):
                while i < n and command[i] != "\n":
                    i += 1
            else:
                cur.append(ch)
                prev = ch
                i += 1
    _flush()
    del line_delims[:]
    del line_progs[:]
    return segments


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
        # -m 模块形（integration.run_scenarios / …sc_x）：模块名命中入口表先判
        # （真跑，t260922-08 维持）；静态工具成员豁免本段剩余实参（被读/编译非执行）。
        if arg == "-m" and k + 1 < n:
            module = tokens[k + 1]
            entry = _match_entry_module(module)
            if entry:
                hits.append(_hit(command, entry, segment))
                k += 2
                continue
            if module in STATIC_TOOL_MODULES:
                # t260922-08：py_compile/… 的文件实参是被编译而非被执行，不再匹配
                # 入口表（此前已记的命中保留，豁免不追溯）。
                break
            k += 2
            continue
        # -m<模块> 连写形（python -mtimeit 同族，CPython 接受无空格连写）：
        # 仅静态白名单成员同样豁免；连写执行器模块名（-mrun_scenarios 等）走下方
        # 泛化 flag 跳过——既有已知漏判，docstring 边界清单已落字（t260922-08）。
        if arg.startswith("-m") and len(arg) > 2 and arg[2:] in STATIC_TOOL_MODULES:
            break
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

    切段引号/转义感知（t260922-14，_split_segments）；畸形输入（None/非串/空）→ []，
    不抛；引号不平衡段→空白切分兜底照常判；递归深度（-c 嵌套）封顶防病态输入。"""
    if not isinstance(command, str) or not command.strip():
        return []
    if _depth > _RECURSION_DEPTH_MAX:
        return []
    hits = []
    for segment in _split_segments(command):
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
        "python3 -m py_compile <文件>（静态语法自检，t260922-08）、"
        "只读侦察（read/grep/cat/sed/ls/git log/diff）——"
        "读集成代码/文档做诊断合法，不算违规；"
        "【集成禁跑】不得在本段执行集成入口（点名）：" + entries + "——"
        "集成验证由引擎集成闸 run_integration_tests 段机械跑，developer 段只交付、"
        "不自跑集成。"
    )
