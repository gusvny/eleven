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
    headline: '合并被挡：main 工作区有已暂存未提交的改动（本地改动保护，不是冲突）',
    next: '在 main 提交或暂存（git stash）这些改动，然后发 retry_qc 重验；引擎绝不自动 stash/提交',
  },
  main_dirty: {
    headline: '合并被挡：main 工作区有未提交的改动（本地改动保护，不是冲突）',
    next: '在 main 提交或暂存（git stash）这些改动，然后发 retry_qc 重验；引擎绝不自动 stash/提交',
  },
  untracked_collision: {
    headline: '合并被挡：main 工作区有未跟踪文件与本次合并路径相撞',
    next: '把相撞文件移走或提交，然后发 retry_qc 重验；引擎绝不自动 stash/提交',
  },
  merge_fault: {
    headline: '合并没有收口：合并执行出现故障（不是冲突）',
    next: '人工处置后发 retry_qc 重验',
  },
  conflict: {
    headline: '合并与 main 有冲突',
    next: '按冲突文件清单消解后发 retry_qc 重验',
  },

  /* ② merge_check 检查项 */
  no_commits: {
    headline: '实现还没落盘：泳道分支还没有提交',
    next: '发 rework 回实现段补落盘',
  },
  worktree_dirty: {
    headline: '泳道工作区不干净：有未提交的改动',
    next: '泳道内提交或清理后发 retry_qc 重验',
  },
  status_failed: {
    headline: 'git 状态读取失败（环境类）',
    next: '排查泳道仓后发 retry_qc 重验',
  },
  merge_base_failed: {
    headline: '泳道 merge-base 失败（git 环境类）',
    next: '排查泳道仓后发 retry_qc 重验',
  },
  verify_red: {
    headline: '泳道自检红灯：改动未通过本票验证',
    next: '按明细里的红灯项修复后发 retry_qc 重验',
  },
  bundle_stale: {
    headline: '前端构建产物过期：源码与 lib 产物不同步',
    next: '泳道内重建产物（tsdown）后发 retry_qc 重验',
  },
  ui_evidence_malformed: {
    headline: 'UI 截图证据缺失或畸形（验收闸兜底）',
    next: '重跑 UI 截图（ui-check/capture-lane）后发 retry_qc 重验',
  },

  /* ③ 段路径闸 / 受保护路径闸 */
  unauthorized_path: {
    headline: '改动超出本票声明的范围（写集越界）',
    next: '返工回方案段补报改动清单，或把越界文件移出提交',
  },
  protected_path: {
    headline: '改动碰到受保护路径（本票无权改的真源）',
    next: '把改动移出受保护路径；确需改动走授权通道（sign authorize）',
  },
  unknown_stage: {
    headline: '闸判定找不到所属段（配置/版本错位）',
    next: '排查模板规则表后发 retry_qc 重验',
  },
  write_set_missing: {
    headline: '工单没有声明写集（开票缺改动清单）',
    next: '返工回方案段补报改动清单',
  },
  ui_dirs_missing: {
    headline: 'UI 截图目录缺失（闸无法核对截图面）',
    next: '重跑 UI 截图（ui-check/capture-lane）后发 retry_qc 重验',
  },
  gate_refusal_unknown: {
    headline: '段闸拒绝（原因码缺失）',
    next: '按 worker 日志核对该拒绝原因后处置',
  },
  gate_refusal_malformed: {
    headline: '段闸拒绝回执畸形（原因码不可读）',
    next: '按 worker 日志核对该拒绝原因后处置',
  },

  /* ④ 人门（引擎状态词） */
  'awaiting-human': {
    headline: '等你审批：流程停在人门，引擎不会自动过',
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
  if (c) return { headline: `受阻（原因码 ${c}）`, fromTable: false }
  return { headline: '工单受阻（引擎未给原因）', fromTable: false }
}
