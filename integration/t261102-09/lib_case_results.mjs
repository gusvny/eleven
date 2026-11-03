// lib_case_results.mjs — the three-state result contract for this ticket's cases
// (non-sc_ prefix = shared code). Same shape the suite already uses:
//   pass / fail / env_fail / na counters, one SUMMARY line, exit 0/1/2.
// No SKIP state (integration/README.md, t260904-12): a missing environment is env_fail
// and exits 2, never a green.

export function makeResults() {
  const rows = []
  const rec = (state, name, detail) => {
    rows.push({ state, name, detail })
    const tag = state === 'pass' ? 'ok    ' : state === 'fail' ? 'FAIL  ' : state === 'env_fail' ? 'ENV   ' : 'N/A   '
    console.log(tag + name + (detail ? ' — ' + detail : ''))
  }
  return {
    rows,
    pass: (name, detail) => rec('pass', name, detail),
    fail: (name, detail) => rec('fail', name, detail),
    env: (name, detail) => rec('env_fail', name, detail),
    na: (name, detail) => rec('na', name, detail),
    check(cond, name, detail) {
      if (cond) rec('pass', name)
      else rec('fail', name, detail)
      return cond
    },
    summarize() {
      const count = (s) => rows.filter((r) => r.state === s).length
      const pass = count('pass')
      const fail = count('fail')
      const envFail = count('env_fail')
      const na = count('na')
      console.log(`SUMMARY pass=${pass} fail=${fail} env_fail=${envFail} na=${na}`)
      if (envFail > 0) process.exit(2)
      if (fail > 0) process.exit(1)
      // Every leg N/A is a product red: nothing was verified (no object is a design
      // problem, never a pass).
      if (pass === 0 && na > 0) {
        console.log('FAIL  every sub-case was N/A — no behaviour was verified')
        process.exit(1)
      }
      process.exit(0)
    },
  }
}
