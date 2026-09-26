/**
 * red-light-lexicon —— 红灯文案翻译层（表驱动，t260915-05，mock ② callout C）。
 *
 * 原则（mock 原话，改动前先读）：
 *   - 人话主文案必答三问：出了什么事 / 影响什么 / 接下来谁做什么；
 *   - 翻译层是表驱动：引擎术语→人话词条表；**UI 不能翻译它没拿到的信息**——
 *     红灯明细（文件清单/原因码/建议动作）只来自 blocked_detail 结构化字段；
 *   - 缺词条回落「原文＋原始日志」——永不显示空白或猜测文案（mock ④ 通用口径）。
 *
 * 表的 key 域=引擎 reason_code 词表（实现期清点，改引擎词表须同步此表）：
 *   ① merge 分类（KI-048，dev_lane.py merge 未收口分支）：
 *      main_staged / main_dirty / untracked_collision / merge_fault / conflict
 *   ② merge_check 检查项（agent_activities.merge_check 结构化清单）：
 *      no_commits / worktree_dirty / status_failed / merge_base_failed /
 *      verify_red / bundle_stale / ui_evidence_malformed
 *   ③ 段路径闸/受保护路径闸（path_gates.py）：
 *      unauthorized_path / protected_path / unknown_stage / write_set_missing /
 *      ui_dirs_missing / gate_refusal_unknown / gate_refusal_malformed
 *   ④ 人门（引擎状态词，非 reason_code）：awaiting-human
 *
 * 测试契约（验收口径②）：改表即改文案——用例只允许经本表取文案；删词条必须
 * 回落原文而不是空串/兜底句（status-card-ui.mjs / lane-map-model.mjs 断言）。
 */

export interface LexiconEntry {
  /** 人话主句（出了什么事）。 */
  headline: string
  /** 人话下一步（接下来谁做什么）；缺省=不提供（卡面回落引擎 next_action 或缺省出路）。 */
  next?: string
}

/** 引擎术语 → 人话词条表。改文案=改这张表（非硬编码）。 */
export const REASON_LEXICON: Record<string, LexiconEntry> = {
  /* ① merge 分类（KI-048） */
  main_staged: {
    headline: 'Merge blocked: the main worktree has staged but uncommitted changes (local-change protection, not a conflict)',
    next: 'Commit or stash (git stash) these changes in main, then send retry_qc to re-verify; the engine never auto-stashes or auto-commits',
  },
  main_dirty: {
    headline: 'Merge blocked: the main worktree has uncommitted changes (local-change protection, not a conflict)',
    next: 'Commit or stash (git stash) these changes in main, then send retry_qc to re-verify; the engine never auto-stashes or auto-commits',
  },
  untracked_collision: {
    headline: 'Merge blocked: untracked files in the main worktree collide with paths in this merge',
    next: 'Move the colliding files away or commit them, then send retry_qc to re-verify; the engine never auto-stashes or auto-commits',
  },
  merge_fault: {
    headline: 'Merge did not settle: the merge run hit a fault (not a conflict)',
    next: 'Handle it manually, then send retry_qc to re-verify',
  },
  conflict: {
    headline: 'Merge conflicts with main',
    next: 'Resolve the conflicting files, then send retry_qc to re-verify',
  },

  /* ② merge_check 检查项 */
  no_commits: {
    headline: 'Implementation not on disk yet: the lane branch has no commits',
    next: 'Send rework back to the implement stage to write results to disk',
  },
  worktree_dirty: {
    headline: 'Lane worktree is dirty: uncommitted changes',
    next: 'Commit or clean up inside the lane, then send retry_qc to re-verify',
  },
  status_failed: {
    headline: 'Failed to read git status (environment issue)',
    next: 'Check the lane repo, then send retry_qc to re-verify',
  },
  merge_base_failed: {
    headline: 'Lane merge-base failed (git environment issue)',
    next: 'Check the lane repo, then send retry_qc to re-verify',
  },
  verify_red: {
    headline: 'Lane self-check red: the change did not pass this ticket\'s verification',
    next: 'Fix the red items listed in the details, then send retry_qc to re-verify',
  },
  bundle_stale: {
    headline: 'Frontend build artifacts are stale: source and lib output are out of sync',
    next: 'Rebuild the artifacts in the lane (tsdown), then send retry_qc to re-verify',
  },
  ui_evidence_malformed: {
    headline: 'UI screenshot evidence missing or malformed (acceptance gate fallback)',
    next: 'Re-run UI screenshots (ui-check/capture-lane), then send retry_qc to re-verify',
  },

  /* ③ 段路径闸 / 受保护路径闸 */
  unauthorized_path: {
    headline: 'Change exceeds the scope this ticket declared (write-set violation)',
    next: 'Send rework back to the plan stage to declare the changed files, or move the out-of-scope files out of the commit',
  },
  protected_path: {
    headline: 'Change touches a protected path (a source of truth this ticket may not modify)',
    next: 'Move the change out of the protected path; if the change is really needed, go through the authorization channel (sign authorize)',
  },
  unknown_stage: {
    headline: 'Gate could not resolve the owning stage (config/version mismatch)',
    next: 'Check the template rule table, then send retry_qc to re-verify',
  },
  write_set_missing: {
    headline: 'Ticket declares no write set (no change list at filing time)',
    next: 'Send rework back to the plan stage to declare the change list',
  },
  ui_dirs_missing: {
    headline: 'UI screenshot directory missing (the gate cannot check the screenshot surface)',
    next: 'Re-run UI screenshots (ui-check/capture-lane), then send retry_qc to re-verify',
  },
  gate_refusal_unknown: {
    headline: 'Stage gate refused (reason code missing)',
    next: 'Check the worker log for this refusal, then handle it',
  },
  gate_refusal_malformed: {
    headline: 'Stage gate refusal receipt malformed (reason code unreadable)',
    next: 'Check the worker log for this refusal, then handle it',
  },

  /* ④ 人门（引擎状态词） */
  'awaiting-human': {
    headline: 'Waiting on your approval: the flow is parked at the human gate; the engine will not auto-advance',
  },
}

export interface TranslatedReason {
  /** 表内人话（fromTable=true）或回落原文（fromTable=false）。 */
  headline: string
  /** 表内下一步（表项有 next 才有）。 */
  next?: string
  /** true=词条表命中；false=回落原文（缺词条降级锚，卡面应可辨）。 */
  fromTable: boolean
}

/**
 * reason_code → 人话。表缺词条回落原文（宁显原文不显空白）；
 * 原文也没有 → 可辨的「原因码裸展示」（最后一道锚，仍不空白）。
 */
export function translateReason(code: unknown, fallbackText?: unknown): TranslatedReason {
  const c = typeof code === 'string' ? code.trim() : ''
  if (c) {
    const entry = REASON_LEXICON[c]
    if (entry) {
      return { headline: entry.headline, next: entry.next, fromTable: true }
    }
  }
  const fb = typeof fallbackText === 'string' ? fallbackText.trim() : ''
  if (fb) return { headline: fb, fromTable: false }
  if (c) return { headline: `Blocked (reason code ${c})`, fromTable: false }
  return { headline: 'Ticket blocked (engine gave no reason)', fromTable: false }
}
