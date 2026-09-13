#!/usr/bin/env python3
"""t260913-03 场景④：例外腿资产面在**真注册表**上闭合（机械不变式，灰盒 L2）。

intent（用户可感知）：例外腿（改到被跳池资产→强制全跑）只有在「派生资产真的覆盖被跳池池的
  资产」时才拦得住。本条用**独立实现的机械判据**（AST 直读真注册表 + 逐条 cmd token +
  import 解析）交叉核对执行器的资产入口 `--print-pool-assets`：
  ①每个被跳条目 cmd 里的 integration/ 落盘 token（场景文件本身、with_stage.sh 等）都在资产集内；
  ②被跳场景文件 import 到的共享模块（同目录 / integration 顶层可解析者）也在资产集内
     ——这是「改共享舞台/协议库的票」必须全跑的唯一机械保障；
  ③非 integration/ token（如 PY=server/engine/.venv/...）不得误收；
  ④资产入口自证：只读真注册表、不跑套件、未知池名非零点名。
  intent 与 developer 的 L1 电池不同面：彼测入口形状/闭包样例，本条按**真注册表逐条**核闭合。

high-level steps：先做有界安全探针（临时 cwd + 短超时 + 杀进程组，防「旗标不认→真跑全量」
  拖住套件）；确认入口在位后，以仓根为 cwd 跑 `--print-pool-assets engine,exclusive`，
  用 AST 独立复算被跳条目的 token 面与 import 面并逐条比对。
"""
import ast
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import lib_pool_exclude_lane as F  # noqa: E402

C = F.Checker("t260913-03-scenario-4-asset-closure")

POOLS = ("engine", "exclusive")
ARGS = ["--print-pool-assets", F.EXCLUDE_VALUE]


def _json_object(out):
    for ln in reversed([x for x in (out or "").splitlines() if x.strip()]):
        try:
            obj = json.loads(ln.strip())
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            return obj
    return None


def _imported_modules(path):
    """AST 收集顶层 Import/ImportFrom（level==0）的模块名首段；解析失败抛异常。"""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    mods = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                mods.add(a.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0 and node.module:
                mods.add(node.module.split(".")[0])
    return mods


with F.tmpdir() as td:
    # ---------------- 有界安全探针（临时 cwd：旗标不认时真套件在此无对象可跑） ----------------
    probe = F.probe_with_killpg(F.REPO, ARGS, cwd=td, timeout=8,
                                env={"SANDBAR_STAGE_LOCK_DIR": str(td / "stages")})
    probe_out = (probe["stdout"] or "") + (probe["stderr"] or "")
    probe_json = _json_object(probe["stdout"])
    supported = bool(probe_json and "assets" in probe_json)
    C.check(supported, "C1 资产入口 --print-pool-assets 在位（有界探针取到 JSON）",
            "rc=%s timed_out=%s out=%s" % (probe["rc"], probe["timed_out"], probe_out[-300:]))
    if not supported:
        # 安全线自证：临时 cwd 里真套件的条目无对象可跑 → 探针不可能「跑过」任何场景
        C.check("PASS [" not in probe_out,
                "C2 入口缺席时探针未真跑受影响场景（临时 cwd 安全线在案）",
                "out=%s" % probe_out[-300:])
        sys.exit(C.finish())

    # ---------------- 真注册表资产入口 ----------------
    real = F.probe_with_killpg(F.REPO, ARGS, cwd=F.REPO, timeout=120,
                               env={"SANDBAR_STAGE_LOCK_DIR": str(td / "stages2")})
    obj = _json_object(real["stdout"]) or {}
    assets = [str(x) for x in (obj.get("assets") or [])]
    C.check(not real["timed_out"], "C2b 资产入口有界收口（超时即杀组，不悬挂套件）",
            "rc=%s timed_out=%s" % (real["rc"], real["timed_out"]))
    C.check(real["rc"] == 0 and bool(assets), "C3 真注册表资产入口 rc=0 且资产非空",
            "rc=%s obj=%s" % (real["rc"], json.dumps(obj, ensure_ascii=False)[:300]))
    C.check(set(obj.get("pools") or []) == set(POOLS), "C4 回报池名与声明一致",
            "pools=%s" % obj.get("pools"))
    C.check("SCENARIOS ran=" not in (real["stdout"] or ""),
            "C5 资产入口只读注册表、不跑套件（观测/资源边界）",
            "out=%s" % (real["stdout"] or "")[-200:])

    registry = F.registry_pools(F.real_registry())
    out_entries = [(n, p, cmd) for n, p, cmd in registry if p in POOLS]
    C.check(bool(out_entries), "C6 真注册表存在被跳池条目（判据有对象）",
            "pools=%s" % sorted({p for _, p, _ in registry}))

    # ①cmd token 面：被跳条目引用的落盘文件必须都在资产集内
    missing_tokens = []
    for name, pool, cmd in out_entries:
        for tok in F.cmd_file_tokens(cmd):
            if tok not in assets:
                missing_tokens.append((name, tok))
    C.check(not missing_tokens, "C7 被跳条目 cmd 的 integration/ 落盘 token 全在资产集内",
            "缺失=%s" % missing_tokens[:6])

    # ②import 面：被跳场景文件自身依赖的共享模块（同目录 / integration 顶层可解析者）
    unparsed, missing_imports = [], []
    for name, pool, cmd in out_entries:
        for tok in F.cmd_file_tokens(cmd):
            if not tok.endswith(".py"):
                continue
            path = F.REPO / tok
            try:
                mods = _imported_modules(path)
            except (SyntaxError, ValueError) as e:
                unparsed.append("%s(%s)" % (tok, e))
                continue
            for mod in sorted(mods):
                cands = [path.parent / ("%s.py" % mod), F.REPO / "integration" / ("%s.py" % mod)]
                exist = [c for c in cands if c.is_file()]
                if not exist:
                    continue          # 经别处 sys.path 解析（动态/跨目录导入）不在本条目面
                if not any(str(c.relative_to(F.REPO)) in assets for c in exist):
                    missing_imports.append((name, mod))
    C.check(not unparsed, "C8 被跳场景文件全部可 AST 解析（与 lint L1 同口径）", "不可解析=%s" % unparsed)
    C.check(not missing_imports, "C9 被跳场景文件 import 的共享模块全在资产集内（import 闭包面）",
            "缺失=%s" % missing_imports[:6])
    C.check("integration/stage_docker.py" in assets,
            "C10 舞台单点 integration/stage_docker.py 在派生资产内（改舞台的票必全跑）",
            "assets=%d 项" % len(assets))

    # ③误收面：非 integration/ token 不得进资产集
    bad = [a for a in assets if (not a.startswith("integration/")) or ".venv" in a]
    C.check(not bad, "C11 资产集只含 integration/ 面，零误收（含 PY= 前缀 token）", "误收=%s" % bad[:5])

    # ④未知池名：闸侧执法单点必须非零点名（防配错开关静默少跑）
    unknown = F.probe_with_killpg(F.REPO, ["--print-pool-assets", "engine,no-such-pool"],
                                  cwd=F.REPO, timeout=120,
                                  env={"SANDBAR_STAGE_LOCK_DIR": str(td / "stages3")})
    text = (unknown["stdout"] or "") + (unknown["stderr"] or "")
    C.check(not unknown["timed_out"] and unknown["rc"] != 0 and "no-such-pool" in text,
            "C12 未知池名 → 非零退出且点名该池（闸侧执法单点在案）",
            "rc=%s timed_out=%s text=%s" % (unknown["rc"], unknown["timed_out"], text[-200:]))
    C.check("SCENARIOS ran=" not in (unknown["stdout"] or ""),
            "C13 未知池校验同样不跑套件（只读注册表）", "out=%s" % (unknown["stdout"] or "")[-200:])

    # ⑤畸形声明端到端：声明里写错池名 → 闸必须红且点名（不得静默少跑或静默全跑）
    key, err = F.gate_apply_contract()
    if not C.check(key is not None, "C14 闸消费参数已在 verify_lane TOOL schema 声明（契约面）", err):
        sys.exit(C.finish())
    bad_lane = F.build_lane(td / "misconfig", [("mini-main", "main", True),
                                               ("mini-engine", "engine", True)],
                            exclude_pools="engine,no-such-pool")["lane"]
    gbad = F.call_gate(bad_lane, apply=True, write_set=["server/engine/dev_lane.py"])
    rbad = gbad.get("result") or {}
    blob = json.dumps({"err": rbad.get("err"), "detail_red": rbad.get("detail_red"),
                       "pool_exclude": rbad.get("pool_exclude")}, ensure_ascii=False)
    C.check(rbad.get("err") or rbad.get("green") is False,
            "C15 声明含未知池名 → 闸红 fail-closed（不静默出绿）",
            "ok=%s err=%s green=%s" % (gbad.get("ok"), rbad.get("err"), rbad.get("green")))
    C.check("no-such-pool" in blob, "C16 闸红点名配错的池名（诊断可定位）", blob[:300])
    C.check(rbad.get("fail") is None or rbad.get("fail") == 0,
            "C17 配错不得退化成「少 0 条照跑」的绿面", "fail=%s" % rbad.get("fail"))

sys.exit(C.finish())
