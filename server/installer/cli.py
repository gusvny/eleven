"""sandbar CLI 参数面：init/up/down/status/doctor/upgrade/project。

出口码：0=绿；1=红（FailClosed/VersionError/ContractError，显式报错）；
2=用法错。管辖面=7233/8233 与工单 worker；3099 只探测只提示（硬规则 1）。
project 子命令族=add|remove|list（注册表接入面，project-lifecycle 票①；
remove 属票②只挂点位）。
"""

from __future__ import annotations

import argparse

from installer import doctor as doctor_mod
from installer import projects as projects_mod
from installer import runtime
from installer import service
from installer import upgrade as upgrade_mod
from installer.runtime import InstallPaths
from installer.service import FailClosed


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="sandbar",
        description="sandbar 安装器：管 temporal dev server（7233/8233）与工单 worker；"
                    "console（3099）永属用户操作面，本工具只探测只提示")
    p.add_argument("--home", default=None, help="状态家目录（缺省 ~/.sandbar，或 $SANDBAR_HOME）")
    p.add_argument("--root", default=None, help="仓根（缺省=自动定位）")
    p.add_argument("--server-port", type=int, default=7233)
    p.add_argument("--ui-port", type=int, default=8233)
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("init", help="初始化 run 目录+工具面检查")
    up = sub.add_parser("up", help="幂等拉起 server+worker")
    up.add_argument("--skip-worker", action="store_true")
    dn = sub.add_parser("down", help="停 worker→停 server（先 worker 后 server）")
    dn.add_argument("--term-timeout", type=float, default=runtime.DOWN_TERM_TIMEOUT)
    st = sub.add_parser("status", help="人读状态（--json 机器口径）")
    st.add_argument("--json", action="store_true")
    dc = sub.add_parser("doctor", help="跑全量兼容探针+落矩阵")
    dc.add_argument("--live", action="store_true", help="真环境档（需 DSH_* 指路；缺省 fixture）")
    dc.add_argument("--matrix", default=None, help="矩阵落盘路径（缺省 ~/.sandbar/compat-matrix.json）")
    dc.add_argument("--dsh-point", default=None, help="⑧-1 多点时指明本次验证点")
    ug = sub.add_parser("upgrade", help="契约⑧区间展示+升版预检（只读演练）")
    ug.add_argument("--to", default=None, help="目标 semver（坏 semver/降版本=红）")
    ug.add_argument("--dry-run", action="store_true", help="只读演练（本命令恒为只读）")
    ug.add_argument("--contract", default=None, help="契约副本路径（缺省仓内同源副本）")
    proj = sub.add_parser("project", help="项目注册表接入面：add 注册 / list 全列 / remove 摘除（票②）")
    psub = proj.add_subparsers(dest="project_cmd", required=True)
    pa = psub.add_parser("add", help="注册新项目：fail-closed 校验+原子写+体检报告（黄牌不阻塞）")
    pa.add_argument("--key", required=True,
                    help="项目 key（小写字母/数字/中划线，^[a-z0-9][a-z0-9-]{0,40}$）")
    pa.add_argument("--name", required=True, help="项目显示名（不含 # 与换行）")
    pa.add_argument("--dir", action="append", required=True,
                    help="项目根目录（恰给一个：绝对路径、真实存在；单根模型，多给=拒收）")
    pa.add_argument("--json", action="store_true", help="机器口径输出")
    pr = psub.add_parser("remove", help="摘除项目（票②交付，本版恒红占位）")
    pr.add_argument("--key", required=True, help="要摘除的项目 key")
    pr.add_argument("--json", action="store_true", help="机器口径输出")
    pl = psub.add_parser("list", help="列注册+隔离条目与票计数（Temporal 不可达降级不红）")
    pl.add_argument("--json", action="store_true", help="机器口径输出")
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    paths = InstallPaths(root=args.root, home=args.home,
                         server_port=args.server_port, ui_port=args.ui_port)
    log = print
    try:
        if args.cmd == "init":
            return service.cmd_init(paths, log)
        if args.cmd == "up":
            return service.cmd_up(paths, log, skip_worker=args.skip_worker)
        if args.cmd == "down":
            return service.cmd_down(paths, log, term_timeout=args.term_timeout)
        if args.cmd == "status":
            return service.cmd_status(paths, log, as_json=args.json)
        if args.cmd == "doctor":
            return doctor_mod.cmd_doctor(paths, log, live=args.live,
                                         matrix_path=args.matrix,
                                         dsh_point=args.dsh_point)
        if args.cmd == "upgrade":
            return cmd_upgrade(paths, args, log)
        if args.cmd == "project":
            if args.project_cmd == "add":
                return projects_mod.cmd_project_add(paths, args, log)
            if args.project_cmd == "remove":
                return projects_mod.cmd_project_remove(paths, args, log)
            if args.project_cmd == "list":
                return projects_mod.cmd_project_list(paths, args, log)
    except (FailClosed,) as e:
        log("[红] %s" % e)
        return 1
    except upgrade_mod.ContractError as e:
        log("[红] %s" % e)
        return 1
    except Exception as e:  # 未预期异常也显式红，不裸栈糊脸
        log("[红] 未预期异常：%s: %s" % (type(e).__name__, e))
        return 1
    return 2


def cmd_upgrade(paths, args, log) -> int:
    from version import VersionError, read_version
    contract = upgrade_mod.load_contract(paths.root, path=args.contract)
    current = read_version()
    target = args.to
    if target is not None:
        upgrade_mod.precheck(target, paths.root)  # 坏 semver/降版本=VersionError 红
    for ln in upgrade_mod.render_report(contract, current, target=target):
        log(ln)
    return 0
