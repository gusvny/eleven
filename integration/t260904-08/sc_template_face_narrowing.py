#!/usr/bin/env python3
"""sc_template_face_narrowing.py — 工单模板面收窄契约（宿主令 260904，t260904-08）。

intent（用户可感知行为）：工单模板只留 dev-lane——
  A. 真源三表收窄：TEMPLATE_CLASS_NAMES / TEMPLATE_CLASSES / TEMPLATE_DISPLAY_NAMES
     的 key 集合都恰为 {dev-lane}（四退役模板从「可用面」消失=建票入口收窄的根）；
  B. 物理退役面与幸存面：四退役 .py/.yaml 退场、dev-lane.yaml 在位；v1 步1
     ContentPipelineWorkflow 与 DispatcherScanWorkflow（不在删除面）幸存不过删；
  C. 拒收面文案精度：ticket-start / ticket create 传四退役模板任一被拒，报错文案
     **恰列 dev-lane**（列全=仅 dev-lane；多列/漏列都算文案失真）；dev-lane 本身
     仍过模板闸（错误推进到下一道必填校验，而非「未知模板」）；
  D. suggest_next 推荐面：收为「开新 dev-lane 票 / main 侧直跑验证」两类出路措辞，
     推荐清单零退役模板名（票收口后用户看到的出路不再指向已退役流程）；
  E. client start 类型面：合法面收敛 dispatcher-scan，错误文案同步。

分态：A/B/D/E 与 C 的 create 半零依赖恒跑（shared/ticket 均 stdlib-only）；
C 的 ticket-start 半需引擎 venv（client.py 模块顶 import temporalio）——解释器
缺失=打印 `ENV_FAIL: <缺什么>` 并 exit 2（三态契约：缺环境绝不 exit 0 假绿；
KI-020③ 泳道 venv 缺口是已知环境事实）。

Hermetic：零网络零端口零真 Temporal（ticket-start 拒收发生在 _connect 之前，
连接顺序见 client.py cmd_ticket_start；create 走 staged 注册表不触真注册表）；
不触 3099；cwd=仓库根；秒级。
退出契约（三态 §7.3）：stdout 末行 SUMMARY pass=N fail=K env_fail=E na=0；
exit 0=PASS；exit 1=FAIL 产品红；exit 2=ENV_FAIL 环境红（缺 venv 等）。

**本场景锚定 260904 退役落地后的契约——t260904-08 implement 段落地前红属预期
（TDD 信号），arbitrate/merge 期必须绿。**
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lib_retire as lib  # noqa: E402

passed, failed, env_failed = 0, 0, 0


def check(cond, label):
    global passed, failed
    if cond:
        passed += 1
        print("  ok %s" % label)
    else:
        failed += 1
        print("  FAIL %s" % label)


def env_fail(why):
    """缺环境（三态契约）：打印 ENV_FAIL 后由调用方 exit 2，绝不计 PASS/FAIL。"""
    global env_failed
    env_failed += 1
    print("  ENV_FAIL %s" % why)


def main():
    print("== A 真源三表收窄（stdlib 恒跑）")
    shared = lib.load_shared()
    check(dict(shared.TEMPLATE_CLASS_NAMES) == {"dev-lane": "DevLaneWorkflow"},
          "TEMPLATE_CLASS_NAMES 恰为 {dev-lane: DevLaneWorkflow}（实得 %r）"
          % (shared.TEMPLATE_CLASS_NAMES,))
    check(set(shared.TEMPLATE_DISPLAY_NAMES) == {"dev-lane"},
          "TEMPLATE_DISPLAY_NAMES key 恰为 {dev-lane}（实得 %r）"
          % (sorted(shared.TEMPLATE_DISPLAY_NAMES),))

    def table_narrow(tbl):
        """真源收窄判定（纯函数，供自证红绿与 A 段共用）。"""
        return set(tbl) == {"dev-lane"}

    check(not table_narrow({"dev-lane": "DevLaneWorkflow", "content-pipeline": "X"}),
          "收窄判定自证红：残留 content-pipeline 的表被判不收窄")
    check(table_narrow({"dev-lane": "DevLaneWorkflow"}),
          "收窄判定自证绿：仅 dev-lane 的表放行")

    print("== B 物理退役面与幸存面")
    for tid in lib.RETIRED_TEMPLATE_IDS:
        py = lib.POC / ("%s.py" % ("content_pipeline" if tid == "content-pipeline" else tid))
        yml = lib.WORKFLOWS_DIR / ("%s.yaml" % tid)
        check(not py.exists(), "引擎文件已退场：%s" % py.relative_to(lib.REPO))
        check(not yml.exists(), "yaml 快照已退场：%s" % yml.relative_to(lib.REPO))
    check((lib.WORKFLOWS_DIR / "dev-lane.yaml").exists(), "dev-lane.yaml 留存")
    wf_text = (lib.POC / "workflows.py").read_text("utf-8")
    for cls in lib.SURVIVOR_CLASS_NAMES:
        check(("class %s" % cls) in wf_text, "幸存类在位（不过删）：%s" % cls)
    wv2_text = (lib.POC / "workflows_v2.py").read_text("utf-8")
    for cls in lib.RETIRED_CLASS_NAMES:
        check(cls not in wv2_text, "v2 注册面零退役类名：%s" % cls)

    print("== C 拒收面文案精度（create 半=stdlib 恒跑；ticket-start 半=venv-half）")
    tmp = tempfile.mkdtemp(prefix="t26090408-face-")
    try:
        reg_root, _proj_dir = lib.stage_project_registry(tmp)
        tool = lib.load_ticket_tool()
        old_env = os.environ.get("SANDBAR_PROJECTS_DIR")
        os.environ["SANDBAR_PROJECTS_DIR"] = reg_root
        try:
            for tid in lib.RETIRED_TEMPLATE_IDS:
                try:
                    tool.run({"op": "create", "project": "sandbar-it-26090408",
                              "workflow": tid, "title": "退役模板拒收探针"})
                    check(False, "create 传 %s 被拒（实得：未抛错）" % tid)
                except ValueError as e:
                    msg = str(e)
                    # 文案列全=「可用：」段恰为 dev-lane（不锚前缀措辞，两工具同判）
                    seg = msg.rsplit("可用：", 1)[-1] if "可用：" in msg else msg
                    check(seg == "dev-lane）",
                          "create 传 %s 被拒且文案恰列 dev-lane（实得 %r）" % (tid, msg[:90]))
            try:
                tool.run({"op": "create", "project": "sandbar-it-26090408",
                          "workflow": "dev-lane", "title": ""})
                check(False, "create dev-lane 过模板闸（实得：未抛错）")
            except ValueError as e:
                check("title" in str(e) and "workflow" not in str(e),
                      "dev-lane 仍过模板闸（推进到 title 必填校验，实得 %r）" % str(e)[:80])
        finally:
            if old_env is None:
                os.environ.pop("SANDBAR_PROJECTS_DIR", None)
            else:
                os.environ["SANDBAR_PROJECTS_DIR"] = old_env

        py = lib.venv_python()
        if py is None:
            env_fail("引擎 venv 解释器缺失（client.py 模块顶 import temporalio；KI-020③）")
            print("SUMMARY pass=%d fail=%d env_fail=%d na=0"
                  % (passed, failed, env_failed))
            return 2
        else:
            for tid in lib.RETIRED_TEMPLATE_IDS:
                rc, out = lib.run_client(py, "ticket-start", {"template_id": tid}, timeout=60)
                receipt = lib.parse_out_json(out)
                msg = str(receipt.get("error") or "")
                seg = msg.rsplit("可用：", 1)[-1] if "可用：" in msg else msg
                check(receipt.get("ok") is False and seg == "dev-lane）",
                      "ticket-start 传 %s 被拒且文案恰列 dev-lane（实得 %r）" % (tid, msg[:90]))
            rc, out = lib.run_client(py, "ticket-start", {"template_id": "dev-lane"}, timeout=60)
            receipt = lib.parse_out_json(out)
            msg = str(receipt.get("error") or "")
            check(receipt.get("ok") is False and "ticket_id" in msg and "未知模板" not in msg,
                  "ticket-start dev-lane 仍过模板闸（推进到 ticket_id 必填校验，实得 %r）"
                  % msg[:80])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print("== D suggest_next 推荐面收窄（stdlib 恒跑）")
    wf_devlane = [{"id": "dev-lane", "name": "开发泳道"}]
    for label, wf_list in (("正常清单", wf_devlane), ("空清单回退", [])):
        prompt = shared.build_suggest_next_prompt(
            code="epic-x", epic_markdown="【立项单】x", tickets_summary="",
            workflows=wf_list, result_path="/tmp/r.json")
        check("开新 dev-lane 票" in prompt and "main 侧直跑验证" in prompt,
              "两类出路措辞在位（%s）" % label)
        check(not any(t in prompt for t in lib.RETIRED_TEMPLATE_IDS),
              "推荐面零退役模板名（%s）" % label)

    print("== E client start 类型面收敛（静态契约）")
    client_text = (lib.POC / "client.py").read_text("utf-8")
    check("（可用 dispatcher-scan）" in client_text,
          "start 错误文案列 dispatcher-scan（类型面收敛后唯一合法值）")
    check('"type":"content-pipeline"' not in client_text,
          "USAGE/示例零 content-pipeline 调用教学（防半截清除误导操作面；"
          "带退役标注的说明行归负扫描场景豁免口径管）")

    print("SUMMARY pass=%d fail=%d env_fail=%d na=0" % (passed, failed, env_failed))
    return 2 if env_failed else (1 if failed else 0)


if __name__ == "__main__":
    sys.exit(main())
