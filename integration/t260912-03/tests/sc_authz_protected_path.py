#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""受保护路径的人授权通道（t260912-03 验收 A/C/D，灰盒 L3）。

用户可感知契约（本场景锁的 intent）：
  泳道要改「真源与期望值文件」（integration/baselines 等，路径在 PROTECTED_PATHS 名单内
  且分叉点已存在）——**没有人授权时照旧拒收落盘**（机读 path_gate_reason=protected_path
  + 点名文件 + 0 commit，t260911-03 已锁的行为逐字节不变）；**持一张覆盖该路径、未过期
  的人授权时同一改动落盘成功**，且回执/时间线**点名授权人（who）、时间（issued）与路径**
  ——把「人审放行」这条写在拒收回执里的合法出路，从文案变成可执行的通道（260912 实证一：
  t260912-01 改 integration/baselines/* 被拒且无任何授权入口，票停在 implement/blocked）。

负锁（防恒真，全部必须照旧红）：
  · scope 不匹配的授权（批了 docs/design，用来放 baselines）→ 拒；
  · 过期授权 → 拒；空/畸形授权条目 → 拒（不放大）；
  · who 为 agent 自身角色名 → 拒收（反自签红线）；
  · 授权只对本票生效：arbitration_verdict 类授权 scope 必须是本票票号，别票票号拒收；
    落点＝本票 workflow 的 meta（另一个 workflow 壳读不到）。

分层与依据（防 intent 级重复）：
  · 与 t260911-03-protected-settle-reject（无授权面的 settle 执法终态）**同台架不同 intent**：
    彼锁「无授权一律拒」（本条腿 A1 复用它守零回归），本条新增「有授权＝真落地 + 记名点名」
    与授权负锁；两条都不锚实现内部结构。
  · 与 developer L1（judge 纯函数/载荷矩阵/上限）不同层：本条锁真实链路（真 git 泳道 +
    真 settle 单点 + 真 sign 信号 handler）下的用户可感知终态。scope 前缀相邻串语义
    （`integration/baselines` 不得命中 `integration/baselines2`）归 L1 的 `_within` 矩阵，
    本条不重复（L3 拿不到「名单内 + 相邻名」的可执法样本）。
  · 授权入参形状（结构化记录 / 裸 scope 串）由校准腿自适应两种实现，但**行为要求不变**：
    放行 + 回执点名 who/issued/理由（裸串形状点不出人＝A2 腿红，对应 review C1）。
  · 依据：工单验收 A①②③④、C（可查性）、D（t260912-01 真实形态）；KI-074 未闭合项不属本条范围
    （名单仍为引擎内声明，本场景不替它背书）。

跑法：PY=server/engine/.venv/bin/python; [ -x "$PY" ] || PY=python3; "$PY" -B
      integration/t260912-03/tests/sc_authz_protected_path.py   （cwd=仓根）
纯本地：tmp 主仓 + 真注册泳道 worktree + 直调 settle 单点，零 Temporal server 零端口。
三态：PASS exit 0 / FAIL exit 1 / ENV_FAIL exit 2（无第四态）。
实现段落地前红属预期（TDD 验收门，先例 t260911-03），arbitrate/merge 期必须绿。
"""
import dataclasses
import datetime
import inspect
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace

REPO = Path(__file__).resolve().parents[3]
TICKET = "t260912-03"
TARGET = "integration/baselines/sc_battery.py"      # 受保护名单内的共享电池
TARGET_DIR = "integration/baselines"                # 目录前缀形态 scope
OTHER_PATH = "docs/design/contract-v1.md"           # 另一条受保护路径（scope 不匹配腿用）
BATTERY_V2 = "# authorized expectation edit\n"
AUTH_WHO = "宿主"
AUTH_REASON = "t260912-03 场景：批准本票改共享电池期望值（八文件路径探测修法的一部分）"

_ok = _fail = 0


def ok(cond, label):
    global _ok, _fail
    print(("  ok " if cond else "  FAIL ") + label)
    _ok, _fail = _ok + (1 if cond else 0), _fail + (0 if cond else 1)


def section(t):
    print("\n== " + t)


def sh(*cmd, cwd=None):
    return subprocess.run([str(c) for c in cmd], capture_output=True, text=True,
                          cwd=str(cwd) if cwd else None)


def head(repo):
    return sh("git", "-C", repo, "rev-parse", "HEAD").stdout.strip()


def load_engine():
    if shutil.which("git") is None:
        print("ENV_FAIL: git 不可用（本场景全程真 git 仓）")
        sys.exit(2)
    try:
        import temporalio  # noqa: F401
    except Exception:
        print("ENV_FAIL: temporalio 不可导入——用 server/engine/.venv/bin/python 跑"
              "（KI-036 口径：缺环境点名，环境红非产品红）")
        sys.exit(2)
    sys.path.insert(0, str(REPO / "server" / "engine"))
    import agent_activities
    import dev_lane
    import shared
    return agent_activities, dev_lane, shared


BASE = {
    "verify.yaml": "schema: v1\nlanes:\n  code:\n    write_allow:\n"
                   "      - server/engine/\n      - integration/\n    checks: []\n",
    "server/engine/keep.py": "# engine anchor\n",
    "docs/design/contract-v1.md": "# contract v1\n",
    TARGET: "# shared battery\n",
    "integration/t260902-07/tests/test_route_table.py": "# shared guard\n",
    "integration/t260912-03/tests/.keep": "",
}


def mk_lane(prefix):
    """tmp 主仓（带本地 git 身份）+ 真注册泳道 worktree → (tmp, main, lane, 分叉 sha)。"""
    tmp = Path(tempfile.mkdtemp(prefix=prefix))
    main = tmp / "main"
    main.mkdir()
    for rel, content in BASE.items():
        p = main / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
    sh("git", "init", "-q", "-b", "main", cwd=main)
    sh("git", "config", "user.email", "t@t", cwd=main)
    sh("git", "config", "user.name", "t", cwd=main)
    sh("git", "add", "-A", cwd=main)
    sh("git", "commit", "-qm", "init", cwd=main)
    fork = head(main)
    lane = tmp / "lane"
    r = sh("git", "-C", main, "worktree", "add", "-q", "-b", "lane/" + TICKET, lane)
    if r.returncode != 0:
        print("ENV_FAIL: worktree add 失败：%s" % r.stderr.strip())
        sys.exit(2)
    return tmp, main, lane, fork


# ---------------- 授权载荷适配（对 args 形状容忍，但要求行为：放行 + 点名） ----------------

def authz_param_name(aa):
    """settle 签名里的授权形参名（未接线 → None，腿内点名）。"""
    try:
        params = inspect.signature(aa._settle_worktree_lane).parameters
    except (TypeError, ValueError):
        return None
    if "path_gate" not in params:
        return None
    for name in params:
        low = name.lower()
        if "authoriz" in low or low in ("authz", "authorized", "auths"):
            return name
    return None


def authz_records(scope, kind="protected_path", who=AUTH_WHO, reason=AUTH_REASON,
                  expires_in=3600, now=None):
    now = int(now if now is not None else time.time())
    return [{"kind": kind, "who": who, "scope": list(scope), "reason": reason,
             "issued": now, "expires": now + expires_in}]


def settle(aa, lane, mainrepo, stage, gen=0, write_set=None, base="", authz=None):
    """直调 settle 单点；返回 (note, err)。authz=None=不传授权形参（老调用形状）。"""
    try:
        sig = inspect.signature(aa._settle_worktree_lane).parameters
    except (TypeError, ValueError):
        sig = {}
    has_face = "face" in sig  # t260916-19 D：face 必填分层标签——新老树两侧可跑
    if authz_param_name(aa) is None and authz is None:
        # 老形状：完全不传授权参数（等价存量调用）——用于 A1 零回归腿。
        try:
            kw = dict(repo=mainrepo, path_gate=True,
                      write_set=list(write_set or []), base_ref=str(base))
            if has_face:
                kw["face"] = "join"  # 「老形状」锁的是授权参数缺省语义，非标签形参
            return aa._settle_worktree_lane(lane, TICKET, stage, gen, **kw), None
        except Exception as e:  # noqa: BLE001
            return None, "settle 调用异常：%s" % e
    if authz is not None and authz_param_name(aa) is None:
        return None, "授权形参未落地（settle 签名无 authorizations 类参数）——人授权通道未接线"
    kw = {"repo": mainrepo, "path_gate": True,
          "write_set": list(write_set or []), "base_ref": str(base)}
    if authz is not None:
        kw[authz_param_name(aa)] = authz
    if has_face:
        kw["face"] = "join"
    try:
        return aa._settle_worktree_lane(lane, TICKET, stage, gen, **kw), None
    except Exception as e:  # noqa: BLE001
        return None, "settle 调用异常：%s" % e


def edit(lane, rel, text=BATTERY_V2):
    (lane / rel).write_text(text, encoding="utf-8")


def commits_in_head(lane):
    return sh("git", "-C", lane, "show", "--name-only", "--format=", "HEAD").stdout.splitlines()


def probe_shape(aa):
    """calibrate: args 形状（结构化记录 / 裸 scope 串）——两种实现都容忍，行为不变。

    返回 (shape, payload_builder, diag)。行为面要求不变：覆盖该路径的生效授权 → 放行。
    """
    candidates = [
        ("records", lambda scope: authz_records(scope)),
        ("scope-strings", lambda scope: list(scope)),
    ]
    diags = []
    for shape, build in candidates:
        tmp, main, lane, fork = mk_lane("authz-probe-")
        try:
            edit(lane, TARGET)
            before = head(lane)
            note, err = settle(aa, lane, main, "design_integration_tests", base=fork,
                               authz=build([TARGET_DIR]))
            if note is None:
                diags.append("%s → settle 驱动失败：%s" % (shape, err))
                continue
            passed = ("path_gate_reason=protected_path" not in note) and head(lane) != before
            diags.append("%s → %s（回执尾：%s）" % (shape, "放行" if passed else "未放行",
                                                 note[-160:]))
            if passed:
                return shape, build, diags
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    return None, None, diags


# ---------------- 信号面 intake（L2 壳驱动：真 handler，零 Temporal） ----------------

def mk_wf(dev_lane, ticket_id=TICKET, now=None, stage="implement", state="blocked"):
    dev_lane.workflow = SimpleNamespace(
        patched=lambda pid: False,
        now=lambda: now or datetime.datetime(2026, 9, 12, 6, 0, 0),
        logger=SimpleNamespace(info=lambda *a, **k: None,
                               warning=lambda *a, **k: None,
                               error=lambda *a, **k: None))
    wf = object.__new__(dev_lane.DevLaneWorkflow)
    wf.meta = {"stage": stage, "stage_state": state, "status": "dispatched"}
    wf.refused = []
    wf.timeline = []
    wf.signatures = {}
    wf._sigs = {}
    wf.ticket_id = ticket_id
    return wf


def sign_field(shared):
    """Signature 上的授权载荷字段名（未落地 → None）。"""
    try:
        names = [f.name for f in dataclasses.fields(shared.Signature)]
    except TypeError:
        return None
    for n in names:
        if "authoriz" in n.lower():
            return n
    return None


def make_authz(shared, dev_lane, kind, who, scope, reason, expires_in, now=None):
    cls = getattr(shared, "HumanAuthorization", None)
    if cls is None:
        return None, "HumanAuthorization 载荷未落地"
    ts = int((now or dev_lane.workflow.now()).timestamp())
    try:
        return cls(kind=kind, who=who, scope=list(scope), reason=reason,
                   expires=ts + expires_in, issued=ts), None
    except TypeError as e:
        return None, "HumanAuthorization 字段形状不符：%s" % e


def send_sign(dev_lane, shared, wf, who, authorize, gate="", decision="approve"):
    fld = sign_field(shared)
    if fld is None:
        return "Signature.authorize 载荷字段未落地"
    sig = shared.Signature(who=who, gate=gate, decision=decision, note="")
    setattr(sig, fld, authorize)
    fn = dev_lane.DevLaneWorkflow.__dict__["sign"]
    fn = getattr(fn, "__func__", fn)
    try:
        fn(wf, sig)
    except Exception as e:  # noqa: BLE001
        return "sign handler 异常：%s: %s" % (type(e).__name__, e)
    return ""


def active_entries(wf, dev_lane):
    now = int(dev_lane.workflow.now().timestamp())
    out = []
    for e in (wf.meta.get("authorizations") or []):
        try:
            exp = int((e.get("expires") if isinstance(e, dict) else getattr(e, "expires")) or 0)
        except (TypeError, ValueError):
            continue
        if exp > now:
            out.append(e)
    return out


def main():
    aa, dev_lane, shared = load_engine()

    # ---------- A1 零回归：无授权改共享电池 → 照旧拒 ----------
    section("A1 无授权 · design_integration_tests 段改共享电池 → protected_path + 0 commit")
    tmp, mainrepo, lane, fork = mk_lane("authz-a1-")
    try:
        edit(lane, TARGET)
        before = head(lane)
        note, err = settle(aa, lane, mainrepo, "design_integration_tests", base=fork)
        if note is None:
            ok(False, "A1 驱动失败：%s" % (err or "note 缺失"))
        else:
            ok("path_gate_reason=protected_path" in note, "受保护原因码在回执")
            ok(TARGET in note, "点名文件 %s" % TARGET)
            ok(head(lane) == before, "0 新 commit（拒收）")
            ok(TARGET in "\n".join(sh("git", "-C", lane, "status", "--porcelain").stdout.splitlines()),
               "泳道脏改动原样保留（agent 产物不丢）")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    if authz_param_name(aa) is None:
        print("  · 授权形参未接线：显式空授权表腿（workflow 传空过滤集）待实现段落地后生效")
    else:
        section("A1b 无授权（显式空授权表）→ 照旧拒（零回归第二形状）")
        tmp, mainrepo, lane, fork = mk_lane("authz-a1b-")
        try:
            edit(lane, TARGET)
            before = head(lane)
            note, err = settle(aa, lane, mainrepo, "design_integration_tests", base=fork,
                               authz=[])
            ok(note is not None and "path_gate_reason=protected_path" in note
               and head(lane) == before, "空授权表→拒+0 commit（%s）"
               % ((err or (note or "")[-80:]).strip()))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    # ---------- 形状校准：覆盖该路径的授权 → 放行（两种 args 形状都容忍） ----------
    section("P 形状校准 · 生效授权（目录前缀 scope）覆盖该路径 → 放行")
    shape, build, diags = probe_shape(aa)
    for d in diags:
        print("  · " + d)
    if shape is None:
        ok(False, "生效授权不放行（授权通道未接线或行为未兑现）——见上方校准诊断")
    else:
        ok(True, "授权载荷形状＝%s（生效授权覆盖 %s → 放行）" % (shape, TARGET_DIR))

    if shape is not None:
        def az(scope, **kw):
            """按校准到的形状产授权载荷；返回 (payload, issued_ts)。"""
            if shape == "scope-strings":
                return build(scope), None
            recs = authz_records(scope, **kw)
            return recs, recs[0]["issued"]

        # ---------- A2 生效授权 → 落盘成功 + 记名点名 ----------
        section("A2 生效授权（scope=%s）→ 落盘成功 + 回执点名授权人/时间/路径/理由" % TARGET_DIR)
        tmp, mainrepo, lane, fork = mk_lane("authz-a2-")
        try:
            edit(lane, TARGET)
            before = head(lane)
            payload, issued = az([TARGET_DIR])
            note, err = settle(aa, lane, mainrepo, "design_integration_tests", base=fork,
                               authz=payload)
            if note is None:
                ok(False, "A2 驱动失败：%s" % err)
            else:
                ok("path_gate_reason=protected_path" not in note, "受保护拒收消失（放行）")
                ok(head(lane) != before, "commit 真落地")
                ok(TARGET in commits_in_head(lane), "提交里逐文件点名 %s" % TARGET)
                ok(AUTH_WHO in note, "回执点名授权人 %r" % AUTH_WHO)
                ok(TARGET in note, "回执点名被批路径")
                if issued is None:
                    ok(False, "args 形状＝裸 scope 串：回执无法点名授权人与时间"
                              "（review C1 修正未落：载荷须可归因到 who/issued）")
                else:
                    ok(str(issued) in note or time.strftime("%Y", time.localtime(issued)) in note,
                       "回执带签发时间（issued=%s）" % issued)
                ok(AUTH_REASON[:12] in note, "回执带理由面")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

        # ---------- A3 scope 不匹配 → 照旧红 ----------
        section("A3 负锁 · scope 不匹配（批的是 %s）→ 照旧拒" % OTHER_PATH)
        tmp, mainrepo, lane, fork = mk_lane("authz-a3-")
        try:
            edit(lane, TARGET)
            before = head(lane)
            note, err = settle(aa, lane, mainrepo, "design_integration_tests", base=fork,
                               authz=az([OTHER_PATH])[0])
            if note is None:
                ok(False, "A3 驱动失败：%s" % err)
            else:
                ok("path_gate_reason=protected_path" in note, "路径不匹配的授权→仍拒")
                ok(head(lane) == before, "0 新 commit")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

        # ---------- A4 精确路径 scope 命中 → 放行 ----------
        section("A4 精确路径 scope（%s）→ 放行（同 _within 语义：条目==路径）" % TARGET)
        tmp, mainrepo, lane, fork = mk_lane("authz-a4-")
        try:
            edit(lane, TARGET)
            before = head(lane)
            note, err = settle(aa, lane, mainrepo, "design_integration_tests", base=fork,
                               authz=az([TARGET])[0])
            if note is None:
                ok(False, "A4 驱动失败：%s" % err)
            else:
                ok("path_gate_reason=protected_path" not in note and head(lane) != before,
                   "精确路径授权→放行落盘")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

        # ---------- A5 空/畸形授权 → 不放大（照旧红） ----------
        section("A5 负锁 · 空 scope 条目 → 照旧拒（不放大）")
        tmp, mainrepo, lane, fork = mk_lane("authz-a5-")
        try:
            edit(lane, TARGET)
            note, err = settle(aa, lane, mainrepo, "design_integration_tests", base=fork,
                               authz=az([])[0])
            ok(note is not None and "path_gate_reason=protected_path" in note,
               "空 scope 授权不放行（%s）" % ((err or (note or "")[-80:]).strip()))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    # ---------- 信号面 intake（真 handler）：授权载荷 + 负锁 ----------
    section("S1 intake · 合法授权 → 入 meta（who/scope/issued/expires 可查）")
    now = datetime.datetime(2026, 9, 12, 6, 0, 0)
    wf = mk_wf(dev_lane, now=now)
    obj, err = make_authz(shared, dev_lane, "protected_path", AUTH_WHO, [TARGET_DIR],
                          AUTH_REASON, 3600, now=now)
    if obj is None:
        ok(False, "S1 载荷未落地：%s（人授权信号面未接线）" % err)
    else:
        serr = send_sign(dev_lane, shared, wf, AUTH_WHO, obj)
        ok(not serr, "sign(authorize) 受理（%s）" % (serr or "ok"))
        act = active_entries(wf, dev_lane)
        ok(len(act) == 1, "meta.authorizations 增一条生效条目（%d）" % len(act))
        if act:
            e = act[0]
            got = e if isinstance(e, dict) else {k: getattr(e, k, None)
                                                 for k in ("kind", "who", "scope", "expires", "issued")}
            ok(got.get("who") == AUTH_WHO, "记名 who=%r" % got.get("who"))
            ok(TARGET_DIR in (got.get("scope") or []), "记 scope=%r" % (got.get("scope"),))
            ok(int(got.get("expires") or 0) > int(now.timestamp()), "记到期时刻（可判过期）")

    section("S2 负锁 · 过期授权 → 不产生生效条目（到期作废）")
    wf = mk_wf(dev_lane, now=now)
    obj, err = make_authz(shared, dev_lane, "protected_path", AUTH_WHO, [TARGET_DIR],
                          AUTH_REASON, -60, now=now)
    if obj is None:
        ok(False, "S2 载荷未落地：%s" % err)
    else:
        serr = send_sign(dev_lane, shared, wf, AUTH_WHO, obj)
        ok(len(active_entries(wf, dev_lane)) == 0,
           "过期授权无生效条目（refused=%d 条，handler=%s）" % (len(wf.refused), serr or "ok"))

    section("S3 负锁 · who=agent 自身角色名（含大小写/空白/-agent 家族）→ 拒收")
    agents = ["developer", "integration", "Product-Operation", " integration ", "integration-agent"]
    for who in agents:
        wf = mk_wf(dev_lane, now=now)
        obj, _ = make_authz(shared, dev_lane, "protected_path", who, [TARGET_DIR],
                            AUTH_REASON, 3600, now=now)
        if obj is None:
            ok(False, "S3 载荷未落地")
            break
        send_sign(dev_lane, shared, wf, who, obj)
        ok(len(active_entries(wf, dev_lane)) == 0 and bool(wf.refused),
           "who=%r 拒收（生效条目 0，refused=%d）" % (who, len(wf.refused)))

    section("S4 负锁 · arbitration_verdict scope=别票票号 → 拒收（授权只对本票生效）")
    wf = mk_wf(dev_lane, now=now)
    obj, _ = make_authz(shared, dev_lane, "arbitration_verdict", AUTH_WHO, ["t-260912-99"],
                        AUTH_REASON, 3600, now=now)
    if obj is not None:
        send_sign(dev_lane, shared, wf, AUTH_WHO, obj)
        ok(len(active_entries(wf, dev_lane)) == 0 and bool(wf.refused), "别票票号拒收")
        other = mk_wf(dev_lane, ticket_id="t-260912-98", now=now)
        ok(not (other.meta.get("authorizations")), "别票 workflow 壳读不到本票授权（落点=本票 meta）")

    section("S5 零回归 · 不带 authorize 的普通签字：merge 人门语义不变（不落授权）")
    wf = mk_wf(dev_lane, now=now, stage="merge", state="awaiting-human")
    serr = send_sign(dev_lane, shared, wf, AUTH_WHO, None, gate="merge")
    ok(not serr, "普通签字受理（%s）" % (serr or "ok"))
    ok(bool(wf._sigs.get("merge")), "落 merge 人门签字（既有语义）")
    ok(not (wf.meta.get("authorizations")), "不产生授权条目（零回归）")

    section("S6 负锁 · 畸形/超上限载荷 → 拒收不进历史")
    cases = [("who 超长", dict(who="H" * 200, scope=[TARGET_DIR], reason=AUTH_REASON, exp=3600)),
             ("reason 超长", dict(who=AUTH_WHO, scope=[TARGET_DIR], reason="R" * 30000, exp=3600)),
             ("scope 17 条", dict(who=AUTH_WHO, scope=[TARGET_DIR] * 17, reason=AUTH_REASON, exp=3600)),
             ("path 非法", dict(who=AUTH_WHO, scope=["../../etc/passwd"], reason=AUTH_REASON, exp=3600))]
    for label, c in cases:
        wf = mk_wf(dev_lane, now=now)
        obj, _ = make_authz(shared, dev_lane, "protected_path", c["who"], c["scope"],
                            c["reason"], c["exp"], now=now)
        if obj is None:
            ok(False, "S6 载荷未落地")
            break
        send_sign(dev_lane, shared, wf, c["who"], obj)
        ok(len(active_entries(wf, dev_lane)) == 0 and bool(wf.refused), "%s → 拒收" % label)

    print("\nSC sc_authz_protected_path pass=%d fail=%d" % (_ok, _fail))
    return 0 if _fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
