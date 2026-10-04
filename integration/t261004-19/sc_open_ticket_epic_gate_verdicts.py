#!/usr/bin/env python3
"""sc_open_ticket_epic_gate_verdicts.py — t261004-19: open-ticket authority is
scoped by epic, and an executor-opened ticket may not widen its own grants.

Grey-box L3, offline (no docker, no Temporal, no browser, zero contact with
3099/7233). Drives the engine's public gate funnel `client._executor_grant_gate`
(same seam as t261003-03 / t261004-11) against an isolated projects root
(SANDBAR_PROJECTS_DIR) holding a real executor-grants declaration plus real
epic fixture files placed at the engine's own epic-directory resolver.

User-perceivable faces under judgment (ticket requirements 1/2/4/5/6/8):
  A1 an executor ticket-start without an epic is refused, reason names the
     missing epic;
  A2 an epic that exists but is not on open_ticket_epics is refused, reason
     names that epic;
  A3 an epic on the list, with an epic file, is allowed, and the verdict face
     carries the epic plus the authorization provenance (open_ticket_epics);
  A4 a stale list entry (code on the list, no epic file) is refused and the
     reason names the missing epic file — a stale entry is never a silent
     bypass;
  A5 a write set carrying an authority surface is refused at create time, the
     reason names the offending entry, and path normalization does not sneak a
     protected path past the gate (each protected surface + one disguised
     relative path);
  A6 the per-epic cap refuses with a named reason that states the count and
     where the cap came from (default 3; declared value honored);
  A7 exempt channels (lane-agent surface) are unaffected: no epic, an
     unauthorized epic, and an authority-surface write set all still pass;
  A8 a malformed declaration is rejected with a named reason, and a malformed
     declaration on disk degrades fail-closed (open-ticket refused, never a
     crash, never an open gate);
  A9 audit: the allowed attempt lands an allowed row whose grant_source names
     the epic authorization; the refused attempts land refused rows with a
     non-empty reason;
  A10 the machine judgment reads the declaration, not the epic prose: changing
     the epic file's prose (status line) never flips a verdict (req. 8).

Intent split: pure-core truth tables, validation matrices and client wiring
order are developer L1 (plan Step 5); the panel render face belongs to
sc_open_ticket_panel_section.mjs (same ticket); the ledger row schema and
replay/idem semantics already owned by t261004-11-ledger-record-and-replay are
not re-judged here.

Three-state discipline (t260904-12): engine venv fallback chain exhausted =
ENV_FAIL exit 2; gate face not implemented at the seam (the funnel does not
accept the epic/write_set/open_count context yet) = FAIL exit 1 with the face
named (TDD-phase red is expected; arbitrate/merge must be green).
"""
import atexit
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, "integration"))

from lib_env import env_fail  # noqa: E402

ENGINE_DIR = os.path.join(REPO, "server", "engine")

PY = os.path.join(ENGINE_DIR, ".venv", "bin", "python")
if not os.path.isfile(PY):
    PY = os.path.join(REPO, "server", "dsh", "temporal-poc", ".venv", "bin", "python")  # engine-venv-compat
if not os.path.isfile(PY):
    found = shutil.which("python3")
    if not found:
        env_fail("no python3 available (engine venv fallback chain exhausted)")
    PY = found

KEY = "proj-t26100419"
SESSION = "sess-t26100419-exec-1"
AUTHORIZED_EPIC = "engine-hardening"
UNAUTHORIZED_EPIC = "localization"
STALE_EPIC = "doc-lifecycle"

# The six authority surfaces from ticket requirement 4 (the disguised relative
# form of the first engine path is appended by the driver).
AUTHORITY_SURFACES = [
    "executor-grants.json",
    "server/engine/executor_grants.py",
    "server/engine/path_gates.py",
    "server/roles/",
    "server/projects.yaml",
    "docs/design/",
    "./server/engine/../engine/executor_grants.py",
]

legs = []


def leg(name, ok, reason=""):
    legs.append(bool(ok))
    print("[%s] %s%s" % ("PASS" if ok else "FAIL", name, (" — " + reason) if reason else ""))


def main():
    root = tempfile.mkdtemp(prefix="t26100419-engine-")
    atexit.register(lambda: shutil.rmtree(root, ignore_errors=True))

    proj = os.path.join(root, KEY)
    os.makedirs(os.path.join(proj, "ledger"))
    decl_path = os.path.join(proj, "executor-grants.json")

    def write_decl(doc):
        with open(decl_path, "w", encoding="utf-8") as f:
            json.dump(doc, f)

    write_decl({"version": 1, "grants": {"open-ticket": True, "sign": True},
                "open_ticket_epics": [AUTHORIZED_EPIC, STALE_EPIC],
                "executor_sessions": [SESSION],
                "updated_by": "scenario", "updated_at": int(time.time() * 1000)})

    env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": os.environ.get("HOME", root),
        # every ticket-start probe below targets the scenario's own project key
        # (gate verdict probes through the public funnel, not bare creations)
        "SANDBAR_CALLER_PROJECT": KEY,
    }

    # The whole battery runs inside the engine interpreter, one process, with
    # the tree isolated via the env seam. The epic fixture files are placed at
    # the engine's own resolver anchor so the scenario does not guess the path.
    script = r'''
import json, os, sys
ENGINE, ROOT, KEY, SESSION = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
sys.path.insert(0, ENGINE)
os.chdir(ENGINE)
os.environ["SANDBAR_PROJECTS_DIR"] = ROOT
os.environ["SANDBAR_CALLER_IDENTITY_SRC"] = "arg"
os.environ["DSH_SESSION_ID"] = SESSION
os.environ.pop("SANDBAR_CALLER_SURFACE", None)

import client, executor_grants

out = {"gate_legs": {}, "decl_legs": {}, "rows": None, "face_absent": []}

def gate(op, **kw):
    """Call the public funnel with the open-ticket context. If the funnel does
    not accept the context yet, record the absent face and degrade to a plain
    call so the battery keeps producing data for the other legs."""
    try:
        return client._executor_grant_gate({"src": "arg", "value": KEY}, op, KEY,
                                           ticket=kw.pop("ticket", "t1"), **kw)
    except TypeError as e:
        out["face_absent"].append(str(e))
        return {"err": "FACE_ABSENT", "keys": {}}

def rows():
    p = os.path.join(ROOT, KEY, "ledger", "executor-actions.jsonl")
    if not os.path.exists(p):
        return []
    with open(p, encoding="utf-8") as f:
        return [json.loads(l) for l in f.read().splitlines() if l.strip()]

# place epic fixtures at the engine's own anchor (shallow binding: the
# scenario asks the engine where epics live, it does not guess)
try:
    epics_dir = str(client.resolve_epics_dir(KEY))
except Exception:
    try:
        import shared
        epics_dir = str(shared.resolve_epics_dir(KEY))
    except Exception:
        # last resort: the conventional project-local anchor
        epics_dir = os.path.join(ROOT, KEY, "notes", "epics")
out["epics_dir"] = epics_dir
if epics_dir:
    os.makedirs(epics_dir, exist_ok=True)
    for code in ("engine-hardening", "localization"):
        with open(os.path.join(epics_dir, code + ".md"), "w", encoding="utf-8") as f:
            f.write("# epic %s\n\n| 状态 | active |\n" % code)
# doc-lifecycle deliberately has NO file (stale list entry)

G = out["gate_legs"]

# A1 no epic
g = gate("ticket-start", epic="", write_set=[])
G["a1"] = [bool(g.get("err")), str(g.get("err"))]

# A2 epic exists but not authorized
g = gate("ticket-start", epic="localization", write_set=[])
G["a2"] = [bool(g.get("err")), str(g.get("err"))]

# A3 authorized epic with file -> allowed, verdict carries epic + provenance
g = gate("ticket-start", epic="engine-hardening", write_set=[])
G["a3_err"] = bool(g.get("err"))
G["a3_err_s"] = str(g.get("err"))
prov = json.dumps(g.get("provenance") or g.get("keys") or {}, default=str)
G["a3_provenance"] = prov
G["a3_epic_in_face"] = "engine-hardening" in json.dumps(g, default=str)
allowed_row_count = len([r for r in rows() if r.get("decision") == "allowed"
                         and r.get("op") == "ticket-start"])
G["a3_allowed_rows"] = allowed_row_count

# A4 stale list entry (no file)
g = gate("ticket-start", epic="doc-lifecycle", write_set=[])
G["a4"] = [bool(g.get("err")), str(g.get("err"))]

# A5 authority surface in the write set (each protected surface, named)
a5 = {}
for surf in ["executor-grants.json", "server/engine/executor_grants.py",
             "server/engine/path_gates.py", "server/roles/",
             "server/projects.yaml", "docs/design/",
             "./server/engine/../engine/executor_grants.py"]:
    # L9-allow: expects-refusal (gate verdict probe, not a bare creation)
    g = gate("ticket-start", epic="engine-hardening", write_set=[surf])
    a5[surf] = [bool(g.get("err")), str(g.get("err"))]
G["a5"] = a5

# A6 cap: default 3 via explicit open_count; declared cap honored
g = gate("ticket-start", epic="engine-hardening", write_set=[], open_count=3)
G["a6_default"] = [bool(g.get("err")), str(g.get("err"))]
g = gate("ticket-start", epic="engine-hardening", write_set=[], open_count=1)
G["a6_under_default"] = [bool(g.get("err")), str(g.get("err"))]
decl = json.load(open(os.path.join(ROOT, KEY, "executor-grants.json"), encoding="utf-8"))
decl["open_ticket_cap"] = 1
json.dump(decl, open(os.path.join(ROOT, KEY, "executor-grants.json"), "w", encoding="utf-8"))
g = gate("ticket-start", epic="engine-hardening", write_set=[], open_count=1)
G["a6_declared"] = [bool(g.get("err")), str(g.get("err"))]

# A7 exempt channel: lane-agent surface passes with no epic, an unauthorized
# epic and an authority-surface write set
os.environ["SANDBAR_CALLER_SURFACE"] = "lane-agent"
os.environ["SANDBAR_CALLER_IDENTITY_SRC"] = "env"
ident_env = {"src": "env", "value": KEY}
try:
    # L9-allow: expects-refusal (gate verdict probe, not a bare creation)
    e1 = client._executor_grant_gate(dict(ident_env), "ticket-start", KEY, ticket="t7", epic="", write_set=[])
    e2 = client._executor_grant_gate(dict(ident_env), "ticket-start", KEY, ticket="t7", epic="localization", write_set=["server/engine/executor_grants.py"])
    G["a7"] = [not e1.get("err"), not e2.get("err"), str(e1.get("err")), str(e2.get("err"))]
except TypeError as e:
    out["face_absent"].append("a7:" + str(e))
    G["a7"] = None
os.environ.pop("SANDBAR_CALLER_SURFACE", None)
os.environ["SANDBAR_CALLER_IDENTITY_SRC"] = "arg"

# A8 malformed declaration: named rejection + fail-closed on disk
D = out["decl_legs"]
cases = [
    ("not_a_list", {"open_ticket_epics": "engine-hardening"}),
    ("int_item", {"open_ticket_epics": [42]}),
    ("empty_item", {"open_ticket_epics": [""]}),
    ("cap_zero", {"open_ticket_cap": 0}),
    ("cap_bool", {"open_ticket_cap": True}),
    ("cap_float", {"open_ticket_cap": 1.5}),
]
for name, patch in cases:
    doc = {"version": 1, "grants": {"open-ticket": True},
           "executor_sessions": [SESSION]}
    doc.update(patch)
    try:
        _, err = executor_grants.validate_declaration(doc)
        D[name] = [err is not None, str(err)]
    except Exception as e:  # a raise is a crash face, not a named rejection
        D[name] = [False, "raised: %r" % (e,)]
# malformed doc on disk -> open-ticket refused, no crash
json.dump({"version": 1, "grants": {"open-ticket": True}, "open_ticket_epics": "nope",
           "executor_sessions": [SESSION]},
          open(os.path.join(ROOT, KEY, "executor-grants.json"), "w", encoding="utf-8"))
try:
    # L9-allow: expects-refusal (gate verdict probe, not a bare creation)
    g = gate("ticket-start", epic="engine-hardening", write_set=[])
    G["a8_failclosed"] = [bool(g.get("err")), str(g.get("err"))]
except Exception as e:
    G["a8_failclosed"] = [False, "raised: %r" % (e,)]
# restore the valid declaration for the A10 prose leg
json.dump({"version": 1, "grants": {"open-ticket": True},
           "open_ticket_epics": ["engine-hardening", "doc-lifecycle"],
           "executor_sessions": [SESSION]},
          open(os.path.join(ROOT, KEY, "executor-grants.json"), "w", encoding="utf-8"))

# A9 audit rows for this op
out["rows"] = rows()

# A10 prose does not rule: rewrite the authorized epic file's prose, verdict unchanged
if epics_dir:
    p = os.path.join(epics_dir, "engine-hardening.md")
    with open(p, "w", encoding="utf-8") as f:
        f.write("# epic engine-hardening\n\n| 状态 | retired-and-renamed-prose |\n")
    # L9-allow: expects-refusal (gate verdict probe, not a bare creation)
    g = gate("ticket-start", epic="engine-hardening", write_set=[])
    G["a10_prose_flip"] = [bool(g.get("err")), str(g.get("err"))]

print("RESULT_JSON=" + json.dumps(out))
'''

    proc = subprocess.run([PY, "-c", script, ENGINE_DIR, root, KEY, SESSION],
                          capture_output=True, text=True, timeout=300, env=env)
    line = next((l for l in proc.stdout.splitlines() if l.startswith("RESULT_JSON=")), None)
    if proc.returncode != 0 or not line:
        env_fail("engine driver did not produce RESULT_JSON (rc=%s, stderr head: %s)"
                 % (proc.returncode, proc.stderr.strip()[:300]))

    out = json.loads(line[len("RESULT_JSON="):])
    G = out.get("gate_legs", {})
    D = out.get("decl_legs", {})
    face_absent = bool(out.get("face_absent"))

    # ---- A1..A4, A6, A8(fail-closed), A10: named verdicts ----
    a1 = G.get("a1") or [False, "missing"]
    leg("A1 no-epic refused with named reason",
        a1[0] and "epic" in a1[1].lower(), "reason=%r" % a1[1][:200])
    a2 = G.get("a2") or [False, "missing"]
    leg("A2 unauthorized epic refused, reason names the epic",
        a2[0] and "localization" in a2[1], "reason=%r" % a2[1][:200])
    leg("A3 authorized epic allowed, face carries epic + open_ticket_epics provenance",
        (not G.get("a3_err")) and G.get("a3_epic_in_face")
        and "open_ticket_epics" in (G.get("a3_provenance") or ""),
        "err=%r prov=%r" % (G.get("a3_err_s"), (G.get("a3_provenance") or "")[:160]))
    a4 = G.get("a4") or [False, "missing"]
    leg("A4 stale list entry (no file) refused, reason names the missing epic",
        a4[0] and "doc-lifecycle" in a4[1], "reason=%r" % a4[1][:200])

    # ---- A5 authority surfaces ----
    a5 = G.get("a5") or {}
    for surf in AUTHORITY_SURFACES:
        r = a5.get(surf) or [False, "missing"]
        leg("A5 authority write-set refused: %s" % surf,
            r[0] and surf.strip("./") .split("/")[0] in r[1] or _names_entry(surf, r[1]),
            "refused=%s reason=%r" % (r[0], r[1][:160]))

    # ---- A6 cap ----
    a6d = G.get("a6_default") or [False, "missing"]
    leg("A6 cap default 3 reached -> named refusal",
        a6d[0] and ("3" in a6d[1] or "cap" in a6d[1].lower()), "reason=%r" % a6d[1][:200])
    a6u = G.get("a6_under_default") or [True, "missing"]
    leg("A6 under the default cap -> not refused by the cap",
        a6u[1] != "FACE_ABSENT" and not a6u[0], "reason=%r" % a6u[1][:200])
    a6c = G.get("a6_declared") or [False, "missing"]
    leg("A6 declared cap (1) honored and named",
        a6c[0] and "1" in a6c[1], "reason=%r" % a6c[1][:200])

    # ---- A7 exempt channel ----
    a7 = G.get("a7")
    if a7 is None:
        leg("A7 exempt channel unaffected", False, "gate face absent for context kwargs")
    else:
        leg("A7 exempt channel: no-epic and authority write-set both pass",
            a7[0] and a7[1], "errs=%r; %r" % (a7[2][:120], a7[3][:120]))

    # ---- A8 malformed declaration ----
    for name, (rejected, reason) in (D.items() or {}.items()):
        leg("A8 malformed declaration rejected with named reason: %s" % name,
            rejected and bool(reason), "reason=%r" % str(reason)[:160])
    if not D:
        leg("A8 malformed declaration rejected with named reason", False, "no validation results returned")
    a8f = G.get("a8_failclosed") or [False, "missing"]
    leg("A8 malformed declaration on disk -> fail-closed refusal, no crash",
        a8f[0] and a8f[1] != "FACE_ABSENT" and not str(a8f[1]).startswith("raised"),
        "reason=%r" % a8f[1][:200])

    # ---- A9 audit rows ----
    rws = out.get("rows") or []
    allowed = [r for r in rws if r.get("decision") == "allowed" and r.get("op") == "ticket-start"]
    refused = [r for r in rws if r.get("decision") == "refused" and r.get("op") == "ticket-start"]
    leg("A9 allowed row recorded with epic authorization in grant_source",
        any("open_ticket_epics" in str(r.get("grant_source", ""))
            and "engine-hardening" in str(r.get("grant_source", "")) for r in allowed),
        "allowed rows=%d" % len(allowed))
    leg("A9 refused rows recorded with non-empty named reason",
        all(str(r.get("reason", "")).strip() for r in refused) and len(refused) >= 2,
        "refused rows=%d" % len(refused))

    # ---- A10 prose does not rule ----
    a10 = G.get("a10_prose_flip")
    if a10 is None:
        leg("A10 verdict reads declaration, not epic prose", False, "prose-flip leg missing from driver output")
    else:
        leg("A10 verdict reads declaration, not epic prose",
            not a10[0], "prose flip changed the verdict: %r" % a10[1][:160])

    if face_absent:
        leg("gate face present at the public funnel (epic/write_set/open_count context)",
            False, "funnel rejected the open-ticket context: %s"
            % "; ".join(out.get("face_absent", []))[:300])

    if not legs:
        env_fail("no legs evaluated (driver produced no gate data)")
    if all(not l for l in legs):
        sys.exit(1)
    sys.exit(0 if all(legs) else 1)


def _names_entry(surf, reason):
    """The refusal must identify the offending entry (exact path, or its
    normalized form / protected family)."""
    if not reason:
        return False
    s = surf.strip("./")
    return s in reason or s.split("/")[0] in reason or "authority" in reason.lower() \
        or "write set" in reason.lower() or "write_set" in reason.lower()


if __name__ == "__main__":
    main()
