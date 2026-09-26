"""测试临时目录回收（260926 磁盘泄漏修，同类普查）：注册表 + atexit 兜底 + 幂等回收。

背景：`$TMPDIR` 顶层实测 407,294 个目录，其中 401,578 个 >6 小时未动（98.6%）——大头是
各测试面 `tempfile.mkdtemp` 出来的 **git 夹具**：`mkdtemp` 从不回收（正常退出也不回收），
`server/engine/tests/test_multirepo_anchor.py` 一个文件就落了 1.7 万个目录 / ~848MB，
`test_multirepo_root_activity.py` ~771MB。本模块=引擎侧测试的**唯一**夹具落点。

终态矩阵（逐个检查过，不假设「正常退出就够」）：
  - 正常完成 / 断言失败 / 异常 / `sys.exit()` → CPython 解释器退出必跑 `atexit` 钩子；
  - pytest 会话结束（含 `--exitfirst`/收集期异常）→ 同上（同一解释器退出路径）；
  - `KeyboardInterrupt`（Ctrl-C）→ 仍走解释器退出，`atexit` 照跑；
  - SIGTERM/SIGINT 的**默认**处置 → 进程直接被终止，**不跑 atexit**（CPython 只把信号转成
    异常，默认处置下不经过解释器退出路径）；
  - SIGKILL（执行器硬超时杀）→ 物理上不可能在进程内捕获。
  后两态**本模块兜不住，也不假装兜得住**：兜底网是仓库级的两件机械面——
  ①`integration/tools/sweep_tmp_fixtures.py`（一次性存量清扫，按前缀白名单 + 年龄 ≥6h）；
  ②引擎巡检第四判据 `inspection_lane_watchdog` 的临时目录水位（越线出 finding）。
  即：进程内所有终态由本模块回收；被硬杀的残留由「开跑即扫 / 巡检水位」接管。

纪律：注册表只在**创建成功之后**入册（创建失败不入册）；回收**幂等**（弹栈式取走，
重复调用/重复删同一目录都不抛）；单个目录删除失败**不中断**其余回收（`ignore_errors`
+ 逐条计数），因为回收是清理面，绝不能把一次套件跑红或吞掉真正的失败。
"""
from __future__ import annotations

import atexit
import shutil
import tempfile
from pathlib import Path

#: 本进程创建、尚未回收的夹具目录（真源；`Path` 列表，回收后立刻出册）
_LIVE_DIRS: list = []

#: 回收失败计数（可观测；测试/收口报告可读——不静默）
REAP_FAILURES: int = 0


def mkdtemp_reclaimed(prefix: str, root: str = None) -> Path:
    """`mkdtemp` 的回收版：建目录 + 入册 + 本进程退出时必被回收。返回 `Path`。

    入册在创建成功之后——`mkdtemp` 抛异常时不留下半条注册（回收面不猜）。
    """
    path = Path(tempfile.mkdtemp(prefix=prefix, dir=root))
    _LIVE_DIRS.append(path)
    return path


def reap_live_tmp_dirs() -> int:
    """回收本进程注册的全部夹具目录（幂等）：返回本次实际尝试回收的条数。

    弹栈式取走（取走即出册），所以重复调用第二次是零条；目录已被别人删掉、
    权限不足等一律 `ignore_errors` 吞掉但计数上报（清理面不抛）。
    """
    global REAP_FAILURES
    n = 0
    while _LIVE_DIRS:
        p = _LIVE_DIRS.pop()
        existed = p.exists()
        shutil.rmtree(str(p), ignore_errors=True)
        n += 1
        if existed and p.exists():
            REAP_FAILURES += 1
    return n


def live_tmp_dirs() -> list:
    """当前在册（未回收）的夹具目录快照（观测面；调用方不得据此改册）。"""
    return list(_LIVE_DIRS)


#: 进程级兜底：正常/异常/早退所有走解释器退出的终态都回收（与各测试文件的
#: `try/finally` 互为冗余，重复回收无害——幂等）。
atexit.register(reap_live_tmp_dirs)
