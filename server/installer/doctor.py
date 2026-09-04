"""doctor：跑全量探针（fixture 缺省 / --live 可选档），绿一行 append 一行进兼容矩阵。

矩阵三轴（契约⑧-3）= sandbar 版本（仓根 VERSION）× dsh 已验证点（契约⑧-1）×
项目 schema 版本（契约⑧标题）。轴值取不到=ContractError/VersionError 红——
没有轴就不落矩阵，绝不猜。dsh 已验证点多于一个时必须 --dsh-point 指明本次
验证点（fail-closed，不替操作者认领未验证的点）。
"""

from __future__ import annotations

import os

from installer import matrix as matrix_mod
from installer import upgrade as upgrade_mod


def cmd_doctor(paths, log=print, live: bool = False, matrix_path=None,
               dsh_point=None) -> int:
    from probes import runner  # server/ 已在 sys.path（入口脚本注入）

    contract = upgrade_mod.load_contract(paths.root)
    points = contract["points"]
    if dsh_point is None:
        if len(points) != 1:
            raise upgrade_mod.ContractError(
                "⑧-1 已验证点多于一个（%s），必须 --dsh-point 指明本次验证点" % "、".join(points))
        dsh_point = points[0]
    elif dsh_point not in points:
        raise upgrade_mod.ContractError(
            "--dsh-point %s 不在⑧-1 已验证点清单（%s）——未列举=未验证，不认领"
            % (dsh_point, "、".join(points)))

    results = runner.run_all(live=live)
    # 第五面（t260904-02，KI-033 防再犯）：异仓引擎进程（僵尸）探测。真源=
    # installer/zombies.py（写集内自持，不动 server/probes/）。输入档与四面探针
    # 同构：SANDBAR_ZOMBIE_CENSUS 注入 > --live 真扫 > 缺省内嵌干净样本（绿行
    # 文案自辨档位，防「跑过 doctor 绿」被误读为「无僵尸」——review C2）。
    from probes import ProbeResult  # server/ 已在 sys.path（入口脚本注入）
    from installer import zombies as zombies_mod
    z_ok, z_detail = zombies_mod.probe(
        live=live, engine_root=paths.root,
        census_path=os.environ.get("SANDBAR_ZOMBIE_CENSUS") or None)
    results.append(ProbeResult(zombies_mod.NAME, z_ok, z_detail))
    for r in results:
        log(r.line())
    greens = [r for r in results if r.ok]

    import sys as _sys
    server_dir = str(paths.root / "server")
    if server_dir not in _sys.path:
        _sys.path.insert(0, server_dir)
    import version as _version
    ver = _version.sandbar_version()

    mpath = matrix_path if matrix_path is not None else (paths.home / "compat-matrix.json")
    for r in greens:
        appended, total = matrix_mod.append_row(
            mpath, probe=r.name, sandbar_version=ver,
            dsh_point=dsh_point, project_schema=contract["schema"])
        log("[矩阵] %s %s（%s，共 %d 行）"
            % ("append" if appended else "幂等跳过", r.name, mpath, total))
    if len(greens) < len(results):
        log("[红] %d/%d 探针红——红面不落矩阵（契约⑧-3：空格=未验证）"
            % (len(results) - len(greens), len(results)))
        return 1
    # 面数动态计数（review C2）：探针数已扩到 5，写死「四面」会撒谎。
    log("doctor 完成：%d/%d 面全绿，矩阵落 %s" % (len(greens), len(results), mpath))
    return 0
