#!/usr/bin/env node
/**
 * sc_metrics_v2_contract_doc_freeze.mjs — t261021-06 L2 (grey-box, offline seconds).
 *
 * intent (user-perceivable / consumer contract): the v2 contract is actually
 * frozen in the knowledge base before the data layer ships — every new field has
 * a written source of truth, formula, known approximation and degrade behaviour;
 * the failure-mode tradeoff list for the reused discovery/parser code is in the
 * doc (review discipline: reuse must carry the inherited failure-mode list);
 * the source_version↔document-version mapping is written down; v1 stays frozen
 * in place (never rewritten); and the "no money" verdict is on record.
 *
 * The contract document IS machine-consumed (schema-sync family precedent), so a
 * structural guard is legitimate here — it pins presence and section shape, not prose.
 *
 * Pre-implement red is the expected TDD signal; arbitrate/merge must be green.
 * Run: node integration/t261021-06/sc_metrics_v2_contract_doc_freeze.mjs (cwd=repo root)
 */
import { readFile } from 'node:fs/promises'
import { makeChecker } from './lib_metrics_v2.mjs'

const { ok, done } = makeChecker()
const V2 = 'docs/design/metrics-api-contract-v2.md'
const V1 = 'docs/design/metrics-api-contract-v1.md'

let v2 = null
try {
  v2 = await readFile(V2, 'utf8')
  ok(true, 'v2 contract document exists')
} catch {
  ok(false, 'v2 contract document exists', `${V2} not found (create_plan decision 1: new file, v1 untouched)`)
}

if (v2 !== null) {
  // C1 — every new field name appears in the doc.
  const fields = ['workflows', 'stage_runs', 'rounds_per_ticket', 'stages', 'avg_rounds_per_ticket',
    'project_sessions', 'rework_rate', 'throughput_per_day', 'median_lead_time', 'human_wait_share',
    'tokens_total', 'tokens_in_tickets', 'tokens_outside_tickets', 'tokens_per_closed_ticket', 'cache_hit',
    'epics', 'last_activity_ms']
  const missing = fields.filter((f) => !v2.includes(f))
  ok(missing.length === 0, `C1 all new field names documented (missing: ${missing.join(',') || 'none'})`, missing.join(','))

  // C2 — per-field discipline: the doc carries formula, approximation and degrade sections.
  ok(/formula|公式|= runs|ratio|share of/i.test(v2), 'C2 formulas written (formula sections / equations present)')
  ok(/approximat|近似/i.test(v2), 'C2 known approximations declared')
  ok(/degrade|降级/i.test(v2) && /null/i.test(v2) && /reason/i.test(v2), 'C2 degrade behaviour written as null + reason')
  ok(!/cost|price/i.test(v2.replace(/no cost[^\n]*|nongoal[^\n]*|there is no price table[^\n]*/gi, '')), 'C2 no cost field is ADDED (mentions only in the nongoal verdict)', '')

  // C3 — failure-mode tradeoff list for the reused code (review conditional C2).
  ok(/resolveAllSessionFiles|aggregateTicketUsage/.test(v2), 'C3 the reused functions are named as the reuse source')
  ok(/failure mode|故障模式|inherited|带入/i.test(v2), 'C3 an inherited failure-mode disposition list is present')

  // C4 — source_version ↔ document-version mapping (review conditional C1).
  ok(/source_version/i.test(v2) && /monotonic|v3|cache generation|缓存代/i.test(v2), 'C4 the source_version (v3) vs document (v2) mapping is written down')

  // C5 — v1 stays frozen: it still carries the no-rewrite rule and is referenced/superseded by v2.
  const v1 = await readFile(V1, 'utf8')
  ok(/must not be rewritten in place/.test(v1), 'C5 v1 untouched (freeze rule sentence still present)')
  ok(/metrics-api-contract-v1/.test(v2), 'C5 v2 references v1 (supersedes link, not an in-place rewrite)')
}

process.exit(done('sc_metrics_v2_contract_doc_freeze'))
