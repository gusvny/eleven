#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""t260902-09 集成测试 it01 —— 暂存凭据合并刷新故障面矩阵（integration 独立黑盒组）。

本件与 developer 自检 t01_creds_merge.py 并存（独立 oracle，不互相替代）：本件从
用户可感知行为与故障面出发独立设计——外部输入三态（缺失/畸形/演化）、写回资源
回收、软依赖降级、追加点安全。被测边界 = 引擎读侧凭据 seam
（agent_activities._copy_creds 及其合并路径），黑盒断言只落在文件系统可观察行为。

夹具一律真实嵌套格式（version + refs，见本票 plan.md「格式载体」），全 tmp/env 桩，
绝不触真 ~/.sandbar、真 ~/.dsh。依赖 PyYAML 的用例在无 yaml 且无 temporal-poc
venv 的解释器上干净 SKIP（integration/README.md 执行契约：依赖缺失=skip）。
跑法：PY=server/dsh/temporal-poc/.venv/bin/python; "$PY" integration/t260902-09/it01_creds_merge_blackbox.py
末行 SUMMARY pass=N skip=N fail=N，fail>0 退出码 1。
"""
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))
import fixture as fx  # noqa: E402

# 夹具叶子（纯虚构值，非真 key）
K_DEEPSEEK, V_DEEPSEEK = "DEEPSEEK_API_KEY", "sk-fixture-deepseek-old"
K_ZAI, V_ZAI = "ZAI_CODING_CN_API_KEY", "sk-fixture-zai-coding-cn-new"

YAML_BLOCKED_ENV = "T26090209_IT01_YAML_BLOCKED"


def _mode_of(p):
    return os.stat(p).st_mode & 0o777


def _run_copy(aa, sb, key="suyou"):
    # 对齐真实调用链：_prepare_agent_spawn 先 mkdir 本地 .dsh 再调 _copy_creds
    # （_copy_creds 契约不建目录），测试侧同序补目录。
    d = sb.lane / ".dsh"
    d.mkdir(parents=True, exist_ok=True)
    aa._copy_creds(d, key)


def run_child_yaml_blocked():
    """子进程模式：sys.modules 塞 None 模拟 PyYAML 软依赖缺失，
    断言合法 dst+src 降级 no-op（不抛错、dst 字节原样）。"""
    sys.modules["yaml"] = None  # import yaml → ImportError
    aa = fx.load_agent_activities()
    ok = False
    with fx.Sandbox() as sb:
        dst_text = fx.creds_text([(K_DEEPSEEK, V_DEEPSEEK)])
        sb.write_dst(dst_text, mode=0o600)
        sb.perkey("suyou", fx.creds_text([(K_DEEPSEEK, V_DEEPSEEK), (K_ZAI, V_ZAI)]))
        try:
            _run_copy(aa, sb)
            ok = sb.dst().read_text("utf-8") == dst_text
        except Exception:
            ok = False
    print("E2-CHILD %s" % ("ok" if ok else "fail"))
    return 0 if ok else 1


def main():
    if os.environ.get(YAML_BLOCKED_ENV) == "1":
        return run_child_yaml_blocked()

    aa = fx.load_agent_activities()
    yaml_ok = fx.ensure_yaml()
    L = fx.Ledger()

    print("== A 外部输入缺失态（现状回归，yaml-free）==")
    # A1 dst 缺失 + per-key 源 → 整拷字节等值、0600 保留
    with fx.Sandbox() as sb:
        src = sb.perkey("suyou", fx.creds_text([(K_DEEPSEEK, V_DEEPSEEK)]), mode=0o600)
        _run_copy(aa, sb)
        L.ok(sb.dst().is_file(), "A1 dst 缺失时整拷落位")
        L.ok(sb.dst().read_text("utf-8") == src.read_text("utf-8"),
             "A1 整拷与源字节等值")
        L.ok(_mode_of(sb.dst()) == 0o600, "A1 整拷 mode 0600 保留",
             oct(_mode_of(sb.dst())))
    # A2 dst 缺失 + 空 project_key → legacy 照拷（=M1-2 前行为）
    with fx.Sandbox() as sb:
        lg = sb.legacy("version: 9\nrefs:\n  LEGACY_ONLY: lv\n")
        _run_copy(aa, sb, key="")
        L.ok(sb.dst().read_text("utf-8") == lg.read_text("utf-8"),
             "A2 空 key 走 legacy 照拷")
    # A3 dst 已 staged + 源三处皆无 → 静默跳过、dst 原样（不造默认凭据）
    with fx.Sandbox() as sb:
        dst_text = fx.creds_text([(K_DEEPSEEK, V_DEEPSEEK)])
        sb.write_dst(dst_text)
        _run_copy(aa, sb)
        L.ok(sb.dst().read_text("utf-8") == dst_text, "A3 源缺失快照原样")

    print("== B dst 畸形三态（yaml-free）==")
    for label, bad in [
        ("B1 dst refs 是列表", "version: 1\nrefs:\n  - a\n  - b\n"),
        ("B2 dst 顶层是列表", "- just\n- a list\n"),
        # 真·语法错（unclosed flow）。注意不能用「顶格键+缩进续行」当畸形样本：
        # 那是合法 YAML 多行纯标量，能解析通，实现按「dst 无 refs」合并是对的。
        ("B3 dst yaml 语法错", "version: 1\nrefs:\n  KEY: [unclosed\n"),
    ]:
        with fx.Sandbox() as sb:
            sb.write_dst(bad)
            sb.perkey("suyou", fx.creds_text([(K_ZAI, V_ZAI)]))
            threw = None
            try:
                _run_copy(aa, sb)
            except Exception as e:  # 约束②：解析失败不抛新错
                threw = e
            L.ok(threw is None, label + " 不抛错", threw)
            L.ok(sb.dst().read_text("utf-8") == bad, label + " 快照字节原样")

    print("== C src 畸形三态（外部输入=项目凭据，yaml-free）==")
    for label, bad in [
        ("C1 src refs 是列表", "version: 1\nrefs:\n  - a\n"),
        ("C2 src 顶层是列表", "- just\n- a list\n"),
        ("C3 src yaml 语法错", "version: 1\nrefs:\n  KEY [\n"),
    ]:
        with fx.Sandbox() as sb:
            dst_text = fx.creds_text([(K_DEEPSEEK, V_DEEPSEEK)])
            sb.write_dst(dst_text)
            sb.perkey("suyou", bad)
            threw = None
            try:
                _run_copy(aa, sb)
            except Exception as e:
                threw = e
            L.ok(threw is None, label + " 不抛错", threw)
            L.ok(sb.dst().read_text("utf-8") == dst_text, label + " 快照字节原样")

    print("== D dst refs inline 形态守卫（yaml-free）==")
    with fx.Sandbox() as sb:
        flow_text = "version: 1\nrefs: {" + K_DEEPSEEK + ": " + V_DEEPSEEK + "}\n"
        sb.write_dst(flow_text)
        sb.perkey("suyou", fx.creds_text([(K_ZAI, V_ZAI)]))
        threw = None
        try:
            _run_copy(aa, sb)
        except Exception as e:
            threw = e
        L.ok(threw is None, "D1 inline refs 不抛错", threw)
        L.ok(sb.dst().read_text("utf-8") == flow_text,
             "D1 inline refs 不做文本追加（防毁整份快照）")

    print("== E 资源回收与软依赖降级（yaml-free）==")
    # E1 写回失败（dst 目录只读）→ 快照原样、无 tmp 半成品残留
    if os.geteuid() != 0:
        with fx.Sandbox() as sb:
            dst_text = fx.creds_text([(K_DEEPSEEK, V_DEEPSEEK)])
            dstd = sb.write_dst(dst_text, mode=0o600).parent
            sb.perkey("suyou", fx.creds_text([(K_ZAI, V_ZAI)]))
            before = sorted(p.name for p in dstd.iterdir())
            os.chmod(dstd, 0o555)
            try:
                threw = None
                try:
                    _run_copy(aa, sb)
                except Exception as e:
                    threw = e  # fail-closed 上抛亦算可接受终态
                after = sorted(p.name for p in dstd.iterdir())
            finally:
                os.chmod(dstd, 0o755)  # 拆桩，保 tmp 清理
            L.ok(sb.dst().read_text("utf-8") == dst_text, "E1 写回失败快照原样")
            L.ok(after == before, "E1 目录无 tmp 半成品残留",
                 "%s -> %s" % (before, after))
    else:
        L.skip1("E1 写回失败资源回收", "euid=0，目录只读挡不住 root")
    # E2 PyYAML 软依赖缺失 → 合并降级 no-op、不抛错（子进程内模拟 import 失败）
    env = dict(os.environ)
    env[YAML_BLOCKED_ENV] = "1"
    env[fx.REEXEC_GUARD] = "1"  # 子进程不再 re-exec
    r = subprocess.run([sys.executable, os.path.abspath(__file__)], env=env,
                       capture_output=True, text=True, timeout=120)
    L.ok(r.returncode == 0 and "E2-CHILD ok" in r.stdout,
         "E2 yaml 缺失降级 no-op 不抛错", (r.stdout + r.stderr)[-300:])

    if not yaml_ok:
        L.skip1("F 组合并正路径（11 用例）",
                "PyYAML 不可用且无 temporal-poc venv（venv=%s）" % fx.VENV_PY)
        return L.finish()

    print("== F 合并正路径（演化态 + 追加点安全）==")
    # F1 KI-016 复现：老快照缺新 provider 叶子，源有 → 可见；且合并=仅追加
    with fx.Sandbox() as sb:
        dst_text = fx.creds_text([(K_DEEPSEEK, V_DEEPSEEK), ("KIMI_CODING_API_KEY",
                                                              "sk-fixture-kimi-old")])
        sb.write_dst(dst_text, mode=0o600)
        sb.perkey("suyou", fx.creds_text(
            [(K_DEEPSEEK, V_DEEPSEEK), ("KIMI_CODING_API_KEY", "sk-fixture-kimi-old"),
             (K_ZAI, V_ZAI)]))
        _run_copy(aa, sb)
        merged = sb.dst().read_text("utf-8")
        refs = (fx.yaml_load(merged) or {}).get("refs") or {}
        L.ok(refs.get(K_ZAI) == V_ZAI, "F1 新 provider 叶子对老泳道可见", refs.get(K_ZAI))
        L.ok(fx.insertion_only(dst_text, merged),
             "F1 合并=仅整行插入（原行无改写无删除）")
        L.ok(_mode_of(sb.dst()) == 0o600, "F1 快照 mode 仍 0600")
    # F2 同名叶子冲突 → dst 值逐字胜出
    with fx.Sandbox() as sb:
        sb.write_dst(fx.creds_text([(K_DEEPSEEK, "sk-user-rotated-mid-ticket")]))
        sb.perkey("suyou", fx.creds_text([(K_DEEPSEEK, V_DEEPSEEK), (K_ZAI, V_ZAI)]))
        _run_copy(aa, sb)
        merged = sb.dst().read_text("utf-8")
        refs = (fx.yaml_load(merged) or {}).get("refs") or {}
        L.ok(refs.get(K_DEEPSEEK) == "sk-user-rotated-mid-ticket",
             "F2 冲突 dst 值胜出", refs.get(K_DEEPSEEK))
        L.ok(V_DEEPSEEK not in merged, "F2 src 冲突值未写入")
    # F3 dst 独有叶子保留
    with fx.Sandbox() as sb:
        sb.write_dst(fx.creds_text([(K_DEEPSEEK, V_DEEPSEEK), ("EXTRA_LOCAL_LEAF", "lv")]))
        sb.perkey("suyou", fx.creds_text([(K_DEEPSEEK, V_DEEPSEEK), (K_ZAI, V_ZAI)]))
        _run_copy(aa, sb)
        refs = (fx.yaml_load(sb.dst().read_text("utf-8")) or {}).get("refs") or {}
        L.ok(refs.get("EXTRA_LOCAL_LEAF") == "lv", "F3 dst 独有叶子保留")
    # F4 version 等 dst 顶层字段不动（src 顶层不搬）
    with fx.Sandbox() as sb:
        sb.write_dst(fx.creds_text([(K_DEEPSEEK, V_DEEPSEEK)], version="1"))
        sb.perkey("suyou", fx.creds_text([(K_ZAI, V_ZAI)], version="2",
                                         top_extra="note: seam-owned\n"))
        _run_copy(aa, sb)
        merged = sb.dst().read_text("utf-8")
        L.ok(merged.startswith("version: 1\n"), "F4 dst version 原样")
        L.ok("note:" not in merged and "version: 2" not in merged,
             "F4 src 顶层字段未搬入")
    # F5 无新增叶子 → 零写回（字节与 mtime 均不变）
    with fx.Sandbox() as sb:
        dst_text = fx.creds_text([(K_DEEPSEEK, V_DEEPSEEK)])
        p = sb.write_dst(dst_text)
        sb.perkey("suyou", fx.creds_text([(K_DEEPSEEK, V_DEEPSEEK)]))
        os.utime(p, (1000000000, 1000000000))
        _run_copy(aa, sb)
        L.ok(p.read_text("utf-8") == dst_text, "F5 零新增不写回（字节不变）")
        L.ok(os.stat(p).st_mtime == 1000000000, "F5 零新增 mtime 不变",
             os.stat(p).st_mtime)
    # F6 幂等：合并后重跑 → 内容不变、无重复行
    with fx.Sandbox() as sb:
        sb.write_dst(fx.creds_text([(K_DEEPSEEK, V_DEEPSEEK)]))
        sb.perkey("suyou", fx.creds_text([(K_DEEPSEEK, V_DEEPSEEK), (K_ZAI, V_ZAI)]))
        _run_copy(aa, sb)
        once = sb.dst().read_text("utf-8")
        _run_copy(aa, sb)
        twice = sb.dst().read_text("utf-8")
        L.ok(once == twice, "F6 重跑幂等（内容不变）")
        L.ok(once.count(K_ZAI) == 1, "F6 新叶子不重复", once.count(K_ZAI))
    # F7 legacy 回落源同样能合并刷新
    with fx.Sandbox() as sb:
        sb.write_dst(fx.creds_text([(K_DEEPSEEK, V_DEEPSEEK)]))
        sb.legacy(fx.creds_text([(K_DEEPSEEK, V_DEEPSEEK), (K_ZAI, V_ZAI)]))
        _run_copy(aa, sb)
        refs = (fx.yaml_load(sb.dst().read_text("utf-8")) or {}).get("refs") or {}
        L.ok(refs.get(K_ZAI) == V_ZAI, "F7 legacy 回落源合并刷新")
    # F8 dst 原 mode 非 0600 → 照抄 dst
    with fx.Sandbox() as sb:
        sb.write_dst(fx.creds_text([(K_DEEPSEEK, V_DEEPSEEK)]), mode=0o644)
        sb.perkey("suyou", fx.creds_text([(K_ZAI, V_ZAI)]))
        _run_copy(aa, sb)
        L.ok(_mode_of(sb.dst()) == 0o644, "F8 mode 照抄 dst（0644）",
             oct(_mode_of(sb.dst())))
    # F9 追加值 yaml 标量安全：数字形值保 string-ness、含空格值单行可解析
    # （夹具必须把数字形值写成带引号的 YAML 字符串——裸拼 `KEY: 123456` 在源文件
    # 里就已经是 int，实现做类型保真 re-dump 并无过错，string-ness 无从谈起）
    with fx.Sandbox() as sb:
        sb.write_dst(fx.creds_text([(K_DEEPSEEK, V_DEEPSEEK)]))
        sb.perkey("suyou", fx.creds_text([(K_DEEPSEEK, V_DEEPSEEK), (K_ZAI, V_ZAI)])
                  + "  NUM_LIKE_KEY: '123456'\n"
                  + "  SPACE_KEY: abc def\n")
        _run_copy(aa, sb)
        refs = (fx.yaml_load(sb.dst().read_text("utf-8")) or {}).get("refs") or {}
        L.ok(refs.get("NUM_LIKE_KEY") == "123456"
             and isinstance(refs.get("NUM_LIKE_KEY"), str),
             "F9 数字形值保字符串", repr(refs.get("NUM_LIKE_KEY")))
        L.ok(refs.get("SPACE_KEY") == "abc def", "F9 含空格值可解析",
             repr(refs.get("SPACE_KEY")))
    # F10 多行值叶子 → 整次不合并（文本追加保形不安全的保守面）
    with fx.Sandbox() as sb:
        dst_text = fx.creds_text([(K_DEEPSEEK, V_DEEPSEEK)])
        sb.write_dst(dst_text)
        sb.perkey("suyou", fx.creds_text([(K_DEEPSEEK, V_DEEPSEEK)]).rstrip("\n")
                  + "\n  MULTILINE_KEY: |\n    line1\n    line2\n")
        _run_copy(aa, sb)
        L.ok(sb.dst().read_text("utf-8") == dst_text, "F10 多行值守卫：快照原样")
    # F11 CRLF 快照 → 不做行级追加，快照原样
    # （必须按字节比：read_text 的 universal-newlines 会把 \r\n 读成 \n，
    #   字节零改动也会被误判成「被改写」）
    with fx.Sandbox() as sb:
        crlf = fx.creds_text([(K_DEEPSEEK, V_DEEPSEEK)]).replace("\n", "\r\n")
        sb.write_dst(crlf)
        sb.perkey("suyou", fx.creds_text([(K_ZAI, V_ZAI)]))
        _run_copy(aa, sb)
        L.ok(sb.dst().read_bytes() == crlf.encode("utf-8"), "F11 CRLF 快照原样（字节级）")

    return L.finish()


if __name__ == "__main__":
    sys.exit(main())
