# installer 包：sandbar 安装器（M2-C 代码票）。
"""sandbar 安装器实现包。

入口在仓根 `sandbar` 薄壳脚本（python3 标准库实现，无第三方依赖）；
本包承载 init/up/down/status/doctor/upgrade 六子命令的全部逻辑。

管辖面纪律（CLAUDE.md 硬规则 1 + 交接单 §2/§4）：
- 管辖：temporal dev server（7233/8233）与工单 worker 的生命周期；
- 不碰：console（3099）只 TCP 探测、只提示，任何代码路径不执行
  启停动词（源码级静态断言由 integration/baselines/sc_sandbar_installer_console_line.py 守）。
"""
