#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""t260916-21 场景：admin.log 按天轮转+保留窗+同日过大顺切+审计写失败点名（灰盒 L3）。

intent（用户可感知契约 = 工单验收①-⑥ 的集成层兑现）：
- ①按天轮转恰好一次：活跃文件 mtime 本地日 ≠ 今日的首笔写入把 admin.log 原子改名
  admin.log.YYYYMMDD（归档名=文件关闭日），后续写新文件；同日多写零归档（「一天一个」
  反向锁）、轮转落定后不再二次轮转。
- ②存量迁移考古：现存 admin.log（手工造两代 schema 行：旧 run_id/actor/name +
  新 call_id/source/sub——工单正文钦点）跨日首写时字节级原样归档（sha256 相等，
  不删不截断），两代行照存。
- ③多进程恰好一次 + 零静默分叉（两相）：相一=轮转写者×8 同栅栏竞速跨日首写——
  归档恰一份、无 rolling 残留、逐行 JSON 可解析（O_APPEND 单行完整性）、行数守恒、
  零静默分叉；相二=轮转落定后纯按路径追加写者×4（tools_registry / node 插件同语义，
  不参与轮转判定——review C1 混合写者普查面）+ 轮转写者×4 并发续写——全部落活跃
  文件、零丢失零重复、家族不增。纯追加写者不进竞速相：它先落笔会把 mtime 刷成今日
  掩蔽跨日态（出写集残留面，结果文件报告）；
- ④保留窗（宿主 260916 定稿：默认 14 天，配置在 project metadata）：缺省 14 天窗口
  过期仅删 admin.log.<8位日>[-<6位时>] 命名匹配面；显式 admin_log.keep_days=30 桩
  覆盖生效（配置可调面）；窗口内与命名面外（admin.log.bak / 形合日而日期非法如
  20269999 / 同名目录条目）一律不碰不炸（review C3 畸形名容错）。
- ⑤同日过大顺切（宿主定稿措辞：纯拆分，无「熔断」告警语义）：admin_log.max_mb 桩
  小值当日切 admin.log.YYYYMMDD-HHMMSS 一刀、切后写新文件、不连切、行数守恒。
- ⑥配置面（宿主 260916 定稿：project metadata，不用 env 旋钮）：保留窗/顺切阈值读
  「引擎所属项目」~/.sandbar/projects/<key>/project.yaml 顶层 admin_log: {keep_days,
  max_mb}（SANDBAR_PROJECTS_DIR 桩隔离，与 shared 装载器同一注册表面）；配置值畸形
  （keep_days: 两周 / max_mb: garbage）=回落内置缺省 14/512，不炸不误删不误切。
- ⑦写失败可感：SANDBAR_ADMIN_LOG 指向目录 = 跨平台稳定 OSError 桩（不依赖 chmod/
  特权位）：client.py 裸入口与 ticket.py 直 spawn 双公共入口回执均带 audit_write_failed
  点名（marker 跨入口 = 「审计先于打印」的集成面兑现），回执主契约 {ok,error} 不吞、
  stderr 留痕非空。SANDBAR_ADMIN_LOG 隔离全套生效；红线守卫=真仓 server/admin.log
  起止 size/mtime 零变化。

与相邻场景/层 intent 分界：t260910-06-ki067-entry-audit 守入口收口面（退出码/审计行
形状/entry_hint/双行契约），本场景守日志文件生命周期面（轮转/归档/保留窗/顺切/写失败
可感），其零回归由套件照跑该场景保证，不在此重复；轮转原语的纯函数矩阵与单进程行为
细节、配置解析纯函数矩阵归 developer L1 UT（server/engine/tests），本场景只钉真子进程
并发与公共入口回执。

环境口径（三态契约：PASS/FAIL/环境红，无跳过语义）：A/B/C/D2 段纯 stdlib 恒跑（audit 模块仅
stdlib）；D1 段（client.py 真子进程命令）需 temporalio 可导入，缺失=ENV_FAIL exit 2
点名（其余段照跑）；无 docker/真 Temporal/真 git 依赖。
红线：模块级先钉 SANDBAR_TARGET_HOST=127.0.0.1:9（不可达桩）；一切审计写经
SANDBAR_ADMIN_LOG 指向 mkdtemp，被测子进程同 env；注册表桩经 SANDBAR_PROJECTS_DIR
指向 mkdtemp（不触真 ~/.sandbar/projects）；收尾复核真仓 admin.log 零接触。
TDD：implement 落地前红属预期（此刻无轮转/无 marker——正是工单病灶形状：1.7GB 单文件
12.8 天未轮转 + 写失败回执无感）；arbitrate/merge 期必须绿。
"""
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
POC = REPO / "server" / "engine"
TICKET_PY = REPO / "server" / "tools" / "ticket.py"

# 红线：先于一切引擎面 import/spawn 钉死不可达桩；测试进程不写 pycache（保工作区干净）。
os.environ["SANDBAR_TARGET_HOST"] = "127.0.0.1:9"
os.environ.pop("SANDBAR_NAMESPACE", None)
for _k in ("SANDBAR_CLIENT_ENTRY", "SANDBAR_CLIENT_CALL_ID"):
    os.environ.pop(_k, None)
sys.dont_write_bytecode = True

sys.path.insert(0, str(POC))
import audit  # noqa: E402  仅 stdlib 依赖

passed = 0
failed = 0
env_fail_n = 0


def check(name, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
        print("ok    " + name)
    else:
        failed += 1
        print("FAIL  " + name + (("：" + detail) if detail else ""))


def env_fail(reason):
    global env_fail_n
    env_fail_n += 1
    print("ENV_FAIL " + reason, flush=True)


def summary():
    print("SUMMARY pass=%d fail=%d env_fail=%d" % (passed, failed, env_fail_n))
    return 1 if failed else (2 if env_fail_n else 0)


def stub_env(extra=None):
    env = dict(os.environ)
    env["SANDBAR_TARGET_HOST"] = "127.0.0.1:9"
    if extra:
        env.update(extra)
    return env


def parse_out_json(out):
    for ln in (out or "").splitlines():
        ln = ln.strip()
        if ln.startswith("{"):
            try:
                return json.loads(ln)
            except Exception:
                continue
    return {}


def _json_ok(line):
    try:
        json.loads(line)
        return True
    except Exception:
        return False


TMP = Path(tempfile.mkdtemp(prefix="t260916-21-rotation-"))
DAY_RE = re.compile(r"admin\.log\.\d{8}$")
OVERSIZE_RE = re.compile(r"admin\.log\.\d{8}-\d{6}(-[0-9A-Za-z]+)*$")


def fresh_dir(tag):
    d = TMP / tag
    d.mkdir(parents=True, exist_ok=True)
    return d


def fresh_registry(tag, keep=None, max_mb=None, key="enginetest"):
    """造独立注册表桩并把 SANDBAR_PROJECTS_DIR 指过去（宿主 260916 定稿的配置面：
    引擎所属项目条目 project.yaml 顶层 admin_log: {keep_days, max_mb}；dirs 覆盖
    引擎仓根=条目归属判定）。keep/max_mb=None=不写 admin_log 块（内置缺省 14/512）；
    传字符串可注入畸形值（回落缺省面）。每段独立根 → audit 配置缓存按根刷新。"""
    reg = fresh_dir(tag) / "registry"
    reg.mkdir(parents=True, exist_ok=True)
    d = reg / key
    d.mkdir(parents=True, exist_ok=True)
    lines = ["schema: v1", "project:", "  - key: %s" % key,
             "    name: 引擎测试桩", "    dirs:", "      - %s" % REPO]
    if keep is not None or max_mb is not None:
        lines.append("admin_log:")
        if keep is not None:
            lines.append("  keep_days: %s" % keep)
        if max_mb is not None:
            lines.append("  max_mb: %s" % max_mb)
    (d / "project.yaml").write_text("\n".join(lines) + "\n", encoding="utf-8")
    os.environ["SANDBAR_PROJECTS_DIR"] = str(reg)
    audit._reset_config()  # 测试钩子：确定性重读（生产路径零调用）
    return reg


def day_archives(d):
    return sorted(p.name for p in d.iterdir() if p.is_file() and DAY_RE.fullmatch(p.name))


def oversize_archives(d):
    return sorted(p.name for p in d.iterdir() if p.is_file() and OVERSIZE_RE.fullmatch(p.name))


def rolling_residues(d):
    return sorted(p.name for p in d.iterdir() if ".rolling." in p.name)


def log_state():
    """红线守卫观测点：真仓 admin.log 的 (size, mtime_ns)，缺席为 None。"""
    p = REPO / "server" / "admin.log"
    if not p.exists():
        return None
    st = p.stat()
    return (st.st_size, st.st_mtime_ns)


STATE0 = log_state()


def rotate_trigger(d, probe, stamp):
    """公共驱动：种子行 + mtime 拨昨日 + 一笔审计写（唯一杠杆=公共入口 audit_call）。"""
    log = d / "admin.log"
    log.write_text("seed\n", encoding="utf-8")
    os.utime(log, (stamp, stamp))
    os.environ["SANDBAR_ADMIN_LOG"] = str(log)
    audit.audit_call(probe, {"ok": True, "probe": probe})
    return log, time.strftime("%Y%m%d", time.localtime(stamp))


# ============ A 段：按天轮转 + 存量迁移考古（stdlib 恒跑） ============
print("---- A 段：按天轮转 + 存量迁移（stdlib 恒跑） ----")
fresh_registry("seg-a-reg")  # 空桩=内置缺省（14 天/512MB；A 段不触阈值与窗口）

dA = fresh_dir("seg-a")
LOGA = dA / "admin.log"
os.environ["SANDBAR_ADMIN_LOG"] = str(LOGA)

# A1 同日多写零归档（一天一个的反向锁）
audit.audit_call("rotate-a1", {"ok": True, "n": 1})
audit.audit_call("rotate-a1", {"ok": True, "n": 2})
check("A1 同日多写：零归档、单文件累计", LOGA.is_file() and not day_archives(dA)
      and len(LOGA.read_text(encoding="utf-8").splitlines()) == 2,
      "归档=%s 行数=%s" % (day_archives(dA), LOGA.stat().st_size if LOGA.exists() else "无文件"))

# A2/A3 跨日首写：惰性轮转 + 字节级考古（两代 schema，工单正文钦点形状）
stamp = time.time() - 86400
seed_old = json.dumps({"run_id": "r-legacy", "actor": "host", "name": "ticket-list",
                       "ok": True}, ensure_ascii=False)
seed_new = json.dumps({"ts": int(stamp), "call_id": "c-legacy", "source": "bare",
                       "sub": "running-tickets", "ok": True, "summary": "{}"},
                      ensure_ascii=False)
seed_bytes = (seed_old + "\n" + seed_new + "\n").encode("utf-8")
LOGA.write_bytes(seed_bytes)
os.utime(LOGA, (stamp, stamp))
expected_day = time.strftime("%Y%m%d", time.localtime(stamp))
seed_sha = hashlib.sha256(seed_bytes).hexdigest()
os.environ["SANDBAR_ADMIN_LOG"] = str(LOGA)
audit.audit_call("rotate-a2", {"ok": True, "probe": "cross-day"})
arch = dA / ("admin.log." + expected_day)

check("A2 跨日首写：归档恰一份、名=mtime 日", arch.is_file() and day_archives(dA) == [arch.name],
      "期望=%s 实得=%s" % (arch.name, day_archives(dA)))
check("A3 存量字节级原样归档（不删不截断，sha256 相等）",
      arch.is_file() and hashlib.sha256(arch.read_bytes()).hexdigest() == seed_sha,
      "归档在=%s" % arch.is_file())
active_lines = LOGA.read_text(encoding="utf-8").splitlines() if LOGA.is_file() else []
check("A4 活跃文件=新文件且仅含新行",
      len(active_lines) == 1 and _json_ok(active_lines[0])
      and json.loads(active_lines[0]).get("sub") == "rotate-a2",
      "活跃行数=%d" % len(active_lines))
check("A5 无 rolling 私有名残留", rolling_residues(dA) == [], str(rolling_residues(dA)))
arch_rows = [json.loads(x) for x in arch.read_text(encoding="utf-8").splitlines()] \
    if arch.is_file() else []
check("A6 两代 schema 行考古保全（旧 run_id 形+新 call_id 形照存）",
      len(arch_rows) == 2 and any("run_id" in r for r in arch_rows)
      and any("call_id" in r for r in arch_rows),
      "归档行数=%d" % len(arch_rows))

# ============ B 段：多进程并发恰好一次 + 混合写者（真子进程） ============
print("---- B 段：多进程并发恰好一次 + 混合写者（真子进程） ----")
fresh_registry("seg-b-reg")  # 空桩：子进程同 env 走内置缺省配置
dB = fresh_dir("seg-b")
LOGB = dB / "admin.log"
stamp = time.time() - 86400
expected_day_b = time.strftime("%Y%m%d", time.localtime(stamp))
seed_b = json.dumps({"seed": "pre-rotation", "run_id": "r-seed", "actor": "a",
                     "name": "n"}, ensure_ascii=False)
LOGB.write_text(seed_b + "\n", encoding="utf-8")
os.utime(LOGB, (stamp, stamp))
os.environ["SANDBAR_ADMIN_LOG"] = str(LOGB)
go = TMP / "seg-b-go"

# 轮转写者（走 audit 公共入口）；纯追加写者（tools_registry/node 插件同语义：
# 只按路径 open('a')，不参与轮转判定）——两相设计见下。
CHILD_ROT = """import sys, os, time
sys.path.insert(0, sys.argv[1])
os.environ['SANDBAR_ADMIN_LOG'] = sys.argv[2]
sys.dont_write_bytecode = True
import audit
t0 = time.time()
while not os.path.exists(sys.argv[3]) and time.time() - t0 < 30:
    time.sleep(0.005)
audit.audit_call('rotation-race', {'ok': True, 'marker': sys.argv[4]})
"""
CHILD_PLAIN = """import sys, os, time, json
t0 = time.time()
while not os.path.exists(sys.argv[2]) and time.time() - t0 < 30:
    time.sleep(0.005)
f = open(sys.argv[1], 'a', encoding='utf-8')
f.write(json.dumps({'plain': sys.argv[3]}) + chr(10))
f.close()
"""
def _spawn(child_code, argv):
    return subprocess.Popen([sys.executable, "-B", "-c", child_code] + argv,
                            env=stub_env(), cwd=str(REPO), stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, text=True)


def _join(procs, check_name):
    deadline = time.time() + 120
    bad = []
    for mk, p in procs:
        try:
            _o, e = p.communicate(timeout=max(5.0, deadline - time.time()))
        except subprocess.TimeoutExpired:
            p.kill()
            _o, e = p.communicate()
        if p.returncode != 0:
            bad.append("%s rc=%s err=%s" % (mk, p.returncode, (e or "")[-160:]))
    check(check_name, not bad, "；".join(bad)[:400])


# 相一（恰好一次竞速）：仅轮转写者×8 同栅栏抢跨日首写。纯追加写者不进本相——
# 它若先落笔会把 mtime 刷成今日、掩蔽跨日态（非轮转写者不参与日切判定，属
# 出写集残留面，见结果文件报告），竞速相注入它会把「恰好一次」变成抽签。
procs = [("m-rot-%02d" % i, _spawn(CHILD_ROT,
          [str(POC), str(LOGB), str(go), "m-rot-%02d" % i])) for i in range(8)]
go.write_text("go", encoding="utf-8")
_join(procs, "B0 8 轮转子进程全部正常退出")

fam = sorted(p.name for p in dB.iterdir() if p.is_file())
day_names = [n for n in fam if DAY_RE.fullmatch(n)]
check("B1 归档恰一份且名=mtime 日", day_names == ["admin.log." + expected_day_b],
      "期望=[admin.log.%s] 实得=%s" % (expected_day_b, fam))
check("B2 无 rolling 私有名残留", rolling_residues(dB) == [], str(rolling_residues(dB)))
blob = "".join((dB / n).read_text(encoding="utf-8") for n in fam)
missing = [i for i in range(8) if blob.count("m-rot-%02d" % i) != 1]
check("B3 竞速行零丢失零重复（8 标记各恰一次+种子在档）",
      not missing and "pre-rotation" in blob, "异常标记=%s" % missing)
lines = [x for x in blob.splitlines() if x.strip()]
bad_lines = [x[:80] for x in lines if not _json_ok(x)]
check("B4 逐行 JSON 可解析（O_APPEND 单行完整性）", not bad_lines, str(bad_lines[:2]))
check("B5 行数守恒（1 种子+8 竞速）", len(lines) == 9, "实得 %d 行" % len(lines))
check("B6 零静默分叉：家族恰为活跃+归档两文件",
      fam == sorted(["admin.log", "admin.log." + expected_day_b]), str(fam))

# 相二（混合写者稳态续写）：轮转已落定，纯追加写者×4 + 轮转写者×4 并发——
# 全部落活跃文件、零丢失零分叉（验收①写者群 worker×N+cli+workbench 的混合面）。
go2 = TMP / "seg-b-go2"
mixed = [("m-pln-%02d" % i, _spawn(CHILD_PLAIN, [str(LOGB), str(go2), "m-pln-%02d" % i]))
         for i in range(4)]
mixed += [("m-rot2-%02d" % i, _spawn(CHILD_ROT,
          [str(POC), str(LOGB), str(go2), "m-rot2-%02d" % i])) for i in range(4)]
go2.write_text("go", encoding="utf-8")
_join(mixed, "B7 混合写者 8 子进程全部正常退出")
fam2 = sorted(p.name for p in dB.iterdir() if p.is_file())
blob2 = "".join((dB / n).read_text(encoding="utf-8") for n in fam2)
miss2 = [m for m in ["m-pln-%02d" % i for i in range(4)]
         + ["m-rot2-%02d" % i for i in range(4)] if blob2.count(m) != 1]
check("B8 混合写者零丢失零重复零分叉（家族仍两文件、8 新标记各恰一次）",
      fam2 == fam and not miss2 and rolling_residues(dB) == [],
      "家族=%s 异常标记=%s" % (fam2, miss2))
check("B9 行数守恒（1 种子+16 写者）",
      sum(len((dB / n).read_text(encoding="utf-8").splitlines()) for n in fam2) == 17,
      "实得 %d 行" % sum(len((dB / n).read_text(encoding="utf-8").splitlines())
                         for n in fam2))

# B10 轮转落定后续写不再归档（一天一个；归档期已过的当日不再切第二刀）
n_day_before = len(day_names)
audit.audit_call("rotation-race", {"ok": True, "post": True})
post_lines = LOGB.read_text(encoding="utf-8").splitlines() if LOGB.is_file() else []
n_day_after = len([n for n in dB.iterdir() if DAY_RE.fullmatch(n.name)])
last_ok = bool(post_lines) and _json_ok(post_lines[-1]) \
    and json.loads(post_lines[-1]).get("sub") == "rotation-race" \
    and '"post": true' in str(json.loads(post_lines[-1]).get("summary", ""))
check("B10 落定后续写：不再归档、新行落活跃文件",
      n_day_after == n_day_before and last_ok,
      "归档数 %d→%d 活跃末行=%r" % (n_day_before, n_day_after,
                                   post_lines[-1][:80] if post_lines else ""))

# ============ C 段：同日过大顺切 + 保留窗 + 配置面（stdlib 恒跑） ============
print("---- C 段：同日过大顺切 + 保留窗 + 配置面（stdlib 恒跑） ----")

# C1 同日过大顺切（admin_log.max_mb 桩小值；默认 512 的取值语义归 developer L1，
# 不在集成层重灌 512MB）
fresh_registry("seg-c1-reg", max_mb=1)
dC1 = fresh_dir("seg-c1")
LOGC1 = dC1 / "admin.log"
os.environ["SANDBAR_ADMIN_LOG"] = str(LOGC1)
pad = "x" * 2048
n_fill = 0
while n_fill < 5000 and not oversize_archives(dC1):
    audit.audit_call("oversize-fill", {"n": n_fill, "pad": pad})
    n_fill += 1
ovs = oversize_archives(dC1)
check("C1a 超阈当日顺切一刀（admin.log.YYYYMMDD-HHMMSS）", len(ovs) == 1,
      "写 %d 行后顺切归档=%s" % (n_fill, ovs))
if ovs:
    op = dC1 / ovs[0]
    mt_day = time.strftime("%Y%m%d", time.localtime(op.stat().st_mtime))
    check("C1b 顺切名日期=文件自身 mtime 日（午夜安全）",
          op.name.startswith("admin.log." + mt_day + "-"), op.name)
post_active = LOGC1.read_text(encoding="utf-8").splitlines() if LOGC1.is_file() else []
audit.audit_call("oversize-post", {"post": True})
post_active2 = LOGC1.read_text(encoding="utf-8").splitlines() if LOGC1.is_file() else []
check("C1c 切后写新文件且不再连切",
      len(ovs) == 1 and len(oversize_archives(dC1)) == 1 and len(post_active2) == 2
      and json.loads(post_active2[-1]).get("sub") == "oversize-post",
      "顺切=%s 活跃行=%d" % (ovs, len(post_active2)))
fam_c1 = sorted(p.name for p in dC1.iterdir() if p.is_file())
total_c1 = sum(len((dC1 / n).read_text(encoding="utf-8").splitlines()) for n in fam_c1)
check("C1d 行数守恒（填充 n 笔+切刀后 1 笔）", total_c1 == n_fill + 1,
      "实得 %d 行（填充 %d 笔）" % (total_c1, n_fill))

# C2 保留窗：缺省 14 天（宿主定稿；空桩=零配置）——过期删、窗内留、面外不碰
fresh_registry("seg-c2-reg")
dC2 = fresh_dir("seg-c2")
os.environ["SANDBAR_ADMIN_LOG"] = str(dC2 / "admin.log")
now = time.time()
d45 = time.strftime("%Y%m%d", time.localtime(now - 45 * 86400))
d15 = time.strftime("%Y%m%d", time.localtime(now - 15 * 86400))
d13 = time.strftime("%Y%m%d", time.localtime(now - 13 * 86400))
d00 = time.strftime("%Y%m%d", time.localtime(now))
(dC2 / ("admin.log.%s" % d45)).write_text("old45\n", encoding="utf-8")
(dC2 / ("admin.log.%s-010203" % d45)).write_text("old45b\n", encoding="utf-8")
(dC2 / ("admin.log.%s" % d15)).write_text("gone15\n", encoding="utf-8")
(dC2 / ("admin.log.%s" % d13)).write_text("keep13\n", encoding="utf-8")
(dC2 / ("admin.log.%s" % d00)).write_text("keep00\n", encoding="utf-8")
(dC2 / "admin.log.bak").write_text("bak\n", encoding="utf-8")
(dC2 / "admin.log.20269999").write_text("malformed\n", encoding="utf-8")
(dC2 / "admin.log.19990101").mkdir()
LOGC2, expected_day_c2 = rotate_trigger(dC2, "sweep-probe", now - 86400)
check("C2a 缺省 14 天：过期归档删（日切形 d-45）",
      not (dC2 / ("admin.log." + d45)).exists(),
      "仍在=%s" % (dC2 / ("admin.log." + d45)).exists())
check("C2b 缺省 14 天：过期归档删（顺切形 d-45-HHMMSS）",
      not (dC2 / ("admin.log.%s-010203" % d45)).exists(),
      "仍在=%s" % (dC2 / ("admin.log.%s-010203" % d45)).exists())
check("C2c 缺省 14 天：窗外 15 天档删、窗内 13 天档留（默认值行为锁）",
      not (dC2 / ("admin.log." + d15)).exists()
      and (dC2 / ("admin.log." + d13)).exists(),
      "d15在=%s d13在=%s" % ((dC2 / ("admin.log." + d15)).exists(),
                            (dC2 / ("admin.log." + d13)).exists()))
check("C2d 窗口内当日档保留",
      (dC2 / ("admin.log." + d00)).exists(), "")
check("C2e 命名面外不碰（bak/形合日日期非法/同名目录条目）且不炸",
      (dC2 / "admin.log.bak").read_text(encoding="utf-8") == "bak\n"
      and (dC2 / "admin.log.20269999").is_file()
      and (dC2 / "admin.log.19990101").is_dir(), "")
check("C2f 本轮跨日归档照常产出",
      (dC2 / ("admin.log." + expected_day_c2)).is_file(),
      "期望=%s" % expected_day_c2)

# C2g 显式配置可调：admin_log.keep_days=30 桩 → 15 天档回到窗内（配置生效面）
fresh_registry("seg-c2g-reg", keep=30)
dC2g = fresh_dir("seg-c2g")
os.environ["SANDBAR_ADMIN_LOG"] = str(dC2g / "admin.log")
(dC2g / ("admin.log.%s" % d45)).write_text("old45\n", encoding="utf-8")
(dC2g / ("admin.log.%s" % d15)).write_text("keep15\n", encoding="utf-8")
LOGC2g, expected_day_c2g = rotate_trigger(dC2g, "sweep-probe-30", now - 86400)
check("C2g keep_days=30 显式桩：45 天档删、15 天档回窗内（可调面）",
      not (dC2g / ("admin.log." + d45)).exists()
      and (dC2g / ("admin.log." + d15)).is_file()
      and (dC2g / ("admin.log." + expected_day_c2g)).is_file(), "")

# C3 配置值畸形回落内置缺省（外部输入畸形面；宿主修订②：配在 project.yaml）
fresh_registry("seg-c3-reg", keep="两周", max_mb="garbage")
dC3 = fresh_dir("seg-c3")
os.environ["SANDBAR_ADMIN_LOG"] = str(dC3 / "admin.log")
(dC3 / ("admin.log.%s" % d45)).write_text("old45\n", encoding="utf-8")
(dC3 / ("admin.log.%s" % d13)).write_text("keep13\n", encoding="utf-8")
LOGC3, expected_day_c3 = rotate_trigger(dC3, "cfg-bad-keep", now - 86400)
check("C3a keep_days 畸形回落缺省 14（45 天档照删、13 天档留、不炸）",
      (dC3 / ("admin.log." + expected_day_c3)).is_file()
      and not (dC3 / ("admin.log." + d45)).exists()
      and (dC3 / ("admin.log." + d13)).is_file(), "")
audit.audit_call("cfg-bad-max", {"ok": True})
check("C3b max_mb 畸形回落缺省 512（不炸不误切）",
      not oversize_archives(dC3) and LOGC3.is_file()
      and len(LOGC3.read_text(encoding="utf-8").splitlines()) == 2, "")

# ============ D 段：审计写失败可感（真子进程 stdout/stderr） ============
print("---- D 段：审计写失败可感（真子进程 stdout/stderr） ----")
fresh_registry("seg-d-reg")  # 干净空桩：D 命令子进程不掺配置变量
blocker = fresh_dir("seg-d-blocker")  # 目录本身 = open('a') 的 OSError 桩（跨平台稳定）
env_d = stub_env({"SANDBAR_ADMIN_LOG": str(blocker)})


def temporalio_available():
    try:
        import temporalio  # noqa: F401
        return True
    except ImportError:
        return False


if not temporalio_available():
    env_fail("temporalio 缺失——D1（client.py 裸入口真子进程命令）无 stdlib 替代；"
             "A/B/C/D2 照跑")
else:
    p = subprocess.run([sys.executable, str(POC / "client.py"), "no-such-sub"],
                       env=env_d, cwd=str(REPO), capture_output=True, text=True,
                       timeout=60)
    receipt = parse_out_json(p.stdout or "")
    check("D1a 写失败不吞回执主契约（结构化 ok/error 照常）",
          receipt.get("ok") is False and str(receipt.get("error") or "").strip(),
          "stdout前120=%r" % (p.stdout or "")[:120])
    check("D1b 回执点名 audit_write_failed（不静默吞，工单验收⑤）",
          "audit_write_failed" in receipt,
          "receipt键=%s" % sorted(receipt)[:8])
    check("D1c stderr 留痕非空", bool((p.stderr or "").strip()),
          "stderr=%r" % (p.stderr or "")[:120])

# D2 ticket.py 直 spawn（stdlib 拒收子用例，恒跑）：marker 跨第二公共入口传播
p = subprocess.run([sys.executable, str(TICKET_PY),
                    json.dumps({"op": "create", "title": "x"})],
                   env=env_d, cwd=str(REPO), capture_output=True, text=True,
                   timeout=60)
receipt2 = parse_out_json(p.stdout or "")
check("D2a ticket.py 直 spawn：拒收形状照常（非零退出+结构化错误）",
      p.returncode != 0 and receipt2.get("ok") is False
      and str(receipt2.get("error") or "").strip(),
      "rc=%r stdout前120=%r" % (p.returncode, (p.stdout or "")[:120]))
check("D2b 直 spawn 回执同样点名 audit_write_failed（审计先于打印，第二入口不缺口）",
      "audit_write_failed" in receipt2, "receipt键=%s" % sorted(receipt2)[:8])
check("D2c 写失败 stderr 留痕非空", bool((p.stderr or "").strip()),
      "stderr=%r" % (p.stderr or "")[:120])

# ============ Z 段：红线守卫 ============
print("---- Z 段：红线守卫 ----")
check("Z1 真仓 server/admin.log 零接触（size/mtime 起止一致）",
      log_state() == STATE0, "起=%s 止=%s" % (STATE0, log_state()))
check("Z2 审计面全部落在 tmp（SANDBAR_ADMIN_LOG 隔离语义）",
      os.environ.get("SANDBAR_ADMIN_LOG", "").startswith(str(TMP)),
      "当前=%s" % os.environ.get("SANDBAR_ADMIN_LOG", ""))
check("Z3 注册表面全部落在 tmp（SANDBAR_PROJECTS_DIR 桩隔离，不触真注册表）",
      os.environ.get("SANDBAR_PROJECTS_DIR", "").startswith(str(TMP)),
      "当前=%s" % os.environ.get("SANDBAR_PROJECTS_DIR", ""))

sys.exit(summary())
