#!/usr/bin/env python3
"""
NOFX Paper Radar — daily arXiv fetcher.
Appends new papers to PAPERS.md and saves abstracts to abstracts/YYYY-MM-DD/.
"""

import os
import re
import time
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

ARXIV_API = "http://export.arxiv.org/api/query"
MAX_RESULTS = 30  # per category per run

# Category → (label, arXiv search query)
CATEGORIES = {
    "momentum": (
        "momentum",
        'cat:q-fin.PM AND (ti:momentum OR ti:"mean reversion" OR ti:"alpha factor" OR ti:"factor model")'
    ),
    "regime": (
        "regime",
        'cat:q-fin.ST AND (ti:"market regime" OR ti:"regime detection" OR ti:"hidden markov" OR ti:"volatility clustering")'
    ),
    "ml": (
        "ml",
        'cat:q-fin.TR AND (ti:"machine learning" OR ti:"deep learning" OR ti:"neural network" OR ti:"reinforcement learning" OR ti:"transformer")'
    ),
    "volume": (
        "volume",
        'cat:q-fin.TR AND (ti:"order flow" OR ti:"volume" OR ti:"microstructure" OR ti:"order book" OR ti:"OBV")'
    ),
    "risk": (
        "risk",
        'cat:q-fin.PM AND (ti:"drawdown" OR ti:"risk management" OR ti:"Kelly" OR ti:"position sizing" OR ti:"portfolio optimization")'
    ),
    "crypto": (
        "crypto",
        'cat:q-fin.* AND (ti:cryptocurrency OR ti:Bitcoin OR ti:crypto OR ti:"digital asset")'
    ),
}

NS = "{http://www.w3.org/2005/Atom}"

# NOFX-relevant keywords for relevance scoring (used in abstract filename prefix)
NOFX_KEYWORDS = [
    "information coefficient", "IC ", "factor", "alpha", "regime",
    "momentum", "mean reversion", "MACD", "volume", "order flow",
    "drawdown", "Kelly", "position sizing", "Sharpe", "cross-sectional",
    "time-series", "quantitative", "systematic", "signal", "backtest",
    "cryptocurrency", "crypto", "high-frequency", "microstructure",
]


def nofx_score(text: str) -> int:
    """Count how many NOFX keywords appear in the text (title + abstract)."""
    text_lower = text.lower()
    return sum(1 for kw in NOFX_KEYWORDS if kw.lower() in text_lower)


def fetch_arxiv(query: str, max_results: int) -> list[dict]:
    params = urllib.parse.urlencode({
        "search_query": query,
        "start": 0,
        "max_results": max_results,
        "sortBy": "submittedDate",
        "sortOrder": "descending",
    })
    url = f"{ARXIV_API}?{params}"
    with urllib.request.urlopen(url, timeout=30) as resp:
        xml_data = resp.read()
    root = ET.fromstring(xml_data)
    papers = []
    for entry in root.findall(f"{NS}entry"):
        arxiv_id_raw = entry.findtext(f"{NS}id", "").strip()
        m = re.search(r"abs/([^\s/]+?)(?:v\d+)?$", arxiv_id_raw)
        if not m:
            continue
        arxiv_id = m.group(1)
        title = re.sub(r"\s+", " ", entry.findtext(f"{NS}title", "").strip())
        abstract = re.sub(r"\s+", " ", entry.findtext(f"{NS}summary", "").strip())
        authors_els = entry.findall(f"{NS}author")
        authors = ", ".join(
            el.findtext(f"{NS}name", "") for el in authors_els[:3]
        )
        if len(authors_els) > 3:
            authors += " et al."
        published = entry.findtext(f"{NS}published", "")[:10]
        papers.append({
            "id": arxiv_id,
            "title": title,
            "abstract": abstract,
            "authors": authors,
            "date": published,
            "url": f"https://arxiv.org/abs/{arxiv_id}",
        })
    return papers


def load_existing_ids(path: str) -> set[str]:
    try:
        with open(path, encoding="utf-8") as f:
            content = f.read()
    except FileNotFoundError:
        return set()
    return set(re.findall(r"arxiv\.org/abs/([^\s)]+)", content))


def save_abstract(paper: dict, abstracts_dir: str) -> None:
    """Save abstract as abstracts/YYYY-MM-DD/[score]_arxiv_id.md"""
    date_dir = os.path.join(abstracts_dir, paper["date"])
    os.makedirs(date_dir, exist_ok=True)
    score = nofx_score(paper["title"] + " " + paper["abstract"])
    # Prefix with zero-padded score (descending) so high-relevance files sort first
    filename = f"{score:02d}_{paper['id'].replace('/', '_')}_{paper['category']}.md"
    filepath = os.path.join(date_dir, filename)
    if os.path.exists(filepath):
        return
    content = (
        f"# {paper['title']}\n\n"
        f"- **arXiv**: [{paper['id']}]({paper['url']})\n"
        f"- **Date**: {paper['date']}\n"
        f"- **Category**: {paper['category']}\n"
        f"- **Authors**: {paper['authors']}\n"
        f"- **NOFX Relevance Score**: {score}\n\n"
        f"## Abstract\n\n{paper['abstract']}\n"
    )
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(content)


def append_to_index(path: str, rows: list[dict]) -> int:
    if not rows:
        return 0
    try:
        with open(path, encoding="utf-8") as f:
            content = f.read()
    except FileNotFoundError:
        content = (
            "# NOFX Paper Radar\n\n"
            "| 日期 | 分类 | 标题 | arXiv |\n"
            "|------|------|------|-------|\n"
        )
    lines = []
    for r in rows:
        safe_title = r["title"].replace("|", "｜")
        lines.append(f"| {r['date']} | {r['category']} | {safe_title} | [link]({r['url']}) |")
    new_content = content.rstrip("\n") + "\n" + "\n".join(lines) + "\n"
    with open(path, "w", encoding="utf-8") as f:
        f.write(new_content)
    return len(lines)


def main():
    index_path = "PAPERS.md"
    abstracts_dir = "abstracts"
    existing_ids = load_existing_ids(index_path)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    new_rows = []

    for key, (label, query) in CATEGORIES.items():
        print(f"Fetching [{label}]...")
        try:
            papers = fetch_arxiv(query, MAX_RESULTS)
        except Exception as e:
            print(f"  ERROR: {e}")
            time.sleep(3)
            continue
        added = 0
        for p in papers:
            if p["id"] not in existing_ids:
                existing_ids.add(p["id"])
                p["category"] = label
                new_rows.append(p)
                save_abstract(p, abstracts_dir)
                added += 1
        print(f"  {added} new papers")
        time.sleep(3)

    new_rows.sort(key=lambda r: (r["date"], r["category"]), reverse=True)
    count = append_to_index(index_path, new_rows)
    print(f"\nDone: {count} new papers added on {today}")
    print(f"Abstracts saved to: {abstracts_dir}/")


if __name__ == "__main__":
    main()
