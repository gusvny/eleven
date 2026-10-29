#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Retired-premise exclusions for a round (ticket t261029-76).

A round judges what it can observe TODAY. When the premise a case rests on is
retired by a host order - docker, host order 261027: never use docker again -
that case can never pass again, yet every round booked it as an environment
failure and no tree could reach a green judgment (measured 2026-10-29 on round
run-01M63CEX71YDHNH56E612BX86C: two cases, two env_fail entries, a frozen
line, a human judgement needed every round).

This module is the ONE place that answers "is this case's premise retired?".
The decision is EXPLICIT DATA - ``integration/retired-premises.json`` - never a
heuristic over a log or a substring of an evidence line: a premise is declared
with its retirement order and a reason, and each entry is named against a
premise. The three consequences travel together and are all required:

  1. the entry does NOT run in the round, so nothing is booked for it;
  2. the round NAMES it with the premise and the reason - a silent skip is the
     same defect in the other direction;
  3. the entry STAYS in the registry (listed, marked in place) - no case simply
     disappears, and its disposition is recorded beside the data.

Vocabulary (a pool skip and a retired premise are TWO decisions, two names):
  pool skip       ``跳过 [<name>]（池=<pool>）`` / ``本轮跳过池=<pools>（少 N 条）``
                  = this round is narrowed for scheduling reasons; the entry
                  is still judged by rounds that do not narrow.
  retired premise ``RETIRED_PREMISE [<name>]（前提=<id>，退役=<order>：<why>）``
                  = this entry cannot be judged by ANY round until its premise
                  returns; the exclusion is an observability fact, not a
                  scheduling choice.

Fail-closed direction: this module only ever NARROWS by explicit declaration,
never widens a verdict. An unreadable or malformed data file excludes NOTHING
(the behaviour before this ticket, which reds the round on a real failure) and
says so by name; the calling round prints that reason, and the integration case
``sc_retired_premise_round_face`` fails on it so the data cannot rot silently.
Every premise that is still live keeps today's behaviour exactly: a real
environment failure still books ENV_FAIL and still reds the round.

Test seam: ``SANDBAR_RETIRED_PREMISE_PATH`` overrides the data path (the same
shape as ``SANDBAR_KNOWN_RED_ROSTER``); an absent value means the repository's
own ``integration/retired-premises.json``.
"""
from __future__ import annotations

import json
import os

#: The declared data file, relative to this module.
DATA_NAME = "retired-premises.json"
#: Override seam (tests / stub premises). An unreadable explicit pointer is a
#: named error, never a silent fallthrough to the repository file.
PATH_ENV = "SANDBAR_RETIRED_PREMISE_PATH"
SCHEMA = "retired-premises-v1"
#: Dispositions an entry may carry. ``excluded`` = this round does not judge it
#: (its premise is retired); ``repointed`` = the case moved to a live
#: observation face and still runs (documented, never excluded).
DISPOSITIONS = ("excluded", "repointed", "replaced")


def data_path(path=None, env=None):
    """The data file this process reads: explicit argument, then the env
    pointer, then this module's own repository file."""
    if path:
        return str(path)
    env = os.environ if env is None else env
    raw = str(env.get(PATH_ENV) or "").strip()
    if raw:
        return raw
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), DATA_NAME)


def validate(data):
    """Schema problems in ``data`` as a list of named strings (empty = sound).

    Judged on the DECLARED meaning, not on shapes alone: every excluded entry
    must name a declared premise (so an exclusion always answers "which
    premise?"), the premise must carry its retirement order and a reason, and
    every excluded entry must carry an ``excluded`` disposition (so the
    registry-side record and the round-side decision cannot drift apart).
    """
    problems = []
    if not isinstance(data, dict):
        return ["data_not_object:%r" % (type(data).__name__,)]
    if data.get("schema") != SCHEMA:
        problems.append("schema_mismatch:%r" % (data.get("schema"),))
    premises = data.get("premises")
    if not isinstance(premises, list) or not premises:
        problems.append("premises_missing")
        premises = []
    ids = []
    for i, p in enumerate(premises):
        if not isinstance(p, dict):
            problems.append("premise_not_object:#%d" % i)
            continue
        pid = p.get("id")
        if not isinstance(pid, str) or not pid.strip():
            problems.append("premise_id_missing:#%d" % i)
            continue
        if pid in ids:
            problems.append("premise_id_duplicate:%s" % pid)
        ids.append(pid)
        if not isinstance(p.get("retired"), str) or not p["retired"].strip():
            problems.append("premise_retirement_missing:%s" % pid)
        if not isinstance(p.get("reason"), str) or not p["reason"].strip():
            problems.append("premise_reason_missing:%s" % pid)
    excluded = data.get("excluded")
    if not isinstance(excluded, list):
        problems.append("excluded_missing")
        excluded = []
    names = []
    for i, e in enumerate(excluded):
        if not isinstance(e, dict):
            problems.append("excluded_not_object:#%d" % i)
            continue
        name = e.get("name")
        if not isinstance(name, str) or not name.strip():
            problems.append("excluded_name_missing:#%d" % i)
            continue
        if name in names:
            problems.append("excluded_name_duplicate:%s" % name)
        names.append(name)
        premise = e.get("premise")
        if premise not in ids:
            problems.append("excluded_premise_undeclared:%s:%r" % (name, premise))
        if not isinstance(e.get("reason"), str) or not e["reason"].strip():
            problems.append("excluded_reason_missing:%s" % name)
    disps = data.get("dispositions")
    if not isinstance(disps, list):
        problems.append("dispositions_missing")
        disps = []
    disp_names = {}
    for i, d in enumerate(disps):
        if not isinstance(d, dict):
            problems.append("disposition_not_object:#%d" % i)
            continue
        name = d.get("name")
        if not isinstance(name, str) or not name.strip():
            problems.append("disposition_name_missing:#%d" % i)
            continue
        kind = d.get("disposition")
        if kind not in DISPOSITIONS:
            problems.append("disposition_unknown:%s:%r" % (name, kind))
        if not isinstance(d.get("detail"), str) or not d["detail"].strip():
            problems.append("disposition_detail_missing:%s" % name)
        if name in disp_names:
            problems.append("disposition_name_duplicate:%s" % name)
        disp_names[name] = kind
    for name in names:
        kind = disp_names.get(name)
        if kind is None:
            problems.append("excluded_has_no_disposition:%s" % name)
        elif kind != "excluded":
            problems.append("excluded_disposition_disagrees:%s:%s" % (name, kind))
    for name, kind in disp_names.items():
        if kind == "excluded" and name not in names:
            problems.append("disposition_excluded_but_not_listed:%s" % name)
    return problems


def load(path=None, env=None):
    """Read + validate the data. Returns ``(data, err)``.

    ``data`` is a dict on success. On ANY failure ``data`` is None and ``err``
    is a named string (``read_failed:<why>`` / ``json_invalid:<why>`` /
    ``schema:<problems>``): the caller must treat "no data" as "exclude
    nothing" and print the reason - this module never guesses an exclusion.
    """
    p = data_path(path, env)
    try:
        with open(p, encoding="utf-8") as fh:
            raw = fh.read()
    except OSError as e:
        return None, "read_failed:%s:%s" % (p, e.strerror or e)
    try:
        data = json.loads(raw)
    except ValueError as e:
        return None, "json_invalid:%s:%s" % (p, e)
    problems = validate(data)
    if problems:
        return None, "schema:%s:%s" % (p, "|".join(problems[:8]))
    return data, None


def exclusions(data):
    """The declared exclusions as receipt records, sorted by name.

    Each record carries exactly what the receipt must be able to say: the case
    name, the premise, the retirement order and the reason. Nothing is derived
    from the runtime evidence of the case - the exclusion is a declaration.
    """
    if not isinstance(data, dict):
        return []
    premises = {p.get("id"): p for p in (data.get("premises") or [])
                if isinstance(p, dict)}
    out = []
    for e in data.get("excluded") or []:
        if not isinstance(e, dict):
            continue
        name = e.get("name")
        premise = premises.get(e.get("premise")) or {}
        if not isinstance(name, str) or not name.strip():
            continue
        out.append({
            "name": name.strip(),
            "premise": str(e.get("premise") or ""),
            "retired": str(premise.get("retired") or ""),
            "reason": str(e.get("reason") or "").strip(),
        })
    return sorted(out, key=lambda r: r["name"])


def exclusion_names(data):
    """Just the names (the round's exclusion set)."""
    return [r["name"] for r in exclusions(data)]


def select(records, names):
    """The records whose name is in ``names``, order preserved by name."""
    wanted = {n for n in (names or []) if isinstance(n, str)}
    return [r for r in records if r["name"] in wanted]


def line(record):
    """The ONE receipt line for an excluded entry (pinned vocabulary).

    Distinguishable by its prefix (``RETIRED_PREMISE``) from the pool-skip
    vocabulary (``跳过 [...]`` / ``本轮跳过池=``), so a reader of the round's log
    never confuses a scheduling decision with a retired premise. It names the
    entry, the premise, the retirement order and the reason - all four.
    """
    return ("RETIRED_PREMISE [%s]（前提=%s，退役=%s：%s）"
            % (record.get("name"), record.get("premise"),
               record.get("retired"), record.get("reason")))


def banner(records):
    """The one-line face above the per-entry lines: what this round does NOT
    judge, and why it is not a pool skip."""
    return ("INTEG_RETIRED_PREMISE 本轮不判 %d 条已退役前提条目（不跑、不判红、"
            "仍列在册；与池排除不同：池排除=排期决定，退役前提=前提已退役、"
            "任何一轮都不可判）" % len(records or []))


def face_refs(data):
    """The audit face of the dispositions (both measured entries included).

    A reader of the data file, and the case that guards it, need the full
    account: which entry was RE-POINTED to a live observation face and which
    one was EXCLUDED, with the detail. This is documentation, not a decision -
    the decision is ``exclusions()``.
    """
    if not isinstance(data, dict):
        return []
    out = []
    for d in data.get("dispositions") or []:
        if not isinstance(d, dict):
            continue
        name = d.get("name")
        if not isinstance(name, str) or not name.strip():
            continue
        out.append({"name": name.strip(),
                    "disposition": str(d.get("disposition") or ""),
                    "detail": str(d.get("detail") or "").strip()})
    return sorted(out, key=lambda r: r["name"])
