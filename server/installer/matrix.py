"""兼容矩阵（契约⑧-3）：三轴行 = sandbar 版本 × dsh 已验证点 × 项目 schema 版本。

纪律：append 制（绿一行 append 一行）、幂等（同键行不重复 append）、
读侧 schema 校验（坏 JSON / schema 不符 / 行缺键 = MatrixError 红，不静默覆写）。
落点 ~/.sandbar/compat-matrix.json（SANDBAR_HOME 可整体换家，测试用 tmp）。
"""

from __future__ import annotations

import json
import os
import pathlib
import tempfile
import time

SCHEMA = 1
ROW_KEYS = ("ts", "sandbar_version", "dsh_point", "project_schema", "probe")


class MatrixError(RuntimeError):
    """矩阵文件/行不合规——fail-closed 红。"""


def _validate_row(row, where: str) -> None:
    if not isinstance(row, dict):
        raise MatrixError("%s：行不是对象" % where)
    for k in ROW_KEYS:
        if k not in row:
            raise MatrixError("%s：行缺键 %s" % (where, k))
    for k in ("ts", "sandbar_version", "dsh_point", "project_schema", "probe"):
        v = row[k]
        ok = isinstance(v, int) and not isinstance(v, bool) if k == "ts" \
            else isinstance(v, str) and v != ""
        if not ok:
            raise MatrixError("%s：键 %s 类型不合规（%r）" % (where, k, v))


def load(path) -> dict:
    """读矩阵；缺失→空表。坏 JSON / schema 不符 / 行不合规→MatrixError。"""
    p = pathlib.Path(path)
    try:
        raw = p.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {"schema": SCHEMA, "rows": []}
    except (IsADirectoryError, PermissionError, UnicodeDecodeError) as e:
        raise MatrixError("矩阵文件不可读：%s（%s）" % (p, e))
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        raise MatrixError("矩阵文件坏 JSON：%s（%s）" % (p, e))
    if not isinstance(data, dict) or data.get("schema") != SCHEMA:
        raise MatrixError("矩阵 schema 不符（期望 %d）：%s" % (SCHEMA, p))
    rows = data.get("rows")
    if not isinstance(rows, list):
        raise MatrixError("矩阵 rows 不是列表：%s" % p)
    for i, row in enumerate(rows):
        _validate_row(row, "矩阵第 %d 行" % (i + 1))
    return data


def row_key(row) -> tuple:
    """幂等键：三轴 + 探针名（ts 不参与——重跑同轴不重复 append）。"""
    return (row["probe"], row["sandbar_version"], row["dsh_point"],
            row["project_schema"])


def append_row(path, probe: str, sandbar_version: str, dsh_point: str,
               project_schema: str):
    """append 一行绿证据；同键已存在则跳过。返回 (appended: bool, total: int)。"""
    data = load(path)
    new = {"ts": int(time.time()), "sandbar_version": sandbar_version,
           "dsh_point": dsh_point, "project_schema": project_schema,
           "probe": probe}
    _validate_row(new, "新行")
    key = row_key(new)
    for row in data["rows"]:
        if row_key(row) == key:
            return False, len(data["rows"])
    data["rows"].append(new)
    _atomic_write(path, data)
    return True, len(data["rows"])


def _atomic_write(path, data: dict) -> None:
    p = pathlib.Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(p.parent), prefix=".compat-matrix-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
        os.replace(tmp, str(p))
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def render(rows) -> str:
    """人读表格（doctor 输出用）。"""
    if not rows:
        return "（矩阵空——尚无绿证据，契约⑧-3：空格=未验证不承诺）"
    head = "%-24s %-12s %-12s %-8s" % ("probe", "sandbar", "dsh 点", "schema")
    lines = [head, "-" * len(head)]
    for r in rows:
        lines.append("%-24s %-12s %-12s %-8s" %
                     (r["probe"], r["sandbar_version"], r["dsh_point"],
                      r["project_schema"]))
    return "\n".join(lines)
