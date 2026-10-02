#!/usr/bin/env python3
"""inspection_scan_stage — stage 面巡检扫描器（t260915-18 工单②：容量可见性）。

------------------------------------------------------------------------
【退役留档（t260916-22，宿主令「不需要这个静态扫描，我们巡检要用 agent 来做」）】
本模块已从生产路径摘除：InspectionPeriodicWorkflow 新票走 inspect 段
（agent 审查，见 inspection_inspect.py / agent_activities.run_inspection_inspect）。
本文件保留一版只服务老在途票 replay（Temporal 重放历史里的 run_inspection_scan
调用必须仍能匹配）——新代码禁接线本模块；S1~S4 静态发现自此不再产出，274 条旧
发现整体作废不迁移（宿主裁定④）。deadman/suite 机械面不受影响。
------------------------------------------------------------------------

## 为什么要有这个面
台面泄漏（KI-077 当日 38 容器/1 租约/37 孤儿/最旧 45h）此前**没有任何周期性
可见面**——stage_docker 的保险丝只数租约不看容器，泄漏要到「起台起不来/端口
被占」才暴露，四张 UI 工单被 38h 旧台阻塞才发现。本面把 `stage_docker.py
inventory`（只读清点）接进巡检：孤儿容器、容量逼近/撞闸逐条开票，周频人工可读。

红线：巡检只产报告与开票建议，**绝不拆台**——回收动作只属于 stage_docker 的
sweep 与引擎所有者路径（inventory 子命令本身也只读）。docker 缺席=响亮「未
检查」条目（绝不静默当绿心跳）。

发现规则（severity 拍板）：
  S11 孤儿容器   orphans>0 → med（人审定责：哪条泳道/哪个形态漏的）
  S12 容量逼近   containers ≥ 0.8×SANDBAR_STAGE_MAX_STAGES → high（撞闸前清场）
  S13 容量撞闸   containers ≥ SANDBAR_STAGE_MAX_STAGES → high（起台必失败）
  S14 未检查     inventory 不可得（docker 缺席/回执畸形/超上限）→ med（响亮不假绿）

故障模式取舍（承 inspection_scan_doc.py 十三项，逐项「带过来/换形态」）：
  1. 仓根缺失 fail-closed ScanError          → 带过来（首行同判）。
  4. stdout 单行 JSON {ok, result|error}     → 带过来（CLI 契约同族）。
  5. 零发现 heartbeat=true                   → 带过来；S14 未检查≠零发现（不假绿）。
  6. 纯读零写入                              → 带过来（inventory 只读；本模块零写入）。
  9. 不确证不判 high 交人审                  → 换形态：S12/S13 是容量算术（非语义
     判断），撞闸=起台必失败的确定性事实，判 high 有据。
 10. 阈值/词法常量置顶、改必带用例           → 带过来（TIMEOUT_S/比率阈值置顶）。
 11. 确定性排序                              → 带过来（inspection_scan.summarize）。
 12. 稳定 finding_id 跨期 dedupe             → 带过来（subject=固定规则名+计数，
     计数进 evidence 不进 subject——id 跨期稳定）。
 13. meta 记录口径局限                       → 带过来（caveat：容器面≠租约面口径、
     out_of_domain 只列不判）。

CLI（ops 通道）：python3 inspection_scan_stage.py --repo-root <repo>
stdout：单行 JSON {ok, result|error}（契约同 inspection_scan.py 族）。
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))
from inspection_scan import Finding, ScanError, summarize  # noqa: E402

STAGE_CLI_REL = Path("integration") / "stage_docker.py"
INVENTORY_TIMEOUT_S = 10.0      # inventory 是两条 docker ps 量级（实测 <1s）；10s=上限
NEAR_FUSE_RATIO = 0.8           # S12 逼近闸阈值（×SANDBAR_STAGE_MAX_STAGES）


def _run_inventory(repo_root: Path, runner=None) -> Dict[str, Any]:
    """跑 inventory 子命令回回执 dict；任何失败=CheckedError 语义（不静默）。
    runner 注入面=UT 假回执（固定文件复现畸形输入，不靠真 docker）。"""
    cli = repo_root / STAGE_CLI_REL
    if not cli.is_file():
        raise FileNotFoundError("stage_docker CLI 不存在：%s" % cli)
    cmd = [sys.executable, str(cli), "inventory"]
    if runner is not None:
        rc, out, err = runner(cmd, INVENTORY_TIMEOUT_S)
    else:
        try:
            p = subprocess.run(cmd, capture_output=True, encoding="utf-8",
                               errors="replace", timeout=INVENTORY_TIMEOUT_S)
        except subprocess.TimeoutExpired:
            raise TimeoutError("inventory 超上限 %ss 被杀" % INVENTORY_TIMEOUT_S)
        rc, out, err = p.returncode, p.stdout or "", p.stderr or ""
    if rc != 0:
        raise RuntimeError("inventory rc=%s：%s" % (rc, (err or "").strip()[-300:]))
    lines = [ln for ln in out.strip().splitlines() if ln.strip()]
    if not lines:
        raise ValueError("inventory 回执为空")
    try:
        receipt = json.loads(lines[-1])
    except ValueError as e:
        raise ValueError("inventory 回执末行非 JSON（%s…）：%s" % (lines[-1][:60], e))
    if not isinstance(receipt, dict) or not receipt.get("ok"):
        raise RuntimeError("inventory 回执 ok≠true：%s" %
                           str(receipt.get("error") or receipt)[:300])
    return receipt


def run_stage_face_scan(repo_root: Path, *, runner=None,
                        now: Optional[float] = None) -> Dict[str, Any]:
    """stage 面主入口（activities.run_inspection_scan face=stage 分派 + CLI 共用）。
    仓根缺失 fail-closed；inventory 不可得=S14 响亮未检查（不假绿）。"""
    repo_root = Path(repo_root)
    if not repo_root.is_dir():
        raise ScanError("仓根缺失：%s 不存在（fail-closed）" % repo_root)
    t0 = time.time() if now is None else float(now)
    findings: List[Finding] = []
    meta: Dict[str, Any] = {"checked": False, "caveat": "容器面≠租约面口径：孤儿="
                            "本管域容器工程而无租约文件；out_of_domain 容器只列不判"
                            "（防误伤他项目台）；本面纯读，回收只属 sweep/引擎所有者"}
    try:
        receipt = _run_inventory(repo_root, runner=runner)
    except (FileNotFoundError, RuntimeError, ValueError, TimeoutError, OSError) as e:
        findings.append(Finding(
            scan="stage-inventory", severity="med", subject="S14 未检查",
            evidence="台面清点不可得：%s: %s" % (type(e).__name__, e),
            suggestion="先排 host docker 面（docker info / docker ps -a "
                       "--filter label=com.docker.compose.project），再重跑巡检"))
        findings.sort(key=lambda f: (f.severity, f.scan, f.subject))
        summary = summarize(findings)
        return {"face": "stage", "findings": [f.to_dict() for f in findings],
                "summary": summary["counts"], "heartbeat": False,
                "meta": dict(meta, error="%s: %s" % (type(e).__name__, e))}
    meta["checked"] = True
    meta["capacity"] = receipt.get("capacity")
    cap = receipt.get("capacity") or {}
    stages = receipt.get("stages") or []
    orphans = [s for s in stages if s.get("orphan")]
    containers = int(cap.get("containers") or 0)
    max_stages = int(cap.get("max_stages") or 0)
    ood = receipt.get("out_of_domain") or []
    if orphans:
        oldest = sorted((s for s in orphans if s.get("age_s") is not None),
                        key=lambda s: -(s.get("age_s") or 0))
        head = "、".join("%s(%dh)" % (s["project"], int((s.get("age_s") or 0) // 3600))
                         for s in oldest[:5])
        findings.append(Finding(
            scan="stage-inventory", severity="med", subject="S11 孤儿容器",
            evidence="孤儿台 %d 只（容器在而租约无=账先于容器销/锁根随 tmp 树删除等"
                     "形态）：%s%s" % (len(orphans), head,
                                       "…" if len(oldest) > 5 else ""),
            suggestion="python3 integration/stage_docker.py sweep --dry-run 先点名"
                       "复核（判定窗/年龄阀自动让位），确认后去 --dry-run 真拆"))
    if max_stages > 0 and containers >= max_stages:
        findings.append(Finding(
            scan="stage-inventory", severity="high", subject="S13 容量撞闸",
            evidence="容器 %d ≥ SANDBAR_STAGE_MAX_STAGES=%d——新起台必被保险丝拒"
                     % (containers, max_stages),
            suggestion="立即 sweep 复核清场，并核对该宿主的台所有权纪律"))
    elif max_stages > 0 and containers >= NEAR_FUSE_RATIO * max_stages:
        findings.append(Finding(
            scan="stage-inventory", severity="high", subject="S12 容量逼近闸",
            evidence="容器 %d ≥ 0.8×%d=%d——撞闸前清场窗口"
                     % (containers, max_stages, int(NEAR_FUSE_RATIO * max_stages)),
            suggestion="sweep --dry-run 点名复核孤儿/死租约，提前清场"))
    if ood:
        findings.append(Finding(
            scan="stage-inventory", severity="low", subject="S15 域外容器在册",
            evidence="本管域外容器工程 %d 只（只列不判）：%s" % (
                len(ood), "、".join(str(o.get("project")) for o in ood[:5])),
            suggestion="确认是否他项目/手工台；本面与 sweep 均不触碰"))
    findings.sort(key=lambda f: (f.severity, f.scan, f.subject))
    summary = summarize(findings)
    meta["orphans"] = len(orphans)
    meta["out_of_domain"] = len(ood)
    meta["duration_s"] = round(time.time() - t0, 2) if now is None else 0.0
    return {"face": "stage", "findings": [f.to_dict() for f in findings],
            "summary": summary["counts"], "heartbeat": len(findings) == 0,
            "meta": meta}


def main() -> None:
    ap = argparse.ArgumentParser(description="stage 面巡检扫描器（纯读，单行 JSON 回执）")
    ap.add_argument("--repo-root", required=True)
    args = ap.parse_args()
    try:
        result = run_stage_face_scan(Path(args.repo_root))
        print(json.dumps({"ok": True, "result": result}, ensure_ascii=False).encode("utf-8", "backslashreplace").decode("utf-8"))
    except ScanError as e:
        print(json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False).encode("utf-8", "backslashreplace").decode("utf-8"))
        sys.exit(1)


if __name__ == "__main__":
    main()
