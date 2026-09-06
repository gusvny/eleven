"""容器层最小脚手架（t260906-01）：`sandbar project add` 代建新根目录时落的一套
开箱即用骨架。容器式定稿（项目=容器、repo=成员）：只建目录骨架与配置，**全程
零 git 操作**（不 init、不 clone——容器未含 git 仓库，开工单前需建/clone repo，
接入报告有提示；多 repo 支持与工单泳道挂靠改造另行立项=票B）。

口径：
- 只对**本次代建的新根目录**落（created_root=True）；接入已存在目录零覆盖零新增。
- 生成物：CLAUDE.md 骨架、notes/epics/.gitkeep、notes/discussions/.gitkeep、
  docs/.gitkeep、server/dsh/model-routes.yaml（引擎仓默认表逐字节拷贝，真源唯一
  不内嵌副本）。
- 源表三态（R2）：缺失（含 installer 脱离仓布局致源路径失效）与畸形（烂表）
  = fail-closed 红，点名源路径，绝不吞成空拷贝；调用方负责全量回滚。
- 零覆盖：任一目标已存在=跳过并记账（防御性；新目录本不该有东西），不报红。
- 本模块 stdlib-only（installer 惯例），由 projects.add 调用，失败回滚链在调用方。
"""

from __future__ import annotations

import pathlib
import shutil

from installer.service import FailClosed

# 引擎仓路由默认表（模板真源）：paths.root 下的同族路径——与 ui/node.ts 的
# routes init 端点、既有运行时查表回落路径同一份文件，三处同源不造两份。
TEMPLATE_ROUTES_REL = pathlib.Path("server") / "dsh" / "model-routes.yaml"

# 源表最低结构自检锚：缺任一锚=畸形（真源表必有 default 与 roles 两节）。
_TEMPLATE_ANCHORS = (b"default:", b"roles:")

CLAUDE_MD_SKELETON = """# <项目名> —— 项目交接入口

> 本文件由 `sandbar project add` 接入时生成的容器骨架（t260906-01 容器式定稿：
> 项目=容器、repo=成员）。它是接力交接总入口：新 agent / 新协作面先读本文件。

## 目录约定
- notes/epics/：立项单（epic 档案）。
- notes/discussions/：过程性讨论与立项笔记。
- docs/：项目定稿知识库（建议索引 = docs/README.md）。
- server/dsh/model-routes.yaml：模型路由表（声明式，工单 agent 查表用；
  改表走工单+人审，详见文件头注释）。

## 硬规则
- （项目自备：把本项目不可破的纪律写在这里。）

## 工单前须知
- 本容器当前**未含 git 仓库**：开工单前先建/clone repo（多 repo 支持与工单
  泳道挂靠改造另行立项=票B）。
"""


def _source_table_bytes(root: pathlib.Path) -> bytes:
    """读引擎仓默认表真源；缺失/不可读/畸形（缺结构锚）= fail-closed 点名源路径。"""
    src = root / TEMPLATE_ROUTES_REL
    try:
        data = src.read_bytes()
    except OSError as e:
        raise FailClosed(
            "脚手架源表不可读（缺失=无法开箱即用，fail-closed 不落空拷贝）：%s: %s"
            % (src, e))
    if not data or any(a not in data for a in _TEMPLATE_ANCHORS):
        raise FailClosed(
            "脚手架源表畸形（非空且须含 default:/roles: 两节锚，真源=%s）——拒绝拷贝，"
            "请先修复引擎仓路由表" % src)
    return data


def scaffold_container(root: pathlib.Path, engine_root: pathlib.Path, log=print):
    """对代建新根目录落容器脚手架。返回 {"created": [...], "skipped": [...]}
    （相对 root 的 posix 风格路径，接入报告账目用）。失败=FailClosed，已落产物
    由调用方 _rollback 清（本函数只保证「失败不落半份模板表」——模板表用
    tmp+os.replace 原子写）。"""
    created, skipped = [], []
    data = _source_table_bytes(engine_root)  # 先验源再落盘：失败=零现场变更

    # 目录骨架（mkdir parents；已存在不报——与零覆盖同口径）。
    for rel in (pathlib.Path("notes") / "epics",
                pathlib.Path("notes") / "discussions",
                pathlib.Path("docs"),
                pathlib.Path("server") / "dsh"):
        d = root / rel
        if not d.is_dir():
            d.mkdir(parents=True)
            created.append(rel.as_posix() + "/")

    # 文件生成物：存在即跳过（零覆盖），新文件直接写（文本）/原子写（模板表）。
    files = [
        (pathlib.Path("CLAUDE.md"), CLAUDE_MD_SKELETON.encode("utf-8")),
        (pathlib.Path("notes") / "epics" / ".gitkeep", b""),
        (pathlib.Path("notes") / "discussions" / ".gitkeep", b""),
        (pathlib.Path("docs") / ".gitkeep", b""),
        (TEMPLATE_ROUTES_REL, data),
    ]
    for rel, content in files:
        target = root / rel
        if target.exists():
            skipped.append(rel.as_posix())
            continue
        if rel == TEMPLATE_ROUTES_REL:
            tmp = target.with_name(target.name + ".scaffold-tmp")
            try:
                tmp.write_bytes(content)
                tmp.replace(target)
            except OSError as e:
                try:
                    tmp.unlink()
                except OSError:
                    pass
                raise FailClosed("脚手架模板表写入失败（%s）：%s: %s"
                                 % (target, type(e).__name__, e))
        else:
            target.write_bytes(content)
        created.append(rel.as_posix())

    log("      脚手架：新建 %s" % (created or "无"))
    if skipped:
        log("      脚手架：已存在跳过（零覆盖）%s" % skipped)
    return {"created": created, "skipped": skipped}


def rollback_scaffold(root: pathlib.Path, scaffold: dict, created_root: bool) -> None:
    """脚手架/条目写失败后的清理链：删本票新建的文件（最深先删），再尝试删本票
    新建的空目录（仅空目录可删——非空=他人数据/并发现场，原样保留）；created_root
    时最后尝试删根目录本身（仅空）。清理失败静默容忍（回滚不掩盖原错误）。"""
    for rel in reversed(scaffold.get("created", [])):
        p = root / rel.rstrip("/")
        try:
            if p.is_file() or p.is_symlink():
                p.unlink()
        except OSError:
            pass
    # 目录按深度降序删空目录（created 里目录带尾 /；文件条目跳过）。
    dirs = [root / r.rstrip("/") for r in reversed(scaffold.get("created", []))
            if r.endswith("/")]
    for d in sorted(dirs, key=lambda x: len(x.parts), reverse=True):
        try:
            d.rmdir()  # 仅空目录可删
        except OSError:
            pass
    if created_root:
        try:
            shutil.rmtree(root)  # 本票代建的根：回滚=整根移除（容器尚无他人数据）
        except OSError:
            pass
