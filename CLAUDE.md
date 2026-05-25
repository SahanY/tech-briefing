# CLAUDE.md - Daily Tech Briefing Agent

## Purpose

Publish a concise weekday tech briefing to GitHub Pages as a Jekyll post, then refresh the Market Movers page with the day's largest tech-related stock moves from a broad Nasdaq-listed plus S&P 500 scan.

## Schedule

Run Monday-Friday at **9:00 AM CT**.

On Monday runs, include weekend coverage: collect and consider technology news published since the prior Friday briefing, including Saturday and Sunday stories, using a 72-hour lookback.

## Context Rules

- Do not read, summarize, reference, or use `latest-post.md` unless explicitly asked to debug generated output.
- Treat `latest-post.md` as generated output, not source context.
- Use `config.yaml`, site files, and this file as operating context.
- Do not expose, print, or commit credentials from `.github-pages-config`.

## Workflow

1. Load source, ranking, and market-mover settings from `config.yaml`.
2. Fetch configured RSS feeds with `web_fetch`.
3. Run web searches for breaking news and free confirmation coverage.
4. For paywalled sources, use headlines as importance signals only; summarize from accessible sources. If no free alternatives are found, use archive.ph.
5. Deduplicate and rank stories by source quality, recency, keyword signal, and category fit.
6. Before writing, apply the source-diversity gate from `config.yaml`: the ranked story pool should include at least 10 usable articles from at least 5 publications, and no single publication should account for more than 35% of usable articles. If the gate fails, retry RSS/web collection with broader searches before drafting. If it still fails, publish only with an explicit reduced-coverage note in the sources footer.
7. Write one Jekyll post: `_posts/YYYY-MM-DD-tech-briefing.md`.
8. Publish the briefing through the GitHub Contents API.
9. Generate `_data/stock_movers.json` from `scripts/generate_stock_movers.py`, which ranks the broad Nasdaq-listed plus S&P 500 universe and skips non-tech companies until 15 tech-related movers are selected. Research each selected mover, add 3-4 sentence explanations, and publish the JSON through the GitHub Contents API.
10. GitHub Pages builds and serves the site.

## Output Format

Use Jekyll front matter:

```yaml
---
layout: post
title: "Tech Briefing — DAY, MONTH DD"
date: YYYY-MM-DD
summary: "One-sentence deck with 3-4 biggest items separated by semicolons"
---
```

Briefing body format:

- Start directly with `## Top Stories`; no intro paragraph.
- Use `##` section headers only.
- Do not use `###` story subheads.
- In all sections except Hot Takes and Quick Hits, each story is one paragraph beginning with a bold declarative lead sentence.
- Use bullets only in Quick Hits.
- End with `---` and an italic sources line.

Market Movers data must be valid JSON at `_data/stock_movers.json` with this shape:

```json
{
  "date": "YYYY-MM-DD",
  "generated_at": "ISO timestamp",
  "data_as_of": "YYYY-MM-DD, 9:00 AM CT",
  "source": "yfinance",
  "universe": {
    "mode": "nasdaq_listed_plus_sp500",
    "tech_only": true
  },
  "filters": {
    "tech_only": true
  },
  "stocks": [
    {
      "rank": 1,
      "ticker": "NVDA",
      "name": "NVIDIA Corporation",
      "price": 135.42,
      "previous_close": 125.61,
      "change_pct": 7.81,
      "change_abs": 9.81,
      "volume": "98.2M",
      "volume_raw": 98200000,
      "direction": "gain",
      "explanation": "Three to four sentences explaining the catalyst."
    }
  ]
}
```
