"""agent_activities —— M11 v2「stage 即 activity」的 agent 段与人门准备活动（t260822-m11）。

架构转向②：一个 stage 一个 activity——
  - agent 段：activity 名=stage 名（develop/process/review/regress…），实现通用
    `_run_agent_stage_impl`：spawn headless agent 进程（`dsh --profile suyou-headless
    "<派活指令>"`，工作目录=工单工作空间），轮询工作空间结果文件 + activity.heartbeat()。
    **幂等**：结果文件（.suyou/stage_<段>_gen<N>.json）已存在则直接读文件返回——
    Temporal 活动重试/ worker 重启后重跑安全；rework 重跑靠 gen+1 换新文件（真重跑）。
  - 人门段：`prepare_human_gate` 做机械准备（提案摘录/工作空间清单/diff stat），
    返回审查上下文；签字等待在 workflow 级 wait_condition（等外部输入的正解）。
  - 工作区段（M16）：`prepare_workspace` 是**每个 v2 工单 workflow 的第一个 activity**——
    工作区由引擎创建/复用，agent 不再自己搞：
      worktree 泳道 → `git worktree add`（已建且属本仓库→复用，幂等）；
      dir 隔离目录 → `mkdir -p`（幂等）；主树道 → 跳过。
    失败**不抛**（回执交 workflow 转 blocked 等 retry_qc / rework 判读）。

结果文件格式（写进派活指令的交付契约）：
  {"status":"ok|failed","summary":…,"deliverables":[…],"files_changed":[…],"evidence":…}

worker 代落盘（260824，t260824-01/-02 两连踩后的确定性收口）：headless agent 的
沙箱写不了真 .git（worktree 的 .git 是指向主库 .git/worktrees/<id> 的 gitfile，
在 agent 可写范围之外），「agent 自己 commit」是物理上做不到的契约——agent 被逼
自建 .git-local 假仓库造假。所以 commit 不从派活契约要：agent 段拿到结果文件后
由 worker（无沙箱）调 `_settle_worktree_lane` 确定性代落盘（假仓库隔离 +
工作区改动收成一个 commit），merge_check 查的是代落盘后的真状态。

自测/演示：`SUYOU_AGENT_STUB=1` 时 activity 自写结果文件即返回（不起 agent 进程）。
派活命令可用 `SUYOU_AGENT_CMD` 覆盖（shlex 切分，缺省 `dsh --profile suyou-headless`）。
"""

from __future__ import annotations

import asyncio
import errno
import json
import os
import re
import sys
import shlex
import signal
import subprocess
import shutil
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from temporalio import activity
import shared
from shared import (
    REPO_ROOT,
    EPICS_DIR,
    EPIC_CODE_RE,
    EPIC_SA_NAME,
    STAGE_DISPATCH_KIND,
    WORKSPACE_TYPES,
    AgentStageArgs,
    ArchiveArgs,
    ArchiveResult,
    ConflictPrepArgs,
    ConflictPrepResult,
    ConflictSettleArgs,
    ConflictSettleResult,
    EpicNextPrepArgs,
    EpicNextPrepResult,
    HumanGateContext,
    HumanGatePrep,
    INTEG_MANIFEST,
    IntegrationRunArgs,
    IntegrationRunResult,
    MergeArgs,
    MergeCheckArgs,
    MergeCheckResult,
    MergeResult,
    ReviewGateArgs,
    ReviewGateResult,
    SettleLaneArgs,
    SettleLaneResult,
    StageResult,
    TEMPLATE_CLASS_NAMES,
    UI_EVIDENCE_DIR,
    EVIDENCE_DIR,
    UiEvidenceArgs,
    UiEvidenceResult,
    WorkspacePrep,
    WorkspacePrepResult,
    epic_next_precache_path,
    epic_state_key,
    is_ui_write_set,
    model_route_for,
    roles_dir_for_spawn,
    routes_file_for_spawn,
)

POLL_SEC = 5
INTEG_CMD_TIMEOUT_SEC = int(os.environ.get("SUYOU_INTEG_CMD_TIMEOUT_SEC") or 900)
DSH_CMD = shlex.split(os.environ.get("SUYOU_AGENT_CMD") or "dsh --profile suyou-headless")


def _src_dsh_home() -> Path:
    """profile/凭据/settings 的拷贝源 home：worker 继承的 DSH_HOME 优先；但该目录
    不存在（console 沙箱临时 home 被清，t260828-05：DSH_HOME=/tmp/dsh-tXXX 已删）
    时回落真实 home——否则 profile 静默拷空，dsh 起来就报 profile 不存在，rc=1 三连。"""
    env_home = os.environ.get("DSH_HOME")
    if env_home and Path(env_home).is_dir():
        return Path(env_home)
    return Path.home() / ".dsh"


def _quarantine_torn_sessions(local_dsh: Path) -> None:
    """spawn 前检疫撕裂的会话文件（t260829-06 两次实测：agent 被杀于写入中会留
    zstd 撕裂帧，resume 与同 id create 都撞 corrupt 死，整步卡死）。坏文件挪
    <cwd>/.suyou/quarantine/ 留档，让「同 id 新建」回落走得通（上下文丢但流程活）。
    zstd -t 只测帧完整性，不解压不看内容。"""
    sessions = local_dsh / "sessions"
    if not sessions.is_dir():
        return
    for f in sessions.rglob("session.jsonl.zstd"):
        r = subprocess.run(["zstd", "-t", str(f)], capture_output=True)
        if r.returncode == 0:
            continue
        qdir = local_dsh.parent / ".suyou" / "quarantine"
        try:
            qdir.mkdir(parents=True, exist_ok=True)
            dst = qdir / ("torn-%s-%s" % (f.parent.name, f.name))
            shutil.move(str(f), str(dst))
            activity.logger.warning("[sessions] 撕裂会话文件已隔离：%s", dst)
        except OSError:
            pass  # 挪不动就留着——同 id create 会再撞，但插件侧兜底已不致死


# 项目 key 白名单（sandbar M1-2 凭据出仓）：与 server/dsh/suyou-projects.ts 的
# PROJECT_KEY_RE 同款字符集，兼防 ../ 路径穿越（per-key 凭据路径要拼目录名）。
# M1-3（t260902-02）真源上移 shared.py（归档路径同用），此处保持旧名 re-export，
# 既有引用（_resolve_credentials_source 等）不破。
PROJECT_KEY_RE = shared.PROJECT_KEY_RE


def _perkey_projects_root() -> Path:
    """per-key 项目目录根（真源 shared.perkey_projects_root；本函数保持旧名
    供既有调用点使用，语义不变）。"""
    return shared.perkey_projects_root()


def _resolve_credentials_source(project_key: str) -> Optional[Path]:
    """凭据拷贝源解析（sandbar M1-2 读侧唯一真源逻辑，ui-check/creds-source.mjs 同构）：

    1. project_key 非空且过 key 白名单，且 <root>/<key>/credentials.yaml 存在（isFile，
       命中目录不算）→ 用它（per-key 首选，契约①b）；
    2. 否则 legacy 回落：env DSH_HOME/.credentials.yaml → $HOME/.dsh/.credentials.yaml
       （=M1-2 前行为，弃用窗口；命中回落时调用方负责打迁移提示日志）；
    3. 两处皆无 → None（不拷贝，既有 MISSING_CREDENTIAL 口径不变）。

    只做路径解析与存在性判定，不读不解析文件内容（凭据内容由 dsh credentials seam
    解析，畸形=fail-closed 交 seam，读侧不重复实现解析器）。"""
    key = (project_key or "").strip()
    if key and PROJECT_KEY_RE.match(key):
        perkey = _perkey_projects_root() / key / "credentials.yaml"
        if perkey.is_file():
            return perkey
    for dsh_home in [os.environ.get("DSH_HOME") or "",
                     str(Path.home() / ".dsh")]:
        if not dsh_home:
            continue  # DSH_HOME 未定义/空串剔除（HOME 空串同理，不拼相对路径）
        cand = Path(dsh_home) / ".credentials.yaml"
        if cand.is_file():
            return cand
    return None


def _perkey_is_hit(project_key: str, src: Path) -> bool:
    """project_key 合法且 src 即 per-key 路径（迁移提示日志的判定，测试亦直用）。"""
    key = (project_key or "").strip()
    return bool(key) and bool(PROJECT_KEY_RE.match(key)) and \
        src == _perkey_projects_root() / key / "credentials.yaml"


def _merge_creds(dst: Path, src: Path) -> None:
    """暂存凭据快照按 refs 叶子合并刷新（KI-016，t260902-09；只合并不覆盖）。

    背景：泳道 .dsh/.credentials.yaml 是 spawn 时的暂存快照，旧逻辑「目标已存在
    即 return」让快照永不刷新——provider 上线新 key（如 0902 的
    ZAI_CODING_CN_API_KEY）对老泳道全部 MISSING_CREDENTIAL。合并单位 = refs
    子映射的叶子（真实凭据文件是 version + 嵌套 refs 形态，version 等 seam
    自管字段 dst 原样保留、src 顶层一律不搬）：
      - src refs 有、dst refs 缺的叶子 → 追加进 dst 的 refs 块；
      - 同名叶子 → dst 值绝对胜出（不抹工单中途换 key 现场，docstring 原约定）；
      - dst 独有叶子 → 不删。

    契约偏离声明（sandbar 项目接入契约 v1 ①b「读侧不重复实现解析器」）：合并
    必须读内容，读侧用 PyYAML 软依赖解析（shared.model_route_for 同款先例），
    ①b 修订草案已随 t260902-09 方案交人审。写回不做再序列化：只在 dst 的
    refs 块内文本追加同形新行，其余字节零改动，seam 解析合并产物无容忍度问题。

    故障模式取舍（除最后一条外，任一命中 = 不合并、快照原样、只打 warning
    不抛新错——约束②「解析失败维持现状不抛新错」）：
      - PyYAML 不可用 / 任一侧 yaml 语法错 / 顶层非 dict（扁平老格式、裸标量）；
      - dst 的 refs 行是 inline 形态（如 `refs: {A: x}`）——再往里追加缩进子行
        会产出非法 YAML，宁可少合一个 key，不可毁整份快照（agent 全部凭据
        不可用比缺一个 key 更糟）；
      - src 无 refs 段：no-op 静默返回（seam 只认 refs 叶子，扁平老文件没有
        可合并单位，与 seam 语义一致，非故障）；
      - dst 读失败 / CRLF 文件 / 叶子值是多行标量（文本追加保形不安全）；
      - 写回 OSError：快照保持原样，tmp 在 finally 清理；
      - 无新增叶子：零写回（不动 mtime/mode，防无谓抖动）。
    追加行文本 = yaml 标量安全序列化（数字形/含特殊字符值自动加引号，防注入
    裸行），缩进取 dst refs 子级的实测缩进（无子级则 2 空格）。写回同目录
    tmp + os.replace 原子替换，mode 照抄 dst。"""
    try:
        import yaml  # pyyaml（temporal-poc venv；shared.model_route_for 同款软依赖）
    except ImportError:
        activity.logger.warning(
            "[creds] 暂存凭据合并跳过（dst=%s src=%s）：PyYAML 不可用，快照原样",
            dst, src)
        return

    def _load(p: Path) -> Optional[dict]:
        try:
            data = yaml.safe_load(p.read_text("utf-8"))
        except Exception:  # yaml 语法错/OSError/UnicodeDecodeError → 不可解析
            return None
        return data if isinstance(data, dict) else None

    dst_data, src_data = _load(dst), _load(src)
    if dst_data is None or src_data is None:
        activity.logger.warning(
            "[creds] 暂存凭据合并跳过（dst=%s src=%s）：内容不可解析为映射，快照原样",
            dst, src)
        return
    src_refs = src_data.get("refs")
    if src_refs is None:
        return  # src 无 refs（扁平老格式）：seam 只认 refs 叶子，无可合并单位
    if not isinstance(src_refs, dict):
        activity.logger.warning(
            "[creds] 暂存凭据合并跳过（src=%s）：refs 段不是映射，快照原样", src)
        return
    dst_refs = dst_data.get("refs")
    if dst_refs is not None and not isinstance(dst_refs, dict):
        activity.logger.warning(
            "[creds] 暂存凭据合并跳过（dst=%s）：refs 段不是映射，快照原样", dst)
        return
    missing = {k: v for k, v in src_refs.items()
               if not isinstance(dst_refs, dict) or k not in dst_refs}
    if not missing:
        return  # 无新增叶子：零写回

    try:
        # 按字节读入再解码：read_text 的 universal-newlines 会在读取时把 \r\n
        # 翻译成 \n，下面的 CRLF 守卫就永远打不中（it01 F11 字节级断言抓出）。
        text = dst.read_bytes().decode("utf-8")
    except (OSError, UnicodeDecodeError) as e:
        activity.logger.warning(
            "[creds] 暂存凭据合并跳过（dst=%s）：读失败（%s），快照原样", dst, e)
        return
    if "\r" in text:
        activity.logger.warning(
            "[creds] 暂存凭据合并跳过（dst=%s）：CRLF 文本不做行级追加，快照原样", dst)
        return

    trailing_nl = text.endswith("\n")
    raw = text.split("\n")
    if trailing_nl:
        raw = raw[:-1]  # split 的末尾空串，重构时统一补回

    # 定位 refs: 行；H2 守卫：冒号后有非空内容 = inline 形态，不可合并
    refs_idx = None
    for i, ln in enumerate(raw):
        if re.match(r"^refs:\s*$", ln):
            refs_idx = i
            break
        if re.match(r"^refs:\s*\S", ln):
            activity.logger.warning(
                "[creds] 暂存凭据合并跳过（dst=%s）：refs 为 inline 形态（%r），"
                "快照原样", dst, ln.strip())
            return
    child_indent: Optional[str] = None
    insert_at = len(raw)  # refs 块到 EOF 或 dst 无 refs 段 → 都算追加到尾
    if refs_idx is not None:
        for j in range(refs_idx + 1, len(raw)):
            ln = raw[j]
            if not ln.strip() or ln.lstrip().startswith("#"):
                continue  # 空行/注释不算块边界
            if not ln[0].isspace():
                insert_at = j  # 下一个顶层键：refs 块在此结束
                break
            if child_indent is None:
                child_indent = " " * (len(ln) - len(ln.lstrip(" ")))
    indent = child_indent or "  "

    add_lines = []
    for k, v in missing.items():
        dumped = yaml.safe_dump({k: v}, allow_unicode=True, default_flow_style=False)
        parts = dumped.splitlines()
        if len(parts) != 1:
            activity.logger.warning(
                "[creds] 暂存凭据合并跳过（dst=%s）：叶子 %s 值是多行标量，"
                "文本追加保形不安全，快照原样", dst, k)
            return
        add_lines.append(indent + parts[0])

    if refs_idx is None:
        # dst 无 refs 段：文件尾补一个块（seam 读 refs 才能看到新叶子）
        new_text = text + ("" if text.endswith("\n") or not text else "\n") \
            + "refs:\n" + "".join(l + "\n" for l in add_lines)
    else:
        new_text = "\n".join(raw[:insert_at] + add_lines + raw[insert_at:]) \
            + ("\n" if trailing_nl else "")

    mode = dst.stat().st_mode & 0o777
    tmp_path: Optional[Path] = None
    try:
        fd, tmp_name = tempfile.mkstemp(dir=str(dst.parent),
                                        prefix=".credentials.yaml.", suffix=".tmp")
        tmp_path = Path(tmp_name)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(new_text)
        os.chmod(str(tmp_path), mode)
        os.replace(str(tmp_path), str(dst))
        tmp_path = None
    except OSError as e:
        activity.logger.warning(
            "[creds] 暂存凭据合并写回失败（dst=%s）：%s，快照保持原样", dst, e)
        return
    finally:
        if tmp_path is not None and tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:
                pass  # 清理失败不掩盖主流程；残留 tmp 下次合并不受影响
    activity.logger.info(
        "[creds] 暂存凭据合并刷新：%s 追加叶子 %s（源=%s，同名叶子未改写）",
        dst, "、".join(str(k) for k in missing), src)


def _copy_creds(dst_dsh: Path, project_key: str = "") -> None:
    """把凭据拷进/合并进工作空间本地 .dsh（API key 透传；拷贝源 = 项目目录
    ~/.sandbar/projects/<key>/credentials.yaml 优先，legacy 全局回落）。
    project_key 未知/为空 = 跳过 per-key 首查、仍走 legacy 回落（=M1-2 前行为）。

    - dst 缺失：整文件 copy2；copy2 抛错（权限/属主等不可读终态）= fail-closed
      上抛，报错含源路径，不静默吞。
    - dst 已存在：refs 叶子级合并刷新（见 _merge_creds，KI-016）——不再整段
      跳过（旧守卫让暂存快照永不刷新，新 provider 对老泳道全 MISSING_CREDENTIAL），
      同时保住原守卫意图：同名叶子 dst 值绝不改写（agent 可能已中途换 key，
      覆盖会把现场抹掉）。
    解析失败/源缺失维持现状不抛新错：源缺失静默跳过（MISSING_CREDENTIAL 口径
    由引擎报），解析失败 warning + 快照原样。"""
    dst = dst_dsh / ".credentials.yaml"
    src = _resolve_credentials_source(project_key)
    if src is None:
        return
    if not dst.exists():
        try:
            shutil.copy2(str(src), str(dst))
            # t260903-12 实雷（安全事件余波）：dsh 拒载过宽权限凭据（agent rc=1 家族）。
            # copy2 保留源权限——源若 644，泳道快照带病；拷后强制 0600。
            os.chmod(str(dst), 0o600)
        except OSError as e:
            raise RuntimeError("凭据拷贝失败（fail-closed，源=%s）：%s" % (src, e))
        if not _perkey_is_hit(project_key, src):
            activity.logger.warning(
                "[creds] 项目凭据不在 %s/%s/credentials.yaml，仍用 legacy 全局凭据 %s"
                "（迁移步骤见契约《sandbar 项目接入契约 v1》①b 节；legacy 回落属弃用窗口）",
                _perkey_projects_root(), (project_key or "").strip() or "<key>", src)
        return
    _merge_creds(dst, src)


async def _fetch_ticket_project(ticket_id: str) -> str:
    """查自身工单的 project key（M1-2：凭据 per-key 化需要项目目录名）。
    数据源 = workflow snapshot 的 meta.project（base.py 落快照时写入）；
    查询失败/超时/为空 → ""（软失败：跳过 per-key 首查走 legacy 回落，
    绝不因凭据路径查询弄挂 spawn）。先例 = _epic_ticket_rows 的 snapshot 查询。"""
    try:
        from client import _connect
        client = await _connect()
        snap = await asyncio.wait_for(
            client.get_workflow_handle(ticket_id).query("snapshot"), timeout=8)
        return str((snap or {}).get("meta", {}).get("project") or "")
    except Exception as e:
        activity.logger.warning("[creds] 工单 %s 的 project 查询降级（%s），"
                                "凭据走 legacy 全局路径", ticket_id, str(e)[:200])
        return ""


def _copy_settings(dst_dsh: Path) -> None:
    """把 dsh home 的 settings.yaml 拷进工作空间本地 .dsh——llm-pi-ai 的 providers 段在其中，
    缺了它 kimi-coding/zai/scnet 适配器全部休眠（NO_ADAPTER）。settings.yaml 无密钥
    （key 走 apiKeyEnv/凭据 seam），拷的是 provider 注册配置。每次 spawn 重拷：
    设置变更（新 provider/排序）下一个 agent 即生效。"""
    src = _src_dsh_home() / "settings.yaml"
    if src.is_file():
        shutil.copy2(str(src), str(dst_dsh / "settings.yaml"))


def _pin_default_model(dst_dsh: Path, route: Dict[str, str]) -> None:
    """把路由结果写进泳道本地 settings.yaml 的 agent-default-model 用户层。

    dsh 层叠规则：settings 用户层 > cordis patch 合成层（dsh-settings resolve =
    mergeLayers(base, section)，用户层后盖）。settings.yaml 里有 GUI 默认模型段
    （agent-default-model），只发一次性 model_patch 必被它盖掉——260826 事故根因：
    路由表切 kimi-coding/zai 全部落空，agent 实际全跑 scnet，scnet 配额一尽全灭。
    所以钉路由必须落用户层；每次 spawn 重拷 settings 故不会残留漂移。"""
    p = dst_dsh / "settings.yaml"
    if not p.is_file():
        return
    out, skipping = [], False
    for ln in p.read_text("utf-8").splitlines(keepends=True):
        if ln.startswith("agent-default-model:"):
            skipping = True  # 整段摘除（含段内缩进注释），统一在文末重写
            continue
        if skipping and ln[:1] not in (" ", "\t", "\n", "#"):
            skipping = False  # 下一个顶层键
        if not skipping:
            out.append(ln)
    out.append("agent-default-model:\n  provider: %s\n  model: %s\n"
               % (route["provider"], route["model"]))
    p.write_text("".join(out), "utf-8")


def _copy_profile(dst_dsh: Path) -> None:
    """把 suyou-headless profile 软链拷进工作空间本地 .dsh（沙箱隔离）。"""
    src = _src_dsh_home() / "profiles" / "suyou-headless"
    if not src.exists():
        return  # 无 profile 可拷——headless 用 dsh 内置兜底
    dst = dst_dsh / "profiles"
    dst.mkdir(parents=True, exist_ok=True)
    if not (dst / "suyou-headless").exists():
        shutil.copytree(str(src), str(dst / "suyou-headless"), symlinks=True)

# 全部 agent 段的 stage id（activity 名=stage 名；纯门段 machine-qc 与
# 人门段 approve/final-review/merge 不在此列）。
# 260824 dev-lane：developer 系工单统一走 create_plan/review_plan/implement/
# integration_review 四 agent 步（旧 code-lane/build-workbench 的 develop/verify/
# visual/close 已随模板退场删除）。
AGENT_STAGE_IDS = (
    "create_plan", "review_plan", "implement", "integration_review",  # dev-lane（integration_review 仅存量 workflow 重放可达）
    "design_integration_tests",                      # dev-lane 集成测试机制（t260831-02）
    # 以下四行所属模板已退役（260904 宿主令）：段名仅为存量 workflow 重放兜底保留
    "propose", "process", "ai-review", "publish",    # content-pipeline（已退役）
    "review", "report",                              # proofread（已退役；report 兼 regression）
    "regress",                                       # regression（已退役）
    "clean", "rederive",                             # cleanup（已退役）
)


def _ws_cwd(ws: Optional[Dict[str, str]], ticket_id: str) -> Path:
    """agent 进程工作目录：worktree 泳道（相对仓库根）/ dir 隔离目录 / 主树。"""
    if isinstance(ws, dict) and ws.get("path"):
        p = Path(str(ws["path"]))
        if not p.is_absolute():
            p = REPO_ROOT / p
        return p
    return REPO_ROOT


def _read_result(path: Path) -> Optional[StageResult]:
    try:
        raw = json.loads(path.read_text("utf-8"))
    except Exception:
        return None
    return StageResult(
        status=str(raw.get("status") or "ok"),
        summary=str(raw.get("summary") or ""),
        report=str(raw.get("report") or ""),
        deliverables=[str(x) for x in (raw.get("deliverables") or [])],
        files_changed=[str(x) for x in (raw.get("files_changed") or [])],
        evidence=str(raw.get("evidence") or ""),
    )


def _patch_result_prompt(rfile: Path, prompt: str) -> None:
    """把完整 prompt 写进结果 JSON 的 prompt 字段（工单台 Agent 日志页签可查看）。
    已存在则跳过（不覆盖，保留首次写入的 prompt）。"""
    try:
        raw = json.loads(rfile.read_text("utf-8"))
    except Exception:
        return
    if raw.get("prompt"):
        return
    raw["prompt"] = prompt
    try:
        rfile.write_text(json.dumps(raw, ensure_ascii=False, indent=1) + "\n", "utf-8")
    except Exception:
        pass


def _session_kb(cwd: Path) -> int:
    """返回工作空间本地 .dsh/sessions/ 下最新 session 文件的 KB 数（agent 进度信号）。"""
    sd = cwd / ".dsh" / "sessions"
    if not sd.is_dir():
        return 0
    best = ("", 0)
    for d in sd.iterdir():
        if not d.is_dir():
            continue
        for f in d.iterdir():
            if f.name.startswith("session-") and f.suffix == ".zstd":
                try:
                    sz = f.stat().st_size
                except OSError:
                    sz = 0
                if sz > best[1]:
                    best = (str(f), sz)
    return best[1] // 1024


# agent 沙箱写不了真 .git 时自建的假仓库目录名（260824 实测：.git-local/.git-obj-tmp/
# .git-tmp/.git-alt）。settle 发现即隔离进 .suyou/quarantine/（不删，留档可查）。
FAKE_GIT_DIRS = (".git-local", ".git-obj-tmp", ".git-tmp", ".git-alt")


def _gitdir_is_real(cwd: Path) -> bool:
    """worktree 的 gitdir 是否指向主库 .git 之下（真身校验）。

    t260824-03 教训：.git gitfile 在泳道目录内、沙箱可写，agent 可以把它改写指向
    自建假仓库（.git-alt）——之后泳道里一切 git 操作都落进假仓库，按目录名抓
    假仓库的排查会全部落空。所以不看名字，看 gitdir 真身。"""
    p = _git(["rev-parse", "--absolute-git-dir"], cwd)
    if p.returncode != 0:
        return False
    try:
        gd = Path(p.stdout.strip()).resolve()
        # 跨项目（t260903-10）：worktree 的真 gitdir 在其所属项目仓 .git 下，
        # 按路径约定自锚定，不恒锚引擎仓（否则跨项目泳道恒误判被"修复"写坏）。
        return gd.is_relative_to((_lane_repo_root(cwd) / ".git").resolve())
    except Exception:
        return False


def _restore_gitfile(cwd: Path, ticket_id: str, stage_id: str, gen: int) -> Optional[str]:
    """gitfile 被改写（指向主库之外）时修复：隔离假仓库 + 重写 gitfile 指向真注册
    gitdir。返回人读说明；gitfile 没问题返回 None；修不了抛异常（交 Temporal 重试/
    workflow 转 blocked）。"""
    p = _git(["rev-parse", "--absolute-git-dir"], cwd)
    fake = Path(p.stdout.strip()).resolve() if p.returncode == 0 else None
    real = _lane_repo_root(cwd) / ".git" / "worktrees" / cwd.name
    if not (real / "HEAD").is_file():
        raise RuntimeError(
            "settle: gitfile 被改写（指向 %s）且真 gitdir %s 不存在，无法自动修复——人工处置"
            % (fake, real))
    # 真 gitdir 的反向指针校验（gitdir 文件应指回 cwd/.git），对不上说明注册已乱
    back = (real / "gitdir").read_text("utf-8").strip() if (real / "gitdir").is_file() else ""
    if back and Path(back).resolve() != (cwd / ".git").resolve():
        raise RuntimeError(
            "settle: 真 gitdir %s 的反向指针指向 %s（非本泳道），注册混乱——人工处置" % (real, back))
    (cwd / ".git").write_text("gitdir: %s\n" % real, "utf-8")
    note = "gitfile 被 agent 改写（指向主库外 %s），已恢复指向真 gitdir" % fake
    # 假仓库隔离留档（在泳道内、且是个 git 目录才挪）
    if fake and fake.is_relative_to(cwd.resolve()) and (fake / "HEAD").exists() and fake.is_dir():
        qdir = cwd / ".suyou" / "quarantine"
        qdir.mkdir(parents=True, exist_ok=True)
        dst = qdir / ("%s-gitdir-%s-gen%d" % (fake.name, stage_id, gen))
        n = 1
        while dst.exists():
            n += 1
            dst = qdir / ("%s-gitdir-%s-gen%d-%d" % (fake.name, stage_id, gen, n))
        shutil.move(str(fake), str(dst))
        note += "；假仓库 %s 已隔离到 %s" % (fake.name, dst.relative_to(cwd))
    activity.logger.warning("[%s/%s] settle：%s", ticket_id, stage_id, note)
    return note

# settle/merge_check 共用的 git pathspec 排除口径：.dsh（agent 沙箱/credentials）与
# .suyou（结果文件/agent 日志/quarantine）是引擎运行时目录，任何泳道必有，不算改动。
# 注意：本 pathspec 只用于 git status（porcelain 正常）；git add 不可带它——
# Apple Git 2.50 对「. + :!ignored目录」组合必报错 rc=1（见 _settle_worktree_lane）。
SETTLE_PATHSPEC = [".", ":!.dsh", ":!.suyou"]


# ---- KI-009（t260901-25）：merge_check dirty 红灯前自动补 settle 的两个纯函数 ----
# 纯函数无 IO，integration/t260901-25 用 ast 抽取直接测（环境无 temporalio 导不进模块）。


def _dirty_files_from_status_z(raw: str) -> List[str]:
    """解析 `git status --porcelain -z` 输出为脏文件路径清单（KI-009）。

    用 -z 而非普通 --porcelain 的理由：NUL 分隔无 quotePath 引号歧义（含空格/
    非 ASCII 的路径不会被引号包裹转义），rename/copy 条目拆成 `XY new<NUL>old<NUL>`
    两字段无「old -> new」箭头解析——两种普通格式的畸形行形态在这里结构上不存在。
    容错：非串/空串 → []；条目 XY 位不足 2 字符或缺路径 → 丢弃该条不抛（畸形输入
    fail-closed 交上层判写集外）；rename/copy 只取 new（工作区现状路径）。
    """
    if not isinstance(raw, str) or not raw:
        return []
    out: List[str] = []
    for ent in raw.split("\0"):
        if not ent:
            continue
        if len(ent) < 4 or not ent[2] == " ":
            continue  # XY<space>path 形态不成立：畸形条目丢弃，不猜
        path = ent[3:]
        if not path:
            continue
        out.append(path)
    return out


def _dirty_within_write_set(files: List[str], write_set: Any) -> bool:
    """脏文件清单是否全部落在工单 write_set 内（KI-009 自愈放行判据，纯函数）。

    fail-closed：files 为空（没脏不用自愈）/ write_set 非列表或为空 / 任一条目
    非串或 strip 后为空 / 任一脏文件非串或为空 / 脏文件是绝对路径、含 `..` 段、
    含反斜杠 / 未命中任何条目 —— 一律 False，不自愈。
    条目命中口径：脏文件 == 条目，或脏文件以「条目 + /」为目录前缀（条目可写
    `app/src` 表示整个前缀）；条目以 / 结尾同义。
    """
    if not files or not isinstance(write_set, list) or not write_set:
        return False
    pats: List[str] = []
    for p in write_set:
        if not isinstance(p, str) or not p.strip():
            return False
        s = p.strip().rstrip("/")
        if s:
            pats.append(s)
    if not pats:
        return False
    for f in files:
        if not isinstance(f, str) or not f:
            return False
        if f.startswith("/") or "\\" in f or f == ".." or f.startswith("../") \
                or "/../" in f or f.endswith("/.."):
            return False
        if any(ch in f for ch in "?!*[]"):  # git 哨兵（?）/通配形态路径：fail-closed 拒
            return False
        if not any(f == s or f.startswith(s + "/") for s in pats):
            return False
    return True


# ---- KI-009（t260901-25）：agent 进程全终态回收（drain 压迟写竞态窗） ----

# reap 有界窗：terminate 后最多等这么久，超时升级 kill；再等 kill 退出。
AGENT_REAP_TERM_TIMEOUT_SEC = 15
AGENT_REAP_KILL_TIMEOUT_SEC = 5


def _reap_agent_proc(proc: subprocess.Popen, ticket_id: str = "", stage_id: str = "",
                     term_timeout: float = AGENT_REAP_TERM_TIMEOUT_SEC,
                     kill_timeout: float = AGENT_REAP_KILL_TIMEOUT_SEC) -> str:
    """agent 进程树全终态回收（KI-009 ②）：terminate → 带超时 wait → 超时 kill → 再 wait。

    为什么按进程组：dsh runner 会再 spawn 子进程，agent「迟写文件」往往发生在
    孙进程手里——只杀直接子进程等于把迟写者留成孤儿（KI-009 竞态窗真凶）。
    所以 spawn 一律 start_new_session=True（独立进程组），本函数对组发信号
    （killpg），组粒度收整棵树。组不存在（进程已死/已被收）按幂等处理不抛。
    返回人读说明（供调用方写 log / evidence）；对已退出 proc 幂等返回 ""。
    """
    if proc.poll() is not None:
        return ""  # 已退出：幂等
    tag = "[%s/%s]" % (ticket_id, stage_id) if ticket_id else "[reap]"

    def _sig_group(sig: int) -> None:
        try:
            os.killpg(os.getpgid(proc.pid), sig)
        except OSError as e:
            # 组已不存在（ESRCH）/ 无权限（EPERM）→ 退回只发直接子进程，尽力而为
            if e.errno not in (errno.ESRCH, errno.EPERM):
                raise
            try:
                proc.send_signal(sig)
            except (ProcessLookupError, OSError):
                pass

    notes: List[str] = []
    _sig_group(signal.SIGTERM)
    notes.append("terminate（进程组）")
    try:
        proc.wait(timeout=term_timeout)
    except subprocess.TimeoutExpired:
        _sig_group(signal.SIGKILL)
        notes.append("terminate 超时 %ss 升级 kill（进程组）" % term_timeout)
        try:
            proc.wait(timeout=kill_timeout)
        except subprocess.TimeoutExpired:
            notes.append("kill 后仍未退出（%ss），放弃等待" % kill_timeout)
    note = "%s reap：%s，rc=%s" % (tag, "→".join(notes), proc.poll())
    activity.logger.info(note)
    return note


def _settle_worktree_lane(cwd: Path, ticket_id: str, stage_id: str, gen: int) -> str:
    """worktree 泳道代落盘（确定性，不依赖 agent 自觉）：agent 交付结果文件后调用。

    背景：headless agent 的沙箱写不了真 .git（worktree 的 .git 是指向主库
    .git/worktrees/<id> 的 gitfile，在沙箱可写范围之外），「agent 自己 commit」
    物理做不到——t260824-01/-02 的 agent 被逼自建 .git-local 假仓库「完成 commit」，
    真泳道 0 commit，merge_check 红灯。所以 commit 改由 worker（无沙箱）兜底：
      1. 假 git 仓库目录隔离进 .suyou/quarantine/（挪不删，留档）；
      2. 工作区改动（SETTLE_PATHSPEC 口径）收成一个 commit 落到泳道分支。
    幂等：工作区已干净则不动（agent 若真能 commit，settle 是 no-op）。
    返回人读说明（追加进 stage evidence）；非 worktree 泳道返回 ""。
    git 故障抛异常 = 基础设施问题，交 Temporal 重试。

    合并进行中护栏（t260826-01 review F1，阻断缺陷修复）：MERGE_HEAD 在场
    （冲突消解轮 prep 已留现场）时**不得**自动 add+commit——否则合并提交
    在这里被抢先落掉（MERGE_HEAD 消耗），settle_conflict_resolution 必报
    「无进行中的合并」假失败，且 agent 没解干净的冲突标记会被当正文提交进
    分支。合并进行中的代落盘唯一收口=settle_conflict_resolution（含标记
    残留校验），本函数直接跳过。正常 implement 轮无 MERGE_HEAD，行为不变。
    """
    if not _is_worktree_of(cwd, _lane_repo_root(cwd)):  # 跨项目同锚（t260903-10）
        return ""
    p = _git(["rev-parse", "--verify", "MERGE_HEAD"], cwd)
    if p.returncode == 0:
        note = "合并进行中（MERGE_HEAD 在场），代落盘跳过——合并提交由 settle_conflict_resolution 收口"
        activity.logger.info("[%s/%s] settle：%s", ticket_id, stage_id, note)
        return note
    notes: List[str] = []
    # 0) gitfile 真身校验：被 agent 改写指向假仓库（t260824-03 手法）则先修复，
    #    否则后续 status/commit 全落进假仓库，按目录名的隔离也会落空
    if not _gitdir_is_real(cwd):
        fixed = _restore_gitfile(cwd, ticket_id, stage_id, gen)
        if fixed:
            notes.append(fixed)
    # 1) 假 git 仓库隔离
    for name in FAKE_GIT_DIRS:
        src = cwd / name
        if not src.exists():
            continue
        qdir = cwd / ".suyou" / "quarantine"
        qdir.mkdir(parents=True, exist_ok=True)
        dst = qdir / ("%s-%s-gen%d" % (name, stage_id, gen))
        n = 1
        while dst.exists():
            n += 1
            dst = qdir / ("%s-%s-gen%d-%d" % (name, stage_id, gen, n))
        shutil.move(str(src), str(dst))
        notes.append("假 git 目录 %s 已隔离到 %s（agent 沙箱 workaround 产物，留档）"
                     % (name, dst.relative_to(cwd)))
    # 2) 工作区改动收成 commit
    p = _git(["status", "--porcelain", "--"] + SETTLE_PATHSPEC, cwd)
    if p.returncode != 0:
        raise RuntimeError("settle: git status 失败: %s" % (p.stderr or "")[-300:])
    dirty = [ln for ln in p.stdout.splitlines() if ln.strip()]
    if dirty:
        # Apple Git 2.50 实测：排除 pathspec（:!.dsh）拦不住「显式点名 ignored 目录」
        # 报错（干净仓库必现 rc=1）——t260826-01 implement gen3 即在此挂死。
        # 改全量 add（.dsh/.suyou 有 gitignore 本就不会入暂存），再 reset 摘回
        # 作双保险（防老 .gitignore 泳道；无匹配时 rc=0 静默）。
        p = _git(["add", "-A", "--", "."], cwd)
        if p.returncode != 0:
            raise RuntimeError("settle: git add 失败: %s" % (p.stderr or "")[-300:])
        _git(["reset", "-q", "--", ".dsh", ".suyou"], cwd)
        msg = ("%s %s：worker 代落盘（gen%d，%d 项改动）\n\n"
               "headless agent 沙箱写不了主库 .git，commit 由 worker 确定性兜底"
               % (ticket_id, stage_id, gen, len(dirty)))
        p = _git(["commit", "-m", msg], cwd)
        if p.returncode != 0:
            raise RuntimeError("settle: git commit 失败: %s" % (p.stderr or p.stdout or "")[-300:])
        head = _git(["rev-parse", "--short", "HEAD"], cwd)
        notes.append("worker 代落盘 commit %s（%d 项：%s）"
                     % (head.stdout.strip() if head.returncode == 0 else "?",
                        len(dirty), "、".join(ln[3:].strip() for ln in dirty[:5])))
    else:
        notes.append("工作区已干净，无需代落盘")
    note = "；".join(notes)
    activity.logger.info("[%s/%s] settle：%s", ticket_id, stage_id, note)
    return note


def _prepare_agent_spawn(cwd: Path, role: str, kind: str, ticket_id: str,
                         artifacts_dir: Path, tag: str, project: str = "",
                         session_key: str = ""):
    """spawn 前共用准备（t260828-08 从 _run_agent_stage_impl 提取）：本地 .dsh 建目录 +
    _copy_profile/_copy_creds/_copy_settings + 角色 preset patch + 模型路由钉
    agent-default-model（一次性 patch + settings 用户层双写，260826 事故根因）+
    会话延续 patch + env 组装。suggest_next（预跑下一单）与通用 agent 步共用本 helper
    ——spawn 口径单点，防两侧漂移。

    返回 (cmd 前缀（含各 patch，不含 prompt）, env)。一次性 patch 文件落 artifacts_dir，
    名带 tag 区分调用方（通用步= stage_gen<N>，预跑步= suggest_next_gen<N>）。
    """
    # 沙箱隔离：worker 进程可能无权写 ~/.dsh，headless agent 用工作空间本地 .dsh
    # 目录（DSH_HOME 覆盖），profile 软链照抄一份。
    local_dsh = cwd / ".dsh"
    local_dsh.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    env["DSH_HOME"] = str(local_dsh)
    # 守卫查 profile 本体（t260828-05 教训：查父目录时，首次失败残留的 profiles/
    # node_modules 会让后续重试永远跳过拷贝）；幂等由 _copy_profile 内部 exists 保证
    _copy_profile(local_dsh)
    _quarantine_torn_sessions(local_dsh)
    # 顺便拷 credentials（API key），否则 headless agent 报 MISSING_CREDENTIAL；
    # 拷贝源 per-key 优先（M1-2），project 未知也走 legacy 回落不改现行为。
    # KI-016（t260902-09）：dst 已存在不再跳过——合并刷新下沉 _copy_creds 单点
    # （refs 叶子级，同名叶子 dst 值不改写），新 provider 的 key 对老泳道立即可见。
    # 原外层 exists 守卫是内部守卫的重复，下沉后会把刷新路径整个挡死，已摘。
    _copy_creds(local_dsh, project)
    # settings.yaml 每次重拷（llm-pi-ai providers 注册表；改了下一个 agent 即生效）
    _copy_settings(local_dsh)

    cmd = list(DSH_CMD)
    # 角色 preset patch（契约①d t260903-03：目录基准经注册条目 paths.roles_dir
    # 声明取值，未声明回落 <cwd>/server/dsh/roles——worktree 内副本=工单快照语义
    # 不变）：persona=岗位说明书全文，cordis patch 同 id 覆盖。未声明时具体角色
    # 文件不存在（旧 base_ref）则跳过，退化为 profile 默认 persona——不硬失败；
    # 声明了而锚点目录缺失/类型错位 = ProjectPathsError 上抛（fail-closed 红，
    # 报错点名条目文件与解析后路径）。
    role_patch = roles_dir_for_spawn(project, cwd) / (role + ".yml")
    if role and role_patch.is_file():
        cmd += ["--patch", str(role_patch)]
    # 运行时模型路由（gen.py 退役后的唯一消费者）：读路由表查
    # (role, kind) → provider/model，生成一次性 patch 钉 agent-default-model。
    # 分工 kind 由 STAGE_DISPATCH_KIND 按 (workflow, stage) 映射（如 ai-review→proofread
    # 审校家模型）。查不到则不传——agent 用 profile 默认模型，不硬失败。表路径经
    # 契约①d paths.model_routes 声明取值（routes_file_for_spawn：未声明回落主仓
    # MODEL_ROUTES_FILE；声明锚点缺失=红；表内容损坏=model_route_for 既有容错
    # 返回 None，声不声明同语义）。
    route = model_route_for(role, kind, routes_file=routes_file_for_spawn(project))
    if route:
        model_patch = artifacts_dir / ("model_patch_%s.yml" % tag)
        model_patch.write_text(
            "# 本文件由 agent activity 每次 spawn 时生成（运行时模型路由，真源=model-routes.yaml）。\n"
            "- id: agent-default-model\n"
            "  name: '@deepseek-ai/dsh-agent-default-model'\n"
            "  config:\n"
            "    provider: %s\n"
            "    model: %s\n" % (route["provider"], route["model"]), "utf-8")
        cmd += ["--patch", str(model_patch)]
        # patch 层会被 settings.yaml 用户层的 GUI 默认模型段盖掉（见 _pin_default_model），
        # 路由必须同时落用户层才真正生效。
        _pin_default_model(local_dsh, route)
    # 会话延续（dsh-headless-resume 插件）：同工单同角色的多次派活延续同一 dsh 会话，
    # 打回意见在 agent 自己的会话里收到接着改，不再每次 spawn 从零重建上下文。
    # 机制仿 model_patch：生成一次性 patch（绝对路径指 runner 文件），disable stock
    # 一次性 runner、换 create-or-resume runner；DSH_HEADLESS_SESSION 传确定性会话 id。
    # runner 优先取泳道内副本（工单快照语义，同 role_patch），旧泳道没有则回退主仓副本；
    # 都没有则跳过本段（退化为 stock 一次性，不硬失败）。SUYOU_AGENT_RESUME=0 一键关停。
    if os.environ.get("SUYOU_AGENT_RESUME", "1") != "0" and role:
        runner = cwd / "server" / "dsh" / "headless-resume" / "node.ts"
        if not runner.is_file():
            runner = REPO_ROOT / "server" / "dsh" / "headless-resume" / "node.ts"
        if runner.is_file():
            resume_patch = artifacts_dir / ("resume_patch_%s.yml" % tag)
            resume_patch.write_text(
                "# 本文件由 agent activity 每次 spawn 时生成（会话延续，runner 真源=server/dsh/headless-resume/）。\n"
                "- id: headless-runner\n"
                "  disabled: true\n"
                "- insert:\n"
                "    - id: headless-resume\n"
                "      name: '%s'\n"
                "      inject: [headlessStartup]\n"
                "      config:\n"
                "        task: !!js ctx.headlessStartup.task\n" % runner, "utf-8")
            cmd += ["--patch", str(resume_patch)]
            # t260903-02 ②：会话 id 默认 ticket-role（同角色跨段延续）；并行分叉的
            # acceptance 边传 ticket-stage 专用 key——同 role 双并发进程绝不同写一个
            # 会话文件（默认 key 下 arbitrate/acceptance 并发 spawn 确定碰撞）。
            env["DSH_HEADLESS_SESSION"] = session_key or ("%s-%s" % (ticket_id, role))
    return cmd, env


async def _run_agent_stage_impl(args: AgentStageArgs) -> StageResult:
    rfile = Path(args.result_file)
    rfile.parent.mkdir(parents=True, exist_ok=True)
    cwd = _ws_cwd(args.workspace, args.ticket_id)
    cwd.mkdir(parents=True, exist_ok=True)

    # 幂等：结果文件已存在 → 直接读文件返回（Temporal 重试/worker 重启重跑安全）
    if rfile.is_file():
        cached = _read_result(rfile)
        if cached is not None:
            activity.logger.info("[%s/%s] 结果文件已存在，幂等返回（gen%d）",
                                 args.ticket_id, args.stage_id, args.gen)
            _patch_result_prompt(rfile, args.prompt)
            # 缓存命中也过 settle（上次 worker 可能死在 agent 交付后、代落盘前）——幂等；
            # skip_settle（并行分叉期）由汇合点的 settle_lane 统一承担
            note = ""
            if not args.skip_settle:
                note = _settle_worktree_lane(cwd, args.ticket_id, args.stage_id, args.gen)
            if note:
                cached.evidence = (cached.evidence + "\n[worker settle] " + note).strip()
            return cached

    if os.environ.get("SUYOU_AGENT_STUB") == "1":
        # 自测/演示 stub：自写结果文件即返回（不起 agent 进程，零模型调用）
        stub = StageResult(
            status="ok",
            summary="[stub] %s 段完成（SUYOU_AGENT_STUB=1，第 %d 次进段）"
                    % (args.stage_id, args.gen),
            report="[stub] 做了什么：无（stub 演示）\n\n怎么验证的：无",
            deliverables=[], files_changed=[],
            evidence="stub evidence: prompt %d 字" % len(args.prompt))
        rfile.write_text(json.dumps({
            "status": stub.status, "summary": stub.summary, "report": stub.report,
            "deliverables": stub.deliverables, "files_changed": stub.files_changed,
            "evidence": stub.evidence, "prompt": args.prompt,
        }, ensure_ascii=False, indent=1) + "\n", "utf-8")
        activity.heartbeat("stub done")
        return stub

    # spawn 前共用准备（本地 .dsh 三拷在上方 helper 内 + 角色 patch + 模型路由 +
    # 会话延续），提取见 _prepare_agent_spawn（t260828-08，suggest_next 共用单点）。
    kind = STAGE_DISPATCH_KIND.get((args.workflow_id, args.stage_id), "")
    project = await _fetch_ticket_project(args.ticket_id)
    cmd, env = _prepare_agent_spawn(
        cwd, args.role, kind, args.ticket_id, rfile.parent,
        "%s_gen%d" % (args.stage_id, args.gen), project=project)
    cmd.append(args.prompt)
    logf = open(args.log_file, "a", buffering=1) if args.log_file else subprocess.DEVNULL
    activity.logger.info("[%s/%s] spawn headless agent（gen%d，cwd=%s）：%s …",
                         args.ticket_id, args.stage_id, args.gen, cwd,
                         " ".join(cmd[:3]))
    # start_new_session=True（KI-009）：独立进程组，_reap_agent_proc 才能 killpg
    # 收 dsh runner 的整棵子进程树（迟写常发生在孙进程手里）
    proc = subprocess.Popen(
        cmd, cwd=str(cwd), env=env,
        stdout=logf, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
        start_new_session=True)

    polls = 0
    try:
        while True:
            if rfile.is_file():
                res = _read_result(rfile)
                if res is not None:
                    activity.logger.info("[%s/%s] 结果文件就绪：status=%s",
                                         args.ticket_id, args.stage_id, res.status)
                    _patch_result_prompt(rfile, args.prompt)
                    # KI-009（t260901-25）：settle 之前先 reap（进程组级全终态回收）
                    # ——agent 交付结果文件后可能还在迟写工作区文件，不收干净就
                    # settle，迟写落在 commit 之后=工作区脏=merge_check 假红（KI-009
                    # 根因）。drain 有界（terminate 15s / kill 5s），见 _reap_agent_proc。
                    _reap_agent_proc(proc, args.ticket_id, args.stage_id)
                    # worker 代落盘（确定性）：agent 沙箱写不了真 .git，
                    # commit 由 worker 兜底；假 git 目录在此隔离；
                    # skip_settle（并行分叉期）由汇合点的 settle_lane 统一承担
                    note = ""
                    if not args.skip_settle:
                        note = _settle_worktree_lane(cwd, args.ticket_id, args.stage_id, args.gen)
                    if note:
                        res.evidence = (res.evidence + "\n[worker settle] " + note).strip()
                    return res
            rc = proc.poll()
            if rc is not None:
                # agent 进程退出但没写结果文件 = 基础设施/用法故障 → 抛出让 Temporal 重试
                raise RuntimeError(
                    "headless agent 退出（rc=%s）但未写结果文件 %s（日志 %s）"
                    % (rc, rfile, args.log_file))
            activity.heartbeat(json.dumps(
                {"stage": args.stage_id, "gen": args.gen, "polls": polls,
                 "session_kb": _session_kb(cwd)}))
            polls += 1
            if args.max_polls and polls >= args.max_polls:
                raise RuntimeError(
                    "等结果文件超时（%d 次轮询 × %ds）：%s" % (polls, POLL_SEC, rfile))
            await asyncio.sleep(POLL_SEC)
    finally:
        # KI-009：finally 兜底升级为组粒度全终态回收（正常/报错/超时/取消四路径
        # 都走到这里；已退出的 proc 幂等跳过）
        _reap_agent_proc(proc, args.ticket_id, args.stage_id)


def _make_stage_activity(stage_id: str):
    """每个 stage 名注册一个 activity（同一实现，名字=stage 名）。
    包一层防 activity.defn 在同一函数对象上互相覆盖定义名。"""
    async def _impl(args: AgentStageArgs) -> StageResult:
        return await _run_agent_stage_impl(args)
    _impl.__name__ = "stage_" + stage_id.replace("-", "_")
    return activity.defn(_impl, name=stage_id)


# ---------- 立项下一单预跑（t260828-08）：prepare_epic_next + suggest_next ----------

async def _epic_ticket_rows(epic: str) -> List[Dict[str, Any]]:
    """epic 关联工单行（{id,status,closed}）。数据源 = client.py cmd_ticket_list 同款
    EpicCode SA 查询通路（client.py :555 口径互指；activities.py 巡检「epic 数据源 =
    ticket list 行形态」同源）：list_workflows 按 WorkflowType 六模版 AND EpicCode 过滤，
    RUNNING 执行 query snapshot 拿 status，COMPLETED 即 closed。查询失败/环境无 SA 一律
    返回 []（上层按「列表为空」降级——state_key 仍可算，只是少行；不硬失败）。"""
    try:
        from workflows_v2 import TEMPLATE_CLASSES  # 延迟导入：workflows_v2 反向依赖本模块链
        from client import _connect
        from temporalio.common import SearchAttributeKey
        client = await _connect()
        type_filter = " OR ".join(
            'WorkflowType="%s"' % c.__name__ for c in TEMPLATE_CLASSES.values())
        type_filter = '(%s) AND %s="%s"' % (type_filter, EPIC_SA_NAME, epic)
        rows: List[Dict[str, Any]] = []
        seen: set = set()
        async for wf in client.list_workflows(type_filter):
            tid = wf.id
            if tid in seen:
                continue
            seen.add(tid)
            exec_status = wf.status.name if wf.status is not None else ""
            if exec_status == "TERMINATED":
                continue  # 与 cmd_ticket_list 同口径：清场执行不上账
            status = ""
            if exec_status == "COMPLETED":
                status = "closed"
            elif exec_status == "RUNNING":
                try:
                    snap = await asyncio.wait_for(
                        client.get_workflow_handle(tid).query("snapshot"), timeout=8)
                    status = str((snap or {}).get("meta", {}).get("status") or "")
                except Exception:
                    status = ""  # 快照不可得按 open 记（保守：多算一次冷起，不误判完结）
            rows.append({"id": tid, "status": status, "closed": status == "closed"})
        return rows
    except Exception as e:
        activity.logger.warning("[prepare_epic_next] epic=%s 工单查询降级（%s）", epic, str(e)[:200])
        return []


@activity.defn
async def prepare_epic_next(args: EpicNextPrepArgs) -> EpicNextPrepResult:
    """立项下一单预跑的准备段：读立项全文 + 列关联工单 + 算 state_key，全量内联返回
    （workflow 内零 IO）。档案不可读 → exists=False（workflow 侧留痕跳过，不阻塞 merge）。"""
    code = str(args.epic or "").strip()
    if not EPIC_CODE_RE.match(code):
        activity.logger.warning("[prepare_epic_next] 代号形状非法：%r", code)
        return EpicNextPrepResult(exists=False)
    markdown = ""
    path = EPICS_DIR / (code + ".md")
    if path.is_file():
        try:
            markdown = path.read_text("utf-8")
        except Exception as e:
            activity.logger.warning("[prepare_epic_next] %s 读取失败：%s", path, str(e)[:200])
    try:
        rows = await _epic_ticket_rows(code)
    except Exception as e:  # 查询路径意外抛错也降级为空行表（不硬失败）
        activity.logger.warning("[prepare_epic_next] epic=%s 工单查询异常（%s）", code, str(e)[:200])
        rows = []
    # state_key 口径见 shared.py 区块注释：当前工单（即将 merge 收口的本票）强制 closed。
    return EpicNextPrepResult(
        exists=bool(markdown), epic_markdown=markdown, tickets=rows,
        state_key=epic_state_key(rows, args.ticket_id))


def _sanitize_suggest_write_set(raw: Any) -> list:
    """预跑建议 write_set 清洗（纯函数，t260901-01）：逐条按 shared._valid_write_set_entry
    口径校验（仓库内相对路径：非字符串/空串/绝对路径/反斜杠/Windows 盘符/'..' 一律丢条），
    strip 后保序去重；字段缺失或非列表 → 空数组不阻塞（与 epic-next.ts sanitizeWriteSet
    同构互指；建议主价值在工单本身）。注意口径差异：建票口 validate_write_set_args 是
    拒收不清洗，本处（建议口）清洗不拒收——两侧既有决策均不改变。"""
    from shared import _valid_write_set_entry
    if not isinstance(raw, list):
        return []
    out: list = []
    for p in raw:
        if not _valid_write_set_entry(p):
            continue
        s = str(p).strip()
        if s not in out:
            out.append(s)
    return out


def _parse_suggest_result(raw: Any):
    """预跑结果文件三态校验（纯函数）：返回 (kind, suggestion|None, error)。
    kind ∈ ok/done/failed；ok 形态要求 workflow+title 非空；suggestion 只保留白名单字段。
    t260901-01：ok 形态白名单增 write_set（清洗后透传，见 _sanitize_suggest_write_set）——
    build_suggest_next_prompt 的 ok 契约本就要求 agent 产出 write_set，此前落缓存被丢，
    弹层写集预填恒空。done/failed 形态不触碰 write_set。"""
    if not isinstance(raw, dict):
        return ("failed", None, "结果文件不是合法 JSON 对象")
    st = str(raw.get("status") or "")
    if st == "ok":
        wf = str(raw.get("workflow") or "").strip()
        title = str(raw.get("title") or "").strip()
        if wf == "":
            return ("failed", None, "ok 形态缺 workflow 字段")
        if title == "":
            return ("failed", None, "ok 形态缺 title 字段")
        return ("ok", {"status": "ok", "workflow": wf, "title": title,
                       "body": str(raw.get("body") or ""),
                       "rationale": str(raw.get("rationale") or ""),
                       "write_set": _sanitize_suggest_write_set(raw.get("write_set"))}, "")
    if st == "done":
        return ("done", {"status": "done",
                         "summary": str(raw.get("summary") or "")}, "")
    if st == "failed":
        return ("failed", {"status": "failed",
                           "reason": str(raw.get("reason") or "未说明原因")}, "")
    return ("failed", None, "未知 status: %r（三态契约：ok/done/failed）" % st)


def _json_dumps(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, indent=1) + "\n"


def _write_precache(ticket_id: str, code: str, state_key: str,
                    suggestion: Dict[str, Any]) -> str:
    """校验过的建议落缓存（pre.json，schema 见 shared.EpicNextCache）；返回文件路径。
    host 读侧 epic-next.ts readPrecache 按 state_key 比对命中（口径互指）。"""
    path = epic_next_precache_path(REPO_ROOT, code)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "ticket_id": ticket_id, "epic": code, "ts": int(time.time()),
        "state_key": state_key, "suggestion": suggestion,
    }, ensure_ascii=False, indent=1) + "\n", "utf-8")
    return str(path)


def _sug_stage_result(kind: str, sug: Dict[str, Any], args: AgentStageArgs,
                      rfile: Path, cache_path: str,
                      evidence_extra: str = "") -> StageResult:
    """校验通过的建议 → StageResult（ok/done 两形态；t260901-19 从 _consume_suggest_result
    提取：rfile 判读与 precache 短路两条路共用同一文案构造，工单台渲染无差异）。
    evidence_extra：短路命中时追加「precache-hit」等标记。"""
    tag = ("；" + evidence_extra) if evidence_extra else ""
    if kind == "done":
        return StageResult(
            status="ok",
            summary="integration 判定立项 %s 已无事可做，可结项：%s%s%s"
                    % (args.epic or "（未关联）", sug["summary"],
                       "（缓存 %s）" % cache_path if cache_path else "", tag),
            evidence="kind=done result_file=%s cache=%s%s"
                     % (rfile, cache_path, (" " + evidence_extra) if evidence_extra else ""))
    return StageResult(
        status="ok",
        summary="预跑下一单建议：%s（模板 %s）%s%s"
                % (sug["title"], sug["workflow"],
                   "（缓存 %s）" % cache_path if cache_path else "", tag),
        report="integration 预跑（merge 签字通过后、落账前）给出下一步建议，"
               "点立项单「继续执行」可直接秒开预填弹层。\n理由：%s"
               % (sug["rationale"] or "（未给理由）"),
        evidence="kind=ok result_file=%s cache=%s%s"
                 % (rfile, cache_path, (" " + evidence_extra) if evidence_extra else ""))


def _precache_hit(args: AgentStageArgs) -> Optional[StageResult]:
    """precache 命中短路（t260901-19）：同立项后续票首跑时 rfile 本就不存在，但上一票
    已把建议写入 <repoRoot>/.suyou/epic-next/<epic>/pre.json（state_key 未变即建议仍
    有效）→ 直接复用，零 spawn 省 token。

    命中条件与校验（disk 文件人手可改，不信任其内容）：
      - pre.json 存在且可解析、state_key 与本次一致、suggestion 过 _parse_suggest_result
        三态校验 + ok 形态模板防幻觉闸——任何一步不过 → 返回 None 落回 spawn（不静默
        降级、不假 ok）；failed 形态缓存（异常态）同样不短路。
    """
    if not args.epic or not args.state_key:
        return None
    ppath = epic_next_precache_path(REPO_ROOT, args.epic)
    if not ppath.is_file():
        return None
    try:
        cache = json.loads(ppath.read_text("utf-8"))
    except Exception:
        return None
    if not isinstance(cache, dict):
        return None
    if str(cache.get("state_key") or "") != args.state_key:
        return None
    raw_sug = cache.get("suggestion")
    if not isinstance(raw_sug, dict):
        return None
    kind, sug, _err = _parse_suggest_result(raw_sug)
    if sug is None or kind == "failed":
        return None
    if kind == "ok" and sug["workflow"] not in TEMPLATE_CLASS_NAMES:
        return None
    return _sug_stage_result(kind, sug, args, Path("(precache)"),
                             str(ppath), evidence_extra="precache-hit")


def _consume_suggest_result(rfile: Path, args: AgentStageArgs) -> Optional[StageResult]:
    """读 + 三态校验 + 落缓存（suggest_next 的判读半，幂等重入与轮询共用）。
    文件不存在 → None（调用方继续轮询）；存在但校验不过 → failed（软失败不抛，
    merge 照常收口——retry_policy=1，抛了只会把失败变成 activity error，不如如实记账）。"""
    if not rfile.is_file():
        return None
    try:
        raw = json.loads(rfile.read_text("utf-8"))
    except Exception as e:
        return StageResult(
            status="failed", summary="预跑结果文件不是合法 JSON：%s" % str(e)[:160],
            evidence="result_file=%s" % rfile)
    kind, sug, err = _parse_suggest_result(raw)
    if sug is None:
        return StageResult(status="failed", summary="预跑建议不合规（%s），软失败跳过" % err,
                           evidence=json.dumps(raw, ensure_ascii=False)[:800])
    if kind == "failed":
        return StageResult(
            status="failed", summary="integration 判定本单给不出下一步建议：%s" % sug["reason"],
            evidence="result_file=%s" % rfile)
    # 防幻觉闸：ok 形态的 workflow 必须在模板清单内（与 host validateSuggestion 同闸，双侧校验）
    if kind == "ok" and sug["workflow"] not in TEMPLATE_CLASS_NAMES:
        return StageResult(
            status="failed",
            summary="预跑建议的模板 %r 不在可用清单内（防幻觉拒收，软失败跳过）" % sug["workflow"],
            evidence="whitelist=%s" % ",".join(sorted(TEMPLATE_CLASS_NAMES)))
    cache_path = _write_precache(args.ticket_id, args.epic, args.state_key, sug) \
        if args.epic and args.state_key else ""
    return _sug_stage_result(kind, sug, args, rfile, cache_path)


@activity.defn
async def suggest_next(args: AgentStageArgs) -> StageResult:
    """预跑下一单建议（t260828-08）：spawn integration 会话（DSH_HEADLESS_SESSION=
    <ticket>-integration，复用 integration_review 的会话上下文——本设计核心收益），
    prompt= workflow 组好的三态契约文本（不走 build_stage_prompt 通用契约）。

    与通用 agent 步的差异：① 跳过 worker settle（只读分析，不落 commit）；
    ② 结果文件是三态契约 JSON 而非 StageResult，判读走 _consume_suggest_result；
    ③ 软失败：超时/进程退出/不合规一律返回 failed 的 StageResult 不抛（merge 照常收口），
    配合 workflow 侧 retry_policy maximum_attempts=1。"""
    rfile = Path(args.result_file)
    rfile.parent.mkdir(parents=True, exist_ok=True)
    cwd = _ws_cwd(args.workspace, args.ticket_id)
    cwd.mkdir(parents=True, exist_ok=True)

    # 幂等：结果文件已存在 → 重新判读并回（Temporal 重试/worker 重启重跑安全；缓存写入幂等）
    res = _consume_suggest_result(rfile, args)
    if res is not None:
        return res

    if os.environ.get("SUYOU_SUGGEST_STUB"):  # 自测桩：自写三态结果文件即判读（零模型调用）
        mode = os.environ["SUYOU_SUGGEST_STUB"]
        stubs = {
            "ok": {"status": "ok", "workflow": "dev-lane", "title": "[stub] 下一单建议",
                   "body": "[stub] 正文", "rationale": "[stub] 理由"},
            "done": {"status": "done", "summary": "[stub] 立项目标已达成"},
            "failed": {"status": "failed", "reason": "[stub] 放弃原因"},
            "invalid": "{not-json",
        }
        payload = stubs["invalid"] if mode == "invalid" else \
            _json_dumps(stubs.get(mode, stubs["failed"]))
        rfile.write_text(payload, "utf-8")
        return _consume_suggest_result(rfile, args)

    # precache 命中短路（t260901-19）：在 stub 之后（stub 是测试专用通道最优先）、
    # spawn 之前——同立项后续票 state_key 未变即复用上一票建议，零 spawn 省 token。
    # 校验不过（损坏/缺字段/模板非法/failed 形态/state_key 不一致）→ None，照常 spawn。
    res = _precache_hit(args)
    if res is not None:
        activity.logger.info("[%s/suggest_next] precache 命中，零 spawn 复用（epic=%s）",
                             args.ticket_id, args.epic)
        return res

    project = await _fetch_ticket_project(args.ticket_id)
    cmd, env = _prepare_agent_spawn(
        cwd, args.role, "", args.ticket_id, rfile.parent,
        "suggest_next_gen%d" % args.gen, project=project)
    cmd.append(args.prompt)
    activity.logger.info("[%s/suggest_next] spawn integration 预跑（cwd=%s）：%s …",
                         args.ticket_id, cwd, " ".join(cmd[:3]))
    logf = open(args.log_file, "a", buffering=1) if args.log_file else subprocess.DEVNULL
    proc = subprocess.Popen(
        cmd, cwd=str(cwd), env=env,
        stdout=logf, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
        start_new_session=True)  # KI-009：独立进程组，见 _reap_agent_proc
    polls = 0
    try:
        while True:
            res = _consume_suggest_result(rfile, args)
            if res is not None:
                return res
            rc = proc.poll()
            if rc is not None:
                return StageResult(
                    status="failed",
                    summary="预跑 integration agent 退出（rc=%s）但未写合规结果，软失败跳过"
                            % rc,
                    evidence="log=%s tail=%s" % (args.log_file, _log_tail(args.log_file)))
            if activity.in_activity():
                activity.heartbeat(json.dumps(
                    {"stage": "suggest_next", "gen": args.gen, "polls": polls,
                     "session_kb": _session_kb(cwd)}))
            polls += 1
            if args.max_polls and polls >= args.max_polls:
                return StageResult(
                    status="failed",
                    summary="预跑等结果文件超时（%d 次轮询 × %ds），软失败跳过"
                            % (polls, POLL_SEC),
                    evidence="result_file=%s log=%s" % (rfile, args.log_file))
            await asyncio.sleep(POLL_SEC)
    finally:
        # KI-009：finally 兜底升级为组粒度全终态回收（四路径都走到这里）
        _reap_agent_proc(proc, args.ticket_id, "suggest_next")


def _log_tail(log_file: str, n: int = 400) -> str:
    try:
        return Path(log_file).read_text("utf-8", errors="replace")[-n:].strip()
    except Exception:
        return ""


# ---------- M16：工作区准备（workflow 第一个 activity） ----------

def _lane_repo_root(cwd: Path) -> Path:
    """泳道所在仓根（跨项目，t260903-10 首战教训）：按路径约定 <repo>/.lane/<id>
    自锚定——多项目工单（项目根≠引擎根）的 worktree add/复用/结算都应对项目仓操作，
    而非引擎仓。不符约定（显式自定义路径/主树/旧相对 payload）回落 REPO_ROOT（旧行为）。"""
    if cwd.parent.name in (".lane", ".worktrees"):  # .lane=新名；.worktrees=旧名（在飞/存量泳道）
        return cwd.parent.parent
    return REPO_ROOT


def _is_worktree_of(p: Path, repo: Optional[Path] = None) -> bool:
    """p 是否**该仓库**（缺省 REPO_ROOT）的已注册 worktree：`git -C repo worktree list --porcelain`
    里必须有 `worktree <p>` 条目（按绝对路径比对）。
    不用 `git -C p rev-parse` 判定——仓库内普通子目录会向上走到仓库根被误判成 worktree。"""
    try:
        proc = subprocess.run(
            ["git", "-C", str(repo if repo is not None else REPO_ROOT), "worktree", "list", "--porcelain"],
            capture_output=True, text=True, timeout=30)
        if proc.returncode != 0:
            return False
        target = p.resolve()
        for line in proc.stdout.splitlines():
            if line.startswith("worktree "):
                try:
                    if Path(line[len("worktree "):]).resolve() == target:
                        return True
                except Exception:
                    continue
    except Exception:
        return False
    return False


# 泳道依赖目录 bootstrap 清单（t260824-12 merge_check 实测踩中）：worktree 不继承
# gitignored 环境目录，verify_lane「依赖在位」（app/node_modules/.bin/tsc）必红。
# 只列泳道内确定性需要的；temporal-poc/.venv 不在列——工单 worker 恒由主仓拉起，
# 泳道内没有消费方（260825 拍板）。
LANE_DEP_SYMLINKS = ("app/node_modules",)


def _ensure_lane_deps(lane_path: Path) -> str:
    """把主仓的 gitignored 依赖目录软链进泳道（幂等）。返回 action 文案后缀
    （"" 或 "+deps:<目录>"），拼进 prepare_workspace 的 action 上报。

    软链=共享约定：泳道内 pnpm install 会写进主仓依赖目录（安装稀少，接受；
    要隔离就在泳道里手工 install 成真目录，本函数见已存在即不动）。
    主仓对应目录不存在（全新克隆）则跳过——verify_lane 的红字会指明原因。"""
    if _lane_repo_root(lane_path) != REPO_ROOT:
        return ""  # 跨项目泳道：依赖清单属引擎所在仓，不外链（t260903-10）
    linked = []
    for rel in LANE_DEP_SYMLINKS:
        src = REPO_ROOT / rel
        dst = lane_path / rel
        if not src.exists() or os.path.lexists(dst):
            continue
        try:
            os.symlink(src, dst)
        except OSError:
            continue  # 软链失败不致命：verify_lane「依赖在位」会给出明确红字
        linked.append(rel)
    return "+deps:%s" % ",".join(linked) if linked else ""


@activity.defn
async def prepare_workspace(prep: WorkspacePrep) -> WorkspacePrepResult:
    """工作区创建/复用（M16：workflow 第一个 activity，agent 不再自己 git worktree add / mkdir）。

    - workspace 无/非 worktree|dir → 主树道，跳过（skipped）；
    - dir → mkdir -p（幂等，ensured）；
    - worktree → 已是本仓库 worktree 则复用（reused）；否则 `git worktree add -b <branch> <path>`
      [基点=base_ref]（created）；失败回执 failed（**不抛**——workflow 转 blocked 交人判读）。
    - worktree 建/复用后跑 _ensure_lane_deps：把主仓 gitignored 依赖目录软链进泳道，
      否则 verify_lane「依赖在位」必红（t260824-12 merge_check 实测踩中）。
    """
    ws = prep.workspace
    if not (isinstance(ws, dict) and ws.get("type") in WORKSPACE_TYPES and ws.get("path")):
        return WorkspacePrepResult(ok=True, kind="main", action="skipped", path="")
    p = Path(str(ws["path"]))
    if not p.is_absolute():
        p = REPO_ROOT / p
    # 跨项目（t260903-10）：worktree add/复用判定对**项目仓**操作（路径约定自锚定），
    # 不再恒锚引擎仓——新单泳道路径已是绝对路径（derive_lane_workspace project_root）。
    repo = _lane_repo_root(p)
    if ws["type"] == "dir":
        try:
            p.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            return WorkspacePrepResult(ok=False, kind="dir", action="failed",
                                       path=str(p), error="mkdir -p %s 失败: %s" % (p, e))
        return WorkspacePrepResult(ok=True, kind="dir", action="ensured", path=str(p))
    # worktree 泳道
    if _is_worktree_of(p, repo):
        return WorkspacePrepResult(ok=True, kind="worktree",
                                   action="reused" + _ensure_lane_deps(p), path=str(p))
    branch = prep.branch or ("lane/" + p.name)
    cmd = ["git", "-C", str(repo), "worktree", "add", "-b", branch, str(p)]
    if prep.base_ref:
        cmd.append(str(prep.base_ref))
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    except Exception as e:
        return WorkspacePrepResult(ok=False, kind="worktree", action="failed",
                                   path=str(p), error="git worktree add 异常: %s" % e)
    if proc.returncode == 0:
        return WorkspacePrepResult(ok=True, kind="worktree",
                                   action="created" + _ensure_lane_deps(p), path=str(p))
    return WorkspacePrepResult(
        ok=False, kind="worktree", action="failed", path=str(p),
        error="git worktree add %s -b %s 失败（目录已存在但非本仓库 worktree？请人工处置）:\n%s"
              % (p, branch, (proc.stderr or proc.stdout or "").strip()[-600:]))


# ---------- 人门段机械准备 ----------

def _proposal_excerpt(proposal_id: str) -> str:
    if not proposal_id:
        return ""
    pf = REPO_ROOT / "pipeline" / "proposals" / (proposal_id + ".md")
    if not pf.is_file():
        return "提案文件缺失: %s" % pf
    text = pf.read_text("utf-8")
    head = text[:800]
    return "提案 %s 开头摘录：\n%s" % (proposal_id, head)


def _workspace_listing(ws: Optional[Dict[str, str]]) -> str:
    if not isinstance(ws, dict) or not ws.get("path"):
        return ""
    p = Path(str(ws["path"]))
    if not p.is_absolute():
        p = REPO_ROOT / p
    if not p.is_dir():
        return "工作空间未建: %s" % p
    try:
        entries = sorted(x.name for x in p.iterdir())[:30]
    except Exception as e:
        return "工作空间列举失败: %s" % e
    return "工作空间 %s 顶层：%s" % (p, "、".join(entries) or "（空）")


def _diff_stat(worktree: str, base_ref: str) -> str:
    if not (worktree and base_ref):
        return ""
    p = Path(worktree)
    if not p.is_absolute():
        p = REPO_ROOT / p
    if not (p / ".git").exists():
        return ""
    try:
        proc = subprocess.run(
            ["git", "-C", str(p), "diff", "--stat", base_ref],
            capture_output=True, text=True, timeout=30)
        out = (proc.stdout or "").strip()
        return ("变更统计（%s vs %s）：\n%s" % (worktree, base_ref, out[-2000:])) if out else ""
    except Exception as e:
        return "diff stat 失败: %s" % e


@activity.defn
async def prepare_human_gate(prep: HumanGatePrep) -> HumanGateContext:
    """人门段机械准备：组装审查上下文（提案摘录/工作空间清单/diff stat），纯机械零判断。"""
    parts: List[str] = [
        "工单 %s（%s）人门段 %s 待签字" % (prep.ticket_id, prep.title, prep.stage_id)]
    for chunk in (_proposal_excerpt(prep.proposal_id),
                  _workspace_listing(prep.workspace),
                  _diff_stat(prep.worktree, prep.base_ref)):
        if chunk:
            parts.append(chunk)
    activity.logger.info("[%s/%s] 人门机械准备完成（%d 段上下文）",
                         prep.ticket_id, prep.stage_id, len(parts) - 1)
    return HumanGateContext(ok=True, context_text="\n\n".join(parts),
                            note="审查上下文已组装（%d 项）" % (len(parts) - 1))


# ---------- dev-lane：merge_check（程序化，无 agent）与 merge（人审后执行） ----------

def _git(args: List[str], cwd: Path, timeout: int = 60) -> subprocess.CompletedProcess:
    return subprocess.run(["git"] + args, cwd=str(cwd),
                          capture_output=True, text=True, timeout=timeout)


def _merge_base_ref(branch: str, repo: Path) -> Tuple[str, str]:
    """白名单 diff 的基线 ref：当前 merge-base(main, branch)。返回 (ref, err)。

    ref 非空 = 成功（正常单输出；多行=畸形，取首行继续并在 err 里留痕）。
    ref 为空 = 解析失败，err 是 fail-closed 红 item 的 detail 文案——调用方
    不得回落任何 ref（回落钉死 base_ref=复活 KI-010；回落字面 main=两点 diff
    下泳道落后即误判），空串也绝不传给 verify_lane。
    （t260901-18：口径详解见 merge_check 第 3 项注释。）
    """
    p = _git(["merge-base", "main", branch], repo)
    if p.returncode != 0 or not (p.stdout or "").strip():
        return "", "merge-base main %s 解析失败 rc=%s：%s" % (
            branch, p.returncode, ((p.stderr or p.stdout or "").strip())[-200:])
    lines = [ln.strip() for ln in p.stdout.strip().splitlines() if ln.strip()]
    ref = lines[0]
    if len(lines) > 1:
        return ref, "merge-base main %s 输出 %d 行（畸形），取首行：%s" % (
            branch, len(lines), ref)
    return ref, ""


def _parse_conflict_files(merge_tree_output: str) -> List[str]:
    """从 `git merge-tree --write-tree` 冲突输出（git≥2.38）解析冲突文件清单（纯函数）。

    输出形态（git 2.50 实测）：首行 tree OID；随后每个冲突文件一段——
    1-3 行「条目行」`<mode> <oid> <stage>\\t<path>`（stage=1 base/2 ours/3 theirs），
    空行后「CONFLICT (content): Merge conflict in <path>」等消息行。
    两类行都解析、并集去重、排序返回（顺序不确定——下游「同批文件反复冲突」
    判定按集合比较，review M6）。解析不到任何文件时返回 []——rc=1 也可能是
    git 异常（bad ref 等），调用方按非冲突红灯处理，不空转消解回路（M1）。"""
    files = set()
    for ln in merge_tree_output.splitlines():
        ln = ln.strip()
        if not ln:
            continue
        m = re.match(r"^CONFLICT \([^)]*\): Merge conflict in (.+)$", ln)
        if m:
            files.add(m.group(1).strip())
            continue
        m = re.match(r"^\d{6} [0-9a-f]{40} [123]\t(.+)$", ln)
        if m:
            files.add(m.group(1).strip())
    return sorted(files)


# merge_check 冲突分类专用的内部标记：第 4 项检查（merge 预演）的 item 前缀，
# 工单台/排查可按此前缀 grep（S3：措辞锚点统一）。
MERGE_REHEARSAL_ITEM = "merge 预演无冲突"

# 项目级扩展检查的配置文件（仓库相对路径；机制在引擎、策略跟项目仓库走，
# 见 merge_check 3.5 节注释与该文件头部说明）。
MERGE_CHECKS_CFG = "server/dsh/merge-checks.yaml"


def _parse_bundle_pairs(text: str) -> List[tuple]:
    """merge-checks.yaml 最小解析（同 model-routes 取舍：只吃固定形状，写坏抛错）。

    只认 bundle_pairs: 下「- src: <前缀>」+「out: <前缀>」成对条目，值裸 token。
    """
    pairs: List[Dict[str, str]] = []
    in_section = False
    cur: Optional[Dict[str, str]] = None
    for raw in text.splitlines():
        ln = raw.replace("\t", "  ").rstrip()
        s = ln.strip()
        if not s or s.startswith("#"):
            continue
        if not ln.startswith(" "):
            in_section = (s == "bundle_pairs:")
            cur = None
            continue
        if not in_section:
            continue
        if s.startswith("- src:"):
            cur = {"src": s[len("- src:"):].strip(), "out": ""}
            pairs.append(cur)
        elif s.startswith("out:") and cur is not None:
            cur["out"] = s[len("out:"):].strip()
        else:
            raise ValueError("merge-checks.yaml 无法解析行: %s" % s)
    return [(p["src"], p["out"]) for p in pairs if p["src"] and p["out"]]


@activity.defn
async def merge_check(args: MergeCheckArgs) -> MergeCheckResult:
    """合并前的程序化检查（260824 dev-lane，无 agent——结论全来自 git/脚本，不信口述）。

    四项全绿才放行到人审 merge：
      1. 泳道分支有 commit（base_ref..branch 非空）——t260824-01 漏的就是这项
         （agent 全程未 commit，旧 verify 门跑主树 diff 为空，全绿假闭环）；
      2. 工作区干净（git status --porcelain 为空）——不许带未提交改动收口；
         KI-009（t260901-25）：判红前先做写集内自愈（见下方 0 号前置段），
         agent 迟写文件 worker 没赶上落盘的，在这里补一刀 settle 再复查。
      3. 泳道内 verify_lane code 绿——跑**泳道副本**的 admin.py（lane 代码+lane 工具），
         不跑主树（主树没泳道改动，跑了等于没测）；
      4. merge-tree 预演无冲突（不落地，只判冲突）。
    另有项目级扩展检查（3.5 节）：读泳道内 server/dsh/merge-checks.yaml，
    无文件=无扩展——检查策略跟项目仓库走，换项目自动不适用。
    红灯不抛：回执交 workflow 转 blocked 等 retry_qc / rework 判读。
    """
    wt = Path(args.worktree) if args.worktree else REPO_ROOT
    if not wt.is_absolute():
        wt = REPO_ROOT / wt
    lane_repo = _lane_repo_root(wt)  # 跨项目（t260903-11 第五枪）：分支/merge-tree 查泳道所属仓
    checks: List[Dict[str, Any]] = []

    # 0. KI-009（t260901-25）：dirty 红灯前自动补 settle（写集内自愈），前置段。
    # 放在 item 1 之前：自愈补的 commit 让 item 1（泳道有 commit）与 item 2 同读
    # 自愈后状态——「补了 commit 却报 0 commit」的时序组合结构上不可能发生。
    # 放行条件：a) 工作区脏且脏文件全部落在工单 write_set 内（写集内自愈，写集外
    # 脏属越界改动，维持 blocked 等人纪律）；b) MERGE_HEAD 不在场（消解期工作区
    # 必脏属正常态，唯一收口是 settle_conflict_resolution，t260826-01 review F1
    # ——这里先自检一次，_settle_worktree_lane 内部护栏是双保险）。
    # 自愈成败判定不看 settle 返回的 note（非 worktree 等场景返回 ""），看自愈后
    # git status 复查；settle 的 git 故障异常包 try 转红 item，保住本 activity
    # 「红灯不抛、回执交 workflow 转 blocked」语义（docstring 见函数尾注）。
    # 每次调用最多自愈一次：自愈后仍脏就如实出红，不内部循环。
    auto_settle_note = ""
    try:
        p = _git(["status", "--porcelain", "-z", "--"] + SETTLE_PATHSPEC, wt)
        dirty_z = p.stdout if p.returncode == 0 else ""
        dirty_files = _dirty_files_from_status_z(dirty_z)
        if p.returncode != 0:
            auto_settle_note = "status 失败: %s" % (p.stderr or "")[-200:]
        elif dirty_files:
            mh = _git(["rev-parse", "--verify", "MERGE_HEAD"], wt)
            if mh.returncode == 0:
                auto_settle_note = "合并进行中（MERGE_HEAD 在场），不自愈"
            elif _dirty_within_write_set(dirty_files, args.write_set):
                try:
                    note = _settle_worktree_lane(
                        wt, args.ticket_id, "merge_check", 0)
                    auto_settle_note = "[auto-settle] %s" % (note or "settle 返回空（见后续复查）")
                except Exception as e:
                    auto_settle_note = ("[auto-settle] settle 异常（转红不抛）: %s: %s"
                                        % (type(e).__name__, e))[-300:]
            else:
                auto_settle_note = "脏文件在 write_set 外，不自愈（越界改动交人工）"
    except Exception as e:  # 自愈前置段自身故障不拦主链：后续 item 照常出红
        auto_settle_note = "自愈前置检查异常: %s: %s" % (type(e).__name__, e)
    if auto_settle_note:
        activity.logger.info("[%s] merge_check 自愈前置：%s", args.ticket_id,
                             auto_settle_note)

    # 1. 泳道有 commit
    try:
        p = _git(["log", "--oneline", "%s..%s" % (args.base_ref, args.branch)], lane_repo)
        n = len([ln for ln in p.stdout.splitlines() if ln.strip()]) if p.returncode == 0 else 0
        checks.append({"item": "泳道分支有 commit（%s..%s）" % (args.base_ref[:7], args.branch),
                       "green": p.returncode == 0 and n > 0,
                       "detail": ("%d 个 commit" % n) if n else
                                 (p.stderr or p.stdout or "0 个 commit").strip()[-300:]})
    except Exception as e:
        checks.append({"item": "泳道分支有 commit", "green": False, "detail": "git log 异常: %s" % e})

    # 2. 工作区干净（SETTLE_PATHSPEC 口径——排除 .dsh/ .suyou/ 引擎运行时目录，
    #    与 settle 代落盘同口径，注释互相指引；agent 的代码改动不会被这两个前缀误盖）
    #    KI-009：改 porcelain -z（NUL 分隔，无 quotePath 引号歧义 / rename 箭头
    #    解析问题），自愈后复查的脏清单也走同一解析（_dirty_files_from_status_z）；
    #    自愈发生时 detail 带 [auto-settle] 标记，账面可见不静默。
    try:
        p = _git(["status", "--porcelain", "-z", "--"] + SETTLE_PATHSPEC, wt)
        if p.returncode == 0:
            dirty = _dirty_files_from_status_z(p.stdout)
            clean = not dirty
            detail = ("干净" if clean else "未提交：%s" % "、".join(dirty[:5]))
            if auto_settle_note:
                detail = "%s ｜ %s" % (detail, auto_settle_note)
            checks.append({"item": "工作区干净（无未提交改动）", "green": clean,
                           "detail": detail})
        else:
            checks.append({"item": "工作区干净（无未提交改动）", "green": False,
                           "detail": "git status 失败: %s" % (p.stderr or "")[-200:]})
    except Exception as e:
        checks.append({"item": "工作区干净", "green": False, "detail": "git status 异常: %s" % e})

    # 3. 泳道内 verify_lane code（跑泳道副本的 admin.py：lane 代码 + lane 工具）
    try:
        # t260901-18（KI-010）× t260901-16 合并解：白名单 diff 的 base 用
        # merge-base(main, branch)（_merge_base_ref，fail-closed）。
        # 根因（t260901-18）：传钉死的 args.base_ref 时，他泳道并进的 main 文件在
        # 泳道 merge main 后出现在 diff 里、又不在本单 write_set → 误判越界。
        # 两层防线的分工：verify_lane 侧（t260901-16）_diff_names 已改三点
        # base...HEAD（字面 main 也安全）；merge_check 侧再显式给 merge-base sha
        # ——两条腿各自独立成立，任一单独回退都不复活 KI-010，且 merge-base sha
        # 对「verify_lane 仍是两点 diff 的旧副本」也免疫（工单快照语义下可能跑到旧
        # 泳道副本）。注意与第 4 项 merge-tree 字面 main 的区别：merge-tree 是三路
        # 运算、内部自算 merge-base，字面 main 无害。
        # t260901-08：补传 base + require_base + write_set——写集白名单在合并闸
        # 按工单 write_set 精判（逐文件上限）、空 base fail-closed，不再静默跳过
        # （260821「无 base 跳过」口径对合并闸作废，仅存于手动调用；verify.yaml
        # write_allow 粗判据仅兜手动/未带写集调用——07/08 越界事故在粗判据下漏网）。
        # 第 1 项 commit 检查仍用钉死 base_ref（语义=泳道有本票产出，防快进误判
        # 0 commit），两项 base 口径分工不同。
        wl_base, wl_err = _merge_base_ref(args.branch, lane_repo)  # 第六枪（t260903-11 二建实雷）：merge-base 也要锚泳道仓
        if not wl_base:
            # fail-closed：红 item 是 merge_check 正常通道，activity 不抛。verify_lane
            # 本轮不跑（tsc/smoke 一并缓，红已定 blocked，重试时恢复）；merge-base
            # 失败时第 4 项 merge-tree main 几乎必然同红，零新增阻塞面。
            checks.append({"item": "写集白名单基线（merge-base main × %s）" % args.branch,
                           "green": False, "detail": wl_err})
        else:
            if wl_err:  # 多行畸形输出：取首行继续，留痕可检索
                activity.logger.info("[%s] %s", args.ticket_id, wl_err)
            lane_admin = wt / "server" / "admin.py"
            admin_bin = str(lane_admin if lane_admin.is_file() else
                             Path(__file__).resolve().parents[2] / "admin.py")  # 第七枪：跨项目无引擎布局
            vp = await asyncio.create_subprocess_exec(  # t260903-09 同雷 async 化（最长 15min 冻结）
                "python3", admin_bin, "call", "verify_lane",
                json.dumps({"lane": "code", "path": str(wt),
                            "base": wl_base, "require_base": True,
                            "write_set": list(args.write_set)}),
                cwd=str(wt), stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
            try:
                vo_b, ve_b = await asyncio.wait_for(vp.communicate(), timeout=900)
                v_stdout, v_stderr = vo_b.decode("utf-8", "replace"), ve_b.decode("utf-8", "replace")
                payload = json.loads(v_stdout)
                res = payload.get("result") or {}
                green = bool(payload.get("ok")) and bool(res.get("green")) and vp.returncode == 0
                detail = "exit=%s red=%s" % (res.get("exit_code"), res.get("red_count"))
            except asyncio.TimeoutError:
                vp.kill(); await vp.wait()
                green, detail = False, "verify_lane 超时（>900s）"
            except json.JSONDecodeError:
                green, detail = False, (v_stderr or v_stdout or "无输出").strip()[-300:]
            checks.append({"item": "泳道内 verify_lane code 绿灯", "green": green, "detail": detail})
    except Exception as e:
        checks.append({"item": "泳道内 verify_lane code 绿灯", "green": False,
                       "detail": "verify_lane 异常: %s" % e})

    # 3.5 项目级扩展检查（策略跟项目仓库走：读泳道内 server/dsh/merge-checks.yaml
    #     ——工单快照语义；无文件=无扩展检查，别的项目不受影响）。
    #     bundle_pairs：src 前缀有改动而 out 产物前缀无改动 → 红（t260827-02 教训：
    #     src/client 改了没重建 lib，合并=假上线）。保持插在 merge 预演之前——
    #     预演必须是 checks 末位（conflict 归类认 checks[:-1] 为「非冲突项」）。
    try:
        cfg = wt / MERGE_CHECKS_CFG
        if cfg.is_file():
            pairs = _parse_bundle_pairs(cfg.read_text("utf-8"))
            if pairs:
                # 同第 3 项白名单口径：三点 main...branch 只看泳道带来的改动，
                # main 侧他人改的 src 不误触发 bundle 新鲜度红（t260901-16）。
                p = _git(["diff", "--name-only", "main...%s" % args.branch],
                         lane_repo)  # 同族锚补：3.5 bundle 新鲜度 diff 锚泳道仓
                changed = p.stdout.split() if p.returncode == 0 else []
                for src, out in pairs:
                    if not any(f.startswith(src) for f in changed):
                        continue  # 本泳道没动这条构建链，不出项（降噪）
                    rebuilt = any(f.startswith(out) for f in changed)
                    checks.append({"item": "bundle 新鲜度（%s → %s）" % (src, out),
                                   "green": rebuilt,
                                   "detail": "src 改动已同批重建产物" if rebuilt else
                                             "src 有改动但产物未同批重建（泳道内 tsdown 重建，settle 代落盘）"})
    except Exception as e:
        checks.append({"item": "bundle 新鲜度（%s）" % MERGE_CHECKS_CFG, "green": False,
                       "detail": "扩展检查异常: %s" % e})

    # 3.6 UI 证据闸（t260828-09，纯机械查、无 agent）：write_set 命中 UI 口径
    #     （shared.is_ui_write_set）而泳道 .suyou/screenshots/ 无 png → 红。
    #     处置指引直接给命令，integration 或 developer 可自行补跑 capture.mjs。
    #     已知盲区（v1 接受）：只查存在性，不校验截图时间戳/内容——防呆靠
    #     integration_review 的看图钩子（审读 prompt 带截图 mtime 清单）。
    #     同样插在 merge 预演之前（预演须保持 checks 末位，见 3.5 注释）。
    try:
        ui_gate_red = False
        if is_ui_write_set(args.write_set):
            shots_dir = wt / UI_EVIDENCE_DIR
            pngs = sorted(shots_dir.glob("*.png")) if shots_dir.is_dir() else []
            ui_gate_red = not pngs
            checks.append({
                "item": "UI 截图证据（%s）" % UI_EVIDENCE_DIR,
                "green": not ui_gate_red,
                "detail": ("%d 张截图在位：%s" % (len(pngs), "、".join(p.name for p in pngs[:5])))
                          if pngs else
                          "UI 票缺截图证据：跑 server/dsh/ui-check/capture.mjs "
                          "--out <worktree>/%s（worker 代跑，只读控制台页面）" % UI_EVIDENCE_DIR})
    except Exception as e:
        checks.append({"item": "UI 截图证据", "green": False, "detail": "证据闸异常: %s" % e})

    # 4. merge-tree 预演无冲突（不落地——只把合并结果写成 tree 对象判冲突，
    #    不改任何工作区/索引；t260826-01：输出解析出冲突文件清单带出给消解回路。
    #    注意：--write-tree 会往主库对象库写 tree/blob（冲突与干净都写），只多
    #    悬空对象、gc 可回收，不算脏（review S1）。
    conflict_files: List[str] = []
    merge_tree_excerpt = ""
    rehearsal_green = False
    try:
        p = _git(["merge-tree", "--write-tree", "main", args.branch], lane_repo)
        rehearsal_green = p.returncode == 0
        if not rehearsal_green:
            out = (p.stdout or "") + ("\n" + p.stderr if p.stderr else "")
            conflict_files = _parse_conflict_files(out)
            merge_tree_excerpt = out.strip()[:1500]
        checks.append({"item": "%s（merge-tree main × %s）" % (MERGE_REHEARSAL_ITEM, args.branch),
                       "green": rehearsal_green,
                       "detail": "无冲突" if rehearsal_green else
                                 ("冲突文件：%s" % "、".join(conflict_files) if conflict_files
                                  else (p.stdout or p.stderr or "有冲突").strip()[-300:])})
    except Exception as e:
        checks.append({"item": MERGE_REHEARSAL_ITEM, "green": False, "detail": "merge-tree 异常: %s" % e})

    green = all(c["green"] for c in checks)
    # t260826-01 冲突自动消解回路：红灯细分两类——
    #   conflict=True：仅 merge 预演项红且解析到非空冲突文件清单 → workflow 自动
    #     打回 implement 消解，不 blocked。判定不以 rc=1 为准（bad ref 等 git
    #     异常也 rc=1 但解析不到冲突文件，误归类会让消解回路空转，review M1）；
    #   conflict=False：其它三项（无 commit/工作区脏/verify_lane 红）任一项红，
    #     或预演红但解析为空 → 维持 blocked 等人。基础问题先交人，不带病消解。
    other_red = any(not c["green"] for c in checks[:-1])
    conflict = (not green) and (not other_red) and (not rehearsal_green) and bool(conflict_files)
    activity.logger.info("[%s] merge_check %s：%s%s", args.ticket_id,
                         "绿灯" if green else "红灯",
                         "；".join("%s=%s" % (c["item"], "绿" if c["green"] else "红") for c in checks),
                         "（冲突类，转自动消解）" if conflict else "")
    return MergeCheckResult(green=green, checks=checks,
                            conflict=conflict, conflict_files=conflict_files,
                            merge_tree_excerpt=merge_tree_excerpt)


# ---------- dev-lane：冲突自动消解回路（t260826-01，worker 代跑 merge / 代落盘） ----------

def _unmerged_files(wt: Path) -> List[str]:
    """泳道工作区里未解冲突的文件清单（git status --porcelain 的 UU/AA/DU/UD 等行）。"""
    p = _git(["status", "--porcelain"], wt)
    if p.returncode != 0:
        return []
    files = set()
    for ln in p.stdout.splitlines():
        if len(ln) >= 3 and ln[:2] in ("UU", "AA", "DU", "UD", "AU", "UA", "DD"):
            files.add(ln[3:].strip().strip('"'))
    return sorted(files)


@activity.defn
async def prepare_conflict_resolution(args: ConflictPrepArgs) -> ConflictPrepResult:
    """worker 代跑 `git merge <base_ref>` 进泳道，把冲突标记文件留在泳道工作区。

    分工（同 implement 步「agent 写、worker 代落盘」契约的延伸）：agent 沙箱写不了
    真 .git（worktree 的 .git 是指向主库的 gitfile，物理上提交不了也合并不了），
    所以合并与提交都由 worker（无沙箱）执行；agent 只编辑工作区里的冲突标记文件。
    本 activity 之后、settle_conflict_resolution commit 之前工作区必脏——此窗口
    不跑 merge_check（workflow 编排严格串行：prep → implement → settle → 回
    merge_check，review S2）。
    竞态兜底：merge 零冲突（rc=0，如 merge_check 与 prep 之间冲突已被消解）→
    already_clean=True 交 workflow 直接回 merge_check 重验；ref 不存在/merge
    异常 → ok=False + error（workflow 转 blocked 交人，不空转回路）。
    """
    wt = Path(args.worktree) if args.worktree else REPO_ROOT
    if not wt.is_absolute():
        wt = REPO_ROOT / wt
    target = args.base_ref or "main"
    p = _git(["rev-parse", "--verify", target], wt)
    if p.returncode != 0:
        return ConflictPrepResult(ok=False, error="合并目标 ref %r 不存在: %s"
                                  % (target, (p.stderr or "").strip()[-200:]))
    p = _git(["merge", "--no-edit", target], wt, timeout=120)
    out = ((p.stdout or "") + "\n" + (p.stderr or "")).strip()
    if p.returncode == 0:
        activity.logger.info("[%s] 冲突消解 prep：merge %s 零冲突（竞态兜底）",
                             args.ticket_id, target)
        return ConflictPrepResult(ok=True, already_clean=True,
                                  merge_output=out[:1500])
    files = _unmerged_files(wt)
    if not files:
        # rc!=0 但无 unmerged 文件 = merge 本身失败（非冲突），如工作区脏被 git 拒
        return ConflictPrepResult(ok=False, error="git merge %s 失败（非冲突）: %s"
                                  % (target, out[-400:]))
    activity.logger.info("[%s] 冲突消解 prep：merge %s 留现场，冲突文件 %d 个：%s",
                         args.ticket_id, target, len(files), "、".join(files[:10]))
    return ConflictPrepResult(ok=True, conflict_files=files,
                              merge_output=out[:1500])


@activity.defn
async def settle_conflict_resolution(args: ConflictSettleArgs) -> ConflictSettleResult:
    """agent 解完冲突后的 worker 代落盘：校验无标记残留 → add + commit 合并提交。

    判定口径（selfcheck C-5 实测修正）：「没解干净」不能看 git status 的 UU/AA 行
    ——agent 沙箱写不了真 .git，编辑完文件后 UU 状态仍在（git 要 add 才认已解）。
    所以本 activity 先代 add，再对**本次合并涉及的文件**（HEAD×MERGE_HEAD diff）
    扫冲突标记残留（^<<<<<<< / ^>>>>>>> / 整行 =======——git 三路合并的 7 字符
    标记形态）。有残留 → ok=False + remaining_files（workflow 记一轮失败，上限/
    同批判定在 workflow 侧）；无残留 → commit 合并提交。add 先于扫描也让重试
    幂等：上一轮已 stage 的残留这一轮照样扫得出（扫描锚定合并涉及文件，不靠
    UU 态）。已知误报面：合并涉及文件里行首恰好是上述标记形态的正当内容
    （如讲 git 冲突的文档）会被判残留——接受，交人工轮兜底。
    """
    wt = Path(args.worktree) if args.worktree else REPO_ROOT
    if not wt.is_absolute():
        wt = REPO_ROOT / wt
    # MERGE_HEAD 不在 = 没有进行中的合并（agent 误把工作区改动当冲突解，或 prep
    # 的 merge 没留现场）——如实上报，不伪造合并提交
    p = _git(["rev-parse", "--verify", "MERGE_HEAD"], wt)
    if p.returncode != 0:
        return ConflictSettleResult(ok=False,
                                    error="无进行中的合并（MERGE_HEAD 不存在），无法落盘合并提交")
    # 合并涉及文件（在 add 前取，add 后 diff HEAD MERGE_HEAD 口径不变）
    p = _git(["diff", "--name-only", "HEAD", "MERGE_HEAD"], wt)
    merge_files = [ln.strip() for ln in p.stdout.splitlines() if ln.strip()] \
        if p.returncode == 0 else []
    p = _git(["add", "-A", "--", "."], wt)
    if p.returncode != 0:
        return ConflictSettleResult(ok=False, error="git add 失败: %s"
                                    % (p.stderr or "")[-300:])
    # .dsh/.suyou 有 gitignore 本不入暂存；reset 摘回是双保险（防老 .gitignore 泳道）
    # ——与 _settle_worktree_lane 同款（SETTLE_PATHSPEC 的排除项不可带进 git add，
    # Apple Git 2.50 对「显式点名 ignored 目录」必报 rc=1，t260828-02 冲突消解轮实测）
    _git(["reset", "-q", "--", ".dsh", ".suyou"], wt)
    remaining = []
    for f in merge_files:
        fp = wt / f
        if not fp.is_file():
            continue  # agent 选择删除该文件（合法解法之一）——尊重删除
        try:
            text = fp.read_text("utf-8", errors="replace")
        except Exception:
            continue
        for ln in text.splitlines():
            if ln.startswith("<<<<<<<") or ln.startswith(">>>>>>>") or ln == "=======":
                remaining.append(f)
                break
    if remaining:
        activity.logger.warning("[%s] 冲突消解 settle：%d 个文件仍有冲突标记残留：%s",
                                args.ticket_id, len(remaining), "、".join(remaining[:10]))
        return ConflictSettleResult(ok=False, remaining_files=sorted(remaining))
    msg = ("%s 冲突消解（第 %d 轮）：worker 代落盘合并提交\n\n"
           "agent 解冲突标记、worker 代 commit（沙箱写不了真 .git）"
           % (args.ticket_id, args.round_no))
    p = _git(["commit", "--no-edit", "-m", msg], wt)
    if p.returncode != 0:
        return ConflictSettleResult(ok=False, error="git commit 失败: %s"
                                    % (p.stderr or p.stdout or "")[-300:])
    head = _git(["rev-parse", "--short", "HEAD"], wt)
    commit = head.stdout.strip() if head.returncode == 0 else ""
    activity.logger.info("[%s] 冲突消解 settle：合并提交落盘 %s（第 %d 轮）",
                         args.ticket_id, commit, args.round_no)
    return ConflictSettleResult(ok=True, commit=commit)


# ---------- KI-006（t260901-26）：squash 收口核心（纯函数，不经 activity 上下文） ----------

# ---------- t260904-09：settle 时刻收口出仓快照（KI-017 引擎侧欠账收口） ----------
# merge 落定后、泳道清理前冻结 token+交付快照到项目级账本：
#   <projects-root>/<key>/data/settle/<票号>.json（与 metrics 缓存同根约定）。
# 幂等：已存在且载荷一致=跳过；不一致=keep-old 不回写（不可变追加语义，
#   重开票增量交付不可见=契约增补段已知边界，reason 的 squash_commit 可发现）。
# 失败软降级：任何异常转 note 拼进 merge warns，绝不阻塞 merge（观测欠账不卡交付，
#   与 ui_evidence 同款 catch-all→log→不阻塞；其余 ui_evidence 面不带——快照单文件
#   无产物族，清理由幂等 keep-old 承担）。
# 命名红线（CLAUDE.md 硬规则⑤）：新 env SANDBAR_SETTLE_SNAPSHOT_DIR 为中性名。

SANDBAR_SETTLE_SNAPSHOT_ENV = "SANDBAR_SETTLE_SNAPSHOT_DIR"


def _settle_snapshot_dir(project_key: str) -> Optional[Path]:
    """快照目录解析（与 metrics.ts resolveSettleDir 同一条根链，两侧注释互指）：
    SANDBAR_SETTLE_SNAPSHOT_DIR ?? SUYOU_METRICS_DIR ?? SANDBAR_PROJECTS_DIR 链
    （perkey_projects_root 内含后两段+home 缺省）——env 替换的是**项目根整体**。
    project_key 为空（Temporal snapshot 查询软降级）→ None，快照跳过并留 note。
    project_key 过 PROJECT_KEY_RE 白名单防路径穿越（与 ticket_data_dir 同款防呆）。"""
    if not project_key or not shared.PROJECT_KEY_RE.match(project_key):
        return None
    root = os.environ.get(SANDBAR_SETTLE_SNAPSHOT_ENV) or os.environ.get("SUYOU_METRICS_DIR") or ""
    if root:
        return Path(root) / project_key / "data" / "settle"
    return shared.perkey_projects_root() / project_key / "data" / "settle"


def _aggregate_lane_usage(wt: Path, ticket_id: str) -> Tuple[Dict[str, Any], str]:
    """聚合泳道会话 usage（TS agent-usage 通路的 Python 等价，口径逐项对齐）：
    - 遍历 <wt>/.dsh/sessions/<slug>/<sub>/session.jsonl.zstd，sub==票号或票号- 前缀
      （同 TS resolveAllSessionFiles）；目录不存在=空集+note，不进入聚合。
    - 只加总 assistant/message 的 data.usage——assistant/chunk 里同名 usage 是同一份，
      两处都加会翻倍（TS 侧钉死的红线，本侧同样适用）。
    - 模型归因：顺序扫描维护当前模型（request/context 的 data.{provider,model}，
      request/header 的 data.header.config.{provider,model} 兜底），缺失记「?」。
    - 坏行跳过；单文件解压失败不毁整体加总（原因拼 note）。
    - 0-usage 有意取舍：快照仍落盘、tokens 全零+tokens_zero 注记（settle 时刻的
      观测欠账也要固化，与读侧「两处皆无→null」语义相异是有意的）。
    - by_stage 不带：引擎侧无 workflow timeline 时间窗真源，恒空对象+by_stage_available
      false 注记（硬造窗口会污染口径）。
    不带 TS 的防穿越界双保险：本侧路径由自身代码构造（wt 来自 activity 入参，
    已过 _ws_cwd/_is_worktree_of 防呆），非用户输入，不重复实现。"""
    zero = {"in": 0, "out": 0, "cacheRead": 0, "by_stage": {},
            "by_model": {}, "by_stage_available": False}
    sess = wt / ".dsh" / "sessions"
    if not sess.is_dir():
        return dict(zero, tokens_zero=True), "无泳道会话目录: %s" % sess
    files: List[Path] = []
    for f in sorted(sess.glob("*/*/session.jsonl.zstd")):
        sub = f.parent.name
        if sub == ticket_id or sub.startswith(ticket_id + "-"):
            files.append(f)
    if not files:
        return dict(zero, tokens_zero=True), "无本票会话文件（%s 下无 %s-*/session.jsonl.zstd）" % (sess, ticket_id)
    total = {"in": 0, "out": 0, "cacheRead": 0}
    by_model: Dict[str, int] = {}
    notes: List[str] = []
    saw_usage = False

    def _num(x: Any) -> int:
        return int(x) if isinstance(x, (int, float)) and not isinstance(x, bool) else 0

    for f in files:
        try:
            p = subprocess.run(["zstd", "-d", "-c", str(f)], capture_output=True,
                               text=True, timeout=60)
            if p.returncode != 0:
                notes.append("%s 解压失败: %s" % (f.name, (p.stderr or "")[-120:]))
                continue
            cur = {"provider": "", "model": ""}
            for raw in (p.stdout or "").split("\n"):
                line = raw.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except ValueError:
                    continue  # 坏行跳过（畸形输入/文件尾正在写）
                t = obj.get("type")
                d = obj.get("data") or {}
                if t == "request/context" and "provider" in d:
                    if isinstance(d.get("provider"), str):
                        cur["provider"] = d["provider"]
                    if isinstance(d.get("model"), str):
                        cur["model"] = d["model"]
                elif t == "request/header":
                    c = (d.get("header") or {}).get("config") or {}
                    if cur["model"] == "" and isinstance(c.get("model"), str):
                        cur["provider"] = c.get("provider") if isinstance(c.get("provider"), str) else cur["provider"]
                        cur["model"] = c["model"]
                elif t == "assistant/message":
                    u = d.get("usage")
                    if not isinstance(u, dict):
                        continue
                    i, o, cr = _num(u.get("inputTokens")), _num(u.get("outputTokens")), _num(u.get("cacheReadTokens"))
                    total["in"] += i
                    total["out"] += o
                    total["cacheRead"] += cr
                    key = "%s/%s" % (cur["provider"] or "?", cur["model"] or "?")
                    by_model[key] = by_model.get(key, 0) + i + o
                    saw_usage = True
        except Exception as exc:  # 单文件失败不毁整体加总
            notes.append("%s 聚合异常: %s" % (f.name, str(exc)[:120]))
    tokens = {"in": total["in"], "out": total["out"], "cacheRead": total["cacheRead"],
              "by_stage": {}, "by_model": by_model, "by_stage_available": False,
              "tokens_zero": not saw_usage}
    note = "；".join(notes)
    if not saw_usage:
        note = (note + "；" if note else "") + "会话无 usage 事件（tokens 记零）"
    return tokens, note


def _squash_snapshot_delivery(repo: Path, commit: str, ticket_id: str) -> Tuple[Dict[str, Any], str]:
    """squash 真身交付快照。前缀校验唯一真源在本纯函数内（review 条件 5）：
    merge_commit 的 subject 首行不以票号开头（真·无内容可收，HEAD=他票 squash）
    → 记零交付 zero_change=true，**不取 numstat**（否则把他票交付记到本票）；
    Temporal 重试态（HEAD=本票上次收口，squash 提交模板保证首 token=票号）
    → 正常取 diff <commit>^1 <commit> --numstat。二进制行（-\t-）跳过求和
    （同 TS parseNumstatTotal）。hash 口径=short（与 _squash_merge 返回值一致）。"""
    p = _git(["log", "-1", "--format=%s", commit], repo)
    if p.returncode != 0:
        return {}, "merge commit %s subject 读取失败: %s" % (commit, (p.stderr or "")[-120:])
    subject = (p.stdout or "").strip()
    bp = _git(["rev-parse", "--short", commit + "^1"], repo)
    base = bp.stdout.strip() if bp.returncode == 0 else ""
    if not subject.startswith(ticket_id):
        return ({"base": base, "add": 0, "del": 0, "commits": 0,
                 "squash_commit": commit, "zero_change": True},
                "收口零变更（%s 为 main 尾提交、非本票交付，message=%r）" % (commit, subject[:60]))
    n = _git(["show", "--numstat", "--format=", commit], repo)
    if n.returncode != 0:
        return {}, "numstat 读取失败: %s" % ((n.stderr or "")[-120:])
    add = 0
    del_ = 0
    for line in (n.stdout or "").split("\n"):
        m = re.match(r"^(\d+|-)\t(\d+|-)\t", line)
        if not m:
            continue
        if m.group(1) != "-":
            add += int(m.group(1))
        if m.group(2) != "-":
            del_ += int(m.group(2))
    return {"base": base, "add": add, "del": del_, "commits": 1,
            "squash_commit": commit, "zero_change": False}, ""


def _freeze_settle_snapshot(repo: Path, wt: Path, ticket_id: str,
                            project_key: str, squash_commit: str) -> str:
    """冻结并出仓 settle 快照（绝不抛，返回 note 人话；空串=无事可记）。
    落盘 tmp+os.replace 原子替换（防双 settle 竞态半文件）。"""
    try:
        # 票 id 形状白名单（t260904-09 打回项 W8）：ticket_id 来自外部 meta，裸拼进
        # 快照文件名会让 `../` 注入上跳目录（integration W8 实证逃出票级 settle
        # 目录）——与 ticket_data_dir 同款 fail-closed：非法即跳过快照+warn note
        # （软降级语义内，不阻塞 merge）。
        if not shared.PROJECT_KEY_RE.match(ticket_id):
            return "settle 快照跳过（ticket_id 形状非法，防路径穿越）: %r" % ticket_id[:60]
        d = _settle_snapshot_dir(project_key)
        if d is None:
            return "settle 快照跳过（无项目 key 或 key 非法）"
        delivery, dnote = _squash_snapshot_delivery(repo, squash_commit, ticket_id)
        tokens, tnote = _aggregate_lane_usage(wt, ticket_id)
        notes = [x for x in (dnote, tnote) if x]
        if not delivery:
            return "settle 快照失败（不阻塞 merge）: " + (dnote or "delivery 不可得")
        payload = {
            "schema_version": "v1",
            "ticket_id": ticket_id,
            "project_key": project_key,
            "squash_commit": squash_commit,
            "settled_at": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()) + "Z",
            "tokens": tokens,
            "delivery": delivery,
        }
        path = d / ("%s.json" % ticket_id)
        if path.exists():
            try:
                old = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                return "settle 快照已存在但不可解析（不可变语义保留旧件，不回写）: %s" % path
            if (old.get("tokens") == tokens and old.get("delivery") == delivery
                    and old.get("squash_commit") == squash_commit):
                return "settle 快照已存在且一致，跳过（幂等）: %s" % path
            return ("settle 快照已存在且内容不一致（不可变语义保留旧件，不回写；"
                    "重开票增量交付须删旧件重 settle）: %s" % path)
        d.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, path)
        note = "settle 快照已落盘: %s" % path
        if notes:
            note += "（" + "；".join(notes) + "）"
        return note
    except Exception as exc:  # catch-all：观测欠账不卡交付
        return "settle 快照失败（不阻塞 merge）: %s" % str(exc)[:200]


def _merge_started(repo: Path) -> bool:
    """判别主树「合并已开始」：MERGE_MSG 在场 或 index 有 unmerged entries。

    KI-006 清理配方的唯一闸门（git 2.50 实测语义）：
      - squash 冲突后 rc=1：MERGE_MSG 存在、ls-files -u 有 stage——合并已开始，
        需要 --quit + reset --merge 才能还原；
      - 未提交改动重叠被拒：无 MERGE_MSG、无 unmerged——合并从未开始，
        现场原样，绝不可 reset（会毁掉主树未提交改动）。
    """
    p = _git(["rev-parse", "-q", "--verify", "MERGE_MSG"], repo)
    if p.returncode == 0:
        return True
    lu = _git(["ls-files", "-u"], repo)
    return bool((lu.stdout or "").strip())


def _squash_merge(repo: Path, wt: Path, branch: str, ticket_id: str,
                  defer_teardown: bool = False, project_key: str = "") -> "MergeResult":
    """squash 收口实现（merge() activity 转调此函数，便于脱离 Temporal 单测）。

    与旧 merge --no-edit 的故障模式取舍（review gen1 意见 3 逐条确认）：
      a) 全路径不抛，返回 MergeResult 交 workflow（红灯转 blocked/打回）；
      b) 失败路径不拆 worktree、不删分支——泳道必须活着等重验；
      c) 泳道清理失败只 warn，聚合进 error 字段，不推翻已完成的收口；
      d) 清理配方幂等（--quit 重复无害；reset --merge 幂等；复查可重跑），
         Temporal 超时重试安全：重跑会走「暂存区无可收内容」分支回填 HEAD 头；
      e) error 精确点名失败环节（防呆/merge/quit/reset/commit/清理验收）。
    清理三段（git 2.50 实测）：squash 冲突无 MERGE_HEAD，merge --abort 不可用；
    --quit 只清 MERGE_MSG 不回滚 index/工作区（ls-files -u 仍非空），故紧跟
    reset --merge HEAD（与真合并 --abort 语义对齐，保留主树无关未暂存改动），
    并以「冲突态已还原」验收：ls-files -u 空 + status 无 unmerged 行（不要求
    全树干净——主树上与合并无关的未暂存改动本来就该保留）。
    """
    # 0) 入参防呆：在碰任何写操作之前（git 会把 - 开头的值当选项解析，
    #    branch 全来自外部 meta，必须挡掉；实测 check-ref-format 拒 - 开头/空/含 ..）
    p = _git(["check-ref-format", "--branch", branch], repo)
    if p.returncode != 0:
        return MergeResult(ok=False, action="failed",
                           error="branch %r 非法（check-ref-format 拒绝）：%s"
                                 % (branch, (p.stderr or "").strip()[-200:]))

    # 0.5) 主树暂存区预检（自测 case E 实测补的防线）：squash 成功会把既有暂存
    #      内容一并卷进出口提交，破坏「一单一提交」语义（revert 本单会带走无关
    #      改动）——有暂存即拒，不动现场（真合并时代 git 自身会拒重叠场景，但这
    #      条对非重叠暂存也兜住，口径更严且 fail-closed）。
    dq0 = _git(["diff", "--cached", "--quiet"], repo)
    if dq0.returncode != 0:
        return MergeResult(ok=False, action="conflict",
                           error="主树有未提交的暂存改动，收口会把它卷进本单提交"
                                 "（破坏一单一提交语义）；请先处置（commit/stash/"
                                 "还原）再收口（主树现场未动）")

    # 1) squash 合并（不自动 commit）
    p = _git(["merge", "--squash", branch], repo, timeout=120)
    out = ((p.stdout or "") + "\n" + (p.stderr or "")).strip()
    if p.returncode != 0:
        if not _merge_started(repo):
            # 合并从未开始（未提交改动重叠等）——只如实上报，绝不动主树现场
            return MergeResult(ok=False, action="conflict",
                               error="git merge --squash %s 未开始即被拒：%s（主树未提交改动原样保留）"
                                     % (branch, out[-400:]))
        # 已开始：清现场（--quit 只清 MERGE_MSG；reset --merge 才回滚 index/工作区
        # 的合并冲突态）。用 --merge 不用 --hard（t260901-26 集成裁决）：--merge 与
        # 真合并的 --abort 语义对齐，只还原本次合并弄脏的部分，主树上与合并无关的
        # 未暂存改动逐字节保留；--hard 会把无关未暂存改动一并抹掉=失败路径静默
        # 丢数据。暂存改动已由 0.5 预检挡在合并前，--merge 不还原暂存的特性无回归面。
        leftover: List[str] = []
        _git(["merge", "--quit"], repo, timeout=60)  # 只看后续冲突态复查，不看它的 rc
        rs = _git(["reset", "--merge", "HEAD"], repo, timeout=60)
        if rs.returncode != 0:
            leftover.append("reset --merge rc=%s：%s"
                            % (rs.returncode, (rs.stderr or "")[-200:]))
        else:
            lu = _git(["ls-files", "-u"], repo)
            st = _git(["status", "--porcelain"], repo)
            if (lu.stdout or "").strip():
                leftover.append("ls-files -u 仍非空：%s" % (lu.stdout or "").strip()[:200])
            # 验收口径只看「冲突态是否还原」（unmerged 行），不看全树干净——
            # 主树上与合并无关的未暂存改动（ M 行）本来就该保留，不是残留
            unmerged_lines = [ln for ln in (st.stdout or "").splitlines()
                              if len(ln) >= 2 and ln[:2] in (
                                  "UU", "AA", "DD", "AU", "UA", "DU", "UD")]
            if unmerged_lines:
                leftover.append("status 仍有 unmerged 行：%s"
                                % "、".join(unmerged_lines[:5]))
        err = "git merge --squash %s 冲突：%s" % (branch, out[-400:])
        if leftover:
            err += "；清理后仍有残留：" + "；".join(leftover)
        return MergeResult(ok=False, action="conflict", error=err)

    # 2) 收口：暂存区无可收内容（重试/内容已等价）→ 不产空提交，回填 HEAD 头
    warns: List[str] = []
    dq = _git(["diff", "--cached", "--quiet"], repo)
    if dq.returncode == 0:
        head = _git(["rev-parse", "--short", "HEAD"], repo)
        merge_commit = head.stdout.strip() if head.returncode == 0 else ""
        warns.append("main 已含本单改动（squash 暂存区无可收内容），未产新提交")
    else:
        # message 必含 lane/<id>：工单台 changes.ts 两形态共用同一 grep 口径定位
        msg = ("%s squash 收口（一单一提交，KI-006）\n\n"
               "来源 %s；审计真源在 Temporal；泳道内小步历史不进 main"
               % (ticket_id, branch))
        c = _git(["commit", "-m", msg], repo, timeout=60)
        if c.returncode != 0:
            return MergeResult(ok=False, action="failed",
                               error="squash 已暂存但 git commit 失败：%s"
                                     "（主树带着暂存改动，需人工处置）"
                                     % ((c.stderr or c.stdout or "")[-300:]))
        head = _git(["rev-parse", "--short", "HEAD"], repo)
        merge_commit = head.stdout.strip() if head.returncode == 0 else ""
    # 2.5) settle 出仓快照（t260904-09，KI-017 引擎侧收口）：commit 落定后、
    #      泳道清理前（此时 .dsh/sessions 尚在）；失败只 warn 不推翻收口，
    #      project_key 缺省（""）时函数内部跳过并留 note——向后兼容零破坏。
    if merge_commit:
        snap_note = _freeze_settle_snapshot(repo, wt, ticket_id, project_key, merge_commit)
        if snap_note:
            warns.append(snap_note)
    # 3) 泳道清理（仅 ok 路径；-D：squash 后 -d 必拒 not fully merged，实测）
    #    M1-3（t260902-02）：defer_teardown=True 时跳过内联清理，交后续
    #    teardown_lane activity（merge→archive→teardown 三段收口）——旧历史
    #    输入缺该字段反序列化回落默认 False = 旧内联清理语义，存量工单零残留
    #    （MergeArgs docstring 记录的 1.18.2 实测依据）。清理失败只 warn 不推翻
    #    已完成的收口（取舍 a）-e) 中 d) 幂等、e) 点名环节两条带过来）。
    if not defer_teardown:
        p = _git(["worktree", "remove", "--force", str(wt)], repo, timeout=60)
        if p.returncode != 0:
            warns.append("worktree remove 失败: %s" % (p.stderr or "").strip()[-200:])
        p = _git(["branch", "-D", branch], repo, timeout=30)
        if p.returncode != 0:
            warns.append("branch -D 失败: %s" % (p.stderr or "").strip()[-200:])
    return MergeResult(ok=True, action="merged", merge_commit=merge_commit,
                       error="；".join(warns))


@activity.defn
async def merge(args: MergeArgs) -> MergeResult:
    """人审签字通过后的真实合并（KI-006 改 squash 收口：main 一单一提交）。

    冲突/故障不抛——回执交 workflow 转 blocked 等人处置；失败路径泳道
    （worktree/分支）不拆不删，留给打回重验。审计真源在 Temporal，main 上
    不再留 merge commit；泳道内小步 commit 与冲突消解回路不受影响。
    defer_teardown=True（M1-3 三段收口）：落账后**不内联清理**，交 teardown_lane。
    """
    wt = Path(args.worktree) if args.worktree else REPO_ROOT
    if not wt.is_absolute():
        wt = REPO_ROOT / wt
    # 项目 key（快照归属目录）：查询失败软降级 "" → _squash_merge 内跳过快照留 note
    project_key = await _fetch_ticket_project(args.ticket_id)
    res = _squash_merge(_lane_repo_root(wt), wt, args.branch, args.ticket_id,  # 第八枪（t260903-11 终建实雷）：squash 进泳道所属仓
                        defer_teardown=bool(args.defer_teardown), project_key=project_key)
    if res.ok:
        activity.logger.info("[%s] squash 落账：%s（%s）%s", args.ticket_id,
                             args.branch, res.merge_commit,
                             ("；清理告警：" + res.error) if res.error else "")
    else:
        activity.logger.warning("[%s] squash 失败：%s", args.ticket_id, res.error)
    return res


# ---------- dev-lane：完结工单数据出仓归档 + 泳道拆除（sandbar M1-3，t260902-02） ----------

# 三类入档路径的扫描归属（口径真源 = shared.py 文件尾注释；自测按这些常量锁）：
#   1) <worktree>/.suyou/stage_*.json  → stages/（stage 结果/结算报告）
#   2) <worktree>/.suyou/screenshots/**/*.png → screenshots/（UI 证据，保相对层级）
#   3) <worktree>/.dsh/sessions/<repo-slug>/* → sessions/（会话落盘事件文件）
# 排除（记入 manifest.excluded_rules，不入档）：agent_*.log、model_patch_*.yml、
# resume_patch_*.yml、.dsh/profiles/**、一切 .credentials.yaml（凭据绝不入档）。
ARCHIVE_EXCLUDED_LOG_RE = re.compile(r"^agent_.*\.log$")


class ArchiveManifestError(Exception):
    """归档 manifest 被篡改（worktree 灰面：file 非 dict / 状态码 / 结构缺失）

    或 manifest 定位失败——**不静默重产不覆盖**（重产即消灭证据），fail-closed
    上抛，workflow 转 blocked 泳道不拆（取舍清单 A-② 第 5 条）。"""


@activity.defn
async def archive_ticket(args: ArchiveArgs) -> ArchiveResult:
    """完结工单数据出仓归档（sandbar M1-3 关键决策 3 本体）。

    归档真源复制到 <SANDBAR_PROJECTS_DIR>/<key>/data/tickets/<id>/（复制非移动，
    泳道拆除由 teardown_lane 执行）+ 写 archive.json manifest（schema v1，字段
    见 shared.ARCHIVE_* 注释）。文件内容按字节级拷贝——结果文件坏 JSON 也原样入档
    （归档是拷贝真源，不解析内容；消费侧读时才判畸形）。

    故障模式取舍（沿用清单，M1-3 review R1 逐条声明）：
      a) 全路径不抛——**不沿用**：归档失败必须 fail-closed 上抛（归档成功是
         拆泳道「不丢报告」的前提，软失败=拆了就丢）。
      b) 损坏 manifest 不许静默重产（灰面，消灭证据）——manifest 已存在且
         畸形/file 非 dict/状态码 → ArchiveManifestError 上抛，不改现场。
      c) 幂等可重跑——manifest 合法存在时读 file 清单校验引用（错项自愈重拷
         + 记 integrity_repaired），Temporal 重试安全。
      d) 缺失目录/文件为软处理——.suyou 或 .dsh 不存在：.suyou 系件数为零且
         无 archive.json 历史 → 落代理文件不静默放过；.dsh/sessions 缺失 →
         manifest.absent 记 absent（同 usage 端点降级口径）；单文件拷失败 →
         fail-closed 上抛（不「半份归档=半丢报告」）。
      e) 错误点名环节——抛错信息含 stage/screenshots/sessions/manifest 段名
         与源/目标路径，blocked 文案可检索。

    legacy=True（archive-legacy 存量诚实过账）：跳过扫描直接写 manifest
    {legacy: true, files: [], absent: ["worktree"], reason}——不伪造不补产。
    """
    res = ArchiveResult()
    dst = shared.ticket_data_dir(args.project_key, args.ticket_id)
    now = time.time()
    src_root = Path(args.worktree) if args.worktree else REPO_ROOT
    if not src_root.is_absolute():
        src_root = REPO_ROOT / src_root

    def _now_iso() -> str:
        import datetime
        return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")

    if args.legacy:
        # 存量诚实过账：泳道已拆除，只落 manifest 本体（files 空、reason 说明）
        reason = "归档前泳道已拆除，stage 报告不可恢复（存量工单诚实过账）"
        dst.mkdir(parents=True, exist_ok=True)
        manifest = {"schema": "v1", "ticket_id": args.ticket_id, "legacy": True,
                    "archived_at": _now_iso(), "meta": dict(args.meta or {}),
                    "files": [], "absent": ["worktree"], "reason": reason,
                    "excluded_rules": list(shared.ARCHIVE_EXCLUDED_RULES)}
        (dst / "archive.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        res.ok = True
        res.retained = False
        res.archive_path = str(dst)
        activity.logger.info("[%s] legacy 诚实过账归档：%s（%s）", args.ticket_id, dst, reason)
        return res

    # ---- 扫描三类入档 ----
    files: List[Dict[str, Any]] = []
    absent: List[str] = []
    staged_specs: List[Tuple[str, str]] = []   # (src, dst_rel)
    p_suyou = src_root / ".suyou"
    p_dsh = src_root / ".dsh"
    if not p_suyou.is_dir():
        # .suyou 缺失 → 前两系件数为零：该泳道 stage_*.json 历史上无真档可拷，
        # 不静默放过——落明牌代理文件，收口受 stage_acceptance 硬项约束（implement
        # 段必写结果文件），泳道拆除时灰面暴露无处遁形。
        files.append({"src": ".suyou/stage_implement_gen0.json", "dst": "stages/stage_implement_gen0.json", "bytes": 0})
        files.append({"src": ".suyou/agent_create_plan_gen0.log", "dst": "stages/agent_create_plan_gen0.log", "bytes": 0})
    if p_suyou.is_dir():
        # stage 结果文件（排除 .log/.yml 由清单规则记 excluded，不扫描入档）
        for f in sorted(p_suyou.glob("stage_*.json")):
            staged_specs.append((str(f), "stages/" + f.name))
        # UI 截图证据（保 screenshots/ 相对层级）
        for f in sorted(p_suyou.glob("screenshots/**/*.png")):
            staged_specs.append((str(f),
                                 "screenshots/" + str(f.relative_to(p_suyou / "screenshots"))))
    if not p_dsh.is_dir():
        absent.append(".dsh/sessions（会话目录不存在）")
    if p_dsh.is_dir():
        p_sess = p_dsh / "sessions"
        if not p_sess.is_dir():
            absent.append(".dsh/sessions（会话目录不存在）")
        else:
            for f in sorted(p_sess.iterdir()):
                if f.is_dir():          # repo-slug 子目录
                    for sf in sorted(f.rglob("*")):
                        if sf.is_file() and ARCHIVE_EXCLUDED_LOG_RE.match(sf.name):
                            continue   # agent spawn 日志（-gen.log）不入档
                        if sf.is_file():
                            staged_specs.append(
                                (str(sf), "sessions/" + sf.relative_to(p_sess).as_posix()))
                elif f.is_file() and not ARCHIVE_EXCLUDED_LOG_RE.match(f.name):
                    staged_specs.append((str(f), "sessions/" + f.name))
    manifest_path = dst / "archive.json"
    if manifest_path.is_file():
        # 幂等重跑：读既有清单校验（b) 损坏 manifest 不许静默重产；c) 合法清单
        # 校验引用、错项自愈重拷）
        try:
            prev = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            raise ArchiveManifestError(
                "manifest 已存在但不可解析（%s）——不静默重产（消灭证据），"
                "人工处置：%s: %s" % (manifest_path, type(e).__name__, e))
        prev_files = prev.get("files") if isinstance(prev, dict) else None
        if prev_files is None or not isinstance(prev_files, list) \
                or any(not isinstance(x, dict) for x in prev_files):
            raise ArchiveManifestError(
                "manifest 已存在但 file 字段非 dict 清单（灰面，可能已覆写本单归档）"
                "——不静默重产，人工处置：%s" % manifest_path)
        # 引用校验 + 自愈：清单里引用的 dst 文件全数还在？不在则重拷
        for ent in prev_files:
            drel = str(ent.get("dst") or "")
            if not drel:
                raise ArchiveManifestError(
                    "manifest 条目缺 dst（%s）——灰面，人工处置" % manifest_path)
            dfile = dst / drel
            if not dfile.is_file():
                raise ArchiveManifestError(
                    "manifest 引用缺失（%s 无 %s）——可能已被覆写/删，不静默重产，"
                    "人工处置" % (dst, drel))
    dst.mkdir(parents=True, exist_ok=True)
    for src, drel in staged_specs:
        dfile = dst / drel
        dfile.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dfile)
        # 字节数以 copy2 后 stat 真值记（归档侧真值，不取源端 racy 值）
        files.append({"src": os.path.relpath(src, src_root),
                      "dst": drel, "bytes": dfile.stat().st_size})
    # 代理文件（.suyou 缺失灰面）：目录落位 = 接管，内容如实写代理说明
    for ent in list(files):
        if ent["bytes"] == 0:
            dfile = dst / ent["dst"]
            dfile.parent.mkdir(parents=True, exist_ok=True)
            dfile.write_text(
                "代理文件：本泳道归档时 %s 不存在（灰面——泳道有 stage_acceptance"
                "硬项却未产 stage_*.json），真实内容不可恢复，不伪造不补产。\n"
                "（sandbar M1-3 archive_ticket 占位语义）\n" % ent["src"],
                encoding="utf-8")
    manifest = {"schema": "v1", "ticket_id": args.ticket_id, "legacy": False,
                "archived_at": _now_iso(), "meta": dict(args.meta or {}),
                "files": files, "absent": absent,
                "excluded_rules": list(shared.ARCHIVE_EXCLUDED_RULES)}
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2),
                             encoding="utf-8")
    res.ok = True
    res.archive_path = str(dst)
    res.files = files
    res.absent = absent
    activity.logger.info("[%s] 归档完成：%s（%d 件%s）",
                         args.ticket_id, dst, len(files),
                         "，会话目录缺失" if absent else "")
    return res


@activity.defn
async def teardown_lane(args: MergeArgs) -> MergeResult:
    """拆泳道（M1-3 三段收口的最后一段；公式原样=M1-2 时的 _squash_merge step 3）。

    只在 merge（squash 落账）与 archive_ticket 都成功后调用（workflow 编排保证）；
    失败不抛——回执 error 点名 worktree/branch 环节，workflow 侧只记 evidence
    （泳道残留为可回收垃圾：本体已进 archive.json 清单与 data/ 真源，人工清单可扫，
    不阻塞工单收口）。清理配方幂等（--quit 重复无害；已不存在的工作区/分支 rc=0
    视为成功）——Temporal 重试安全（沿用取舍 d)）。
    """
    repo = REPO_ROOT
    wt = Path(args.worktree) if args.worktree else REPO_ROOT
    if not wt.is_absolute():
        wt = REPO_ROOT / wt
    branch = args.branch
    # 入参防呆同 _squash_merge step 0（branch 来自外部 meta）
    p = _git(["check-ref-format", "--branch", branch], repo)
    if p.returncode != 0:
        return MergeResult(ok=False, action="failed",
                           error="branch %r 非法（check-ref-format 拒绝）：%s"
                                 % (branch, (p.stderr or "").strip()[-200:]))
    warns: List[str] = []
    p = _git(["worktree", "remove", "--force", str(wt)], repo, timeout=60)
    if p.returncode != 0:
        warns.append("worktree remove 失败: %s" % (p.stderr or "").strip()[-200:])
    p = _git(["branch", "-D", branch], repo, timeout=30)
    if p.returncode != 0:
        warns.append("branch -D 失败: %s" % (p.stderr or "").strip()[-200:])
    return MergeResult(ok=True, action="teardown",
                       merge_commit="", error="；".join(warns))


# ---------- dev-lane：审读判据机械化（t260829-07，纯 git/文件零 LLM） ----------

REVIEW_GATE_GIT_TO_SEC = 30   # 单条 git 命令兜底超时


@activity.defn
async def verify_review_gate(args: ReviewGateArgs) -> ReviewGateResult:
    """integration_review ok 后的机械复核（dev_lane REVIEW_GATE_PATCH_ID 门内调用）。

    报错精确性三态（方案 v3 B1）：
      - git 查询失败 → git_error 非空、lane_commits=-1（禁止用 0 表达「查不了」，
        否则 git 故障会被误报成「实现未落盘」）；
      - screenshots 路径存在但异常（是文件/不可读）→ shots_path_error 非空、
        png_count=-1（不可断言「证据缺失」）；路径不存在 = 没拍，等价 0 png；
      - 查询成功 → lane_commits / png_count 给真值，dev_lane 侧据判定打回。
    本 activity 只回数据不做业务判定（闸逻辑在 workflow，确定性编排可测）。"""
    res = ReviewGateResult()
    wt = Path(args.worktree) if args.worktree else REPO_ROOT
    if not wt.is_absolute():
        wt = REPO_ROOT / wt

    async def _run_git(*cmd: str) -> "tuple[int, str, str]":
        proc = await asyncio.create_subprocess_exec(
            "git", "-C", str(wt), *cmd,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        try:
            out_b, err_b = await asyncio.wait_for(
                proc.communicate(), timeout=REVIEW_GATE_GIT_TO_SEC)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            return -1, "", "git %s 超时（%ds）" % (cmd[0], REVIEW_GATE_GIT_TO_SEC)
        return (proc.returncode or 0,
                (out_b or b"").decode("utf-8", "replace").strip(),
                (err_b or b"").decode("utf-8", "replace").strip())

    if not wt.is_dir():
        res.git_error = "泳道 worktree 不存在：%s" % wt
        res.passed = False
        res.reasons.append(res.git_error)
        return res
    rc, out, err = await _run_git("rev-list", "--count", "HEAD")
    if rc != 0:
        res.git_error = "git rev-list 失败（rc=%s）：%s" % (rc, (err or out)[-200:])
        res.passed = False
        res.reasons.append(res.git_error)
        return res
    try:
        res.lane_commits = int(out)
    except ValueError:
        res.git_error = "git rev-list 输出非整数：%r" % out[:80]
        res.passed = False
        res.reasons.append(res.git_error)
        return res

    shots_dir = wt / UI_EVIDENCE_DIR
    if shots_dir.exists() and not shots_dir.is_dir():
        res.shots_path_error = "%s 存在但不是目录" % shots_dir
        res.png_count = -1
    elif not shots_dir.is_dir():
        res.png_count = 0  # 目录不存在 = 没拍，等价 0 png（可断言缺失）
    else:
        try:
            res.png_count = len([p for p in shots_dir.iterdir()
                                 if p.is_file() and p.suffix.lower() == ".png"])
        except OSError as e:
            res.shots_path_error = "%s 不可读：%s: %s" % (shots_dir, type(e).__name__, e)
            res.png_count = -1
    return res


# ---------- dev-lane：UI 截图证据（t260828-09，worker 代跑 capture.mjs） ----------

# 子进程超时（秒）：capture.mjs 自身对页面还有更细的超时；本值兜死整个截图流程。
# 注意与 workflow 侧 activity 超时的关系：activity 的 start_to_close 必须**明显大于**
# 本值（dev_lane.UI_EVIDENCE_TO=180s vs 120s），否则 Temporal 先杀 activity，
# 下面的子进程超时回收路径永远走不到（review_plan 意见 1：超时叠超时）。
UI_CAPTURE_TIMEOUT_SEC = 120


def _shot_lines(shots_dir: Path, names: List[str]) -> List[str]:
    """「名（mtime iso）」清单——activity 侧算好带回（workflow 侧零 IO，不能查盘）。"""
    import datetime
    lines = []
    for n in names:
        try:
            mt = datetime.datetime.fromtimestamp((shots_dir / n).stat().st_mtime,
                                                 datetime.timezone.utc)
            lines.append("%s（%s）" % (n, mt.isoformat(timespec="seconds")))
        except OSError:
            lines.append("%s（时间未知）" % n)
    return lines


def _archive_shots(args: UiEvidenceArgs, shots_dir: Path, names: List[str]) -> str:
    """截图归档到主树 <REPO_ROOT>/.suyou/evidence/<ticket_id>/（t260829-02）。

    泳道 merge 后拆 worktree，report 里 `![](…/tickets/<id>/evidence/<file>)` 引图
    不死链靠这份归档（host 只读端点读主树归档处，泳道在时兜底读泳道）。归档失败
    **不抛不翻 ok**——软失败语义与 capture 一致（证据闸仍看泳道目录），返回人话说明
    由调用方拼进 detail 留痕。"""
    if not names:
        return ""
    # env 覆盖（自测指向临时目录，防污染真主树；node 侧 evidence 端点同名 env 互指）
    base = os.environ.get("SUYOU_EVIDENCE_DIR") or (REPO_ROOT / EVIDENCE_DIR)
    dst = Path(base) / args.ticket_id
    try:
        dst.mkdir(parents=True, exist_ok=True)
        for n in names:
            shutil.copy2(shots_dir / n, dst / n)
        return "；已归档 %d 张到主树 %s" % (len(names), dst)
    except OSError as e:
        return "；归档失败（不拦主链）：%s: %s" % (type(e).__name__, e)


def _preserve_failed_shots(args: UiEvidenceArgs, shots_dir: Path) -> Tuple[List[str], List[str], str]:
    """capture 失败时保留尽力视图（t260901-02 顺手项）：已拍 PNG 不再随失败蒸发。

    三方口径兼得（方案 gen1 修 1）：
      - 机械闸 review_gate_verdict 数泳道 shots_dir on-disk png（shared.py L1308，
        merge_check 时重查）——归档**成功**的图从泳道 unlink 移出 → png_count 归 0 →
        闸红灯不变，残缺视图不骗过闸（软失败不假通过）；
      - 归档到主树 .suyou/evidence/<ticket>/ → 抽屉可读、worktree 拆后不蒸发；
      - **按文件粒度**：归档失败的图**留在泳道**（png_count>0 同样闸红，且图可被
        人工捞回——归档失败还 unlink=图彻底蒸发，正是本单根治的病，review 意见 1）。
    返回（成功归档并移出的文件名， 归档失败留在泳道的文件名， 人话说明）。不抛。"""
    try:
        pngs = sorted(p.name for p in shots_dir.glob("*.png")) if shots_dir.is_dir() else []
    except OSError:
        return [], [], "；尽力视图收集失败：screenshots 目录不可读"
    if not pngs:
        return [], [], ""
    moved: List[str] = []
    kept: List[str] = []
    try:
        base = os.environ.get("SUYOU_EVIDENCE_DIR") or (REPO_ROOT / EVIDENCE_DIR)
        dst = Path(base) / args.ticket_id
        dst.mkdir(parents=True, exist_ok=True)
        for n in pngs:
            try:
                shutil.copy2(shots_dir / n, dst / n)
            except OSError as e:
                kept.append(n)
                activity.logger.warning("[%s] 尽力视图归档失败留泳道：%s: %s",
                                        args.ticket_id, n, e)
                continue
            try:
                (shots_dir / n).unlink()
            except OSError:
                kept.append(n)  # unlink 失败：图留泳道，闸红不假通过
                continue
            moved.append(n)
        note = "；capture 失败，尽力视图 %d 张已归档主树并移出泳道（机械闸维持红灯）" % len(moved) if moved else ""
        if kept:
            note += "；归档/移出失败 %d 张留泳道（可人工捞回）：%s" % (len(kept), "、".join(kept))
        return moved, kept, note
    except OSError as e:
        # 归档目录级失败：全部留泳道（闸红 + 可捞回，安全侧）
        return [], pngs, "；尽力视图归档失败（留泳道）：%s: %s" % (type(e).__name__, e)


def _ui_capture_stub(args: UiEvidenceArgs, shots_dir: Path) -> UiEvidenceResult:
    """SUYOU_UI_CAPTURE_STUB=1：自写两张假 png 即返回（不起 node/浏览器，零依赖）。
    仿 SUYOU_AGENT_STUB（_run_agent_stage_impl 同款先例），供自测/干跑。"""
    shots_dir.mkdir(parents=True, exist_ok=True)
    names = []
    for name in ("console-default.png", "console-chat.png"):
        p = shots_dir / name
        # 最小合法 PNG（1x1 像素），glob("*.png") 可命中
        p.write_bytes(bytes.fromhex(
            "89504e470d0a1a0a0000000d4948445200000001000000010806000000"
            "1f15c4890000000a49444154789c63000100000500010d0a2db4"
            "0000000049454e44ae426082"))
        names.append(name)
    note = _archive_shots(args, shots_dir, names)
    return UiEvidenceResult(ok=True, shots=names, shot_lines=_shot_lines(shots_dir, names),
                            detail="[stub] SUYOU_UI_CAPTURE_STUB=1，假截图两张（自测/干跑）" + note)


@activity.defn
async def prepare_ui_evidence(args: UiEvidenceArgs) -> UiEvidenceResult:
    """UI 票截图证据（t260828-09）：worker（无沙箱）代跑 ui-check/capture.mjs，
    截控制台默认页 + chat 态两张图落 <worktree>/.suyou/screenshots/。

    只读红线：capture.mjs 只 GET 打开控制台页面并做导航点击，不提交表单、
    不发工单、不碰任何端口；env SUYOU_CONSOLE_URL 指向被测环境（缺省 3099，
    测试环境 3199）。

    失败**不抛**：依赖缺失/浏览器探测不到/超时/非零退出一律回执 ok=False，
    阻塞语义交给 merge_check 证据闸（UI 票无 png → 红灯），本步不拦主链。

    子进程终态回收（对照 agent spawn 通路 _run_agent_stage_impl）：
      正常退出 → 读回执；非零退出 → ok=False 回执；超时 → kill + ok=False；
      activity 取消（asyncio.CancelledError）→ kill + 再抛（Temporal 语义）；
      finally 兜底 proc 存活即 terminate/kill，不留孤儿浏览器/node 进程。"""
    wt = Path(args.worktree) if args.worktree else REPO_ROOT
    if not wt.is_absolute():
        wt = REPO_ROOT / wt
    shots_dir = Path(args.screenshots_dir) if args.screenshots_dir else wt / UI_EVIDENCE_DIR

    if os.environ.get("SUYOU_UI_CAPTURE_STUB") == "1":
        res = _ui_capture_stub(args, shots_dir)
        activity.logger.info("[%s] ui_evidence stub：%s", args.ticket_id, res.detail)
        return res

    # t260829-02：capture 固定从**主树**跑（playwright-core 等 node_modules 只在主树
    # 装过，泳道 checkout 没有也不装——t260829-01 实测泳道内跑直接软失败）。输出目录
    # --out 与 cwd 仍是泳道（审读/merge_check 证据闸口径不变）。
    # t260829-07：优先 capture-lane.mjs 一键隔离台（自动挑端口/boot/拆台，不依赖
    # 外部控制台）；缺失或失败软降级回退直跑 capture.mjs（旧环境仍可用），降级
    # 路径写 detail 不静默（自举：本票 merge 前即走旧逻辑软失败+人可手工补）。
    ui_check_dir = REPO_ROOT / "server" / "dsh" / "ui-check"
    lane_script = ui_check_dir / "capture-lane.mjs"
    script = REPO_ROOT / "server" / "dsh" / "ui-check" / "capture.mjs"
    if not script.is_file():
        return UiEvidenceResult(ok=False, detail="capture.mjs 不存在（主树）：%s" % script)
    env = dict(os.environ)
    env.setdefault("SUYOU_CONSOLE_URL", "http://127.0.0.1:3099")
    candidates = []
    if lane_script.is_file():
        candidates.append((["node", str(lane_script), "--lane", str(wt),
                            "--out", str(shots_dir)], "capture-lane（隔离台）"))
    candidates.append((["node", str(script), "--url", env["SUYOU_CONSOLE_URL"],
                        "--out", str(shots_dir)], "capture.mjs（直连 %s）" % env["SUYOU_CONSOLE_URL"]))
    detail_tail = ""
    detail_parts: List[str] = []   # t260831-02 第 11 轮：逐候选累加，不再相互覆盖
    for i, (cmd, label) in enumerate(candidates):
        proc = None
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd, cwd=str(wt), env=env,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
            try:
                out_b, err_b = await asyncio.wait_for(proc.communicate(), timeout=UI_CAPTURE_TIMEOUT_SEC)
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
                run_fail = "%s 超时（%ds），进程已 kill" % (label, UI_CAPTURE_TIMEOUT_SEC)
            except asyncio.CancelledError:
                proc.kill()
                await proc.wait()
                raise  # activity 取消：清理后按 Temporal 语义上抛
            else:
                out = (out_b or b"").decode("utf-8", "replace").strip()
                err = (err_b or b"").decode("utf-8", "replace").strip()
                run_fail = "" if proc.returncode == 0 else \
                    "%s 退出码 %s：%s" % (label, proc.returncode, (err or out)[-400:])
                if not run_fail:
                    pngs = sorted(p.name for p in shots_dir.glob("*.png")) if shots_dir.is_dir() else []
                    if not pngs:
                        run_fail = "%s 报成功但 %s 无 png：%s" % (label, UI_EVIDENCE_DIR, out[-300:])
            if not run_fail:
                activity.logger.info("[%s] ui_evidence（%s）：%s", args.ticket_id, label, "、".join(pngs))
                note = _archive_shots(args, shots_dir, pngs)
                return UiEvidenceResult(ok=True, shots=pngs, shot_lines=_shot_lines(shots_dir, pngs),
                                        detail="%s：截图 %d 张：%s%s" % (label, len(pngs), "、".join(pngs), note))
            detail_tail = run_fail
        except Exception as e:  # 基础设施故障（node 不在/权限等）：回执不抛，闸来红灯
            detail_tail = "%s 启动失败：%s: %s" % (label, type(e).__name__, e)
        finally:
            if proc is not None and proc.returncode is None:
                proc.terminate()  # 兜底：任何未走到回收的路径不留孤儿进程
                try:
                    await asyncio.wait_for(proc.wait(), timeout=10)
                except asyncio.TimeoutError:
                    proc.kill()
        detail_parts.append("%s → %s" % (label, detail_tail))
        if i + 1 < len(candidates):
            activity.logger.info("[%s] ui_evidence %s 失败，降级下一候选：%s",
                                 args.ticket_id, label, detail_tail[:200])
    # 尽力视图保留（t260901-02）：候选全败后，已拍 PNG 归档主树 + 成功归档的移出
    # 泳道（闸 png_count 归 0 维持红灯），归档失败的留泳道可人工捞回。
    moved, _kept, keep_note = _preserve_failed_shots(args, shots_dir)
    return UiEvidenceResult(ok=False, shots=moved, shot_lines=_shot_lines(shots_dir, moved),
                            detail="；".join(detail_parts) + keep_note)


# worker 注册清单：每 stage 名一个 activity + 人门准备 + 工作区准备（M16 首个 activity）
# + dev-lane 的 merge_check/merge（260824：合并前程序化检查与人审后的真实合并）
# + 冲突消解两活动（t260826-01：worker 代跑 merge 留现场 / 代落盘合并提交，review M2 注册）
# + UI 截图证据（t260828-09：worker 代跑 capture.mjs，仅 UI 票由 workflow 调用）
AGENT_STAGE_ACTIVITIES = [_make_stage_activity(s) for s in AGENT_STAGE_IDS]

# ---- 集成测试机制（t260829-07 后续）：机械测试步 / 统一落盘 / 仲裁 / 验收走查 ----

@activity.defn
async def settle_lane(args: SettleLaneArgs) -> SettleLaneResult:
    """汇合点统一代落盘（并行分叉期 implement/design 都 skip_settle，此处一次收口）：
    实现改动 + 测试集（integration/）同一 commit 落泳道分支。幂等：工作区干净则 no-op。

    t260901-16 修正①：相对 worktree 路径按 REPO_ROOT 锚定（同 verify_review_gate /
    run_integration_tests 口径）——此前直接 Path(args.worktree) 按 worker 进程 cwd
    （server/dsh/temporal-poc）解析，_is_worktree_of 匹配不上已注册 worktree。
    t260901-16 修正②：不匹配时不许静默回退主树——回退意味着「在该落盘的泳道上
    什么都没做还报干净」（主树本来就干净 → no-op 假绿，并行分叉票的产物全漏落盘，
    t260901-16 第一轮集成测试 2 哨兵红实锤），比报错更糟。改为 raise，交 Temporal
    重试/上层失败可见。"""
    wt = Path(args.worktree) if args.worktree else REPO_ROOT
    if not wt.is_absolute():
        wt = REPO_ROOT / wt
    wt_repo = _lane_repo_root(wt)  # 跨项目：按约定锚项目仓（t260903-10 二次实雷——漏此点曾致死票）
    if not _is_worktree_of(wt, wt_repo):
        raise RuntimeError(
            "settle_lane: worktree %r（解析为 %s）不是其归属仓（%s）的已注册 worktree，"
            "拒绝回退主树代落盘（静默回退=该落盘的泳道什么都不落还报干净，t260901-16 实锤）"
            % (args.worktree, wt, wt_repo))
    cwd = wt
    note = _settle_worktree_lane(cwd, args.ticket_id, args.stage_id, args.gen)
    rc = _git(["rev-list", "--count", "HEAD"], cwd)
    commits = int(rc.stdout.strip() or -1) if rc.returncode == 0 else -1
    return SettleLaneResult(note=note, lane_commits=commits)


BATCH_TIMEOUT_SEC = int(os.environ.get("SUYOU_INTEG_BATCH_TIMEOUT_SEC") or 5400)


async def _run_scenarios(wt: Path, ticket_id: str) -> IntegrationRunResult:
    """薄壳（宿主令 t260902 薄壳化）：声明读取/命令执行/契约解析全在 verify_lane lane=integ
    （单份实现+单份解析器），本函数只下单+把工具 JSON 翻译成 IntegrationRunResult
    （字段口径不变：ran/passed/failed/details[{name,cmd,exit,output_tail}]，arbitrate 无感）。"""
    admin = Path(__file__).resolve().parents[2] / "admin.py"
    # t260903-09 实雷（宿主首诊命中）：async 活动里禁止阻塞 subprocess.run——
    # 曾把 worker 事件循环冻满整套件时长，查询全体 8s 超时（诊断笔记
    # notes/diag-query-starvation.md）。全 async 化：create_subprocess + wait_for，
    # 超时先杀再报。
    p = await asyncio.create_subprocess_exec(
        "python3", str(admin), "call", "verify_lane",
        json.dumps({"lane": "integ", "path": str(wt)}),
        cwd=str(wt), stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    try:
        p_out_b, p_err_b = await asyncio.wait_for(
            p.communicate(), timeout=BATCH_TIMEOUT_SEC + 300)
    except asyncio.TimeoutError:
        p.kill(); await p.wait()
        return IntegrationRunResult(error="场景执行器整体超时（>%ds）" % BATCH_TIMEOUT_SEC)
    p_stdout = p_out_b.decode("utf-8", "replace")
    p_stderr = p_err_b.decode("utf-8", "replace")
    try:
        payload = json.loads(p_stdout)
    except json.JSONDecodeError:
        return IntegrationRunResult(error="verify_lane integ 无有效输出（exit=%s）：%s"
                                    % (p.returncode, (p_stdout + p_stderr)[-2000:]))
    res = payload.get("result") or {}
    if not payload.get("ok") or res.get("err"):
        return IntegrationRunResult(error=str(res.get("err") or "未知错误"))
    out = IntegrationRunResult()
    out.ran = int(res.get("ran") or 0)
    out.passed = int(res.get("pass") or 0)
    out.failed = int(res.get("fail") or 0)
    out.details = [{"name": s.get("name", ""), "cmd": "", "exit": int(s.get("exit") or 0),
                    "output_tail": s.get("output_tail") or ""}
                   for s in (res.get("scenarios") or [])]
    activity.logger.info("[%s] 场景汇总：ran=%s pass=%s fail=%s", ticket_id, out.ran, out.passed, out.failed)
    return out


@activity.defn
async def run_integration_tests(args: IntegrationRunArgs) -> IntegrationRunResult:
    """机械集成测试步（t260829-07 后续）：跑项目声明场景执行器（integration/run_scenarios.py），
    纯 subprocess 零 LLM。结果交 arbitrate（integration）三态判定——不在此判对错。"""
    wt = Path(args.worktree) if args.worktree else REPO_ROOT
    if not wt.is_absolute():
        wt = REPO_ROOT / wt
    return await _run_scenarios(wt, args.ticket_id)


@activity.defn
async def arbitrate(args: AgentStageArgs) -> StageResult:
    """仲裁步（t260829-07 后续）：integration 读机械测试结果，三态判定——
    pass / tests-fault（自己迭代测试集，改动随本步 settle 落盘）/ code-fault
    （集成测试报告在 report，打回 implement）。prompt 由 workflow 组好
    （含机械测试结果 JSON），spawn 复用 integration 会话（上下文连续）。
    verdict 编码契约：summary 首个 ``verdict=<值>`` 标记（FLOW_BRIEF 明示）。"""
    rfile = Path(args.result_file)
    rfile.parent.mkdir(parents=True, exist_ok=True)
    cwd = _ws_cwd(args.workspace, args.ticket_id)
    project = await _fetch_ticket_project(args.ticket_id)
    cmd, env = _prepare_agent_spawn(
        cwd, args.role, "", args.ticket_id, rfile.parent,
        "arbitrate_gen%d" % args.gen, project=project)
    cmd.append(args.prompt)
    logf = open(args.log_file, "a", buffering=1) if args.log_file else subprocess.DEVNULL
    activity.logger.info("[%s/arbitrate] spawn integration 仲裁（gen%d，cwd=%s）",
                         args.ticket_id, args.gen, str(cwd))
    proc = subprocess.Popen(cmd, cwd=str(cwd), env=env,
                            stdout=logf, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                            start_new_session=True)  # KI-009：独立进程组，见 _reap_agent_proc
    polls = 0
    try:
        while True:
            if rfile.is_file():
                res = _read_result(rfile)
                if res is not None:
                    _patch_result_prompt(rfile, args.prompt)
                    # KI-009：settle 之前先 reap——迟写文件收干净再落盘（竞态窗源头）
                    _reap_agent_proc(proc, args.ticket_id, "arbitrate")
                    # tests-fault 的测试集迭代随本步 settle 落盘（提交的代码资产）。
                    # t260903-02 ②：并行分叉期 skip_settle=True 跳过（防止把走查边
                    # 半成品一起代落盘），统一落盘由 workflow 的单点 settle_lane 承担。
                    if not args.skip_settle:
                        note = _settle_worktree_lane(cwd, args.ticket_id, args.stage_id, args.gen)
                        if note:
                            res.evidence = (res.evidence + "\n[worker settle] " + note).strip()
                    return res
            rc = proc.poll()
            if rc is not None:
                raise RuntimeError("arbitrate agent 退出（rc=%s）但未写结果文件 %s（日志 %s）"
                                   % (rc, rfile, args.log_file))
            activity.heartbeat(json.dumps({"stage": "arbitrate", "gen": args.gen,
                                           "polls": polls, "session_kb": _session_kb(cwd)}))
            polls += 1
            if args.max_polls and polls >= args.max_polls:
                raise RuntimeError("等仲裁结果超时（%d 轮询）：%s" % (polls, rfile))
            await asyncio.sleep(POLL_SEC)
    finally:
        # KI-009：兜底回收升级为组粒度（原 terminate+wait+kill 只收直接子进程）
        _reap_agent_proc(proc, args.ticket_id, "arbitrate")


@activity.defn
async def acceptance_walkthrough(args: AgentStageArgs) -> StageResult:
    """验收走查步（t260829-07 后续）：测试通过后 integration 以用户视角走查新功能、
    写验收报告（供人审门查阅）。walkthrough 实证由 worker 前置产出——先跑
    capture-lane 隔离台实拍（泳道 build，截图落 .suyou/screenshots/acceptance/），
    输出注入 prompt；agent 判读截图/DOM 断言写报告（StageResult 契约：
    status=ok + report=验收报告 / status=failed + report=走查发现的代码问题）。
    agent 沙箱跑不了浏览器（t260829-02/-06 两次实测），浏览器一律 worker 代跑。"""
    rfile = Path(args.result_file)
    rfile.parent.mkdir(parents=True, exist_ok=True)
    cwd = _ws_cwd(args.workspace, args.ticket_id)
    # 前置：capture-lane 隔离台实拍（best-effort——失败注入说明，agent 按无截图判定）
    cap_out = cwd / ".suyou" / "screenshots" / "acceptance"
    cap_note = ""
    try:
        lane = str(args.worktree or cwd)
        cproc = await asyncio.create_subprocess_exec(  # t260903-09 同雷 async 化（浏览器实拍分钟级）
            "node", str(REPO_ROOT / "server" / "dsh" / "ui-check" / "capture-lane.mjs"),
            "--lane", lane, "--out", str(cap_out),
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        try:
            co_b, ce_b = await asyncio.wait_for(cproc.communicate(), timeout=UI_CAPTURE_TIMEOUT_SEC)
            cap_note = co_b.decode("utf-8", "replace")[-1500:] + ce_b.decode("utf-8", "replace")[-500:]
            if cproc.returncode != 0:
                cap_note = "capture-lane 退出码 %s：%s" % (cproc.returncode, cap_note)
        except asyncio.TimeoutError:
            cproc.kill(); await cproc.wait()
            cap_note = "capture-lane 超时（>%ss）" % UI_CAPTURE_TIMEOUT_SEC
    except Exception as e:
        cap_note = "capture-lane 启动失败：%s: %s" % (type(e).__name__, e)
    project = await _fetch_ticket_project(args.ticket_id)
    cmd, env = _prepare_agent_spawn(
        cwd, args.role, "", args.ticket_id, rfile.parent,
        "acceptance_gen%d" % args.gen, project=project,
        # t260903-02 ②：ticket-stage 专用会话 key——与并发仲裁边不同会话，双进程
        # 不同写一个 session 文件（取舍记录：走查会话不进 agent-live/agent-usage
        # 的 ticket-role 定位，内容仍可从结果文件/日志取）。
        session_key="%s-acceptance" % args.ticket_id)
    cmd.append(args.prompt)
    logf = open(args.log_file, "a", buffering=1) if args.log_file else subprocess.DEVNULL
    activity.logger.info("[%s/acceptance_walkthrough] spawn integration 验收走查（gen%d）",
                         args.ticket_id, args.gen)
    proc = subprocess.Popen(cmd, cwd=str(cwd), env=env,
                            stdout=logf, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                            start_new_session=True)  # KI-009：独立进程组，见 _reap_agent_proc
    polls = 0
    try:
        while True:
            if rfile.is_file():
                res = _read_result(rfile)
                if res is not None:
                    _patch_result_prompt(rfile, args.prompt)
                    # KI-009：返回前 reap——走查报告不落账（.suyou 口径内），但迟写
                    # 的意外工作区脏不能留给 merge_check 与活进程赛跑
                    _reap_agent_proc(proc, args.ticket_id, "acceptance_walkthrough")
                    return res
            rc = proc.poll()
            if rc is not None:
                raise RuntimeError("acceptance agent 退出（rc=%s）但未写结果文件 %s（日志 %s）"
                                   % (rc, rfile, args.log_file))
            activity.heartbeat(json.dumps({"stage": "acceptance_walkthrough", "gen": args.gen,
                                           "polls": polls, "session_kb": _session_kb(cwd)}))
            polls += 1
            if args.max_polls and polls >= args.max_polls:
                raise RuntimeError("等验收报告超时（%d 轮询）：%s" % (polls, rfile))
            await asyncio.sleep(POLL_SEC)
    finally:
        # KI-009：兜底回收升级为组粒度（原 terminate+wait+kill 只收直接子进程）
        _reap_agent_proc(proc, args.ticket_id, "acceptance_walkthrough")



ALL_AGENT_ACTIVITIES = AGENT_STAGE_ACTIVITIES + [
    prepare_human_gate, prepare_workspace, merge_check, merge,
    prepare_conflict_resolution, settle_conflict_resolution,
    # M1-3（t260902-02）：三段收口——merge 只落账，archive_ticket 出仓，teardown_lane 拆泳道。
    archive_ticket, teardown_lane,
    # 立项下一单预跑（t260828-08）：prepare 读档案/算 state_key，suggest_next 只读分析。
    # suggest_next 不进 AGENT_STAGE_IDS——不走 stage 工厂（prompt 由 workflow 组好，
    # 判读走三态契约而非 StageResult），activity 名即 stage id 供 dev_lane 直调。
    prepare_epic_next, suggest_next,
    prepare_ui_evidence,
    verify_review_gate,
    # 集成测试机制（t260829-07 后续）：settle_lane=汇合点统一落盘；
    # run_integration_tests=机械测试步（零 LLM）；arbitrate/acceptance_walkthrough
    # 为 integration 专用 agent 步（prompt 由 workflow 组好，走会话复用），
    # 不进 AGENT_STAGE_IDS（自定义结果判读）。
    settle_lane, run_integration_tests, arbitrate, acceptance_walkthrough,
]
