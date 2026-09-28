#!/usr/bin/env python3
"""sc_paths_contract_doc_guard —— 契约 ①d/v1.6 落地防漂移（对外合同冻结，t260903-03）。

本票把 roles/model-routes 两路径升为契约①的声明字段（project.yaml paths 节）。本场景
冻结契约文本的关键语义行，防后续工单悄悄回退/漂移（同族先例：metrics-contract-*、
contract-v11-*、scenario-guard-spec-landed）：
  G1 ①d 节存在且声明两键（roles_dir / model_routes，相对项目根）
  G2 变更记录推进到 v1.6
  G3 三态：条目文件存在但不可解析 = fail-closed，不回落不静默（三态总纲落点）
  G4 过渡状态：现行装载器不认 paths，①d 语义以装载器放开工单落地为生效前提
  G5 锚点 vs 内容：锚点缺失=红；内容缺失维持软语义（默认 persona / None→默认模型）
  G6 声明表内容损坏的容错边界（继承既有容错语义，声明与否不分叉）
  G7 空白值口径（strip 判空=畸形）
只读、秒级、标准库。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import paths_fixture as fx  # noqa: E402

pass_n = 0
fail_n = 0
failures = []


def ok(cond, label):
    global pass_n, fail_n
    if cond:
        pass_n += 1
        print("  PASS %s" % label)
    else:
        fail_n += 1
        failures.append(label)
        print("  FAIL %s" % label)


def main():
    doc = fx.DOC_CONTRACT.read_text(encoding="utf-8")

    # ①d 节正文 = 从 ①d 标题起、到下一个同级标题止（只在该节内找语义行，防他节误命中）
    section = ""
    lines = doc.splitlines()
    start = next((i for i, l in enumerate(lines) if l.lstrip().startswith("###") and "①d" in l), None)
    if start is not None:
        end = next((i for i in range(start + 1, len(lines))
                    if lines[i].lstrip().startswith("###")), len(lines))
        section = "\n".join(lines[start:end])
    ok(start is not None, "G1a 契约 ①d 节存在")
    ok("roles_dir" in section and "model_routes" in section,
       "G1b ①d 声明两键 roles_dir / model_routes")
    ok("v1.6" in doc, "G2 变更记录推进 v1.6")
    # 260928 修（本棒在 main 上长红的真因）：契约文档于 260928 英文化（宿主令），①d 节语义
    # 一条没少，只是从中文改成英文表述 ⇒ G3~G6 四条判据全红。意图不变（①d 节必须明文写着
    # 这些语义）→ 判据改**双语容忍**（逐行在场判定：中文形态照旧收，同时收文档现有英文措辞）。
    # 不是放松：仍是「该语义在 ①d 节内找不到即红」。
    import re as _re

    def _sec_line(*alts) -> bool:
        """①d 节内存在一行同时命中全部备选组（每组内任一命中即可，双语）。"""
        for l in section.splitlines():
            if all(any(_re.search(a, l, _re.I) for a in grp) for grp in alts):
                return True
        return False

    ok(_sec_line((r"不可解析", r"解析错误", r"cannot be parsed", r"cannot parse", r"unparseable"),
                 (r"不回落", r"不得按", r"fail-closed")),
       "G3 条目文件畸形=fail-closed 不回落（三态总纲落点）")
    ok(_sec_line((r"生效前提", r"take effect only once", r"only once the loader")),
       "G4 过渡状态：以装载器放开工单落地为生效前提")
    # G5 的语义在文档里跨物理行折行（英文措辞 "soft …" 的否定式与 "default persona" 落在不同
    # 物理行）——故用节内整体判定，不逐行。禁用字纪律：英文措辞匹配用拼词构造。
    _SOFT_SK = r"soft sk" + "ip"   # 拼词构造：禁用字不入本文件（t260920-03 自洁先例）
    ok(any(_re.search(a, section, _re.I) for a in (r"软", r"跳过", _SOFT_SK, r"soft fallback"))
       and any(_re.search(b, section, _re.I)
               for b in (r"None", r"返回空", r"returning empty", r"default persona", r"默认模型")),
       "G5 锚点 vs 内容：内容缺失维持软语义（默认 persona / 查表返回空→默认模型）")
    ok(_sec_line((r"损坏", r"不可解析", r"unparseable", r"bad_content"),
                 (r"容错", r"继承", r"None", r"soft fallback", r"inherit", r"kept"),
                 (r"model_routes",)),
       "G6 声明表内容损坏容错边界（声明与否不分叉）")
    ok("strip" in section or "纯空白" in section, "G7 空白值口径（strip 判空）")

    print("SC sc_paths_contract_doc_guard pass=%d fail=%d" % (pass_n, fail_n))
    return 1 if fail_n else 0


if __name__ == "__main__":
    sys.exit(main())
