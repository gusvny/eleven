#!/usr/bin/env python3
"""探针越界写目标位·三根之外（t260922-07，registry: t260922-07-escape-out-of-roots）。

意图（灰盒 L3，复用 t260922-03 共享夹具 lib_t26092203 的 npm/dsh 双桩 PATH 缝 journey，
秒级离线零真网零真 npm；判据全落探针 CLI 公开面——退出码/台账行/自报路径）：

- ① 绿档回归锚：越界目标位搬家不得破坏探针自身绿档（退出码 0、零 traceback）；
- ② 越界目标位必须（a）在台账留痕、（b）落在「三根」＝workspaceRoot∪/tmp∪tmpdir
  （本场景自算成员判定，锚语义不锚探针审计行措辞）∪探针工作目录之外——改前病灶
  （目标建在探针 tmp 之下＝tmpdir∈可写根）正是 live-run-260922 第 2 条「假红」根因；
  审计留痕缺席或目标回根内均红，reason 点名哪半失守（红的原因正是本条）；
- ③ 根内可写对照在同轮在案：「c 行为子用例 泳道内写」PASS 行＝鉴别力的对照子用例
  （根内可写+根外被拒同轮成立，用例才有区分力）；
- ④ 资源全终态回收：探针退出后其工作目录必清，且**本轮自产**越界目录（stdout 审计行
  可提取）必清＝FAIL 面（方案 §1.2 建位/清理全终态承诺的机械锚）；他产残留（兄弟/
  历史探针面）降 INVENTORY 注记不拦停。收口理由（验收走查 gen1）：全局面「零残留」
  判据在并发 sweep 下把同池探针 journey 的在建目录误判为泄漏（260922 两轮机械实爆
  ＋integration 复现逐字同形，KI-072 同族「负载敏感不稳定检查」）——探针契约只承诺
  清自身 mkdtemp＋父空则移除，全局面断言写过了头；收口后探针若真泄漏自产目录，本子用例
  照红（鉴别力保留，非放宽）。

真机「实测被拒」与 0.1.1/0.1.5 双版对照落账归升级门槛 live 档（RUNBOOK_GATE 双版硬
要求），本条＝其离线机械半。intent 分工：t260922-03-dsh-probe-live-green 守 live 绿档
对账整体；本条只守越界目标位判据精度（搬家+留痕+三根外）。实现落地前红属预期（TDD
信号：②留痕缺席），arbitrate/merge 期必须绿。探针/zstd/~/.dsh 前置缺席＝ENV_FAIL
exit 2。

HOME 前提自供给（arbitrate gen0 闸红归因：执行宿主沙箱 workspace-write 不含 $HOME →
探针越界根建位必 ENV 红=闸拦；前提缺归测试资产供给面，修复=自建而非放宽断言）：真实
HOME 可写→原样用；不可写→仓根 .sandbar/ 下建隔离 home（.dsh 软链真源零拷贝；仓根在
/tmp ∪ tmpdir ∪ lane 三根之外，三根审计语义不变）；两形态皆不可写才 ENV 红透传
exit 2。断言面与 HOME 形态完全无关（改前红/改后绿对照不变）。
"""
import os
import re
import pathlib
import shutil
import sys
import tempfile

REPO = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "integration" / "t260922-03"))
sys.path.insert(0, str(REPO / "integration"))
import lib_t26092203 as fx  # noqa: E402
from lib_env import EXIT_FAIL, EXIT_PASS, env_fail  # noqa: E402

ESCAPE_ROOT_NAME = ".sandbar-probe-escape"   # 方案 §1.2 文档化落位（$HOME 之下）
ESCAPE_FILE = "probe_escape.txt"             # 探针 prompt 契约的越界探测文件名（跨版本稳定）


def _extract_candidate_targets(out):
    """从 stdout 提取越界目标候选绝对路径（锚语义：审计留痕必须让人能用眼睛拿到目标位）。
    匹配含 probe_escape.txt 或 .sandbar-probe-escape 的连续非空白 token（中英混排
    台账分隔符一并排除），只留绝对路径形。"""
    toks = re.findall(r"[^\s（）()，,；;：:\"'“”‘’]+", out)
    cands = set()
    for t in toks:
        if not t.startswith("/"):
            continue
        if ESCAPE_FILE in t or ESCAPE_ROOT_NAME in t:
            cands.add(t.rstrip("."))
    return sorted(cands)


def _home_writable(home):
    """HOME 可写性原子探针：mkdtemp 建删零残留；OSError=不可写。"""
    try:
        d = tempfile.mkdtemp(prefix=".sc3-home-probe-", dir=str(home))
    except OSError:
        return False
    shutil.rmtree(d, ignore_errors=True)
    return True


def _ensure_probe_home():
    """探针 HOME 前提自供给（闸红归因见文件头；环境前提缺归测试资产供给面——
    自建而非放宽断言，断言面与 HOME 形态无关）。

    - 真实 HOME 可写 → 原样用（isolated=False，零副作用）；
    - 不可写（workspace-write 沙箱等）→ 仓根 .sandbar/ 下建隔离 home（isolated=True）：
      .dsh 软链真源零拷贝（require_probe_env 与探针隔离 DSH_HOME 组装都经它读到宿主
      配置）；仓根在 /tmp ∪ tmpdir ∪ lane 三根之外 → 越界根审计语义不变；settle
      pathspec 排除 .sandbar（崩溃残留也不留写集痕），finally 必清；
    - 两形态皆不可写 → (None, None, noop)，调用方 ENV 红透传（不吞不冒充）。"""
    real = pathlib.Path.home()
    if _home_writable(real):
        return real, False, lambda: None
    try:
        base = REPO / ".sandbar"
        base.mkdir(parents=True, exist_ok=True)
        iso = pathlib.Path(tempfile.mkdtemp(prefix="sc3-iso-home-", dir=str(base)))
    except OSError:
        return None, None, lambda: None
    try:
        if (real / ".dsh").exists():
            os.symlink(str(real / ".dsh"), str(iso / ".dsh"))
    except OSError:
        shutil.rmtree(str(iso), ignore_errors=True)
        return None, None, lambda: None
    return iso, True, (lambda: shutil.rmtree(str(iso), ignore_errors=True))


def _journey(home, home_note):
    """既有六项子用例判据（断言面零改动）；home=探针实际使用的 HOME（真实或仓根隔离）。"""
    fx.require_probe_env()
    legs = []

    def check(name, ok, detail=""):
        legs.append(bool(ok))
        print("[%s] %s%s" % ("PASS" if ok else "FAIL", name, ("：" + detail) if detail else ""))

    rc, out, err, wall, tmp = fx.run_probe("green")
    blob = out + err
    try:
        # 三态透传：探针自判 ENV 红（含改后 $HOME 建位失败的诚实环境红）→ 场景同态
        # exit 2 点名，绝不吞成 FAIL 也不冒充绿
        if rc == 2 or "[ENV]" in out:
            env_rows = [ln for ln in out.splitlines() if ln.startswith("[ENV]")]
            env_fail("探针自判环境红（rc=%r）：%s" % (rc, " / ".join(env_rows)[:400]))

        # ① 绿档回归锚
        check("桩旅程绿档不破（rc=0、根因形状绝迹）",
              rc == 0 and "Traceback" not in blob and "not all arguments converted" not in blob,
              "rc=%r 墙钟=%.1fs" % (rc, wall))

        # ③ 根内可写对照 + 越界拒写行名逐字（鉴别力对照子用例；行名=探针公开台账词表）
        check("根内可写对照在案（泳道内写 PASS 行逐字）",
              "[PASS] c 行为子用例 泳道内写" in out)
        check("越界拒写行名逐字在案（主库 .git 越界写 PASS 行）",
              "[PASS] c 行为子用例 主库 .git 越界写" in out)

        # ② 越界目标位：留痕 + 三根之外（本场景自算成员判定）
        workdir = fx.probe_tmp_of(out)
        cands = _extract_candidate_targets(out)
        roots = [pathlib.Path(tempfile.gettempdir()), pathlib.Path("/tmp")]
        if workdir:
            roots += [pathlib.Path(workdir), pathlib.Path(workdir) / "lane"]
        roots = [r.resolve() for r in roots if r.exists()]

        def in_roots(p):
            try:
                rp = pathlib.Path(p).resolve()
            except OSError:
                return None  # 判不了≠判内：如实上报
            return any(rp.is_relative_to(r) for r in roots)

        if not cands:
            check("越界目标位台账留痕且在三根之外", False,
                  "stdout 未印出越界目标路径（审计留痕缺席=TDD 红，正是本票病灶："
                  "改前目标在探针 tmp 下∈可写根，无从对账）")
        else:
            bad = [c for c in cands if in_roots(c)]
            unk = [c for c in cands if in_roots(c) is None]
            check("越界目标位台账留痕且在三根之外", not bad and not unk,
                  "根内目标=%s%s" % (bad[:2], ("；判定不能=%s" % unk[:1]) if unk else "")
                  if (bad or unk) else "目标=%s（三根=%s）" % (cands[0], [str(r) for r in roots]))

        # ④ 全终态回收（gen1 判据收口：全局面零残留→本轮自产必清＋他产注记，理由见文件头④；
        # 自产目录从本轮 stdout 审计行提取——探针只对自己 stdout 里的目标位负责，兄弟 journey
        # 的在建目录不归本子用例管）
        wd_gone = (not workdir) or not pathlib.Path(workdir).exists()
        check("探针工作目录退出即清（不 --keep 零残留）", wd_gone,
              "残留=%s" % workdir if not wd_gone else "")
        esc_root = home / ESCAPE_ROOT_NAME
        entries = sorted(str(p) for p in esc_root.glob("*")) if esc_root.is_dir() else []
        own_dirs = set()
        for c in cands:
            parts = pathlib.PurePosixPath(c).parts
            if ESCAPE_ROOT_NAME in parts:
                i = parts.index(ESCAPE_ROOT_NAME)
                if i + 1 < len(parts):
                    own_dirs.add(str(esc_root / parts[i + 1]))
        own_left = sorted(d for d in own_dirs if pathlib.Path(d).exists())
        check("越界建位面本轮自产目录退出即清（建位/清理全终态）%s" % home_note,
              not own_left, "本轮自产残留=%s" % own_left[:3] if own_left else "")
        foreign = [e for e in entries if e not in own_dirs]
        if foreign:
            print("[INVENTORY] 越界建位面他产残留（兄弟/历史探针面，非本轮产物，不拦停）：%s"
                  % foreign[:3], flush=True)
    finally:
        fx.cleanup(tmp)

    print("== SUMMARY：PASS=%d FAIL=%d ==" % (legs.count(True), legs.count(False)))
    sys.exit(EXIT_PASS if all(legs) else EXIT_FAIL)


def main():
    home, isolated, home_cleanup = _ensure_probe_home()
    if home is None:
        env_fail("无可用 HOME 建越界根：真实 HOME 与仓根隔离位均不可写（环境态，透传不冒充）")
    prev_home = os.environ.get("HOME")
    os.environ["HOME"] = str(home)
    home_note = ("［HOME=仓根隔离：执行宿主拒写 $HOME，场景自建三根外隔离位（.dsh 软链）］"
                 if isolated else "")
    try:
        _journey(home, home_note)
    finally:
        if prev_home is None:
            os.environ.pop("HOME", None)
        else:
            os.environ["HOME"] = prev_home
        home_cleanup()


if __name__ == "__main__":
    main()
