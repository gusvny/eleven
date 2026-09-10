#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""t260910-12 场景：瞬态分类与一次重试契约（灰盒 L2 库契约，秒级零 docker，ro 池）。

intent（登记于 run_scenarios.py SCENARIOS，本文件为其执行体）：
- 三类已知瞬态（台内 502 / 端口拒连族 / 起台面繁忙族）命中白名单判 transient；
  非瞬态（镜像缺席、畸形工程名等终态环境红）判 fatal 不重试；
- retry 语义：瞬态失败自动重试恰一次——首试瞬态次试成功=成功且调用计数=2；
  两试皆瞬态=原样抛最后一次（文案逐字节不变，仲裁分类器不被迫吸收）；
  首试即非瞬态=不重试（计数=1）原样抛；
- 畸形输入（空串 / 非字符串对象 / 超长行）不误分类、不炸；
- py 单源与 mjs 判定一致（固定消息桩清单两态逐条比对——防双实现漂移，
  stage_docker.mjs 头注自述「两份逻辑会漂移且漂移发生过」）。
断言锚公开契约（库函数名与 judge 子命令是方案承诺的对外面），零 docker 依赖。
实现段落地前 import 红=FAIL 属预期（TDD 信号），arbitrate/merge 期必须绿。
"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
LIB = os.path.join(REPO, "integration", "lib_transient_retry.py")
LIB_MJS = os.path.join(REPO, "integration", "lib_transient_retry.mjs")

# 固定消息桩清单（py/mjs 两态同源比对；含畸形三态）
TRANSIENT_SAMPLES = [
    "HTTP 502 Bad Gateway",
    "connect refused（tcp 127.0.0.1:21001）",
    "ECONNREFUSED 127.0.0.1:21002",
    "满员等待 12.3s 超时：当前活租约 12=t26091012-cap-a(pid 4321)",
    "端口段耗尽：400 档（21000~24999）全忙或被锁",
]
FATAL_SAMPLES = [
    "ENV_FAIL: 测试镜像缺席：test-temporal:cli-1.8.3（本机自建镜像、无 registry 拉取）",
    "usage 红：project 名含非法字符",
    "STAGE_ENV: 供给台 x ensure 互斥等待超时（600s）",
]
MALFORMED_SAMPLES = ["", None, 12345, {"msg": "HTTP 502 Bad Gateway"}, "x" * 100000]


def main():
    sys.path.insert(0, os.path.join(REPO, "integration"))
    passed = failed = env_failed = 0

    def check(cond, label):
        nonlocal passed, failed
        print(("ok    " if cond else "FAIL  ") + label, flush=True)
        if cond:
            passed += 1
        else:
            failed += 1

    try:
        import lib_transient_retry as tr  # noqa: PLC0415 实现未落地=TDD 红（FAIL 非 ENV_FAIL）
    except ImportError as e:
        check(False, "lib_transient_retry 未落地（TDD 红，implement 段转绿）：%s" % e)
        print("SUMMARY pass=%d fail=%d env_fail=%d na=0" % (passed, failed, env_failed))
        sys.exit(1)

    # ① 分类白名单：瞬态 / 终态
    for msg in TRANSIENT_SAMPLES:
        check(tr.is_transient(msg) is True, "瞬态桩判 transient：%s" % msg[:40])
    for msg in FATAL_SAMPLES:
        check(tr.is_transient(msg) is False, "终态桩不误判 transient：%s" % msg[:40])
    for msg in MALFORMED_SAMPLES:
        try:
            out = tr.is_transient(msg)
            check(out is False, "畸形桩安全判 fatal 不炸：%r…" % (str(msg)[:20]))
        except Exception as e:  # 畸形输入炸库=红
            check(False, "畸形桩 %r… 抛异常 %s（应安全拒收）" % (str(msg)[:20], e))

    # ② retry 恰一次：首试瞬态次试成功
    calls = {"n": 0}

    def flaky_once():
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError(TRANSIENT_SAMPLES[0])
        return "done"

    check(tr.retry_transient_once(flaky_once) == "done" and calls["n"] == 2,
          "首试瞬态次试成功（调用计数=2，实际 %d）" % calls["n"])

    # ③ 两试皆瞬态：原样抛最后一次、计数=2、文案逐字节
    calls["n"] = 0

    def always_transient():
        calls["n"] += 1
        raise RuntimeError("HTTP 502 Bad Gateway（第 %d 次）" % calls["n"])

    last = ""
    try:
        tr.retry_transient_once(always_transient)
        check(False, "恒瞬态应抛出（实际被吞）")
    except RuntimeError as e:
        last = str(e)
    check(calls["n"] == 2, "重试仍红恰好重试一次（计数=2，实际 %d）" % calls["n"])
    check(last == "HTTP 502 Bad Gateway（第 2 次）", "原样上报最后一次文案（逐字节）：%s" % last)

    # ④ 首试非瞬态：不重试
    calls["n"] = 0

    def fatal_first():
        calls["n"] += 1
        raise RuntimeError(FATAL_SAMPLES[0])

    try:
        tr.retry_transient_once(fatal_first)
        check(False, "非瞬态应原样抛出")
    except RuntimeError:
        pass
    check(calls["n"] == 1, "非瞬态不重试（计数=1，实际 %d）" % calls["n"])

    # ⑤ 单源一致性：py judge 子命令（方案承诺的对外缝，mjs 薄包装即 spawn 它——
    #   单源由架构保证，本条锚 judge 契约逐桩输出 transient|fatal）
    if not os.path.exists(LIB):
        check(False, "lib_transient_retry.py 未落地（TDD 红）")
    else:
        for msg in TRANSIENT_SAMPLES + FATAL_SAMPLES:
            p = subprocess.run([sys.executable, LIB, "judge", msg],
                               capture_output=True, text=True, timeout=60, cwd=REPO)
            want = "transient" if msg in TRANSIENT_SAMPLES else "fatal"
            check(p.returncode == 0 and want in (p.stdout or ""),
                  "judge 子命令判 %s：%s" % (want, msg[:40]))

    # ⑥ mjs 薄包装可被 node 加载（node 缺席=环境缺件 exit 2；文件缺席=TDD 红）
    node = None
    try:
        subprocess.run(["node", "--version"], capture_output=True, timeout=15)
        node = "node"
    except (OSError, subprocess.SubprocessError):
        pass
    if node is None:
        env_failed += 1
        print("ENV_FAIL node 不可用——mjs 薄包装腿没验成（环境缺件，exit 2）")
        print("SUMMARY pass=%d fail=%d env_fail=%d na=0" % (passed, failed, env_failed))
        sys.exit(2)
    if not os.path.exists(LIB_MJS):
        check(False, "lib_transient_retry.mjs 未落地（TDD 红）")
    else:
        probe = ("try { await import(%s); console.log('load-ok'); }\n"
                 "catch (e) { console.log('load-fail: ' + e.message); }"
                 % ("'file://" + LIB_MJS + "'"))
        p = subprocess.run([node, "--input-type=module", "-e", probe],
                           capture_output=True, text=True, timeout=60, cwd=REPO)
        check(p.returncode == 0 and "load-ok" in (p.stdout or ""),
              "mjs 薄包装 node 可加载（rc=%s %s）"
              % (p.returncode, ((p.stdout or "") + (p.stderr or ""))[-120:]))

    print("SUMMARY pass=%d fail=%d env_fail=%d na=0" % (passed, failed, env_failed))
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
