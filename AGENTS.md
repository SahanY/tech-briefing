# AGENTS.md - Codex Daily Tech Briefing Agent

## Purpose

Run the weekday Tech Briefing automation in Codex and publish it to GitHub Pages. Each run also refreshes the Market Movers page with a newly generated list of tech-related stock movers.

## Operating Rules

- Do not read or use `latest-post.md` unless debugging generated output.
- Do not expose credentials from `.github-pages-config`.
- Use `config.yaml`, `CLAUDE.md`, and `github-pages-site/scheduled-task-prompt.md` as operating context.
- The canonical market movers script is `scripts/generate_stock_movers.py`.

## Market Movers

- Each run must replace the prior Market Movers names with the current run's 15 selected stocks.
- Store only the current market movers data in `_data/stock_movers.json`.
- Do not create dated Market Movers files, snapshots, archives, or history folders.
- Temporary files such as `tmp/stock_movers_raw.json`, `tmp/stock_movers_explanations.json`, and `tmp/stock_movers.json` must be deleted after the GitHub update succeeds or after failure details are reported.
- The generator scans Nasdaq-listed common stocks plus current S&P 500 constituents, ranks movers by absolute daily percentage change, skips non-tech companies, and keeps walking down the ranked list until 15 tech-related movers are selected.

## Publishing

- Publish the daily briefing post to `_posts/YYYY-MM-DD-tech-briefing.md`.
- Publish Market Movers by updating the single file `_data/stock_movers.json` through the GitHub Contents API.
- Use the existing file SHA when updating GitHub content so the file is replaced in place.
- After publishing, clean up posts older than 30 days. Do not delete `_data/stock_movers.json`.
