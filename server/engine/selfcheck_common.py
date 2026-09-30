"""selfcheck_* 脚本共用断言助手（t261001-04 收敛）。

九个 selfcheck_*.py 原先各自复制粘贴 ok()/section()，措辞与落点略有差异
（pass 行格式、失败行是否打印/打到哪个流、是否收集失败清单）。本模块用
参数化 reporter 一次性收敛为唯一 `def ok` / `def section` 定义，各脚本的
既有输出格式逐字保留——只收敛定义点，不改任何一行断言行为。

用法（脚本内）::

    from selfcheck_common import Selfcheck
    _rep = Selfcheck(ok_fmt="ok - %s", fail_fmt="FAIL - %s",
                     fail_stream=sys.stderr)
    ok = _rep.ok
    # 结尾汇总用 _rep.passes / _rep.fails / _rep.failures
"""

from __future__ import annotations

import sys
from typing import List, Optional, TextIO


class Selfcheck:
    """ok()/section() 断言助手 + pass/fail 计数。

    - ``ok_fmt``：通过行的 print 格式（如 ``"  ok %s"`` / ``"ok - %s"``）。
    - ``fail_fmt``：失败行的 print 格式；``None`` 表示失败行不打印
      （只计数，如 write_lifecycle 需要时自己断言）。
    - ``fail_stream``：失败行落点；``None`` = stdout，``sys.stderr`` = stderr。
    - ``track_failures``：True 时把失败 label 收进 ``failures``（结尾汇总用）。
    - ``section_fmt``：分节标题格式（``"\\n%s"`` / ``"\\n== %s"`` / ``"\\n== %s =="``）。
    """

    def __init__(
        self,
        ok_fmt: str = "  ok %s",
        fail_fmt: Optional[str] = "  FAIL %s",
        fail_stream: Optional[TextIO] = None,
        section_fmt: str = "\n%s",
        track_failures: bool = False,
    ) -> None:
        self.passes = 0
        self.fails = 0
        self.failures: List[str] = []
        self.ok_fmt = ok_fmt
        self.fail_fmt = fail_fmt
        self.fail_stream = fail_stream if fail_stream is not None else sys.stdout
        self.section_fmt = section_fmt
        self.track_failures = track_failures

    def ok(self, cond: bool, label: str) -> None:
        """断言 cond；通过打 ok 行，失败计数（按配置打失败行/收清单）。"""
        if cond:
            self.passes += 1
            print(self.ok_fmt % label)
        else:
            self.fails += 1
            if self.track_failures:
                self.failures.append(label)
            if self.fail_fmt is not None:
                print(self.fail_fmt % label, file=self.fail_stream)

    def section(self, name: str) -> None:
        """打印分节标题（不计数）。"""
        print(self.section_fmt % name)
