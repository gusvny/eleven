#!/usr/bin/env python3
# sc_stage_plugins_selfcheck.py —— t260916-26 场景②：stage 启停脚本「全插件激活」自检
# 断言面（灰盒 L2/L3，缺省池；工单验收② + review C1/C6 附条件直通面）。
#
# 用户故事：本票事故（0.1.5 stage 两插件 pending → UI 顶部 Failed to load plugins）是
# 靠人眼在 UI 顶部发现的。验收②要求 stage 启停脚本自检加入「全部插件 activated、零
# pending 零 failed」断言（与 epic T5 搭台脚本对接），review C1 裁定：只读 plugins 查询
# +断言必须**默认挂进 up/ensure** 的 console 就绪等待之后（失败打告警行含 pending/failed
# 清单、进回执字段，不阻断不拆台），`--check-plugins` 旗标=失败升格非零退出（CI/演练）；
# C6 裁定：定位失败/回执畸形/部分 entry 缺席三态行为必须显式可辨，畸形回执绝不许静默
# 「全绿」（KI-046/049「测试在场≠测试生效」同族：少跑少查必须可见）。
#
# 【S0 对齐注（walkthrough 期，20260918）】设计期假回执形状是 S0 前取证假设
# （GET + entries:[{id,state}]）。implement 期 `plugins` 子命令钉死真端点=宿主 typert
# 线型：POST /api/pluginInventory/list，信封 {type:"client-request",rpcId,method,payload}
# → {type:"server-response",rpcId,result:{ok,value:{entries:[{moduleName,fiberPhase,
# enabled}]}}}（dsh 0.1.1/0.1.5 同一线格式，真台活证=本场景 B2）。本文件按其自身维护
# 契约（「S0 钉死真端点后若真形不同，改本文件假回执常量即可，判定语义不变」）对齐夹
# 具——**判定语义逐腿保持，不改任何判定口径**：
#   健康→exit0+回执双空；pending/failed→非零且点名 id 与状态词；畸形→绝不许全绿；
#   拒连→exit2 环境红；只读→方法白名单（typert RPC 本质只读，读「只准清单查询这一
#   条方法、零其它路径」——字面 GET-only 是 S0 前假设的形态残留）；部分清单→判定所据
#   可见（落地契约为 counts.{total,enabled,disabled} 投影，cmd_plugins docstring ③）。
#
# 本场景守两层面：
#   A 断言机器契约（离线，注入式假 console typert 服务——黑盒只经 CLI 面，不窥内部）：
#      A1 健康回执（全 active）→ `plugins --console <url> --assert` exit 0，回执 JSON
#         ok=true 且 pending/failed 双空；
#      A2/A3 pending / failed entry 各一 → --assert 非零，输出点名 entry id 与状态词
#         （报错精确纪律：哪个 entry 哪个状态，不许只说「有失败」）；
#      A4 回执畸形（200 + 非 JSON 体）→ 非零 + 输出点名解析/畸形（不裸崩不假绿，
#         **不许把「回执畸形」误归因为「不可达」**——报错必须精确，把诊断引向网络
#         面=把人往错误的方向支）；
#      A5 console 不可达（拒连端口）→ exit 2 环境红点名（三态语义）；
#      A6 只读性：假 console 记录的全部请求须为 pluginInventory/list 这一条只读
#         RPC（POST 该端点、信封方法名匹配），零其它路径（方法白名单锚，见 S0 对齐注）；
#      A7 「全绿禁令」电池（C6 畸形面）：entries 非列表 / entry 缺 enabled 字段 /
#         fiberPhase 未知值——三种畸形回执一律**不许**得出 exit0+ok+双空的「全绿」
#         判定；部分 entry 清单按落地契约不是畸形（本命令是宿主版本无关的通用投影，
#         期望集是 profile 层关注点，cmd_plugins docstring ③）——但绿必须带可见判定
#         所据：counts.{total,enabled} 须回显清单规模，部分清单不许伪装成全量核查
#         （少查必须可见，KI-046/049 家族）。
#   B 真台面（docker；docker 缺席=ENV_FAIL exit 2 点名，不假红不假绿）：
#      B1 本场景自起冷台（own-bench）：`ensure` exit 0 且**租约回执可见 plugins 自检
#         已跑**（C1 挂接活性观测——探针随冷启动运行、回执随租约 JSON 打印；健康复用
#         的热 ensure 回显同一回执，观测不灭），热复用台 `ensure --check-plugins`
#         exit 0（升格旗标健康台不误伤），`plugins --project <own> --assert` exit 0
#         零 pending 零 failed（真台活体腿=验收②实锤，自含不依赖共享台）。锚「跑过
#         且可见」非措辞。为什么不在共享供给台上 ensure：共享台租约/心跳属于启动它的
#         进程，台面归属别的泳道（arbitrate 20260918 实录：租约 owner_root=邻票泳道），
#         对共享台项目名跑 ensure 有收容/重启动别人台面的风险——共享台只做只读查询。
#         台用完 down 回收；
#      B2 共享供给台（sandbar-test-integ）`plugins --project --assert`：**只读查询**，
#         锁根与供给契约对齐（文件头 setdefault，同 verify.yaml integration.supply；
#         arbitrate 20260918 实锤：不对齐=降级默认锁根租约不可见=结构性 env_fail，
#         对齐后真台探针 exit0 零 pending 零 failed），查得到→exit 0+回执零 pending
#         零 failed（真台活体加演）；台真缺席/非 up→ENV_FAIL 点名（环境面：台不在，
#         不假红不假绿）；租约写 up 而拒连同判环境面——租约可陈旧（容器带外回收/
#         owner 换泳道后租约不更新，arbitrate 20260918 KI 候选③；t260916-26
#         implement gen3 实测：owner=t260917-09 的旧租约在、容器零在册）；台面
#         **回话之后**的红（pending/failed/malformed/rpc_error）才是产品 FAIL，
#         不回答≠回答得红，两态不互冒；
#      B3 无独立腿：升格旗标负形由 A2/A3 同一判定路径守（--check-plugins 健康台腿
#         并入 B1 热复用段）。
#
# 三态（t260904-12）：末行 SUMMARY pass/fail/env_fail/na；fail>0 或全 na=exit 1；
# env_fail>0=exit 2。零 3099/7233 接触；B1 own-bench 用完即收，B2/B3 只读复用共享供
# 给台（--keep 常驻基建例外），不拆台。
import json
import os
import re
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

# 锁根与供给契约对齐（t260916-26 arbitrate 20260918）：verify.yaml integration.supply
# 的搭台/查台同一锁根（${SANDBAR_STAGE_LOCK_DIR:-/tmp/sandbar-test-stages}）。场景不
# 显式对齐时 stage_docker 落到降级默认锁根，共享台租约永远不可见——B2「真台活体加演」
# 腿结构性 env_fail（arbitrate 实锤：同机同台在跑，对齐锁根后探针 exit0 零 pending 零
# failed，此前 walkthrough 把这误归因为「锁根互不可见」）。显式 env 仍优先（setdefault）。
os.environ.setdefault("SANDBAR_STAGE_LOCK_DIR", "/tmp/sandbar-test-stages")
STAGE_CLI = ["python3", str(REPO / "integration" / "stage_docker.py")]
SUPPLY_PROJECT = "sandbar-test-integ"
OWN_BENCH = "t260916-26-selfchk"  # B1 冷启动观测台（用完即收；命名守 PROJECT_RE 白名单）

# S0 钉死的公开查询端点与方法名（implement 期落地，真台活证=B2；夹具只认这一条）
INVENTORY_ENDPOINT = "/api/pluginInventory/list"
INVENTORY_METHOD = "pluginInventory/list"

_passed = _failed = _envfail = _na = 0


def check(name, cond, detail=""):
    global _passed, _failed
    if cond:
        _passed += 1
        print(f"  ok {name}")
    else:
        _failed += 1
        print(f"  FAIL {name}" + (f" — {detail}" if detail else ""))


def env_fail(name, detail):
    global _envfail
    _envfail += 1
    print(f"  [ENV_FAIL] {name} — {detail}")


def na(name, detail):
    global _na
    _na += 1
    print(f"  [NA] {name} — {detail}")


def summary():
    print("SUMMARY pass=%d fail=%d env_fail=%d na=%d" % (_passed, _failed, _envfail, _na))
    if _failed > 0 or (_na > 0 and _passed == 0 and _envfail == 0):
        return 1
    if _envfail > 0:
        return 2
    return 0


def run_cli(args, timeout=120):
    try:
        p = subprocess.run(STAGE_CLI + args, capture_output=True, text=True,
                           cwd=str(REPO), timeout=timeout)
        return p.returncode, p.stdout, p.stderr
    except subprocess.TimeoutExpired:
        return None, "", f"超时 {timeout}s（命令：{' '.join(args)}）"


def extract_json(text):
    """回执提取：整段→逐行（自尾向前）取首个可解析 JSON 对象——容忍 STAGE_ 行混排。"""
    try:
        return json.loads(text)
    except (json.JSONDecodeError, ValueError):
        pass
    for line in reversed(text.splitlines()):
        line = line.strip()
        if line.startswith("{"):
            try:
                return json.loads(line)
            except (json.JSONDecodeError, ValueError):
                continue
    return None


class FakeConsole:
    """注入式假 console：POST typert 线型（S0 对齐，见头注）——对
    /api/pluginInventory/list 回 {type:"server-response",rpcId,result} 信封；raw_body=True
    时回 200 + 非 JSON 体（A4 畸形腿）。记录 (method, path, body) 供只读性断言。"""

    def __init__(self, entries, raw_body=False):
        self.entries = entries
        self.raw_body = raw_body
        self.seen = []  # (method, path, body)

    def serve(self):
        outer = self

        class H(BaseHTTPRequestHandler):
            def do_POST(self):
                length = int(self.headers.get("Content-Length") or 0)
                body = self.rfile.read(length) if length else b"{}"
                outer.seen.append(("POST", self.path, body.decode("utf-8", "replace")))
                if outer.raw_body:
                    payload = b"this is not json"
                else:
                    try:
                        req = json.loads(body)
                    except (json.JSONDecodeError, ValueError):
                        req = {}
                    payload = json.dumps({
                        "type": "server-response",
                        "rpcId": str(req.get("rpcId") or ""),
                        "result": {"ok": True, "value": {"entries": outer.entries}},
                    }).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def do_GET(self):
                outer.seen.append(("GET", self.path, ""))
                self.send_response(404)
                self.send_header("Content-Length", "0")
                self.end_headers()

            def log_message(self, *a):  # 静默访问日志
                pass

        srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
        t = threading.Thread(target=srv.serve_forever, daemon=True)
        t.start()
        return srv


def entry(mid, phase):
    """entry 形状=S0 真形：moduleName + fiberPhase（宿主清单五态词）+ enabled。"""
    return {"moduleName": mid, "fiberPhase": phase, "enabled": True}


HEALTHY = [
    entry("sandbar-admin-ui/client", "active"),
    entry("sandbar-workbench/client", "active"),
    entry("sandbar-knowledge/client", "active"),
    entry("sandbar-providers/client", "active"),
]
PENDING_ONE = HEALTHY[:2] + [entry("sandbar-knowledge/client", "pending")] + HEALTHY[3:]
FAILED_ONE = HEALTHY[:3] + [entry("sandbar-providers/client", "failed")]
PARTIAL_LIST = [entry("sandbar-admin-ui/client", "active")]
BAD_SHAPES = [
    ("entries 非列表", "all-good-trust-me"),
    ("entry 缺 enabled 字段", [{"moduleName": "sandbar-knowledge/client", "fiberPhase": "active"}]),
    ("fiberPhase 未知值", [entry("sandbar-knowledge/client", "somewhere")]),
]


def plugins_missing(rc, out, err):
    """子命令未落地的显式识别（usage 错误文案点名未知子命令）。"""
    return "未知子命令" in (out + err) or "invalid choice" in (out + err)


def main():
    print("== A 断言机器契约（注入式假 console typert 线型，黑盒 CLI 面）==")
    all_seen = []

    def with_server(entries, raw_body=False):
        fc = FakeConsole(entries, raw_body=raw_body)
        srv = fc.serve()
        try:
            yield fc, f"http://127.0.0.1:{srv.server_address[1]}"
        finally:
            all_seen.extend(fc.seen)
            srv.shutdown()

    # A0 前置：子命令在场识别（裸子命令探针——未知旗标/未知子命令都是 usage 红，
    # 但只有「未知子命令」能证明缺席；带了旗标时旗标检查先行会掩盖子命令缺席）
    rc0, out0, err0 = run_cli(["plugins"], timeout=60)
    present = not plugins_missing(rc0, out0, err0)
    check("A0 plugins 子命令在场（stage_docker.py）", present,
          "子命令未落地——A 面各腿显式点名红" if not present else "")
    present = present and "未知旗标" not in (out0 + err0)  # 裸探针不应报旗标错

    def absent(label):
        check(label, False, "plugins 子命令未落地（TDD 预期红，落地后自动生效）")

    # A1 健康回执 → exit 0 + ok=true + 双空
    for fc, url in with_server(HEALTHY):
        if not present:
            absent("A1 健康回执→exit0+回执双空")
            break
        rc, out, err = run_cli(["plugins", "--console", url, "--assert"])
        receipt = extract_json(out)
        check("A1 健康回执→exit0+回执双空", rc == 0 and isinstance(receipt, dict)
              and receipt.get("ok") is True and receipt.get("pending") == [] and receipt.get("failed") == [],
              f"rc={rc} receipt={str(receipt)[:160]}")
        break

    # A2/A3 pending / failed → 非零 + 点名 id 与状态
    for label, payload, state in (("A2 pending entry", PENDING_ONE, "pending"),
                                  ("A3 failed entry", FAILED_ONE, "failed")):
        for fc, url in with_server(payload):
            if not present:
                absent(f"{label}→非零且点名")
                break
            rc, out, err = run_cli(["plugins", "--console", url, "--assert"])
            blob = out + err
            bad = [e for e in payload if e["fiberPhase"] == state][0]
            bad_id = bad["moduleName"]
            check(f"{label}→非零且点名 id 与状态词",
                  rc not in (0, None) and bad_id in blob and state in blob,
                  f"rc={rc} 输出含 {bad_id}={bad_id in blob} 含 {state}={state in blob}")
            break

    # A4 回执畸形（200 + 非 JSON 体）→ 非零 + 点名解析/畸形
    # 报错精确纪律：畸形回执若被归因为 unreachable（不可达），把诊断引向网络面——
    # 本腿红 = 落地实现的归因缺陷（walkthrough 20260918 实锤，见验收报告）。
    for fc, url in with_server(None, raw_body=True):
        if not present:
            absent("A4 非 JSON 回执→非零且点名畸形")
            break
        rc, out, err = run_cli(["plugins", "--console", url, "--assert"])
        blob = (out + err).lower()
        named = any(w in blob for w in ("json", "解析", "畸形", "invalid", "malformed", "parse"))
        check("A4 非 JSON 回执→非零且点名畸形", rc not in (0, None) and named,
              f"rc={rc} 点名={named} 回执原文={str(extract_json(out))[:140]}")
        break

    # A5 console 不可达 → exit 2 环境红（子命令已在场前提下方有意义）
    if not present:
        check("A5 console 不可达→exit2 环境红点名", False,
              "plugins 子命令未落地——退出码契约无从验证（落地后自动生效）")
    else:
        rc, out, err = run_cli(["plugins", "--console", "http://127.0.0.1:1", "--assert"], timeout=60)
        check("A5 console 不可达→exit2 环境红点名", rc == 2, f"rc={rc} err={err[:120]}")

    # A7 全绿禁令电池：畸形回执绝不许得出「全绿」（子命令缺席时全数点名红，不许空转绿）
    for label, payload in BAD_SHAPES:
        for fc, url in with_server(payload):
            if not present:
                absent(f"A7 {label}→不许全绿")
                break
            rc, out, err = run_cli(["plugins", "--console", url, "--assert"])
            receipt = extract_json(out) if isinstance(extract_json(out), dict) else {}
            all_clear = rc == 0 and receipt.get("ok") is True \
                and receipt.get("pending") == [] and receipt.get("failed") == []
            check(f"A7 {label}→不许全绿", not all_clear,
                  f"rc={rc} receipt={str(receipt)[:140]}")
            break

    # A7 部分 entry 清单：按落地契约（docstring ③ 通用投影、空真 ok）允许绿，但绿必须
    # 带可见判定所据——counts 回显清单规模，部分清单不许伪装成全量核查（少查必须可见）
    for fc, url in with_server(PARTIAL_LIST):
        if not present:
            absent("A7 部分 entry 清单→判定所据可见")
            break
        rc, out, err = run_cli(["plugins", "--console", url, "--assert"])
        receipt = extract_json(out) if isinstance(extract_json(out), dict) else {}
        counts = receipt.get("counts") if isinstance(receipt.get("counts"), dict) else {}
        check("A7 部分 entry 清单→绿且判定所据可见（counts 回显清单规模，少查必须可见）",
              rc == 0 and receipt.get("ok") is True
              and counts.get("total") == len(PARTIAL_LIST)
              and counts.get("enabled") == len(PARTIAL_LIST),
              f"rc={rc} counts={str(counts)[:120]}")
        break

    # A6 只读性：本场景全部 A 面调用只应留下 pluginInventory/list 这一条只读 RPC
    # （S0 对齐：typert RPC 本质只读；锚=端点+方法名白名单，非字面 GET——见头注）
    if present:
        ok_ro = (len(all_seen) > 0
                 and all(m == "POST" for m, _, _ in all_seen)
                 and all(p == INVENTORY_ENDPOINT for _, p, _ in all_seen)
                 and all(f'"method": "{INVENTORY_METHOD}"' in b for _, _, b in all_seen))
        check("A6 自检只读（方法白名单：仅 pluginInventory/list 一条 RPC，零其它路径）", ok_ro,
              f"seen={[(m, p) for m, p, _ in all_seen[:6]]}")
    else:
        check("A6 自检只读（方法白名单：仅 pluginInventory/list 一条 RPC，零其它路径）", False,
              "子命令未落地——假 console 零请求，只读性无从验证（落地后自动生效）")

    print("== B 真台面（docker；缺席=ENV_FAIL 点名）==")
    dprobe = subprocess.run(["docker", "version", "--format", "{{.Server.Version}}"],
                            capture_output=True, text=True, timeout=20)
    if dprobe.returncode != 0:
        env_fail("B 面 docker 守护进程", f"docker version 失败：{(dprobe.stderr or dprobe.stdout)[:140]}")
        na("B1 冷启动 ensure 租约回执可见 plugins 自检（C1 挂接活性）", "docker 缺席")
        na("B1 热复用 ensure 回执仍可见", "docker 缺席")
        na("B1 热复用 ensure --check-plugins 健康台不误伤", "docker 缺席")
        na("B1 own-bench plugins --assert 零 pending 零 failed", "docker 缺席")
        na("B1 台面回收（down）", "docker 缺席")
        na("B2 共享供给台 plugins --assert 零 pending 零 failed", "docker 缺席")
        sys.exit(summary())

    # B1 冷启动 own-bench：探针随冷启动跑、回执随租约 JSON 打印（C1 挂接活性的闸内
    # 可观测量）；热复用回显 + 升格旗标健康台 + own-bench 真台断言，最后 down 回收
    # （finally 兜底，四路径回收纪律）。全程只用本场景自己的项目名——绝不对共享台
    # 项目名跑 ensure（沙箱锁根互相不可见，有收容别人台面的风险，见头注）。
    try:
        rc, out, err = run_cli(["ensure", "--project", OWN_BENCH, "--keep",
                                "--services", "full", "--timeout", "300"], timeout=420)
        lease = extract_json(out) if rc == 0 else None
        plugins = lease.get("plugins") if isinstance(lease, dict) else None
        check("B1 冷启动 ensure exit0", rc == 0, f"rc={rc} err={err[-160:]}")
        check("B1 租约回执可见 plugins 自检已跑（C1 挂接活性：随冷启动跑+随租约打印，"
              "锚「跑过且可见」非措辞）",
              rc == 0 and isinstance(plugins, dict) and plugins.get("query") == "ok"
              and plugins.get("ok") is True,
              f"plugins 字段={str(plugins)[:150] if plugins is not None else '无（租约零 plugins 字段）'}")
        # 热复用回显：健康复用秒回路径上，租约（含 plugins 回执）仍随输出可见——观测不灭
        rc, out, err = run_cli(["ensure", "--project", OWN_BENCH, "--keep",
                                "--services", "full", "--timeout", "60"], timeout=120)
        lease = extract_json(out) if rc == 0 else None
        plugins = lease.get("plugins") if isinstance(lease, dict) else None
        check("B1 热复用 ensure 回执仍可见（回显语义，零 docker 查询路径观测不灭）",
              rc == 0 and isinstance(plugins, dict) and plugins.get("query") == "ok",
              f"rc={rc} plugins 字段={'有' if isinstance(plugins, dict) else '无'}")
        # 升格旗标健康台不误伤（负形由 A2/A3 同一判定路径守）
        rc, out, err = run_cli(["ensure", "--project", OWN_BENCH, "--keep",
                                "--services", "full", "--check-plugins", "--timeout", "60"],
                               timeout=120)
        check("B1 热复用 ensure --check-plugins 健康台 exit0（升格旗标不误伤）", rc == 0,
              f"rc={rc} err={err[-140:]}")
        # own-bench 真台活体断言（验收②实锤，自含）
        rc, out, err = run_cli(["plugins", "--project", OWN_BENCH, "--assert"], timeout=120)
        receipt = extract_json(out)
        check("B1 own-bench plugins --assert 零 pending 零 failed（真台活体）",
              rc == 0 and isinstance(receipt, dict) and receipt.get("ok") is True
              and receipt.get("pending") == [] and receipt.get("failed") == [],
              f"rc={rc} receipt={str(receipt)[:150]} err={err[-120:]}")
    finally:
        rc, out, err = run_cli(["down", "--project", OWN_BENCH, "--timeout", "60"], timeout=120)
        check("B1 台面回收（down）", rc == 0, f"rc={rc} err={err[-140:]}")

    # B2 共享供给台：只读查询（绝 ensure；锁根已对齐供给契约，见文件头 setdefault）。
    # 查得到=真台活体加演；台真缺席/非 up=ENV_FAIL 环境红点名——不假红不假绿。
    rc, out, err = run_cli(["plugins", "--project", SUPPLY_PROJECT, "--assert"], timeout=120)
    receipt = extract_json(out)
    blob = out + err
    if rc == 0 and isinstance(receipt, dict) and receipt.get("ok") is True \
            and receipt.get("pending") == [] and receipt.get("failed") == []:
        check("B2 共享供给台 plugins --assert 零 pending 零 failed（真台活体加演）", True,
              f"counts={str(receipt.get('counts'))[:100]}")
    elif "不是可查询的 up 台" in blob or "锁根" in blob:
        env_fail("B2 共享供给台不可查询（台缺席/非 up——环境面，不假红不假绿）",
                 f"rc={rc} err={err[-140:]}")
    elif isinstance(receipt, dict) and receipt.get("reason") == "unreachable":
        # 租约写 up 但拒连=台面进程真不在场（容器带外回收/owner 换泳道后旧租约
        # 残留——arbitrate 20260918 KI 候选③实锤：本轮实测租约 owner 已从
        # t260916-25 换到 t260917-09 而容器零在册）。归位本腿头注声明的环境面：
        # 拒连=ENV_FAIL 点名；台面**回话之后**的任何红（pending/failed/malformed
        # /rpc_error）仍走下方产品 FAIL——不回答≠回答得红，两态不互冒。
        env_fail("B2 共享供给台拒连（租约 up 而台面不在——环境面：台真缺席/租约陈旧，不假红不假绿）",
                 f"rc={rc} receipt={str(receipt)[:150]}")
    else:
        check("B2 共享供给台 plugins --assert 零 pending 零 failed（真台活体加演）", False,
              f"rc={rc} receipt={str(receipt)[:150]} err={err[-140:]}")

    sys.exit(summary())


if __name__ == "__main__":
    main()
