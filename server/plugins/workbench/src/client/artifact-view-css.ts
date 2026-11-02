/**
 * artifact-view-css.ts — the six views' stylesheet (epic artifact-face, slice 3,
 * ticket t261030-36). A `.ts` module on purpose: every color is a theme token with a hex
 * fallback, and the L2 battery imports this string to check the token discipline without
 * a browser or a `.tsx` loader.
 */

/** Every color is a theme token with a hex fallback (the palette gates read this form). */
export const ARTIFACT_VIEW_CSS = `
.wb-av{margin-top:6px;padding-top:6px;border-top:1px dashed var(--dsw-derive-border,#d0d7de);font-size:12px;color:var(--dsw-derive-fg,#1f2328)}
.wb-av-body{display:flex;flex-direction:column;gap:4px}
.wb-av-toggle,.wb-av-retry,.wb-av-thumb{font:inherit;color:var(--dsw-derive-accent,#0969da);background:none;border:0;padding:0;cursor:pointer;text-align:left}
.wb-av-thumb{padding:0;border:0;background:none}
.wb-av-state{color:var(--dsw-derive-warn-deep,#7d4e00)}
.wb-av-note{color:var(--dsw-derive-muted,#57606a)}
.wb-av-meta{color:var(--dsw-derive-muted,#57606a)}
.wb-av-source{font-family:ui-monospace,monospace;font-size:11px;word-break:break-all}
.wb-av-strong{font-weight:600}
.wb-av-img{display:block;max-width:100%;max-height:240px;border:1px solid var(--dsw-derive-border,#d0d7de);border-radius:6px;background:var(--dsw-derive-surface,#f6f8fa)}
.wb-av-pre{margin:0;padding:6px 8px;max-height:320px;overflow:auto;white-space:pre-wrap;word-break:break-word;
  font-family:ui-monospace,monospace;font-size:11px;background:var(--dsw-derive-surface,#f6f8fa);
  border:1px solid var(--dsw-derive-border,#d0d7de);border-radius:6px}
.wb-av-table{width:100%;border-collapse:collapse;font-size:11px}
.wb-av-table th,.wb-av-table td{border:1px solid var(--dsw-derive-border,#d0d7de);padding:2px 5px;text-align:left;vertical-align:top}
.wb-av-table th{background:var(--dsw-derive-surface,#f6f8fa);font-weight:600}
.wb-av-tree{margin:0;padding-left:14px;list-style:none}
.wb-av-tree li{margin:1px 0}
.wb-av-key{font-family:ui-monospace,monospace}
.wb-av-val{font-family:ui-monospace,monospace;color:var(--dsw-derive-fg,#1f2328)}
.wb-av-file{margin-top:4px}
.wb-av-file-head{display:flex;gap:8px;align-items:baseline}
.wb-av-hunk{margin-top:2px;border:1px solid var(--dsw-derive-border,#d0d7de);border-radius:6px;overflow:hidden}
.wb-av-hunk-head{padding:2px 6px;font-family:ui-monospace,monospace;font-size:10px;color:var(--dsw-derive-muted,#57606a);background:var(--dsw-derive-surface,#f6f8fa)}
.wb-av-dline{display:flex;gap:6px;padding:0 6px;font-family:ui-monospace,monospace;font-size:11px;white-space:pre-wrap;word-break:break-word}
.wb-av-dline[data-kind=added]{background:var(--dsw-derive-success-bg,#dafbe1);color:var(--dsw-derive-success-deep,#116329)}
.wb-av-dline[data-kind=removed]{background:var(--dsw-derive-danger-bg,#ffebe9);color:var(--dsw-derive-danger-solid,#d1242f)}
.wb-av-ln{min-width:2.5em;text-align:right;color:var(--dsw-derive-muted,#57606a)}
.wb-av-mark{min-width:1em}
.wb-av-run{margin-top:6px}
.wb-av-run-head{display:flex;flex-wrap:wrap;gap:8px;align-items:baseline}
.wb-av-verdict{font-weight:600}
.wb-av-verdict[data-verdict=green]{color:var(--dsw-derive-success,#1a7f37)}
.wb-av-verdict[data-verdict=red]{color:var(--dsw-derive-danger,#cf222e)}
.wb-av-verdict[data-verdict=none]{color:var(--dsw-derive-muted,#57606a)}
.wb-av-counts{color:var(--dsw-derive-muted,#57606a)}
.wb-av-entry{display:flex;flex-wrap:wrap;gap:6px;align-items:baseline;padding:1px 0}
.wb-av-dot{width:8px;height:8px;border-radius:50%;display:inline-block;flex:0 0 auto}
.wb-av-dot[data-color=green]{background:var(--dsw-derive-success,#1a7f37)}
.wb-av-dot[data-color=red]{background:var(--dsw-derive-danger,#cf222e)}
.wb-av-dot[data-color=neutral]{background:var(--dsw-derive-muted,#57606a)}
.wb-av-tag{font-size:10px;color:var(--dsw-derive-muted,#57606a);border:1px solid var(--dsw-derive-border,#d0d7de);border-radius:5px;padding:0 4px}
.wb-av-action{color:var(--dsw-derive-accent,#0969da)}
`
