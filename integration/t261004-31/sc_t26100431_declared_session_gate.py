#!/usr/bin/env python3
"""sc_t26100431_declared_session_gate.py — t261004-31: the executor's granted
writes are enforced AND recorded for the project whose main directory IS the
engine repo tree.

Grey-box L3, offline (no docker, no Temporal server, no browser, zero contact
with 3099/7233). The defect: a host-created executor session gets no shell env
injection, so its only machine-observable identity channel is cwd — and for
this project cwd sits inside the engine repo tree, where caller identity
resolution deliberately refuses to derive an identity (the C1 anti-impersonation
rule). Result: the gate passes every write as EXEMPT, nothing is enforced, and
the panel's Recent actions ledger never gains a row.

User-perceivable contract under test (with cwd inside the repo-tree exclusion
zone, an isolated projects registry, and a declaration naming the session):
  S1 a NAMED declared executor session's gated write is allowed-enforced and
     records exactly one ledger row at <root>/<key>/ledger/executor-actions.jsonl
  S2 a refused attempt through the same seam records one refused row with a
     non-empty reason (a refusal is still recorded)
  S3 an absent session id stays src=none -> exempt, zero rows (the exclusion is
     NOT weakened for indirect calls)
  S4 an unnamed session id stays src=none -> exempt, zero rows
  S5 a malformed executor-grants.json invents no identity (stays src=none)
     and a trusted-session caller is fail-closed REFUSED with the malformed
     declaration named — a broken declaration never opens the gate (the
     module's standing structured-refusal contract) and the refusal is
     still recorded as one row
  S6 cwd inside a normal registered project dir still resolves src=cwd
     (the seam did not broaden the exclusion or break the ordinary channel)
  S7 an ambiguous registry (two projects claiming the same directory) resolves
     none -> exempt, zero rows
  S8 the request-filing surface (executor_requests.resolve_caller) resolves the
     same declared-session identity, so both gated surfaces agree

Legs S1-S2/S8 go red until the declared-session seam lands (TDD signal);
arbitrate/merge must be green. Engine venv missing across the fallback chain =
ENV_FAIL exit 2. Intent split: t261004-11-ledger-record-and-replay owns the
record/replay funnel with an INJECTED identity inside a normal project dir;
t260915-12 owns the cwd channel in a registered project; this entry owns the
repo-tree exclusion zone and the declaration seam that ends it.
"""
import json
import os
import shutil
import sys
import tempfile
import time

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, "integration"))

from lib_env import env_fail, fail_if_all_na  # noqa: E402
import bench  # noqa: E402

ENGINE_DIR = os.path.join(REPO, "server", "engine")
REPO_ROOT = os.path.realpath(REPO)

PY = os.path.join(ENGINE_DIR, ".venv", "bin", "python")
if not os.path.isfile(PY):
    PY = os.path.join(REPO, "server", "dsh", "temporal-poc", ".venv", "bin", "python")  # engine-venv-compat
if not os.path.isfile(PY):
    found = shutil.which("python3")
    if not found:
        env_fail("no python3 available (engine venv fallback chain exhausted)")
    PY = found

KEY = "sandbar-lane-probe"          # the project whose main dir IS the repo tree
OTHER_KEY = "plain-proj"            # a normal project outside the repo tree
SESSION = "sess-t26100431-exec"
STRANGER = "sess-t26100431-stranger"

legs = []
na_legs = []


def leg(name, ok, reason=""):
    legs.append((name, bool(ok), reason))
    print("[%s] %s%s" % ("PASS" if ok else "FAIL", name, (" — " + reason) if reason else ""))


def write_decl(root, key, sessions, raw=None):
    proj = os.path.join(root, key)
    os.makedirs(proj, exist_ok=True)
    p = os.path.join(proj, "executor-grants.json")
    if raw is not None:
        with open(p, "w", encoding="utf-8") as f:
            f.write(raw)
    else:
        with open(p, "w", encoding="utf-8") as f:
            json.dump({"version": 1, "grants": {"sign": True},
                       "executor_sessions": list(sessions),
                       "updated_by": "scenario", "updated_at": int(time.time() * 1000)}, f)


def main():
    root = tempfile.mkdtemp(prefix="t26100431-gate-")
    atexit_done = []

    def cleanup():
        shutil.rmtree(root, ignore_errors=True)

    import atexit
    atexit.register(cleanup)

    # registry: KEY claims the repo root (the exclusion zone); OTHER_KEY a plain dir
    bench.write_registry(root, KEY, REPO_ROOT)
    plain_dir = os.path.join(root, OTHER_KEY, "workdir")
    os.makedirs(plain_dir)
    bench.write_registry(root, OTHER_KEY, plain_dir)
    write_decl(root, KEY, [SESSION])

    env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": os.environ.get("HOME", root),
        "SANDBAR_PROJECTS_DIR": root,
        "DSH_SESSION_ID": SESSION,
    }
    for k in ("SANDBAR_CALLER_PROJECT", "SANDBAR_CALLER_IDENTITY_SRC",
              "SANDBAR_CALLER_SURFACE", "SANDBAR_UNDECLARED_POLICY",
              "SANDBAR_PROJECTS_YAML"):
        env[k] = ""

    script = r'''
import json, os, sys
ENGINE = sys.argv[1]
ROOT = sys.argv[2]
KEY = sys.argv[3]
OTHER_KEY = sys.argv[4]
OTHER_DIR = sys.argv[5]
SESSION = sys.argv[6]
STRANGER = sys.argv[7]
REPO_ROOT = os.path.realpath(sys.argv[8])
sys.path.insert(0, ENGINE)
os.chdir(ENGINE)  # inside the repo-tree exclusion zone
os.environ["SANDBAR_PROJECTS_DIR"] = ROOT
for k in ("SANDBAR_CALLER_PROJECT", "SANDBAR_CALLER_IDENTITY_SRC", "SANDBAR_CALLER_SURFACE"):
    os.environ.pop(k, None)

import client, executor_grants, executor_requests

out = {}
def rows():
    p = os.path.join(ROOT, KEY, "ledger", "executor-actions.jsonl")
    if not os.path.exists(p):
        return p, []
    with open(p, encoding="utf-8") as f:
        return p, [json.loads(l) for l in f.read().splitlines() if l.strip()]

# S1 named declared session, cwd in repo tree
os.environ["DSH_SESSION_ID"] = SESSION
i1 = client._caller_identity({})
out["s1_src"] = i1.get("src")
out["s1_value"] = i1.get("value")
out["s1_class"] = i1.get("identity_class")
g1 = client._executor_grant_gate(dict(i1), "sign", KEY, ticket="t31a")
out["s1_err"] = g1.get("err")
out["s1_keys"] = g1.get("keys")
p, rs = rows()
out["s1_rows"] = rs
out["s1_path"] = p

# S2 refusal through the same seam
g2 = client._executor_grant_gate(dict(i1), "cancel", KEY, ticket="t31a")
out["s2_err"] = g2.get("err")
_, rs2 = rows()
out["s2_refused"] = [r for r in (rs2 or []) if r.get("decision") == "refused"]

# S3 absent session id
os.environ.pop("DSH_SESSION_ID", None)
i3 = client._caller_identity({})
out["s3_src"] = i3.get("src")
g3 = client._executor_grant_gate(dict(i3), "sign", KEY, ticket="t31b")
out["s3_err"] = g3.get("err")
out["s3_keys_empty"] = g3.get("keys") == {}
_, rs3 = rows()
out["s3_total"] = len(rs3 or [])

# S4 unnamed session id
os.environ["DSH_SESSION_ID"] = STRANGER
i4 = client._caller_identity({})
out["s4_src"] = i4.get("src")
g4 = client._executor_grant_gate(dict(i4), "sign", KEY, ticket="t31b")
out["s4_err"] = g4.get("err")
out["s4_keys_empty"] = g4.get("keys") == {}
_, rs4 = rows()
out["s4_total"] = len(rs4 or [])

# S5 malformed declaration invents no identity
write_malformed = sys.argv[9] == "1"
if write_malformed:
    with open(os.path.join(ROOT, KEY, "executor-grants.json"), "w", encoding="utf-8") as f:
        f.write("{not json at all")
os.environ["DSH_SESSION_ID"] = SESSION
i5 = client._caller_identity({})
out["s5_src"] = i5.get("src")
g5 = client._executor_grant_gate(dict(i5), "sign", KEY, ticket="t31c")
out["s5_err"] = g5.get("err")
out["s5_err_kind"] = (g5.get("err") or {}).get("kind") if isinstance(g5.get("err"), dict) else None
out["s5_keys_empty"] = g5.get("keys") == {}
_, rs5 = rows()
out["s5_total"] = len(rs5 or [])
out["s5_rows"] = rs5

# S6 ordinary cwd channel outside the repo tree is unchanged
os.chdir(OTHER_DIR)
i6 = client._caller_identity({})
out["s6_src"] = i6.get("src")
out["s6_value"] = i6.get("value")
os.chdir(ENGINE)

# S7 ambiguity: two registry projects claim the repo root -> none
os.environ["SANDBAR_PROJECTS_DIR"] = sys.argv[10]
i7 = client._caller_identity({})
out["s7_src"] = i7.get("src")
out["s7_value"] = i7.get("value")
os.environ["SANDBAR_PROJECTS_DIR"] = ROOT

# S8 request-filing surface sees the same identity (env/cwd/projects are the
# documented injection seams of resolve_caller). Restore a valid declaration
# first — S5 deliberately leaves the malformed one behind, and the seam must
# stay shut on a broken declaration (that is S5's own assertion).
if write_malformed:
    with open(os.path.join(ROOT, KEY, "executor-grants.json"), "w", encoding="utf-8") as f:
        json.dump({"version": 1, "grants": {"sign": True},
                   "executor_sessions": [SESSION],
                   "updated_by": "scenario", "updated_at": 0}, f)
try:
    projects8, _q = __import__("shared").load_projects_registry()
except Exception:
    projects8 = []
rc = executor_requests.resolve_caller(
    "", env={"DSH_SESSION_ID": SESSION}, cwd=ENGINE,
    projects=projects8, exclude_trees=(os.path.realpath(ENGINE),))
out["s8_ok"] = bool(rc.get("ok"))
out["s8_project"] = rc.get("project")
out["s8_channel"] = rc.get("channel")
out["s8_session"] = rc.get("session")
out["s8_reason"] = rc.get("reason")
out["s8_nproj"] = len(projects8 or [])

print("RESULT_JSON=" + json.dumps(out))
'''
    # ambiguity fixture: a second registry root where two keys claim the repo root
    amb_root = os.path.join(root, "ambig")
    bench.write_registry(amb_root, "amb-one", REPO_ROOT)
    bench.write_registry(amb_root, "amb-two", REPO_ROOT)

    import subprocess
    r = subprocess.run([PY, "-c", script, ENGINE_DIR, root, KEY, OTHER_KEY, plain_dir,
                        SESSION, STRANGER, REPO_ROOT, "1", amb_root],
                       capture_output=True, text=True, timeout=180,
                       env={k: v for k, v in env.items() if v != ""})
    if r.returncode != 0:
        leg("engine-runner", False, "engine interpreter exited %d: %s"
            % (r.returncode, (r.stderr or r.stdout).strip()[-400:]))
        fail_if_all_na(len(legs), len(na_legs), "t261004-31-gate")
        print("SUMMARY pass=%d fail=%d env_fail=0 na=0"
              % (sum(1 for l in legs if l[1]), sum(1 for l in legs if not l[1])))
        sys.exit(1)
    line = [l for l in r.stdout.splitlines() if l.startswith("RESULT_JSON=")]
    out = json.loads(line[0][len("RESULT_JSON="):]) if line else {}

    rows1 = out.get("s1_rows") or []
    ok = (out.get("s1_src") == "declared-session"
          and out.get("s1_value") == KEY
          and out.get("s1_class") == "declared"
          and out.get("s1_err") is None and out.get("s1_keys")
          and len(rows1) == 1)
    leg("s1-named-declared-session-enforced-with-one-row", ok,
        "" if ok else "src=%s value=%s err=%s rows=%s"
        % (out.get("s1_src"), out.get("s1_value"), out.get("s1_err"), rows1))
    if rows1:
        row = rows1[0]
        ok2 = (row.get("decision") == "allowed" and row.get("op") == "sign"
               and row.get("ticket") == "t31a" and row.get("session") == SESSION
               and str(row.get("channel") or "") == "declared-session"
               and str(row.get("grant") or "") == "sign")
        leg("s1b-row-attributes-declared-session-channel", ok2,
            "" if ok2 else "row=%s" % row)
    else:
        leg("s1b-row-attributes-declared-session-channel", False,
            "no ledger row (seam not landed?) path=%s" % out.get("s1_path"))

    ref2 = out.get("s2_refused") or []
    ok = (out.get("s2_err") and len(ref2) == 1
          and str(ref2[0].get("reason") or "").strip())
    leg("s2-refusal-through-seam-still-recorded", ok,
        "" if ok else "err=%s refused=%s" % (out.get("s2_err"), ref2))

    ok = (out.get("s3_src") == "none" and out.get("s3_err") is None
          and out.get("s3_keys_empty") and out.get("s3_total") == 2)
    leg("s3-absent-session-stays-none-exempt-zero-rows", ok,
        "" if ok else "src=%s err=%s keys_empty=%s total=%s"
        % (out.get("s3_src"), out.get("s3_err"), out.get("s3_keys_empty"), out.get("s3_total")))

    ok = (out.get("s4_src") == "none" and out.get("s4_err") is None
          and out.get("s4_keys_empty") and out.get("s4_total") == 2)
    leg("s4-unnamed-session-stays-none-exempt-zero-rows", ok,
        "" if ok else "src=%s err=%s keys_empty=%s total=%s"
        % (out.get("s4_src"), out.get("s4_err"), out.get("s4_keys_empty"), out.get("s4_total")))

    ref5 = [r for r in (out.get("s5_rows") or []) if r.get("ticket") == "t31c"]
    ok = (out.get("s5_src") == "none"
          and out.get("s5_err_kind") == "executor_grant_refused"
          and "malformed" in str(out.get("s5_err") or "").lower()
          and len(ref5) == 1 and ref5[0].get("decision") == "refused"
          and str(ref5[0].get("reason") or "").strip())
    leg("s5-malformed-declaration-invents-no-identity-and-refuses-loud", ok,
        "" if ok else "src=%s err=%s kind=%s rows=%s"
        % (out.get("s5_src"), out.get("s5_err"), out.get("s5_err_kind"), ref5))

    ok = (out.get("s6_src") == "cwd" and out.get("s6_value") == OTHER_KEY)
    leg("s6-ordinary-cwd-channel-outside-tree-unchanged", ok,
        "" if ok else "src=%s value=%s" % (out.get("s6_src"), out.get("s6_value")))

    ok = (out.get("s7_src") == "none")
    leg("s7-ambiguous-registry-resolves-none", ok,
        "" if ok else "src=%s value=%s" % (out.get("s7_src"), out.get("s7_value")))

    ok = (out.get("s8_ok") and out.get("s8_project") == KEY
          and out.get("s8_channel") == "declared-session"
          and out.get("s8_session") == SESSION)
    leg("s8-request-surface-same-identity", ok,
        "" if ok else "ok=%s project=%s channel=%s session=%s reason=%s nproj=%s"
        % (out.get("s8_ok"), out.get("s8_project"), out.get("s8_channel"),
           out.get("s8_session"), out.get("s8_reason"), out.get("s8_nproj")))

    fail_if_all_na(len(legs), len(na_legs), "t261004-31-gate")
    passed = sum(1 for l in legs if l[1])
    failed = len(legs) - passed
    print("SUMMARY pass=%d fail=%d env_fail=0 na=0" % (passed, failed))
    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()
