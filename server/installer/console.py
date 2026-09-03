"""console（3099）探界模块——CLAUDE.md 硬规则 1 的代码落点。

纪律：console 永属用户操作面。本模块对它**只 TCP 探测、只提示**；
任何代码路径不得对 3099 执行启停动词。全安装器 3099 字面量只允许出现在
本文件（CONSOLE_PORT 定义处），由 integration/baselines/sc_sandbar_installer_console_line.py
做源码级静态断言（禁词表 × 3099/console 上下文；「请手动起停」提示文案白名单豁免，
断言区分提示字符串与可执行代码）。
"""

CONSOLE_PORT = 3099

# 白名单提示文案（§3：提示与执行分离的样板；静态断言对含此样的字符串豁免）
CONSOLE_PROMPT = "console 属用户操作面，请手动起停"


def probe_console(port=None, host="127.0.0.1", timeout=1.0) -> bool:
    """判 console 是否在位：纯 TCP connect 探测，别无动作。"""
    from installer import runtime
    return runtime.port_open(
        CONSOLE_PORT if port is None else port, timeout=timeout, host=host)


def describe(port, present: bool) -> str:
    """人读状态行（提示文案出自 CONSOLE_PROMPT，不带执行语义）。"""
    if present:
        return "console（%d）在位（%s；本安装器只探测不管控）" % (port, CONSOLE_PROMPT)
    return "console（%d）未在位——%s" % (port, CONSOLE_PROMPT)
