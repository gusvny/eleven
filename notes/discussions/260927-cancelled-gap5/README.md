# 被取消的「缺口 5 直修」存档（260927）

**为什么在这里**：这份实现是宿主 260927 下令**取消**的 main 直修（原话「这个票对应的直修取消掉」），
因为同一缺口已由工单 `t260927-05` 的泳道接管并交付（main `021e838`）。取消时它的改动**未入库**，
只留在 gitignored 的 `out/` 下 ⇒ 清一次 `out/` 就没了。为了「证据可追溯、又不污染 main 的历史」，
把它原样挪进知识库存档（本目录），**不入代码树**。

## 内容
- `directfix-final.patch` —— 该直修在 main 上的最终改动（4 个已跟踪文件的补丁；`server/engine/client.py`、
  `server/engine/template_topology.py`、`server/tools/workflow.py`、`server/tools/ticket.py`）。
- `test_t260927_template_directory_face.py` / `project-template-lane-map.mjs` —— 它自带的两支新测试
  （引擎侧 9 例 / 前端 20 断言）。取消时从工作区删除，此处为存档副本。
- `MD5SUMS.txt` —— 三个文件的 md5（对账用）。

## 当时的核实（存档不承担结论）
据其自报与我的复核：`workflow.py op=list` 能列出 `content-studio`（8 段/8 节点）、
`ticket.py show t260926-04` 拓扑非空、引擎全量 2549 passed、lint 0/0。**但交付以 t260927-05 泳道为准**；
本存档只作「取消时手上的东西长什么样」的证据，不构成采纳建议。

## 提醒（260927 当天立的纪律）
main 上同一写集只能有一个写者。当天的教训：这条直修与泳道并行写同一批文件，被取消后它仍多次
自我复原（`/tmp/gap5/restore.sh`），与我的 `git restore` 拉锯四次 —— 后来在 tick 提醒词里补了
「主仓被外部写者弄脏→立刻还原并上报」与「他项目票只读」两条。
