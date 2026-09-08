"""lib_retire.py — t260904-08 模板退役场景共享库（词表 / 扫描面 / 豁免 / 离线夹具）。

供本票 sc_template_face_narrowing.py 与 sc_template_retire_no_revival.py 共用；
lib_ 前缀文件不登记场景清单（约定胜过推断，lint L5 豁免）。

零第三方依赖：仅 stdlib。temporalio 相关检查由场景自行分态（venv 探测，
缺失=打印 ENV_FAIL 并 exit 2（三态契约：缺环境绝不 exit 0 假绿——KI-020③
泳道 venv 缺口是已知环境事实）。

设计取舍（防误报，见各注释）：
- 扫描词表只收**无歧义**退役记号：四退役类名 + content-pipeline/content_pipeline。
  裸词 proofread/regression/cleanup **不入词表**——它们分别是分工 kind
  （KIND_LABELS/KIND_MODELS，t260902-07 路由测试在用）、测试词汇（static
  regression pin）、通用函数名（lib_gate.cleanup），全局禁会大量误报；
  模板 id 语义的复活由真源三表收窄 + 文件退场 + 拒收面文案三道独立守卫承担。
- v1 步1 ContentPipelineWorkflow 是**幸存类**（不在删除面），其类名不在词表。
"""
from __future__ import annotations

import json
import os
import pathlib
import subprocess
import sys

REPO = pathlib.Path(__file__).resolve().parents[2]
POC = REPO / "server" / "engine"
WORKFLOWS_DIR = REPO / "server" / "workflows"
TOOLS_DIR = REPO / "server" / "tools"
INTEG_DIR = REPO / "integration"

# 四退役模板（宿主令 260904；dev-lane 保留，dispatcher-scan 非工单巡检不在删除面）
RETIRED_TEMPLATE_IDS = ("content-pipeline", "proofread", "regression", "cleanup")
RETIRED_CLASS_NAMES = ("ContentPipelineTicketWorkflow", "ProofreadWorkflow",
                       "RegressionWorkflow", "CleanupWorkflow")
SURVIVOR_CLASS_NAMES = ("ContentPipelineWorkflow", "DispatcherScanWorkflow")  # v1 步1 + 巡检

# 扫描词表（无歧义退役记号；取舍见模块 docstring）
SCAN_TOKENS = ("content-pipeline", "content_pipeline", "ContentPipelineTicketWorkflow",
               "ProofreadWorkflow", "RegressionWorkflow", "CleanupWorkflow")

# 扫描面（写集五面中与模板可用面相关的部分；.suyou/notes 历史快照不入面）  # naming-compat
SKIP_DIRS = {".venv", "__pycache__", ".dsh", ".suyou", "out", "bin", "node_modules"}  # naming-compat
DOC_TWO = (
    "docs/design/工单工作流台设计.md",
    "docs/design/deepseek_harness_and_temporal_based_multi-agent_mechanism.md",
)

# 整文件豁免（每条都有声明依据，见 sc_template_retire_no_revival docstring）
ALLOW_FILES = {
    # v1 向后兼容演示面（gen1 方案声明保留；dispatcher-scan 同文件共存）
    "server/engine/workflows.py",
    "server/engine/demo_happy.py",
    "server/engine/demo_fail.py",
    "server/engine/demo_schedule.py",
    "server/engine/demo.sh",
    "server/engine/demo_cli.sh",
    "server/engine/demo_durability.sh",
    # 退役标注面（README/docs；场景另验标注在位，防豁免黑洞）
    "server/engine/README.md",
    "server/workflows/README.md",
    "docs/design/工单工作流台设计.md",
    "docs/design/deepseek_harness_and_temporal_based_multi-agent_mechanism.md",
    # v1 留存引擎样例（gen0 评审 R1 裁定：测 build_dispatch_prompt+STAGE_CLAUSES
    # 留存面，非模板可用性）与其知识常量 docstring（历史断链形态描述）
    "integration/t260904-03/lib_dispatch_prompt.py",
    "integration/t260904-03/sc_dispatch_composition_integrity.py",
    "integration/t260904-03/sc_dispatch_knowledge_constant_and_linked.py",
    # 场景注册表 intent 文本（描述退役事实本身）
    "integration/run_scenarios.py",
    # 历史对照夹具（gen0 评审 C1：KI-035 新制下 workflow_id 不选路，纯构造输入）
    "server/engine/tests/test_t260904_03_t01_dispatch_header_indexed.py",
}


def rel_of(path) -> str:
    return str(pathlib.Path(path).resolve().relative_to(REPO)).replace(os.sep, "/")


def allow(rel: str, line: str) -> bool:
    """单行豁免判定。返回 True=该行允许出现退役记号（不计违规）。"""
    if rel.startswith("integration/t260904-08/"):
        return True  # 本票场景自身（词表/意图文本）
    if rel in ALLOW_FILES:
        return True
    # shared.py 留存面：数据表键（GateSpec/STAGE_CLAUSES/STAGE_DISPATCH_KIND 的
    # (模板,段) 元组键，gen1 方案声明全部留存不动）+ v1 workflow id 前缀字面量
    # （pipeline_wf_id 的 f"content-pipeline:<id>"，仅被声明保留的 v1 演示面消费）
    # ——命中即豁免；未命中**不提前返回**，继续落到通用标记规则
    # （shared.py 自己的退役注释/真源表头注也靠标记豁免——20260904 实测教训：
    #  分支提前 return 会把带标记的行误判为违规）
    if rel == "server/engine/shared.py":
        if ('("content-pipeline"' in line or '("regression"' in line
                or '("proofread"' in line or "content-pipeline:" in line):
            return True
    # 通用规则：带**退役语义标记**（退役/已删/260904）即豁免——注释、docstring、
    # 报错文案、工具描述串同样能标注退役（gen1 验收口径「已退役注释与历史引用」
    # 的语义机械化：判红的是声称可用面，不是提到退役事实本身）
    return ("退役" in line or "已删" in line or "260904" in line)


def iter_face_files():
    """枚举扫描面全部文件（场景自检面完整性，防面配置漂移假绿）。"""
    for base, exts in ((POC, (".py", ".sh", ".md")),
                       (WORKFLOWS_DIR, (".yaml", ".md")),
                       (TOOLS_DIR, (".py",)),
                       (INTEG_DIR, (".py", ".mjs"))):
        for root, dirs, names in os.walk(base):
            dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
            for n in sorted(names):
                if n.endswith(exts):
                    yield pathlib.Path(root) / n
    for d in DOC_TWO:
        yield REPO / d


def scan_lines(rel: str, lines):
    """对给定行序列做退役记号扫描（可注入，供自证红绿）。返回 [(lineno, line, tokens)]。"""
    out = []
    for i, line in enumerate(lines, 1):
        if allow(rel, line):
            continue
        hits = [t for t in SCAN_TOKENS if t in line]
        if hits:
            out.append((i, line.rstrip(), hits))
    return out


def scan_repo():
    """全扫描面扫描。返回 [(rel, lineno, line, tokens)] 违规清单。"""
    out = []
    for f in iter_face_files():
        rel = rel_of(f)
        try:
            lines = f.read_text("utf-8").splitlines()
        except (OSError, UnicodeDecodeError):
            continue  # 二进制/不可读不入面
        out.extend((rel, i, ln, toks) for (i, ln, toks) in scan_lines(rel, lines))
    return out


def venv_python():
    """引擎 venv 解释器（本树 .venv → 主 checkout .venv 回落）；无则 None。

    client.py 模块顶 import temporalio（KI-029 同族事实），CLI 级检查必须 venv；
    worktree 常态无 .venv，回落主 checkout：--git-common-dir 在 worktree 返回主库
    .git 路径（绝对或相对 ".git"），取其父目录=主 checkout 根。"""
    cand = POC / ".venv" / "bin" / "python"
    if cand.is_file():
        return str(cand)
    try:
        common = subprocess.run(["git", "rev-parse", "--git-common-dir"], cwd=str(REPO),
                                capture_output=True, text=True, timeout=10).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return None
    if not common:
        return None
    p = pathlib.Path(common)
    if not p.is_absolute():
        p = REPO / p
    p = p.resolve()
    root = p.parent if p.name == ".git" else p
    alt = root / "server" / "engine" / ".venv" / "bin" / "python"
    return str(alt) if alt.is_file() else None


def load_shared():
    """加载 engine/shared.py（纯 stdlib 模块，独立可载；ticket._shared 同款
    spec_from_file_location 手法——py3.9 dataclasses 需注册 sys.modules）。"""
    import importlib.util
    spec = importlib.util.spec_from_file_location("_retire_shared", str(POC / "shared.py"))
    mod = importlib.util.module_from_spec(spec)
    sys.modules["_retire_shared"] = mod
    spec.loader.exec_module(mod)
    return mod


def load_ticket_tool():
    """加载 server/tools/ticket.py（stdlib-only 模块），返回模块（含 run(args)）。"""
    import importlib.util
    spec = importlib.util.spec_from_file_location("_retire_ticket", str(TOOLS_DIR / "ticket.py"))
    mod = importlib.util.module_from_spec(spec)
    sys.modules["_retire_ticket"] = mod
    spec.loader.exec_module(mod)
    return mod


def run_client(py, sub, args, env=None, timeout=60):
    """spawn <py> client.py <sub> <argsJSON>（node.ts cli 同款口径）。返回 (rc, out)。"""
    e = dict(os.environ)
    if env:
        e.update(env)
    p = subprocess.run([py, str(POC / "client.py"), sub, json.dumps(args)],
                       env=e, cwd=str(REPO), capture_output=True, text=True, timeout=timeout)
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def parse_out_json(out):
    """从输出取第一行 JSON 对象（client.py 单行回执口径）；取不到返回 {}。"""
    for ln in (out or "").splitlines():
        ln = ln.strip()
        if ln.startswith("{"):
            try:
                return json.loads(ln)
            except Exception:
                continue
    return {}


def stage_project_registry(tmp_root, key="sandbar-it-26090408"):
    """staged 机器级项目注册表（SANDBAR_PROJECTS_DIR 目录模式，KI-032 硬闸前提）。

    返回 (registry_root, project_dir)。project.yaml 形状=shared.parse_project_file
    契约：schema v1 + project 列表条目（key/name/dirs），key 与目录名全等，
    dirs[0] 即 project_root 锚（必须真实存在）。"""
    root = pathlib.Path(tmp_root)
    proj_dir = root / key
    proj_dir.mkdir(parents=True, exist_ok=True)
    (root / key / "project.yaml").write_text(
        "schema: v1\n"
        "project:\n"
        "  - key: %s\n"
        "    name: 集成测试夹具项目（t260904-08 模板退役场景）\n"
        "    dirs:\n"
        "      - %s\n" % (key, proj_dir),
        "utf-8")
    return str(root), str(proj_dir)
