#!/usr/bin/env python3
"""溯游 docs 知识库索引生成器。

扫描 docs/design、docs/content、docs/ops、docs/reference 四个目录下的 *.md，
解析每篇的 YAML frontmatter（标准头：title / category / tags / status / updated），
生成 docs/index.json，供 dsh 插件 suyou-knowledge 与其它检索消费。

用法（仓库根）：
    python3 docs/scripts/build_index.py

幂等：每次运行全量重扫四目录重写 index.json，可重复跑。
frontmatter 缺失时大声报（进 review.missing_frontmatter），不静默丢。
仅依赖 stdlib，无第三方依赖。
"""

import json
import re
import sys
from datetime import date, datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
DOCS = REPO / "docs"
OUT = DOCS / "index.json"

CATEGORIES = ["design", "content", "ops", "reference"]

# updated 超过多少天视为「过旧」（review 里提示，不阻断）。
STALE_DAYS = 180

# 标准 frontmatter 键（缺了会提示，但只有 title/category/updated 是硬需要）。
REQUIRED_KEYS = ["title", "category", "updated"]


def extract_title_from_heading(text: str) -> str:
    """回退路径：取正文第一个 `# ` 标题。"""
    for line in text.splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return ""


def parse_frontmatter(text: str):
    """解析文件头部 YAML frontmatter，返回 (meta, body)。无 frontmatter 时 meta={}。

    只支持本仓统一的极简制式：
        ---
        title: "..."
        category: 设计
        tags:
          - a
          - b
        status: active
        updated: 2026-08-19
        ---
    title 支持带引号或裸值；tags 支持块列表或行内 [a, b]。
    """
    meta: dict = {}
    body = text
    if not text.startswith("---\n"):
        return meta, body

    lines = text.split("\n")
    end = None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end = i
            break
    if end is None:
        return meta, body

    block = lines[1:end]
    body = "\n".join(lines[end + 1:]).lstrip("\n")

    tags = []
    for raw in block:
        line = raw.rstrip("\n")
        if line.strip() == "":
            continue
        # 块列表项（只用于 tags）
        if line.startswith("  - ") or line == "-" or line.startswith("- "):
            item = line.lstrip(" -")
            tags.append(item.strip().strip('"').strip("'"))
            continue
        m = re.match(r"^([A-Za-z_][A-Za-z0-9_]*):\s*(.*)$", line)
        if not m:
            continue
        key = m.group(1)
        val = m.group(2).strip()
        if key == "tags":
            # 行内流列表 [a, b, c]；空值=后接块列表（tags 在循环里累积）
            if val.startswith("[") and val.endswith("]"):
                tags = [x.strip().strip('"').strip("'") for x in val[1:-1].split(",") if x.strip()]
            continue
        if val.startswith("[") and val.endswith("]"):
            inner = val[1:-1]
            meta[key] = [x.strip().strip('"').strip("'") for x in inner.split(",") if x.strip()]
            continue
        # 引号字符串
        if len(val) >= 2 and val[0] == val[-1] and val[0] in ('"', "'"):
            val = val[1:-1]
        meta[key] = val

    if tags:
        meta["tags"] = tags

    return meta, body


def parse_date(s: str):
    for fmt in ("%Y-%m-%d", "%Y/%m/%d"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def build() -> dict:
    docs = []
    review = {"missing_frontmatter": [], "deprecated": [], "stale": []}
    today = date.today()

    # 260928：扫描面 = 四类目录 + docs/ 根级散篇（README/terminology/testing-guide 等）。
    # 以前只扫四类目录，根级三篇从未进索引 → 巡检 S8 报「文档缺登记」三项，人查目录时
    # 也看不到它们。根级篇目的 category 取 frontmatter 声明值，不猜目录名。
    targets = []
    for cat in CATEGORIES:
        cat_dir = DOCS / cat
        if cat_dir.is_dir():
            targets.extend((md, cat) for md in sorted(cat_dir.glob("*.md")))
    targets.extend((md, "") for md in sorted(DOCS.glob("*.md")))

    for md, cat in targets:
        rel = md.relative_to(DOCS).as_posix()
        try:
            text = md.read_text(encoding="utf-8")
        except OSError as e:
            print(f"[warn] 读不了 {rel}: {e}", file=sys.stderr)
            continue

        meta, _body = parse_frontmatter(text)
        missing = [k for k in REQUIRED_KEYS if not meta.get(k)]
        has_frontmatter = bool(meta)

        if missing:
            review["missing_frontmatter"].append(rel)
            print(f"[warn] {rel} 缺 frontmatter 键: {missing}", file=sys.stderr)

        title = str(meta.get("title") or extract_title_from_heading(text) or md.stem)
        category = str(meta.get("category") or cat)
        status = str(meta.get("status") or "active")
        updated_raw = str(meta.get("updated") or "")
        tags = meta.get("tags") if isinstance(meta.get("tags"), list) else []
        if isinstance(tags, str):
            tags = [tags]
        tags = [str(t) for t in tags]

        updated_date = parse_date(updated_raw)
        if status == "deprecated":
            review["deprecated"].append(rel)
        if updated_date is not None and (today - updated_date).days > STALE_DAYS:
            review["stale"].append(rel)

        docs.append({
            "path": rel,
            "file": md.name,
            "title": title,
            "category": category,
            "tags": tags,
            "status": status,
            "updated": updated_raw,
            "has_frontmatter": has_frontmatter,
        })

    docs.sort(key=lambda d: (d["category"], d["path"]))

    payload = {
        "generated_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "total": len(docs),
        "categories": CATEGORIES,
        "docs": docs,
        "review": review,
    }
    return payload


def main() -> int:
    payload = build()
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    r = payload["review"]
    print(
        f"docs/index.json 已生成：{payload['total']} 篇，"
        f"缺 frontmatter {len(r['missing_frontmatter'])}，"
        f"deprecated {len(r['deprecated'])}，stale {len(r['stale'])}。"
    )
    for p in r["missing_frontmatter"]:
        print(f"  [缺 frontmatter] {p}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
