fixtures/ —— t260905-09 叠台场景族固定桩样本（非 sc_ 前缀=数据文件，不登记 SCENARIOS）。

取证来源声明：平台自启上下文注入源在宿主二进制（仓内 grep「Current runtime
context」「Instructions from」零命中），本目录文本按宿主 260906 实报
（notes/queued-fold-platform-context-ticket.json）+ 真控制台新会话实文取证措辞
固定；每文件 `%%%` 尾注=逐文件取证来源（sc_platform_context_anchor_contract
S4 子用例强制在文）。平台改措辞=ro 冻结场景红 → 人审同步本目录与
src/client/platform-context-anchors.ts 锚清单，不静默。

| 文件 | 用途 |
|---|---|
| fx-01-runtime-context.txt | 锚 runtime-context-snapshot（平台 runtime 快照首句）——叠台注入子用例 |
| fx-02-instructions-claude-md.txt | 锚 instructions-from + claude-md-heading **同气泡双锚**（去重按气泡身份用例）——叠台注入子用例 |
| fx-03-workspace-instructions.txt | 锚 runtime-context-preamble（workspace instructions wrapper 开场句）——叠台注入子用例 |
| fx-04-dsh-file-policy.txt | 锚 dsh-file-policy（文件沙箱策略行）——ro 契约样本 |
| fx-05-claude-md-heading.txt | 锚 claude-md-heading（项目侧内容锚，更名=漂移人审）——ro 契约样本 |
| fx-91-user-mid-mention.txt | 负向：普通用户消息，锚字样仅中段出现，绝不折叠（browser T3 负向子用例） |
| fx-92-user-paste-prefix.txt | 声明性用例：用户粘贴恰好以锚行开头=命中即折（设计内不可分辨限制，browser T2 断言其折叠、防后人当缺陷修） |
