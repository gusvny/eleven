# -*- coding: utf-8 -*-
"""t260902-09 t01 —— 泳道暂存凭据按 refs 叶子合并刷新（agent_activities._copy_creds/_merge_creds）。

KI-016 主回归：泳道 .dsh/.credentials.yaml 是 spawn 暂存快照，旧逻辑「目标已存在
即 return」让快照永不刷新——zai-coding-cn 0902 上线后老泳道 arbitrate 代理全部
MISSING_CREDENTIAL。新契约（t260902-09 plan.md，评审 gen1 通过）：
  - src refs 有、dst refs 缺的叶子 → 追加（写回 = 仅整行插入，insertion_only 钉死）；
  - 同名叶子 → dst 值绝对胜出（不抹工单中途换 key 现场）；
  - dst 独有叶子不删；version 等 seam 自管字段不动；
  - dst 畸形（refs 列表/顶层列表/语法错/inline 形态/裸标量）与 src 畸形
    （评审 H1）→ 不合并、快照原样、不抛新错；
  - 无新增叶子 → 零写回（字节与 mtime 均不变）。

夹具一律真实嵌套格式（version + refs），全 tmp/env 桩（lib/fixture.Sandbox），
不读真 ~/.sandbar 与 ~/.dsh。跑法（manifest 已登记 venv 回落链；裸 python3 会
经 ensure_yaml 自动 re-exec 进 venv，仍无 PyYAML 则干净 SKIP）：
  PY=server/dsh/temporal-poc/.venv/bin/python; "$PY" integration/t260902-09/t01_creds_merge.py
末行 SUMMARY pass=N skip=N fail=N，fail>0 退出码 1。
"""
import logging
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))
import fixture as fx  # noqa: E402

aa = fx.load_agent_activities()
L = fx.Ledger()
LOGS = []


class _Capture(logging.Handler):
    def emit(self, record):
        LOGS.append((record.levelname, record.getMessage()))


logging.getLogger("temporalio-stub").addHandler(_Capture())

# 真实嵌套格式（同 ~/.dsh/.credentials.yaml：version + refs 两级）
DST_STAGED = fx.creds_text([("DEEPSEEK_API_KEY", "sk-deepseek-dst"),
                            ("KIMI_CODING_API_KEY", "sk-kimi-dst")])
SRC_WITH_NEW_KEY = fx.creds_text([("DEEPSEEK_API_KEY", "sk-deepseek-src"),
                                  ("ZAI_CODING_CN_API_KEY", "sk-zai-cn-src")],
                                 version="2")


def ok(cond, label, detail=""):
    L.ok(cond, label, detail)


def refs_of(text):
    return (fx.yaml_load(text) or {}).get("refs") or {}


def warnings():
    return [m for lv, m in LOGS if lv == "WARNING"]


def mode_of(p):
    return os.stat(p).st_mode & 0o777


def spawn_dsh(sb):
    """spawn 前的本地 .dsh 目录（_prepare_agent_spawn 会 mkdir，被测函数不管建
    目录——测试侧自建，对齐真实调用链）。"""
    d = sb.dst().parent
    d.mkdir(parents=True, exist_ok=True)
    return d


def main():
    global yaml
    if not fx.ensure_yaml():
        L.skip1("合并回归整条", "PyYAML 不可用且无 venv 可 re-exec（合并路径软依赖）")
        return L.finish()
    import yaml  # ensure_yaml 之后必可达（本解释器或 re-exec 进的 venv）

    # 1. KI-016 主回归：staged 快照 + 源新增 zai-coding-cn key → 合并后可见
    with fx.Sandbox() as sb:
        sb.write_dst(DST_STAGED)
        sb.perkey(text=SRC_WITH_NEW_KEY)
        before = sb.dst().read_text("utf-8")
        aa._copy_creds(spawn_dsh(sb), "suyou")
        text = sb.dst().read_text("utf-8")
        refs = refs_of(text)
        ok(refs.get("ZAI_CODING_CN_API_KEY") == "sk-zai-cn-src",
           "KI-016 复现：新增叶子可见", text)
        ok(refs.get("DEEPSEEK_API_KEY") == "sk-deepseek-dst", "同名叶子 dst 值胜出")
        ok(refs.get("KIMI_CODING_API_KEY") == "sk-kimi-dst", "dst 独有叶子保留")
        ok((fx.yaml_load(text) or {}).get("version") == 1, "version 等 seam 字段不动")
        ok(text.count("version:") == 1, "src 顶层不搬（version 未被覆盖）")
        ok(sb.root.joinpath("suyou/credentials.yaml").read_text("utf-8") == SRC_WITH_NEW_KEY,
           "源文件未被改写")
        ok(fx.insertion_only(before, text), "写回=仅整行插入（原行零改写零删除）")

    # 2. dst 缺失 → 整拷（现状回归），mode 0600 保留
    with fx.Sandbox() as sb:
        sb.perkey(text=SRC_WITH_NEW_KEY, mode=0o600)
        aa._copy_creds(spawn_dsh(sb), "suyou")
        out = sb.dst()
        ok(out.is_file() and out.read_text("utf-8") == SRC_WITH_NEW_KEY, "dst 缺失整拷字节等值")
        ok(mode_of(out) == 0o600, "整拷 mode 0600", oct(mode_of(out)))

    # 3. 无新增叶子 → 零写回（字节与 mtime 均不变；先拨旧 mtime 防同秒蒙混）
    with fx.Sandbox() as sb:
        sb.write_dst(DST_STAGED)
        sb.perkey(text=fx.creds_text([("DEEPSEEK_API_KEY", "other")], version="9"))
        dstf = sb.dst()
        os.utime(dstf, (1000000, 1000000))
        before = dstf.read_text("utf-8")
        aa._copy_creds(dstf.parent, "suyou")
        ok(dstf.read_text("utf-8") == before, "无新增叶子零写回（字节）")
        ok(os.stat(dstf).st_mtime == 1000000, "无新增叶子零写回（mtime）")

    # 4. dst 畸形五态：不抛错、字节原样、有 warning（含 H2 inline 形态守卫）
    for label, bad in [
        ("refs 是列表", "version: 1\nrefs:\n  - a\n  - b\n"),
        ("顶层是列表", "- a\n- b\n"),
        ("yaml 语法错", "version: 1\nrefs:\n  DEEPSEEK_API_KEY: [unclosed\n"),
        ("refs inline 形态", "version: 1\nrefs: {DEEPSEEK_API_KEY: x}\n"),
        ("裸标量（扁平老格式）", "just-a-plain-string\n"),
    ]:
        with fx.Sandbox() as sb:
            sb.write_dst(bad)
            sb.perkey(text=SRC_WITH_NEW_KEY)
            before = sb.dst().read_text("utf-8")
            del LOGS[:]
            err = ""
            try:
                aa._copy_creds(spawn_dsh(sb), "suyou")
            except Exception as ex:  # 不抛新错是硬约束
                err = str(ex)
            ok(err == "", "dst 畸形不抛错（%s）" % label, err)
            ok(sb.dst().read_text("utf-8") == before, "dst 畸形字节原样（%s）" % label)
            ok(len(warnings()) > 0, "dst 畸形有 warning（%s）" % label)

    # 5. src 畸形三态（评审 H1：源是本方案消费的第一外部输入）→ 不抛错、dst 原样
    for label, bad in [
        ("src refs 是列表", "version: 2\nrefs:\n  - a\n"),
        ("src 顶层是列表", "- a\n- b\n"),
        ("src yaml 语法错", "version: 2\nrefs: [unclosed\n"),
    ]:
        with fx.Sandbox() as sb:
            sb.write_dst(DST_STAGED)
            sb.perkey(text=bad)
            before = sb.dst().read_text("utf-8")
            del LOGS[:]
            err = ""
            try:
                aa._copy_creds(spawn_dsh(sb), "suyou")
            except Exception as ex:
                err = str(ex)
            ok(err == "", "src 畸形不抛错（%s）" % label, err)
            ok(sb.dst().read_text("utf-8") == before, "src 畸形 dst 原样（%s）" % label)
            ok(len(warnings()) > 0, "src 畸形有 warning（%s）" % label)

    # 6. src 无 refs（扁平映射老格式）→ no-op 静默不合并（seam 只认 refs 叶子）
    with fx.Sandbox() as sb:
        sb.write_dst(DST_STAGED)
        sb.perkey(text="OLD_FLAT_KEY: sk-flat\n")
        before = sb.dst().read_text("utf-8")
        del LOGS[:]
        aa._copy_creds(spawn_dsh(sb), "suyou")
        ok(sb.dst().read_text("utf-8") == before, "src 无 refs 不合并且不报错")
        ok(len(warnings()) == 0, "src 无 refs 静默（无 warning）")

    # 7. 源缺失 → 现状口径：静默跳过，dst 不动（MISSING_CREDENTIAL 由引擎报）
    with fx.Sandbox() as sb:
        sb.write_dst(DST_STAGED)
        before = sb.dst().read_text("utf-8")
        aa._copy_creds(spawn_dsh(sb), "suyou")
        ok(sb.dst().read_text("utf-8") == before, "源缺失不抛错 dst 不动")

    # 8. 幂等：合并后重跑，无重复行、无变化
    with fx.Sandbox() as sb:
        sb.write_dst(DST_STAGED)
        sb.perkey(text=SRC_WITH_NEW_KEY)
        aa._copy_creds(spawn_dsh(sb), "suyou")
        once = sb.dst().read_text("utf-8")
        aa._copy_creds(spawn_dsh(sb), "suyou")
        twice = sb.dst().read_text("utf-8")
        ok(once == twice, "幂等：二次合并无变化")
        ok(twice.count("ZAI_CODING_CN_API_KEY:") == 1, "幂等：无重复叶子行")

    # 9. legacy 回落源同样能合并刷新
    with fx.Sandbox() as sb:
        sb.write_dst(DST_STAGED)
        sb.legacy(text=SRC_WITH_NEW_KEY)
        aa._copy_creds(spawn_dsh(sb), "suyou")
        refs = refs_of(sb.dst().read_text("utf-8"))
        ok(refs.get("ZAI_CODING_CN_API_KEY") == "sk-zai-cn-src", "legacy 回落源合并")
        ok(refs.get("DEEPSEEK_API_KEY") == "sk-deepseek-dst", "legacy 合并仍保 dst 胜出")

    # 10. dst 原 mode 非 0600 → 合并后照抄 dst（不硬编 0600）
    with fx.Sandbox() as sb:
        sb.write_dst(DST_STAGED, mode=0o644)
        sb.perkey(text=SRC_WITH_NEW_KEY)
        aa._copy_creds(spawn_dsh(sb), "suyou")
        ok(mode_of(sb.dst()) == 0o644, "合并后 mode 照抄 dst", oct(mode_of(sb.dst())))

    # 11. 特殊字符值 → yaml 标量安全序列化，合并产物可解析且值保真
    #     （夹具用 safe_dump 构造：裸拼会把值里的 # 当成 yaml 注释，测不到点）
    tricky = "#lead: 'q' val #tail"
    with fx.Sandbox() as sb:
        sb.write_dst(DST_STAGED)
        sb.perkey(text=yaml.safe_dump(
            {"version": 2, "refs": {"TRICKY_API_KEY": tricky}}, allow_unicode=True))
        aa._copy_creds(spawn_dsh(sb), "suyou")
        text = sb.dst().read_text("utf-8")
        ok(refs_of(text).get("TRICKY_API_KEY") == tricky, "特殊字符产物可解析", text)
        ok(refs_of(text).get("DEEPSEEK_API_KEY") == "sk-deepseek-dst", "特殊字符不毁既有行")

    # 11b. 多行标量值 → 拒绝合并（文本追加保形不安全），快照原样有 warning
    with fx.Sandbox() as sb:
        sb.write_dst(DST_STAGED)
        sb.perkey(text=yaml.safe_dump(
            {"version": 2, "refs": {"MULTI_API_KEY": "line1\nline2"}}, allow_unicode=True))
        before = sb.dst().read_text("utf-8")
        del LOGS[:]
        aa._copy_creds(spawn_dsh(sb), "suyou")
        ok(sb.dst().read_text("utf-8") == before, "多行值拒绝合并 dst 原样")
        ok(len(warnings()) > 0, "多行值有 warning")

    # 12. dst 无 refs 段 → 文件尾补 refs 块（seam 读 refs 才能看到新叶子）
    with fx.Sandbox() as sb:
        sb.write_dst("version: 1\n")
        sb.perkey(text=SRC_WITH_NEW_KEY)
        aa._copy_creds(spawn_dsh(sb), "suyou")
        text = sb.dst().read_text("utf-8")
        ok(refs_of(text).get("ZAI_CODING_CN_API_KEY") == "sk-zai-cn-src", "dst 无 refs 段补块", text)
        ok((fx.yaml_load(text) or {}).get("version") == 1, "补块后 version 仍不动")

    # 13. 4 空格缩进的 dst → 追加行随实测缩进（产物可解析）
    with fx.Sandbox() as sb:
        sb.write_dst("version: 1\nrefs:\n    DEEPSEEK_API_KEY: x\n")
        sb.perkey(text="version: 2\nrefs:\n  NEW_API_KEY: n\n")
        aa._copy_creds(spawn_dsh(sb), "suyou")
        text = sb.dst().read_text("utf-8")
        ok(refs_of(text).get("NEW_API_KEY") == "n", "4 空格缩进实测跟随", text)

    # 14. 不可读源 + dst 已存在 → 不抛新错、dst 原样（root 下权限不生效则 SKIP）
    if os.geteuid() != 0:
        with fx.Sandbox() as sb:
            sb.write_dst(DST_STAGED)
            before = sb.dst().read_text("utf-8")
            pk = sb.perkey(text=SRC_WITH_NEW_KEY, mode=0o000)
            err = ""
            try:
                aa._copy_creds(spawn_dsh(sb), "suyou")
            except Exception as ex:
                err = str(ex)
            finally:
                os.chmod(pk, 0o644)  # 拆桩：tmp 目录清理需要
            ok(err == "", "不可读源不抛新错", err)
            ok(sb.dst().read_text("utf-8") == before, "不可读源 dst 原样")
    else:
        L.skip1("不可读源", "当前 euid=0，权限不生效")

    # 15. 无残留 tmp（写回后同目录只应有 .credentials.yaml）
    with fx.Sandbox() as sb:
        sb.write_dst(DST_STAGED)
        sb.perkey(text=SRC_WITH_NEW_KEY)
        aa._copy_creds(spawn_dsh(sb), "suyou")
        leftovers = [p.name for p in sb.dst().parent.iterdir()
                     if p.name != ".credentials.yaml"]
        ok(leftovers == [], "无残留 tmp 文件", str(leftovers))

    return L.finish()


if __name__ == "__main__":
    sys.exit(main())
