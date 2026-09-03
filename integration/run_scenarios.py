#!/usr/bin/env python3
"""integration 场景执行器（manifest 退役后的项目声明道）。

约定：
- SCENARIOS = (name, intent, cmd[, pool]) 三元组或四元组——intent 是该场景守护的用户可
  感知行为/合同；pool 可选："main"（缺省，串行主池）/命名池（如 "ro" 只读并行池，
  与主池并行）/"exclusive"（独占全程）。同池串行保顺序，跨池并行提吞吐
  （评审一眼可见；intent 级重复禁止，步骤级共享允许）。
- 层次：单组件函数测试归 UT（temporal-poc/tests pytest、workbench/tests node 源级）；
  本清单只收跨组件场景、对外合同冻结、用户旅程与故障面对抗。
- 命名铁律：场景案例文件一律 sc_<slug>.py/.mjs——凡 sc_ 必须登记本清单，
  凡未登记的 sc_ = 孤儿（lint L5 红）；不带 sc_ 前缀的文件 = 共享/子检查代码，
  不登记、不报警（t260902 宿主令：约定胜过推断）。
- 一次性交付验收快照不入场（交付完成使命即终，t260902 宿主令重审定案）。
- cmd 以仓库根为 cwd、/bin/sh -c 执行，单条超时 900s；只用标准库。
- 清单只收本仓在位资产（L4 口径：cmd 引用脚本必须存在）。迁移种子中指向未迁移
  资产的 84 条悬空引用已移除；suyou 全量场景集与其资产留在 suyou 仓原位。
"""
import subprocess
import sys
import time

SCENARIOS = [
    ("t260903-10-installer-console-line",
     "3099 红线源码级静态守卫（交接单 §3 C1 全词表）：安装器入口+server/installer 全源对 kill/pkill/重启/spawn/start/launch × 3099/console 上下文零容忍、提示文案（请手动/操作面）白名单豁免区分提示与执行；扫描器自证红绿（干净样本绿+注入 pkill 副本红+含 start 的提示行豁免）；verify.yaml guard-3099-redline 为 2 词行级粗守卫，本场景为全词表+上下文窗细守卫不互替（t260903-10）",
     "python3 integration/t260903-10/sc_sandbar_installer_console_line.py", "ro"),
    ("t260903-10-installer-lifecycle",
     "安装器生命周期用户旅程（黑盒 CLI+fixture 仓注入+假 temporal 替身+临时 HOME 桩，经公共旗标 --root/--server-port/--ui-port 全程隔离，与真 7233/8233 零接触）：up 起 server（演练端口探活+状态真源 ~/.sandbar/run 落 pidfile）、status 必印「console 属用户操作面，请手动起停」、重复 up 幂等（监听者与 stub 自报 pid 恒为首发进程，不重复拉起）、down 先 worker 后 server（TERM 时间戳红线观测）且终态进程全灭+run 目录 pid 清空；所选端口被占=exit3 环境冲突不对抗（t260903-11 环境无关化重造）",
     "python3 integration/t260903-10/sc_sandbar_installer_lifecycle.py"),
    ("t260903-10-installer-orphan-claim",
     "认领契约 V1 三态进程演练（交接单 §2-#9+V1 钦点：down supervisor 持有的 server 必须「报告+不杀+不复活」绝不能杀后被复活）：supervisor 存活→只报告归属不认领（安装器对 ppid 做真 os.kill 存活交叉核对）；父死真孤儿且命令行谓词命中（temporal server start-dev+数据卷属本安装）→认领后 down 停掉；谓词不命中→显式报错不误杀；argv/ppid 观测面经 PATH 前置 ps 桩按登记表供数（本沙箱禁真 ps），存活与信号全走真内核语义；stub 全程自建不与真环境对抗（t260903-10；t260903-11 观测缝重造）",
     "python3 integration/t260903-10/sc_sandbar_installer_orphan_claim.py"),
    ("t260903-10-installer-fail-closed",
     "依赖故障显式红不静默（§2-#1/#8 fail-closed 家族 CLI 面，经公共旗标 --root 注入 fixture 仓驱动真实拉起路径）：temporal 可执行缺失→up 非零且报错点名 temporal；假 temporal 秒退→30s 量级超时内非零显式失败且启动超时子进程就地回收显式声明；status 空态零退出不崩不误报且必印 3099 红线提示（t260903-10；t260903-11 环境无关化重造）",
     "python3 integration/t260903-10/sc_sandbar_installer_fail_closed.py"),
    ("t260903-10-doctor-compat-matrix",
     "doctor 一条命令全量探针→兼容矩阵落盘契约（契约⑧-3 三轴）：缺省 fixture 档（不起真 dsh、HOME 桩隔离）doctor 零退出、~/.sandbar/compat-matrix.json 恰 4 行（四面全绿=绿一行 append 一行）、行含 sandbar 版本（单源仓根 VERSION，字面量锚退役 t260903-12）与 dsh 已验证点 0.1.1-rc.2、重复 doctor 幂等行集合不变、坏 JSON 矩阵不静默（读侧 schema 校验：非零报错或恢复合法）（t260903-10）",
     "python3 integration/t260903-10/sc_sandbar_doctor_compat_matrix.py"),
    ("t260903-10-upgrade-contract",
     "upgrade 消费契约⑧展示契约（副本在场/缺失两态各判，断言锚全取⑧节承诺面）：副本在→--dry-run 零退出且输出含当前版本（单源仓根 VERSION，字面量锚退役 t260903-12）、已验证点 0.1.1-rc.2、必查项四条可辨（A3/A4/B1/D1 编号或语义词）；副本缺→非零 fail-closed 点名契约文件不展示假区间（t260903-10）",
     "python3 integration/t260903-10/sc_sandbar_upgrade_contract.py", "ro"),
    ("t260903-12-ver-semver-rc",
     "VERSION 单源 semver 校验 fail-closed 守护（t260903-12）：仓根 VERSION 读回自证（read_version==文件内容 strip、version_tuple==核心三段、通过现行正则——零字面量锚，升版不触红）；semver 行为契约正例回归（纯三段/-rc/-rc.N）+ 负例 12 例全拒不松（核心段与 prerelease 段前导零、rc.x、rc1 无点、-RC 大写、v 前缀、rc.1.2 双段、空串、多行、全角、缺段、四段）——version.py 校验放宽后仓内唯一负例守护点（installer/tests 无自动跑点，写集外）",
     "python3 integration/t260903-12/sc_ver_semver_rc.py"),
    ("t260903-12-merge-checks-pairs",
     "bundle 新鲜度护栏配置与仓实况对齐（t260903-12）：server/dsh/merge-checks.yaml 在场（缺失=护栏未启用红）、形状可解析（引擎遇坏行 fail-closed）、恰含声明对 workbench src/client/→lib/、每对 src/out 前缀为仓内真实目录——路径写错时 3.5 节「src 前缀无改动→降噪」令护栏静默失效（t260827-02 假上线教训的复燃形态），本场景独立守护该对齐，与引擎解析逻辑不互替",
     "python3 integration/t260903-12/sc_merge_checks_pairs.py"),
    ("t260903-13-workbench-bundle-loads",
     "重建产物在 dsh 客户端模块契约下可加载（t260903-13）：lib/client.cjs 与 client.js 同体（exports ./client 指向 client.js，防 onSuccess 复制缺失的半新产物）、closure 外衣头尾完整（window.__ModuleLoader__.load({id:\"suyou-workbench\", factory}) 头 + return module.exports 尾）、vm 沙箱按契约真实加载——工厂可执行、返回非空 exports、bare require 全部落在声明外部化面（react、@deepseek-ai/*）内，越界泄漏=台面加载失败的用户可感形态；加载器先自证红绿（合法样本绿/泄漏红/外衣破损红/未挂载红）再量真产物。锚产物形态合同不锚 bundle 内部实现，tsdown 重建不改契约则本场景不因实现重构而红",
     "node integration/t260903-13/sc_workbench_bundle_loads.mjs", "ro"),
    ("t260903-13-metrics-golden-freeze",
     "度量响应形状对串行基线冻结（t260903-13）：tests/golden_serial/ 基线（t260903-09 修复产物，剔除 generated_at/cache.computed_at）与当前 src/host/metrics.ts 实现逐字节一致；golden.mjs 被 run_tests 执行器 HELPERS 排除、此前全仓无自动跑点（t260903-13 review 实锤的孤儿入口，票面点名「基线一并过」却无执行点），本场景补上唯一自动比对点并机械守护两条纪律：比对后 golden_serial/ 零 git 脏（--record 重录换绿在此现形）、tests/ 无 stub 运行时残留；判定行为级不钉案例数（基线面随窗口枚举自然扩展）",
     "node integration/t260903-13/sc_metrics_golden_freeze.mjs"),
]

CMD_TIMEOUT = 900


def _run_entry(entry):
    """跑单条场景（cmd=/bin/sh -c，cwd=仓库根）。返回 (name, exit_code, tail)。"""
    name, cmd = entry[0], entry[2]
    try:
        proc = subprocess.run(["/bin/sh", "-c", cmd], capture_output=True,
                              text=True, timeout=CMD_TIMEOUT)
        return name, proc.returncode, ((proc.stdout or "") + (proc.stderr or ""))[-1500:]
    except subprocess.TimeoutExpired:
        return name, -9, "超时（>%ds）" % CMD_TIMEOUT


def main() -> int:
    """分池执行（宿主令 t260902 并发分池）：条目可带可选第四元素——
    None/缺省 = "main" 池；"ro"/其他字符串 = 命名池；"exclusive" = 独占（先单独跑）。
    池间并行、池内严格串行（保顺序与可复现）；输出契约不变（PASS/FAIL 行+缩进尾段+
    末行汇总），跨池顺序可交错——引擎/工具逐行解析，不在乎顺序。"""
    import threading
    from concurrent.futures import ThreadPoolExecutor
    ran = passed = failed = 0
    t0 = time.time()
    lock = threading.Lock()
    pools, exclusives = {}, []
    for e in SCENARIOS:
        opt = e[3] if len(e) > 3 else None
        if opt == "exclusive":
            exclusives.append(e)
        else:
            pools.setdefault(opt or "main", []).append(e)

    def _drain(entries):
        nonlocal ran, passed, failed
        for e in entries:
            name, exit_code, tail_out = _run_entry(e)
            block = (["PASS [%s]" % name] if exit_code == 0
                     else ["FAIL [%s] exit=%d" % (name, exit_code)]
                     + ["    " + ln for ln in tail_out.splitlines()[-6:]])
            with lock:
                ran += 1
                passed += (exit_code == 0)
                failed += (exit_code != 0)
                print("\n".join(block), flush=True)

    for e in exclusives:      # 独占项先行，不与任何池重叠
        _drain([e])
    with ThreadPoolExecutor(max_workers=max(1, len(pools))) as ex:
        for f in [ex.submit(_drain, v) for v in pools.values()]:
            f.result()
    print("SCENARIOS ran=%d pass=%d fail=%d (%.0fs)" % (ran, passed, failed, time.time() - t0),
          flush=True)
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
