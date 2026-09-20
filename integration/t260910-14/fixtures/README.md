# 负向重放夹具（子用例三）生成程序——integration 在 acceptance 段执行（一次性）

目标：拿到一份**含 prepare_epic_next / suggest_next 活动命令**的旧形态 dev-lane history
JSON（`temporal workflow show -o json` 形状，replay_check --history 可消费），
落为本目录 `history_with_suggest_next.json`（连同本 README 提交）。

退役后代码无法再生这种 history（活动已删），两条生成路：

## 路①（首选，零生产接触）：退役前代码 × docker 测试台 × SUGGEST_STUB 桩
1. 取退役前代码：`git worktree add /tmp/pre-retire <implement 首个退役 commit 之父>`
   （须含 dev_lane 的 SUGGEST_NEXT_PATCH_ID 分支与 SANDBAR_SUGGEST_STUB 桩，shared.py:1838 族）；
2. `python3 integration/stage_docker.py ensure --project t26091014-fix --keep`；
3. 在 /tmp/pre-retire 的引擎代码上对测试台 spawn worker（SANDBAR_TARGET_HOST/NAMESPACE 指测试台，
   SANDBAR_SUGGEST_STUB=1 桩建议会话），开带 epic 的 dev-lane 票，走查到 merge 签字
   （client.py sign gate=merge decision=approve）→ 桩跑完 suggestion → 票 closed；
4. 导出：`temporal --address <台> --namespace <ns> workflow show --workflow-id <tid> -o json`
   > integration/t260910-14/fixtures/history_with_suggest_next.json；
5. 自证导出件含 suggestion 命令：grep 'prepare_epic_next\|EVENT_TYPE_ACTIVITY_TASK_SCHEDULED'
   且 activity 名含 suggest/prepare_epic（缺失=导错票，重来）。

## 路②（备选）：生产 t260910-06/09/10 只读导出
COMPLETED 票永不重放，导出纯读（replay_check 同级只读口径）：
`temporal --address $SANDBAR_TARGET_HOST --namespace $SANDBAR_NAMESPACE workflow show ...`。
择看板空闲窗（宿主令⑤精神），不与任何在飞操作并发。

## 夹具消费语义（场景③子用例三）
退役后代码回放该 history **必须响亮红**（活动命令序分歧）=「含 suggestion 命令 history
与删除后代码不可重放」边界 + drain 必要性的机械证据。夹具是静态语料（非现状 pin），
未来删除票亦不使其失效。
