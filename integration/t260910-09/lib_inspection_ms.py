"""t260910-09 巡检票②场景共享夹具与驱动（无 sc_ 前缀=共享子检查代码，不登记场景清单）。

三态纪律沿 t260905-03/lib_inspection.py（t260904-12，闸内不设第三态）：
exit 0=PASS / 1=FAIL（产品红，缺什么点名什么）/ 2=ENV_FAIL（环境缺供点名）。
模块/入口未交付=产品红（红属预期：实现段落地前 TDD 信号）；temporalio 缺席=环境红，
两不相冒充（KI-051 教训）。

绑定面（全部为已交付/已声明的对外契约，场景侧裁定，实现侧照办）：
- 机制/简化面扫描器 CLI（本票场景侧裁定，沿票① lib 同款裁定先例）：
    `python3 server/engine/inspection_scan_ms.py --face mechanism|simplify --repo-root <dir>`
  stdout 单行 JSON {ok, result:{face,findings,summary,heartbeat,meta}|error}；
  finding 六键 {id,scan,severity,subject,evidence,suggestion}（复用票① Finding 形状）；
  ScanError（仓根缺失等无法起扫）= ok:false + exit 非零 + error 点名路径（fail-closed）。
  scan 字段取名不锁定（场景按 subject/evidence 内容定位，灰盒绑定浅）；severity 按
  方案 D2/D4/D5 承诺锁定：dead-man=med、影子代码=med、补丁退役（带取代证据）=med、
  重复防御层=med、过长/过深点名=low。
- face 分派缝（activities.run_inspection_scan）：args 增 face 键，缺省=test（既有语义
  零变化），未知 face=ok:false 且 error 点名已知面清单（fail-closed 不静默）。
- 触发面 decl 子命令离线视图：`inspection_trigger.py decl --decl-path <yaml>`，
  stdout 单行 JSON，schedule_specs 只含 enabled 实例（enabled=false 不调度=数据面）。

夹具=仓形树（repo-shaped）：integration/run_scenarios.py + server/engine/** 生产方——
与扫描器真实收集口径同构，不靠 mock 缝合（沿票① 夹具纪律）。共享管线（RepoTree/
run_cmd/单行 JSON 解析/三态退出）跨票 import t260905-03 lib（先例：t260907-08 夹具
跨票 import t260905-08 lib），本文件只放机制/简化面特有夹具。
"""
from __future__ import annotations

import os
import re
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_T1 = os.path.join(os.path.dirname(_HERE), "t260905-03")
sys.path.insert(0, _T1)
import lib_inspection as base  # noqa: E402 — 共享管线跨票复用（RepoTree/run_cmd/三态退出）

REPO = base.REPO
TP_DIR = base.TP_DIR
MS_SCANNER = os.path.join(TP_DIR, "inspection_scan_ms.py")
ACTIVITIES = os.path.join(TP_DIR, "activities.py")

FINDING_KEYS = base.FINDING_KEYS
RESULT_KEYS = {"face", "findings", "summary", "heartbeat", "meta"}
KNOWN_FACES = ("test", "mechanism", "simplify")

# 证据计数带分母（review C2）：零命中必须可辨「查过 0/N」而非空集恒真——
# 证据文本中至少出现一处「0/<非零>」形计数。
_ZERO_COUNT_RE = re.compile(r"0\s*/\s*[1-9]\d*")


def require_ms_entry() -> None:
    base.require_entry(MS_SCANNER, "机制/简化面扫描器")


def run_ms_scanner(repo_root: str, face: str):
    """跑机制/简化面扫描器 CLI，返回 (proc, parsed)。"""
    require_ms_entry()
    proc = base.run_cmd([base.py_runner(), MS_SCANNER, "--face", face, "--repo-root", repo_root])
    base.env_fail_if_missing_dep(proc)
    return proc, base.last_json(proc.stdout)


def ms_result(parsed):
    """{ok:true} 回执的 result；形状不符返回 None。"""
    if not isinstance(parsed, dict) or parsed.get("ok") is not True:
        return None
    res = parsed.get("result")
    return res if isinstance(res, dict) else None


def finding_text(f) -> str:
    return "%s %s %s" % (f.get("subject", ""), f.get("evidence", ""), f.get("suggestion", ""))


# ================================================================ 机制面夹具族（S4/S5）

_GHOST_MOD = (
    '"""夹具：全史零命中机制（KI-049「写集跟随方案」形态）。"""\n'
    "\n"
    "\n"
    "def ghost_mechanism():\n"
    "    print(\"授权扩展已记录\")\n"
)

_ZOMBIE_MOD = (
    '"""夹具：零日志字面的死机制（日志面空集形态，review C2 分母口径的对照面）。"""\n'
    "\n"
    "\n"
    "def zombie_fn():\n"
    "    return None\n"
)

_LIVE_MOD = (
    '"""夹具：在役机制（有调用点，反例）。"""\n'
    "\n"
    "\n"
    "def live_mechanism():\n"
    "    return 42\n"
)

_LIVE_USER_MOD = (
    "from mod_live import live_mechanism\n"
    "\n"
    "\n"
    "def use_live():\n"
    "    return live_mechanism()\n"
)


def _ms_base_tree(label: str):
    """机制面基座：ghost（三重零+1 条日志字面）+ zombie（零日志字面）+ live（在役）。
    附中性 sc_* 守卫：场景引用面沿票① collect_guards 口径只索引 sc_* 文件——无 sc_
    文件=该面 0/0 空转，「场景引用 0/N」的分母口径与反例①（引用破零）都无从验起。"""
    t = base.RepoTree(label)
    t.write_scenarios([("t-ms-base", "机制面基座夹具条目：候选登记对照", "true")])
    t.write("integration/sc_ms_base_guard.py",
            "# 中性守卫夹具（不提及任何候选机制名，维持三重零）\n"
            "assert True, \"基座守卫\"\n")
    t.write("server/engine/mod_ghost.py", _GHOST_MOD)
    t.write("server/engine/mod_zombie.py", _ZOMBIE_MOD)
    t.write("server/engine/mod_live.py", _LIVE_MOD)
    t.write("server/engine/mod_live_user.py", _LIVE_USER_MOD)
    return t


def dead_hit_tree(label: str = "ms-dead-hit"):
    """dead-man 正例夹具：ghost 三重零命中（med）+ zombie（日志面空集仍判）。"""
    return _ms_base_tree(label)


def referenced_tree(label: str = "ms-referenced"):
    """反例①：场景零引用被打破——sc_* 守卫提及 ghost_mechanism → 不报。"""
    t = _ms_base_tree(label)
    t.write("integration/sc_ref_guard.py",
            "# 场景引用反例守卫：ghost_mechanism 被本守卫提及\n"
            "REF = \"ghost_mechanism\"\n")
    return t


def called_tree(label: str = "ms-called"):
    """反例②：代码路径零调用被打破——跨模块调用 ghost_mechanism → 不报。"""
    t = _ms_base_tree(label)
    t.write("server/engine/mod_ghost_user.py",
            "from mod_ghost import ghost_mechanism\n"
            "\n"
            "\n"
            "def use_ghost():\n"
            "    return ghost_mechanism()\n")
    return t


def exempt_tree(label: str = "ms-exempt"):
    """反例③：注册表豁免——ghost_mechanism 进 ALL_WORKFLOWS 清单 → 不报。"""
    t = _ms_base_tree(label)
    t.write("server/engine/workflows.py",
            'ALL_WORKFLOWS = ["ghost_mechanism"]\n'
            "ALL_ACTIVITIES = []\n")
    return t


def shadow_tree(label: str = "ms-shadow"):
    """影子代码夹具：legacy 零调用+新旧命名对（med）；v2 在役不报。"""
    t = base.RepoTree(label)
    t.write_scenarios([("t-ms-shadow", "影子代码夹具条目", "true")])
    t.write("server/engine/mod_pair.py",
            '"""夹具：新旧形态对。"""\n'
            "\n"
            "\n"
            "def fetch_payload_v2():\n"
            "    return {\"v\": 2}\n"
            "\n"
            "\n"
            "def fetch_payload_legacy():\n"
            "    return {\"v\": 1}\n")
    t.write("server/engine/mod_pair_user.py",
            "from mod_pair import fetch_payload_v2\n"
            "\n"
            "\n"
            "def use_payload():\n"
            "    return fetch_payload_v2()\n")
    return t


# ================================================================ 简化面夹具族（S6/S7）

def patch_tree(label: str = "ms-patch"):
    """补丁退役夹具：*_patch 薄包装、宿主已被 v2 取代、补丁零外部调用者 → med+风险注。"""
    t = base.RepoTree(label)
    t.write_scenarios([("t-ms-patch", "补丁退役夹具条目", "true")])
    t.write("server/engine/mod_upsert.py",
            '"""夹具：upsert 补丁层（宿主已被 v2 取代）。"""\n'
            "\n"
            "\n"
            "def upsert_ticket_v2(payload):\n"
            "    return payload\n"
            "\n"
            "\n"
            "def upsert_ticket_patch(payload):\n"
            "    # 兼容层：旧调用名过渡（补丁/防御层）\n"
            "    return upsert_ticket_v2(payload)\n")
    return t


def dupdef_tree(label: str = "ms-dupdef"):
    """重复防御层夹具：同一 sanitize 在调用链两层出现 → med。"""
    t = base.RepoTree(label)
    t.write_scenarios([("t-ms-dupdef", "重复防御层夹具条目", "true")])
    t.write("server/engine/mod_def.py",
            '"""夹具：防御层重复。"""\n'
            "\n"
            "\n"
            "def sanitize_name(s):\n"
            "    return (s or \"\").strip().lower()\n"
            "\n"
            "\n"
            "def store_user(s):\n"
            "    return {\"n\": sanitize_name(s)}\n"
            "\n"
            "\n"
            "def store_user_caller(s):\n"
            "    # 调用方又洗一遍：防御层重复\n"
            "    return store_user(sanitize_name(s))\n")
    return t


def _nested_src(depth: int) -> str:
    lines = ["def deep_fn(v):"]
    ind = "    "
    for i in range(depth):
        lines.append(ind + "if v > %d:" % i)
        ind += "    "
    lines.append(ind + "return 1")
    lines.append("    return 0")
    return "\n".join(lines) + "\n"


def _flat_src(stmts: int, fn: str) -> str:
    lines = ["def %s():" % fn] + ["    v%d = %d" % (i, i) for i in range(stmts)]
    lines.append("    return v%d" % (stmts - 1))
    return "\n".join(lines) + "\n"


def longfn_tree(label: str = "ms-longfn"):
    """过长/过深点名夹具：显著超阈（120 行/深 8）必点名、显著低于（40 行/深 2）不报。
    阈值精确边界（80/81、深 5/6 真值表）归 developer L1（阈值常量在实现内）；本条守
    点名行为的用户可感知面。"""
    t = base.RepoTree(label)
    t.write_scenarios([("t-ms-long", "过长过深点名夹具条目", "true")])
    t.write("server/engine/mod_long.py", _flat_src(120, "long_fn"))
    t.write("server/engine/mod_short.py", _flat_src(40, "short_fn"))
    t.write("server/engine/mod_deep.py", _nested_src(8))
    t.write("server/engine/mod_shallow.py", _nested_src(2))
    return t


def clean_ms_tree(label: str = "ms-clean"):
    """全绿夹具：在役有调用（含 use_live——零引用包装会被 dead-man 判，故补调用点使其
    在役）、无补丁/影子特征、函数短且浅——两 face 均零发现+heartbeat。
    （t260910-09 implement 校正：原夹具 mod_live_user.use_live 本身零引用，dead-man
    语义下属真嫌疑、干净树必红——补 mod_clean_entry 引用点使夹具自洽。）"""
    t = base.RepoTree(label)
    t.write_scenarios([("t-ms-clean", "干净夹具条目：零发现心跳数据面", "true")])
    t.write("server/engine/mod_live.py", _LIVE_MOD)
    t.write("server/engine/mod_live_user.py", _LIVE_USER_MOD)
    t.write("server/engine/mod_clean_entry.py", "z = use_live\n")
    t.write("server/engine/mod_short.py",
            "# dead-man-exempt: short_fn\n" + _flat_src(40, "short_fn"))
    t.write("server/engine/mod_shallow.py",
            "# dead-man-exempt: deep_fn\n" + _nested_src(2))
    return t


def garbage_tree(label: str = "ms-garbage"):
    """畸形被扫输入：server/engine 下 NUL 乱码模块——不崩、结构化回执、逐项降级。"""
    t = base.RepoTree(label)
    t.write_scenarios([("t-ms-garbage", "畸形输入夹具条目", "true")])
    t.write("server/engine/mod_live.py", _LIVE_MOD)
    t.write("server/engine/mod_live_user.py", _LIVE_USER_MOD)
    t.write_bytes("server/engine/mod_nul.py", b"\x00\x01\xff binary garbage \xfe")
    return t


# 真仓 smoke 用（ro）：真仓可跑、回执形状齐；发现量级不 pin（发现随工单演化，
# 可行动性归人审——沿票① 腿8 口径）。
