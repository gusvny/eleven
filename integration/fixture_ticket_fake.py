# fixture_ticket_fake.py —— 夹具票的假 DevLaneWorkflow（260908）。
#
# 为什么存在：等台族的工单场景（ticket-session-restore / t260903-07 族 /
# ticket-evidence-images）需要台上有「健康工单」——行有标题、抽屉 show 秒回。
# 真 workflow 没有常驻 worker 时查询会空等到超时（左栏「查询超时，刷新重试」、
# 抽屉 show 挂起）。而引擎有现成出路：COMPLETED 的 workflow 免 worker 直读
# （client.py cmd_ticket_query 的 result() 通路，260824 实测口径）——所以夹具
# 票只要「跑到收口」就永久健康（收口 7 天回填窗内列表行带全量 meta）。
#
# 本模块被 fixture_ticket_worker.py 以 Worker 装载：必须保持「干净模块」
# （只有 temporalio import + 类定义，无模块级受限调用）——temporalio 沙箱
# 校验 @workflow.defn 类时会重执行定义模块，模块级 pathlib/subprocess 会炸
# 校验（integration/t260902-02 同案）。快照 meta 形状对齐 dev_lane._init
# 的字段面（消费方=client.py _row_from_meta / handleTicketSessionOpen 的
# workspace/worktree 判定），只填场景要的面，不追求全字段复刻。

from temporalio import workflow


def _now_epoch() -> int:
    # workflow 沙箱禁 time.time()（RestrictedWorkflowAccessError）——
    # workflow.now() 是沙箱内取时的唯一正道（deterministic，重放安全）；
    # epoch 化走 timedelta 算术（不经任何 time.* 调用）。
    import datetime as _dt

    return int((workflow.now() - _dt.datetime(1970, 1, 1, tzinfo=_dt.timezone.utc))
               .total_seconds())


def _g(obj, key, default=""):
    """dict / dataclass 双形态取值（ticket-start 的入参形态以引擎为准，不猜）。"""
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


@workflow.defn(name="DevLaneWorkflow")
class FixtureTicket:
    """夹具票 workflow：run 直接回吐终态快照（秒收口，零活动零副作用）。"""

    @workflow.run
    async def run(self, inp) -> dict:
        now = _now_epoch()
        tid = str(_g(inp, "ticket_id", ""))
        title = str(_g(inp, "title", ""))
        meta = {
            "id": tid,
            "workflow_id": str(_g(inp, "template_id", "dev-lane")),
            "project": str(_g(inp, "project", "")),
            "title": title,
            "role": "developer",
            "lane": str(_g(inp, "lane", "worktree")),
            # 空路径=宿主随工单走契约的缺省面（open 路由回落 cwd=项目主目录）。
            "workspace": {"type": "worktree", "path": ""},
            "worktree": "",
            "branch": str(_g(inp, "branch", "")),
            "base_ref": str(_g(inp, "base_ref", "")),
            "proposal_id": str(_g(inp, "proposal_id", "")),
            "book_path": str(_g(inp, "book_path", "")),
            "epic": str(_g(inp, "epic", "")),
            "stage": "create_plan",
            "stage_state": "awaiting",
            "write_set": [],
            "no_file_changes": True,
            "acceptance": [],
            "checks": {},
            "deliverables": "",
            "user_request": str(_g(inp, "user_request", "")),
            "spec": str(_g(inp, "spec", "")),
            "body": str(_g(inp, "body", "")),
            "pending": [],
            "handoffs": [],
            "status": "dispatched",
            "created": now,
            "updated": now,
            "last_rework_note": "",
            "temporal": True,
        }
        return {"engine": "template-as-code-v2", "meta": meta}
