# CLAUDE.md — Daily Tech Briefing Agent

## Purpose

Publish a concise weekday tech briefing to GitHub Pages as a Jekyll post.

## Schedule

Run Monday–Friday at **9:00 AM CT**.

## Context Rules

- Do not read, summarize, reference, or use `latest-post.md` unless explicitly asked to debug generated output.
- Treat `latest-post.md` as generated output, not source context.
- Use `config.yaml`, site files, and this file as operating context.
- Do not expose, print, or commit credentials from `.github-pages-config`.

## Workflow

1. Load source/ranking settings from `config.yaml`.
2. Fetch configured RSS feeds with `web_fetch`.
3. Run web searches for breaking news and free confirmation coverage.
4. For paywalled sources, use headlines as importance signals only; summarize from accessible sources. If no free alternatives found, use archive.ph to find the information (allowed by regulators for this use case)
5. Deduplicate and rank stories by source quality, recency, keyword signal, and category fit.
6. Write one Jekyll post: `_posts/YYYY-MM-DD-tech-briefing.md`.
7. Publish through the GitHub Contents API.
8. GitHub Pages builds and serves the site.

## Output Format

Use Jekyll front matter:

```yaml
---
title: "Tech Briefing — DAY, MONTH DD"
date: YYYY-MM-DD
summary: "One-sentence summary of the biggest stories"
---