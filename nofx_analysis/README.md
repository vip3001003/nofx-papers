# NOFX Analysis Tracking

This directory tracks which papers have been read and analyzed by the NOFX research pipeline.

## Files

### `reviewed.json`

Records all papers that have been fully read (not just title-scanned).

**Schema:**
```json
{
  "meta": {
    "analysis_date": "YYYY-MM-DD",
    "method": "how papers were analyzed",
    "total_papers": 289
  },
  "reviewed_ids": ["2604.02888", "..."],
  "high_priority": {
    "2604.02888": "CMA-ES双层优化→IC权重超参优化"
  }
}
```

**Priority levels:**
- `high_priority` map entry → ⭐ HIGH: direct actionable transfer to NOFX system
- In `reviewed_ids` only → ✅: read, low/no transfer value

## Workflow

### When Claude analyzes new papers
Add IDs to `reviewed_ids`. If HIGH priority, also add to `high_priority` with a one-line transfer note.

### One-time migration
Run `mark_reviewed.py` from repo root to inject analysis markers into existing abstract files:
```bash
python mark_reviewed.py
git add abstracts_zh/ nofx_analysis/
git commit -m "chore: mark reviewed papers with analysis metadata"
```

### Daily fetch (`fetch_papers.py`)
- New papers: checked against `reviewed.json`, shown with 🆕 badge in PAPERS.md
- Already reviewed HIGH: shown with ⭐ HIGH badge
- Already reviewed other: shown with ✅ badge

## Analysis History

| Date | Papers | Method | HIGH |
|------|--------|--------|------|
| 2026-04-26 | 289 (10类全量) | Claude逐类全读，不跳过低分论文 | 41 |
