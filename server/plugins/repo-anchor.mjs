// Anchor discipline for the sandbar plugin family (t261008-33).
//
// Single shared resolver for the repo anchor chain
//   config.repo -> SANDBAR_REPO -> location-derived
// plus the escape guard: a process whose OWN tree is a git linked worktree
// (its `.git` is a gitfile, not a directory) is lane work; for such a process an
// explicit anchor that resolves outside its own tree is a NAMED failure
// (`SANDBAR_ANCHOR_MISMATCH`) thrown BEFORE any write. A standalone checkout
// (`.git` is a directory: the main checkout, an external deployed copy) keeps
// honouring config.repo / SANDBAR_REPO exactly as documented in server/README.md
// — the escape hatch's purpose is preserved, the resolution ORDER is unchanged.
//
// The own tree is derived from THIS module's own file location, never from the
// anchor being validated (a wrong anchor must not pick the `.git` the guard
// inspects). Both sides are realpath-normalized before equality (macOS
// /var vs /private/var, symlinked checkouts), so the legitimate
// `config.repo == lane root` pass case cannot false-fail.
//
// Decision-parity: this module mirrors engine/shared.anchor_guard_error (Python)
// row for row; server/engine/tests/test_t261008_33_anchor_discipline.py pins the
// two to identical verdicts via a shared decision table.
import { realpathSync, statSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

/** This module lives at <repo>/server/plugins/repo-anchor.mjs — TWO levels up is
 * the repo root. Rework (t261008-33 gen3, arbitration code-fault): the previous
 * one-level derivation resolved to <repo>/server, which (a) disarmed the guard
 * everywhere — isLinkedWorktree(<repo>/server) is false for every lane process,
 * the ticket's forbidden silence — and (b) mis-anchored the location-derived
 * branch at <repo>/server. */
export const OWN_ROOT = join(dirname(fileURLToPath(import.meta.url)), '..', '..')

export function isLinkedWorktree(root) {
  try {
    return statSync(join(root, '.git')).isFile()
  } catch {
    return false
  }
}

function normalized(p) {
  try {
    return realpathSync(p)
  } catch {
    // nonexistent / unreachable path: fall back to lexical resolution so the
    // guard can still name the mismatch instead of crashing on realpath
    return p
  }
}

/** Resolution order, unchanged: config.repo -> env SANDBAR_REPO -> location-derived.
 * The location branch defaults to THIS module's own tree (OWN_ROOT); a consumer may
 * pass its own location-derived default (DEFAULT_REPO) — same tree by layout. */
export function resolveRepoAnchor(configRepo, locationDefault = OWN_ROOT) {
  if (configRepo) return { repo: String(configRepo), anchorSource: 'config.repo' }
  if (process.env.SANDBAR_REPO) return { repo: process.env.SANDBAR_REPO, anchorSource: 'env SANDBAR_REPO' }
  return { repo: locationDefault, anchorSource: 'location-derived' }
}

/** Pure verdict, mirroring engine/shared.anchor_guard_error. Returns null (pass) or the named error.
 * Scope (rework t261008-33 gen6): the guard covers the ENV-SOURCED anchor only —
 * the 261008 incident class is an anchor INHERITED across a process boundary.
 * `config.repo` is an explicit, in-code choice by the process owner (the
 * documented primary seam); a deliberate foreign config.repo anchor is exactly
 * the external-caller / fixture face the ticket orders preserved (outcome 3),
 * so it passes the guard like the escape hatch does. Location-derived is the
 * normal state and always passes. */
export function anchorGuardError(repo, anchorSource, ownRoot = OWN_ROOT) {
  if (!repo || anchorSource === 'location-derived' || anchorSource === 'config.repo') return null
  if (!isLinkedWorktree(ownRoot)) return null
  let a, o
  try {
    a = normalized(String(repo))
    o = normalized(String(ownRoot))
  } catch (e) {
    return 'SANDBAR_ANCHOR_MISMATCH: anchor ' + JSON.stringify(String(repo)) +
      ' (src=' + anchorSource + ') unresolvable against own root ' +
      JSON.stringify(String(ownRoot)) + ' (src=this module\'s own file location): ' + (e && e.message)
  }
  if (a === o) return null
  return 'SANDBAR_ANCHOR_MISMATCH: anchor ' + JSON.stringify(a) + ' (src=' + anchorSource +
    ') points outside this process\'s own tree ' + JSON.stringify(o) +
    ' (src=this module\'s own file location; lane worktree); refusing to write into ' +
    'another checkout. Set the anchor to the lane root or unset it.'
}

/** Throwing face of the guard (consumers and the L3 scenarios call this): raises a
 * named SANDBAR_ANCHOR_MISMATCH error BEFORE any write when the verdict is a mismatch. */
export function assertAnchorOwnTree(repo, anchorSource, ownRoot = OWN_ROOT) {
  const err = anchorGuardError(repo, anchorSource, ownRoot)
  if (err) {
    const e = new Error(err)
    e.name = 'SANDBAR_ANCHOR_MISMATCH'
    throw e
  }
}

/** Resolver every consumer calls at apply/startup, before its first write. Throws the named guard error. */
export function resolveRepo(configRepo, locationDefault) {
  const { repo, anchorSource } = resolveRepoAnchor(configRepo, locationDefault)
  assertAnchorOwnTree(repo, anchorSource)
  return repo
}
