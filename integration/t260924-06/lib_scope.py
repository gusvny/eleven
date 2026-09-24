"""t260924-06 inspect 缩面场景共享夹具（无 sc_ 前缀=共享代码，不登记场景清单）。

工单：审查面缩面——inspect 段从「全仓普查」改为「本期变化面定向审」，预算内必出
发现清单（治三期零产出）。方案 v2（.sandbar/stage_create_plan_gen1.json）拍定的
用户可感知契约面：
- 审查范围=活动侧机械给定四路输入（变化面 diff/套件回执红/上期台账/KI 册），
  prompt 明示「清单外不看」，分片硬上限，无基点**不回落全仓**；
- 四路畸形一律不抛出：回落值+meta 计数+scope_block 点名三件套；
- 零发现显式：findings==[] 必带证据面（scope 记账）+票面「本期无新病灶」渲染；
- 预算护栏：meta 记 used_sec/scope，>90% 预算票面点名「先报实测再谈预算」。

三态纪律（t260904-12）：exit 0=PASS / 1=FAIL（产品红点名）/ 2=ENV_FAIL（环境缺供点名）。
实现段落地前红属预期（TDD 信号），arbitrate/merge 期必须绿。

夹具策略（arbitrate 定版：对齐实现真接缝）：全离线（stub temporalio +
SANDBAR_INSPECT_STUB 桩缝，先例=t260916-22）。活动壳自做 IO，场景只供真缝面：
- 变化面=真 git 仓夹具（base_dir 建仓两提交，prev..this 差分自然产生）；
- 上期台账=SANDBAR_INSPECTION_DIR 注入 + 真文件播种（lane.base_ref=prev 提交）；
- 套件回执=args["suite_receipt"] 显式路径；KI 册=base/notes/debts/known-issues.md；
- 分片上限=args["inspect_max_shards"] / ["inspect_max_files_per_shard"]（decl 键
  词法收非空字符串标量，与 inspection_decl 词法一致）。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
sys.path.insert(0, os.path.join(os.path.dirname(_HERE), "t260916-22"))
sys.path.insert(0, os.path.join(os.path.dirname(_HERE), "t260905-03"))

import lib_inspect as base  # noqa: E402  复用 t260916-22 inspect 桩缝夹具单点

# ---------------------------------------------------------------- 真缝夹具构建


def write_ki_under(repo, *, exists=True, entries=True):
    """KI 册夹具落实现固定相对路径 base/notes/debts/known-issues.md。"""
    d = os.path.join(repo, "notes", "debts")
    path = os.path.join(d, "known-issues.md")
    if not exists:
        return path  # 故意不写（不可读子用例）
    os.makedirs(d, exist_ok=True)
    if entries:
        with open(path, "w", encoding="utf-8") as f:
            f.write("| KI-900 | inspect 缩面夹具条目一 | 非阻塞 | open | 现场 |\n"
                    "| KI-901 | inspect 缩面夹具条目二 | 非阻塞 | open | 现场 |\n")
    else:
        with open(path, "w", encoding="utf-8") as f:
            f.write("自由文本，没有任何可识别条目结构。\n")
    return path


def make_base_repo(workdir, *, n_changed=3, ki_exists=True, ki_entries=True):
    """建审查基座真 git 仓：commit1=基线（KI 册+base 文件），commit2=变化面 N 文件。

    返回 (repo, prev_sha, this_sha)。"""
    repo = tempfile.mkdtemp(prefix="t260924-06-base-", dir=workdir)
    run = lambda *a: subprocess.run(["git", "-C", repo] + list(a), check=True,
                                    capture_output=True, text=True)  # noqa: E731
    run("init", "-q")
    run("config", "user.email", "sc@example.test")
    run("config", "user.name", "sc")
    write_ki_under(repo, exists=ki_exists, entries=ki_entries)
    with open(os.path.join(repo, "base_file.py"), "w") as f:
        f.write("# baseline\n")
    run("add", "-A")
    run("commit", "-qm", "baseline")
    prev = run("rev-parse", "HEAD").stdout.strip()
    for i in range(n_changed):
        with open(os.path.join(repo, "sc_sample_%03d.py" % i), "w") as f:
            f.write("# changed %d\n" % i)
    run("add", "-A")
    run("commit", "-qm", "change face")
    this = run("rev-parse", "HEAD").stdout.strip()
    return repo, prev, this


def write_suite_receipt(workdir, *, valid=True, entries=None):
    """造本期套件回执 -suite.json（valid=False=坏 JSON）。"""
    path = os.path.join(workdir, "receipt-%d-suite.json" % (os.getpid() % 100000))
    if not valid:
        with open(path, "w", encoding="utf-8") as f:
            f.write("{not-json<<<")
        return path
    doc = {"ran": 10, "failed": 2, "details": entries if entries is not None else [
        {"name": "sc_red_one", "status": "FAIL"},
        {"name": "sc_env_fail_one", "status": "ENV_FAIL"},
    ]}
    with open(path, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False)
    return path


# ---------------------------------------------------------------- 活动参（真键名）


def scope_args(instance, period, base_repo, this_sha, *, suite_path=None,
               max_shards=None, max_files=None, **extra):
    """run_inspection_inspect 活动参：实现真键名（suite_receipt/base_head/上限两键）。"""
    d = base.inspect_args(instance, period, base_repo)
    d["base_head"] = this_sha
    if suite_path is not None:
        d["suite_receipt"] = suite_path
    if max_shards is not None:
        d["inspect_max_shards"] = max_shards
    if max_files is not None:
        d["inspect_max_files_per_shard"] = max_files
    d.update(extra)
    return d


def seed_prev_doc(ledger_dir, instance, period, *, base_ref="a" * 40, findings=None,
                  raw=None):
    """播上期台账 doc：base_ref 在册（lane.base_ref）/缺基点/坏 JSON 三态。"""
    os.makedirs(ledger_dir, exist_ok=True)
    path = os.path.join(ledger_dir, base.ledger_name(instance, period))
    if raw is not None:
        with open(path, "w", encoding="utf-8") as f:
            f.write(raw)
        return path
    doc = {"instance_id": instance, "period": period,
           "findings": findings or [], "summary": {}, "heartbeat": True}
    if base_ref is not None:
        doc["lane"] = {"base_ref": base_ref}
    with open(path, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False)
    return path


# ---------------------------------------------------------------- 离线活动驱动


class InspectDriver:
    """离线驱动 run_inspection_inspect（stub temporalio + 桩缝），env 单点进出。"""

    def __init__(self):
        self._mods = base.load_engine_modules()  # ImportError 系环境面→ENV_FAIL
        self.activities, self.agent_activities, self.inspect_mod = self._mods
        self._tmp = tempfile.mkdtemp(prefix="t260924-06-ledger-")
        self._old_env = {}

    def close(self):
        for k, v in self._old_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def run(self, args, stub_text=None, stub_findings=None, stub_missing=False):
        """跑一次活动：缺省=空 findings 合法桩；stub_missing=True=桩夹具路径不存在。"""
        if stub_missing:
            stub_file = os.path.join(self._tmp, "no-such-stub.txt")
        else:
            if stub_text is None:
                stub_text = base.fenced_message(stub_findings if stub_findings is not None else [])
            stub_file = base.write_stub_file(self._tmp,
                                             "stub-%s-%s.txt" % (args.get("instance_id"),
                                                                 args.get("period")), stub_text)
        for k, v in (("SANDBAR_INSPECT_STUB", "1"),
                     ("SANDBAR_INSPECT_STUB_FILE", stub_file),
                     ("SANDBAR_INSPECTION_DIR", self._tmp)):
            self._old_env.setdefault(k, os.environ.get(k))
            os.environ[k] = v
        try:
            return base.run_coro(self.agent_activities.run_inspection_inspect(args))
        finally:
            for k in ("SANDBAR_INSPECT_STUB", "SANDBAR_INSPECT_STUB_FILE"):
                v = self._old_env.get(k)
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v

    def seed_prev(self, instance, period, **kw):
        return seed_prev_doc(self._tmp, instance, period, **kw)

    # ---- 断言容差访问器（行为锚定，不锚键名实现） ----

    def payload_text(self, payload):
        try:
            return json.dumps(payload, ensure_ascii=False, default=str)
        except Exception:
            return str(payload)

    def meta(self, payload):
        """meta 容差读取：真链=payload.meta；桩链=result.meta（arbitrate 定版双处查）。"""
        m = base.meta_of(payload)
        if m:
            return m
        if isinstance(payload, dict):
            r = payload.get("result")
            if isinstance(r, dict) and isinstance(r.get("meta"), dict):
                return r["meta"]
        return {}

    def result_ok(self, payload):
        return isinstance(payload, dict) and payload.get("ok") is True

    def scope_blob(self, payload):
        """scope 面汇总文本：meta.scope/scope_note/prompt 任一在处，全拼平供标记搜索。"""
        m = self.meta(payload)
        parts = [self.payload_text(m.get("scope")), self.payload_text(m.get("scope_block")),
                 self.payload_text(m.get("scope_note")), self.payload_text(m.get("prompt")),
                 self.payload_text(m.get("scope_meta")),
                 self.payload_text(m.get("notes"))]
        return "\n".join(parts)

    def has_any(self, blob, markers):
        return any(mk in blob for mk in markers)
