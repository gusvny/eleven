#!/usr/bin/env python3
"""t260924-05 · KI-116 巡检套件回执信号面（灰盒 L3，真缝夹具，秒级，ro 池）。

用户可感知契约（工单正文病象逐条反演，锚公开回执形状 verify_lane 头注
「lane=integ → {lane, green, ran, pass, fail, scenarios, err}」，不锚实现内部）：
巡检等价路径（生产入口 admin.py call verify_lane lane=integ）的回执必须产出
**真实场景信号**——A 正常套件 ran>0 且计数不撒谎；B 零场景信号永不静默绿
（KI-116 病象②「260918 期 ran=0 绿」的回归锁，正是 implement 要拆的逃逸口）；
C 同一套件重复下单量级稳定（必做③棒「与同套件量级一致」的集成面：差 0≤1 且
≤10% 取严）；D 畸形 timeout 载荷 fail-closed 显式红不静默（方案 v2 步2 载荷
形状变更的回放安全面；老形状载荷=本场景 A/C 已在用，天然覆盖缺键回落）。

真缝夹具（t260922-12 同族，按票自足不跨票 import）：临时 git 仓 verify.yaml
integration.cmd→桩执行器 × 生产 admin.py call verify_lane × SANDBAR_SCENARIO_ONLY
定点。夹具自带桩，绝不递归进真场景注册表；全落系统临时目录，零真仓接触，
不触 3099/7233，零 docker 零端口。

三态：git 缺失/temporal 面不可用等环境缺席=ENV_FAIL exit 2；断言红=exit 1。
实现落地前 B/D 红属预期（TDD 信号：逃逸口与 fail-closed 尚未落地），
arbitrate/merge 期必须全绿。
"""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

# 桩执行器：输出规范行协议（PASS [name] + INTEG_SUMMARY 汇总行，闸重算复核面），
# 与真执行器输出契约同形（t260904-12 定稿 §7.3）。零选中（ONLY 指向缺席名）时
# 零 PASS 行+INTEG_SUMMARY ran=0+exit 0——正是现状「ran==0 且有 { 开头行且
# exit==0 → 静默绿」逃逸口的触发形态。
STUB = r'''#!/usr/bin/env python3
import json, os, sys
ONLY = [s for s in (os.environ.get("SANDBAR_SCENARIO_ONLY") or "").split(",") if s]
DEFAULT = @@DEFAULT@@
selected = ONLY or list(DEFAULT)
names = [n for n in selected if n in DEFAULT]
for n in names:
    print("PASS [%s]" % n)
print("INTEG_SUMMARY " + json.dumps(
    {"ran": len(names), "pass": len(names), "fail": 0,
     "expected": len(DEFAULT)}))
sys.exit(0)
'''


def make_fixture(default_names):
    """临时仓：verify.yaml（integration.cmd→桩）+ 桩 + git init/commit（main）。"""
    repo = Path(tempfile.mkdtemp(prefix="t26092405-"))
    (repo / "verify.yaml").write_text(
        "schema: v1\nlanes:\n  code:\n    write_allow:\n      - src/\n"
        "integration:\n  cmd: python3 stub_exec.py\n", encoding="utf-8")
    (repo / "stub_exec.py").write_text(
        STUB.replace("@@DEFAULT@@", repr(list(default_names))), encoding="utf-8")
    r = subprocess.run(["git", "init", "-b", "main"], cwd=str(repo),
                       capture_output=True, text=True)
    if r.returncode != 0:  # 旧 git 无 -b：init+branch 兜底
        subprocess.run(["git", "init"], cwd=str(repo), capture_output=True)
        subprocess.run(["git", "-C", str(repo), "checkout", "-b", "main"],
                       capture_output=True)
    subprocess.run(["git", "-C", str(repo), "add", "-A"], capture_output=True)
    subprocess.run(["git", "-C", str(repo), "-c", "user.email=t@t",
                    "-c", "user.name=t", "commit", "-m", "stub"],
                   capture_output=True)
    return repo


def call_gate(repo, payload, extra_env=None, timeout=240):
    """真缝调闸：admin.py call verify_lane lane=integ（生产 spawn 同款入口）。"""
    env = dict(os.environ)
    env.update(extra_env or {})
    try:
        p = subprocess.run(
            [sys.executable, "server/admin.py", "call", "verify_lane",
             json.dumps(payload)],
            cwd=str(REPO), capture_output=True, text=True, timeout=timeout,
            env=env)
    except subprocess.TimeoutExpired:
        return {"ok": False, "err": "gate call timeout", "green": False}
    if p.returncode != 0:
        return {"ok": False,
                "err": ((p.stderr or "") + (p.stdout or ""))[-400:],
                "green": False}
    try:
        parsed = json.loads(p.stdout)
    except json.JSONDecodeError:
        return {"ok": False, "err": "unparseable: " + p.stdout[-300:],
                "green": False}
    inner = parsed.get("result") if isinstance(parsed, dict) else None
    if not isinstance(inner, dict):
        return {"ok": False, "err": "no result envelope", "green": False}
    inner.setdefault("ok", True)
    return inner


def fail(msg):
    print("FAIL[ki116] " + msg)
    return 1


def main():
    if subprocess.run(["git", "--version"], capture_output=True).returncode != 0:
        print("ENV_FAIL [ki116] git 缺失——夹具无法建临时仓")
        return 2
    bad = []
    base_payload = lambda r: {"lane": "integ", "path": str(r)}  # noqa: E731 老形状载荷（缺 timeout 键=回放兼容面）

    # ---- A 信号面：正常套件 ran>0 且计数不撒谎（ran==pass+fail==场景行数）
    names = ("ki116-a", "ki116-b")
    repo_a = make_fixture(names)
    ra = call_gate(repo_a, base_payload(repo_a))
    if not ra.get("ok"):
        bad.append("A 闸调用失败: %s" % ra.get("err", "")[-200:])
    elif not (ra.get("ran", 0) > 0 and ra.get("green") is True):
        bad.append("A 回执无信号: green=%s ran=%s err=%s"
                   % (ra.get("green"), ra.get("ran"), str(ra.get("err"))[-200:]))
    else:
        rows = [s.get("name") for s in (ra.get("scenarios") or [])]
        if ra["ran"] != ra.get("pass", -1) + ra.get("fail", -1):
            bad.append("A 计数撒谎: ran=%s pass=%s fail=%s"
                       % (ra["ran"], ra.get("pass"), ra.get("fail")))
        if sorted(rows) != sorted(names):
            bad.append("A 场景行与名单错位: %s" % rows)

    # ---- B 零信号显式红：逃逸口拆除后，零场景信号不得冒充绿（KI-116 病象②回归锁）
    repo_b = make_fixture(("ki116-b1",))
    rb = call_gate(repo_b, base_payload(repo_b),
                   extra_env={"SANDBAR_SCENARIO_ONLY": "ki116-zzz-missing"})
    if not rb.get("ok"):
        pass  # 显式红（顶层报错）=允许形态
    elif rb.get("green") is not False or not str(rb.get("err") or "").strip():
        bad.append("B 零场景信号仍静默绿: green=%s ran=%s err=%r（逃逸口未拆）"
                   % (rb.get("green"), rb.get("ran"), rb.get("err")))

    # ---- C 重复下单量级稳定：同套件两次下单 ran 恒等（差 0，满足 ≤1 且 ≤10% 取严）
    repo_c = make_fixture(("ki116-c1", "ki116-c2", "ki116-c3"))
    r1 = call_gate(repo_c, base_payload(repo_c))
    r2 = call_gate(repo_c, base_payload(repo_c))
    if not (r1.get("ok") and r2.get("ok")):
        bad.append("C 重复下单失败: %s / %s"
                   % (str(r1.get("err"))[-120:], str(r2.get("err"))[-120:]))
    else:
        n1, n2 = r1.get("ran", -1), r2.get("ran", -1)
        if not (n1 == n2 == 3):
            bad.append("C 量级漂移: 两次 ran=%s/%s（期望恒等 3；容差 ≤1 且 ≤10%% 双违反）"
                       % (n1, n2))

    # ---- D 畸形 timeout 载荷 fail-closed：显式红不静默（方案 v2 步2 形状变更面）
    # （仲裁修正：载荷键名按实现契约=integ_timeout_sec（verify_lane._integ_timeout_sec），
    #   初稿误用 'timeout' 键=被忽略恒绿，红是测试错不是产品错。）
    repo_d = make_fixture(("ki116-d1",))
    rd = call_gate(repo_d, dict(base_payload(repo_d), integ_timeout_sec="not-a-number"))
    if rd.get("ok") and rd.get("green") is True:
        bad.append("D 畸形 integ_timeout_sec 载荷被静默放绿（fail-closed 缺位）")
    # 老形状回落：A/C 用即老形状载荷（无 timeout 键）已过——缺键回落兼容不再单列断言。

    for r in (repo_a, repo_b, repo_c, repo_d):
        subprocess.run(["rm", "-rf", str(r)], capture_output=True)

    if bad:
        for m in bad:
            fail(m)
        print("FAIL[ki116] %d 条断言红（实现落地前 B/D 红属 TDD 预期）" % len(bad))
        return 1
    print("PASS [t260924-05-ki116-inspection-receipt-signal] "
          "A 信号面/B 零信号显式红/C 量级稳定/D 畸形载荷 fail-closed 全绿")
    return 0


if __name__ == "__main__":
    sys.exit(main())
