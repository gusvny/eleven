# develop-buffer 成本度量配方（261010 起草，integration 岗）

**为什么写**：`notes/epics/develop-buffer.md` 的判据 #1 是「**每票成本下降可测**：同一批票在新旧流下的
落地前耗时对比（不是感觉，是记录里的数）」。本文件只做一件事：**把"数"从哪读、怎么比、什么条件下比**写死，
免得测量那天大家各拿一个说法。**不含实现细节、不含进度。**

## 一、三个可读的数（全部来自票面/账本，不需要新代码）

| 数 | 来源 | 口径 |
|---|---|---|
| **每票的套件秒数** | 票面 `gate_phase_timings.suite_s` | 该票**落地前**那次闸轮里，全量套件占用的秒数（老流：每轮一次） |
| **每票落地前墙钟** | 票面 `created` → `close_ts` | 从建票到收口的墙钟（含所有等待与返工） |
| **每票的闸轮数** | timeline 里 `run_integration_tests` 的 `Entered step` 次数 | 老流**每轮都跑一次全量**，所以这个数就是"这票烧了几份证明" |

取数（只读，一条 Python 就是全部）：

```bash
PY=server/engine/.venv/bin/python
"$PY" server/tools/ticket.py '{"op":"list","project":"sandbar","caller_project":"sandbar"}' \
  | "$PY" -c 'import json,sys
d=json.load(sys.stdin)["result"]["tickets"]
for t in d:
    if t.get("status")!="closed": continue
    print("%-14s %-16s close-created=%6.0fs" % (t["id"], (t.get("epic") or "-")[:16],
          (t.get("close_ts") or 0) - (t.get("created") or 0)))'
# suite_s 与闸轮数在 op=show 的单票面上（逐票读；本岗用时逐张取）
```

## 二、对比口径（两条，主 + 副）

1. **主指标：每落地一次烧掉的"全量套件次数"**——这是"一份内容的重证明只做一次"的直接读数，
   也是**唯一跨新旧流同量纲**的数：
   - 老流（dev-lane 既有版本）：≈ `1 × 闸轮数`（每轮一次全量，含重跑）；
   - 新流（opt-in 到线的票）：**票面自身 ≈ 0**，成本转移到"线的轮"（每 tick 至多一次、且**一批内容共享**）。
   ⇒ 报告时写"**每次落地的全量跑次数**"，而不是"每票跑了几分钟"。
2. **副指标：落地前墙钟中位数**（同票型、同期、同台面宽度的两组对比）。

## 三、三条 caveat（不写清就会得出相反结论）

1. **并发会放大套件秒数**：全量套件跑在**一处共享的串行资源**上（epic 目标 5），同一时刻几条车道在跑，
   `suite_s` 会被拉长（本夜实测同一套件 8:44～9:00 不等）。⇒ ①两组样本要**同宽度**；②最好在**安静台子**上量
   （`ps -ax -o lstart=,command | grep run_scenarios.py` 无跑批）。
2. **新流的成本会"搬家"**：新流里票面 `suite_s` 变小甚至为 0，**不等于成本消失**——它搬到了"线的轮"上。
   ⇒ **只报票面数会把新流报成"零成本"**，所以主指标必须用"每次落地的全量跑次数"，并同时给出"线轮次数"。
3. **返工轮要把成本计入票**：老流里一次红就是一次全量重跑（本夜 `-55`/`-58` 各烧了两轮），
   这部分必须算进"老流每票成本"，否则对比会偏袒老流。

## 四、开工前的已知缺口（如实记，先解决再宣布"可测"）

- **run 账本的头记录是"按设计稀疏"的，不是坏的（261010 17:0x 复核，本岗先前判成缺口是错的）**：
  `~/.sandbar/projects/sandbar/ledger/scenario-runs.jsonl` 只有 **1 行**（`source=inspection`），而同一目录的
  `scenario-results.jsonl` **行里带 run id**（尾部 6 万行里有 **203 个不同 run**、来源 `lane:<票>`）。
  读码确认这是**明文的具名规则**，不是漏写：`integration/run_scenarios.py` 的
  `run_record_skip_reason` 逐条点名——**"窄轮（`--only`／池排除）不是证明 ⇒ 不落头记录，但行保留 run id 让分组仍可见"**、
  **"gate-owned 轮由 gate 写"**（`SANDBAR_INTEG_LEDGER_OWNER=gate`，免得一轮两个头）、以及
  "source/commit/env_fp 推不出来就跳过"。⇒ **口径结论不变、理由要改**：
  **"每次落地的全量跑次数"不能指望头记录**（车道的闸轮多为窄轮），要么**按 run id 分组数**（行里有），
  要么**数票面 timeline 的 `run_integration_tests` attempt**——量之前先把这两条选一条写进本文件，
  不许量的时候临时改口径。
- **新流样本还没有**：`-46`（新泳道版本的 opt-in 与落地通路）是开关；**它落地 + 第一张 opt-in 票走完**之前，
  新流那一组是空的。⇒ 本文件和 epic 判据 #1 都**只在有第一张 opt-in 票之后**才可宣布"可测"。
