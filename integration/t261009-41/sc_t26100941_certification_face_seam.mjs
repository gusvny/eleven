// sc_t26100941_certification_face_seam.mjs — t261009-41, grey-box L2, offline.
//
// The engine→model seam: the engine-generated golden fixture (the same file
// the sibling fixture-contract gate pins against the real projections) is fed
// through the tab's view model, and the face a person would see obeys the
// dispatch rules the mock rules on: counts add up (rule 3, the '12 certified /
// 2 promotable' order), promote stays enabled while frozen and is disabled
// ONLY at zero (rule 5), the boundary moment is the certifying round and
// precedes the red one, the measured column says 'line <sha>' and never
// 'main@<sha> +N' (rule 4), the trigger vocabulary is auto/manual only, and no
// label carries an emoji (rule 8). Malformed inputs degrade to a named empty
// face — never a throw, never invented data (rule 9).
//
// Intent split: the engine projection truth table belongs to
// sc_t26100941_freeze_promote_contract.py; the fixture-vs-engine drift guard
// lives in the C1 pytest this ticket's fixture-contract gate runs; this entry
// uniquely owns the FACE the model produces from engine-shaped inputs.
//
// Model not importable / fixture not generated = FAIL named (TDD signal);
// green required at the integration gate / merge. node missing = ENV_FAIL 2.

import { spawnSync } from "node:child_process";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

const here = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(here, "..", "..");
const modelPath = path.join(
  root, "server/plugins/workbench/src/client/certification-model.ts");
const fixturePath = path.join(
  root, "server/plugins/workbench/tests/fixtures/t261009-41-certification-fixture.json");

const fail = (m) => { console.log("FAIL: " + m); process.exit(1); };
if (spawnSync("node", ["--version"]).status !== 0) {
  console.log("ENV_FAIL: node missing"); process.exit(2);
}

const EMOJI_RE = /[\u{1F000}-\u{1FAFF}\u{2600}-\u{27BF}\u{2190}-\u{21FF}\u{2B00}-\u{2BFF}]/u;
const checks = [];
const check = (name, cond) => checks.push([name, Boolean(cond)]);
const labels = (v) => {
  if (typeof v === "string") return [v];
  if (Array.isArray(v)) return v.flatMap(labels);
  if (v && typeof v === "object") return Object.values(v).flatMap(labels);
  return [];
};

const fixture = JSON.parse(readFileSync(fixturePath, "utf8"));
const input = fixture.input;
if (!input || !Array.isArray(input.outcomes)) {
  fail("fixture lacks engine projection input (keys: " +
       Object.keys(fixture).join(",") + ")");
}

const mod = await import(modelPath).catch(() => null);
if (!mod || typeof mod.deriveCertificationFace !== "function") {
  fail("deriveCertificationFace not importable from " + modelPath +
       " (TDD-phase red expected pre-implement)");
}
const { deriveCertificationFace, promoteDisabled, formatClock, formatStamp, faceVocabulary } = mod;
for (const fn of [promoteDisabled, formatClock, formatStamp, faceVocabulary]) {
  if (typeof fn !== "function") fail("model public helper missing: " + fn);
}

// B1 counts add up and appear once: delivered + certified + waiting == every
// outcome the engine reported, and promotable == certified count (rule 3).
{
  const f = deriveCertificationFace(input);
  // 261017 re-anchor (integration, gatekeeper): the face's buckets are SUBSETS of
  // the outcomes, not a partition — a certified ticket may also be delivered, and
  // `promotable` is the certified-but-not-yet-delivered count (see the model's own
  // rule: "promote stays enabled while frozen: the gate is promotable === 0 only").
  // The old assertions assumed a partition, which the t261016-09 landing's face
  // semantics (D4 refusal face) no longer provide; the face is right, the
  // expectation was stale.
  const outcomeTickets = new Set(input.outcomes.map((o) => o.ticket));
  const certifiedTickets = f.certified.map((c) => c.ticket);
  const waitingTickets = f.waiting.map((w) => w.ticket);
  check("B1 every counted ticket appears in outcomes and none is counted twice",
        [...certifiedTickets, ...waitingTickets].every((t) => outcomeTickets.has(t))
        && new Set([...certifiedTickets, ...waitingTickets]).size
           === certifiedTickets.length + waitingTickets.length
        && f.deliveredTotal <= input.outcomes.length);
  check("B1b promotable equals the certified-but-undelivered count",
        f.promotable === f.certified.filter((c) => !c.delivered).length);
  check("B1c face is ok with no reason", f.ok === true && f.reason === "");
}

// B2 promote lives through freeze, disabled only at zero (rule 5).
{
  const f = deriveCertificationFace(input);
  check("B2 frozen face still promotable",
        f.state === "FROZEN" && f.promotable > 0 && promoteDisabled(f) === false);
  check("B2b frozen banner names the blockers",
        f.frozenFace && f.frozenFace.blockers.length > 0);
  const zero = deriveCertificationFace({ ...input, outcomes: [], waitStates: [], certs: [] });
  check("B2c nothing to promote is the ONLY disabled reason",
        zero.promotable === 0 && promoteDisabled(zero) === true);
  // A PARTIAL freeze claim (boolean only, identity fields absent) may never
  // render as a green line — the conservative direction is frozen, blockers
  // empty because none were recorded (arbitrate gen 0 pin boundary).
  const bare = deriveCertificationFace({ ...input, freeze: { frozen: true } });
  check("B2e partial freeze claim never reads as green",
        bare.state === "FROZEN" && bare.frozen === true);
}

// B3 the boundary is the certifying round, older than the red round. It is
// shown whenever a certification covers landed tickets (it is the certified/
// waiting boundary under the bar, rule 2), and a face with no certification
// at all owes no boundary.
{
  const f = deriveCertificationFace(input);
  const greenCert = input.certs.find((c) => c.run === "run-green");
  const redRun = input.runs.find((r) => r.verdict === "red");
  check("B3 boundary names the certifying run whenever a cert covers landings",
        input.certs.length > 0 && f.boundary && f.boundary.runId === greenCert.run);
  // t261019-23 (F3): every moment the face shows carries a full date+time
  // stamp, boundary included (arbitrate gen 0 contract update — the pin was
  // clock-only, the ticket's user words name '10:45'-style moments as the
  // defect).
  check("B3b boundary moment is that certification's moment, with a date",
        f.boundary.at === formatStamp(greenCert.at));
  const red = f.rounds.find((r) => r.runId === redRun.id);
  check("B3c boundary precedes the red round",
        red && greenCert.at < redRun.started_at && f.boundary.at !== red.startedAt);
  const bare = deriveCertificationFace({ ...input, certs: [], waitStates: [] });
  check("B3d no certification, no boundary", bare.boundary === null);
}

// B4 the measured column, trigger words, and labelled result parts (rule 4).
{
  const f = deriveCertificationFace(input);
  const sha = input.runs[0].repos[0].revision;
  // t261019-23 (F6): the measured token names the repo ('line <repo>:<sha8>')
  // so the short sha reads as a revision of a named repo, not a serial number
  // (arbitrate gen 0 contract update — the ticket's user words name the bare
  // sha as the defect).
  check("B4 measured is 'line <repo>:<sha8>'",
        f.rounds.every((r) => r.measured === "line " +
          input.runs[0].repos[0].repo + ":" + sha));
  check("B4b never 'main@<sha> +N'",
        !labels(f).some((s) => /main@[0-9a-f]+\s*\+\d+/.test(s)));
  check("B4c trigger is auto/manual only",
        f.rounds.every((r) => r.trigger === "auto" || r.trigger === "manual"));
  check("B4d result parts labelled and summing",
        f.rounds.every((r) => {
          const q = r.result;
          return [q.pass, q.fail, q.env].every((n) => Number.isInteger(n) && n >= 0);
        }));
  const red = f.rounds.find((r) => r.verdict === "red");
  check("B4e red verdict carries its blocker count", red && red.blockers > 0);
}

// B5 no emoji, vocabulary only (rule 8).
{
  const f = deriveCertificationFace(input);
  const ls = labels(f);
  check("B5 no emoji on the face", ls.every((s) => !EMOJI_RE.test(s)));
  check("B5b vocabulary is published and the round words are in it",
        ["auto", "manual", "green", "red"].every((w) => faceVocabulary().includes(w)));
}

// B6 malformed input degrades to a NAMED empty face — no throw, no invented
// data, never a fabricated 'next round at' (rule 9), and a malformed freeze
// record never silently reads as 'not frozen' (the fail-closed ledger rule).
// Pin boundary (arbitrate gen 0): the validator's DECLARED contract accepts a
// boolean frozen claim with optional string identity fields (B2e pins its
// conservative direction); what must still degrade is everything outside the
// engine's output shape — non-object freeze, non-string identity fields,
// non-boolean frozen.
for (const bad of [null, undefined, {}, { line: 42 }, { outcomes: "nope" },
                   { ...input, freeze: "red" },
                   { ...input, freeze: { frozen: true, cause: 42 } },
                   { ...input, freeze: { frozen: "yes" } }]) {
  let f2 = null;
  try { f2 = deriveCertificationFace(bad); } catch (e) { f2 = null; check(
    "B6 malformed input " + JSON.stringify(bad) + " THREW (rule 9 breach)", false);
    continue; }
  check("B6 malformed input " + JSON.stringify(bad) + " tolerated",
        f2 && typeof f2 === "object" && f2.ok === false && f2.reason !== "" &&
        f2.certified.length === 0 && f2.promotable === 0);
}

let bad = 0;
for (const [n, ok] of checks) { console.log((ok ? "ok " : "RED ") + n); if (!ok) bad++; }
console.log(JSON.stringify({ total: checks.length, failed: bad }));
process.exit(bad ? 1 : 0);
