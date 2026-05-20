
## `README.md`

```md
# Daily Tech News Agent

Automated weekday tech briefing published to GitHub Pages.

The agent collects tech news from RSS feeds and web search, curates the most relevant stories into seven sections, writes a Jekyll markdown post, and publishes it through the GitHub Contents API.

**Live site:** https://sahany.github.io/tech-briefing/

## How It Works

The scheduled task runs Monday–Friday at **9:00 AM CT**.

1. **Collect** — Fetch RSS feeds with `web_fetch` and run web searches for breaking or confirming coverage.
2. **Handle paywalls** — Find accessible coverage for paywalled articles. If this fails, use archive.ph
3. **Curate** — Deduplicate, rank, and write a 1,300–2,000 word briefing.
4. **Publish** — Push a Jekyll post to GitHub. GitHub Pages auto-builds the site.

## Briefing Sections

1. Top Stories
2. Enterprise Software
3. Venture Capital & Fundraising
4. Tech Investing & Markets
5. AI & Emerging Tech
6. Hot Takes & Commentary
7. Quick Hits

## Setup

### 1. GitHub repo + Pages

Create a public GitHub repo. In **Settings → Pages**, deploy from the `main` branch and root folder.

### 2. Fine-grained token

Create a fine-grained GitHub personal access token with **Contents: Read and write** permission for this repo only.

Save credentials in `.github-pages-config`:

```bash
GITHUB_TOKEN=github_pat_...
GITHUB_USERNAME=YourUsername
GITHUB_REPO_NAME=tech-briefing