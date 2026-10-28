#!/usr/bin/env node
/**
 * tests/t261028-22-lane-map-labels.mjs — lane-map caption placement battery
 * (ticket t261028-22; host report 261028: "on the dev-lane map the captions
 * frequently overlap and cannot be read").
 *
 * INTENT (what this battery proves). `laneMapScene` must never paint two
 * captions on top of each other, never paint a caption outside the canvas,
 * grow the scene height with the caption rows it actually used, keep a
 * documented minimum gap between two captions on one row, and never lose a
 * shortened caption (its full text stays in the hover title). The retired
 * placement (`level = i % 2`, no box comparison) is exactly the defect the host
 * reported, so the SAME checker must go red against it - that is the teeth leg.
 *
 * HIGH-LEVEL STEPS.
 *   1. Build scenes for several step-duration sets (one stage; four stages;
 *      the ten dev-lane stages; fourteen one-minute stages; seventeen stages
 *      carrying an optional note; seventeen three-round stages - the ellipsis
 *      face; thirty long-id stages; a dev-lane map with two parallel pairs; a
 *      map with nothing started yet).
 *   2. Re-derive every VISIBLE caption box independently of the model's own
 *      placement: from the label's text + tspans, its anchor, its track's font
 *      size and the documented character-width estimate.
 *   3. Assert, for every scene: no two boxes intersect; every box lies inside
 *      the canvas; the height covers the rows used; same-row boxes keep
 *      LM_LABEL.MIN_GAP; no caption is blank; a shortened caption keeps its
 *      full text in its hover title and the segment's own hover title still
 *      names the stage; levels stay inside [0, LM_LABEL.MAX_LEVEL] and each
 *      label's y is the row the model documents for its level.
 *   4. Teeth: calibrate the checker on hand-made box pairs (it must bite the
 *      overlap and pass the separated pair), then re-place the crowded scenes'
 *      captions with the retired two-level rule and require the checker to
 *      report intersections there - while the model's own scene stays clean.
 *
 * Pure functions only: buildLaneMap + laneMapScene run in node, no DOM
 * measurement, no console server, never port 3099.
 */

import {
  buildLaneMap, laneMapScene, lmCaptionFont, lmCaptionText, lmTextWidth,
  LM_LABEL, LM_SCENE, LM_PARTNER_LABEL_Y,
} from '../src/client/lane-map-model.ts'
import { stageDisplayLabel } from '../src/client/ui-labels.ts'

let passed = 0
let failed = 0
function ok(cond, name) {
  if (cond) { passed += 1; console.log(`ok   ${name}`) }
  else { failed += 1; console.error(`FAIL ${name}`) }
}

const MIN = 60_000
const T0 = 1_700_000_000_000
/** The engine's own stage vocabulary (ids that map to long English captions). */
const IDS = [
  'create_plan', 'review_plan', 'implement', 'design_integration_tests', 'ui_evidence',
  'run_integration_tests', 'arbitrate', 'acceptance_walkthrough', 'merge_check', 'merge',
  'setup', 'suite', 'inspect', 'produce', 'selfcheck', 'report', 'close',
]

/* ── fixtures ───────────────────────────────────────────────────────────── */

/** A linear topology (`ids`) whose stages each ran `durs[i]` minutes, closed
 *  with an explicit done row per stage (so the weights are `measured`). */
function linearScene(ids, durs, nodeExtra = () => ({})) {
  const nodes = ids.map(id => ({ id, label: id, role: 'developer', kind: 'agent', parts: [], ...nodeExtra(id) }))
  let t = 0
  const timeline = []
  for (let i = 0; i < ids.length; i += 1) {
    timeline.push({ at: new Date(T0 + t * MIN).toISOString(), stage: ids[i], state: 'running' })
    t += durs[i]
    timeline.push({ at: new Date(T0 + t * MIN).toISOString(), stage: ids[i], state: 'done' })
  }
  const model = buildLaneMap(
    { version: 'topology-v1', template: 'fixture-linear', nodes, edges: ids.slice(1).map((id, i) => [ids[i], id]), groups: [] },
    { status: 'running', stage: ids[ids.length - 1], timeline, handoffs: [] },
    { nowMs: T0 + t * MIN },
  )
  return laneMapScene(model)
}

/** A dev-lane shaped map: two parallel pairs folded into windows, one human
 *  gate at the end. */
function groupScene(minutesPerStage) {
  const ids = ['create_plan', 'review_plan', 'implement', 'design_integration_tests', 'ui_evidence',
    'run_integration_tests', 'arbitrate', 'acceptance_walkthrough', 'merge_check', 'merge']
  const nodes = ids.map(id => ({ id, label: id, role: 'integration', kind: id === 'merge' ? 'human' : 'agent', parts: [] }))
  let t = 0
  const timeline = []
  for (const id of ids) {
    timeline.push({ at: new Date(T0 + t * MIN).toISOString(), stage: id, state: 'running' })
    t += minutesPerStage
    timeline.push({ at: new Date(T0 + t * MIN).toISOString(), stage: id, state: 'done' })
  }
  const model = buildLaneMap(
    {
      version: 'topology-v1',
      template: 'dev-lane',
      nodes,
      edges: [],
      groups: [
        { id: 'parallel_impl_design', members: ['implement', 'design_integration_tests'], phase: 'p1' },
        { id: 'arb_acc_parallel', members: ['arbitrate', 'acceptance_walkthrough'], phase: 'p2' },
      ],
    },
    { status: 'running', stage: 'merge', timeline, handoffs: [] },
    { nowMs: T0 + t * MIN },
  )
  return laneMapScene(model)
}

/** A rework-heavy map: every stage ran `rounds` times and carries an optional
 *  note, so the captions are long enough that the rows run out. */
function reworkScene(ids, rounds) {
  const nodes = ids.map(id => ({ id, label: id, role: 'developer', kind: 'agent', parts: [], optional: 'UI tickets only' }))
  let t = 0
  const timeline = []
  for (const id of ids) {
    for (let r = 1; r <= rounds; r += 1) {
      timeline.push({ at: new Date(T0 + t * MIN).toISOString(), stage: id, state: 'running', gen: r })
      t += 3
      timeline.push({ at: new Date(T0 + t * MIN).toISOString(), stage: id, state: 'done', gen: r })
    }
  }
  const model = buildLaneMap(
    { version: 'topology-v1', template: 'fixture-rework', nodes, edges: [], groups: [] },
    { status: 'running', stage: ids[ids.length - 1], timeline, handoffs: [] },
    { nowMs: T0 + t * MIN },
  )
  return laneMapScene(model)
}

/* ── the checker: caption boxes re-derived from the label alone ──────────── */

/** The visible caption of a label (text + the tspans the renderer appends). */
const visible = l => lmCaptionText(l)

/** A caption box in scene coordinates: the model's documented estimate, the
 *  label's own anchor and row baseline (this file never reads a placed box out
 *  of the model - it re-derives it, so a wrong placement cannot hide). */
function boxOf(l) {
  const font = lmCaptionFont(l.track)
  const w = lmTextWidth(visible(l), font)
  const x0 = l.anchor === 'middle' ? l.x - w / 2 : l.x
  return {
    label: l,
    text: visible(l),
    x0,
    x1: x0 + w,
    y0: l.y - font * LM_LABEL.ASCENT_EM,
    y1: l.y + font * LM_LABEL.DESCENT_EM,
  }
}

const intersects = (a, b) => a.x0 < b.x1 && b.x0 < a.x1 && a.y0 < b.y1 && b.y0 < a.y1

/** Every visible caption box of a scene (a blank caption paints nothing). */
const boxesOf = scene => scene.labels.filter(l => visible(l) !== '').map(boxOf)

/**
 * The whole contract, as a list of named violations (empty = clean).
 * Rows are identified by (track, level): a main row and a partner row that
 * share a level number are different rows at different baselines.
 */
function violationsOf(scene) {
  const out = []
  const boxes = boxesOf(scene)
  for (let i = 0; i < boxes.length; i += 1) {
    const a = boxes[i]
    if (a.x0 < -1e-9 || a.x1 > scene.width + 1e-9) out.push(`caption "${a.text}" leaves the canvas horizontally (${a.x0.toFixed(1)}..${a.x1.toFixed(1)} of ${scene.width})`)
    if (a.y0 < -1e-9 || a.y1 > scene.height + 1e-9) out.push(`caption "${a.text}" leaves the canvas vertically (${a.y0.toFixed(1)}..${a.y1.toFixed(1)} of ${scene.height})`)
    if (a.label.level < 0 || a.label.level > LM_LABEL.MAX_LEVEL) out.push(`caption "${a.text}" sits on level ${a.label.level} outside [0, ${LM_LABEL.MAX_LEVEL}]`)
    for (let j = i + 1; j < boxes.length; j += 1) {
      const b = boxes[j]
      if (intersects(a, b)) out.push(`captions intersect: "${a.text}" L${a.label.track[0]}${a.label.level} x "${b.text}" L${b.label.track[0]}${b.label.level}`)
      if (a.label.track === b.label.track && a.label.level === b.label.level) {
        const gap = b.x0 >= a.x0 ? b.x0 - a.x1 : a.x0 - b.x1
        if (gap < LM_LABEL.MIN_GAP - 1e-9) out.push(`same-row captions "${a.text}" / "${b.text}" keep only ${gap.toFixed(2)}px (min ${LM_LABEL.MIN_GAP})`)
      }
    }
  }
  // The height must cover the rows the model used: level 0 and 1 are the
  // mock's own rows, every further main row grows the scene by one STEP.
  const mainLevels = scene.labels.filter(l => l.track === 'main').reduce((m, l) => Math.max(m, l.level), 0)
  const needHeight = LM_SCENE.H + Math.max(0, mainLevels - 1) * LM_LABEL.STEP
  if (scene.height < needHeight - 1e-9) out.push(`scene height ${scene.height} does not cover ${mainLevels + 1} caption rows (needs ${needHeight})`)
  return out
}

/** The label's y is exactly the documented row baseline for its level (plus the
 *  whole-scene downward shift the model applies when rows stack above row 1). */
function rowFormulaViolations(scene) {
  const out = []
  const mainLevels = scene.labels.filter(l => l.track === 'main').reduce((m, l) => Math.max(m, l.level), 0)
  const dy = Math.max(0, mainLevels - 1) * LM_LABEL.STEP
  for (const l of scene.labels) {
    const want = l.track === 'main'
      ? LM_SCENE.LABEL_LO - l.level * LM_LABEL.STEP + dy
      : LM_PARTNER_LABEL_Y + l.level * LM_LABEL.STEP + dy
    if (Math.abs(l.y - want) > 1e-9) out.push(`"${visible(l)}" sits at y=${l.y}, the documented row for level ${l.level} is y=${want}`)
    if (Math.abs(lmCaptionFont(l.track) - (l.track === 'main' ? LM_LABEL.FONT_MAIN : LM_LABEL.FONT_PARTNER)) > 1e-9) out.push(`"${visible(l)}" carries the wrong font size for its track`)
  }
  return out
}

/** The retired placement (t261028-22 root cause): caption i on level i % 2,
 *  anchor clamped into [CLAMP_MIN, CLAMP_MAX], NOTHING compares label boxes.
 *  Re-built here from the scene's own bars (bar geometry is untouched by the
 *  ticket) so the teeth leg tests the rule, not a stale copy of the code.
 *  Captions are restored to their full text first: the retired code never
 *  shortened anything, and the teeth leg must not inherit this ticket's cuts. */
function retiredPlacement(scene) {
  const mainBars = scene.bars.filter(b => b.track === 'main')
  const full = l => ({
    text: l.title ?? l.text,
    opt: l.ellipsized ? undefined : l.opt,
    roundBadge: l.ellipsized ? undefined : l.roundBadge,
    everTitle: l.ellipsized ? undefined : l.everTitle,
  })
  let mainSeen = 0
  return scene.labels.map(l => {
    const parts = full(l)
    if (l.track === 'partner') {
      return { ...l, ...parts, x: l.x, y: LM_PARTNER_LABEL_Y, level: 0 }
    }
    const bar = mainBars[mainSeen] || { x: 0, w: 0 }
    const level = mainSeen % 2
    const y = level === 0 ? LM_SCENE.LABEL_LO : LM_SCENE.LABEL_HI
    const x = Math.max(LM_SCENE.CLAMP_MIN, Math.min(bar.x + bar.w / 2, LM_SCENE.CLAMP_MAX))
    mainSeen += 1
    return { ...l, ...parts, x, y, level }
  })
}

/* ── S0. the checker is calibrated (guard the guard) ─────────────────────── */

{
  const mk = (x0, y0) => boxOf({ text: 'a', x: x0 + lmTextWidth('a', 8) / 2, y: y0 + 8 * LM_LABEL.ASCENT_EM, track: 'main', anchor: 'middle', level: 0 })
  const a = mk(0, 0)
  const overlapping = { ...mk(1, 0) }
  const separated = { ...mk(200, 0) }
  const otherRow = { ...mk(1, 20) }
  ok(intersects(a, overlapping), 'S0 checker bites a 1px-apart pair (the calibration red)')
  ok(!intersects(a, separated), 'S0 checker passes a separated pair')
  ok(!intersects(a, otherRow), 'S0 checker sees rows 20px apart as separate rows')
}

/* ── S1..S9 per-scene contract ───────────────────────────────────────────── */

const SCENES = [
  ['S1 one stage', linearScene(['create_plan'], [5])],
  ['S2 four stages', linearScene(IDS.slice(0, 4), [60, 10, 6, 10])],
  ['S3 the ten dev-lane stages (quick)', linearScene(IDS.slice(0, 10), Array.from({ length: 10 }, () => 1))],
  ['S4 fourteen one-minute stages (collides today)', linearScene(IDS.slice(0, 14), Array.from({ length: 14 }, () => 1))],
  ['S5 seventeen one-minute stages, every one optional', linearScene(IDS.slice(0, 17), Array.from({ length: 17 }, () => 1), () => ({ optional: 'UI tickets only' }))],
  ['S6 thirty long-id stages', linearScene(Array.from({ length: 30 }, (_, i) => `${IDS[i % IDS.length]}_${i}`), Array.from({ length: 30 }, (_, i) => 1 + (i % 4)))],
  ['S7 seventeen stages x three rounds (ellipsis face)', reworkScene(IDS.slice(0, 17), 3)],
  ['S8 dev-lane with two parallel pairs', groupScene(2)],
  ['S9 nothing started yet', laneMapScene(buildLaneMap(
    { version: 'topology-v1', template: 'fixture-todo', nodes: IDS.slice(0, 10).map(id => ({ id, label: id, role: 'developer', kind: 'agent', parts: [] })), edges: [], groups: [] },
    { status: 'open', timeline: [] },
  ))],
]

for (const [name, scene] of SCENES) {
  const violations = violationsOf(scene)
  ok(violations.length === 0, `${name}: no caption intersection, no box outside the canvas, rows covered, min gap kept${violations.length ? ` -- ${violations[0]}` : ''}`)
  const rows = rowFormulaViolations(scene)
  ok(rows.length === 0, `${name}: every caption sits on its documented row (level -> y)${rows.length ? ` -- ${rows[0]}` : ''}`)
  ok(scene.labels.every(l => visible(l) !== ''), `${name}: no caption was dropped (an empty caption would hide the stage)`)
  ok(Number.isFinite(scene.height) && scene.height >= LM_SCENE.H, `${name}: the scene height is finite and at least the base canvas (${scene.height})`)
}

/* ── S10. the collision machinery actually engages ───────────────────────── */

{
  const uncrowded = SCENES[1][1]
  ok(uncrowded.labels.filter(l => l.track === 'main').every(l => l.level === 0),
    'S10a the four-stage map keeps every caption on the lowest row (no row spent in vain)')
  const crowded = SCENES[3][1]
  const levels = crowded.labels.filter(l => l.track === 'main').map(l => l.level)
  ok(Math.max(...levels) >= 1, `S10b the crowded map climbs rows instead of overlapping (max level ${Math.max(...levels)})`)
  const rowCounts = new Map()
  for (const l of crowded.labels) rowCounts.set(l.track + l.level, (rowCounts.get(l.track + l.level) || 0) + 1)
  ok([...rowCounts.keys()].length >= 2, 'S10c the crowded map really spreads its captions over several rows')
  // Row-major reading order is preserved: the left-to-right caption order of
  // each row follows the segment order (the reader can still scan the map).
  for (const l of crowded.labels.filter(x => x.track === 'main')) {
    const sameRow = crowded.labels.filter(x => x.track === 'main' && x.level === l.level)
    ok(sameRow.every((x, i) => i === 0 || x.x > sameRow[i - 1].x), `S10d row ${l.level} reads left to right`)
    break
  }
}

/* ── S11. a shortened caption keeps its data ────────────────────────────── */

{
  const scene = SCENES[6][1]
  const cut = scene.labels.filter(l => l.ellipsized)
  const mainLabels = scene.labels.filter(l => l.track === 'main')
  const mainBars = scene.bars.filter(b => b.track === 'main')
  ok(cut.length > 0, `S11a the rework-heavy map shortens at least one caption (got ${cut.length})`)
  ok(mainLabels.length === mainBars.length,
    'S11b every main caption keeps a segment bar to hover (the caption face and the bar face stay paired)')
  for (const l of cut) {
    const full = l.title || ''
    ok(Boolean(full) && full.length > l.text.length, `S11c shortened caption "${l.text}" carries the FULL caption in its hover title (${JSON.stringify(full)})`)
    const stem = l.text.replace(/…$/u, '')
    ok(stem === '' || full.startsWith(stem), `S11d the visible part is a prefix of the full caption ("${stem}" vs "${full}")`)
    ok(lmTextWidth(l.text, lmCaptionFont(l.track)) <= lmTextWidth(full, lmCaptionFont(l.track)),
      'S11e the shortened caption is never wider than the full one')
    const bar = mainBars[mainLabels.indexOf(l)]
    ok(Boolean(bar) && bar.title.includes(stageDisplayLabel(bar.stageId)),
      `S11f the shortened stage keeps its own hover title ("${l.text}" -> ${JSON.stringify(bar ? bar.title.slice(0, 48) : '')})`)
  }
  // The stage names must survive on the bar face for every stage, shortened or not.
  ok(mainBars.every(b => b.title.includes(stageDisplayLabel(b.stageId))),
    'S11g every segment hover title still names its stage (nothing was dropped)')
  const rows = new Set(mainLabels.map(l => l.level)).size
  ok(scene.height > LM_SCENE.H,
    `S11h the scene grew with the caption rows it used (h=${scene.height} > ${LM_SCENE.H}, rows=${rows})`)
}

/* ── S12. TEETH: the retired two-level placement fails the same checker ──── */

{
  const crowded = SCENES[3][1] // fourteen one-minute stages
  const retired = retiredPlacement(crowded)
  const retiredScene = { ...crowded, labels: retired }
  const bad = violationsOf(retiredScene)
  const firstHit = bad.find(v => v.startsWith('captions intersect'))
  ok(Boolean(firstHit),
    `S12a teeth: today's two-level placement puts captions on top of each other${firstHit ? ` -- ${firstHit}` : ' -- NO intersection violation, the teeth leg is vacuous'}`)
  ok(bad.length > 0, `S12b teeth: the same checker reports ${bad.length} violation(s) against the retired placement`)
  const clean = violationsOf(crowded)
  ok(clean.length === 0, 'S12c teeth control: the identical checker passes the model\'s own placement of the same map')
  // Calibration: the retired rule on an UNCROWDED map is clean - so the teeth
  // red comes from crowding + the two-level rule, never from a broken checker.
  const small = SCENES[1][1]
  const smallRetired = violationsOf({ ...small, labels: retiredPlacement(small) })
  ok(smallRetired.filter(v => v.startsWith('captions intersect')).length === 0,
    'S12d teeth calibration: the retired rule is clean on the uncrowded map (the red is the crowding)')
  // And the crowded map is genuinely the defect the host sees: count the pairs.
  const boxes = boxesOf({ ...crowded, labels: retired })
  let pairs = 0
  for (let i = 0; i < boxes.length; i += 1) for (let j = i + 1; j < boxes.length; j += 1) if (intersects(boxes[i], boxes[j])) pairs += 1
  ok(pairs >= 1, `S12e teeth: the retired placement overlaps ${pairs} caption pair(s) on the fourteen-stage map`)
}

/* ── S13. group maps: partner captions take part in the same contract ────── */

{
  const scene = SCENES[7][1]
  const partner = scene.labels.filter(l => l.track === 'partner')
  ok(partner.length === 2, `S13a the two parallel pairs each draw a partner caption (got ${partner.length})`)
  ok(partner.every(l => l.y >= LM_PARTNER_LABEL_Y), 'S13b partner captions stay below the partner track')
  ok(scene.windows.length === 2 && scene.bars.filter(b => b.track === 'partner').length === 2,
    'S13c the partner band and window faces are unchanged by the placement work')
}

console.log(`\nLANE_MAP_LABELS ran=${passed + failed} pass=${passed} fail=${failed}`)
process.exit(failed === 0 ? 0 : 1)
