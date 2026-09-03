"""严格子集 YAML 解析器（探针专用，标准库零依赖）。

只支持 dsh settings/patch 类配置的真实所需面：
  嵌套 mapping（2 空格缩进）、`- ` 列表、标量（int/float/bool/null/带引号/裸串）、
  行尾/整行 `#` 注释。**严格 fail-closed**：tab 缩进、不一致缩进、重复键、
  未闭合引号、flow 语法（{a: b} / [a, b]）一律 YamlError——探针宁可红也不猜。
"""

from __future__ import annotations

import re


class YamlError(ValueError):
    """不支持的 YAML 语法/坏格式——fail-closed。"""


_SCALAR_TRUE = {"true", "True", "TRUE"}
_SCALAR_FALSE = {"false", "False", "FALSE"}
_SCALAR_NULL = {"null", "Null", "NULL", "~", ""}


def _strip_comment(line: str) -> str:
    """去行尾注释：`#` 须在行首或空白之后，且不在引号内。"""
    out = []
    quote = None
    i = 0
    while i < len(line):
        ch = line[i]
        if quote:
            out.append(ch)
            if ch == quote:
                quote = None
        else:
            if ch in ("'", '"'):
                quote = ch
                out.append(ch)
            elif ch == "#" and (i == 0 or line[i - 1] in " \t"):
                break
            else:
                out.append(ch)
        i += 1
    return "".join(out).rstrip()


def _parse_scalar(raw: str):
    s = raw.strip()
    if s and s[0] in "{[":
        raise YamlError("不支持 flow 语法（%r）——本解析器只收块级子集" % s)
    if s and s[0] in ("'", '"'):
        if len(s) < 2 or s[-1] != s[0]:
            raise YamlError("未闭合引号：%r" % s)
        inner = s[1:-1]
        if s[0] == "'" and "'" in inner.replace("''", ""):
            raise YamlError("非法单引号转义：%r" % s)
        if s[0] == '"' and '"' in inner:
            raise YamlError("非法双引号：%r" % s)
        return inner.replace("''", "'") if s[0] == "'" else inner
    if s in _SCALAR_TRUE:
        return True
    if s in _SCALAR_FALSE:
        return False
    if s in _SCALAR_NULL:
        return None
    if re.fullmatch(r"-?\d+", s):
        return int(s)
    if re.fullmatch(r"-?\d+\.\d+", s):
        return float(s)
    return s


def _indent_of(line: str) -> int:
    n = 0
    for ch in line:
        if ch == " ":
            n += 1
        elif ch == "\t":
            raise YamlError("tab 缩进不支持（严格子集）：%r" % line)
        else:
            break
    return n


def loads(text: str):
    """解析 YAML 子集文本为 Python 对象（顶层须为 mapping）。"""
    lines = []
    for no, raw in enumerate(text.splitlines(), 1):
        line = _strip_comment(raw)
        if line.strip():
            lines.append((no, line))
    if not lines:
        return {}
    value, idx = _parse_block(lines, 0, _indent_of(lines[0][1]))
    if idx != len(lines):
        raise YamlError("第 %d 行缩进不一致（严格子集）" % lines[idx][0])
    return value


def _parse_block(lines, idx, indent):
    """解析同缩进块：mapping（k: v）或列表（- v）。返回 (value, next_idx)。"""
    is_list = lines[idx][1].lstrip().startswith("- ")
    if is_list:
        items = []
        while idx < len(lines):
            no, line = lines[idx]
            if _indent_of(line) != indent or not line.lstrip().startswith("- "):
                break
            items.append(_parse_scalar(line.lstrip()[2:]))
            idx += 1
        return items, idx
    mapping = {}
    while idx < len(lines):
        no, line = lines[idx]
        cur = _indent_of(line)
        if cur < indent:
            break
        if cur > indent:
            raise YamlError("第 %d 行缩进不一致（期望 %d 空格，实得 %d）" % (no, indent, cur))
        body = line.strip()
        if body.startswith("- "):
            break  # 同层出现列表项=上层列表已收
        m = re.match(r"^([^:]+):\s*(.*)$", body)
        if not m or not m.group(1).strip():
            raise YamlError("第 %d 行不是 `key: value` 形态：%r" % (no, body))
        key = _parse_scalar(m.group(1))
        if isinstance(key, str) and key in mapping:
            raise YamlError("第 %d 行重复键：%s（fail-closed，不静默覆盖）" % (no, key))
        rest = m.group(2).strip()
        if rest:
            mapping[key] = _parse_scalar(rest)
            idx += 1
        else:
            idx += 1
            if idx < len(lines) and _indent_of(lines[idx][1]) > indent:
                child, idx = _parse_block(lines, idx, _indent_of(lines[idx][1]))
                mapping[key] = child
            elif idx < len(lines) and _indent_of(lines[idx][1]) == indent \
                    and lines[idx][1].lstrip().startswith("- "):
                child, idx = _parse_block(lines, idx, indent)
                mapping[key] = child
            else:
                mapping[key] = None
    return mapping, idx


def load_file(path):
    """读文件并解析；IO/语法错误统一 YamlError（探针显式红）。"""
    try:
        text = pathlib_read(path)
    except OSError as e:
        raise YamlError("读不了 %s：%s" % (path, e))
    return loads(text)


def pathlib_read(path) -> str:
    import pathlib
    return pathlib.Path(path).read_text(encoding="utf-8")
