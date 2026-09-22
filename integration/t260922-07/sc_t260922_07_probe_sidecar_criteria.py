#!/usr/bin/env python3
"""探针判据精度收口·正文/侧车分流（t260922-07，registry: t260922-07-probe-sidecar-criteria）。

意图（灰盒，全量判据见 registry intent；判据只落探针 CLI 公开面——旗标/退出码/台账行，
探针内部实现重构不破）：
对 integration/t260916-24/probe_dsh_seam.py --selftest 的台账输出断言（秒级离线零网络）：

- ① 0.1.5 侧车 session.lock 显式单列为 INVENTORY 行（点名文件名），且 vN-sidecar 金样本
  档整体 → 绿——侧车不再被收进「会话正文清单」造成假红（live-run-260922.md 第 1 条的
  判据精度收口面）；
- ② 0.1.1 判据逐字不变：golden/v0-full 台账 10 行冻结逐字在案（本文件常量＝改前实跑
  快照 260922，与方案 §3 步骤 1 的 UT 冻结同源同值）；
- ③ 不放宽反方向：篡改档 tampered/bad-filename（session.v3.jsonl.gz，两代口径均不匹配）
  仍按「a 文件名口径」红；全程无任何含 session.lock 的 FAIL 行（豁免不许做成吞红的
  静默，也不许把侧车重新收回来）；
- ④ selftest 退出码 0（探针不腐锚）。

intent 分工：t260916-24-dsh-probe-selftest 守探针断言逻辑正负自检整体不腐（含本票扩档
后的全集）；本条只守本票判据精度收口的用户可感知面（侧车单列 + 0.1.1 逐字 + 篡改仍红
三向）。实现落地前红属预期（TDD 信号：①侧车档/单列行缺席），arbitrate/merge 期必须绿。
探针缺席 = ENV_FAIL exit 2 点名。
"""
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
PROBE = REPO / "integration" / "t260916-24" / "probe_dsh_seam.py"
sys.path.insert(0, str(REPO / "integration"))
from lib_env import EXIT_FAIL, EXIT_PASS, env_fail  # noqa: E402

SELFTEST_TIMEOUT_SEC = 120  # 实测秒级；上界只为场景自身不挂死

# 0.1.1 判据逐字不变锚（票面验收①后半）：golden/v0-full 台账 10 行，逐字冻结自
# 改前实跑（260922，python3 probe_dsh_seam.py --selftest）。改动后必须原序逐字在案。
V0_GOLDEN_BLOCK = (
    "[PASS] a 文件名口径：probe/t260916-24-gen0/session.jsonl → v0 代口径",
    "[PASS] 完整性（坏行/半行/坏帧）：全部记录可解析",
    "[PASS] b 必填面 provider/model：provider='probe-provider' model='probe-model-X'"
    "（context 主/header 备）",
    "[PASS] b 必填面 usage：inputTokens/outputTokens 均可取整型",
    "[PASS] b 可选面 cacheReadTokens：在场且整型（max=3）",
    "[PASS] b+ 消费必需型：assistant/message ×1",
    "[PASS] b+ 消费必需型：request/context ×1",
    "[PASS] b+ 消费必需型：request/header ×1",
    "[INVENTORY] b+ 族内类型：assistant/chunk ×1（属于 v0.1.1 族；漂移不影响本票判据，"
    "底册交 T5）",
    "[PASS] d 钉模型生效：实际 provider/model == 期望（probe-provider/probe-model-X）",
)


def main():
    if not PROBE.is_file():
        env_fail("缺被测探针 %s" % PROBE)
    p = subprocess.run([sys.executable, str(PROBE), "--selftest"],
                       capture_output=True, text=True, timeout=SELFTEST_TIMEOUT_SEC)
    out = p.stdout
    lines = out.splitlines()
    legs = []

    def check(name, ok, detail=""):
        legs.append(bool(ok))
        print("[%s] %s%s" % ("PASS" if ok else "FAIL", name, ("：" + detail) if detail else ""))

    # ④ 探针不腐锚（绿档；本票改动不许把自检跑红）
    check("selftest 退出码 0（探针不腐）", p.returncode == 0,
          "rc=%r stderr_tail=%r" % (p.returncode, (p.stderr or "")[-120:]))

    # ① 侧车显式单列：INVENTORY 行点名 session.lock（改前：无此行——侧车被混进正文
    # 清单只在 .lock 触发 FAIL 时才露面）；实现落地前红=TDD 信号
    sidecar_rows = [ln for ln in lines
                    if ln.startswith("[INVENTORY]") and "session.lock" in ln]
    check("侧车显式单列 INVENTORY 行（session.lock 点名在案，不计入正文计数）",
          bool(sidecar_rows),
          "改后应单列点名；改前无此行=TDD 红（本条原因正是侧车判据未收口）"
          if not sidecar_rows else sidecar_rows[0][:140])

    # ① 后半：vN-sidecar 金样本档整体绿（正文判据不因侧车在场而红）
    sidecar_verdict = next((ln for ln in lines
                            if "金样本 golden/vN-sidecar" in ln), None)
    check("侧车金样本档 vN-sidecar → 绿（正文判据行与 vN-full 同口径）",
          sidecar_verdict is not None and "→ 绿" in sidecar_verdict,
          sidecar_verdict or "vN-sidecar 档缺席=TDD 红（fixtures/金样本未扩）")

    # ③ 反方向：侧车永不产生 FAIL 行（豁免不许做成「照样收、照样红」的假红，
    # 也不许「收进来但不报」的静默——红行缺席+INVENTORY 单列在场合取才两头都锁）
    lock_fails = [ln for ln in lines if ln.startswith("[FAIL]") and "session.lock" in ln]
    check("无任何含 session.lock 的 FAIL 行（侧车假红绝迹）", not lock_fails,
          lock_fails[0][:140] if lock_fails else "")

    # ② 0.1.1 逐字不变：冻结块原序逐字在案（连续出现，位置不锚——台账排版可漂，
    # 行字面不许漂）
    hit = next((i for i in range(len(lines) - len(V0_GOLDEN_BLOCK) + 1)
                if tuple(lines[i:i + len(V0_GOLDEN_BLOCK)]) == V0_GOLDEN_BLOCK), None)
    check("0.1.1 金样本台账 10 行逐字不变（v0-full 冻结块原序在案）", hit is not None,
          "首处失配行=%r" % next((l for i, l in enumerate(lines)
                                  if i < len(V0_GOLDEN_BLOCK) and l != V0_GOLDEN_BLOCK[i]), "")
          if hit is None else "块首行号=%d" % (hit + 1))

    # ③ 反方向：.gz 篡改形仍按断言 a 红（非正文=不豁免；改前实锤该档 12 FAIL 命中
    # 「a 文件名口径」——收窄后无论按「不匹配」还是「无正文产物」翻红，命中断言名
    # 必须仍是 a，不许静默放行）
    gz = next((ln for ln in lines
               if "篡改档 tampered/bad-filename" in ln and "→ 红" in ln), None)
    check("篡改档 bad-filename（session.v3.jsonl.gz）仍按「a 文件名口径」红",
          gz is not None and "'a 文件名口径'" in gz,
          gz or "bad-filename 档红行缺席（放行=假绿方向，本条红即对）")

    print("== SUMMARY：PASS=%d FAIL=%d ==" % (legs.count(True), legs.count(False)))
    sys.exit(EXIT_PASS if all(legs) else EXIT_FAIL)


if __name__ == "__main__":
    main()
