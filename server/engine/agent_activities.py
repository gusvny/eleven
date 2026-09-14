"""agent_activities — agent stages and human-gate preparation activities under the
"stage = activity" design (ticket t260822-m11).

Architecture: one activity per stage —
  - Agent stages: activity name = stage name (create_plan/implement/…), all sharing
    the generic implementation `_run_agent_stage_impl`: spawn a headless agent
    process (`dsh --profile sandbar-headless "<dispatch prompt>"`, cwd = the ticket
    workspace), then poll the result file + activity.heartbeat().
    **Idempotent**: if the result file (.sandbar/stage_<stage>_gen<N>（老泳道 .suyou 粘滞）.json）已存在则直接读文件返回——  # naming-compat
    safe to re-run after Temporal retries / worker restarts; a rework re-run gets a
    fresh file via gen+1 (a true re-run).
  - Human-gate stage: `prepare_human_gate` only does mechanical preparation
    (proposal excerpt / workspace listing / diff stat); the signature wait lives in a
    workflow-level wait_condition (the right answer for awaiting external input).
  - Workspace stage: `prepare_workspace` is **the first activity of every ticket
    workflow** — the workspace is created/reused by the engine, the agent no longer
    does it itself:
      worktree lane → `git worktree add` (already exists and belongs to this repo →
      reuse, idempotent); dir isolated directory → `mkdir -p` (idempotent); main-tree
      path → skip.
    Failure **does not raise** (the receipt goes back to the workflow to turn blocked
    and wait for retry_qc / rework triage).

Result-file format (the delivery contract written into the dispatch prompt):
  {"status":"ok|failed","summary":…,"deliverables":[…],"files_changed":[…],"evidence":…}
  files_changed must be a **non-empty array of paths** (ticket t260904-18, KI-049
  gate ②) — an empty array, or a bare string (which iterates character-by-character
  into a fake list of single chars), both trip the write-set refresh red light on the
  spot (meta write_set_refresh_fault); tickets that genuinely changed no files
  declare it up front via allow_empty_write_set.

Worker-side settling (tickets t260824-01/-02): the headless agent sandbox cannot
write the real .git (a worktree's .git is a gitfile pointing at the main repo's
.git/worktrees/<id>, outside the agent's writable scope), so "the agent commits
itself" is physically impossible — the agent is forced to build a fake .git-local
repo to fake it. So the commit is not part of the dispatch contract: once the agent
stage has the result file, the worker (unsandboxed) calls `_settle_worktree_lane`
to settle deterministically on the agent's behalf (isolate the fake repo + fold the
workspace changes into a single commit); merge_check then inspects the real
post-settle state.

Self-test / demo: with `SANDBAR_AGENT_STUB=1` the activity writes its own result
file and returns (no agent process spawned). The dispatch command can be overridden
via `SANDBAR_AGENT_CMD` (shlex-split; default `dsh --profile sandbar-headless`).
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
import agent_runtime  # 容器执行面传输层（t260913-04）：stdlib-only；其内不得 import 本包避免环
import authz_gates
import failure_protocol
import path_gates
import shared
from shared import (
    REPO_ROOT,
    STAGE_DISPATCH_KIND,
    WORKSPACE_TYPES,
    AgentStageArgs,
    ArchiveArgs,
    ArchiveResult,
    ConflictPrepArgs,
    ConflictPrepResult,
    ConflictSettleArgs,
    ConflictSettleResult,
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
    TEST_STUB_ENV_KNOBS,
    WORKER_ROUTING_ENV_KNOBS,
    UI_EVIDENCE_DIR,
    ui_evidence_dir,
    evidence_base,
    lane_dot_path,
    mirror_to_legacy,
    EVIDENCE_DIR,
    load_ui_evidence,
    normalize_files_changed,
    UiChangedPathsArgs,
    UiChangedPathsResult,
    UiEvidenceArgs,
    UiEvidenceDeclArgs,
    UiEvidenceDeclResult,
    UiEvidenceResult,
    WorkspacePrep,
    WorkspacePrepResult,
    match_ui_paths,
    model_route_for,
    rebase_write_set,
    build_repo_worktrees,
    is_multi_repo_layout,
    resolve_repos_for_paths,
    roles_dir_for_spawn,
    routes_file_for_spawn,
)

POLL_SEC = 5
INTEG_CMD_TIMEOUT_SEC = int(os.environ.get("SANDBAR_INTEG_CMD_TIMEOUT_SEC") or 900)
DSH_CMD = shlex.split(os.environ.get("SANDBAR_AGENT_CMD") or "dsh --profile sandbar-headless")


def _src_dsh_home() -> Path:
    """Copy-source home for profiles/credentials/settings: prefer the DSH_HOME the
    worker inherited; if that directory is missing (the console sandbox's temp home
    got wiped, ticket t260828-05) fall back to the real home — otherwise the profile
    is silently copied empty and dsh starts up reporting the profile missing."""
    env_home = os.environ.get("DSH_HOME")
    if env_home and Path(env_home).is_dir():
        return Path(env_home)
    return Path.home() / ".dsh"


def _session_jsonl_torn(path: Path) -> bool:
    """Line-by-line probe of a session file (ticket t260905-10): stream-decompress
    with `zstd -dc` (never load it whole) and json.loads each line — any line that is
    not valid JSON (including a mid-decompression blowup: the trailing line is
    necessarily truncated into invalid JSON) means torn frames inside a healthy
    frame, True; every line valid (including an empty file, or a complete line with
    no trailing newline) means healthy, False.
    Blank lines are skipped, not judged (avoid false quarantines — the reverse
    accident is more routine than a miss; valid JSONL contains no bare blank lines,
    so skipping only loosens the check, never tightens it)."""
    proc = subprocess.Popen(["zstd", "-dc", str(path)],
                            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    out = proc.stdout
    try:
        for raw in out:  # type: ignore[union-attr]
            line = raw.decode("utf-8", errors="replace").strip()
            if not line:
                continue
            try:
                json.loads(line)
            except ValueError:
                return True
        return False
    finally:
        # Full terminal-state cleanup: every path (read to end / torn mid-read /
        # reader-side exception) closes the fd, kills the leftover zstd, and reaps via wait().
        if out is not None:
            out.close()
        if proc.poll() is None:
            proc.kill()
        proc.wait()


def _quarantine_session_file(local_dsh: Path, f: Path, reason: str) -> None:
    """坏会话档挪 <cwd>/.sandbar/quarantine/（老泳道 .suyou 粘滞） 留档（挪不删），reason 进告警文案。  # naming-compat
    If the move fails, leave the file in place silently — a create with the same id
    will collide again, but the plugin-side fallback already keeps that non-fatal
    (existing stance unchanged)."""
    qdir = lane_dot_path(local_dsh.parent, "quarantine", create=True)
    try:
        qdir.mkdir(parents=True, exist_ok=True)
        dst = qdir / ("torn-%s-%s" % (f.parent.name, f.name))
        shutil.move(str(f), str(dst))
        activity.logger.warning("[sessions] 撕裂会话文件已隔离（%s）：%s", reason, dst)
    except OSError:
        pass


def _quarantine_torn_sessions(local_dsh: Path) -> None:
    """Quarantine torn session files before spawn (ticket t260829-06: an agent killed
    mid-write leaves torn zstd frames behind, and both resume and a same-id create
    then die on corrupt input, wedging the whole step). Bad files are moved to
    <cwd>/.sandbar/quarantine/（老泳道 .suyou 粘滞） 留档，让「同 id 新建」回落走得通（上下文丢但流程活）。  # naming-compat

    Two layers of quarantine (ticket t260905-10):
    1. `zstd -t` checks frame integrity — torn frames get quarantined right away;
    2. if the frames are intact, probe line by line (_session_jsonl_torn) —
       **intact frames ≠ intact content**: a truncated JSONL record (ticket
       t260906-05, same shape of wedge) is invisible to zstd -t and dies on JSON
       parsing after decompression. Bad files take the same quarantine path
       (_quarantine_session_file); only the reason text differs."""
    sessions = local_dsh / "sessions"
    if not sessions.is_dir():
        return
    for f in sessions.rglob("session.jsonl.zstd"):
        r = subprocess.run(["zstd", "-t", str(f)], capture_output=True)
        if r.returncode == 0:
            if _session_jsonl_torn(f):
                _quarantine_session_file(local_dsh, f, "torn-jsonl")
            continue
        _quarantine_session_file(local_dsh, f, "torn-frame")


# Project key whitelist (credential exit, M1-2): same character set as PROJECT_KEY_RE
# in server/project-registry.ts, and it also blocks ../ path traversal (per-key
# credential paths splice in a directory name).
# The source of truth moved up into shared.py (ticket t260902-02, M1-3; the archive
# path uses it too); this keeps the old name as a re-export so existing references
# (_resolve_credentials_source etc.) don't break.
PROJECT_KEY_RE = shared.PROJECT_KEY_RE


def _perkey_projects_root() -> Path:
    """Per-key project directory root (source of truth: shared.perkey_projects_root;
    this wrapper keeps the old name for existing call sites, semantics unchanged)."""
    return shared.perkey_projects_root()


def _resolve_credentials_source(project_key: str) -> Optional[Path]:
    """Resolve the credential copy source (sandbar M1-2 read-side single source of
    truth; ui-check/creds-source.mjs is the isomorphic counterpart):

    1. project_key non-empty and passes the key whitelist, and
       <root>/<key>/credentials.yaml exists (isFile; a directory hit doesn't count)
       → use it (per-key first, contract ①b);
    2. otherwise the legacy fallback: env DSH_HOME/.credentials.yaml →
       $HOME/.dsh/.credentials.yaml (pre-M1-2 behavior, deprecation window; when the
       fallback hits, the caller is responsible for logging the migration hint);
    3. neither exists → None (no copy; the existing MISSING_CREDENTIAL stance is
       unchanged).

    Only path resolution and existence checks — never reads or parses file contents
    (the credential payload is parsed by the dsh credentials seam; malformed input is
    fail-closed inside that seam, so the read side does not reimplement a parser)."""
    key = (project_key or "").strip()
    if key and PROJECT_KEY_RE.match(key):
        perkey = _perkey_projects_root() / key / "credentials.yaml"
        if perkey.is_file():
            return perkey
    for dsh_home in [os.environ.get("DSH_HOME") or "",
                     str(Path.home() / ".dsh")]:
        if not dsh_home:
            continue  # drop an undefined/empty DSH_HOME (same for an empty HOME; no relative paths)
        cand = Path(dsh_home) / ".credentials.yaml"
        if cand.is_file():
            return cand
    return None


def _perkey_is_hit(project_key: str, src: Path) -> bool:
    """project_key is valid and src is exactly the per-key path (drives the migration
    hint log; tests call it directly too)."""
    key = (project_key or "").strip()
    return bool(key) and bool(PROJECT_KEY_RE.match(key)) and \
        src == _perkey_projects_root() / key / "credentials.yaml"


def _merge_creds(dst: Path, src: Path) -> None:
    """Merge-refresh the staged credential snapshot at refs-leaf granularity
    (ticket t260902-09, KI-016: merge only, never overwrite).

    Background: the lane's .dsh/.credentials.yaml is a staged snapshot taken at spawn
    time, and the old "return if the target already exists" logic meant the snapshot
    never refreshed — a provider shipping a new key left every old lane with
    MISSING_CREDENTIAL. The merge unit is the leaves of the refs sub-mapping (seam-
    managed fields such as version are kept in dst as-is):
    leaves present in src but missing from dst are appended; for same-named leaves
    the dst value wins outright (never wipes a mid-ticket key swap); dst-only leaves
    are not deleted.

    Contract-deviation statement (onboarding contract v1 ①b "the read side does not
    reimplement the parser"): merging requires reading contents, so the read side
    parses with a soft PyYAML dependency (same precedent as shared.model_route_for);
    the ①b revision draft went out for human review with ticket t260902-09. The
    write-back is not a re-serialization: it only appends same-shaped new lines as
    text inside dst's refs block, every other byte untouched. Appended lines use
    yaml-safe scalar serialization (no injectable bare lines), with the indentation
    taken from the measured indent of dst's refs children; the write-back goes to a
    tmp file in the same directory + os.replace for an atomic swap, mode copied from
    dst.

    Fault-mode trade-offs (last item excepted, any hit = no merge, snapshot left as
    is, warning only, never raise — "on a parse failure keep the status quo, raise no
    new error"):
      - PyYAML unavailable / a yaml syntax error on either side / top level not a dict;
      - dst's refs line is inline form — appending indented children would produce
        invalid YAML; better to merge one key fewer than to destroy the whole
        snapshot (an agent with zero usable credentials beats one missing key);
      - src has no refs section: no-op (the seam only recognizes refs leaves; not a
        fault);
      - dst read failure / CRLF file / a leaf value that is a multi-line scalar
        (text appending cannot preserve shape safely);
      - OSError on write-back: snapshot untouched, tmp cleaned up in finally;
      - no new leaves: zero write-back (mtime/mode untouched, avoids pointless churn).
    """
    try:
        import yaml  # pyyaml (engine venv; same soft dependency as shared.model_route_for)
    except ImportError:
        activity.logger.warning(
            "[creds] 暂存凭据合并跳过（dst=%s src=%s）：PyYAML 不可用，快照原样",
            dst, src)
        return

    def _load(p: Path) -> Optional[dict]:
        try:
            data = yaml.safe_load(p.read_text("utf-8"))
        except Exception:  # yaml syntax error / OSError / UnicodeDecodeError → unparseable
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
        return  # src has no refs (flat legacy format): the seam only reads refs leaves, nothing to merge
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
        return  # no new leaves: zero write-back

    try:
        # Read bytes, then decode: read_text's universal-newlines would translate
        # \r\n into \n while reading, and the CRLF guard below could never fire.
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
        raw = raw[:-1]  # the trailing empty string from split; put it back on rejoin

    # Locate the refs: line; guard: non-empty content after the colon = inline form, not mergeable
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
    insert_at = len(raw)  # refs block runs to EOF, or dst has no refs section → append at the end either way
    if refs_idx is not None:
        for j in range(refs_idx + 1, len(raw)):
            ln = raw[j]
            if not ln.strip() or ln.lstrip().startswith("#"):
                continue  # blank lines / comments are not block boundaries
            if not ln[0].isspace():
                insert_at = j  # next top-level key: the refs block ends here
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
        # dst has no refs section: append a block at EOF (the seam only sees new leaves by reading refs)
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
                pass  # a cleanup failure must not mask the main flow; a leftover tmp doesn't hurt the next merge
    activity.logger.info(
        "[creds] 暂存凭据合并刷新：%s 追加叶子 %s（源=%s，同名叶子未改写）",
        dst, "、".join(str(k) for k in missing), src)


def _copy_creds(dst_dsh: Path, project_key: str = "") -> None:
    """Copy/merge credentials into the workspace-local .dsh (API key passthrough;
    copy source = the project's ~/.sandbar/projects/<key>/credentials.yaml first,
    legacy global fallback). An unknown/empty project_key = skip the per-key first
    probe and still take the legacy fallback (= pre-M1-2 behavior).

    - dst missing: copy2 the whole file; if copy2 raises (unreadable terminal state
      such as permissions/ownership) that is fail-closed and propagates, the error
      names the source path, never silently swallowed.
    - dst present: refs-leaf merge refresh (see _merge_creds, KI-016) — no longer a
      blanket skip (the old guard meant the staged snapshot never refreshed, so a new
      provider left every old lane with MISSING_CREDENTIAL), while keeping the old
      guard's intent: same-named leaves are never rewritten in dst (the agent may
      have swapped keys mid-ticket; overwriting would erase that state).
    On a parse failure / missing source, keep the status quo and raise no new error:
    a missing source is skipped silently (MISSING_CREDENTIAL is reported by the
    engine); a parse failure logs a warning and leaves the snapshot as is."""
    dst = dst_dsh / ".credentials.yaml"
    src = _resolve_credentials_source(project_key)
    if src is None:
        return
    if not dst.exists():
        try:
            shutil.copy2(str(src), str(dst))
            # dsh refuses credentials with overly broad permissions (ticket
            # t260903-12, aftermath of a security incident); copy2 preserves the
            # source mode — a 644 source would ship a sick lane snapshot, so force
            # 0600 after the copy.
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
    """Look up this ticket's project key (M1-2: per-key credentials need the project
    directory name). Data source = meta.project on the workflow snapshot (written
    when base.py persists the snapshot); lookup failure / timeout / empty → ""
    (soft failure: skip the per-key first probe and take the legacy fallback — never
    let a credential-path lookup break the spawn). Precedent = the snapshot query in
    _epic_ticket_rows."""
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
    """Copy the dsh home's settings.yaml into the workspace-local .dsh — llm-pi-ai's
    providers section lives there; without it the kimi-coding/zai/scnet adapters all
    stay dormant (NO_ADAPTER). settings.yaml holds no secrets (keys go through
    apiKeyEnv / the credentials seam); what gets copied is the provider registry
    config. Re-copied on every spawn: settings changes (new provider / ordering) take
    effect for the very next agent."""
    src = _src_dsh_home() / "settings.yaml"
    if src.is_file():
        shutil.copy2(str(src), str(dst_dsh / "settings.yaml"))


def _pin_default_model(dst_dsh: Path, route: Dict[str, str]) -> None:
    """Write the routing decision into the agent-default-model user layer of the
    lane-local settings.yaml.

    dsh layering: the settings user layer beats the cordis patch composition layer
    (dsh-settings resolve = mergeLayers(base, section), user layer applied last).
    settings.yaml carries a GUI default-model section (agent-default-model), so a
    one-shot model_patch alone is guaranteed to be shadowed by it — the root cause of
    the 260826 incident: switching the route table to kimi-coding/zai landed nowhere,
    every agent actually ran on scnet, and once scnet's quota ran out everything
    died. So pinning a route must land in the user layer; settings are re-copied on
    every spawn, so no drift lingers."""
    p = dst_dsh / "settings.yaml"
    if not p.is_file():
        return
    out, skipping = [], False
    for ln in p.read_text("utf-8").splitlines(keepends=True):
        if ln.startswith("agent-default-model:"):
            skipping = True  # excise the whole section (its indented comments included), rewritten once at EOF
            continue
        if skipping and ln[:1] not in (" ", "\t", "\n", "#"):
            skipping = False  # next top-level key
        if not skipping:
            out.append(ln)
    out.append("agent-default-model:\n  provider: %s\n  model: %s\n"
               % (route["provider"], route["model"]))
    p.write_text("".join(out), "utf-8")


def _copy_profile(dst_dsh: Path) -> None:
    """Copy the sandbar-headless profile (symlinks included) into the workspace-local
    .dsh (sandbox isolation)."""
    src = _src_dsh_home() / "profiles" / "sandbar-headless"
    if not src.exists():
        return  # no profile to copy — headless falls back to dsh's built-in default
    dst = dst_dsh / "profiles"
    dst.mkdir(parents=True, exist_ok=True)
    if not (dst / "sandbar-headless").exists():
        shutil.copytree(str(src), str(dst / "sandbar-headless"), symlinks=True)

# Every agent-stage stage id (activity name = stage name; the pure-gate stage
# machine-qc and the human-gate stages approve/final-review/merge are not in here).
# 260824 dev-lane: developer-family tickets uniformly go through the four agent
# steps create_plan/review_plan/implement/integration_review (the old code-lane /
# build-workbench develop/verify/visual/close steps were deleted along with their
# templates).
AGENT_STAGE_IDS = (
    "create_plan", "review_plan", "implement", "integration_review",  # dev-lane (integration_review reachable only by replaying existing workflows)
    "design_integration_tests",                      # dev-lane integration-test machinery (ticket t260831-02)
    # The templates owning the next four lines were retired (260904 host order): the
    # stage names remain only as a fallback for replaying existing workflows.
    "propose", "process", "ai-review", "publish",    # content-pipeline (retired 260904)
    "review", "report",                              # proofread (retired; report doubles for regression)
    "regress",                                       # regression (retired)
    "clean", "rederive",                             # cleanup (retired)
    "fx_step_one", "fx_step_two",                    # fixture-two-step 测试夹具模板（t260908-01，仅 SANDBAR_FIXTURE_TEMPLATES=1 下可开票）
)


def _ws_kind_of(ws: Any) -> str:
    """工作区形态（容器执行面挂载准入用：worktree|dir 可挂；main/未知=spawn_agent 拒）。"""
    return ws.get("type") if isinstance(ws, dict) else ""


def _ws_cwd(ws: Optional[Dict[str, str]], ticket_id: str) -> Path:
    """Working directory for the agent process: worktree lane (relative to the repo
    root) / dir isolated directory / main tree."""
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
    # Shape-preserving normalization of files_changed (ticket t260904-18, KI-049
    # gate ②): no [str(x) for x in …] shape-destroying coercion — a string receipt
    # would be iterated character-by-character into a fake list of single chars and
    # slip past the gate silently; normalize_files_changed assigns the shape
    # (absent/ok/malformed) so consumers can go visibly red on that basis.
    fc, fc_shape = normalize_files_changed(raw.get("files_changed"))
    return StageResult(
        status=str(raw.get("status") or "ok"),
        summary=str(raw.get("summary") or ""),
        report=str(raw.get("report") or ""),
        deliverables=[str(x) for x in (raw.get("deliverables") or [])],
        files_changed=fc,
        files_changed_shape=fc_shape,
        evidence=str(raw.get("evidence") or ""),
    )


def _patch_result_prompt(rfile: Path, prompt: str) -> None:
    """Write the full prompt into the result JSON's prompt field (viewable from the
    ticket console's Agent log tab). Skipped when already present (no overwrite; the
    first-written prompt is kept)."""
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
    """KB size of the newest session file under the workspace-local .dsh/sessions/
    (an agent progress signal)."""
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


# Fake repo directory names an agent builds when its sandbox cannot write the real
# .git (observed 260824: .git-local/.git-obj-tmp/.git-tmp/.git-alt). settle
# quarantines them into .sandbar/quarantine/ on sight (never deleted, kept for audit).
FAKE_GIT_DIRS = (".git-local", ".git-obj-tmp", ".git-tmp", ".git-alt")


def _gitdir_is_real(cwd: Path, repo: Optional[Path] = None) -> bool:
    """Does the worktree's gitdir point under the main repo's .git (identity check)?

    Lesson from ticket t260824-03: the .git gitfile sits inside the lane directory,
    writable by the sandbox, so an agent can rewrite it to point at its own fake repo
    (.git-alt) — after that every git operation in the lane lands in the fake repo,
    and any sweep that hunts fake repos by directory name comes up empty. So don't
    look at names; look at the gitdir's real identity."""
    p = _git(["rev-parse", "--absolute-git-dir"], cwd)
    if p.returncode != 0:
        return False
    try:
        gd = Path(p.stdout.strip()).resolve()
        # Cross-project (ticket t260903-10): the worktree's real gitdir lives under
        # the .git of the project repo that owns it — self-anchored by path
        # convention, never hard-anchored to the engine repo (otherwise cross-project
        # lanes are permanently misjudged and "repaired" into corruption).
        return gd.is_relative_to(((repo if repo is not None else _lane_repo_root(cwd)) / ".git").resolve())
    except Exception:
        return False


def _registered_gitdir(repo: Path, cwd: Path) -> Optional[Path]:
    """Find, in repo's registered-worktree table, the registered gitdir whose
    back-pointer points at cwd/.git (ticket B).

    Multi-repo lane tree names have no correspondence with the repo basename
    (registered names may carry dedup suffixes), so don't guess from `cwd.name` —
    read each `.git/worktrees/*/gitdir` in turn and check the back-pointer; the one
    that points back is the real one. Returns None when not found (the caller then
    reports "cannot auto-repair")."""
    reg_root = repo / ".git" / "worktrees"
    if not reg_root.is_dir():
        return None
    want = (cwd / ".git").resolve()
    for reg in sorted(reg_root.iterdir()):
        gd_file = reg / "gitdir"
        if not gd_file.is_file():
            continue
        try:
            back = Path(gd_file.read_text("utf-8").strip())
            # The registered gitdir file records <worktree>/.git
            if back.resolve() == want:
                return reg
        except Exception:
            continue
    return None


def _restore_gitfile(cwd: Path, ticket_id: str, stage_id: str, gen: int,
                     repo: Optional[Path] = None) -> Optional[str]:
    """Repair a rewritten gitfile (pointing outside the main repo): quarantine the
    fake repo + rewrite the gitfile to the real registered gitdir. Returns a
    human-readable note; None when the gitfile is fine; raises when unrepairable
    (left to Temporal retry / the workflow turning blocked).
    repo (ticket B, t260907-06): the repo root owning the tree; None = the old
    stance of computing _lane_repo_root(cwd) here (single-repo path unchanged).
    In multi-repo setups the real gitdir lives under the child repo's
    .git/worktrees/, so the child repo root must be passed, and the registered name
    is found via _registered_gitdir (never guessed from cwd.name)."""
    p = _git(["rev-parse", "--absolute-git-dir"], cwd)
    fake = Path(p.stdout.strip()).resolve() if p.returncode == 0 else None
    if repo is None:
        real = _lane_repo_root(cwd) / ".git" / "worktrees" / cwd.name
        if not (real / "HEAD").is_file():
            raise RuntimeError(
                "settle: gitfile 被改写（指向 %s）且真 gitdir %s 不存在，无法自动修复——人工处置"
                % (fake, real))
    else:
        real = _registered_gitdir(repo, cwd)
        if real is None or not (real / "HEAD").is_file():
            raise RuntimeError(
                "settle: gitfile 被改写（指向 %s）且仓 %s 的注册表里找不到反向指回本树"
                "（%s）的 gitdir，无法自动修复——人工处置" % (fake, repo, cwd))
    # Back-pointer check on the real gitdir (its gitdir file should point back at
    # cwd/.git); a mismatch means the registration is already scrambled
    back = (real / "gitdir").read_text("utf-8").strip() if (real / "gitdir").is_file() else ""
    if back and Path(back).resolve() != (cwd / ".git").resolve():
        raise RuntimeError(
            "settle: 真 gitdir %s 的反向指针指向 %s（非本泳道），注册混乱——人工处置" % (real, back))
    (cwd / ".git").write_text("gitdir: %s\n" % real, "utf-8")
    note = "gitfile 被 agent 改写（指向主库外 %s），已恢复指向真 gitdir" % fake
    # Quarantine the fake repo for the record (moved only if it sits inside the lane and is a git directory)
    if fake and fake.is_relative_to(cwd.resolve()) and (fake / "HEAD").exists() and fake.is_dir():
        qdir = lane_dot_path(cwd, "quarantine", create=True)
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

# The git pathspec exclusion stance shared by settle/merge_check: .dsh (agent
# sandbox / credentials) and both coordination-directory names (new .sandbar +
# legacy sticky .suyou, see shared.resolve_dot_dir) are engine runtime directories
# present in every lane, so they don't count as changes.
# Note: this pathspec is only for git status (fine for porcelain); git add must not
# carry it — Apple Git 2.50 always errors rc=1 on the ". + :!ignored-dir" combination
# (see _settle_worktree_lane).
# The literal shape is an ast contract: integration/t260911-01 extracts this list with
# ast.literal_eval, so it cannot become a runtime-derived expression; the unit test
# test_t260914_01_settle_lane_stance pins it to shared.DOT_DIR_NEW/DOT_DIR_OLD instead
# (single source at the name level, drift = red). t260914-01 fixed the 260907 rename
# slip that had written .sandbar twice and dropped the legacy name entirely.
SETTLE_PATHSPEC = [".", ":!.dsh", ":!.sandbar", ":!.suyou"]  # naming-compat: .suyou = legacy coordination dir (shared.DOT_DIR_OLD)

# 协调目录撤下清单（add -A 之后的 reset 目标）：从 shared 真源派生，杜绝旧名/新名
# 各抄一份（t260914-01；同族教训 KI-074/KI-077）。settle 与 settle_conflict_resolution
# 共用同一元组，两处不再各写一份字面量。
_SETTLE_RESET_PATHS = (".dsh", shared.DOT_DIR_OLD, shared.DOT_DIR_NEW)  # naming-compat


# ---- KI-009 (ticket t260901-25): the two pure functions that auto-settle before merge_check goes red on dirty ----
# Pure functions, no IO; the integration test (ticket t260901-25) extracts them with
# ast and tests them directly (that environment has no temporalio, so the module
# cannot be imported).


def _dirty_files_from_status_z(raw: str) -> List[str]:
    """Parse `git status --porcelain -z` output into a list of dirty file paths
    (KI-009).

    Why -z instead of plain --porcelain: NUL separation has no quotePath quoting
    ambiguity (paths with spaces / non-ASCII are never quote-wrapped and escaped),
    and rename/copy entries split into the two fields `XY new<NUL>old<NUL>` with no
    "old -> new" arrow to parse — the malformed-line shapes of both plain formats
    structurally cannot exist here.
    Tolerance: non-string / empty string → []; an entry with fewer than 2 XY chars or
    no path is dropped without raising (malformed input fails closed and is left to
    the caller to judge out-of-write-set); rename/copy keeps only new (the current
    workspace path).
    """
    if not isinstance(raw, str) or not raw:
        return []
    out: List[str] = []
    for ent in raw.split("\0"):
        if not ent:
            continue
        if len(ent) < 4 or not ent[2] == " ":
            continue  # the XY<space>path shape doesn't hold: drop the malformed entry, no guessing
        path = ent[3:]
        if not path:
            continue
        out.append(path)
    return out


def _dirty_within_write_set(files: List[str], write_set: Any) -> bool:
    """Is every dirty file inside the ticket's write_set (KI-009 self-heal admission
    test; pure function)?

    Fail-closed: files empty (nothing dirty, no self-heal needed) / write_set not a
    list or empty / any entry non-string or empty after strip / any dirty file
    non-string or empty / a dirty file that is absolute, has a `..` segment, or has a
    backslash / no entry matches — always False, no self-heal.
    Entry match stance: dirty file == entry, or the dirty file has "entry + /" as a
    directory prefix (an entry may be `app/src` to mean the whole prefix); an entry
    ending in / means the same.
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
        if any(ch in f for ch in "?!*[]"):  # git sentinels (?) / glob-shaped paths: rejected fail-closed
            return False
        if not any(f == s or f.startswith(s + "/") for s in pats):
            return False
    return True


# ---- KI-009 (ticket t260901-25): full terminal-state reaping of the agent process (draining closes the late-write race window) ----

# Bounded reap window: after terminate, wait at most this long before escalating to
# kill; then wait for the kill to take effect.
AGENT_REAP_TERM_TIMEOUT_SEC = 15
AGENT_REAP_KILL_TIMEOUT_SEC = 5


def _reap_agent_proc(proc: subprocess.Popen, ticket_id: str = "", stage_id: str = "",
                     term_timeout: float = AGENT_REAP_TERM_TIMEOUT_SEC,
                     kill_timeout: float = AGENT_REAP_KILL_TIMEOUT_SEC) -> str:
    """Full terminal-state reaping of the agent process tree (KI-009 ②):
    terminate → wait with timeout → kill on timeout → wait again.

    Why by process group: the dsh runner spawns children of its own, and an agent's
    "late file write" usually belongs to a grandchild process — killing only the
    direct child leaves the late writer behind as an orphan (the real culprit of the
    KI-009 race window). So every spawn uses start_new_session=True (its own process
    group) and this function signals the group (killpg), reaping the whole tree at
    group granularity. A missing group (process already dead / already reaped) is
    treated as idempotent, no raise. Returns a human-readable note (for the caller's
    log / evidence); idempotent "" for an already-exited proc.
    """
    if proc.poll() is not None:
        return ""  # already exited: idempotent
    tag = "[%s/%s]" % (ticket_id, stage_id) if ticket_id else "[reap]"

    def _sig_group(sig: int) -> None:
        try:
            os.killpg(os.getpgid(proc.pid), sig)
        except OSError as e:
            # Group already gone (ESRCH) / no permission (EPERM) → fall back to
            # signalling the direct child only, best effort
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


def _path_exists_at_ref(repo: Path, ref: str, path: str) -> bool:
    """受保护闸的「基点已存在」判定（t260911-03）：`git cat-file -e <ref>:<path>`。

    ref = 泳道分叉点（base_ref，建泳道时各仓 HEAD；**不是 HEAD**——取 HEAD 会把本票
    早段 commit 里的文件误判为已存在，票内 rework 会被自保护闸红掉、每轮需人审放行）。
    ref 缺省（锚不可知）→ 一律按已存在处理（fail-closed 拦），绝不因锚缺失放行。
    """
    if not ref:
        return True
    p = _git(["cat-file", "-e", "%s:%s" % (ref, path)], repo)
    return p.returncode == 0


def _settle_with_gate(args: AgentStageArgs, cwd: Path) -> str:
    """通用 agent 段的带闸 settle（t260911-03）：把 AgentStageArgs 里的闸参数传给
    _settle_worktree_lane——单一拼装点，generic 段/缓存命中分支/arbitrate 系共用，
    两侧不可能漂移。t260912-03：人授权结构化记录（已由 workflow 侧按票+时效过滤）
    一并下传，受保护闸据此做豁免摘除。"""
    return _settle_worktree_lane(
        cwd, args.ticket_id, args.stage_id, args.gen,
        write_set=list(args.write_set or []),
        path_gate=bool(args.path_gate),
        base_ref=str(args.base_ref or ""),
        authorizations=list(getattr(args, "authorizations", None) or []))


def _apply_settle_note(res: StageResult, note: str) -> StageResult:
    """settle note 落回执：普通 note 进 evidence；闸拒绝（含 path_gate_reason= 键值）
    把结果改判 failed、summary 换成拒绝回执——workflow 侧按既有 failed 处理转
    blocked，点名段/文件与合法出路随回执上台面（协议三态之「越权」可辨）。"""
    if not note:
        return res
    res.evidence = (res.evidence + "\n[worker settle] " + note).strip()
    if path_gates.is_gate_refusal(note):
        res.status = "failed"
        res.summary = note
    return res


def _settle_worktree_lane(cwd: Path, ticket_id: str, stage_id: str, gen: int,
                          repo: Optional[Path] = None, write_set: Optional[List[str]] = None,
                          path_gate: bool = False, base_ref: str = "",
                          authorizations: Optional[List[Dict[str, Any]]] = None) -> str:
    """Settle a worktree lane on the agent's behalf (deterministic, never trusting
    the agent to behave): called once the agent has delivered its result file.

    Background: the headless agent's sandbox cannot write the real .git (a worktree's
    .git is a gitfile pointing at the main repo's .git/worktrees/<id>, outside the
    sandbox's writable scope), so "the agent commits itself" is physically
    impossible — the agent is forced to build a fake .git-local repo to "finish the
    commit", leaving the real lane at 0 commits and merge_check red (tickets
    t260824-01/-02). So the worker (unsandboxed) backs the commit up:
      1. 假 git 仓库目录隔离进 .sandbar/quarantine/（老泳道粘滞 .suyou；挪不删，留档）；  # naming-compat
      2. workspace changes (SETTLE_PATHSPEC stance) are folded into a single commit on
      the lane branch.
    Idempotent: a clean workspace is left alone (if the agent really could commit,
    settle is a no-op).
    Returns a human-readable note (appended to the stage evidence); returns "" for a
    non-worktree lane.
    A git failure raises = an infrastructure problem, left to Temporal retry.

    Mid-merge guard (ticket t260826-01): while MERGE_HEAD is present (the conflict
    resolution round's prep left that state behind) this function must **not**
    auto-add+commit — otherwise the merge commit lands here first (consuming
    MERGE_HEAD), settle_conflict_resolution then surely reports the false failure "no
    merge in progress", and any conflict markers the agent failed to clean get
    committed into the branch as if they were content. The only settlement path for a
    mid-merge workspace is settle_conflict_resolution (which also checks for leftover
    markers); this function skips outright. A normal implement round has no
    MERGE_HEAD, so its behavior is unchanged.

    路径闸（t260911-03，仅 path_gate=True 的票生效；False=老票 patch 门保护，行为与
    旧版逐字节一致）：脏清单非空时先过两道闸——阶段路径闸（段 × 允许面，judge_stage_paths）
    与受保护路径闸（真源与期望值，judge_protected_paths，锚=base_ref 泳道分叉点）。
    任一违规 = **不 add 不 commit**（工作区原样保留，agent 产物不丢），返回带
    path_gate_reason=<码> 与点名文件清单的拒绝 note，由调用方转 blocked。闸判定严格
    先于任何 git add——脏清单=未暂存工作区态，rename 只会呈 D+?? 两态（lane agent
    物理写不了 .git），D 条目保留旧路径、受保护闸可拦；该前提是闸判 rename 盲区
    不可达的根据。git status 失败 = 改动清单未知 = fail-closed 拒绝落盘
    （reason=status_failed，环境类），不留给实现猜。
    """
    if not _is_worktree_of(cwd, repo if repo is not None else _lane_repo_root(cwd)):
        # Ticket B (t260907-06): repo given = a multi-repo tree, ownership judged by
        # its child repo; None = the old single-repo self-computed anchor
        return ""
    p = _git(["rev-parse", "--verify", "MERGE_HEAD"], cwd)
    if p.returncode == 0:
        note = "合并进行中（MERGE_HEAD 在场），代落盘跳过——合并提交由 settle_conflict_resolution 收口"
        activity.logger.info("[%s/%s] settle：%s", ticket_id, stage_id, note)
        return note
    notes: List[str] = []
    # 0) gitfile identity check: if an agent rewrote it to point at a fake repo (the
    #    t260824-03 trick), repair first — otherwise every status/commit below lands
    #    in the fake repo and even the name-based quarantine comes up empty
    if not _gitdir_is_real(cwd, repo):
        fixed = _restore_gitfile(cwd, ticket_id, stage_id, gen, repo)
        if fixed:
            notes.append(fixed)
    # 1) Quarantine fake git repos
    for name in FAKE_GIT_DIRS:
        src = cwd / name
        if not src.exists():
            continue
        qdir = lane_dot_path(cwd, "quarantine", create=True)
        qdir.mkdir(parents=True, exist_ok=True)
        dst = qdir / ("%s-%s-gen%d" % (name, stage_id, gen))
        n = 1
        while dst.exists():
            n += 1
            dst = qdir / ("%s-%s-gen%d-%d" % (name, stage_id, gen, n))
        shutil.move(str(src), str(dst))
        notes.append("假 git 目录 %s 已隔离到 %s（agent 沙箱 workaround 产物，留档）"
                     % (name, dst.relative_to(cwd)))
    # 2) Fold workspace changes into a commit
    #    t260911-03: status 改走 -z（与 KI-009 解析器 _dirty_files_from_status_z 同源，
    #    免 quotePath 引号歧义与 rename 箭头解析）；闸判定在任何 git add 之前。
    p = _git(["status", "--porcelain", "-z", "--"] + SETTLE_PATHSPEC, cwd)
    if p.returncode != 0:
        if path_gate:
            note = path_gates.gate_refusal_note(stage_id, [], "status_failed")
            activity.logger.warning("[%s/%s] settle：%s", ticket_id, stage_id, note)
            return note
        raise RuntimeError("settle: git status 失败: %s" % (p.stderr or "")[-300:])
    dirty = _dirty_files_from_status_z(p.stdout)
    if path_gate and dirty:
        # 闸①：段 × 允许面（纯路径白名单，零猜测）
        allowed, violations, reason = path_gates.judge_stage_paths(
            stage_id, dirty, write_set=write_set, ticket_id=ticket_id)
        # 闸②：受保护路径（真源与期望值，「存在才拦」，锚=泳道分叉点 base_ref）
        # t260912-03：定性仍走 judge_protected_paths 单点（判定严格先于任何 git add），
        # 随后按本票生效中的人授权做「豁免摘除」——无授权/不匹配时 violations 与
        # 旧版逐字节相同（零回归面）。豁免命中＝记名点名 + 机读键（谁批/何时/批哪条）。
        passed: List[Dict[str, Any]] = []
        if allowed:
            anchor = repo if repo is not None else _lane_repo_root(cwd)
            pv, preason = path_gates.judge_protected_paths(
                dirty, exists_at_base=lambda path: _path_exists_at_ref(anchor, base_ref, path))
            pv, passed = authz_gates.exempt_authorized(
                pv, authorizations=list(authorizations or []))
            if pv:
                allowed, violations, reason = False, pv, preason
        if not allowed:
            note = path_gates.gate_refusal_note(stage_id, violations, reason)
            activity.logger.warning("[%s/%s] settle：%s", ticket_id, stage_id, note)
            return note
        if passed:
            # 记名点名 + 机读键（谁批、何时、批的哪条路径）——进回执/时间线，审计可回溯
            authz_note = authz_gates.authorized_passage_note(passed)
            notes.append(authz_note)
            activity.logger.info("[%s/%s] settle：%s", ticket_id, stage_id, authz_note)
    if dirty:
        # Observed on Apple Git 2.50: an exclusion pathspec (:!.dsh) does not stop
        # the "explicitly named ignored directory" error (rc=1 even on a clean repo,
        # seen live in ticket t260826-01) — so add everything instead (.dsh/.sandbar
        # are gitignored and would never be staged anyway), then reset them back as
        # belt and braces (for lanes with an old .gitignore; rc=0 silently when
        # nothing matches).
        p = _git(["add", "-A", "--", "."], cwd)
        if p.returncode != 0:
            raise RuntimeError("settle: git add 失败: %s" % (p.stderr or "")[-300:])
        _git(["reset", "-q", "--", *_SETTLE_RESET_PATHS], cwd)
        # t260914-01（dengzhufpv/t260911-07 根因之二）：判脏非空但撤下协调目录后暂存区
        # 可能为空——该段只产出协调目录产物时就是这种形态，「无改动可提交」是正常工作态，
        # 不是基础设施故障（旧版在此让 commit rc≠0 上抛 RuntimeError，被 Temporal 表现成
        # 「agent 活动故障」，归因噪声极大）。显式预检把两态分开：空暂存=可辨 note（含
        # 判脏项数与点名，进回执 evidence，不含 path_gate_reason= 键故不会被判闸拒绝）；
        # 暂存非空而 commit 仍失败=真失败，照旧响亮。
        st = _git(["diff", "--cached", "--quiet"], cwd)
        if st.returncode == 0:
            note = ("判脏 %d 项均为引擎运行时目录（%s），撤下后暂存区为空——无需代落盘"
                    "（空提交=正常工作态，非故障；判脏=%s）"
                    % (len(dirty), "、".join(_SETTLE_RESET_PATHS),
                       "、".join(dirty[:5]) + ("…" if len(dirty) > 5 else "")))
            activity.logger.info("[%s/%s] settle：%s", ticket_id, stage_id, note)
            notes.append(note)
        else:
            if st.returncode != 1:
                # rc=1 之外都不是「有差异」而是 git 自身出问题（索引损坏等）：环境类
                # fail-closed，绝不吞成 note
                raise RuntimeError("settle: 暂存区检查失败（diff --cached --quiet rc=%d）: %s"
                                   % (st.returncode, (st.stderr or "")[-200:]))
            msg = ("%s %s：worker 代落盘（gen%d，%d 项改动）\n\n"
                   "headless agent 沙箱写不了主库 .git，commit 由 worker 确定性兜底"
                   % (ticket_id, stage_id, gen, len(dirty)))
            p = _git(["commit", "-m", msg], cwd)
            if p.returncode != 0:
                raise RuntimeError("settle: git commit 失败: %s" % (p.stderr or p.stdout or "")[-300:])
            head = _git(["rev-parse", "--short", "HEAD"], cwd)
            notes.append("worker 代落盘 commit %s（%d 项：%s）"
                         % (head.stdout.strip() if head.returncode == 0 else "?",
                            len(dirty), "、".join(dirty[:5])))
    else:
        notes.append("工作区已干净，无需代落盘")
    note = "；".join(notes)
    activity.logger.info("[%s/%s] settle：%s", ticket_id, stage_id, note)
    return note


def _prepare_agent_spawn(cwd: Path, role: str, kind: str, ticket_id: str,
                         artifacts_dir: Path, tag: str, project: str = "",
                         session_key: str = ""):
    """Shared pre-spawn preparation (extracted from _run_agent_stage_impl in ticket
    t260828-08): create the local .dsh directory + _copy_profile/_copy_creds/
    _copy_settings + the role preset patch + pinning the model route into
    agent-default-model (one-shot patch + a second write into the settings user
    layer, the root cause of the 260826 incident — a patch alone is always shadowed
    by the GUI default-model section) + the session-continuation patch + env
    assembly. (t260910-14: the pre-run-next-ticket consumer retired; the helper
    remains the single spawn stance of the generic agent step.)

    Returns (cmd prefix including the patches but not the prompt, env). One-shot
    patch files land in artifacts_dir, named with a tag to tell callers apart
    (generic step = stage_gen<N>).
    """
    # Sandbox isolation: the worker process may lack permission to write ~/.dsh, so
    # the headless agent uses a workspace-local .dsh directory (via a DSH_HOME
    # override), with the profile's symlinks copied along.
    local_dsh = cwd / ".dsh"
    local_dsh.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    env["DSH_HOME"] = str(local_dsh)
    # The guard checks the profile itself (lesson from ticket t260828-05: checking
    # the parent directory let leftovers from the first failed attempt — profiles/
    # node_modules — make every later retry skip the copy forever); idempotence is
    # guaranteed by the exists check inside _copy_profile
    _copy_profile(local_dsh)
    _quarantine_torn_sessions(local_dsh)
    # Copy the credentials too (API key), otherwise the headless agent reports
    # MISSING_CREDENTIAL; the copy source prefers per-key (M1-2), and an unknown
    # project still takes the legacy fallback, so current behavior is unchanged.
    # KI-016 (ticket t260902-09): an existing dst is no longer skipped — the merge
    # refresh was pushed down into _copy_creds as the single point (refs-leaf
    # granularity, same-named dst leaves never rewritten), so a new provider's key is
    # visible to old lanes immediately. The old outer exists guard duplicated the
    # inner one and, left in place, would have blocked the whole refresh path; removed.
    _copy_creds(local_dsh, project)
    # settings.yaml is re-copied every time (llm-pi-ai providers registry; a change takes effect for the next agent)
    _copy_settings(local_dsh)

    cmd = list(DSH_CMD)
    # Role preset patch (contract ①d, ticket t260903-03: the directory base comes
    # from the registered entry's declared paths.roles_dir, falling back to
    # <cwd>/server/roles when undeclared — the in-worktree copy keeps the ticket
    # snapshot semantics): persona = the full role brief, and the cordis patch
    # overrides by the same id. When undeclared and the concrete role file is absent
    # (old base_ref) it is skipped, degrading to the profile's default persona — no
    # hard failure; declared but the anchor directory is missing / the wrong kind =
    # ProjectPathsError propagates (fail-closed red, the error names the entry file
    # and the resolved path).
    role_patch = roles_dir_for_spawn(project, cwd) / (role + ".yml")
    if role and role_patch.is_file():
        cmd += ["--patch", str(role_patch)]
    # Runtime model routing (the only consumer left after gen.py retired): read the
    # route table for (role, kind) → provider/model and generate a one-shot patch
    # pinning agent-default-model. The division-of-labor kind comes from
    # STAGE_DISPATCH_KIND mapped by (workflow, stage) (e.g. ai-review → the
    # proofread reviewer's model). No hit = don't pass one — the agent uses the
    # profile's default model, no hard failure. The table path comes from the
    # contract ①d paths.model_routes declaration (t260910-14 重构)：resolve_routes_table
    # 单点解析（真源=声明指向文件；读侧分层兜底=仓内表，宿主风险令 260910）。
    # 任何非 ok 态在此点名留痕（state+path+error）后继续用兜底表——agent 仍可跑，
    # 绝不静默回落 profile 默认（KI-030 收窄）。
    resolved = routes_file_for_spawn(project)
    if resolved["state"] != "ok":
        activity.logger.warning(
            "[model_route] 路由表解析非 ok（state=%s，读=%s）：%s",
            resolved["state"], resolved["path"], resolved["error"])
    route = model_route_for(role, kind, table=resolved["table"],
                            routes_file=resolved["path"])
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
        # The patch layer gets shadowed by the GUI default-model section of the
        # settings.yaml user layer (see _pin_default_model), so the route must also
        # land in the user layer to actually take effect.
        _pin_default_model(local_dsh, route)
    # Session continuation (dsh-headless-resume plugin): repeated dispatches for the
    # same ticket and role continue the same dsh session, so rework feedback arrives
    # inside the agent's own session and it keeps editing instead of rebuilding
    # context from scratch on every spawn. The mechanism mirrors model_patch:
    # generate a one-shot patch (absolute path to the runner file) that disables the
    # stock one-shot runner and swaps in the create-or-resume runner;
    # DSH_HEADLESS_SESSION carries the deterministic session id. The runner prefers
    # the in-lane copy (ticket snapshot semantics, same as role_patch), falls back to
    # the main repo copy for old lanes, and if neither exists this section is skipped
    # (degrades to the stock one-shot, no hard failure). SANDBAR_AGENT_RESUME=0 turns
    # it off with one switch.
    if os.environ.get("SANDBAR_AGENT_RESUME", "1") != "0" and role:
        runner = cwd / "server" / "headless-resume" / "node.ts"
        if not runner.is_file() and agent_runtime.runtime_mode() == "docker":
            # 容器执行面（t260913-04，A 腿真链实测缺陷修复）：runner 缺泳道内副本时会回落到
            # REPO_ROOT（引擎主树=宿主路径），该路径在容器里**不可见**（红线 2：不挂工作区
            # 以外宿主路径）→ dsh boot 直接 ERR_MODULE_NOT_FOUND「…/server/headless-resume/
            # node.ts」而整段全灭（实测：真 worker+docker runtime 的 implement 段容器内
            # agent 起不来，容器空转到段超时）。修法=把 runner 落进【泳道内】再引用：整目录
            # 拷到 <lane>/.sandbar/agent-plugins/headless-resume/（.sandbar 不入 settle
            # 清单、path 闸放行；泳道本就挂进容器，路径天然可见）。
            _src_runner_dir = REPO_ROOT / "server" / "headless-resume"
            _dst_runner_dir = cwd / ".sandbar" / "agent-plugins" / "headless-resume"
            if _src_runner_dir.is_dir():
                try:
                    _dst_runner_dir.parent.mkdir(parents=True, exist_ok=True)
                    if not _dst_runner_dir.exists():
                        shutil.copytree(str(_src_runner_dir), str(_dst_runner_dir))
                    runner = _dst_runner_dir / "node.ts"
                except OSError as e:
                    activity.logger.info(
                        "[%s/%s] 泳道内 runner 物化失败（%s）——回落宿主路径（容器内不可见）",
                        ticket_id, tag, e)
        if not runner.is_file():
            runner = REPO_ROOT / "server" / "headless-resume" / "node.ts"
        if runner.is_file():
            resume_patch = artifacts_dir / ("resume_patch_%s.yml" % tag)
            resume_patch.write_text(
                "# 本文件由 agent activity 每次 spawn 时生成（会话延续，runner 真源=server/headless-resume/）。\n"
                "- id: headless-runner\n"
                "  disabled: true\n"
                "- insert:\n"
                "    - id: headless-resume\n"
                "      name: '%s'\n"
                "      inject: [headlessStartup]\n"
                "      config:\n"
                "        task: !!js ctx.headlessStartup.task\n" % runner, "utf-8")
            cmd += ["--patch", str(resume_patch)]
            # Ticket t260903-02: the session id defaults to ticket-role (continuation
            # across stages of the same role); the parallel-fork acceptance edge
            # passes a ticket-stage-specific key — two concurrent processes of the
            # same role must never write one session file (with the default key,
            # concurrent arbitrate/acceptance spawns collide for certain).
            env["DSH_HEADLESS_SESSION"] = session_key or ("%s-%s" % (ticket_id, role))
    # ---- 容器执行面专属（t260913-04，方案 D5/D8；host 形态零改动） ----
    if agent_runtime.runtime_mode() == "docker":
        # profile 篡改面重置（对抗面闭环）：泳道 .dsh 对 agent 可写，且 _copy_profile 的
        # exists 守卫使 profile 层【跨段持久】——agent 段内往自己的 profile patch 里注
        # `disabled: true`（关沙箱）或 `- insert:` 任意插件，下一 spawn 会原样加载
        # （260913 真探针实证 disabled 面穿透 patch 钉死）。docker 分支每次 spawn 删旧
        # 重拷：profile 回到宿主真源票快照；dsh 自愈农场的 profiles/node_modules 兄弟位
        # 不动（容器内自愈重指的链接仍有效）。settings/凭据本就每段重拷（_copy_settings/
        # _copy_creds），沙箱模式另由下方 sandbox_pin 钉死——三层合围后无跨段持久注入面。
        _lane_profile = local_dsh / "profiles" / "sandbar-headless"
        if _lane_profile.exists():
            shutil.rmtree(str(_lane_profile))
        _copy_profile(local_dsh)
        # 一次性钉死 patch（内容单点=agent_runtime.sandbox_pin_yaml；每次 spawn 重写）：
        # ① sandbox-policy.mode 字面量 'danger-full-access'（宿主 260914 A 案：容器内
        #    全权，隔离由挂载面承担——容器只见本票泳道，宿主边界守卫=neglock 场景的
        #    「宿主边界不可达」腿；字面量仍压掉 dsh-base 的 !!js env 表达式与 env 面
        #    DSH_PERMISSION_MODE 任何值，「模式不被篡改」这层机械保障不变）+
        #    workspaceRoot 一并写（C1：防整段替换丢授予面）+ 入口级 disabled:false
        #    （压 profile 层 disabled 注入）；
        # ② bash-sandbox timeoutMs/maxTimeoutMs=900s（D8：60s 硬顶会掐分钟级测试；对齐
        #    SANDBAR_INTEG_CMD_TIMEOUT_SEC 缺省，执行面容量参数而非判定放宽；仅 docker
        #    作用域——host 形态命令面本就 fail-closed，不扩无谓动面）。
        sandbox_pin = artifacts_dir / ("sandbox_pin_%s.yml" % tag)
        sandbox_pin.write_text(agent_runtime.sandbox_pin_yaml(), "utf-8")
        cmd += ["--patch", str(sandbox_pin)]
    return cmd, env


async def _run_agent_stage_impl(args: AgentStageArgs) -> StageResult:
    rfile = Path(args.result_file)
    rfile.parent.mkdir(parents=True, exist_ok=True)
    cwd = _ws_cwd(args.workspace, args.ticket_id)
    cwd.mkdir(parents=True, exist_ok=True)

    # Idempotent: the result file already exists → read it and return (safe across
    # Temporal retries / worker restarts)
    if rfile.is_file():
        cached = _read_result(rfile)
        if cached is not None:
            activity.logger.info("[%s/%s] 结果文件已存在，幂等返回（gen%d）",
                                 args.ticket_id, args.stage_id, args.gen)
            _patch_result_prompt(rfile, args.prompt)
            # A cache hit still goes through settle (the last worker may have died
            # after the agent delivered but before settling) — idempotent;
            # skip_settle (during the parallel fork) is handled by the single
            # settle_lane at the join point
            note = ""
            if not args.skip_settle:
                note = _settle_with_gate(args, cwd)
            _apply_settle_note(cached, note)
            return cached

    if os.environ.get("SANDBAR_AGENT_STUB") == "1":
        # Self-test / demo stub: write our own result file and return (no agent
        # process, zero model calls).
        # The stub supports explicit files_changed (ticket t260904-18: env
        # SANDBAR_AGENT_STUB_FILES, comma-separated paths) — the default stays []
        # for good (the stub honestly reports "did nothing"), but a default receipt
        # keeps the write_set_refresh_fault annotation lit through KI-049 gate ②; a
        # stub chain that needs to demo the write-set refresh passes the list
        # explicitly, and the gate's own judgement is never loosened.
        # t260908-01：可注入的桩段时长 SANDBAR_AGENT_STUB_DELAY_SEC（秒，缺省 0=
        # 即时回执，既有语义不变）——段间暂停集成腿需要确定性的「段在飞」窗口
        #（在飞中发 pause、断言段自然跑完才停门口）；无此旋钮桩段秒过，信号永远
        # 落在段外，在飞粒度不可验。睡眠在写结果文件之前=在飞窗真实拉长。
        _stub_delay = float(os.environ.get("SANDBAR_AGENT_STUB_DELAY_SEC") or 0)
        if _stub_delay > 0:
            activity.heartbeat("stub delayed start (%ss)" % _stub_delay)
            await asyncio.sleep(_stub_delay)
        stub_files = [x.strip() for x in
                      os.environ.get("SANDBAR_AGENT_STUB_FILES", "").split(",")
                      if x.strip()]
        stub = StageResult(
            status="ok",
            summary="[stub] %s 段完成（SANDBAR_AGENT_STUB=1，第 %d 次进段）"
                    % (args.stage_id, args.gen),
            report="[stub] 做了什么：无（stub 演示）\n\n怎么验证的：无",
            deliverables=[], files_changed=stub_files,
            files_changed_shape="ok",  # always a legal shape; the empty-list emptiness call belongs to the consumer
            evidence="stub evidence: prompt %d 字" % len(args.prompt))
        rfile.write_text(json.dumps({
            "status": stub.status, "summary": stub.summary, "report": stub.report,
            "deliverables": stub.deliverables, "files_changed": stub.files_changed,
            "evidence": stub.evidence, "prompt": args.prompt,
        }, ensure_ascii=False, indent=1) + "\n", "utf-8")
        activity.heartbeat("stub done")
        return stub

    # Shared pre-spawn preparation (the three local .dsh copies live in the helper
    # above, plus the role patch, model routing and session continuation); see
    # _prepare_agent_spawn (ticket t260828-08).
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
    # start_new_session=True (KI-009): its own process group, so _reap_agent_proc can
    # killpg the dsh runner's entire child tree (late writes usually belong to
    # grandchildren)
    _ws_kind = _ws_kind_of(args.workspace)
    proc = agent_runtime.spawn_agent(
        cmd, cwd=cwd, env=env, logf=logf, ticket_id=args.ticket_id,
        stage_tag="%s_gen%d" % (args.stage_id, args.gen), project=project,
        workspace_kind=_ws_kind, lane=cwd, log=activity.logger.info)

    polls = 0
    try:
        while True:
            if rfile.is_file():
                res = _read_result(rfile)
                if res is not None:
                    activity.logger.info("[%s/%s] 结果文件就绪：status=%s",
                                         args.ticket_id, args.stage_id, res.status)
                    _patch_result_prompt(rfile, args.prompt)
                    # KI-009 (ticket t260901-25): reap before settling (full
                    # terminal-state reaping at process-group granularity) — after
                    # delivering the result file the agent may still be late-writing
                    # workspace files; settle without draining them and the late
                    # write lands after the commit = dirty workspace = a false
                    # merge_check red (the KI-009 root cause). The drain is bounded
                    # (terminate 15s / kill 5s); see _reap_agent_proc.
                    proc.reap(args.ticket_id, args.stage_id)
                    # Worker-side settling (deterministic): the agent sandbox cannot
                    # write the real .git, so the worker backs the commit up; fake
                    # git directories are quarantined here; skip_settle (during the
                    # parallel fork) is handled by the single settle_lane at the join
                    # point
                    note = ""
                    if not args.skip_settle:
                        note = _settle_with_gate(args, cwd)
                    _apply_settle_note(res, note)
                    return res
            rc = proc.poll()
            if rc is not None:
                # The agent process exited without writing a result file = an
                # infrastructure / usage fault → raise so Temporal retries
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
        # KI-009: the finally block escalates to full terminal-state reaping at group
        # granularity (all four paths — normal / error / timeout / cancel — reach
        # here; an already-exited proc is skipped idempotently)
        proc.reap(args.ticket_id, args.stage_id)


def _make_stage_activity(stage_id: str):
    """Register one activity per stage name (same implementation, name = stage name).
    The wrapper keeps activity.defn from overwriting its defn name on one function
    object."""
    async def _impl(args: AgentStageArgs) -> StageResult:
        return await _run_agent_stage_impl(args)
    _impl.__name__ = "stage_" + stage_id.replace("-", "_")
    return activity.defn(_impl, name=stage_id)


def _log_tail(log_file: str, n: int = 400) -> str:
    try:
        return Path(log_file).read_text("utf-8", errors="replace")[-n:].strip()
    except Exception:
        return ""


# ---------- M16: workspace preparation (the workflow's first activity) ----------

def _lane_repo_root(cwd: Path) -> Path:
    """Repo root owning the lane (cross-project, ticket t260903-10): self-anchored by
    the path convention <repo>/.lane/<id> — for multi-project tickets (project root ≠
    engine root) the worktree add/reuse/settle must operate on the project repo, not
    the engine repo. Anything not matching the convention (an explicitly custom path /
    the main tree / an old relative payload) falls back to REPO_ROOT (old behavior)."""
    if cwd.parent.name in (".lane", ".worktrees"):  # .lane = new name; .worktrees = old name (in-flight / pre-existing lanes)
        return cwd.parent.parent
    return REPO_ROOT


# ---- Ticket B (t260907-06): multi-repo lane scope list (the single entry point for per-tree settle/merge/check) ----

# Multi-repo lane manifest (written by prepare_workspace; meta.repo_worktrees is the
# only source of truth, and this file is its on-disk mirror for downstream activities
# to read mechanically). Paths are relative: tree relative to the lane root, repo
# relative to the project root (= the lane root's grandparent), so moving the lane
# does not invalidate it.
# 盘上位置的唯一真源＝shared.multi_manifest_path（协调目录解析三规则）；本常量只剩
# 「老名存量镜像路径」这一语义：改名前的泳道清单落在它上面（读侧回落锚），夹具与
# 存量消费方仍按它直读（t260914-01；值必须保持老名相对路径不变）。
MULTI_MANIFEST_REL = shared.DOT_DIR_OLD + "/" + shared.MULTI_MANIFEST_NAME  # naming-compat


def _lane_scopes(wt: Path, branch: str = "", base_ref: str = "",
                 write_set: Optional[List[str]] = None,
                 entries: Optional[List[Any]] = None) -> List[Dict[str, Any]]:
    """Lane scope list: single repo = 1 entry (each field is exactly the old
    single-anchor behavior, a byte-level regression surface); multi-repo = one entry
    per repo (a corrupt manifest = RuntimeError to Temporal retry / a human, never a
    silent fallback to the single-repo anchor — falling back would settle/merge the
    wrong repo). Fields: name/tree/repo/branch/base_ref/write_set, where write_set has
    already been rebased per repo (a tree-root-relative subset; passed through
    unchanged for a single repo).

    `entries`（t260913-05，拆道逐仓化）：明细的另一种入参——workflow 递来的
    `meta.repo_worktrees`（唯一真源）。传了就跳过读盘清单、直接走同一段条目校验 +
    归一化（判定单点，不另造第二套解析）；None=读盘清单镜像（merge 等既有调用点
    原样零回归）。参数必须留在末尾：:2322 现存 4 个位置实参调用
    `_lane_scopes(wt, args.branch, args.base_ref, args.write_set)`。
    损坏/畸形一律 RuntimeError（两源同语义），绝不静默回落单仓锚。"""
    mf = shared.multi_manifest_path(wt, legacy_fallback=True)
    from_entries = entries is not None
    if not from_entries:
        if not mf.is_file():
            return [{"name": "", "tree": wt, "repo": _lane_repo_root(wt), "repo_rel": "",
                     "branch": branch or ("lane/" + wt.name), "base_ref": base_ref,
                     "write_set": list(write_set or [])}]
        try:
            entries = json.loads(mf.read_text("utf-8"))
        except Exception as e:
            raise RuntimeError("多仓泳道清单损坏（%s: %s）——人工处置，不静默回落单仓锚" % (mf, e))
    src = "meta.repo_worktrees 明细" if from_entries else str(mf)
    if not isinstance(entries, list) or not entries:
        raise RuntimeError("多仓泳道清单为空或非列表（%s）——人工处置" % src)
    project_root = wt.parent.parent
    scopes: List[Dict[str, Any]] = []
    for e in entries:
        # Ticket t260907-12: repo may be an empty string = the root-repo tree
        # (tree = the lane container, repo = the project root itself); a missing /
        # non-string branch is still rejected (fail-closed, not weakened; the message
        # names the genuinely missing field).
        if not isinstance(e, dict):
            raise RuntimeError("多仓泳道清单条目须为对象（%r in %s）——人工处置" % (e, src))
        if not isinstance(e.get("repo"), str):
            raise RuntimeError("多仓泳道清单条目 repo 字段缺失或非字符串（%r in %s）"
                               "——人工处置" % (e, src))
        if not (isinstance(e.get("branch"), str) and e["branch"]):
            raise RuntimeError("多仓泳道清单条目 branch 字段缺失或为空（%r in %s）"
                               "——人工处置" % (e, src))
        scopes.append({
            "name": str(e.get("name") or e["repo"] or "root"),
            "tree": wt / e["repo"],
            "repo": project_root / e["repo"],
            "branch": str(e["branch"]),
            "repo_rel": str(e["repo"]),
            "base_ref": str(e.get("base_ref") or ""),
            "write_set": rebase_write_set(write_set, str(e["repo"])),
        })
    return scopes


def _scope_tag(sc: Dict[str, Any]) -> str:
    """逐仓点名的 tag（t260913-05）：清单 name 优先，其次仓相对路径；旧单仓回落
    条目（name/repo_rel 皆空）返回空串——调用方不加前缀，warn 文案与旧代码逐字一致
    （单仓路径逐字节零回归）。"""
    name = str(sc.get("name") or "")
    if name:
        return name
    return str(sc.get("repo_rel") or "")


def _tagged(tag: str, msg: str) -> str:
    """带 tag 的逐仓 warn 文案；tag 空（旧单仓回落）= 原样，零回归。"""
    return ("[%s] %s" % (tag, msg)) if tag else msg


def _is_worktree_of(p: Path, repo: Optional[Path] = None) -> bool:
    """Is p a registered worktree of **that repo** (default REPO_ROOT)?
    `git -C repo worktree list --porcelain` must contain a `worktree <p>` entry
    (compared as absolute paths).
    Not decided via `git -C p rev-parse` — an ordinary subdirectory inside the repo
    walks up to the repo root and would be misjudged as a worktree."""
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


def multirepo_materialization_error(lane_root: Path, write_set: Optional[List[str]],
                                    scopes: List[Dict[str, Any]],
                                    is_worktree_of=None) -> str:
    """保险丝B（合并红灯，工单 t260910-03）：多仓写集 × 未逐仓物化的 fail-closed
    背闸（dengzhufpv 260910 缺陷：明细缺失时 _lane_scopes 静默回落单仓锚 → 成员仓
    零落仓仍可全绿收口）。

    语义：写集经 resolve_repos_for_paths 归属出的**成员仓集合**（归属≠项目根本体），
    必须 ⊆ scopes 中已物化仓集合（scope name 非空、tree 目录在位、
    is_worktree_of(tree, repo) 为真）；任一缺失 → 返回点名缺失仓+未落成条目的
    红灯文案；否则 ""（放行）。
      - 写集为空 → ""（保险丝不触发：旧在途票 MergeArgs.write_set 反序列化缺键
        回落空列表，按旧语义收口不追溯——兼容约定，非静默降级）；
      - 写集全归根本体（单仓/混合形态的根树部分）→ ""（零回归面）；
      - 清单缺失（单 scope 回落形态，name=""）+ 写集含成员仓条目 → 全部成员仓
        判未物化（正是缺陷形态）；清单**损坏**仍走 _lane_scopes 的 RuntimeError，
        不在本函数重复判（两态互补封口）；
      - 归属解析 ValueError（逃逸/嵌套仓/条目畸形）→ 转红灯文案不 raise（
        merge_check 红灯不抛的既有语义；创建时刻已被保险丝A/写集校验拦截，
        此处再红一道是纵深，不是第一防线）；
      - is_worktree_of 参数注入（默认 _is_worktree_of）：UT 用桩谓词，免 git
        子进程依赖；消费方（merge_check / merge）共用同一判定源，不另造第二真源。
    """
    entries = list(write_set or [])
    if not entries:
        return ""
    predicate = is_worktree_of or _is_worktree_of
    lane_root = Path(lane_root)
    project_root = lane_root.parent.parent
    try:
        mapping = resolve_repos_for_paths(project_root, entries)
    except ValueError as e:
        if "未发现任何 git 仓" in str(e):
            return ""  # 仓集合为空=无成员仓可言，保险丝不适用（存量无 .git 注册目录面）
        return ("写集归属解析 fail-closed（t260910-03 保险丝B）：%s" % e)
    root_abs = str(project_root.resolve())
    member = {repo: paths for repo, paths in mapping.items()
              if str(Path(repo).resolve()) != root_abs}
    if not member:
        return ""
    materialized = set()
    for sc in scopes or []:
        if not str(sc.get("name") or ""):
            continue  # 单仓回落 scope（清单缺失）：无逐仓物化可言
        repo_abs = str(Path(str(sc.get("repo"))).resolve())
        tree = Path(str(sc.get("tree")))
        if tree.is_dir() and predicate(tree, Path(str(sc.get("repo")))):
            materialized.add(repo_abs)
    missing = {repo: paths for repo, paths in member.items()
               if str(Path(repo).resolve()) not in materialized}
    if not missing:
        return ""
    return ("多仓写集未逐仓物化（t260910-03 保险丝B，绝不静默收口）：%s"
            % "；".join("[%s] 未落成（写集条目 %s）" % (repo, ",".join(paths))
                       for repo, paths in sorted(missing.items())))


def _check_git_identity(repo: Path) -> Optional[str]:
    """Commit-identity guard (ticket t260905-10): a lane settle's commit happens in
    the lane worktree (_settle_worktree_lane's `git -C lane commit`), and the source
    of truth for the git identity is the host's ~/.gitconfig (if that file vanishes,
    every settle track goes FAILED — a hidden dependency that only surfaces at the
    moment of the accident). The probe anchors on the **owning repo root**:
    `git -C repo-root config` covers all three layers (system/global/repo) — a repo
    level config and the global identity apply equally to future lane worktrees
    (worktrees share the main repo's config), and the repo-root probe still works on
    the created path before the lane directory exists (with -C on a nonexistent lane,
    the missing directory would be misreported as a missing identity). Returns None =
    identity in place; otherwise the red text (naming what's missing + the fix)."""
    missing: List[str] = []
    for key in ("user.name", "user.email"):
        try:
            r = subprocess.run(["git", "-C", str(repo), "config", key],
                               capture_output=True, text=True, timeout=30)
        except (OSError, subprocess.TimeoutExpired) as e:
            return ("git 身份探针执行失败（%s: %s）——开工前点名：连 git 都起不来，"
                    "泳道 settle 代落盘 commit 必炸，先修环境再 retry_qc。" % (type(e).__name__, e))
        if r.returncode != 0 or not (r.stdout or "").strip():
            missing.append(key)
    if not missing:
        return None
    return ("git 身份缺失（%s）——开工前点名，不落盘才炸：泳道 settle 代落盘 commit 依赖 "
            "git 身份（真源=宿主 ~/.gitconfig，260906 曾因该文件消失致三轨 settle 全 FAILED）。"
            "处置：补宿主 ~/.gitconfig 的 user.name/user.email，或在本仓 "
            "`git config user.name <名> && git config user.email <邮箱>` 补 repo 级身份"
            "（worktree 与主仓共享 config），然后 retry_qc 重跑本步。" % "、".join(missing))


# Lane dependency directory bootstrap list (hit live in ticket t260824-12): a
# worktree does not inherit gitignored environment directories, so verify_lane's
# "dependencies in place" check would always go red. Includes server/engine/.venv
# (added in ticket t260905-10: replay_check's interpreter fallback chain consumes the
# in-lane venv — the 260825 ruling that "no lane has a consumer" was overturned by
# measurement and is void). Existing behavior kept: when the main repo's directory is
# absent (a fresh clone) _ensure_lane_deps skips without an error, and the red text
# comes from verify_lane's "dependencies in place".
LANE_DEP_SYMLINKS = ("app/node_modules", "server/engine/.venv")


def _ensure_lane_deps(lane_path: Path) -> str:
    """Symlink the main repo's gitignored dependency directories into the lane
    (idempotent). Returns the action text suffix ("" or "+deps:<dir>") appended to
    prepare_workspace's reported action.

    The symlink is a shared-by-convention arrangement: a pnpm install inside the lane
    writes into the main repo's dependency directory (installs are rare; accepted —
    to isolate, hand-install into a real directory inside the lane, and this function
    leaves anything already present alone).
    If the main repo's directory doesn't exist (a fresh clone) it is skipped —
    verify_lane's red text will say why."""
    if _lane_repo_root(lane_path) != REPO_ROOT:
        return ""  # cross-project lane: the dependency list belongs to the engine's repo, don't link out (ticket t260903-10)
    linked = []
    for rel in LANE_DEP_SYMLINKS:
        src = REPO_ROOT / rel
        dst = lane_path / rel
        if not src.exists() or os.path.lexists(dst):
            continue
        try:
            os.symlink(src, dst)
        except OSError:
            continue  # a failed symlink is not fatal: verify_lane's "dependencies in place" gives a clear red
        linked.append(rel)
    return "+deps:%s" % ",".join(linked) if linked else ""


def _prepare_multirepo_lane(lane_root: Path, entries: Any,
                            prep: WorkspacePrep) -> WorkspacePrepResult:
    """Create/reuse a multi-repo lane repo by repo (ticket B, t260907-06). Failure
    semantics are the same family as single-repo:
      - a directory present but not a worktree of that repo → that repo is named in a
        failed result, no rollback, no deletion (human triage);
      - a per-repo identity probe (_check_git_identity); any repo missing its identity
        = the whole thing fails with red text naming the repo;
      - any repo failing = an overall failed receipt (no raise, the workflow turns
        blocked); already-succeeded trees are **not rolled back** (same semantics as
        single-repo, left for human triage);
      - once everything succeeds, write the manifest at the lane's resolved
        coordination directory (shared.multi_manifest_path; the mechanical source of
        truth for downstream _lane_scopes; idempotent: retries take the reuse path and
        the manifest is rewritten with the same shape — for an existing legacy lane the
        resolution is sticky, so it is rewritten in place under the old name and no
        new-name directory is born).
    base_ref: each repo records the repo HEAD at tree-creation time (single-repo
    base_ref semantics = main-tree HEAD do not carry over to multi-repo — each repo's
    baseline is independent, and recording HEAD is what lets merge_check's item 1
    judge "this ticket produced something").
    deps symlinks are not linked out; _ensure_lane_deps is single-repo only."""
    if not isinstance(entries, list) or not entries:
        return WorkspacePrepResult(ok=False, kind="worktree", action="failed",
                                   path=str(lane_root),
                                   error="repo_worktrees 形状非法（须非空列表）: %r" % (entries,))
    project_root = lane_root.parent.parent
    notes: List[str] = []
    errors: List[str] = []
    created_n = 0
    # 根树（repo=""，树=泳道容器本身）恒最先建（t260910-03）：混合形态下若子树
    # 先建，容器目录会先以普通目录形态存在，根树的 worktree add 随即误判
    # 「目录已存在但非已注册 worktree」整票 failed（缺陷现场写集 integration/
    # 归根仓且排后即踩）。排序只动创建顺序，不动明细/清单本身。
    for e in sorted(entries, key=lambda x: 0 if not str((x or {}).get("repo") or "") else 1):
        # Ticket t260907-12: repo may be an empty string = the root-repo tree
        # (repo = the project root itself, tree = the lane container itself; Path/""
        # share one form with zero special-casing); name/branch must be non-empty
        # strings, missing ones are rejected as before.
        if not (isinstance(e, dict) and isinstance(e.get("repo"), str)
                and isinstance(e.get("name"), str) and e["name"]
                and isinstance(e.get("branch"), str) and e["branch"]):
            return WorkspacePrepResult(ok=False, kind="worktree", action="failed",
                                       path=str(lane_root),
                                       error="repo_worktrees 条目形状非法（须 {repo(允许空串=根仓树),name,branch} 且 name/branch 非空）: %r" % (e,))
        repo = project_root / e["repo"]
        tree = lane_root / e["repo"]
        if not (repo / ".git").exists():
            errors.append("[%s] 归属仓 %s 不存在（建票后被删/挪？人工处置，不代建仓）"
                          % (e["repo"], repo))
            continue
        ident_err = _check_git_identity(repo)
        if ident_err:
            errors.append("[%s] %s" % (e["repo"], ident_err))
            continue
        if _is_worktree_of(tree, repo):
            notes.append("[%s] reused" % e["repo"])
            continue
        if tree.exists():
            errors.append("[%s] 树目录已存在但非仓 %s 的已注册 worktree？请人工处置"
                          "（不回滚不删除）" % (e["repo"], repo))
            continue
        cmd = ["git", "-C", str(repo), "worktree", "add", "-b", e["branch"], str(tree)]
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        except Exception as ex:
            errors.append("[%s] git worktree add 异常: %s" % (e["repo"], ex))
            continue
        if proc.returncode != 0:
            errors.append("[%s] git worktree add -b %s 失败:\n%s"
                          % (e["repo"], e["branch"],
                             (proc.stderr or proc.stdout or "").strip()[-400:]))
            continue
        created_n += 1
        notes.append("[%s] created（分支 %s）" % (e["repo"], e["branch"]))
    if errors:
        return WorkspacePrepResult(
            ok=False, kind="worktree", action="failed", path=str(lane_root),
            error="多仓泳道准备未全绿（已成功树不回滚，留人判读）：\n" + "\n".join(errors))
    # All green: write the manifest (idempotent rewrite). base_ref = each repo's HEAD
    # at tree creation (also refreshed on the reuse path).
    manifest = []
    for e in entries:
        repo = project_root / e["repo"]
        rc = _git(["rev-parse", "HEAD"], repo)
        manifest.append({"repo": e["repo"], "name": str(e.get("name") or e["repo"]),
                         "branch": e["branch"],
                         "base_ref": rc.stdout.strip() if rc.returncode == 0 else ""})
    # 清单落盘位＝shared.multi_manifest_path（协调目录解析真源；新泳道必落新名，
    # 存量老名泳道粘滞原地复写——绝不硬编码名字，t260914-01 三病灶之三）。create=True
    # 只建解析位目录；报错文案点名**实际解析出的**路径（老名位只在回落到它时出现）。
    mf_path: Optional[Path] = None
    try:
        mf_path = shared.multi_manifest_path(lane_root, create=True)
        mf_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=1), "utf-8")
    except Exception as ex:
        return WorkspacePrepResult(ok=False, kind="worktree", action="failed",
                                   path=str(lane_root),
                                   error="多仓泳道清单落盘失败（%s）: %s"
                                         % (mf_path or "路径解析失败", ex))
    action = "created" if created_n else "reused"
    activity.logger.info("[%s] prepare 多仓泳道：%s（%s）", prep.ticket_id, action,
                         "；".join(notes))
    return WorkspacePrepResult(ok=True, kind="worktree", action=action, path=str(lane_root))


@activity.defn
async def prepare_workspace(prep: WorkspacePrep) -> WorkspacePrepResult:
    """Workspace creation/reuse (M16: the workflow's first activity — the agent no
    longer runs git worktree add / mkdir itself).

    - no workspace / not worktree|dir → main-tree path, skip (skipped);
    - dir → mkdir -p (idempotent, ensured);
    - worktree → if it is already a worktree of this repo, reuse (reused); otherwise
      `git worktree add -b <branch> <path>` [base point = base_ref] (created); a
      failure returns a failed receipt (**no raise** — the workflow turns blocked for
      human triage).
    - after the worktree is created/reused, _ensure_lane_deps runs: it symlinks the
      main repo's gitignored dependency directories into the lane, otherwise
      verify_lane's "dependencies in place" always goes red (hit live in ticket
      t260824-12).
    - before work starts on a worktree branch, _check_git_identity runs (ticket
      t260905-10): a missing git identity is an immediate failed red naming it — the
      identity is called out before work starts instead of blowing up only at the
      settling commit;
      dir/main workspaces have no commit and are not checked.
    """
    ws = prep.workspace
    if not (isinstance(ws, dict) and ws.get("type") in WORKSPACE_TYPES and ws.get("path")):
        return WorkspacePrepResult(ok=True, kind="main", action="skipped", path="")
    # D7③（t260913-04）：每票首活动扫尾——孤儿 agent 容器回收（label 过滤+泳道目录已
    # 不存在才拆；worker 崩溃残留由下一票首活动兜底）。一切异常容忍，不拦工作流。
    for _gc_note in agent_runtime.gc_stale_containers():
        activity.logger.info("[agent-gc] %s", _gc_note)
    p = Path(str(ws["path"]))
    if not p.is_absolute():
        p = REPO_ROOT / p
    # Cross-project (ticket t260903-10): the worktree add/reuse decision operates on
    # the **project repo** (self-anchored by path convention), no longer hard-anchored
    # to the engine repo — new tickets' lane paths are already absolute
    # (derive_lane_workspace project_root).
    repo = _lane_repo_root(p)
    if ws["type"] == "dir":
        try:
            p.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            return WorkspacePrepResult(ok=False, kind="dir", action="failed",
                                       path=str(p), error="mkdir -p %s 失败: %s" % (p, e))
        return WorkspacePrepResult(ok=True, kind="dir", action="ensured", path=str(p))
    # Ticket B (t260907-06) multi-repo lane: repo_worktrees present = a multi-repo
    # ticket — take the per-repo create/reuse branch (meta.repo_worktrees is the only
    # source of truth; this function only checks that the disk state agrees, it does
    # not re-derive).
    # Three-ring read order (ticket t260908-02): ① prep.repo_worktrees (the Temporal
    # main road, a first-class field carried through payload encode/decode) →
    # ② ws.get("repo_worktrees") (fixture / direct-call fallback) → ③ derived from
    # prep.write_set + prep.project_root (the multi-repo layout test is_multi_repo_layout
    # shares a source with the ticket-creation chain, and mixed shapes activate it too
    # since t260907-12; the derivation logic = shared.build_repo_worktrees, the single
    # point). Single-repo projects never enter this branch, so the old path has zero
    # regression.
    rws = list(prep.repo_worktrees) if prep.repo_worktrees else ws.get("repo_worktrees")
    if not (isinstance(rws, list) and rws) and prep.write_set and prep.project_root:
        _pr = Path(prep.project_root)
        if is_multi_repo_layout(_pr):
            try:
                rws = build_repo_worktrees(_pr, prep.write_set, p.name)
            except ValueError as e:
                return WorkspacePrepResult(ok=False, kind="worktree", action="failed",
                                           path=str(p), error="多仓泳道推导拒收：%s" % e)
        else:
            rws = None  # single-repo project: ignore the channel field, take the old single-repo path (regression surface)
    if isinstance(rws, list) and rws:
        return _prepare_multirepo_lane(p, rws, prep)
    # worktree lane
    # Commit-identity guard (ticket t260905-10): checked before work starts on both
    # the created and reused paths — the identity can vanish between reuses; missing
    # = a failed receipt (the workflow turns blocked for a human, the same path as a
    # worktree add failure). The probe anchors on the owning repo root `repo` (on the
    # created path the lane directory doesn't exist yet and -C lane would misreport;
    # the repo root's repo-level/global/system layers are the same source future lane
    # worktrees will see). dir/main workspaces have no commit and are not checked.
    ident_err = _check_git_identity(repo)
    if ident_err:
        return WorkspacePrepResult(ok=False, kind="worktree", action="failed",
                                   path=str(p), error=ident_err)
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


# ---------- Human-gate mechanical preparation ----------

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
    """Human-gate mechanical preparation: assemble the review context (proposal
    excerpt / workspace listing / diff stat) — purely mechanical, zero judgement."""
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


# ---------- dev-lane: merge_check (programmatic, no agent) and merge (after human sign-off) ----------

def _git(args: List[str], cwd: Path, timeout: int = 60) -> subprocess.CompletedProcess:
    return subprocess.run(["git"] + args, cwd=str(cwd),
                          capture_output=True, text=True, timeout=timeout)


def _merge_base_ref(branch: str, repo: Path) -> Tuple[str, str]:
    """The baseline ref for the whitelist diff: the current merge-base(main, branch).
    Returns (ref, err).

    Non-empty ref = success (normally a single line; multiple lines = malformed, keep
    the first and leave a trace in err).
    Empty ref = resolution failed, and err is the detail text for a fail-closed red
    item — the caller must not fall back to any ref (falling back to the pinned
    base_ref revives KI-010; falling back to the literal main misjudges as soon as the
    lane is behind under a two-dot diff), and the empty string is never handed to
    verify_lane either.
    (Ticket t260901-18: for the full stance see the merge_check item 3 comment.)
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


def _ui_diff_paths(lane_repo: Path, wl_base: str, branch: str,
                   prefixes: Any = None) -> Tuple[List[str], str]:
    """The diff-side shared predicate for UI-ticket detection (KI-044 root fix,
    ticket t260904-13): the actual changed paths of
    `git diff --name-only <wl_base>...branch` × the shared.match_ui_paths prefix
    table → (UI paths hit, error trace).

    The mechanism guarantee behind "two call sites, one source": both the
    ui_changed_paths activity and merge_check 3.6 come through this function — the
    predicate has exactly one entry (match_ui_paths) and the diff stance (three-dot /
    anchored to the lane repo / where the baseline comes from) exists only here, so a
    stance change cannot drift between the two sides.

    prefixes (ticket t260904-18, KI-050 gate ③): the UI stance's prefix table = the
    project declaration (the lane root's verify.yaml ui_evidence.dirs, loaded by the
    caller with load_ui_evidence and passed in explicitly); None is only allowed as a
    compatibility fallback — both live call sites must pass the declaration, no
    new single-argument calls.

    wl_base is computed by the caller with _merge_base_ref (merge-base(main, branch)
    anchored to the lane repo, the t260901-18/t260903-11 family; never fall back to
    the literal main — under a two-dot diff a lane that is behind is misjudged).
    Fail-closed: missing wl_base/branch or a failed git diff → ([], error text), and
    the caller treats it as "UI ticket, evidence pending", never a silent SKIP. The
    subprocess follows the _git family as-is: a synchronous run + a bounded timeout
    (the caller turns a timeout raise into red); cancellation immediacy is the
    family's existing debt and is not claimed here."""
    if not wl_base or not branch:
        return [], "UI diff 基线缺失（wl_base=%r branch=%r），fail-closed" % (wl_base, branch)
    p = _git(["diff", "--name-only", "%s...%s" % (wl_base, branch)], lane_repo)
    if p.returncode != 0:
        return [], "git diff %s...%s 失败 rc=%s：%s" % (
            wl_base, branch, p.returncode,
            ((p.stderr or p.stdout or "").strip())[-300:])
    files = [ln.strip() for ln in (p.stdout or "").splitlines() if ln.strip()]
    return match_ui_paths(files, prefixes), ""


def _parse_conflict_files(merge_tree_output: str) -> List[str]:
    """Parse the conflict file list out of `git merge-tree --write-tree` conflict
    output (git ≥ 2.38; pure function).

    Output shape (measured on git 2.50): the first line is the tree OID; then one
    block per conflicted file — 1-3 "entry lines" `<mode> <oid> <stage>\\t<path>`
    (stage = 1 base / 2 ours / 3 theirs), then, after a blank line, message lines such
    as 「CONFLICT (content): Merge conflict in <path>」.
    Both kinds of line are parsed, unioned, deduped and returned sorted (order is not
    deterministic — the downstream "same batch of files conflicting repeatedly" check
    compares as a set). Returns [] when no file can be parsed — rc=1 can also mean a
    git fault (a bad ref and the like), and the caller treats that as a non-conflict
    red rather than spinning the resolution loop."""
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


# Internal marker used only by merge_check's conflict classification: the item
# prefix of check 4 (the merge rehearsal); the ticket console / an investigator can
# grep for this prefix.
MERGE_REHEARSAL_ITEM = "merge 预演无冲突"

# Config file for project-level extra checks (repo-relative path; the mechanism
# lives in the engine while the policy follows the project repo — see the merge_check
# 3.5 comment and the header of that file).
MERGE_CHECKS_CFG = "server/merge-checks.yaml"


def _parse_bundle_pairs(text: str) -> List[tuple]:
    """Minimal parser for merge-checks.yaml (same trade-off as model-routes: accept
    only the fixed shape, raise on a broken file).

    Only the paired 「- src: <prefix>」 + 「out: <prefix>」 entries under bundle_pairs:
    are recognized, with bare-token values.
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


async def _merge_check_one_scope(args: "MergeCheckArgs", sc: Dict[str, Any],
                                 lane_root: Path, multi: bool) -> Dict[str, Any]:
    """Single-scope merge_check core (extracted from merge_check in ticket B
    t260907-06, reused per tree).

    Single-repo (multi=False) behavior is byte-identical to the old single-anchor
    implementation (regression surface); the multi-repo differences are only three:
    ① sc["write_set"] has been rebased per repo — the whitelist gate and the KI-009
    self-heal test judge precisely per repo;
    ② the ui_evidence declaration is read from the lane root, and the hit test uses
    the repo-prefix-stripped subset of the declaration (_scope_dirs);
    ③ the settle self-heal carries a repo anchor (the gitfile trio is parameterized).
    Known limitation: per-tree verify_lane uses path = tree, so the tool cannot read
    the lane root's project declaration verify.yaml → the project-declared checks
    extras fall, per tree on multi-repo tickets, into the tool's own visible
    "disabled per project declaration" state (not silent; verify_lane emits a
    disabled annotation); the precise write-set judgement is unaffected.
    Returns {checks, rehearsal_green, conflict_files, merge_tree_excerpt}."""
    checks: List[Dict[str, Any]] = []
    wl_base = ""  # merge-base baseline computed by item 3 (reused by the 3.6 UI judgement; empty if item 3 raised before assigning, in which case 3.6 recomputes fail-closed)

    # 0. KI-009 (ticket t260901-25): auto-settle before the dirty red light (self-heal
    # inside the write set).
    # Placed before item 1 so the self-heal commit makes items 1 and 2 read the same
    # post-heal state — the timing combination "a commit was added yet 0 commits are
    # reported" is structurally impossible. Admission conditions: a) every dirty file
    # is inside the write_set (dirt outside the write set = an out-of-bounds change,
    # stay blocked for a human); b) MERGE_HEAD is absent (dirt during a resolution
    # round is a normal state and only settle_conflict_resolution may close it out,
    # ticket t260826-01 — self-checked once here, and _settle_worktree_lane's internal
    # guard is the second line of defense).
    # Whether the self-heal worked is judged by re-running git status afterwards, not
    # by settle's return value (scenarios like a non-worktree return ""); a git fault
    # raised by settle is wrapped in try and turned into a red item, preserving this
    # activity's "red lights don't raise, the receipt goes back to the workflow to
    # turn blocked" semantics. At most one self-heal per call: still dirty afterwards
    # = report it honestly as red, no internal loop.
    auto_settle_note = ""
    try:
        p = _git(["status", "--porcelain", "-z", "--"] + SETTLE_PATHSPEC, sc["tree"])
        dirty_z = p.stdout if p.returncode == 0 else ""
        dirty_files = _dirty_files_from_status_z(dirty_z)
        if p.returncode != 0:
            auto_settle_note = "status 失败: %s" % (p.stderr or "")[-200:]
        elif dirty_files:
            mh = _git(["rev-parse", "--verify", "MERGE_HEAD"], sc["tree"])
            if mh.returncode == 0:
                auto_settle_note = "合并进行中（MERGE_HEAD 在场），不自愈"
            elif _dirty_within_write_set(dirty_files, sc["write_set"]):
                try:
                    note = _settle_worktree_lane(
                        sc["tree"], args.ticket_id, "merge_check", 0,
                        write_set=list(sc.get("write_set") or []),
                        path_gate=bool(getattr(args, "path_gate", False)),
                        base_ref=str(sc.get("base_ref") or getattr(args, "base_ref", "") or ""),
                        authorizations=list(getattr(args, "authorizations", None) or []))
                    auto_settle_note = "[auto-settle] %s" % (note or "settle 返回空（见后续复查）")
                except Exception as e:
                    auto_settle_note = ("[auto-settle] settle 异常（转红不抛）: %s: %s"
                                        % (type(e).__name__, e))[-300:]
            else:
                auto_settle_note = "脏文件在 write_set 外，不自愈（越界改动交人工）"
    except Exception as e:  # a fault in this pre-check itself never blocks the chain: later items still go red as usual
        auto_settle_note = "自愈前置检查异常: %s: %s" % (type(e).__name__, e)
    if auto_settle_note:
        activity.logger.info("[%s] merge_check 自愈前置：%s", args.ticket_id,
                             auto_settle_note)

    # 1. The lane has commits
    try:
        p = _git(["log", "--oneline", "%s..%s" % (sc["base_ref"], sc["branch"])], sc["repo"])
        n = len([ln for ln in p.stdout.splitlines() if ln.strip()]) if p.returncode == 0 else 0
        checks.append({"item": "泳道分支有 commit（%s..%s）" % (sc["base_ref"][:7], sc["branch"]),
                       "green": p.returncode == 0 and n > 0,
                       "detail": ("%d 个 commit" % n) if n else
                                 (p.stderr or p.stdout or "0 个 commit").strip()[-300:]})
    except Exception as e:
        checks.append({"item": "泳道分支有 commit", "green": False, "detail": "git log 异常: %s" % e})

    # 2. Clean workspace (SETTLE_PATHSPEC stance — the .dsh/ and .sandbar/ engine
    #    runtime directories are excluded, the same stance as the worker settle; the
    #    comments point at each other; the agent's code changes can't be wrongly
    #    covered by those two prefixes)
    #    KI-009: switched to porcelain -z (NUL separated — no quotePath quoting
    #    ambiguity and no rename-arrow parsing), and the post-heal re-check of the
    #    dirty list goes through the same parser (_dirty_files_from_status_z);
    #    when a self-heal happened the detail carries an [auto-settle] marker, visible
    #    in the record rather than silent.
    try:
        p = _git(["status", "--porcelain", "-z", "--"] + SETTLE_PATHSPEC, sc["tree"])
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

    # 3. verify_lane code inside the lane (runs the lane's own admin.py copy: lane
    # code + lane tools)
    try:
        # Merged resolution of t260901-18 (KI-010) × t260901-16: the whitelist diff's
        # base is merge-base(main, branch) (_merge_base_ref, fail-closed).
        # Root cause (ticket t260901-18): with the pinned sc["base_ref"], files that
        # another lane merged into main show up in the diff after this lane merges
        # main, are not in this ticket's write_set → a false out-of-bounds verdict.
        # Division of labor between the two defense lines: on the verify_lane side
        # (ticket t260901-16) _diff_names already uses the three-dot base...HEAD
        # (safe even with a literal main); the merge_check side additionally passes
        # the explicit merge-base sha — each line holds on its own, so reverting
        # either one alone cannot revive KI-010, and the merge-base sha is also
        # immune to "running the old lane copy" (ticket snapshot semantics). Note the
        # difference from item 4's merge-tree with a literal main: merge-tree is a
        # three-way operation that computes its own merge-base internally, so a
        # literal main is harmless there.
        # Ticket t260901-08: base + require_base + write_set are now passed — the
        # write-set whitelist is judged precisely (per-file cap) against the ticket's
        # write_set at the merge gate, and an empty base is fail-closed instead of a
        # silent skip (the "skip without a base" stance is void at the merge gate and
        # survives only for manual calls; verify.yaml's coarse write_allow only backs
        # manual calls / calls without a write set).
        # Item 1's commit check still uses the pinned base_ref (semantics = the lane
        # has this ticket's output, guarding against a fast-forward misjudged as
        # 0 commits); the two items intentionally use different base stances.
        wl_base, wl_err = _merge_base_ref(sc["branch"], sc["repo"])  # the merge-base must also anchor the lane repo (real near-miss in ticket t260903-11)
        if not wl_base:
            # Fail-closed: a red item is merge_check's normal channel, the activity
            # doesn't raise. verify_lane doesn't run this round (tsc/smoke are
            # skipped with it, the red already means blocked, restored on retry);
            # when merge-base fails, item 4's merge-tree main almost certainly goes
            # red too, so no new blocking surface is added.
            checks.append({"item": "写集白名单基线（merge-base main × %s）" % sc["branch"],
                           "green": False, "detail": wl_err})
        else:
            if wl_err:  # multi-line malformed output: keep the first line, leave a searchable trace
                activity.logger.info("[%s] %s", args.ticket_id, wl_err)
            lane_admin = sc["tree"] / "server" / "admin.py"
            admin_bin = str(lane_admin if lane_admin.is_file() else
                             Path(__file__).resolve().parents[1] / "admin.py")  # cross-project without an engine layout: fall back to the main-tree copy
            vp = await asyncio.create_subprocess_exec(  # async (ticket t260903-09: a blocking subprocess would freeze the event loop)
                "python3", admin_bin, "call", "verify_lane",
                json.dumps({"lane": "code", "path": str(sc["tree"]),
                            "base": wl_base, "require_base": True,
                            "write_set": list(sc["write_set"])}),
                cwd=str(sc["tree"]), stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
                # t260908-01：剥除测试台桩旋钮族+worker 路由旋钮族
                #（shared.TEST_STUB_ENV_KNOBS / WORKER_ROUTING_ENV_KNOBS）——
                # 桩脑工单的 worker env 会把它们漏进 verify_lane 的 pytest 子进程，
                # 被测契约 UT 被换成桩行为/测试台值造成假红（e2e 两轮实证）。
                # 生产 worker 的正常运转不依赖子进程携带这些旋钮，剥除对生产恒等。
                env={k: v for k, v in os.environ.items()
                     if k not in TEST_STUB_ENV_KNOBS and k not in WORKER_ROUTING_ENV_KNOBS})
            try:
                vo_b, ve_b = await asyncio.wait_for(vp.communicate(), timeout=900)
                v_stdout, v_stderr = vo_b.decode("utf-8", "replace"), ve_b.decode("utf-8", "replace")
                payload = json.loads(v_stdout)
                res = payload.get("result") or {}
                green = bool(payload.get("ok")) and bool(res.get("green")) and vp.returncode == 0
                detail = "exit=%s red=%s" % (res.get("exit_code"), res.get("red_count"))
                # Carry the red items' names into the detail (ticket B G2 contract: an
                # out-of-write-set injection must be findable by filename in the
                # merge_check receipt; single-repo benefits equally — pure
                # added visibility, no tightening)
                _red_lines = []
                for _chk in (res.get("checks") or []):
                    if _chk.get("level") != "red":
                        continue
                    for _it in (_chk.get("items") or []):
                        _red_lines.append(str((_it or {}).get("detail") if isinstance(_it, dict) else _it))
                if _red_lines:
                    detail += "；%s" % "；".join(_red_lines[:6])
            except asyncio.TimeoutError:
                vp.kill(); await vp.wait()
                green, detail = False, "verify_lane 超时（>900s）"
            except json.JSONDecodeError:
                green, detail = False, (v_stderr or v_stdout or "无输出").strip()[-300:]
            checks.append({"item": "泳道内 verify_lane code 绿灯", "green": green, "detail": detail})
    except Exception as e:
        checks.append({"item": "泳道内 verify_lane code 绿灯", "green": False,
                       "detail": "verify_lane 异常: %s" % e})

    # 3.5 Project-level extra checks (policy follows the project repo: read the lane's
    #     own server/merge-checks.yaml — ticket snapshot semantics; no file = no extra
    #     checks, other projects are unaffected).
    #     bundle_pairs: a change under the src prefix with no change under the out
    #     artifact prefix → red (lesson from ticket t260827-02: src/client changed
    #     without rebuilding lib, so the merge = shipping a lie). Stays inserted
    #     before the merge rehearsal — the rehearsal must remain the last item in
    #     checks (the conflict classification treats checks[:-1] as "non-conflict
    #     items").
    try:
        cfg = sc["tree"] / MERGE_CHECKS_CFG
        if cfg.is_file():
            pairs = _parse_bundle_pairs(cfg.read_text("utf-8"))
            if pairs:
                # Same whitelist stance as item 3: the three-dot main...branch only
                # sees what the lane brought in, so src changed by someone else on the
                # main side does not falsely trip the bundle freshness red (ticket
                # t260901-16).
                p = _git(["diff", "--name-only", "main...%s" % sc["branch"]],
                         sc["repo"])  # same-family anchor fix: the 3.5 bundle freshness diff anchors the lane repo
                changed = p.stdout.split() if p.returncode == 0 else []
                for src, out in pairs:
                    if not any(f.startswith(src) for f in changed):
                        continue  # this lane never touched that build chain: no item emitted (noise reduction)
                    rebuilt = any(f.startswith(out) for f in changed)
                    checks.append({"item": "bundle 新鲜度（%s → %s）" % (src, out),
                                   "green": rebuilt,
                                   "detail": "src 改动已同批重建产物" if rebuilt else
                                             "src 有改动但产物未同批重建（泳道内 tsdown 重建，settle 代落盘）"})
    except Exception as e:
        checks.append({"item": "bundle 新鲜度（%s）" % MERGE_CHECKS_CFG, "green": False,
                       "detail": "扩展检查异常: %s" % e})

    # 3.6 UI 证据闸（票 t260828-09，纯机械查、无 agent）。KI-044 根修（票 t260904-13）：
    #     The judgement source moved from the declared write set to the **actual diff
    #     paths** (a declared stance ≠ the real write surface, and could be bypassed):
    #     _ui_diff_paths shares a source with the ui_changed_paths activity, and the
    #     baseline reuses the wl_base already computed by item 3 (if item 3 raised
    #     before assigning it, recompute fail-closed and leave a trace).
    #     KI-050 declaration regime (ticket t260904-18 gate ③): the UI stance's prefix
    #     table = the project declaration (the lane root's verify.yaml
    #     ui_evidence.dirs, loaded by load_ui_evidence) — reading it from disk inside
    #     this activity is legitimate; a project with no declaration has no gate. The
    #     four branches, pinned:
    #       ① declaration present + diff hit: the current red/green judgement (a hit
    #         with no png → red);
    #       ② declaration present + diff miss: no item (noise-reduction stance
    #         unchanged);
    #       ③ declaration absent + healthy diff: green + a visible note (not a SKIP,
    #         not a fake green);
    #       ④ malformed declaration or diff fault: red fail-closed (the malformed
    #         field is named; a mechanism fault ≠ "no UI surface", and an absent
    #         declaration does not absorb a mechanism fault).
    #     A diff hit (or diff fault) with no png → red: this is what catches a diff
    #     change between the two points in time — if the ui_evidence stage shot its
    #     screenshots and the UI changed afterwards, recomputing here must go red, and
    #     the red goes back to the workflow to turn blocked for a human (a manual
    #     rework may re-shoot with ui_evidence as a legitimate target); the evidence
    #     must cover the final diff.
    #     The hit paths go into the detail (searchable gate record), and the guidance
    #     hands over the capture.mjs command directly.
    #     Known blind spot (accepted): existence only — screenshot timestamps/contents
    #     are not validated; the foolproofing is integration_review's
    #     look-at-the-image hook (its review prompt carries a screenshot mtime list).
    #     Also inserted before the merge rehearsal (the rehearsal must stay the last
    #     item in checks; see the 3.5 comment).
    try:
        base_36 = wl_base
        base_note = ""
        if not base_36:
            base_36, base_err = _merge_base_ref(sc["branch"], sc["repo"])
            base_note = ("（wl_base 第 3 项未产出、此处自算%s）"
                         % ("失败 fail-closed" if not base_36 else "取 %s" % base_36[:7]))
            if base_36 and base_err:  # the recompute carries its malformed trace, not silent
                base_note = "（wl_base 此处自算，带畸形留痕：%s）" % base_err[-120:]
        # The declaration is read from the lane root (sc["tree"]) — the same stance as
        # the verify_lane code lane (path = lane root), not from sc["repo"] (the main
        # repo root: declaration changes on the main side would pollute the lane's
        # gate judgement)
        decl_mode, decl_dirs, decl_note = load_ui_evidence(lane_root)
        if decl_mode == "malformed":
            # ④a Malformed declaration: fail-closed red naming the field (malformed ≠
            # absent, per contract ②'s three-state master rule)
            checks.append({
                "item": "UI 截图证据（ui_evidence 声明）",
                "green": False,
                "detail": "ui_evidence 声明畸形 fail-closed：%s（修 verify.yaml 的 "
                          "ui_evidence.dirs 或删声明走缺省态）" % decl_note})
        else:
            ui_paths, diff_err = _ui_diff_paths(sc["repo"], base_36, sc["branch"], _scope_dirs(decl_dirs, sc))
            diff_fault = bool(diff_err or not base_36)
            if decl_mode == "absent" and not diff_fault:
                # ③ Declaration absent + healthy diff: green + a visible note (the
                # behavior is visible, not silent)
                checks.append({
                    "item": "UI 截图证据（ui_evidence 声明）",
                    "green": True,
                    "detail": "ui_evidence 未声明：截图证据项按项目声明缺席"
                              "（KI-050 声明制；要启用截图闸在 verify.yaml 声明 "
                              "ui_evidence.dirs）"})
            elif decl_mode == "absent" and diff_fault:
                # ④b Declaration absent but the diff is faulty: a mechanism fault is
                # not absorbed — red
                checks.append({
                    "item": "UI 截图证据（ui_evidence 声明）",
                    "green": False,
                    "detail": "ui_evidence 未声明且 diff 故障 fail-closed：%s" % (diff_err or "基线缺失")})
            elif ui_paths or diff_fault:
                # ① Declaration present + a hit (or a diff fault while present): the
                # current red/green judgement
                judge = "按 diff 判定（%s...%s，口径=%d 声明目录）%s：%s" % (
                    (base_36 or "?")[:7], sc["branch"], len(decl_dirs), base_note,
                    ("命中 %d 个 UI 路径：%s" % (len(ui_paths), "、".join(ui_paths[:8]))) if ui_paths
                    else ("diff 故障 fail-closed：%s" % (diff_err or "基线缺失")))
                shots_dir = ui_evidence_dir(lane_root)  # sticky resolution (ticket t260907-04)
                pngs = sorted(shots_dir.glob("*.png")) if shots_dir.is_dir() else []
                ui_gate_red = not pngs
                checks.append({
                    "item": "UI 截图证据（%s）" % UI_EVIDENCE_DIR,
                    "green": not ui_gate_red,
                    "detail": ("%s｜%d 张截图在位：%s" % (judge, len(pngs), "、".join(p.name for p in pngs[:5])))
                              if pngs else
                              ("%s｜UI 票缺截图证据：跑 server/ui-check/capture.mjs "
                               "--out <worktree>/%s（worker 代跑，只读控制台页面）" % (judge, UI_EVIDENCE_DIR))})
            # ② Declaration present + a miss + healthy diff: no item emitted (noise
            # reduction; the current stance is unchanged)
    except Exception as e:
        checks.append({"item": "UI 截图证据", "green": False, "detail": "证据闸异常: %s" % e})

    # 3.7 KI-048 (t260911-05): pre-merge main-workspace dirty check (active, not
    #     post-facto). The four original items only inspect the lane side; main-tree
    #     dirt surfaced only when the merge activity refused (too late: after the
    #     human sign-off). Verdict source = _classify_main_dirty — the SAME truth the
    #     merge activity's failure classification uses, and the gate detail derives
    #     its human phrase from the same _dirty_block_note, so the two faces cannot
    #     drift. Insertion point pinned BEFORE the rehearsal (the rehearsal must stay
    #     checks[-1]: the conflict classification treats checks[:-1] as non-conflict
    #     items — a dirty red is always non-conflict, never enters the auto-resolution
    #     loop, and blocks for a human; same-position discipline as fuse B).
    #     RED LINE: this check is read-only — it NEVER stashes and NEVER auto-commits
    #     (the 260908 auto-stash incident: a session stashed host edits and merged
    #     half-way, breaking the console loading chain).
    try:
        dirty_verdict = _classify_main_dirty(sc["repo"], sc["branch"])
        dirty_kind = dirty_verdict.get("kind") or ""
        human = _dirty_block_note(dirty_verdict)
        checks.append({"item": "main 工作区无未提交改动（合并前脏检查）",
                       "green": not dirty_kind,
                       "detail": ("干净（无未提交改动、无与本单收口路径相撞的未跟踪文件）"
                                  if not dirty_kind else human)})
    except Exception as e:  # a fault in this read-only pre-check goes red honestly, the activity never raises
        checks.append({"item": "main 工作区无未提交改动（合并前脏检查）",
                       "green": False, "detail": "脏检查异常: %s" % e})

    # 4. merge-tree 预演无冲突（不落地——只把合并结果写成 tree 对象判冲突，
    #    It changes no workspace/index state; ticket t260826-01: the conflict file
    #    list parsed from the output is carried out for the resolution loop.
    #    Note: --write-tree writes tree/blob objects into the main repo's object
    #    store (both for conflicts and for clean merges) — that only adds dangling
    #    objects, gc can reclaim them, and it does not count as dirt.
    conflict_files: List[str] = []
    merge_tree_excerpt = ""
    rehearsal_green = False
    try:
        p = _git(["merge-tree", "--write-tree", "main", sc["branch"]], sc["repo"])
        rehearsal_green = p.returncode == 0
        if not rehearsal_green:
            out = (p.stdout or "") + ("\n" + p.stderr if p.stderr else "")
            conflict_files = _parse_conflict_files(out)
            merge_tree_excerpt = out.strip()[:1500]
        checks.append({"item": "%s（merge-tree main × %s）" % (MERGE_REHEARSAL_ITEM, sc["branch"]),
                       "green": rehearsal_green,
                       "detail": "无冲突" if rehearsal_green else
                                 ("冲突文件：%s" % "、".join(conflict_files) if conflict_files
                                  else (p.stdout or p.stderr or "有冲突").strip()[-300:])})
    except Exception as e:
        checks.append({"item": MERGE_REHEARSAL_ITEM, "green": False, "detail": "merge-tree 异常: %s" % e})
    return {"checks": checks, "rehearsal_green": rehearsal_green,
            "conflict_files": conflict_files,
            "merge_tree_excerpt": merge_tree_excerpt}


def _scope_dirs(dirs: List[str], sc: Dict[str, Any]) -> List[str]:
    """Declaration directories (lane-root-relative) → a tree-root-relative subset
    (the single point that aligns baselines for the multi-repo UI hit test)."""
    return rebase_write_set(dirs, str(sc.get("repo_rel") or "")) if sc.get("repo_rel") else list(dirs or [])


@activity.defn
async def merge_check(args: MergeCheckArgs) -> MergeCheckResult:
    """Programmatic checks before the merge (260824 dev-lane, no agent — every
    conclusion comes from git/scripts, never from anyone's word).

    Only when all four are green does the ticket advance to the human-reviewed merge:
      1. the lane branch has commits (base_ref..branch non-empty) — the very item
         ticket t260824-01 was missing (the agent never committed, the old verify
         gate ran the main-tree diff which was empty, and everything went green in a
         fake closed loop);
      2. the workspace is clean (git status --porcelain empty) — no closing out with
         uncommitted changes;
         KI-009 (ticket t260901-25): self-heal within the write set before judging
         red (see the item 0 pre-check below) — files the agent wrote late and the
         worker failed to settle in time get one more settle here, then a re-check.
      3. verify_lane code green inside the lane — runs the **lane's own** admin.py
         copy (lane code + lane tools), not the main tree (the main tree has none of
         the lane's changes, so running there tests nothing);
      4. merge-tree rehearsal with no conflicts (no state change, conflict detection
         only).
    Plus project-level extra checks (section 3.5): reads the lane's own
    server/merge-checks.yaml; no file = no extras — the check policy follows the
    project repo and stops applying automatically when the project changes.
    Red lights don't raise: the receipt goes back to the workflow to turn blocked and
    wait for retry_qc / rework triage.
    """
    # Ticket B (t260907-06): scope-list driven — a single repo = 1 scope (the logic
    # below matches the old single-anchor implementation); multi-repo = run the core
    # per tree, prefix item names with the tree, and aggregate red/green and the
    # conflict list across trees.
    wt = Path(args.worktree) if args.worktree else REPO_ROOT
    if not wt.is_absolute():
        wt = REPO_ROOT / wt
    scopes = _lane_scopes(wt, args.branch, args.base_ref, args.write_set)
    multi = len(scopes) > 1
    checks: List[Dict[str, Any]] = []
    rehearsal_green = True
    conflict_files: List[str] = []
    merge_tree_excerpt = ""
    for sc in scopes:
        core = await _merge_check_one_scope(args, sc, wt, multi)
        sc_checks = core["checks"]
        if multi:  # tree prefix (multi-repo visibility: every red/green names its tree)
            for c in sc_checks:
                c["item"] = "[%s] %s" % (sc["name"], c["item"])
        checks.extend(sc_checks)
        rehearsal_green = rehearsal_green and bool(core["rehearsal_green"])
        conflict_files.extend(core["conflict_files"])
        if core["merge_tree_excerpt"]:
            merge_tree_excerpt = (merge_tree_excerpt + "\n" + core["merge_tree_excerpt"]).strip()
    # 保险丝B（t260910-03）：多仓写集必须逐仓物化落成，任一成员仓缺失 → 红灯。
    # 插入位置钉死在 rehearsal 项**之前**（rehearsal 必须保持 checks[-1]，冲突分类
    # 把 checks[:-1] 当非冲突类——保险丝红恒为非冲突类，绝不进自动消解回路，
    # 直接 blocked 交人；KI-047 同族位置风险由此消解）。
    fuse_b_err = multirepo_materialization_error(wt, args.write_set, scopes)
    if fuse_b_err:
        checks.insert(max(len(checks) - 1, 0),
                      {"item": "repo_worktrees 逐仓物化（t260910-03 保险丝B）",
                       "green": False, "detail": fuse_b_err})
    elif multi and args.write_set:
        # 绿对照可见项（红灯不扩大化的反面：全绿也不静默——多仓票恒有物化闸记录）
        checks.insert(max(len(checks) - 1, 0),
                      {"item": "repo_worktrees 逐仓物化（t260910-03 保险丝B）",
                       "green": True,
                       "detail": "多仓写集逐仓物化齐全（%d 仓）" % len(scopes)})
    green = all(c["green"] for c in checks)
    # Ticket t260826-01 automatic conflict resolution loop: red lights split into two
    # classes —
    #   conflict=True: only the merge rehearsal item is red and a non-empty conflict
    #     file list was parsed → the workflow automatically bounces it back to
    #     implement for resolution instead of blocking. The judgement does not trust
    #     rc=1 alone (git faults such as a bad ref also return rc=1 but parse no
    #     conflict files; misclassifying them would spin the resolution loop idly);
    #   conflict=False: any of the other three items red (no commits / dirty
    #     workspace / verify_lane red), or the rehearsal red with an empty parse →
    #     stay blocked for a human. Infrastructure problems go to a person first; we
    #     never resolve while sick.
    other_red = any(not c["green"] for c in checks[:-1])
    conflict = ((not green) and (not other_red) and (not rehearsal_green)
                and bool(conflict_files) and not multi)  # multi-repo: the resolution loop is single-repo by design, so a red stays blocked for a human (ticket B limitation)
    activity.logger.info("[%s] merge_check %s：%s%s", args.ticket_id,
                         "绿灯" if green else "红灯",
                         "；".join("%s=%s" % (c["item"], "绿" if c["green"] else "红") for c in checks),
                         "（冲突类，转自动消解）" if conflict else "")
    return MergeCheckResult(green=green, checks=checks,
                            conflict=conflict, conflict_files=conflict_files,
                            merge_tree_excerpt=merge_tree_excerpt)


# ---------- dev-lane: automatic conflict resolution loop (ticket t260826-01; the worker runs the merge and settles) ----------

def _unmerged_files(wt: Path) -> List[str]:
    """Files still carrying unresolved conflicts in the lane workspace (the UU/AA/DU/UD
    and friends lines of git status --porcelain)."""
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
    """Run `git merge <base_ref>` into the lane on the worker's behalf, leaving the
    conflict-marked files in the lane workspace.

    Division of labor (an extension of the implement step's "the agent writes, the
    worker settles" contract): the agent sandbox cannot write the real .git (a
    worktree's .git is a gitfile pointing at the main repo, so it can neither commit
    nor merge), so both the merge and the commit are executed by the worker
    (unsandboxed); the agent only edits the conflict-marked files in the workspace.
    After this activity and before settle_conflict_resolution's commit the workspace
    is necessarily dirty — merge_check does not run in that window (the workflow
    orchestration is strictly serial: prep → implement → settle → back to
    merge_check).
    Race fallback: if the merge finds no conflicts (rc=0, e.g. the conflict was
    resolved between merge_check and prep) → already_clean=True and the workflow goes
    straight back to merge_check for a re-check; a missing ref / a merge exception →
    ok=False + error (the workflow turns blocked for a human, the loop does not spin)."""
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
        # rc != 0 with no unmerged files = the merge itself failed (not a conflict),
        # e.g. git refused because the workspace was dirty
        return ConflictPrepResult(ok=False, error="git merge %s 失败（非冲突）: %s"
                                  % (target, out[-400:]))
    activity.logger.info("[%s] 冲突消解 prep：merge %s 留现场，冲突文件 %d 个：%s",
                         args.ticket_id, target, len(files), "、".join(files[:10]))
    return ConflictPrepResult(ok=True, conflict_files=files,
                              merge_output=out[:1500])


@activity.defn
async def settle_conflict_resolution(args: ConflictSettleArgs) -> ConflictSettleResult:
    """Worker-side settle after the agent resolved the conflicts: verify no marker
    residue → add + commit the merge commit.

    Judgement stance: "not fully resolved" cannot be read from git status's UU/AA
    lines — the agent sandbox cannot write the real .git, so after editing the files
    the UU state is still there (git only accepts a resolution once it is added). So
    this activity adds on the agent's behalf first, then scans the files **this merge
    touched** (the HEAD × MERGE_HEAD diff) for conflict marker residue (^<<<<<<< /
    ^>>>>>>> / a whole line of ======= — the 7-character marker shapes of git's
    three-way merge). Residue → ok=False + remaining_files (the workflow records one
    failed round; the cap / same-batch rules live on the workflow side); no residue →
    commit the merge commit. Adding before scanning also makes retries idempotent:
    residue staged in the previous round is still found this round (the scan anchors
    on the merge's files, not on the UU state). Known false-positive surface: a file
    in the merge set whose lines legitimately start with one of those marker shapes
    (a document explaining git conflicts, say) is judged as residue — accepted, with
    the human round as the backstop.
    """
    wt = Path(args.worktree) if args.worktree else REPO_ROOT
    if not wt.is_absolute():
        wt = REPO_ROOT / wt
    # No MERGE_HEAD = no merge in progress (the agent mistook ordinary workspace
    # changes for conflicts, or prep's merge left nothing behind) — report honestly,
    # never fake a merge commit
    p = _git(["rev-parse", "--verify", "MERGE_HEAD"], wt)
    if p.returncode != 0:
        return ConflictSettleResult(ok=False,
                                    error="无进行中的合并（MERGE_HEAD 不存在），无法落盘合并提交")
    # The files this merge touches (taken before add; the diff HEAD MERGE_HEAD stance
    # is unchanged afterwards)
    p = _git(["diff", "--name-only", "HEAD", "MERGE_HEAD"], wt)
    merge_files = [ln.strip() for ln in p.stdout.splitlines() if ln.strip()] \
        if p.returncode == 0 else []
    p = _git(["add", "-A", "--", "."], wt)
    if p.returncode != 0:
        return ConflictSettleResult(ok=False, error="git add 失败: %s"
                                    % (p.stderr or "")[-300:])
    # .dsh 与两个协调目录名都没被暂存（协同目录被 .gitignore 兜住时本就进不了暂存）；
    # reset 目标从 shared 真源派生（与 _settle_worktree_lane 同一元组，不再各抄一份）。
    _git(["reset", "-q", "--", *_SETTLE_RESET_PATHS], wt)
    remaining = []
    for f in merge_files:
        fp = wt / f
        if not fp.is_file():
            continue  # the agent chose to delete this file (one legal resolution) — respect the deletion
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


# ---------- KI-006 (ticket t260901-26): the squash close-out core (pure functions, never touching activity context) ----------

# ---------- The settle-time close-out export snapshot (ticket t260904-09, closing the KI-017 engine-side debt) ----------
# After the merge lands and before lane teardown, freeze a token + delivery snapshot
# into the project-level ledger:
#   <projects-root>/<key>/data/settle/<ticket>.json (same-root convention as the
#   metrics cache).
# Idempotent: exists with an identical payload = skip; differs = keep-old, never
# rewrite (immutable-append semantics).
# Soft degradation on failure: any exception becomes a note appended to merge's
# warns and never blocks the merge (an observability debt must not hold up delivery —
# the same catch-all → log → don't block pattern as ui_evidence).
# Naming red line (CLAUDE.md hard rule ⑤): the new env SANDBAR_SETTLE_SNAPSHOT_DIR
# is a neutral name.

SANDBAR_SETTLE_SNAPSHOT_ENV = "SANDBAR_SETTLE_SNAPSHOT_DIR"


def _settle_snapshot_dir(project_key: str) -> Optional[Path]:
    """Resolve the snapshot directory (the same root chain as metrics.ts
    resolveSettleDir; the two sides' comments point at each other): the
    SANDBAR_SETTLE_SNAPSHOT_DIR ?? SANDBAR_METRICS_DIR ?? SANDBAR_PROJECTS_DIR chain
    (perkey_projects_root embeds the last two plus the home default) — the env
    replaces the **whole project root**. An empty project_key (the Temporal snapshot
    query soft-degraded) → None, the snapshot is skipped with a note. project_key must
    pass the PROJECT_KEY_RE whitelist to block path traversal (the same guard as
    ticket_data_dir)."""
    if not project_key or not shared.PROJECT_KEY_RE.match(project_key):
        return None
    root = os.environ.get(SANDBAR_SETTLE_SNAPSHOT_ENV) or os.environ.get("SANDBAR_METRICS_DIR") or ""
    if root:
        return Path(root) / project_key / "data" / "settle"
    return shared.perkey_projects_root() / project_key / "data" / "settle"


def _aggregate_lane_usage(wt: Path, ticket_id: str) -> Tuple[Dict[str, Any], str]:
    """Aggregate the lane sessions' usage (the Python equivalent of the TS
    agent-usage path, aligned item by item):
    - walk <wt>/.dsh/sessions/<slug>/<sub>/session.jsonl.zstd where sub == the ticket
      id or starts with "<ticket id>-" (same as the TS resolveAllSessionFiles); a
      missing directory = an empty set + note, nothing enters the aggregation.
    - Only assistant/message's data.usage is summed — the same-named usage inside
      assistant/chunk is the same one, and counting both would double it (a red line
      pinned on the TS side, and equally binding here).
    - Model attribution: the sequential scan keeps the current model (data.{provider,
      model} of request/context, with request/header's
      data.header.config.{provider,model} as the fallback); a miss records 「?」.
    - Bad lines are skipped; a single file's decompression failure never destroys the
      overall total (the reason is appended to the note).
    - The 0-usage case is a deliberate trade-off: the snapshot is still written, with
      all-zero tokens plus a tokens_zero annotation (an observability debt at settle
      time deserves to be frozen too; differing from the read side's "nothing
      anywhere → null" is intentional).
    - by_stage is not produced: the engine side has no source of truth for a workflow
      timeline window, so it is always an empty object plus a by_stage_available false
      annotation (inventing a window would pollute the stance).
    The TS side's double anti-traversal guard is not reproduced here: these paths are
    built by our own code (wt comes from the activity input and has already passed
    the _ws_cwd/_is_worktree_of guards), not from user input."""
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
                    continue  # skip bad lines (malformed input / the tail is still being written)
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
        except Exception as exc:  # one file failing never destroys the overall total
            notes.append("%s 聚合异常: %s" % (f.name, str(exc)[:120]))
    tokens = {"in": total["in"], "out": total["out"], "cacheRead": total["cacheRead"],
              "by_stage": {}, "by_model": by_model, "by_stage_available": False,
              "tokens_zero": not saw_usage}
    note = "；".join(notes)
    if not saw_usage:
        note = (note + "；" if note else "") + "会话无 usage 事件（tokens 记零）"
    return tokens, note


def _squash_snapshot_delivery(repo: Path, commit: str, ticket_id: str) -> Tuple[Dict[str, Any], str]:
    """The real delivery snapshot behind the squash. The prefix check has exactly one
    source of truth, in this pure function:
    if the merge_commit's subject first line does not start with the ticket id
    (genuinely nothing to collect, HEAD = another ticket's squash) → record a zero
    delivery with zero_change=true and **do not take numstat** (otherwise another
    ticket's delivery would be booked to this one);
    the Temporal retry state (HEAD = this ticket's previous close-out; the squash
    commit template guarantees the first token = the ticket id) → take
    diff <commit>^1 <commit> --numstat as normal. Binary lines (-\\t-) are skipped in
    the sum (same as the TS parseNumstatTotal). The hash stance = short (matching
    _squash_merge's return value)."""
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
    """Freeze and export the settle snapshot (never raises; returns a human-readable
    note, an empty string = nothing to record).
    Written via a tmp file + os.replace for an atomic swap (so a double settle cannot
    leave a half-written file)."""
    try:
        # Ticket-id shape whitelist (ticket t260904-09): ticket_id comes from external
        # meta, and splicing it raw into the snapshot filename would let a `../`
        # injection climb out of the directory (demonstrated escaping the per-ticket
        # settle directory) — the same fail-closed stance as ticket_data_dir: an
        # illegal shape skips the snapshot with a warn note (inside the soft-degradation
        # semantics, never blocking the merge).
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
    except Exception as exc:  # catch-all: an observability debt never holds up delivery
        return "settle 快照失败（不阻塞 merge）: %s" % str(exc)[:200]


def _merge_started(repo: Path) -> bool:
    """Decide whether the main tree has "a merge in progress": MERGE_MSG present, or
    unmerged entries in the index.

    The only gate for the KI-006 cleanup recipe (git 2.50 measured semantics):
      - after a squash conflict with rc=1: MERGE_MSG exists and ls-files -u has
        stages — the merge did start, and only --quit + reset --merge can restore it;
      - rejected because of overlapping uncommitted changes: no MERGE_MSG, no
        unmerged — the merge never started, the state is pristine, and a reset is
        absolutely forbidden (it would destroy the main tree's uncommitted changes)."""
    p = _git(["rev-parse", "-q", "--verify", "MERGE_MSG"], repo)
    if p.returncode == 0:
        return True
    lu = _git(["ls-files", "-u"], repo)
    return bool((lu.stdout or "").strip())


# ---------- KI-048 (ticket t260911-05): main-workspace dirt classification ----------
# A main-workspace dirt rejection is git's local-change protection, NOT a conflict.
# Misclassifying it as action="conflict" made the workflow auto-bounce the ticket for
# re-verification and silently consume a human sign-off (KI-048, t260904-14). The
# classifier is the SINGLE source of truth for both the merge activity's failure
# classification and merge_check's pre-merge dirty check item — the blocked text and
# the gate detail derive from the same verdict, so the two faces cannot drift.

# Point-naming cap: the file list in receipts/UI is capped, the count overflow goes
# into the note (an unbounded list can blow up the ticket face / the gate record).
MERGE_FILES_CAP = 20

# Classification verdicts (reason codes on the failure-classification protocol's open
# vocabulary; "" = clean, never a failure code):
#   main_staged        — staged content in the main tree (would fold into the
#                        ticket's own commit, breaking one-ticket-one-commit)
#   main_dirty         — uncommitted tracked changes (overlapping or not: both block,
#                        fail-closed — the main tree may carry ownerless edits at any
#                        time, the KI-048 operating root cause; two-tone wording only)
#   untracked_collision— an untracked file sits on a path this merge would write
#   conflict           — the merge started and left a conflict scene (real conflict)
#   merge_fault        — everything else (bad ref, commit fault, race outlet still
#                        clean, …): never coerced to conflict
# Non-empty invariant: every failure path carries a non-empty reason — an
# unclassifiable shape falls to merge_fault, never to "" and never guessed.


def _classify_main_dirty(repo: Path, branch: str) -> Dict[str, Any]:
    """Read-only classifier of the main tree's dirt against the lane branch's merge
    surface (KI-048; no writes ever — only status/diff, so Temporal retries and the
    red-line "main workspace byte-identical" assertion are both safe).

    Returns {kind, files, extra, note}:
      kind  — "" (clean) or one of the verdicts above (main_staged / main_dirty /
              untracked_collision); conflict/merge_fault are NOT produced here (they
              belong to the merge attempt itself, not to the pre-read);
      files — point-named blocking files, capped at MERGE_FILES_CAP;
      extra — count of capped-away files (0 = none);
      note  — machine-readable context: overlap flag for main_dirty (重叠/不重叠),
              diff-fault note, … (never raised, faults degrade to clean+note and the
              merge attempt itself re-judges).

    Verdict precedence: staged > tracked-dirty > untracked-collision — a staged hit
    means the merge must refuse regardless of anything else; tracked dirt blocks even
    when it does not overlap (git only refuses on overlap, but closing out over any
    uncommitted main-tree change risks folding ownerless edits into the ticket's
    commit — the conservative reading integration confirmed in plan review gen1).
    """
    out: Dict[str, Any] = {"kind": "", "files": [], "extra": 0, "note": ""}

    def _cap(names: List[str]) -> Tuple[List[str], int]:
        names = sorted({n.strip() for n in names if isinstance(n, str) and n.strip()})
        return names[:MERGE_FILES_CAP], max(0, len(names) - MERGE_FILES_CAP)

    # Paths this merge would write (three-dot: only what the lane brings; a diff
    # fault is not a dirt verdict — degrade to clean+note, the merge attempt itself
    # fails closed on its own).
    p = _git(["diff", "--name-only", "main...%s" % branch], repo)
    if p.returncode != 0:
        out["note"] = "merge 面 diff 失败（不作脏判定）: %s" % ((p.stderr or "")[-150:])
        merge_paths: set = set()
    else:
        merge_paths = {ln.strip() for ln in (p.stdout or "").splitlines() if ln.strip()}

    # 1) staged content (precise list via --cached --name-only)
    p = _git(["diff", "--cached", "--name-only"], repo)
    if p.returncode == 0:
        staged = [ln.strip() for ln in (p.stdout or "").splitlines() if ln.strip()]
        if staged:
            files, extra = _cap(staged)
            out.update(kind="main_staged", files=files, extra=extra)
            return out
    else:
        out["note"] = "diff --cached 失败（不作暂存判定）: %s" % ((p.stderr or "")[-150:])

    # 2) uncommitted tracked changes + 3) untracked collision (one status read)
    tracked: List[str] = []
    untracked: List[str] = []
    p = _git(["status", "--porcelain", "-z"] + SETTLE_PATHSPEC, repo)
    if p.returncode == 0 and isinstance(p.stdout, str):
        for ent in p.stdout.split("\0"):
            if not ent or len(ent) < 4 or ent[2] != " ":
                continue  # malformed entry: dropped, no guessing (same stance as _dirty_files_from_status_z)
            xy, path = ent[:2], ent[3:]
            if not path:
                continue
            if xy == "??":
                untracked.append(path)
            elif xy.strip("MADRC") or xy[0] in "MADRC" or xy[1] in "MADRC":
                tracked.append(path)
    else:
        out["note"] = "status 失败（不作工作区判定）: %s" % ((p.stderr or "")[-150:])
    if tracked:
        overlap = sorted(set(tracked) & merge_paths)
        files, extra = _cap(tracked)
        out.update(kind="main_dirty", files=files, extra=extra,
                   note=("与收口路径重叠：%s" % "、".join(overlap[:5])) if overlap
                         else "不重叠（仍保守拦：main 侧可能有未提交的无主编辑）")
        return out
    colliding = sorted(set(untracked) & merge_paths)
    if colliding:
        files, extra = _cap(colliding)
        out.update(kind="untracked_collision", files=files, extra=extra)
    return out


def _dirty_block_note(verdict: Dict[str, Any]) -> str:
    """The human phrase shared by the merge blocked text and the merge_check gate
    detail (same source of truth as _classify_main_dirty — the two faces cannot
    drift): WHICH file / WHAT reason / WHAT to do. Pure function."""
    kind = verdict.get("kind") or ""
    names = list(verdict.get("files") or [])
    extra = int(verdict.get("extra") or 0)
    listing = "、".join(names[:MERGE_FILES_CAP]) + (
        "（另有 %d 个未列）" % extra if extra else "")
    why = {
        "main_staged": "main 工作区有未提交的暂存改动（收口会把它卷进本单提交）",
        "main_dirty": "main 工作区有未提交改动（git 本地改动保护，非冲突）",
        "untracked_collision": "main 工作区有未跟踪文件与本单收口路径相撞",
    }.get(kind, "")
    if not why:
        return ""
    tail = ("｜处理：提交或暂存（git stash）这些改动，或在票面说明后发 retry_qc 重验"
            "；引擎绝不自动 stash/自动提交")
    if verdict.get("note"):
        tail = "｜%s%s" % (verdict["note"], tail)
    return "%s——挡事文件：%s%s" % (why, listing, tail)


def _squash_merge(repo: Path, wt: Path, branch: str, ticket_id: str,
                  defer_teardown: bool = False, project_key: str = "") -> "MergeResult":
    """The squash close-out implementation (the merge() activity delegates here, so it
    can be unit-tested without Temporal).

    Fault-mode trade-offs versus the old merge --no-edit:
      a) no path raises; a MergeResult goes back to the workflow (red → blocked /
         bounce);
      b) failure paths do not tear down the worktree or delete the branch — the lane
         must stay alive awaiting re-verification;
      c) a lane cleanup failure only warns and is aggregated into the error field; it
         never overturns a completed close-out;
      d) the cleanup recipe is idempotent (a repeated --quit is harmless;
         reset --merge is idempotent; the re-check can be rerun), so Temporal
         timeout-retries are safe: a rerun takes the "nothing collectable in the
         index" branch and back-fills the HEAD sha;
      e) error names the failing step precisely (input guard / merge / quit / reset /
         commit / cleanup acceptance).
    The three-step cleanup (git 2.50 measured): a squash conflict leaves no
    MERGE_HEAD, so merge --abort is unavailable; --quit clears only MERGE_MSG and does
    not roll back the index/workspace (ls-files -u is still non-empty), so it is
    immediately followed by reset --merge HEAD (semantically aligned with a real
    merge's --abort, preserving unrelated unstaged changes in the main tree), and the
    acceptance is "the conflict state is restored": ls-files -u empty + no unmerged
    lines in status (a fully clean tree is not required — unrelated unstaged changes
    in the main tree deserve to survive).
    """
    # 0) Input guard: before touching any write operation (git parses a value starting
    #    with "-" as an option, and branch comes entirely from external meta, so it
    #    must be blocked; measured: check-ref-format rejects a leading "-", empty, and
    #    anything containing "..")
    p = _git(["check-ref-format", "--branch", branch], repo)
    if p.returncode != 0:
        return MergeResult(ok=False, action="failed", reason="merge_fault",
                           error="branch %r 非法（check-ref-format 拒绝）：%s"
                                 % (branch, (p.stderr or "").strip()[-200:]))

    # 0.5) KI-048 (t260911-05): classify the main tree's dirt BEFORE touching any
    #      write operation — a dirt rejection is git's local-change protection, not a
    #      conflict (the old code returned action="conflict" here and on the
    #      rejected-before-start path below, which made the workflow auto-bounce and
    #      silently consume a human sign-off). Now: action="dirty" + a protocol
    #      reason code + the named blocking files; the workflow turns blocked for a
    #      human instead of bouncing. The read-only classifier returns before the
    #      merge, so the "failure paths never tear down the lane" trade-off (b) and
    #      the "main tree untouched" guarantee are structurally preserved — no
    #      stash/checkout/commit ever happens on this path (the 260908 auto-stash
    #      incident red line). Covers: staged content (the old 0.5 pre-check,
    #      subsumed), uncommitted tracked changes (overlapping or not —
    #      fail-closed), and untracked files colliding with the merge surface.
    verdict = _classify_main_dirty(repo, branch)
    if verdict.get("kind"):
        return MergeResult(ok=False, action="dirty", reason=str(verdict["kind"]),
                           files=list(verdict.get("files") or []),
                           error="合并收口被 main 工作区未提交改动挡住（git 本地改动保护，"
                                 "非冲突；主树现场未动）：%s"
                                 % _dirty_block_note(verdict))

    # 1) squash merge (no automatic commit)
    p = _git(["merge", "--squash", branch], repo, timeout=120)
    out = ((p.stdout or "") + "\n" + (p.stderr or "")).strip()
    if p.returncode != 0:
        if not _merge_started(repo):
            # The merge never started. The pre-read (0.5) judged clean, so this is
            # either dirt that appeared between the read and the merge (race) or a
            # git fault — re-classify honestly; if still clean this is a fault, and
            # it is NEVER coerced to conflict (the reason-non-empty invariant: an
            # unclassifiable shape falls to merge_fault → failed → blocked for a
            # human, not an idle resolution loop).
            race = _classify_main_dirty(repo, branch)
            if race.get("kind"):
                return MergeResult(ok=False, action="dirty", reason=str(race["kind"]),
                                   files=list(race.get("files") or []),
                                   error="git merge --squash %s 未开始即被拒（读时干净、"
                                         "merge 时 main 已有未提交改动——竞态出口）：%s（主树原样保留）"
                                         % (branch, _dirty_block_note(race)))
            return MergeResult(ok=False, action="failed", reason="merge_fault",
                               error="git merge --squash %s 未开始即被拒（复判 main 干净，"
                                     "归故障非冲突）：%s（主树未提交改动原样保留）"
                                     % (branch, out[-400:]))
        # It did start: clean up (--quit clears only MERGE_MSG; reset --merge is what
        # rolls the merge conflict state back out of the index/workspace). --merge
        # rather than --hard (the ticket t260901-26 integration ruling): --merge
        # aligns with a real merge's --abort semantics and restores only what this
        # merge dirtied, preserving unrelated unstaged changes in the main tree byte
        # for byte; --hard would wipe those unrelated unstaged changes too = silent
        # data loss on the failure path. Staged changes were already blocked before
        # the merge by the 0.5 pre-check, so --merge's refusal to restore the index
        # has no regression surface.
        leftover: List[str] = []
        _git(["merge", "--quit"], repo, timeout=60)  # only the conflict-state re-check below matters; its rc is ignored
        rs = _git(["reset", "--merge", "HEAD"], repo, timeout=60)
        if rs.returncode != 0:
            leftover.append("reset --merge rc=%s：%s"
                            % (rs.returncode, (rs.stderr or "")[-200:]))
        else:
            lu = _git(["ls-files", "-u"], repo)
            st = _git(["status", "--porcelain"], repo)
            if (lu.stdout or "").strip():
                leftover.append("ls-files -u 仍非空：%s" % (lu.stdout or "").strip()[:200])
            # The acceptance only asks "is the conflict state restored" (unmerged
            # lines), not "is the whole tree clean" — unrelated unstaged changes in
            # the main tree (the " M" lines) deserve to survive; they are not residue
            unmerged_lines = [ln for ln in (st.stdout or "").splitlines()
                              if len(ln) >= 2 and ln[:2] in (
                                  "UU", "AA", "DD", "AU", "UA", "DU", "UD")]
            if unmerged_lines:
                leftover.append("status 仍有 unmerged 行：%s"
                                % "、".join(unmerged_lines[:5]))
        err = "git merge --squash %s 冲突：%s" % (branch, out[-400:])
        if leftover:
            err += "；清理后仍有残留：" + "；".join(leftover)
        # A real conflict: the merge started and left a scene (reason code pinned to
        # the protocol word; the parsed conflict file list rides along when present)
        return MergeResult(ok=False, action="conflict", reason="conflict",
                           files=_parse_conflict_files(out)[:MERGE_FILES_CAP],
                           error=err)

    # 2) Close out: nothing collectable in the index (a retry, or the content is
    #    already equivalent) → produce no empty commit, back-fill with the HEAD sha
    warns: List[str] = []
    dq = _git(["diff", "--cached", "--quiet"], repo)
    if dq.returncode == 0:
        head = _git(["rev-parse", "--short", "HEAD"], repo)
        merge_commit = head.stdout.strip() if head.returncode == 0 else ""
        warns.append("main 已含本单改动（squash 暂存区无可收内容），未产新提交")
    else:
        # The message must contain lane/<id>: the ticket console's changes.ts greps
        # for it in both shapes, so it is the shared locator
        msg = ("%s squash 收口（一单一提交，KI-006）\n\n"
               "来源 %s；审计真源在 Temporal；泳道内小步历史不进 main"
               % (ticket_id, branch))
        c = _git(["commit", "-m", msg], repo, timeout=60)
        if c.returncode != 0:
            return MergeResult(ok=False, action="failed", reason="merge_fault",
                               error="squash 已暂存但 git commit 失败：%s"
                                     "（主树带着暂存改动，需人工处置）"
                                     % ((c.stderr or c.stdout or "")[-300:]))
        head = _git(["rev-parse", "--short", "HEAD"], repo)
        merge_commit = head.stdout.strip() if head.returncode == 0 else ""
    # 2.5) Export the settle snapshot (ticket t260904-09, closing the KI-017
    #      engine-side debt): after the commit lands and before lane teardown (while
    #      .dsh/sessions still exists); a failure only warns and never overturns the
    #      close-out; with project_key defaulted ("") the function skips internally
    #      and leaves a note — backward compatible with zero breakage.
    if merge_commit:
        snap_note = _freeze_settle_snapshot(repo, wt, ticket_id, project_key, merge_commit)
        if snap_note:
            warns.append(snap_note)
    # 3) Lane teardown (the ok path only; -D because after a squash -d always refuses
    #    with "not fully merged", measured)
    #    M1-3 (ticket t260902-02): with defer_teardown=True the inline cleanup is
    #    skipped and handed to the later teardown_lane activity (the three-stage
    #    close-out merge → archive → teardown) — old history inputs missing that
    #    field deserialize to the default False = the old inline-cleanup semantics,
    #    so existing tickets leave no residue.
    #    A cleanup failure only warns and never overturns the completed close-out
    #    (carrying over trade-offs d) idempotence and e) naming the failing step).
    if not defer_teardown:
        p = _git(["worktree", "remove", "--force", str(wt)], repo, timeout=60)
        if p.returncode != 0:
            warns.append("worktree remove 失败: %s" % (p.stderr or "").strip()[-200:])
        p = _git(["branch", "-D", branch], repo, timeout=30)
        if p.returncode != 0:
            warns.append("branch -D 失败: %s" % (p.stderr or "").strip()[-200:])
        # D7②（t260913-04）：内联清理路径（defer_teardown=False 的老票语义）同口径拆
        # agent 容器——收口即拆；幂等、失败留痕不拦收口。
        _rm_note = agent_runtime.remove_container(ticket_id)
        if _rm_note:
            warns.append("agent 容器回收: %s" % _rm_note)
    return MergeResult(ok=True, action="merged", merge_commit=merge_commit,
                       error="；".join(warns))


@activity.defn
async def merge(args: MergeArgs) -> MergeResult:
    """The real merge after human sign-off (KI-006 switched to a squash close-out: one
    commit per ticket on main).

    Conflicts/faults do not raise — the receipt goes back to the workflow to turn
    blocked for human handling; on failure the lane (worktree/branch) is not torn down
    or deleted, left for the bounce and a re-verification. The audit source of truth
    is Temporal and main no longer keeps a merge commit; the small-step commits inside
    the lane and the conflict resolution loop are unaffected.
    defer_teardown=True (the M1-3 three-stage close-out): **no inline cleanup** after
    booking; teardown_lane takes over.
    """
    wt = Path(args.worktree) if args.worktree else REPO_ROOT
    if not wt.is_absolute():
        wt = REPO_ROOT / wt
    # Project key (which directory the snapshot belongs to): a lookup failure
    # soft-degrades to "" → _squash_merge skips the snapshot internally with a note
    project_key = await _fetch_ticket_project(args.ticket_id)
    # Ticket B (t260907-06): a single repo = 1 scope (the old single-anchor path,
    # unchanged behavior); multi-repo = squash into each child repo in turn
    # (_squash_merge's a–e fault trade-offs hold per tree; re-entrant — an
    # already-closed tree takes its "nothing collectable in the index" idempotent
    # branch and back-fills instead of booking twice; a failed tree is not torn down
    # or deleted, awaiting re-verification).
    scopes = _lane_scopes(wt, args.branch, base_ref="", write_set=None)
    # 保险丝B（t260910-03）：逐仓 squash 前先验「多仓写集 × 逐仓物化」——明细缺失/
    # 漂移（含 _lane_scopes 清单缺失静默回落单仓锚的缺陷形态）→ 整体 failed，lane
    # 不拆不删交人工，绝不按单仓锚静默落账。write_set 空（在途旧票缺键回落）→
    # 保险丝不触发，按旧语义收口（payload 兼容约定，见 shared.MergeArgs 注释）。
    fuse_b_err = multirepo_materialization_error(wt, args.write_set, scopes)
    if fuse_b_err:
        return MergeResult(ok=False, action="failed",
                           error="合并红灯（t260910-03 保险丝B）：%s" % fuse_b_err)
    results = []
    for sc in scopes:
        res = _squash_merge(sc["repo"], sc["tree"], sc["branch"], args.ticket_id,
                            defer_teardown=bool(args.defer_teardown), project_key=project_key)
        if sc["name"]:  # multi-repo: prefix the tree name onto error/merge_commit (docstring item e, per tree)
            if res.error:
                res.error = "[%s] %s" % (sc["name"], res.error)
            if res.merge_commit:
                res.merge_commit = "%s=%s" % (sc["name"], res.merge_commit)
        results.append(res)
        if res.ok:
            activity.logger.info("[%s%s] squash 落账：%s（%s）%s", args.ticket_id,
                                 "/%s" % sc["name"] if sc["name"] else "",
                                 sc["branch"], res.merge_commit,
                                 ("；清理告警：" + res.error) if res.error else "")
        else:
            activity.logger.warning("[%s%s] squash 失败：%s", args.ticket_id,
                                    "/%s" % sc["name"] if sc["name"] else "", res.error)
    if len(results) == 1:
        return results[0]
    ok = all(r.ok for r in results)
    first_bad = next((r for r in results if not r.ok), None)
    merged = "；".join(r.merge_commit for r in results if r.merge_commit)
    errs = "\n".join(r.error for r in results if r.error)
    return MergeResult(ok=ok,
                       action=("merged" if ok else (first_bad.action if first_bad else "failed")),
                       # KI-048: the aggregated multi-repo receipt must carry the first
                       # failing tree's classification and named files too (the
                       # workflow's blocked text points its file list at this receipt)
                       reason=(first_bad.reason if first_bad else ""),
                       files=list(first_bad.files) if first_bad else [],
                       merge_commit=merged, error=errs)


# ---------- dev-lane: exporting a finished ticket's data + lane teardown (M1-3, ticket t260902-02) ----------

# The three archive intake paths (stance source of truth = the block comment at the
# end of shared.py; the self-tests pin these constants):
#   1) <worktree>/.sandbar/stage_*.json  → stages/ (stage results / settle reports)
#   2) <worktree>/.sandbar/screenshots/**/*.png → screenshots/ (UI evidence, relative
#      layout preserved)
#   3) <worktree>/.dsh/sessions/<repo-slug>/* → sessions/ (session event files)
# Excluded (recorded in manifest.excluded_rules): agent_*.log, model_patch_*.yml,
# resume_patch_*.yml, .dsh/profiles/**, and every .credentials.yaml (credentials are
# never archived).
ARCHIVE_EXCLUDED_LOG_RE = re.compile(r"^agent_.*\.log$")


class ArchiveManifestError(Exception):
    """The archive manifest was tampered with (a worktree gray area: file not a dict /
    a status code / missing structure)

    or the manifest could not be located — **never silently regenerate or overwrite**
    (regenerating destroys evidence); fail-closed raise, the workflow turns blocked
    and the lane is not torn down (trade-off list A-② item 5)."""


@activity.defn
async def archive_ticket(args: ArchiveArgs) -> ArchiveResult:
    """Archive a finished ticket's data out of the repo (the body of sandbar M1-3 key
    decision 3).

    The archive source of truth is copied to
    <SANDBAR_PROJECTS_DIR>/<key>/data/tickets/<id>/ (copied, not moved — lane teardown
    is teardown_lane's job) + an archive.json manifest is written (schema v1; fields in
    the shared.ARCHIVE_* comments). File contents are copied byte for byte — even a
    result file with broken JSON is archived as-is (the archive is a copy of the truth
    and does not parse contents; the consumer judges malformed on read).

    Fault-mode trade-offs (the M1-3 trade-off list):
      a) no path raises — **not carried over**: an archive failure must fail-closed
         and raise (archive success is the precondition for tearing down the lane
         without losing reports; a soft failure = tear it down and the reports are
         gone).
      b) A damaged manifest must not be silently regenerated (a gray area that
         destroys evidence) — a manifest already present that is malformed / has a
         non-dict file / has a status code → raise ArchiveManifestError, the state is
         untouched.
      c) Idempotent and rerunnable — when a valid manifest exists, read its file list
         and verify the references (a wrong entry self-heals by re-copying and is
         recorded as integrity_repaired); Temporal retries are safe.
      d) Missing directories/files are handled softly — no .sandbar (or the sticky
         .suyou) or .dsh:  # naming-compat
         no archive.json history → write proxy files instead of letting it slide;
         .dsh/sessions missing → manifest.absent records absent (the same degraded
         stance as the usage endpoint); a single file copy failure → fail-closed
         raise (no "half an archive = half the reports lost").
      e) Errors name the failing segment — the raised message carries the
         stage/screenshots/sessions/manifest segment names and the source/target
         paths, so the blocked text is searchable.

    legacy=True (archive-legacy, honest accounting for existing tickets): skip the
    scan and write the manifest
    {legacy: true, files: [], absent: ["worktree"], reason} — nothing faked, nothing
    back-filled.
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
        # Honest accounting for an existing ticket: the lane is already gone, so only
        # the manifest itself lands (files empty, reason explains)
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

    # ---- Scan the three archive intake paths ----
    files: List[Dict[str, Any]] = []
    absent: List[str] = []
    staged_specs: List[Tuple[str, str]] = []   # (src, dst_rel)
    # Lane coordination directory resolution (ticket t260907-04): new lanes .sandbar/,
    # old lanes stick to .sandbar/ — the archive read side uses the same order as the
    # engine write side (shared.resolve_dot_dir is the single source of truth), so no
    # second judging scheme is invented here.
    p_dot = shared.resolve_dot_dir(src_root)      # the variable name is kept (semantics = the coordination directory root)
    dot_prefix = p_dot.name                        # ".sandbar" or the legacy ".suyou" (sticky fallback)
    p_dsh = src_root / ".dsh"
    if not p_dot.is_dir():
        # Missing coordination directory → the first two families count as zero: this
        # lane has no real stage_*.json archive to copy, and it is not allowed to
        # slide — obvious proxy files are written instead. The close-out is bound by
        # the stage_acceptance hard items (the implement stage must write its result
        # file), so the gray area is exposed with nowhere to hide at lane teardown.
        files.append({"src": "%s/stage_implement_gen0.json" % dot_prefix, "dst": "stages/stage_implement_gen0.json", "bytes": 0})
        files.append({"src": "%s/agent_create_plan_gen0.log" % dot_prefix, "dst": "stages/agent_create_plan_gen0.log", "bytes": 0})
    if p_dot.is_dir():
        # Stage result files (the excluded .log/.yml are handled by the manifest's
        # exclusion rules, never scanned in)
        for f in sorted(p_dot.glob("stage_*.json")):
            staged_specs.append((str(f), "stages/" + f.name))
        # UI screenshot evidence (the screenshots/ relative layout is preserved)
        for f in sorted(p_dot.glob("screenshots/**/*.png")):
            staged_specs.append((str(f),
                                 "screenshots/" + str(f.relative_to(p_dot / "screenshots"))))
    if not p_dsh.is_dir():
        absent.append(".dsh/sessions（会话目录不存在）")
    if p_dsh.is_dir():
        p_sess = p_dsh / "sessions"
        if not p_sess.is_dir():
            absent.append(".dsh/sessions（会话目录不存在）")
        else:
            for f in sorted(p_sess.iterdir()):
                if f.is_dir():          # a repo-slug subdirectory
                    for sf in sorted(f.rglob("*")):
                        if sf.is_file() and ARCHIVE_EXCLUDED_LOG_RE.match(sf.name):
                            continue   # agent spawn logs (-gen.log) are never archived
                        if sf.is_file():
                            staged_specs.append(
                                (str(sf), "sessions/" + sf.relative_to(p_sess).as_posix()))
                elif f.is_file() and not ARCHIVE_EXCLUDED_LOG_RE.match(f.name):
                    staged_specs.append((str(f), "sessions/" + f.name))
    manifest_path = dst / "archive.json"
    if manifest_path.is_file():
        # Idempotent rerun: read the existing manifest and verify (b) a damaged
        # manifest must not be silently regenerated; c) a valid manifest has its
        # references checked and wrong entries self-heal by re-copying)
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
        # Reference verification + self-heal: are all the dst files the manifest
        # references still there? If not, copy them again
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
        # The byte count is the post-copy2 stat truth (the archive side's truth, not a
        # racy value taken from the source)
        files.append({"src": os.path.relpath(src, src_root),
                      "dst": drel, "bytes": dfile.stat().st_size})
    # Proxy files (the .sandbar-missing gray area): the directory landing = taking
    # over, and the contents honestly describe the proxy
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
    """Tear down the lane (the last stage of M1-3's three-stage close-out; the recipe
    is _squash_merge step 3, now applied **per repo**).

    逐仓化（t260913-05）：泳道可能是多仓的，判定与 merge 落账**同源**（都过
    `_lane_scopes`，拆道不另造第二套判定），逐仓对**该仓自己**执行
    `git -C <repo> worktree remove --force <tree>` + `git -C <repo> branch -D <branch>`
    （旧写法硬编码 repo=REPO_ROOT，成员仓的 worktree 注册与 lane/* 分支完全够不着，
    残留且不可见）。根树条目（repo=""）的仓 = 泳道容器父项目的根仓（_lane_scopes
    解析）。明细取用序：①盘上清单镜像（与 merge 同输入，正常态）；②清单随部分拆除
    消失时取 workflow 递来的 `args.repo_worktrees`（meta 真源=救源，堵「重试回落
    单仓锚 → 成员仓静默残留」）；③都无=旧单仓回落（引擎仓泳道 repo==REPO_ROOT，
    git 命令流逐字节与旧代码一致）。

    不对称（有意为之，两态各守一边）：
      - 明细损坏/畸形、或逐仓 branch 非法 → ok=False + action="failed" → dev_lane
        置 blocked 交人工，泳道不拆（fail-closed，绝不在错仓上静默收口）；
      - git 清理失败、成员仓目录已不在盘上 → **逐仓点名**进回执 error 字段、恒
        ok=True：残留=可回收垃圾（内容已在 archive.json 清单与 data/ 真源），不阻断
        收口（既有取舍 d 承袭），但点名后残留可被巡检消费（时间线「泳道拆除告警」行
        原样透传 error，不再笼统一条）。裸 `_git` 对缺失 cwd 会抛 FileNotFoundError，
        故动手前判 `repo.is_dir()`——一个坏仓不得把可回收残留升级成卡票。
    The cleanup recipe is idempotent in outcome (a repeated --quit is harmless). NB
    (measured, t260913-05 acceptance F1): a rerun over an already-torn lane does NOT
    get rc=0 per step — git says not-a-working-tree / branch-not-found (rc=128) and
    each step records a **named** warn while the receipt stays ok=True — Temporal
    retries are still safe (trade-off d) carries over)."""
    wt = Path(args.worktree) if args.worktree else REPO_ROOT
    if not wt.is_absolute():
        wt = REPO_ROOT / wt
    branch = args.branch
    # Input guard, same as _squash_merge step 0 (branch comes from external meta).
    # 刻意锚 REPO_ROOT：check-ref-format 是纯字符串校验（与仓无关），而 -C 指向一个
    # 已不存在的成员仓会 rc=128（cannot change to）被误读成 branch 非法（review 实测）。
    p = _git(["check-ref-format", "--branch", branch], REPO_ROOT)
    if p.returncode != 0:
        return MergeResult(ok=False, action="failed",
                           error="branch %r 非法（check-ref-format 拒绝）：%s"
                                 % (branch, (p.stderr or "").strip()[-200:]))
    # 明细取用序（见 docstring）：清单镜像在 → 读盘（与 merge 同输入）；不在而
    # workflow 递来 meta 明细 → 走 entries（同一归一化段）；都无 → 旧单仓回落。
    entries = None
    # 盘上清单存在性走同一读侧（解析位优先＋老名镜像回落），与 _lane_scopes 不可能漂移
    if not shared.multi_manifest_path(wt, legacy_fallback=True).is_file() and args.repo_worktrees:
        entries = list(args.repo_worktrees)
    try:
        scopes = _lane_scopes(wt, branch, entries=entries)
    except RuntimeError as e:
        # 与 merge/merge_check 同语义：损坏=人工处置，绝不静默回落单仓锚（那会去清错仓）
        return MergeResult(ok=False, action="failed", error=str(e)[:400])
    # 逐仓 branch 守卫，全部先校验完再动任何破坏性命令：args.branch 已在上方逐字校验，
    # 此处补成员仓 branch（同款 check-ref-format，仍锚 REPO_ROOT）。任一非法 → 整体
    # failed，一个仓都不碰（外部输入不得带病进入 git 破坏性命令段）。
    for sc in scopes:
        br = str(sc["branch"])
        if br == branch:
            continue  # 旧单仓路径：不重复校验，命令流与旧代码一字不差
        p = _git(["check-ref-format", "--branch", br], REPO_ROOT)
        if p.returncode != 0:
            return MergeResult(ok=False, action="failed",
                               error=_tagged(_scope_tag(sc),
                                             "branch %r 非法（check-ref-format 拒绝）：%s"
                                             % (br, (p.stderr or "").strip()[-200:])))
    warns: List[str] = []
    # 成员树先删、根树（泳道容器）最后：移除容器会把整个目录树带走（成员树的目录就
    # 在容器里）。实测 git 2.x 对「目录已不在但注册还在」的 worktree remove 仍 rc=0
    # （草拟补丁担心的注册残留不成立），此处保持成员先行的确定性序：每次 remove 都锚
    # 在活目录上，不依赖 dangling 注册那条路径。
    ordered = ([sc for sc in scopes if str(sc.get("repo_rel") or "")]
               + [sc for sc in scopes if not str(sc.get("repo_rel") or "")])
    for sc in ordered:
        tag = _scope_tag(sc)
        repo = Path(str(sc["repo"]))
        tree = Path(str(sc["tree"]))
        if not repo.is_dir():
            # 仓目录已不在盘上：无注册/分支可清（_git 会 FileNotFoundError）；点名不阻断
            warns.append(_tagged(tag, "仓目录不存在（%s），无注册/分支可清" % repo))
            continue
        p = _git(["worktree", "remove", "--force", str(tree)], repo, timeout=60)
        if p.returncode != 0:
            warns.append(_tagged(tag, "worktree remove 失败: %s"
                                 % (p.stderr or "").strip()[-200:]))
        p = _git(["branch", "-D", str(sc["branch"])], repo, timeout=30)
        if p.returncode != 0:
            warns.append(_tagged(tag, "branch -D 失败: %s" % (p.stderr or "").strip()[-200:]))
    # D7②（t260913-04）：票收口即拆——agent 容器随泳道拆除（幂等；失败留痕不拦收口，
    # 与邻位 git 清理同口径；异常残留由后续票 prepare_workspace 的 gc 兜底）。放在仓树
    # 清理之后：容器挂载面=泳道根，先清干净成员/根仓树的 git 注册再拆容器。
    # 拆除成功/本就无容器=正常路径不留 warn（teardown 的 warns 契约=只装异常面，
    # t260913-05 多仓 teardown 测试钉死空 warns）；只有真失败才留痕。
    _rm_note = agent_runtime.remove_container(args.ticket_id)
    if _rm_note and not _rm_note.startswith("已拆"):
        warns.append("agent 容器回收: %s" % _rm_note)
    return MergeResult(ok=True, action="teardown",
                       merge_commit="", error="；".join(warns))


# ---------- dev-lane: mechanizing the review-gate criteria (t260829-07; pure git/files, zero LLM) ----------

REVIEW_GATE_GIT_TO_SEC = 30   # per-command git fallback timeout


@activity.defn
async def verify_review_gate(args: ReviewGateArgs) -> ReviewGateResult:
    """Mechanical re-check after integration_review says ok (called inside dev_lane's
    REVIEW_GATE_PATCH_ID gate).

    Three-state error precision:
      - a git query failure → git_error non-empty and lane_commits=-1 (0 must never
        mean "couldn't ask", otherwise a git fault gets misreported as "the
        implementation never landed");
      - a screenshots path that exists but is broken (a file / unreadable) →
        shots_path_error non-empty and png_count=-1 (you may not claim "evidence
        missing"); a nonexistent path = nothing was shot, equivalent to 0 png;
      - a successful query → lane_commits / png_count carry real values, and dev_lane
        bounces based on them.
    This activity only returns data and makes no business judgement (the gate logic
    lives in the workflow, keeping the deterministic orchestration testable)."""
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

    shots_dir = ui_evidence_dir(wt)
    if shots_dir.exists() and not shots_dir.is_dir():
        res.shots_path_error = "%s 存在但不是目录" % shots_dir
        res.png_count = -1
    elif not shots_dir.is_dir():
        res.png_count = 0  # no directory = nothing was shot, equivalent to 0 png (safe to claim missing)
    else:
        try:
            res.png_count = len([p for p in shots_dir.iterdir()
                                 if p.is_file() and p.suffix.lower() == ".png"])
        except OSError as e:
            res.shots_path_error = "%s 不可读：%s: %s" % (shots_dir, type(e).__name__, e)
            res.png_count = -1
    return res


# ---------- dev-lane: UI screenshot evidence (t260828-09; the worker runs capture.mjs) ----------

# Subprocess timeout (seconds): capture.mjs has its own finer-grained page timeouts;
# this value is the hard cap on the whole screenshot flow.
# Mind the relationship with the workflow side's activity timeout: the activity's
# start_to_close must be **clearly larger** than this value
# (dev_lane.UI_EVIDENCE_TO=180s vs 120s), otherwise Temporal kills the activity first
# and the subprocess-timeout cleanup path below is never reached (no timeout stacking
# on timeout).
UI_CAPTURE_TIMEOUT_SEC = 120


def _shot_lines(shots_dir: Path, names: List[str]) -> List[str]:
    """A 「name (mtime iso)」 list — computed here in the activity and carried back
    (the workflow side does zero IO and cannot touch the disk)."""
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
    """截图归档到主树 <REPO_ROOT>/.sandbar/evidence/<ticket_id>/（老主树粘滞 .suyou/evidence）（t260829-02）。  # naming-compat

    After the lane merges the worktree is torn down, and this archive is what keeps
    the `![](…/tickets/<id>/evidence/<file>)` image references in the report from
    becoming dead links (the host's read-only endpoint reads the main-tree archive,
    falling back to the lane while it still exists). An archive failure **neither
    raises nor flips ok** — the soft-failure semantics match capture's (the evidence
    gate still looks at the lane directory), and the returned plain-language note is
    appended to the detail by the caller for the record."""
    if not names:
        return ""
    # env override (self-tests point at a temp dir so the real main tree stays clean;
    # the node-side evidence endpoint shares the same env name, they reference each
    # other)
    base = evidence_base()
    dst = Path(base) / args.ticket_id
    try:
        dst.mkdir(parents=True, exist_ok=True)
        for n in names:
            shutil.copy2(shots_dir / n, dst / n)
        return "；已归档 %d 张到主树 %s" % (len(names), dst)
    except OSError as e:
        return "；归档失败（不拦主链）：%s: %s" % (type(e).__name__, e)


def _preserve_failed_shots(args: UiEvidenceArgs, shots_dir: Path) -> Tuple[List[str], List[str], str]:
    """Preserve a best-effort view when capture fails (ticket t260901-02): PNGs that
    were shot no longer vanish with the failure.

    All three stances are satisfied at once:
      - the mechanical gate review_gate_verdict counts the on-disk png in the lane's
        shots_dir (shared.py L1308, re-checked at merge_check) — images that archived
        **successfully** are unlinked out of the lane → png_count drops to 0 → the
        gate stays red, so a partial view cannot fool the gate (a soft failure never
        fakes a pass);
      - archiving into the main tree's .sandbar/evidence/<ticket>/ → readable from the
        drawer and safe from the worktree teardown;
      - **at file granularity**: an image whose archive failed **stays in the lane**
        (png_count>0 keeps the gate red, and the image can be rescued by hand —
        unlinking after a failed archive = the image evaporates entirely, which is
        exactly the disease this ticket cured).
    Returns (names archived and moved out successfully, names left in the lane because
    archiving failed, a plain-language note). Never raises."""
    try:
        pngs = sorted(p.name for p in shots_dir.glob("*.png")) if shots_dir.is_dir() else []
    except OSError:
        return [], [], "；尽力视图收集失败：screenshots 目录不可读"
    if not pngs:
        return [], [], ""
    moved: List[str] = []
    kept: List[str] = []
    try:
        base = evidence_base()
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
                kept.append(n)  # unlink failed: the image stays in the lane, the gate stays red instead of faking a pass
                continue
            moved.append(n)
        note = "；capture 失败，尽力视图 %d 张已归档主树并移出泳道（机械闸维持红灯）" % len(moved) if moved else ""
        if kept:
            note += "；归档/移出失败 %d 张留泳道（可人工捞回）：%s" % (len(kept), "、".join(kept))
        return moved, kept, note
    except OSError as e:
        # A directory-level archive failure: everything stays in the lane (gate red +
        # rescuable — the safe side)
        return [], pngs, "；尽力视图归档失败（留泳道）：%s: %s" % (type(e).__name__, e)


def _ui_capture_stub(args: UiEvidenceArgs, shots_dir: Path) -> UiEvidenceResult:
    """SANDBAR_UI_CAPTURE_STUB=1: write two fake pngs and return (no node/browser,
    zero dependencies).
    Modeled on SANDBAR_AGENT_STUB (the same precedent as _run_agent_stage_impl), for
    self-tests / dry runs."""
    shots_dir.mkdir(parents=True, exist_ok=True)
    names = []
    for name in ("console-default.png", "console-chat.png"):
        p = shots_dir / name
        # The smallest valid PNG (1x1 pixels), so glob("*.png") can hit it
        p.write_bytes(bytes.fromhex(
            "89504e470d0a1a0a0000000d4948445200000001000000010806000000"
            "1f15c4890000000a49444154789c63000100000500010d0a2db4"
            "0000000049454e44ae426082"))
        names.append(name)
    note = _archive_shots(args, shots_dir, names)
    return UiEvidenceResult(ok=True, shots=names, shot_lines=_shot_lines(shots_dir, names),
                            detail="[stub] SANDBAR_UI_CAPTURE_STUB=1，假截图两张（自测/干跑）" + note)


@activity.defn
async def ui_evidence_decl(args: UiEvidenceDeclArgs) -> UiEvidenceDeclResult:
    """Preload the ui_evidence declaration (t260904-18, KI-050 gate ③): read the
    ui_evidence declaration from the lane root's verify.yaml and return the three
    states (ok/absent/malformed) for the workflow to store in meta (the disk read
    happens in the activity while the workflow only reads meta = replay safe).
    Failures don't raise: unreadable = the absent state (the consumer falls back on
    the "declaration absent" stance — a declaration that fails to read is not the same
    as a project that never declared)."""
    wt = Path(args.worktree) if args.worktree else REPO_ROOT
    if not wt.is_absolute():
        wt = REPO_ROOT / wt
    lane_repo = _lane_repo_root(wt)
    mode, dirs, note = load_ui_evidence(wt)  # the declaration is read from the lane root (same stance as verify_lane)
    activity.logger.info("[%s] ui_evidence 声明：%s（%d 目录）%s",
                         args.ticket_id, mode, len(dirs), note)
    return UiEvidenceDeclResult(mode=mode, dirs=dirs, note=note)


@activity.defn
async def ui_changed_paths(args: UiChangedPathsArgs) -> UiChangedPathsResult:
    """UI-ticket detection switched to a diff source (KI-044 root fix, t260904-13):
    decide whether this is a UI ticket from the lane branch's **actually changed
    paths** — `git diff --name-only <merge-base>...branch` × UI_WRITE_PREFIXES — and
    return the UI paths that hit. The user's ruling stance (260904): the ui_evidence
    stage calls once to decide "shoot or not", and merge_check 3.6 computes again to
    decide "is evidence required" — both call sites share one source (_ui_diff_paths,
    with match_ui_paths as the only predicate entry), and a diff change between the
    two points in time is caught by 3.6's fail-closed backstop.

    The baseline uses _merge_base_ref (the real thing, reused, so all its failure
    behavior comes along automatically: rc≠0 fail-closed / multi-line malformed keeps
    the first line with a trace / empty output = failure / never falls back to a
    literal main — the t260901-18/t260903-11 family anchors).
    Fail-closed: a failure of merge-base or diff → empty ui_paths + an error in the
    detail, and the caller treats it as "UI ticket, evidence pending" (shoot, gate as
    backstop), never a silent SKIP.
    The subprocess follows the _git/_diff_stat family as-is: a synchronous run + a
    bounded timeout (a timeout raise is handled by Temporal's retry semantics);
    cancellation immediacy is the family's existing debt and is not widened by this
    ticket."""
    wt = Path(args.worktree) if args.worktree else REPO_ROOT
    if not wt.is_absolute():
        wt = REPO_ROOT / wt
    lane_repo = _lane_repo_root(wt)
    # The judgement stance = the project declaration (the lane root's verify.yaml
    # ui_evidence.dirs, ticket t260904-18 gate ③).
    # malformed → fail-closed (empty ui_paths + an error in the detail; the caller
    # treats it as "UI ticket, evidence pending");
    # absent → an empty stance (no diff can hit = not a UI ticket, don't shoot — a
    # project without a declaration has no screenshot gate, and the detail leaves a
    # visible trace).
    decl_mode, decl_dirs, decl_note = load_ui_evidence(wt)  # the declaration is read from the lane root (same stance as above)
    if decl_mode == "malformed":
        detail = "ui_changed_paths fail-closed：ui_evidence 声明畸形：%s" % decl_note
        activity.logger.info("[%s] %s", args.ticket_id, detail)
        return UiChangedPathsResult(ui_paths=[], detail=detail)
    decl_suffix = "" if decl_mode == "ok" else "；ui_evidence 未声明（截图闸按项目声明缺席）"
    # Ticket B (t260907-06): a single repo = the old single-anchor path (unchanged
    # behavior); multi-repo = diff per tree and re-add the repo prefix onto hit paths
    # to make them project-root-relative before unioning (anchored to the same
    # baseline as the declared dirs; match_ui_paths stays the single point).
    # A diff/baseline failure on any tree → fail-closed empty (the caller treats it
    # as "UI ticket, evidence pending", the same family semantics).
    scopes = _lane_scopes(wt, args.branch, base_ref="", write_set=None)
    ui_paths: List[str] = []
    for sc in scopes:
        wl_base, wl_err = _merge_base_ref(sc["branch"], sc["repo"])
        if not wl_base:
            detail = "ui_changed_paths fail-closed：merge-base 解析失败（%s）：%s" % (
                sc["name"] or "lane", wl_err)
            activity.logger.info("[%s] %s", args.ticket_id, detail)
            return UiChangedPathsResult(ui_paths=[], detail=detail)
        sc_dirs = _scope_dirs(decl_dirs, sc)
        sc_paths, diff_err = _ui_diff_paths(sc["repo"], wl_base, sc["branch"], sc_dirs)
        if diff_err:
            detail = "ui_changed_paths fail-closed：%s" % diff_err
            activity.logger.info("[%s] %s", args.ticket_id, detail)
            return UiChangedPathsResult(ui_paths=[], detail=detail)
        for pth in sc_paths:
            prefixed = ("%s/%s" % (sc["repo_rel"], pth)) if sc["repo_rel"] else pth
            if prefixed not in ui_paths:
                ui_paths.append(prefixed)
    lane_repo = scopes[0]["repo"]
    detail = ("按 diff 判定（merge-base %s...%s，锚泳道仓 %s，口径=%d 声明目录）：命中 %d 个 UI 路径%s%s"
              % (wl_base[:7], args.branch, lane_repo.name, len(decl_dirs), len(ui_paths),
                 ("：%s" % "、".join(ui_paths[:8])) if ui_paths else "（非 UI 票）",
                 decl_suffix))
    activity.logger.info("[%s] %s", args.ticket_id, detail)
    return UiChangedPathsResult(ui_paths=ui_paths, detail=detail)


@activity.defn
async def prepare_ui_evidence(args: UiEvidenceArgs) -> UiEvidenceResult:
    """UI 票截图证据（t260828-09）：worker（无沙箱）代跑 ui-check/capture.mjs，
    截控制台默认页 + chat 态两张图落 <worktree>/.sandbar/screenshots/（老泳道 .suyou 粘滞）。  # naming-compat

    Read-only red line: capture.mjs only GETs the console page open and does
    navigation clicks — it never submits a form, never files a ticket, never touches
    any port; env SANDBAR_CONSOLE_URL points at the environment under test (default
    3099, test environment 3199).

    Failure **does not raise**: a missing dependency / no browser found / timeout /
    nonzero exit all return ok=False; the blocking semantics belong to merge_check's
    evidence gate (a UI ticket with no png → red light), and this step never blocks
    the main chain.

    Subprocess terminal-state handling (mirroring the agent spawn path
    _run_agent_stage_impl):
      normal exit → read the receipt; nonzero exit → ok=False receipt; timeout → kill
      + ok=False; activity cancellation (asyncio.CancelledError) → kill + re-raise
      (Temporal semantics); the finally block terminate/kill anything still alive so
      no orphan browser/node process is left behind."""
    wt = Path(args.worktree) if args.worktree else REPO_ROOT
    if not wt.is_absolute():
        wt = REPO_ROOT / wt
    shots_dir = Path(args.screenshots_dir) if args.screenshots_dir else ui_evidence_dir(wt)

    if os.environ.get("SANDBAR_UI_CAPTURE_STUB") == "1":
        res = _ui_capture_stub(args, shots_dir)
        activity.logger.info("[%s] ui_evidence stub：%s", args.ticket_id, res.detail)
        return res

    # Ticket t260829-02: capture always runs from the **main tree** (the playwright-core
    # node_modules are installed only in the main tree; a lane checkout doesn't have
    # them and doesn't install them — running inside the lane soft-failed outright in
    # ticket t260829-01). The --out directory and the cwd stay the lane (the review /
    # merge_check evidence-gate stance is unchanged).
    # Ticket t260829-07: prefer the capture-lane.mjs one-shot isolated bench (it picks
    # a port / boots / tears down by itself, with no dependency on an external
    # console); a missing script or a failure soft-degrades back to running
    # capture.mjs directly (old environments keep working), and the degradation is
    # written into the detail rather than kept silent (bootstrapping: before this
    # ticket's merge the old logic's soft failure was the norm and a human could patch
    # by hand).
    ui_check_dir = REPO_ROOT / "server" / "ui-check"
    lane_script = ui_check_dir / "capture-lane.mjs"
    script = REPO_ROOT / "server" / "ui-check" / "capture.mjs"
    if not script.is_file():
        return UiEvidenceResult(ok=False, detail="capture.mjs 不存在（主树）：%s" % script)
    env = dict(os.environ)
    env.setdefault("SANDBAR_CONSOLE_URL", "http://127.0.0.1:3099")
    candidates = []
    if lane_script.is_file():
        candidates.append((["node", str(lane_script), "--lane", str(wt),
                            "--out", str(shots_dir)], "capture-lane（隔离台）"))
    candidates.append((["node", str(script), "--url", env["SANDBAR_CONSOLE_URL"],
                        "--out", str(shots_dir)], "capture.mjs（直连 %s）" % env["SANDBAR_CONSOLE_URL"]))
    detail_tail = ""
    detail_parts: List[str] = []   # ticket t260831-02: accumulate per candidate instead of overwriting each other
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
                raise  # activity cancelled: clean up, then re-raise per Temporal semantics
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
                # Transitional mirror for the plugin face (retirement debt #5): the
                # plugin / old-chain read side still looks at .sandbar/screenshots.
                for _n in pngs:
                    try:
                        mirror_to_legacy(wt, Path("screenshots") / _n)
                    except Exception:  # noqa: BLE001  best-effort
                        pass
                note = _archive_shots(args, shots_dir, pngs)
                return UiEvidenceResult(ok=True, shots=pngs, shot_lines=_shot_lines(shots_dir, pngs),
                                        detail="%s：截图 %d 张：%s%s" % (label, len(pngs), "、".join(pngs), note))
            detail_tail = run_fail
        except Exception as e:  # infrastructure fault (node missing / permissions / …): the receipt doesn't raise, the gate goes red
            detail_tail = "%s 启动失败：%s: %s" % (label, type(e).__name__, e)
        finally:
            if proc is not None and proc.returncode is None:
                proc.terminate()  # backstop: no path that missed reaping leaves an orphan process
                try:
                    await asyncio.wait_for(proc.wait(), timeout=10)
                except asyncio.TimeoutError:
                    proc.kill()
        detail_parts.append("%s → %s" % (label, detail_tail))
        if i + 1 < len(candidates):
            activity.logger.info("[%s] ui_evidence %s 失败，降级下一候选：%s",
                                 args.ticket_id, label, detail_tail[:200])
    # Best-effort view preservation (ticket t260901-02): after every candidate fails,
    # PNGs already shot are archived to the main tree and the successfully archived
    # ones are moved out of the lane (png_count drops to 0 so the gate stays red);
    # images whose archive failed stay in the lane where a human can rescue them.
    moved, _kept, keep_note = _preserve_failed_shots(args, shots_dir)
    return UiEvidenceResult(ok=False, shots=moved, shot_lines=_shot_lines(shots_dir, moved),
                            detail="；".join(detail_parts) + keep_note)


# Worker registration list: one activity per stage name + human-gate preparation +
# workspace preparation (M16's first activity)
# + dev-lane's merge_check/merge (260824: the programmatic pre-merge checks and the
# real merge after human sign-off)
# + the two conflict-resolution activities (t260826-01: the worker runs the merge and
# leaves the state / settles the merge commit)
# + UI screenshot evidence (t260828-09: the worker runs capture.mjs; only UI tickets
# invoke it from the workflow)
AGENT_STAGE_ACTIVITIES = [_make_stage_activity(s) for s in AGENT_STAGE_IDS]

# ---- Integration-test machinery (follow-on to t260829-07): the mechanical test step / unified settling / arbitration / acceptance walkthrough ----

@activity.defn
async def settle_lane(args: SettleLaneArgs) -> SettleLaneResult:
    """Unified worker-side settle at the join point (during the parallel fork both
    implement and design run with skip_settle; this settles once here): the
    implementation changes and the test set (integration/) land in one commit on the
    lane branch. Idempotent: a clean workspace is a no-op.

    Fix ① (ticket t260901-16): worktree-relative paths are anchored at REPO_ROOT (the
    same stance as verify_review_gate / run_integration_tests) — they used to be
    resolved against the worker process's cwd, which never matched a registered
    worktree in _is_worktree_of.
    Fix ② (ticket t260901-16): on a mismatch, silently falling back to the main tree is
    forbidden — falling back = "the lane that had something to settle did nothing and
    still reported clean" (the main tree is clean to begin with → a no-op fake green,
    and every artifact of a parallel-fork ticket leaked without landing; proven in the
    field), which is worse than an error. It now raises, leaving Temporal to retry and
    the failure visible upstream."""
    wt = Path(args.worktree) if args.worktree else REPO_ROOT
    if not wt.is_absolute():
        wt = REPO_ROOT / wt
    # Ticket B (t260907-06): a single repo = 1 scope (unchanged behavior); multi-repo =
    # verify ownership per tree and settle per tree. Every tree refuses to fall back to
    # the main tree (a silent fallback = the lane with something to settle lands
    # nothing and reports clean; proven in t260901-16).
    scopes = _lane_scopes(wt, base_ref=str(args.base_ref or ""),
                          write_set=list(args.write_set or []))
    notes: List[str] = []
    commits = -1
    for sc in scopes:
        if not _is_worktree_of(sc["tree"], sc["repo"]):
            raise RuntimeError(
                "settle_lane: worktree %r（解析为 %s）不是其归属仓（%s）的已注册 worktree，"
                "拒绝回退主树代落盘（静默回退=该落盘的泳道什么都不落还报干净，t260901-16 实锤）"
                % (args.worktree, sc["tree"], sc["repo"]))
        sc_note = _settle_worktree_lane(sc["tree"], args.ticket_id, args.stage_id,
                                        args.gen, repo=sc["repo"],
                                        write_set=list(sc.get("write_set") or []),
                                        path_gate=bool(args.path_gate),
                                        base_ref=str(sc.get("base_ref") or args.base_ref or ""),
                                        authorizations=list(getattr(args, "authorizations", None) or []))
        # t260911-03：闸拒绝随 error 上抛给 workflow（join 点点名段/文件转 blocked，
        # 不静默吞成一条 note——否则违规改动不落盘、0-commit 预检只会给一句含糊红）。
        if path_gates.is_gate_refusal(sc_note):
            return SettleLaneResult(note=sc_note, error=sc_note, lane_commits=commits)
        if sc["name"]:
            sc_note = "[%s] %s" % (sc["name"], sc_note or "settle 返回空")
        notes.append(sc_note)
        rc = _git(["rev-list", "--count", "HEAD"], sc["tree"])
        sc_commits = int(rc.stdout.strip() or -1) if rc.returncode == 0 else -1
        commits = sc_commits if commits < 0 else min(commits, sc_commits)
    return SettleLaneResult(note="\n".join(n for n in notes if n), lane_commits=commits)


# t260913-01 仲裁修（测试道预算对）：本值 +300s 守卫必须**严格小于** dev_lane.INTEG_RUN_TO
# （该 activity 的 start_to_close_timeout，现行 60min）——否则本函数 :3710 的结构化超时
# 回报是死代码：套件只会被 Temporal 硬杀成「Activity task timed out（ran=0，无归因）」，
# 且 RETRY(maximum_attempts=3) 会把每次硬杀再重试 3 轮（每轮 60min 白烧）。
# 原默认 5400s（=95min 守卫）恒晚于 60min 外层 ⇒ 实测（260913）连续两轮 0 跑无归因。
# 3000s（+300=55min）给正常 ~25min 套件 2× 余量，超限则走结构化回报。运维可用
# SANDBAR_INTEG_BATCH_TIMEOUT_SEC 覆盖，但覆盖时须同步抬高 dev_lane.INTEG_RUN_TO。
BATCH_TIMEOUT_SEC = int(os.environ.get("SANDBAR_INTEG_BATCH_TIMEOUT_SEC") or 3000)


async def _run_scenarios(wt: Path, ticket_id: str, write_set=None,
                         apply_skip_pools: bool = False) -> IntegrationRunResult:
    """A thin shell (thinned by host order t260902): declaration reading, command
    execution and contract parsing all live in verify_lane lane=integ (one
    implementation + one parser); this function only places the order and translates
    the tool's JSON into an IntegrationRunResult (the field stance is unchanged:
    ran/passed/failed/details[{name,cmd,exit,output_tail}], invisible to arbitrate)."""
    # The lane's own toolchain copy wins (ticket t260904-18): the integ lane treats
    # **the lane as the thing under test**, so loading the lane's declaration must use
    # the lane's own toolchain — when the worker-side (main tree) copy lags behind the
    # lane (the normal state before a declaration-first ticket merges), the main
    # tree's verify_lane whitelist does not recognize the lane's new top-level keys →
    # the whole lane fails closed with ran=0. The same principle as merge_check's
    # verify item (:1723 prefers the lane copy, falling back to the worker copy only
    # cross-project without an engine layout) — the integ shell had missed that
    # precedent, which meant the two mechanical gates behaved differently.
    lane_admin = wt / "server" / "admin.py"
    admin = str(lane_admin if lane_admin.is_file() else
                Path(__file__).resolve().parents[1] / "admin.py")
    # A real near-miss from t260903-09: blocking subprocess.run is forbidden inside an
    # async activity — it once froze the worker's event loop for the entire scenario
    # duration and every query timed out at 8s (diagnostic note
    # notes/diag-query-starvation.md).
    # Fully async: create_subprocess + wait_for; on timeout, kill first, then report.
    p = await asyncio.create_subprocess_exec(
        "python3", admin, "call", "verify_lane",
        # t260913-03：载荷面薄壳只下单——是否按泳道声明排除池由调用方（每票段）显式
        # 置位，本层只透传；缺省 False=巡检/老回放形态恒全跑（验收 E 机械锁）
        json.dumps(shared.integ_verify_payload(wt, write_set, apply_skip_pools)),
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
    out.env_fail = int(res.get("env_fail") or 0)   # the may-be-absent reading keeps the old gate compatible
    out.details = [{"name": s.get("name", ""), "cmd": "", "exit": int(s.get("exit") or 0),
                    "output_tail": s.get("output_tail") or ""}
                   for s in (res.get("scenarios") or [])]
    # ---- t260913-03 池排除回执面：applied（跳过面点名）与旧口径命中面留痕两态
    # 都进 details——红线「少跑必须点名」；宿主管 260914 起例外腿已撤除，
    # former_force_assets 只作迁移期可见性（说明这些资产在旧口径下会触发全跑）----
    _pe = res.get("pool_exclude") or {}
    out.excluded_pools = [str(x) for x in (_pe.get("excluded_pools") or [])]
    out.excluded_count = int(_pe.get("excluded_count") or 0)
    out.forced_by = [str(x) for x in (_pe.get("former_force_assets") or [])]
    if _pe.get("applied"):
        _tail = "本轮跳过池=%s（少 %d 条）" % (
            "、".join(str(x) for x in (_pe.get("declared") or out.excluded_pools)),
            out.excluded_count)
        if out.forced_by:
            _tail += "｜旧口径命中面（已撤除，不再据此全跑）%d 项" % len(out.forced_by)
        out.details.append({"name": "__pool_exclude__", "cmd": "", "exit": 0,
                            "output_tail": _tail})
    else:
        out.details.append({"name": "__pool_exclude__", "cmd": "", "exit": 0,
                            "output_tail": "本轮跳过池=%s（少 %d 条）"
                                           % ("、".join(str(x) for x in
                                                       (_pe.get("declared") or [])),
                                              out.excluded_count)})
    # ---- t260910-13 失败分类协议：闸机械归属判定接线 ----
    # 闸决策表 verdict=block 的用例（真回归/本票造成的 not-checked/协议违约）
    # 机械计入 failed（被改判的 not-checked 从 env_fail 挪走）——「拦」不是文字
    # 建议，是计数的机械面；归属结论与基线 ref 随回执上送仲裁。
    aff = res.get("affiliation") or {}
    out.blockers = [str(b) for b in (aff.get("blockers") or [])]
    out.affiliation_confidence = str(aff.get("affiliation_confidence") or "")
    out.baseline_ref = str(res.get("baseline_ref") or "")
    if out.blockers:
        case_status = {c.get("name"): c.get("status")
                       for c in (aff.get("cases") or [])}
        out.failed, out.env_fail = failure_protocol.apply_gate_blockers(
            out.failed, out.env_fail, case_status, out.blockers)
        out.details.append({
            "name": "__gate_blockers__", "cmd": "", "exit": 1,
            "output_tail": "闸拦（t260910-13 决策表）：%s ｜ 归属置信=%s ｜ 基线=%s"
                           % (", ".join(out.blockers),
                              out.affiliation_confidence or "n/a",
                              out.baseline_ref or "n/a")})
    activity.logger.info("[%s] 归属判定：confidence=%s blockers=%s baseline=%s",
                         ticket_id, out.affiliation_confidence or "n/a",
                         out.blockers or "无", out.baseline_ref or "n/a")
    activity.logger.info("[%s] 场景汇总：ran=%s pass=%s fail=%s env_fail=%s",
                         ticket_id, out.ran, out.passed, out.failed, out.env_fail)
    return out


@activity.defn
async def run_integration_tests(args: IntegrationRunArgs) -> IntegrationRunResult:
    """Mechanical integration-test step (follow-on to t260829-07): runs the project's
    declared scenario executor (integration/run_scenarios.py), pure subprocess with
    zero LLM. The result goes to arbitrate (integration) for its three-state verdict —
    right and wrong are not judged here."""
    wt = Path(args.worktree) if args.worktree else REPO_ROOT
    if not wt.is_absolute():
        wt = REPO_ROOT / wt
    # t260913-03：每票段是全仓唯一显式打开「按声明排除池」的调用点——宿主管 260914
    # 口径为「声明即跳过」（例外腿已撤除），write_set 只余旧口径命中面留痕用途。
    # 策略值只透传，activity 不回填策略。
    return await _run_scenarios(wt, args.ticket_id,
                                write_set=list(getattr(args, "write_set", None) or []),
                                apply_skip_pools=bool(getattr(args, "apply_skip_pools", False)))


def _stub_stage_shortcut(args: AgentStageArgs, settle_on_cache: bool = False) -> Optional[StageResult]:
    """Stub/cache short-circuit for the integration-specific stages (filling the gap in
    arbitrate/acceptance_walkthrough).

    The generic agent stage has two pre-checks in _run_agent_stage_impl: an idempotent
    return when the result file exists + with SANDBAR_AGENT_STUB=1 it writes its own
    stub result and returns (the contract promised in the module header comment: "in
    stub mode the activity writes its own result file and returns, no agent process").
    These two integration-specific stages bypassed the generic implementation —
    measured on 260909 with a stub worker, the acceptance walkthrough stage still
    really launched capture-lane plus a real agent process, an external rework signal
    was only consumed by the workflow once the current activity finished, and one
    scenario dragged out ~590s of pointless waiting. This adds the same short-circuit:
    - result file present = idempotent return (the path consuming a scene's preset
      verdict is unchanged; settle_on_cache is decided by the caller per this stage's
      semantics — arbitrate must settle when not in the parallel fork);
    - stub mode with no file = write our own stub result and return — the summary never
      carries a verdict= marker, matching the generic stub (so scene D's
      arbitration-format round-cap trigger semantics do not drift).
    """
    rfile = Path(args.result_file)
    if rfile.is_file():
        cached = _read_result(rfile)
        if cached is not None:
            activity.logger.info("[%s/%s] 结果文件已存在，幂等返回（gen%d）",
                                 args.ticket_id, args.stage_id, args.gen)
            _patch_result_prompt(rfile, args.prompt)
            if settle_on_cache:
                note = _settle_with_gate(
                    args, _ws_cwd(args.workspace, args.ticket_id))
                _apply_settle_note(cached, note)
            return cached
    if os.environ.get("SANDBAR_AGENT_STUB") != "1":
        return None
    stub = StageResult(
        status="ok",
        summary="[stub] %s 段完成（SANDBAR_AGENT_STUB=1，第 %d 次进段）"
                % (args.stage_id, args.gen),
        report="[stub] 做了什么：无（stub 演示）\n\n怎么验证的：无",
        deliverables=[], files_changed=[], files_changed_shape="ok",
        evidence="stub evidence: prompt %d 字" % len(args.prompt))
    rfile.write_text(json.dumps({
        "status": stub.status, "summary": stub.summary, "report": stub.report,
        "deliverables": stub.deliverables, "files_changed": stub.files_changed,
        "evidence": stub.evidence, "prompt": args.prompt,
    }, ensure_ascii=False, indent=1) + "\n", "utf-8")
    activity.heartbeat("stub done")
    return stub


@activity.defn
async def arbitrate(args: AgentStageArgs) -> StageResult:
    """The arbitration step (follow-on to t260829-07): integration reads the mechanical
    test results and issues a three-state verdict — pass / tests-fault (iterate the
    test set itself, the changes landing with this step's settle) / code-fault (the
    integration test report goes into report, bounce back to implement). The prompt is
    assembled by the workflow (including the mechanical test result JSON), and the
    spawn reuses the integration session (continuous context).
    Verdict encoding contract: the first ``verdict=<value>`` marker in the summary
    (stated explicitly in FLOW_BRIEF)."""
    rfile = Path(args.result_file)
    rfile.parent.mkdir(parents=True, exist_ok=True)
    # Stub/cache short-circuit (260909: the same two pre-checks as the generic stage,
    # now added — with a stub worker this stage used to really launch an agent process,
    # an external signal waited for the activity to finish before the workflow consumed
    # it, and one scenario dragged out ~10 minutes of pointless waiting).
    hit = _stub_stage_shortcut(args, settle_on_cache=not args.skip_settle)
    if hit is not None:
        return hit
    cwd = _ws_cwd(args.workspace, args.ticket_id)
    project = await _fetch_ticket_project(args.ticket_id)
    cmd, env = _prepare_agent_spawn(
        cwd, args.role, "", args.ticket_id, rfile.parent,
        "arbitrate_gen%d" % args.gen, project=project)
    cmd.append(args.prompt)
    logf = open(args.log_file, "a", buffering=1) if args.log_file else subprocess.DEVNULL
    activity.logger.info("[%s/arbitrate] spawn integration 仲裁（gen%d，cwd=%s）",
                         args.ticket_id, args.gen, str(cwd))
    proc = agent_runtime.spawn_agent(
        cmd, cwd=cwd, env=env, logf=logf, ticket_id=args.ticket_id,
        stage_tag="arbitrate_gen%d" % args.gen, project=project,
        workspace_kind=_ws_kind_of(args.workspace), lane=cwd,
        log=activity.logger.info)  # KI-009：host 形态内部仍 start_new_session（独立进程组）
    polls = 0
    try:
        while True:
            if rfile.is_file():
                res = _read_result(rfile)
                if res is not None:
                    _patch_result_prompt(rfile, args.prompt)
                    # KI-009: reap before settling — collect the late-written files
                    # cleanly before landing them (the source of the race window)
                    proc.reap(args.ticket_id, "arbitrate")
                    # In the tests-fault case the test-set iteration lands with this
                    # step's settle (committed code assets).
                    # Ticket t260903-02: during the parallel fork skip_settle=True skips
                    # it (so the walkthrough edge's half-finished work is not settled
                    # along with it); the unified settle is handled by the workflow's
                    # single settle_lane.
                    if not args.skip_settle:
                        note = _settle_with_gate(args, cwd)
                        _apply_settle_note(res, note)
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
        # KI-009: the backstop reap is upgraded to group granularity (the old
        # terminate+wait+kill only reaped the direct child)
        proc.reap(args.ticket_id, "arbitrate")


# ---- doc-lifecycle ticket ② (t260905-01): the two close-out questions — a sedimentation trigger plus a reverse-sync gate ----
# Light-path carrier: the result file gains doc_sediment / doc_conflicts fields
# (_read_result's existing behavior of dropping unknown keys is untouched), and three
# pure functions read → validate → register → assemble back into StageResult's
# existing six fields, with zero workflow changes. Discipline: answering or not never
# blocks (res.status is never changed; an unanswered question is still a record);
# failed rounds are assembled and registered too (a docs contradiction found in a
# bounce round is just as real a debt entry, and cross-round duplicates are stopped by
# the registration dedup key). Debt-promotion discipline: before human sign-off the
# merge executor promotes the entries into notes/debts/known-issues.md or the docs
# debt ledger — the receipt section's closing sentence carries that instruction to the
# human reviewer (.sandbar/ is destroyed by teardown_lane, so the receipt must carry
# the entries themselves in full, not just paths).

DOC_GATE_DIRNAME = ".sandbar/doc-gate"  # new-lane default; the sticky form is resolved where it is used (see lane_dot_path)
PENDING_DOC_SYNC_NAME = "pending-doc-sync.jsonl"
DOC_GATE_TRANSFER_NOTE = (
    "债条目转正：人审签字前，由 merge 执行人将上述条目登记进 "
    "notes/debts/known-issues.md（或 docs 债册）；未转正不得视为已闭环。")


def parse_doc_gate(raw: Any) -> Dict[str, Any]:
    """The result file's raw dict → a judgement on both questions (zero IO, fully
    tolerant; malformed = record and degrade, never raise).

    Returned keys (absent is tracked per question so the receipt can record each
    question's answered/unanswered separately):
      sediment            = {want: bool, target: str, reason: str} or None (unanswered /
                            malformed)
      sediment_absent     = bool (the key was not present)
      sediment_malformed  = str (why it was malformed; empty when fine)
      conflicts / conflicts_absent / conflicts_malformed follow the same shape;
      conflicts           = [{doc, claim, actual}] (only entries with all three fields)
    """
    out: Dict[str, Any] = {
        "sediment": None, "sediment_absent": True, "sediment_malformed": "",
        "conflicts": [], "conflicts_absent": True, "conflicts_malformed": "",
    }
    if not isinstance(raw, dict):
        return out
    # ① The sedimentation question
    if "doc_sediment" in raw:
        out["sediment_absent"] = False
        s = raw["doc_sediment"]
        if not isinstance(s, dict):
            out["sediment_malformed"] = "doc_sediment 不是对象（%s）" % type(s).__name__
        elif not isinstance(s.get("want"), bool):
            out["sediment_malformed"] = "doc_sediment.want 缺失或非布尔"
        else:
            out["sediment"] = {
                "want": s["want"],
                "target": str(s.get("target") or "")[:300],
                "reason": str(s.get("reason") or "")[:600],
            }
    # ② The reverse-sync gate
    if "doc_conflicts" in raw:
        out["conflicts_absent"] = False
        c = raw["doc_conflicts"]
        if not isinstance(c, list):
            out["conflicts_malformed"] = "doc_conflicts 不是列表（%s）" % type(c).__name__
        else:
            bad = []
            for item in c[:50]:  # length capping: the list stops at 50 entries, guarding against a malformed giant table
                if not isinstance(item, dict):
                    bad.append("非对象条目")
                    continue
                doc, claim, actual = item.get("doc"), item.get("claim"), item.get("actual")
                if not (isinstance(doc, str) and doc.strip()
                        and isinstance(claim, str) and claim.strip()
                        and isinstance(actual, str) and actual.strip()):
                    bad.append("缺 doc/claim/actual 或非非空字符串")
                    continue
                out["conflicts"].append({
                    "doc": doc.strip()[:300],
                    "claim": claim.strip()[:600],
                    "actual": actual.strip()[:600],
                })
            if len(c) > 50:
                bad.append("超过 50 条已截断")
            if bad:
                out["conflicts_malformed"] = "%d 条畸形（%s）" % (len(bad), "; ".join(bad[:3]))
    return out


def register_pending_doc_sync(cwd: Path, ticket_id: str,
                              conflicts: List[Dict[str, str]]) -> Dict[str, Any]:
    """Register contradiction entries into the lane's debt ledger
    pending-doc-sync.jsonl (append-only, path injectable).

    Idempotent: the dedup key = ticket+doc+claim+actual (the key includes actual — an
    evolved actual = a new entry, latest-wins with old entries never deleted, which is
    audit friendly); the dedup scan tolerates pre-existing malformed lines (a torn
    write skips the line instead of raising). A write failure degrades to
    registered=0 + error without raising (it never blocks the acceptance close-out)."""
    info: Dict[str, Any] = {"registered": 0, "path": "", "error": ""}
    if not conflicts:
        return info
    # Sticky resolution (t260907-04): create=True actually creates the directory, so it
    # must sit inside the try (a mkdir under a read-only base raises PermissionError,
    # and the degradation contract "a write failure returns an error without raising"
    # has to cover the whole path surface).
    try:
        gate_dir = lane_dot_path(cwd, "doc-gate", create=True)
    except OSError as e:
        info["error"] = "doc-gate 目录解析/创建失败（降级不抛）：%s: %s" % (type(e).__name__, e)
        return info
    f = gate_dir / PENDING_DOC_SYNC_NAME
    info["path"] = str(f)
    try:
        seen = set()
        if f.is_file():
            for line in f.read_text("utf-8", errors="replace").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except Exception:
                    continue  # a torn-write malformed line: skip, don't raise
                if isinstance(row, dict):
                    seen.add((str(row.get("ticket") or ""), str(row.get("doc") or ""),
                              str(row.get("claim") or ""), str(row.get("actual") or "")))
        gate_dir.mkdir(parents=True, exist_ok=True)
        new_rows = []
        for c in conflicts:
            key = (ticket_id, c["doc"], c["claim"], c["actual"])
            if key in seen:
                continue
            seen.add(key)
            new_rows.append(json.dumps({
                "ticket": ticket_id, "doc": c["doc"], "claim": c["claim"],
                "actual": c["actual"], "registered_at": int(time.time()),
            }, ensure_ascii=False))
        if new_rows:
            with open(f, "a", encoding="utf-8") as fh:
                fh.write("\n".join(new_rows) + "\n")
        info["registered"] = len(new_rows)
    except OSError as e:
        info["error"] = str(e)[:200]
    return info


def _doc_gate_report_section(pg: Dict[str, Any], reg: Dict[str, Any]) -> str:
    """Both questions' judgement + registration result → the receipt's「close-out two
    questions」markdown section (human-readable, with the entries themselves in
    full)."""
    lines = ["## 收口两问（沉淀触发器+反向同步闸）"]
    # ① The sedimentation question (unanswered / malformed are both recorded — the
    # record shape behind acceptance ① "not answering doesn't block, with evidence")
    if pg["sediment"] is not None:
        s = pg["sediment"]
        if s["want"]:
            lines.append("- 沉淀一问：建议沉淀 → target=%s；理由=%s" % (s["target"], s["reason"]))
        else:
            lines.append("- 沉淀一问：显式无可沉淀（%s）" % (s["reason"] or "未给理由"))
    elif pg["sediment_malformed"]:
        lines.append("- 沉淀一问：未答（字段形态不合格按未答留痕：%s；不阻塞收口）"
                     % pg["sediment_malformed"])
    else:
        lines.append("- 沉淀一问：未答（留痕；不阻塞收口）")
    # ② The reverse-sync gate
    if pg["conflicts"]:
        lines.append("- 反向同步闸：发现 %d 条 docs 矛盾（条目本体如下）" % len(pg["conflicts"]))
        for i, c in enumerate(pg["conflicts"], 1):
            lines.append("  - 债条目 %d：doc=%s；被推翻主张=%s；实现现实=%s"
                         % (i, c["doc"], c["claim"], c["actual"]))
        if reg.get("registered"):
            lines.append("  - 已登记 %d 条（跨轮去重后）→ %s" % (reg["registered"], reg["path"]))
        elif reg.get("error"):
            lines.append("  - 债册登记失败（%s）——以上方条目本体为准，请人审手工登记"
                         % reg["error"])
    elif pg["conflicts_malformed"]:
        lines.append("- 反向同步闸：字段形态不合格按未答留痕（%s；不阻塞收口）"
                     % pg["conflicts_malformed"])
    elif pg["conflicts_absent"]:
        lines.append("- 反向同步闸：未答（留痕；不阻塞收口）")
    else:
        lines.append("- 反向同步闸：核对完成，未发现 docs 矛盾")
    if pg["conflicts"]:
        lines.append("- %s" % DOC_GATE_TRANSFER_NOTE)
    return "\n".join(lines)


def apply_doc_gate(res: StageResult, rfile: Path, cwd: Path, ticket_id: str) -> StageResult:
    """Read the result file's two-question fields → judge → register → assemble into
    res (a light-path receipt; status is never changed).

    Idempotent: when the activity's Temporal retry re-executes the whole block, res is
    a fresh _read_result product (the original report is not polluted by the previous
    assembly), and the registration dedup key stops cross-run duplicates. Defensive
    throughout: no exception from this function may ever block the acceptance
    close-out (the two questions are an accompanying increment, not an adjudication
    surface)."""
    try:
        try:
            raw = json.loads(Path(rfile).read_text("utf-8"))
        except Exception:
            raw = {}
        pg = parse_doc_gate(raw if isinstance(raw, dict) else {})
        reg = register_pending_doc_sync(cwd, ticket_id, pg["conflicts"])
        res.report = (res.report + "\n\n" + _doc_gate_report_section(pg, reg)).strip()
        ev = ("doc_gate: sediment=%s; conflicts=%s; registered=%d" % (
            "absent" if pg["sediment_absent"] else
            ("malformed(%s)" % pg["sediment_malformed"]) if pg["sediment"] is None else "ok",
            "absent" if pg["conflicts_absent"] else
            ("malformed(%s)" % pg["conflicts_malformed"]) if not pg["conflicts"] else
            "ok(%d)" % len(pg["conflicts"]),
            reg.get("registered") or 0))
        if reg.get("path") and (reg.get("registered") or pg["conflicts"]):
            ev += "; file=%s" % reg["path"]
        res.evidence = (res.evidence + "\n[doc-gate] " + ev).strip()
        if reg.get("registered") and reg.get("path") and reg["path"] not in res.deliverables:
            res.deliverables.append(reg["path"])
    except Exception as e:  # backstop: nothing unexpected may block the close-out, only leave a trace
        res.evidence = (res.evidence + "\n[doc-gate] 判读异常软降级：%s" % str(e)[:200]).strip()
    return res


@activity.defn
async def acceptance_walkthrough(args: AgentStageArgs) -> StageResult:
    """The acceptance walkthrough step (follow-on to t260829-07): once the tests pass,
    integration walks the new feature from the user's point of view and writes the
    acceptance report (for the human review gate to consult). The walkthrough evidence
    is produced up front by the worker — first the capture-lane isolated bench shoots
    for real (a lane build; screenshots land in .sandbar/screenshots/acceptance/), the
    output is injected into the prompt, and the agent judges the screenshots / DOM
    assertions to write the report (the StageResult contract: status=ok + report = the
    acceptance report / status=failed + report = code problems found by the
    walkthrough). The agent sandbox cannot run a browser (measured in tickets
    t260829-02/-06), so the browser always runs on the worker."""
    rfile = Path(args.result_file)
    rfile.parent.mkdir(parents=True, exist_ok=True)
    # Stub/cache short-circuit (260909: same as arbitrate — with a stub worker this
    # stage still really launched capture-lane plus a real agent, dragging one scenario
    # through ~590s/~85s of pointless waiting).
    hit = _stub_stage_shortcut(args)
    if hit is not None:
        return hit
    cwd = _ws_cwd(args.workspace, args.ticket_id)
    # Up front: the capture-lane isolated bench shoots for real (best-effort — a
    # failure injects an explanation and the agent judges as if there were no
    # screenshots)
    cap_out = lane_dot_path(cwd, "screenshots", "acceptance", create=True)
    cap_note = ""
    try:
        lane = str(args.worktree or cwd)
        cproc = await asyncio.create_subprocess_exec(  # the same t260903-09 trap, made async (a real browser shoot takes minutes)
            "node", str(REPO_ROOT / "server" / "ui-check" / "capture-lane.mjs"),
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
        # Ticket t260903-02: a ticket-stage-specific session key — a different session
        # from the concurrent arbitration edge, so two processes never write one
        # session file (trade-off record: the walkthrough session does not appear in
        # agent-live / agent-usage's ticket-role locator, and its content is still
        # reachable from the result file / logs).
        session_key="%s-acceptance" % args.ticket_id)
    cmd.append(args.prompt)
    logf = open(args.log_file, "a", buffering=1) if args.log_file else subprocess.DEVNULL
    activity.logger.info("[%s/acceptance_walkthrough] spawn integration 验收走查（gen%d）",
                         args.ticket_id, args.gen)
    proc = agent_runtime.spawn_agent(
        cmd, cwd=cwd, env=env, logf=logf, ticket_id=args.ticket_id,
        stage_tag="acceptance_gen%d" % args.gen, project=project,
        workspace_kind=_ws_kind_of(args.workspace), lane=cwd,
        log=activity.logger.info)  # KI-009：host 形态内部仍 start_new_session（独立进程组）
    polls = 0
    try:
        while True:
            if rfile.is_file():
                res = _read_result(rfile)
                if res is not None:
                    # doc-lifecycle ticket ②: judge both close-out questions + register +
                    # assemble into the receipt (both ok and failed rounds are assembled,
                    # since a contradiction found in a bounce round is just as real a debt
                    # entry; status is never changed — the close-out is not blocked)
                    apply_doc_gate(res, rfile, cwd, args.ticket_id)
                    _patch_result_prompt(rfile, args.prompt)
                    # KI-009: reap before returning — the walkthrough report is never
                    # booked (inside the .sandbar stance), but unexpected workspace dirt
                    # from a late write must not be left to race a live process at
                    # merge_check
                    proc.reap(args.ticket_id, "acceptance_walkthrough")
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
        # KI-009: the backstop reap is upgraded to group granularity (the old
        # terminate+wait+kill only reaped the direct child)
        proc.reap(args.ticket_id, "acceptance_walkthrough")



ALL_AGENT_ACTIVITIES = AGENT_STAGE_ACTIVITIES + [
    prepare_human_gate, prepare_workspace, merge_check, merge,
    prepare_conflict_resolution, settle_conflict_resolution,
    # M1-3 (t260902-02): the three-stage close-out — merge only books, archive_ticket
    # exports, teardown_lane tears the lane down.
    archive_ticket, teardown_lane,
    prepare_ui_evidence,
    verify_review_gate,
    # KI-044 root fix (t260904-13): UI-ticket detection switched to a diff source — the
    # ui_evidence stage computes once to decide "shoot or not", and merge_check 3.6
    # computes again to decide "is evidence required"; both come from the same
    # _ui_diff_paths. A missing registration = the worker doesn't recognize the
    # activity and it only surfaces at runtime; the selfcheck carries a registration
    # assertion (selfcheck_ui_acceptance section B).
    ui_changed_paths,
    # KI-050 declaration regime (t260904-18 gate ③): the ui_evidence declaration is
    # preloaded (when the lane starts it reads the lane root's verify.yaml into meta,
    # consumed by the review_gate patched branch). A missing registration, as above,
    # only surfaces at runtime.
    ui_evidence_decl,
    # Integration-test machinery (follow-on to t260829-07): settle_lane = the unified
    # settle at the join point; run_integration_tests = the mechanical test step (zero
    # LLM); arbitrate/acceptance_walkthrough are integration-specific agent steps (the
    # prompt is assembled by the workflow, with session reuse), not in AGENT_STAGE_IDS
    # (custom result judgement).
    settle_lane, run_integration_tests, arbitrate, acceptance_walkthrough,
]
