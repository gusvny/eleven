"""compat 探针集（交接单 §5 四面）：全部读 fixture/只读探测。

- 缺省只跑 fixture 桩（不起真 dsh 进程、不写 dsh home）；
- 真环境是 doctor --live 可选档（需 DSH_* 环境变量指路，缺指路=显式红，不静默）；
- 每个探针返回 ProbeResult（ok + 人读 detail），红绿双向皆显式。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ProbeResult:
    name: str
    ok: bool
    detail: str

    def line(self) -> str:
        return "[%s] %s：%s" % ("绿" if self.ok else "红", self.name, self.detail)
