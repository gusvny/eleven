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
    ok(("不回落" in section or "不得按" in section)
       and ("不可解析" in section or "解析错误" in section),
       "G3 条目文件畸形=fail-closed 不回落（三态总纲落点）")
    ok("生效前提" in section or ("放开" in section and "装载器" in section),
       "G4 过渡状态：以装载器放开工单落地为生效前提")
    ok(("软" in section or "跳过" in section) and ("None" in section or "返回空" in section),
       "G5 锚点 vs 内容：内容缺失维持软语义（默认 persona / 查表返回空→默认模型）")
    ok(("损坏" in section or "不可解析" in section)
       and ("容错" in section or "继承" in section or "None" in section)
       and "model_routes" in section,
       "G6 声明表内容损坏容错边界（声明与否不分叉）")
    ok("strip" in section or "纯空白" in section, "G7 空白值口径（strip 判空）")

    print("SC sc_paths_contract_doc_guard pass=%d fail=%d" % (pass_n, fail_n))
    return 1 if fail_n else 0


if __name__ == "__main__":
    sys.exit(main())
