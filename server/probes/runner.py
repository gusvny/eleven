"""探针注册表与执行器：doctor 的载体。

缺省=fixture 档（零外部依赖、零副作用）；`--live` 档读真环境（只读），
需环境变量指路，缺指路=该面显式红（不静默、不假装绿）：
  DSH_HOME（probe-home-layout）、DSH_SESSION_FILE（probe-session-format）、
  DSH_INSTALL_ROOT（probe-runner-assembly）、DSH_SETTINGS_ROOT（probe-settings-resolve）。
"""

from __future__ import annotations

import os
import pathlib

from probes import ProbeResult
from probes import probe_home_layout, probe_runner_assembly, probe_session_format, probe_settings_resolve

FIXTURE_ROOT = pathlib.Path(__file__).resolve().parent / "fixtures"


def _fixture(*parts) -> pathlib.Path:
    return FIXTURE_ROOT.joinpath(*parts)


def _live(name: str, env: str):
    val = os.environ.get(env)
    if not val:
        return ProbeResult(name, False,
                           "--live 档需环境变量 %s 指路（缺省只跑 fixture，不静默猜真环境）" % env)
    return None


def run_all(live: bool = False):
    """跑四面探针，返回 [ProbeResult]（顺序固定，便于 doctor 逐行 append）。"""
    if not live:
        return [
            probe_home_layout.run(_fixture("home_layout", "good")),
            probe_session_format.run(_fixture("session", "good", "session.jsonl")),
            probe_runner_assembly.run(_fixture("runner", "good", "dsh-dist")),
            probe_settings_resolve.run(_fixture("settings", "good")),
        ]
    results = []
    r = _live(probe_home_layout.NAME, "DSH_HOME")
    results.append(r or probe_home_layout.run(os.environ["DSH_HOME"]))
    r = _live(probe_session_format.NAME, "DSH_SESSION_FILE")
    results.append(r or probe_session_format.run(os.environ["DSH_SESSION_FILE"]))
    r = _live(probe_runner_assembly.NAME, "DSH_INSTALL_ROOT")
    results.append(r or probe_runner_assembly.run(os.environ["DSH_INSTALL_ROOT"]))
    r = _live(probe_settings_resolve.NAME, "DSH_SETTINGS_ROOT")
    results.append(r or probe_settings_resolve.run(os.environ["DSH_SETTINGS_ROOT"]))
    return results
