# t260910-08 场景 implement 段修订说明（developer 对并行子用例 sc_t260910_08 的协同修订）

本文件=同票并行分叉（implement∥design_integration_tests）的接力记录：implement 段对
场景文件 `sc_t260910_08_lane_materialization.py` 与 `run_scenarios.py` 登记行做了下列
修订。每条附实证，供汇合/arbitrate 复核；如 design_integration_tests 子用例对本文件有
后续改动，以磁盘最新版为准，但下述事实性结论不受版本影响。

## 修订清单（全部为「断言面打在真实现」的修正，无功能取舍）

1. **泳道目录派生名**（T3/T5/T6/T7 子用例）：`.lane/<票号>` → `shared.default_lane_paths`
   派生名（票号 `t26091008lm` → 泳道目录 `t260910-08lm`）。原稿手写票号路径与 create
   实际落点不等=四件套磁盘断言永久假红（disk_ready 永不成立）。
2. **T3b/T3c 期望值**：硬编码 `lane/<票号>-root/repo_a` → `shared.build_repo_worktrees`
   单点派生的 branch/三元组（与创建链同源，含 macOS /var→/private/var 已由 resolve
   对齐）。
3. **T3d/T4 根树条目比对**：`member_repos(...) == ["", "repo_a"]` → 新增 `repo_seq`
   （有序、含空串根树条目）比对派生明细。member_repos 会滤掉空串 repo（根树），混合
   形态对照恒假红。
4. **T6 子用例（类型毁形）事实修正**（附实证）：原稿断言「start 即拒（编码层）、Temporal
   无此 workflow」与本仓 temporalio 实测不符——
   - 实测（server/engine/.venv，t260910-08 会话）：
     `payload_converter.to_payloads([TicketInput(repo_worktrees=[42])])` 成功（编码面
     不带 type_hints 不设防）；`from_payloads(..., type_hints=[TicketInput])` 抛
     `TypeError: Failed converting field repo_worktrees on dataclass`（校验在 decode
     侧）。t260910-13 实案记录（worker log "Failed converting field workspace"）同款。
   - 真链行为=start 受理（probe found=True、payload 原样过线）→ worker 解码拒 →
     **workflow 代码永不执行** → 无物化、无 workspace_prep、磁盘零落仓。
   - T6 改为四子用例：T6a start 受理（started=True）；T6b 新拉专属 worker 后日志出现
     "Failed converting"（解码面拒收实锤）；T6c probe 断 payload 原样 `[42]`（无静默
     清洗）；T6d 泳道目录不存在（磁盘零落仓）。「不物化、不静默、可见 fail-closed」的
     分层意图不变，锚点移到真实现。
5. **登记行同步**（run_scenarios.py t260910-08 条目）：类型毁形措辞按第 4 条修正。
6. （并行子用例自身已修，此处记录确认）PROBE_SRC 尾行括号失衡已修（语法可编译）。

## 验证口径

- `python3 -c "import ast; ast.parse(open(...sc_t260910_08...).read())"` ✓
- `python3 integration/lint_tests.py` → 0 error / 0 warn（L4/L5 登记铁律过）✓
- 台面子用例实跑：隔离台（docker test-temporal）一次性 namespace 全部子用例跑，结果见工单
  implement 段结果文件 evidence（ENV_FAIL=台缺席口径，accept 段由 integration 复跑把关）。
