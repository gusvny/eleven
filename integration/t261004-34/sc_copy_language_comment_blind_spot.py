#!/usr/bin/env python3
"""t261004-34 scenario A: the copy-language gate must see its own comment lines.

Executor request -0002: `lint_diff` in integration/lint_copy_language.py exempted
a line that is nothing but a comment, so a planted whole-line Chinese comment
never fired while inline comments, docstrings and string literals did. Host
order 261004 puts comments inside the gate; the module docstring already claims
comments fire. This scenario proves the wired per-diff face through the public
CLI contract (`python3 integration/lint_copy_language.py --base <ref>`,
exit 0 = pass / 1 = violations / 2 = environment failure).

Grey-box L3, offline, seconds. No shared-tree planting: the gate script is
copied into a throwaway git repo (it is stdlib-only and resolves its repo root
from its own location, per the documented usage "cwd = repo root"), so no
concurrently running scenario can observe a transient CJK probe.

Cases:
- A1 a whole-line Chinese comment added to an in-scope file FIRES, exit 1,
     the added path named in the output (the incident face; red before the fix);
- A2 an inline comment (`x = 1  # Chinese`) still fires (tighten-only guard);
- A3 a whole-line Chinese comment carrying `copy-lang-allow:fixture` on the
     same line stays exempt, exit 0;
- A4 a whole-line Chinese comment with the marker on the line directly above
     stays exempt, exit 0, and the exempt line is listed in the output.

Three states: PASS exit 0 / FAIL exit 1 / ENV_FAIL exit 2 (git or gate script
unavailable). Run: python3 integration/t261004-34/sc_copy_language_comment_blind_spot.py
(cwd = repo root).
"""
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
GATE_SRC = os.path.join(REPO, "integration", "lint_copy_language.py")

FAILURES = []


def check(name, cond, detail=""):
    tag = "PASS" if cond else "FAIL"
    print("%s %s%s" % (tag, name, (" | " + detail) if detail else ""))
    if not cond:
        FAILURES.append(name)


def git(tmp, *args):
    r = subprocess.run(["git", *args], cwd=tmp, capture_output=True, text=True)
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def write_base(tmp):
    rel = os.path.join("server", "engine", "probe_surface.py")
    os.makedirs(os.path.dirname(os.path.join(tmp, rel)), exist_ok=True)
    with open(os.path.join(tmp, rel), "w", encoding="utf-8") as f:
        f.write("x = 1\n")
    return rel


def run_gate(tmp):
    gate = os.path.join(tmp, "integration", "lint_copy_language.py")
    r = subprocess.run([sys.executable, gate, "--base", "HEAD"],
                       cwd=tmp, capture_output=True, text=True, timeout=60)
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def append(tmp, rel, text):
    with open(os.path.join(tmp, rel), "a", encoding="utf-8") as f:
        f.write(text)


def main():
    if not os.path.isfile(GATE_SRC):
        print("ENV_FAIL: gate script missing: integration/lint_copy_language.py")
        return 2
    rc, why = git(".", "--version")
    if rc != 0:
        print("ENV_FAIL: git unavailable: %s" % why.strip()[:200])
        return 2
    tmp = tempfile.mkdtemp(prefix="t26100434-copylang-")
    try:
        rc, _ = git(tmp, "init", "-q")
        if rc != 0:
            print("ENV_FAIL: git init failed in temp repo")
            return 2
        git(tmp, "config", "user.email", "gate@example.invalid")
        git(tmp, "config", "user.name", "gate probe")
        rel = write_base(tmp)
        git(tmp, "add", "-A")
        git(tmp, "commit", "-q", "-m", "base")
        os.makedirs(os.path.join(tmp, "integration"), exist_ok=True)
        shutil.copy2(GATE_SRC, os.path.join(tmp, "integration",
                                            "lint_copy_language.py"))

        print("== A1 whole-line Chinese comment fires (incident face)")
        append(tmp, rel, "\n# 中文注释：whole-line comment must not dodge the gate\n")
        rc1, out1 = run_gate(tmp)
        check("A1 exit 1 on whole-line Chinese comment", rc1 == 1,
              "exit=%d" % rc1)
        check("A1 output names the added path", rel in out1,
              "out=%r" % out1.strip()[-200:])
        # reset to base for the next faces
        git(tmp, "checkout", "--", rel)

        print("== A2 inline comment still fires (tighten-only)")
        append(tmp, rel, "x = 2  # 中文 inline\n")
        rc2, out2 = run_gate(tmp)
        check("A2 exit 1 on inline Chinese comment", rc2 == 1, "exit=%d" % rc2)
        git(tmp, "checkout", "--", rel)

        print("== A3 marker on the same line stays exempt")
        append(tmp, rel, "\n# 中文注释 copy-lang-allow:fixture\n")
        rc3, out3 = run_gate(tmp)
        check("A3 exit 0 with same-line marker", rc3 == 0, "exit=%d out=%r"
              % (rc3, out3.strip()[-160:]))
        git(tmp, "checkout", "--", rel)

        print("== A4 marker on the line above stays exempt")
        append(tmp, rel, "\n# copy-lang-allow:fixture\n# 中文注释 under a marker\n")
        rc4, out4 = run_gate(tmp)
        check("A4 exit 0 with marker-above", rc4 == 0, "exit=%d out=%r"
              % (rc4, out4.strip()[-160:]))
        check("A4 exempt line listed in output",
              "copy-lang-allow" in out4 and rel in out4, "")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    if FAILURES:
        print("SUMMARY: fail=%d" % len(FAILURES))
        return 1
    print("SUMMARY: fail=0 env_fail=0")
    return 0


if __name__ == "__main__":
    sys.exit(main())
