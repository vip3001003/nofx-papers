#!/usr/bin/env python3
"""
NOFX Paper Radar — daily arXiv fetcher.
- abstracts/      : English originals (for Claude analysis)
- abstracts_zh/   : Pure Chinese translations (for user reading)
- PAPERS.md       : Index with Chinese titles and relevance scores
- nofx_analysis/reviewed.json : Tracks already-analyzed papers (prevent re-read)
"""

import os
import re
import json
import time
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

try:
    from deep_translator import GoogleTranslator
    _translator = GoogleTranslator(source="en", target="zh-CN")
    def translate_zh(text: str) -> str:
        if not text:
            return ""
        try:
            if len(text) > 4500:
                text = text[:4500] + "..."
            result = _translator.translate(text)
            time.sleep(0.5)
            return result or text
        except Exception:
            return text
except ImportError:
    def translate_zh(text: str) -> str:
        return text

ARXIV_API = "http://export.arxiv.org/api/query"
MAX_RESULTS = 30

# ─────────────────────────────────────────────────────────────────────────────
# Scoring keywords — tuned specifically for NOFX system's needs
# ─────────────────────────────────────────────────────────────────────────────

# q-fin categories: direct relevance to factor/IC/gate/regime systems
NOFX_KEYWORDS = [
    # IC / factor evaluation
    "information coefficient", " IC ", "rank IC", "ICIR", "spearman",
    "factor score", "alpha factor", "factor weight", "adaptive weight",
    "factor model", "factor alpha", "factor selection", "factor pruning",
    # Regime & gate logic
    "market regime", "regime detection", "regime switching", "regime router",
    "hidden markov", "hmm", "trending", "ranging", "volatility clustering",
    # Core quant signals
    "momentum", "mean reversion", "macd", "rsi", "order flow",
    "cross-sectional", "time-series momentum", "tsmom", "csmom",
    # Risk & position sizing
    "drawdown", "kelly", "position sizing", "cvar", "sharpe", "max drawdown",
    "portfolio optimization", "risk management",
    # ML applied to quant trading
    "quantitative", "systematic trading", "signal", "backtest",
    "alpha", "ensemble", "cross-validation", "walk-forward",
    # Crypto specific
    "cryptocurrency", "crypto", "bitcoin", "perpetual", "binance",
    "funding rate", "open interest", "liquidation", "long short ratio",
    # Microstructure
    "order book", "microstructure", "high-frequency", "limit order",
    "order flow imbalance", "ofi", "market impact", "spread",
    # Shadow / predictability
    "predictability", "adaptive threshold", "shadow", "out-of-sample",
]

# Cross-disciplinary: physics/bio/info concepts with genuine transfer potential
# Tier-1: method concepts that have demonstrated transfer value to trading systems
TRANSFER_CONCEPTS = [
    # Phase transitions & criticality (→ regime detection, P5 design)
    "phase transition", "critical", "bifurcation", "equilibrium",
    "self-organized criticality", "emergence", "percolation threshold",
    "order parameter", "symmetry breaking",
    # Network dynamics (→ External group, cross-asset contagion)
    "cascade", "contagion", "synchronization", "eigenvalue",
    "network dynamics", "propagation", "systemic risk",
    # Information theory applied (→ IC evaluation, P4 Predictability)
    "kolmogorov complexity", "mutual information", "entropy rate",
    "conditional entropy", "information bottleneck", "transfer entropy",
    # Evolutionary / swarm optimization (→ IC weight hyperparameter tuning)
    "evolutionary algorithm", "genetic algorithm", "cma-es",
    "particle swarm", "pareto", "multi-objective", "nsga",
    "concept drift", "co-evolution", "adaptive mutation",
    # Feedback & control (→ adaptive systems, ModelHealth)
    "feedback control", "adaptive control", "measurement feedback",
    "reinforcement", "attractor", "lyapunov",
    # Prediction & forecasting (generic but high signal)
    "time series prediction", "forecasting", "anomaly detection",
]

# Tier-2: finance bridge — paper explicitly applies to markets
FINANCE_BRIDGE = [
    "market", "trading", "financial", "stock", "portfolio",
    "price", "volatility", "regime", "crypto", "asset",
    "return", "prediction", "forecast", "risk", "hedge",
]

CROSS_CATEGORIES = {"complexity", "network", "info_theory", "bio_inspired"}

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
    "complexity": (
        "complexity",
        'cat:cond-mat.stat-mech OR cat:nlin.AO AND (ti:"phase transition" OR ti:"self-organized" OR ti:emergence OR ti:"complex system" OR ti:"critical" OR ti:attractor OR ti:"nonlinear dynamics")'
    ),
    "network": (
        "network",
        'cat:physics.soc-ph AND (ti:network OR ti:graph OR ti:contagion OR ti:cascade OR ti:"systemic risk" OR ti:interconnected OR ti:propagation)'
    ),
    "info_theory": (
        "info_theory",
        'cat:cs.IT AND (ti:entropy OR ti:"mutual information" OR ti:"information theory" OR ti:"Kolmogorov" OR ti:"compression" OR ti:"channel capacity" OR ti:"rate distortion")'
    ),
    "bio_inspired": (
        "bio_inspired",
        '(cat:q-bio.PE OR cat:cs.NE) AND (ti:evolutionary OR ti:"genetic algorithm" OR ti:"swarm" OR ti:"neural evolution" OR ti:adaptive OR ti:"reinforcement" OR ti:optimization)'
    ),
}

NS = "{http://www.w3.org/2005/Atom}"


def nofx_score(text: str, category: str = "") -> int:
    """
    Score paper relevance to NOFX system.

    For q-fin categories: count NOFX_KEYWORDS hits (direct relevance).
    For cross-disciplinary: TRANSFER_CONCEPTS hits + FINANCE_BRIDGE bonus.
    Bridge bonus rewards papers that explicitly apply to financial markets —
    a paper about CMA-ES applied to trading scores higher than one on CMA-ES
    applied to robotics, even if both use the same concepts.
    """
    text_lower = text.lower()
    if category in CROSS_CATEGORIES:
        concept_hits = sum(1 for kw in TRANSFER_CONCEPTS if kw.lower() in text_lower)
        bridge_hits = sum(1 for kw in FINANCE_BRIDGE if kw.lower() in text_lower)
        # Bridge multiplies only if concepts are present; caps at 9
        if concept_hits == 0:
            return 0
        return min(9, concept_hits + bridge_hits)
    return sum(1 for kw in NOFX_KEYWORDS if kw.lower() in text_lower)


# ─────────────────────────────────────────────────────────────────────────────
# Reviewed paper tracking — prevents re-processing already-analyzed papers
# ─────────────────────────────────────────────────────────────────────────────

REVIEWED_PATH = "nofx_analysis/reviewed.json"
PRIORITY_BADGE = {"HIGH": "⭐ HIGH", "MED": "✦ MED", "LOW": "· LOW", "NONE": "  "}


def load_reviewed() -> dict:
    """Load reviewed.json. Returns {"reviewed_ids": set, "high_priority": dict}."""
    try:
        with open(REVIEWED_PATH, encoding="utf-8") as f:
            data = json.load(f)
        return {
            "reviewed_ids": set(data.get("reviewed_ids", [])),
            "high_priority": data.get("high_priority", {}),
        }
    except FileNotFoundError:
        return {"reviewed_ids": set(), "high_priority": {}}


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
        authors = ", ".join(el.findtext(f"{NS}name", "") for el in authors_els[:3])
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


def save_abstracts(paper: dict, abstracts_dir: str, abstracts_zh_dir: str,
                   reviewed_meta: dict | None = None) -> None:
    score = paper.get("score", 0)
    filename = f"{score:02d}_{paper['id'].replace('/', '_')}_{paper['category']}.md"

    # English original — for Claude analysis
    en_dir = os.path.join(abstracts_dir, paper["date"])
    os.makedirs(en_dir, exist_ok=True)
    en_path = os.path.join(en_dir, filename)
    if not os.path.exists(en_path):
        reviewed_block = ""
        if reviewed_meta:
            priority = reviewed_meta.get("priority", "")
            note = reviewed_meta.get("note", "")
            reviewed_block = (
                f"- **NOFX Reviewed**: ✅ {reviewed_meta.get('date', '')}\n"
                f"- **NOFX Priority**: {priority}\n"
            )
            if note:
                reviewed_block += f"- **NOFX Note**: {note}\n"
        with open(en_path, "w", encoding="utf-8") as f:
            f.write(
                f"# {paper['title']}\n\n"
                f"- **arXiv**: [{paper['id']}]({paper['url']})\n"
                f"- **Date**: {paper['date']}\n"
                f"- **Category**: {paper['category']}\n"
                f"- **Authors**: {paper['authors']}\n"
                f"- **NOFX Relevance Score**: {score}\n"
                f"{reviewed_block}"
                f"\n## Abstract\n\n{paper['abstract']}\n"
            )

    # Chinese — for user reading, organized by category
    zh_dir = os.path.join(abstracts_zh_dir, paper["category"])
    os.makedirs(zh_dir, exist_ok=True)
    zh_filename = f"{score:02d}_{paper['date']}_{paper['id'].replace('/', '_')}.md"
    zh_path = os.path.join(zh_dir, zh_filename)
    if not os.path.exists(zh_path):
        title_zh = paper.get("title_zh") or paper["title"]
        abstract_zh = translate_zh(paper["abstract"])
        reviewed_block_zh = ""
        if reviewed_meta:
            priority = reviewed_meta.get("priority", "")
            note = reviewed_meta.get("note", "")
            reviewed_block_zh = (
                f"- **NOFX分析**: ✅ {reviewed_meta.get('date', '')}\n"
                f"- **迁移优先级**: {PRIORITY_BADGE.get(priority, priority)}\n"
            )
            if note:
                reviewed_block_zh += f"- **迁移价值**: {note}\n"
        with open(zh_path, "w", encoding="utf-8") as f:
            f.write(
                f"# {title_zh}\n\n"
                f"- **arXiv**: [{paper['id']}]({paper['url']})\n"
                f"- **日期**: {paper['date']}\n"
                f"- **分类**: {paper['category']}\n"
                f"- **作者**: {paper['authors']}\n"
                f"- **NOFX相关度**: {score}\n"
                f"{reviewed_block_zh}"
                f"\n## 摘要\n\n{abstract_zh}\n"
            )


def append_to_index(path: str, rows: list[dict], reviewed: dict) -> int:
    """Append new papers to PAPERS.md. Already-reviewed papers show badge."""
    if not rows:
        return 0
    try:
        with open(path, encoding="utf-8") as f:
            content = f.read()
    except FileNotFoundError:
        content = (
            "# NOFX Paper Radar\n\n"
            "| 日期 | 分类 | 相关度 | 中文标题 | arXiv |\n"
            "|------|------|--------|----------|-------|\n"
        )
    lines = []
    for r in rows:
        paper_id = r["id"]
        score = r.get("score", 0)
        title_zh = (r.get("title_zh") or r["title"]).replace("|", "｜")
        # Prefix title with review badge for high-priority papers
        if paper_id in reviewed.get("high_priority", {}):
            title_zh = "⭐ " + title_zh
        lines.append(
            f"| {r['date']} | {r['category']} | {score} | {title_zh} | [link]({r['url']}) |"
        )
    new_content = content.rstrip("\n") + "\n" + "\n".join(lines) + "\n"
    with open(path, "w", encoding="utf-8") as f:
        f.write(new_content)
    return len(lines)


def main():
    index_path = "PAPERS.md"
    abstracts_dir = "abstracts"
    abstracts_zh_dir = "abstracts_zh"

    reviewed = load_reviewed()
    existing_ids = load_existing_ids(index_path)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    new_rows = []

    print(f"Loaded {len(reviewed['reviewed_ids'])} reviewed papers, "
          f"{len(reviewed['high_priority'])} HIGH priority.")

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
                p["score"] = nofx_score(p["title"] + " " + p["abstract"], label)
                p["title_zh"] = translate_zh(p["title"])

                # Attach reviewed metadata if known
                reviewed_meta = None
                if p["id"] in reviewed["reviewed_ids"]:
                    if p["id"] in reviewed["high_priority"]:
                        reviewed_meta = {
                            "priority": "HIGH",
                            "note": reviewed["high_priority"][p["id"]],
                            "date": "2026-04-26",
                        }
                    else:
                        reviewed_meta = {"priority": "reviewed", "date": "2026-04-26"}

                new_rows.append(p)
                save_abstracts(p, abstracts_dir, abstracts_zh_dir, reviewed_meta)
                added += 1
        print(f"  {added} new papers")
        time.sleep(3)

    new_rows.sort(key=lambda r: (r["score"], r["date"]), reverse=True)
    count = append_to_index(index_path, new_rows, reviewed)
    print(f"\nDone: {count} new papers added on {today}")


if __name__ == "__main__":
    main()
