# t260912-02 验收入口（机械口径 A–G）

本目录是工单 t260912-02（测试台三修）的票内验收脚本。**B 的判据已等强并入常跑
套件**（sc_stage_docker_parallel_zero_residue 的受管网段腿），本目录只作 A/D/E/F/G
（+C 的注入式全形态）机械入口；所有脚本三态诚实：docker 缺席=ENV_FAIL exit 2。

| 口径 | 入口 | 判据要点 |
| --- | --- | --- |
| A+B | `python3 integration/t260912-02/acc_ab_burst.py` | 并发 32×dsh 32/32、墙钟 ≤60s；48×temporal 无非环境失败；`fully subnetted` 在输出与 docker events 双零；逐台网络子网 ∈ 受管网段表；打印实际发起数对账、boot 清扫耗时行、容器出网探针记录行 |
| C | `python3 integration/t260912-02/acc_c_residue.py` | 注入三残台形态（真 compose 台+真锁根租约）全拆（容器+网络+卷）逐条点名；α/β 对照 + γ=C4b 负锁（活台+目录在+非工作树）只报告不拆 |
| D | `python3 integration/t260912-02/acc_d_sweep_cost.py` | 空扫 ≤5s；生产锁根 `--dry-run` 逐条分类落证据（C4a）；坏 compose shim 下清理失败非零上抛、原文可见、租约保留不静默 |
| E | `python3 integration/t260912-02/acc_e_fuse.py` | 缺省保险丝=100 显式断言；200 路失控样本（MAX_STAGES=4 代理）刹停 196 路逐条点名、损害有界（容器≤4、零租约零孤儿 hold） |
| F | `python3 integration/t260912-02/acc_f_capacity.py` | 6 条常驻租约在场时 16/16 绿；负锁腿：压回旧缺省 12 → 恰 6 入位 10 路刹停（证明旧闸自我挤压、新缺省不挤） |
| G | `python3 integration/t260912-02/acc_g_cleanup.py` | 网络/可用槽回落基线、本票零残留、3099/7233 监听 pid 全程一致 |

实现面改动：integration/stage_docker.py（保险丝/清扫/受管网段）、
server/docker-compose.test.yml（default 网络显式子网，尾槽保留给手工直跑）。
常跑回归网：integration/tests/test_stage_lease.py（33 例）、
integration/tests/test_stage_docker.py（24 例，多泳道宿主跑法见
SANDBAR_STAGE_BAND_BASE / SANDBAR_STAGE_LOCK_DIR 两旋钮，integration/README.md）。
