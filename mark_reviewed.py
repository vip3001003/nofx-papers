#!/usr/bin/env python3
"""
One-time migration: add NOFX analysis markers to existing abstract files.
Run once from the nofx-papers repo root:
    python mark_reviewed.py

What it does:
- Reads nofx_analysis/reviewed.json
- Finds all matching .md files in abstracts_zh/
- Injects "NOFX分析" and "迁移优先级" fields if not already present
- Reports how many files were updated
"""

import os
import re
import json

REVIEWED_PATH = "nofx_analysis/reviewed.json"
ABSTRACTS_ZH_DIR = "abstracts_zh"

PRIORITY_BADGE = {
    "HIGH": "⭐ HIGH",
    "MED": "✦ MED",
    "LOW": "· LOW",
    "NONE": "  NONE",
}


def load_reviewed():
    with open(REVIEWED_PATH, encoding="utf-8") as f:
        return json.load(f)


def inject_marker(filepath: str, arxiv_id: str, high_map: dict, analysis_date: str) -> bool:
    """
    Add NOFX analysis fields after the NOFX相关度 line.
    Returns True if file was modified.
    """
    with open(filepath, encoding="utf-8") as f:
        content = f.read()

    # Skip if already marked
    if "NOFX分析" in content or "NOFX Reviewed" in content:
        return False

    # Determine priority
    if arxiv_id in high_map:
        priority = "HIGH"
        note = high_map[arxiv_id]
        badge = PRIORITY_BADGE["HIGH"]
    else:
        priority = "reviewed"
        note = ""
        badge = "✅"

    # Build injection text
    if note:
        injection = (
            f"- **NOFX分析**: ✅ {analysis_date}\n"
            f"- **迁移优先级**: {badge}\n"
            f"- **迁移价值**: {note}\n"
        )
    else:
        injection = (
            f"- **NOFX分析**: ✅ {analysis_date}\n"
            f"- **迁移优先级**: ✅ 已分析\n"
        )

    # Inject after the "NOFX相关度" line
    new_content = re.sub(
        r"(- \*\*NOFX相关度\*\*:.*\n)",
        r"\1" + injection,
        content,
        count=1,
    )

    if new_content == content:
        # Fallback: inject before ## 摘要
        new_content = content.replace("## 摘要", injection + "## 摘要", 1)

    if new_content != content:
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(new_content)
        return True
    return False


def main():
    data = load_reviewed()
    reviewed_ids = set(data["reviewed_ids"])
    high_map = data["high_priority"]
    analysis_date = data["meta"]["analysis_date"]

    updated = 0
    skipped_already = 0
    not_found = []

    for category in os.listdir(ABSTRACTS_ZH_DIR):
        cat_dir = os.path.join(ABSTRACTS_ZH_DIR, category)
        if not os.path.isdir(cat_dir):
            continue
        for fname in os.listdir(cat_dir):
            if not fname.endswith(".md"):
                continue
            # Extract arXiv ID from filename: {score}_{date}_{id}.md
            # ID may contain dots: e.g. 2604.02888 or 1704.01366
            m = re.match(r"\d+_\d{4}-\d{2}-\d{2}_(.+)\.md$", fname)
            if not m:
                continue
            arxiv_id = m.group(1).replace("_", "/")
            # Handle standard IDs (no slash needed)
            if "/" not in arxiv_id:
                pass  # already clean like 2604.02888

            if arxiv_id not in reviewed_ids:
                # Try without slash transformation
                arxiv_id_plain = m.group(1)
                if arxiv_id_plain in reviewed_ids:
                    arxiv_id = arxiv_id_plain
                else:
                    not_found.append(fname)
                    continue

            filepath = os.path.join(cat_dir, fname)
            result = inject_marker(filepath, arxiv_id, high_map, analysis_date)
            if result:
                updated += 1
            else:
                skipped_already += 1

    print(f"✅ Updated:          {updated} files")
    print(f"⏭  Already marked:   {skipped_already} files")
    if not_found:
        print(f"⚠️  ID not in reviewed ({len(not_found)} files): {not_found[:5]}{'...' if len(not_found)>5 else ''}")
    print("\nDone. Commit with: git add abstracts_zh/ && git commit -m 'chore: mark 289 papers as reviewed (2026-04-26)'")


if __name__ == "__main__":
    main()
