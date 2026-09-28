/**
 * Baseline: sandbar project admission contract v1 (t260831-06).
 *
 * Intent:
 *   This ticket produces NO code — its entire deliverable is two design
 *   documents: the new 《sandbar project onboarding contract v1》 and a new
 *   「five-layer architecture & dependency reversal」 section in the multi-agent
 *   mechanism doc.
 *   The user-perceivable contract is therefore documentary:
 *   - Every downstream ticket (config-ization, in-place reversal, physical
 *     relocation) depends on the contract doc as its prior input; a missing or
 *     partial contract means future config tickets have no spec to implement
 *     fail-closed behavior against (silent pass-through becomes the default).
 *   - The five admitted contract items must each carry a schema version and a
 *     three-state closing semantics clause (missing/malformed/version-unsupported),
 *     where malformed input fails closed with a precise error — never silently
 *     treated as "no declaration".
 *
 * Note (260928): the documents were translated into English (host order); the
 * assertions below were re-anchored on the English wording of the deliverables.
 * Chinese-only fixtures stay Chinese: the source tag `> 来源立项：sandbar` and the
 * change-record version/hash identifiers.
 *   - The two documents must not drift: the mechanism doc gives direction and
 *     cross-links only; the contract doc is the single place details expand.
 *   - Write-set discipline is owned by verify_lane (per-ticket write_set
 *     context) and is deliberately NOT asserted here (t260831-08 rework per
 *     the baseline design red line): the baseline carries document-content
 *     assertions only — see integration/README.md.
 *
 * High-level steps (fully offline: repo-read-only assertions + one git call):
 *   A. Contract doc exists with complete frontmatter and the source tag
 *      (> 来源立项：sandbar).
 *   B. Four-part template per the writing guide: Problem -> Requirement ->
 *      Nongoal -> Proposal, in order.
 *   C. Five admitted items, each with schema version and a closing-semantics
 *      clause; global three-state semantics (missing / malformed / version
 *      unknown-or-too-new) with fail-closed for the latter two.
 *   D. Context composition order clause: repo docs ⊕ project-level docs; IDE docs
 *      never enter project ticket context.
 *   E. Stable vs internal surfaces; change-record mechanism; upgrade
 *      decoupling (semver + deprecation window + compatibility matrix as a
 *      mechanism promise, not pre-filled cells); elevation principle
 *      (third real project demand).
 *   F. Mechanism doc: new section present; five layers named; "the dsh platform
 *      is followed, never patched"; reversal direction (projects register
 *      toward the IDE); source tag; cross-links both ways; frontmatter updated.
 *   G. Cross-doc consistency (same five items / three-state keywords / context
 *      composition).
 *
 * Note: FAILS LOUDLY until t260831-06 implement lands — the contract doc does
 * not exist yet and the mechanism doc has no such section. That is the
 * intended pre-implementation state; run_integration_tests is the judging
 * stage.
 *
 * Reference: .suyou/stage_create_plan_gen1.json (approved plan v2);  // naming-compat
 * review history in .suyou/stage_review_plan_gen0.json (round 1: three-state  // naming-compat
 * closing semantics mandated) and .suyou/stage_review_plan_gen1.json  // naming-compat
 * (round 2: approved).
 */

import { readFileSync, existsSync } from 'node:fs'
import { join } from 'node:path'

let pass = 0, fail = 0, envFail = 0, na = 0
function ok(cond, label) {
  if (cond) { pass++; console.log(`  ok ${label}`) }
  else { fail++; console.error(`  FAIL ${label}`) }
}
function section(t) { console.log(`\n== ${t}`) }

const root = process.cwd()
const CONTRACT = join(root, 'docs', 'design', 'sandbar-project-onboarding-contract-v1.md')
const MECH = join(root, 'docs', 'design', 'deepseek_harness_and_temporal_based_multi-agent_mechanism.md')

let contract = ''
let mech = ''
try { contract = readFileSync(CONTRACT, 'utf8') } catch { contract = null }
try { mech = readFileSync(MECH, 'utf8') } catch { mech = null }

/* ============================ helpers ============================ */
/** Extract a markdown section: from the heading line containing `title` to the next same-or-higher `#` heading. */
function extractSection(md, title) {
  if (md == null) return null
  const lines = md.split('\n')
  const start = lines.findIndex(l => l.startsWith('#') && l.toLowerCase().includes(String(title).toLowerCase()))
  if (start === -1) return null
  const level = lines[start].match(/^#+/)[0].length
  let end = lines.length
  for (let i = start + 1; i < lines.length; i++) {
    const m = lines[i].match(/^(#+)\s/)
    if (m && m[1].length <= level) { end = i; break }
  }
  return lines.slice(start, end).join('\n')
}
/** Per-item check: section for `keyword` exists and mentions schema v1. */
function itemSectionHasSchema(keyword) {
  const s = extractSection(contract, keyword)
  return s !== null && /schema/i.test(s) && /v1/.test(s)
}

const ITEMS = [
  ['Project registration and directory model', 'registration & directory model'],
  ['Policy configuration and integration test declaration', 'strategy config & integration-test declaration'],
  ['Role persona override', 'persona overlay'],
  ['Epic proposal content location', 'epic content location'],
  ['Tool bridge protocol', 'tool-bridge protocol'],
]

try {
  /* ------------------------------------------------ A. contract doc shell */
  section('A contract doc shell (exists, frontmatter, source tag)')
  if (contract == null) {
    ok(false, 'docs/design/sandbar-project-onboarding-contract-v1.md exists')
  } else {
    ok(true, 'docs/design/sandbar-project-onboarding-contract-v1.md exists')
    const fm = contract.match(/^---\n([\s\S]*?)\n---/)
    ok(fm !== null, 'frontmatter block present')
    if (fm) {
      ok(/title:\s*.*/.test(fm[1]), 'frontmatter: title')
      ok(/category:\s*design/.test(fm[1]), 'frontmatter: category=design')
      ok(/tags:\s*\[?[\s\S]*?sandbar/.test(fm[1]), 'frontmatter: tags include sandbar')
      ok(/status:\s*\S+/.test(fm[1]), 'frontmatter: status')
      ok(/updated:\s*\d{4}-\d{2}-\d{2}/.test(fm[1]), 'frontmatter: updated (YYYY-MM-DD)')
    }
    ok(contract.includes('> 来源立项：sandbar') || /^>\s*Source epic( proposal)?:\s*sandbar\s*$/m.test(contract),
      'source tag (> 来源立项：sandbar / > Source epic: sandbar) at document end')
    ok(contract.includes('deepseek_harness_and_temporal_based_multi-agent_mechanism')
      || contract.includes('mechanism doc'),
      'cross-link/reference to the mechanism doc')
  }

  /* ------------------------------------------------ B. four-part template */
  section('B four-part template per writing guide (Problem -> Requirement -> Nongoal -> Proposal)')
  if (contract != null) {
    const probes = ['Problem', 'Requirement', 'Nongoal', 'Proposal']
    const pos = probes.map(p => {
      const m = contract.match(new RegExp(`^#{2,3}[^\\n]*${p}`, 'm'))
      return m ? contract.indexOf(m[0]) : -1
    })
    for (let i = 0; i < probes.length; i++) ok(pos[i] !== -1, `section present: ${probes[i]}`)
    ok(pos.every(p => p !== -1) && pos.every((p, i) => i === 0 || p > pos[i - 1]),
      'four sections present and in order')
  }

  /* ------------------------------------------------ C. five items + schema + three-state */
  section('C five admitted items, each with schema version + closing semantics; three-state clause')
  if (contract != null) {
    for (const [kw, label] of ITEMS) {
      ok(new RegExp(kw.replace(/[-/\\^$*+?.()|[\]{}]/g, '\\$&'), 'i').test(contract), `item named: ${label}`)
      ok(itemSectionHasSchema(kw), `item carries schema version: ${label}`)
      const s = extractSection(contract, kw)
      ok(s !== null && /closing semantics/i.test(s), `item has closing-semantics clause: ${label}`)
    }
    // Strategy item must name both policy files with their roles.
    const strat = extractSection(contract, 'Policy configuration and integration test declaration') || ''
    ok(strat.includes('verify.yaml'), 'strategy item names verify.yaml')
    ok(strat.includes('merge-checks.yaml'), 'strategy item names merge-checks.yaml')
    ok(/integration test|red-green/i.test(strat), 'strategy item covers integration-test declaration (entry/judgement)')
    // Global three-state closing semantics (review_plan round-1 mandate).
    ok(/\bmissing\b/i.test(contract), 'three-state clause: missing state')
    ok(/\bmalformed\b/i.test(contract), 'three-state clause: malformed state')
    ok(/fail[- ]?closed/i.test(contract), 'malformed/version-unsupported state is fail-closed')
    ok(/version/i.test(contract) && (/unknown|newer|too new|unsupported/i.test(contract)),
      'version-unknown-or-too-new state named with fail-closed handling')
    ok(/never[^.\n]{0,60}(silent|treat)/i.test(contract)
      || /must not[^.\n]{0,60}silent/i.test(contract)
      || /not silently/i.test(contract),
      'explicit ban on silently treating malformed as "no declaration"')
    // merge-checks.yaml current behavior must be classified as the missing state, unchanged
    // (classification sentence may sit a heading away from the first filename mention).
    ok(contract.split('\n').some(l => l.includes('merge-checks') && /\bmissing\b/i.test(l)),
      'merge-checks.yaml existing "no file = no extended checks" classified as missing state (same line)')
  }

  /* ------------------------------------------------ D. context composition order */
  section('D docs context composition order (repo docs ⊕ project docs; IDE docs excluded)')
  if (contract != null) {
    ok(/repo[^⊕\n]{0,25}docs?\s*⊕\s*project[- ]level/i.test(contract)
      || (contract.includes('repo') && /project[- ]level docs/i.test(contract) && contract.includes('⊕')),
      'composition named: repo docs ⊕ project-level docs')
    ok(contract.includes('⊕') || /compose|composed|composition|concatenat|combine/i.test(contract),
      'composition operator/verb present')
    ok(/IDE\s*docs?[^\n]{0,60}(never|not|excluded|outside)/i.test(contract)
      || /(never|not|excluded)[^\n]{0,40}project ticket context/i.test(contract),
      'IDE docs explicitly excluded from project ticket context')
    ok(/three[- ]tier|IDE docs|project[- ]level docs|repo[- ]level docs/i.test(contract),
      'three-tier docs hierarchy (IDE / project / repo) named')
  }

  /* ------------------------------------------------ E. stable vs internal + change record + upgrade */
  section('E stable vs internal surfaces, change record, upgrade decoupling, elevation principle')
  if (contract != null) {
    ok(/stable|contract surface/i.test(contract), 'stable contract surface named')
    ok(/internal implementation|implementation-internal/i.test(contract), 'internal-implementation surface named')
    for (const kw of ['template', 'plugin', '.suyou']) {  // naming-compat
      ok(contract.includes(kw), `internal-surface example named: ${kw}`)
    }
    ok(/unstable|may change (at )?any time|not guaranteed/i.test(contract), 'internal surfaces marked as unstable')
    ok(/change record|change log/i.test(contract), 'change-record mechanism present')
    ok(/semver/i.test(contract) && /compatibility matrix/i.test(contract), 'upgrade decoupling: semver + compatibility matrix')
    ok(/deprecat/i.test(contract) && /\bN\b\s*(releases?|versions?)?/i.test(contract), 'deprecation keeps old reading for N versions')
    ok(/third real project|third project/i.test(contract) && /real (project )?demand/i.test(contract),
      'elevation principle: third real project demand')
    ok(/upgrade burden/i.test(contract), 'contract surface = upgrade burden stated')
  }

  /* ------------------------------------------------ F. mechanism doc new section */
  section('F mechanism doc: five-layer architecture & dependency-reversal section')
  if (mech != null) {
    const s = extractSection(mech, 'Five-layer architecture')
    ok(s !== null, 'section five-layer architecture & dependency reversal present')
    if (s != null) {
      for (const layer of ['dsh platform', 'sandbar itself', 'built-in extensions', 'machine-level configuration', 'workspace']) {
        ok(new RegExp(layer, 'i').test(s), `five-layer table names: ${layer}`)
      }
      ok(/follow but never touch|never patch/i.test(s), 'dsh platform stance: follow but never touch')
      ok(/dependency[- ]direction reversal|revers(e|ing) the dependency direction|registers? with the IDE|project registers/i.test(s),
        'reversal direction: project registers toward IDE')
      ok(/contractualiz/i.test(s) && /reverse in place|in[- ]place reversal/i.test(s) && /physically relocate|physical relocation|physical move/i.test(s),
        'three ordered steps named (contractualize -> in-place reversal -> physical relocation)')
      ok(/irreversible|never reversed|order (may not|must not|cannot) be|cannot be reversed/i.test(s), 'step order pinned as irreversible')
      ok(s.includes('> 来源立项：sandbar') || /^>\s*Source epic( proposal)?:\s*sandbar\s*$/m.test(s),
        'section ends with source tag (> 来源立项：sandbar / > Source epic: sandbar)')
      ok(s.includes('sandbar-project-onboarding-contract-v1') || /contract v1|contract doc/i.test(s),
        'section cross-references the contract doc (no re-expansion)')
    }
    // frontmatter updated stamp must record this change (advances with the document).
    const fm = mech.match(/^---\n([\s\S]*?)\n---/)
    ok(fm !== null && /updated:\s*2026-\d{2}-\d{2}/.test(fm[1]) && !/updated:\s*2026-08-24/.test(fm[1]),
      'mechanism doc frontmatter updated bumped for this change')
    // Related-docs mutual link back to the contract doc.
    ok(mech.includes('sandbar-project-onboarding-contract-v1'), 'mechanism doc links the contract doc (related docs)')
  }

  /* ------------------------------------------------ G. consistency */
  section('G cross-doc consistency')
  if (contract != null && mech != null) {
    // The mechanism doc gives direction and links the contract; it must reference
    // the three-state semantics as a pointer ("见契约" / see the contract), not
    // silently omit them —
    // while NOT re-expanding the per-state vocabulary (double-source guard below).
    const sec = extractSection(mech, 'Five-layer architecture') || ''
    ok(/three-state|closing semantics/i.test(sec), 'new section references the three-state closing semantics (as pointer to contract v1)')
    // Mechanism doc must not re-expand per-item schema detail (double-source guard):
    // the new section points at the contract doc instead of duplicating schema labels.
    const s = extractSection(mech, 'Five-layer architecture') || ''
    const schemaMentions = (s.match(/schema/gi) || []).length
    ok(schemaMentions <= 1, `new section does not re-expand schema details (${schemaMentions} mention(s), link-only)`)
  }
  /* ------------------------------------------------ H. ②a~②e declaration-based alignment (t260903-01) */
  section('H ②a list-command rewrite + ②b/②c/②d/②e new chapters + schema-v1 adjudication')
  if (contract != null) {
    const sec2a = extractSection(contract, '②a')
    ok(sec2a !== null, '②a section present')
    // ②a must carry the v2 list-command key set as the authoritative field table.
    ok(sec2a !== null && /id,\s*cmd,\s*cwd\?,\s*timeout\?/.test(sec2a),
      '②a field table carries list-command keys {id, cmd, cwd?, timeout?}')
    ok(sec2a !== null && /integration\.cmd/.test(sec2a), '②a names integration.cmd (not entry/red_green)')
    ok(sec2a !== null && /keep[- ]schema[- ]v1|erratum/i.test(sec2a),
      '②a carries the keep-schema-v1 adjudication (erratum, not a grammar break)')
    // Four new chapters present as headings.
    for (const [kw, label] of [
      ['output contract', '②b output contract'],
      ['grammar subset', '②c parser grammar subset'],
      ['Thin-shell execution topology', '②d thin-shell topology'],
      ['rule of three', '②e reuse tiers + rule of three'],
    ]) {
      const s = extractSection(contract, kw)
      ok(s !== null, `new chapter present: ${label}`)
    }
    // ②b must state the two per-lane return shapes and the zero-scenario-green idiom.
    const sec2b = extractSection(contract, '②b ') || ''
    ok(/red_count/.test(sec2b) && /ran,\s*pass,\s*fail/.test(sec2b),
      '②b states both per-lane return shapes (content/code vs integ)')
    ok(/zero[- ]scenario[- ]green/i.test(sec2b) && /(no|not)[^.\n]{0,60}["“「]?missing\s*=\s*(off|closed)/i.test(sec2b),
      '②b states zero-scenario-green as the integration lane sole closing idiom')
    ok(/SCENARIOS ran=/.test(sec2b) && /(does not (read|verify|cross-check)|neither reads nor)/i.test(sec2b),
      '②b downgrades the SCENARIOS line to a reference line (engine neither reads nor cross-checks)')
    // ②a field table must be free of live five-type vocabulary: any occurrence of
    // retired keys in the whole doc may only sit on a retirement/erratum note line.
    // The change-record section is append-only history (past entries stay verbatim)
    // and is out of scope for the live-drift check. Note words may sit on the
    // neighbouring line (cross-line sentence), hence the ±1 line window.
    const liveLines = contract.split(/^#{2,4}\s*change (record|log)/im)[0].split('\n')
    const hasNote = (l) => /retired|stale|erratum|obsolete|deprecated/i.test(l)
    const fiveTypeBad = liveLines.filter((l, i) =>
      /shotdebug|deps_dir|integration\.entry|red_green\.rule/.test(l)
      && !hasNote(l)
      && !(i > 0 && hasNote(liveLines[i - 1]))
      && !(i < liveLines.length - 1 && hasNote(liveLines[i + 1])))
    ok(fiveTypeBad.length === 0,
      `retired five-type keys appear only on retirement/erratum note lines (${fiveTypeBad.length} bad line(s))`)
    // change record carries this ticket's entry
    ok(/v1\.5/.test(contract) && /t260903-01/.test(contract),
      'change record carries v1.5 / t260903-01 entry')
  }
} finally {
  // repo-read-only test: no fixtures, no env mutation, nothing to clean up.
}

console.log(`\nSUMMARY pass=${pass} fail=${fail} env_fail=${envFail} na=${na}`)
const allNa = na > 0 && pass + fail + envFail === 0
process.exit(fail > 0 || allNa ? 1 : envFail > 0 ? 2 : 0)
