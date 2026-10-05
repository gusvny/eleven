#!/usr/bin/env python3
"""t261004-28 场景：搬运票交付契约守卫（carrier-port guard）。

用户场景（工单正文 + 261004 宿主 send-back 第 4 版）：t261004-18 / t261004-19 的
引擎侧单测因写集冻结无法合法落盘，本票是合法载体——把**三份**文件恢复为真测试
并登记锚点：t261004-19 的闸判定测试、t261004-18 的写入口测试、以及 t261004-19
仲裁期被挪档的「源序锁」。用户验收口径是搬运契约本身，不是新的引擎覆盖（本票
明确「adds no new coverage」）；本场景把「搬运真发生了、且代码面没被顺手改写」
锁成可判定红线。

契约（灰盒，锚定工单承诺，不锚引擎内部）：
  C1 在位：三份测试文件以票面点名原名存在于 server/engine/tests/
     （t261004-18 曾五次被阶段路径闸挪档——在位性就是本票的头号故障面）。
  C2 代码面同一（宿主 L15 裁定后的重基判据；不许降级成「文件在」或自declare）：
     每份文件与其作者源在「剥离注释与 docstring、字符串字面量去非 ASCII 归一」
     后 token 流逐项相等，且测试函数名集合与个数不变。允许的差异面=译文注释/
     docstring 与被归一的非 ASCII 字面量（断言里的引擎拒收文案已随 t261004-36 译英、
     不再带 copy-lang-allow: data 标记（拆写避免本场景自体携带该标记字面）（标记退役是 t261004-36 的票面要求）。源不可达=ENV_FAIL
     exit 2 点名缺哪只源，不判 FAIL。
     源基准：t19 闸 ← blob 8cee0cd（票面 12772 B 源，lane 分支退役后对象库即
     真源）；t18 写入口 ← integration/t261004-25/evidence/...gen5 证据副本；
     源序锁 ← 270af67 版（其唯一存活作者文本，同时落了 main 证据副本）。
  C3 锚点登记：integration/test_anchors.json 里三份文件各有条目且 label 在册
     （L16 静态闸的覆盖面；缺条目=静态闸红，搬运不完整）。
  C4 证据副本（源序锁专项）：integration/t261004-28/evidence/ 下的作者原文
     副本与 270af67 版逐字节相等（耐久保存面；quarantine/lane 已不可达，
     这份副本是作者原文在 main 上的唯一形状）。
  C5 可运行：venv 回落链下 pytest 真跑三份文件（import 解析**不够**——收集期
     缺席的引擎入口属性不炸，只有用例真跑到才红）。t261004-18/-19 引擎入口在
     main 的 squash 收口已带进树；若仍红=点名缺失入口（BLOCK 面，不许改测试
     迁就旧树）。源序锁锚定 client.py 源序，main 同步后应绿。
  C6 静态闸整体绿：python3 integration/lint_tests.py exit 0（含 L17 对 t19
     作者字面量的豁免消费；豁免丢失/过期=红点名）。

纯离线零 docker；只读被测树 + 一次 lint 子进程 + 一次 pytest 子进程。
"""
import ast
import io
import pathlib
import subprocess
import sys
import tokenize

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from lib_result import ScenarioCheck  # noqa: E402

REPO = pathlib.Path(__file__).resolve().parents[2]
NAME = "t261004-28-carrier-verbatim-port-guard"

FILES = {
    "t261004-19-gate": pathlib.Path("server/engine/tests/test_t261004_19_open_ticket_gate.py"),
    "t261004-18-write-entry": pathlib.Path("server/engine/tests/test_t261004_18_grants_write_entry.py"),
    "t261004-19-source-order-lock": pathlib.Path("server/engine/tests/test_t261004_19_source_order_lock.py"),
}
# Author-text yardsticks (immutable object-store refs; the t261004-19 lane branch
# and its worktree are retired, these blobs are what the ticket's named sources
# resolve to).
SRC_BLOBS = {
    "t261004-19-gate": ("blob", "8cee0cd111336551a7000b68c6177f7d680bea33"),
    "t261004-19-source-order-lock": ("path", "270af67:server/engine/tests/test_t261004_19_source_order_lock.py"),
}
# Named adaptation table (ticket rule: any adaptation forced by the current engine
# API must be named). The t261004-19 squash that landed on main ANGLICIZED the
# open-ticket refusal messages, so the gate test's asserted substrings were
# re-anchored from the author's Chinese literals to the landed English texts
# (each substitution is applied to the author text before the C2 comparison).
# Everything else in the file stays pinned by C2.
ADAPTED_LITERALS = {
    "t261004-19-gate": [
        ('"执行器" in (eg.authority_surface_violation([entry]) or "")',
         '"hits the protected surface" in (eg.authority_surface_violation([entry]) or "")'),
        ('"必须点名" in v["why"]', '"must name an epic" in v["why"]'),
        ('"不在" in v["why"]', '"not on project" in v["why"]'),
        ('"没有立项档案" in v["why"]', '"no epic file" in v["why"]'),
        ('"受保护真源" in v["why"]', '"protected source of truth" in v["why"]'),
        ('"上限" in v["why"] and "达上限 2" in v["why"]',
         '"per-epic cap" in v["why"] and "already has 2" in v["why"]'),
        ('"上限 3" in v["why"] and "缺省即 3" in v["why"]',
         '"at the cap of 3" in v["why"] and "default 3" in v["why"]'),
        ('"没有立项档案" in v2["why"]', '"no epic file" in v2["why"]'),
        # t261004-36 copy translation: the meta-permission-lock refusal reason and
        # the fixture charter header were anglicized in the landed file too.
        ('"反锁" in (r.get("reason") or "")', '"meta-permission lock" in (r.get("reason") or "")'),
        ('write_text("# 立项单\\n"', 'write_text("# epic charter\\n"'),
    ],
    "t261004-18-write-entry": [
        ('"反锁" in res["reason"]', '"meta-permission lock" in res["reason"]'),
    ],
}
SRC_18 = pathlib.Path("integration/t261004-25/evidence/t261004-18_grants_write_entry.py.txt")
EVIDENCE_LOCK = pathlib.Path("integration/t261004-28/evidence/t261004-19_source_order_lock.py.txt")
MANIFEST = pathlib.Path("integration/test_anchors.json")
VOCAB = {"behaviour", "contract", "production-snapshot", "source-text"}

_ck = ScenarioCheck(detail_cap=800, flush=True)
ok, finish, env_fail = _ck.ok, _ck.finish, _ck.env_fail


def run(cmd):
    return subprocess.run(cmd, cwd=str(REPO), capture_output=True, text=True, timeout=600)


def venv_py():
    for cand in ("server/engine/.venv/bin/python",
                 "server/dsh/temporal-poc/.venv/bin/python",  # engine-venv-compat: lawful fallback leg (t260907-10 marker; removal ticket drops this line)
                 "python3"):
        if (REPO / cand).exists() or cand == "python3":
            return cand
    return "python3"


def _normalized_tokens(src):
    """Re-based C2 comparator: drop comments, NL/INDENT/DEDENT and docstrings;
    strip non-ASCII from every remaining token (translated literals normalize)."""
    skip = set()
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            b = node.body and node.body[0]
            if isinstance(b, ast.Expr) and isinstance(b.value, ast.Constant) and isinstance(b.value.value, str):
                skip.add((b.lineno, b.end_lineno))
    out = []
    for t in tokenize.generate_tokens(io.StringIO(src).readline):
        if t.type in (tokenize.COMMENT, tokenize.NL, tokenize.NEWLINE, tokenize.INDENT, tokenize.DEDENT):
            continue
        if t.type == tokenize.STRING and any(a <= t.start[0] <= b for a, b in skip):
            continue
        out.append((t.type, "".join(ch for ch in t.string if ord(ch) < 128)))
    return out


def _test_functions(src):
    return sorted(n.name for n in ast.walk(ast.parse(src))
                  if isinstance(n, ast.FunctionDef) and n.name.startswith("test"))


def author_text(key):
    """Author bytes for one carrier file; None (with env_fail already fired) if the
    yardstick is unreachable."""
    if key == "t261004-18-write-entry":
        if not (REPO / SRC_18).is_file():
            env_fail(NAME, "source unreachable: %s missing (gen5 evidence copy)" % SRC_18)
            return None
        return (REPO / SRC_18).read_text(encoding="utf-8")
    kind, ref = SRC_BLOBS[key]
    r = run(["git", "cat-file", "blob", ref] if kind == "blob"
            else ["git", "show", ref])
    if r.returncode != 0 or not r.stdout:
        env_fail(NAME, "author source unreachable: %s -> %s" % (ref, (r.stderr or "").strip()[:300]))
        return None
    return r.stdout


def main():
    # ---- C1 presence (the ticket's #1 fault face: five prior evictions) ----
    missing = [str(p) for p in FILES.values() if not (REPO / p).is_file()]
    ok(not missing, "C1 all three carrier test files present under server/engine/tests/",
       detail="missing: %s" % missing)

    # ---- C2 code-identity against the author sources (re-based predicate) ----
    for key, rel in FILES.items():
        path = REPO / rel
        if not path.is_file():
            continue  # C1 already named it; no duplicate FAIL line
        src = author_text(key)
        if src is None:
            continue
        for was, now in ADAPTED_LITERALS.get(key, []):
            if was not in src:
                ok(False, "C2 %s adaptation table stale: author literal no longer present" % key,
                   detail=was[:200])
                continue
            src = src.replace(was, now)
        mine = path.read_text(encoding="utf-8")
        same_code = _normalized_tokens(src) == _normalized_tokens(mine)
        same_tests = _test_functions(src) == _test_functions(mine)
        ok(same_code and same_tests,
           "C2 %s code-identical to author source (comments/docstrings/non-ASCII literals aside, test names+count kept)" % key,
           detail="%s vs author source: code-identical=%s test-names=%s (any other adaptation must be named in the handover)"
                  % (rel, same_code, same_tests) if not (same_code and same_tests) else "")

    # ---- C3 anchor manifest entries ----
    mpath = REPO / MANIFEST
    if not mpath.is_file():
        ok(False, "C3 anchor manifest present", detail=str(MANIFEST))
    else:
        import json
        entries = json.loads(mpath.read_text(encoding="utf-8")).get("engine_tests", {})
        for key, rel in FILES.items():
            k = str(rel)  # manifest keys are repo-relative strings, not Paths
            e = entries.get(k)
            ok(isinstance(e, dict) and e.get("anchor") in VOCAB,
               "C3 %s has an in-vocabulary anchor entry" % key,
               detail="entry for %r=%r (vocab=%s)" % (k, e, sorted(VOCAB))
               if not (isinstance(e, dict) and e.get("anchor") in VOCAB) else "")

    # ---- C4 durable evidence copy of the source-order lock on main ----
    if (REPO / EVIDENCE_LOCK).is_file():
        kind, ref = SRC_BLOBS["t261004-19-source-order-lock"]
        r = run(["git", "show", ref])
        same = r.returncode == 0 and (REPO / EVIDENCE_LOCK).read_bytes() == r.stdout.encode("utf-8")
        ok(same, "C4 evidence copy byte-identical to the author's source-order-lock text",
           detail="%s differs from %s" % (EVIDENCE_LOCK, ref) if not same else "")
    else:
        ok(False, "C4 evidence copy present", detail=str(EVIDENCE_LOCK))

    # ---- C5 runnable: the carried engine entry points resolve at call time ----
    # (collect-only would pass with the entry points absent — imports only touch
    # the module object; the missing attribute fires when a test body runs.)
    present = [str(REPO / p) for p in FILES.values() if (REPO / p).is_file()]
    if present:
        py = venv_py()
        r = run([py, "-m", "pytest"] + present + ["-q", "--no-header", "-p", "no:cacheprovider"])
        ok(r.returncode == 0, "C5 pytest runs all three carrier files green (entry points on tree)",
           detail=(r.stdout + r.stderr)[-700:] if r.returncode != 0 else "")
    else:
        ok(False, "C5 pytest runs all three carrier files green", detail="no carrier file present")

    # ---- C6 static gate green end to end ----
    r = run(["python3", "integration/lint_tests.py"])
    ok(r.returncode == 0, "C6 integration/lint_tests.py exits 0 (L16/L17 faces settled)",
       detail=(r.stdout + r.stderr)[-700:] if r.returncode != 0 else "")

    finish(NAME)


if __name__ == "__main__":
    main()
