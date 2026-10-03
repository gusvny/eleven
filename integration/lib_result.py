#!/usr/bin/env python3
"""失败分类协议 v1 发射器（python 侧，t260910-13）——场景产「一行 JSON =
一个用例」规范行的唯一入口（mjs 侧对应 integration/lib_result.mjs）。

写侧 fail-closed（与闸侧 enforce_semantics 双端同治「免责标签」）：
- not-checked 无 evidence → 拒绝发射（ValueError），不许把无证据的环境红
  推给闸去改判——写侧就该报对；
- status/cause 不在词表 / 缺 name → 拒发；
- evidence 机械一行化（换行/回车压平），一行原文不变式由发射器保证。

字段缺省：attempt=1（producer=发射器；rework 代数由闸/引擎侧显式盖写，
不许双写者并存——K4）、started=当前 UTC、git_sha=SANDBAR_GIT_SHA 或
git rev-parse 回落、suite=""、artifacts=[]。

旧文本行（ENV_FAIL:/SUMMARY）暂保留输出作兼容期观测面——闸双解析期
规范行权威，文本行忽略；协议全量切换后由退役票统一摘除。
"""
import datetime
import json
import os
import subprocess
import sys

STATUSES = ("pass", "fail", "not-checked")
CAUSES = ("self", "external", "unknown")


def evidence_one_line(text):
    if text is None:
        return ""
    return str(text).replace("\\", "\\\\").replace("\r", "").replace("\n", "\\n")


def _git_sha():
    sha = os.environ.get("SANDBAR_GIT_SHA")
    if sha:
        return sha
    try:
        p = subprocess.run(["git", "rev-parse", "--short", "HEAD"],
                           capture_output=True, text=True, timeout=5)
        return p.stdout.strip() if p.returncode == 0 else ""
    except Exception:
        return ""


def spec_line(name, status, cause="unknown", reason="", evidence="",
              suite="", dur_s=None, attempt=1, started=None, git_sha=None,
              artifacts=None):
    """构造并校验一条规范行（返回 str，含末尾换行）。写侧 fail-closed：
    无证据 not-checked / 词表外状态 / 缺名一律 ValueError 拒发。"""
    if not name or not isinstance(name, str):
        raise ValueError("规范行缺 name，拒发")
    if status not in STATUSES:
        raise ValueError("status=%r 不在词表 %s，拒发" % (status, (STATUSES,)))
    if cause not in CAUSES:
        raise ValueError("cause=%r 不在词表 %s，拒发" % (cause, (CAUSES,)))
    evidence = evidence_one_line(evidence)
    if status == "not-checked" and not evidence.strip():
        raise ValueError(
            "not-checked（环境红/未检验到）无 evidence 拒发（写侧 fail-closed："
            "无证据的 ENV_FAIL 一律按 FAIL 处理，t260910-13）——把缺什么写进 evidence")
    obj = {
        "name": name, "suite": suite or "", "status": status, "cause": cause,
        "reason": reason or "", "dur_s": dur_s,
        "attempt": int(attempt) if attempt else 1,
        "started": started or datetime.datetime.now(
            datetime.timezone.utc).isoformat(timespec="seconds"),
        "git_sha": git_sha if git_sha is not None else _git_sha(),
        "evidence": evidence, "artifacts": list(artifacts or []),
    }
    return json.dumps(obj, ensure_ascii=False) + "\n"


def emit_case(**kw):
    """spec_line 的打印出口。"""
    sys_stdout_write(spec_line(**kw))


def sys_stdout_write(text):
    sys.stdout.write(text)
    sys.stdout.flush()


class ScenarioCheck:
    """场景内断言助手单点（t261002-14 收敛）：ok()/na()/finish()/env_fail() 四件套，
    收编 sc_*.py 里逐字拷贝的局部定义（t261001-04 收敛 selfcheck_* 同族问题的
    场景侧续作）。输出格式参数化以逐字保留各场景既有措辞（detail 截断上限、
    flush 与否），只收敛定义点，不改任何一行断言行为。

    退出码契约与 integration/lib_env 三态一致：finish() 有 FAIL=exit 1（含
    「全部 N/A=设计/覆盖问题」判红）；env_fail() 恒 exit 2 并点名缺什么。
    用法::

        _ck = ScenarioCheck(detail_cap=600, flush=True)
        ok, na, finish, env_fail = _ck.ok, _ck.na, _ck.finish, _ck.env_fail
        ...
        finish(NAME)          # 早退档自行 exit；正常返回后才收口
    """

    def __init__(self, ok_fmt="  ok %s", fail_fmt="  FAIL %s",
                 detail_cap=600, flush=False):
        self.passes = 0
        self.fails = 0
        self.nas = 0
        self.ok_fmt = ok_fmt
        self.fail_fmt = fail_fmt
        self.detail_cap = detail_cap
        self.flush = flush

    def ok(self, cond, label, detail=""):
        if cond:
            self.passes += 1
            print(self.ok_fmt % label, flush=self.flush)
        else:
            self.fails += 1
            msg = self.fail_fmt % label
            if detail:
                msg += " | " + str(detail)[:self.detail_cap]
            print(msg, flush=self.flush)

    def na(self, label, reason=""):
        self.nas += 1
        print("  N/A: %s（%s）" % (label, str(reason)[:400]), flush=self.flush)

    def env_fail(self, name, reason):
        print("ENV_FAIL [%s] exit=2\n    %s" % (name, reason), flush=self.flush)
        sys.exit(2)

    def finish(self, name):
        if self.nas and self.passes == 0 and self.fails == 0:
            print("FAIL [%s] exit=1\n    全部子用例 N/A=无可验对象（设计/覆盖问题）" % name,
                  flush=self.flush)
            sys.exit(1)
        print("SUMMARY pass=%d fail=%d env_fail=0 na=%d"
              % (self.passes, self.fails, self.nas), flush=self.flush)
        sys.exit(1 if self.fails else 0)
