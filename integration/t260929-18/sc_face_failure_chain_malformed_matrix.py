#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""t260929-18 场景②：票面失败文案的畸形链契约面（灰盒，离线秒级零 docker）。

intent（工单要求 5(c) 逐字：malformed matrix——无 cause 链 / cause 非异常 /
成环 / 超深链 / 全空消息 → 显式「根因不可得」类话术，绝不炸、绝不编造；以及
要求③反向锁在畸形链上同样成立）：format_agent_stage_failure 是票面 blocked
文案的唯一出口（12 个 catch 位 + base.py 共用），它的对外契约是「text-in →
text-out 纯函数、畸形输入不炸不编造」——这是用户可感知的票面行为，不是实现
细节，故锚公开函数面（白盒矩阵归 developer L1 UT，不同层）。

子用例（全部喂 SDK 造不出来的畸形链，真实包裹路归场景①）：
- M1 无 cause 链：普通 RuntimeError(消息) → 文案含该消息与类型名，不炸；
- M2 cause 挂野对象（非异常）：下钻就地停，文案含外层消息，不炸；
- M3 cause 成环：a↔b 互指 → 守卫生效不挂死，显式话术或最深可达真消息，不炸；
- M4 超深链（10 级真消息）：不炸；文案要么点名链上真实消息、要么显式「不可得」
  ——绝不只剩通用包装形状、绝不编造链上不存在的消息；
- M5 全链零消息：每层消息皆空 → 显式「不可得」话术，不编造；
- M6 反向锁×畸形链：成环链中藏 type=worker_terminated → 专用文案赢，不炸。

三态：零环境依赖（被测函数 stdlib-only，直接源码路径装载）；实现未落地段红属
预期（TDD 信号），arbitrate/merge 期必须绿。
"""
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, ".."))                             # integration/
sys.path.insert(0, os.path.join(_HERE, "..", "..", "server", "engine"))  # shared

from lib_env import env_fail  # noqa: E402

try:
    from shared import format_agent_stage_failure
except Exception as e:
    env_fail("shared.py（stdlib-only）装载失败：%r" % (e,))

SCENARIO = "t260929-18-face-reason-malformed-matrix"
MARKER = "根因标记消息-每层都有-第%d层"
CASES = []


def case(name, ok_, evidence):
    CASES.append((name, bool(ok_), evidence))


def face(exc):
    """统一入口：任意畸形输入走公开函数，异常也算结果不炸场景。"""
    try:
        return format_agent_stage_failure("t260929-18", "implement", exc), None
    except Exception as e:  # noqa: BLE001 —— 畸形输入炸了=红
        return None, repr(e)


REPO = os.path.abspath(os.path.join(_HERE, "..", ".."))


def _reexec_with_engine_venv():
    """M6 需要 temporalio（ApplicationError 构造）→ 引擎 venv 回落链重自exec。"""
    try:
        import temporalio  # noqa: F401
        return
    except Exception:
        pass
    from shared import engine_venv_python
    py = engine_venv_python(REPO)
    if py is None:
        env_fail("引擎 venv（temporalio，M6 反向锁构造面需要）缺失：server/engine/.venv "
                 "与旧路径回落均无解释器")
    os.execv(str(py), [str(py), __file__])


def main():
    _reexec_with_engine_venv()
    # M1 无 cause 链
    e1 = RuntimeError("普通失败：真实原因甲")
    t1, err = face(e1)
    case("M1-plain-no-chain",
         err is None and t1 and "真实原因甲" in t1 and "RuntimeError" in t1,
         "text=%r err=%r" % (t1, err))

    # M2 cause 挂野对象（非异常）。真实异常的 __cause__ 只能赋 None/BaseException
    # （解释器强制），畸形形态来自鸭子类型链——Temporal 侧读的是 `.cause` 属性，
    # 桩形链（SimpleNamespace 面）正是客户端/桩数据可出现的形状，链上挂野字符串。
    from types import SimpleNamespace
    e2 = SimpleNamespace(__name__="FakeActivityError",
                         cause="not-an-exception", args=("外层有话要说",))
    t2, err = face(e2)
    case("M2-cause-not-exception",
         err is None and t2 and "外层有话要说" in t2,
         "text=%r err=%r" % (t2, err))

    # M3 cause 成环
    a, b = RuntimeError("环甲"), ValueError("环乙")
    a.__cause__ = b
    b.__cause__ = a
    t3, err = face(a)
    case("M3-cyclic-cause-no-hang",
         err is None and isinstance(t3, str) and bool(t3),
         "text=%r err=%r" % (t3, err))

    # M4 超深链（10 级、每层真消息）
    deep = RuntimeError(MARKER % 9)
    for i in range(8, -1, -1):
        nxt = RuntimeError(MARKER % i)
        nxt.__cause__ = deep
        deep = nxt
    t4, err = face(deep)
    reachable = any((MARKER % i) in (t4 or "") for i in range(10))
    case("M4-overdeep-chain",
         err is None and t4 and (reachable or "不可得" in t4)
         and "不存在的消息" not in t4,
         "text=%r err=%r" % (t4, err))

    # M5 全链零消息
    e5 = RuntimeError("")
    inner = ValueError("")
    e5.__cause__ = inner
    t5, err = face(e5)
    case("M5-all-empty-messages-explicit-unavailable",
         err is None and t5 and "不可得" in t5,
         "text=%r err=%r" % (t5, err))

    # M6 反向锁 × 成环链（worker_terminated type 藏在环里）
    from temporalio.exceptions import ApplicationError  # noqa: F401  # 探测可导入性
    e6 = RuntimeError("环面外层")
    w6 = ApplicationError("worker shutdown", type="worker_terminated")
    c6 = ValueError("环丙")
    e6.__cause__ = w6
    w6.__cause__ = c6
    c6.__cause__ = e6                          # 成环
    t6, err = face(e6)
    case("M6-worker-terminated-wins-on-cyclic-chain",
         err is None and t6 and "worker 被外部终止" in t6
         and "Activity task failed" not in t6,
         "text=%r err=%r" % (t6, err))

    npass = sum(1 for _, ok_, _ in CASES if ok_)
    from lib_result import spec_line
    for name, ok_, ev in CASES:
        sys.stdout.write(spec_line("%s/%s" % (SCENARIO, name),
                                   "pass" if ok_ else "fail",
                                   cause="self" if ok_ else "unknown",
                                   reason="" if ok_ else "assertion red",
                                   evidence=ev, suite=SCENARIO))
    sys.stdout.write("SUMMARY %s: ran=%d pass=%d fail=%d\n"
                     % (SCENARIO, len(CASES), npass, len(CASES) - npass))
    sys.exit(0 if npass == len(CASES) else 1)


if __name__ == "__main__":
    main()
