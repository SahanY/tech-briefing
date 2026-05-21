# Daily Tech News Agent

Automated weekday tech briefing and market-movers tracker published to GitHub Pages.

**Live site:** https://sahany.github.io/tech-briefing/

## How It Works

The scheduled task runs Monday-Friday at **9:00 AM CT**.

1. **Collect** - Fetch RSS feeds with `web_fetch` and run web searches for breaking or confirming coverage.
2. **Handle paywalls** - Find accessible coverage for paywalled articles. If needed, use archive.ph.
3. **Curate** - Deduplicate, rank, and write a 1,300-2,000 word investor-style briefing.
4. **Publish briefing** - Push a Jekyll post to GitHub. GitHub Pages auto-builds the site.
5. **Refresh Market Movers** - Run `scripts/generate_stock_movers.py`, research catalysts for the top movers, and publish `_data/stock_movers.json` for `/stocks/`.

## Briefing Sections

1. Top Stories
2. Enterprise Software
3. Venture Capital & Fundraising
4. Tech Investing & Markets
5. AI & Emerging Tech
6. Hot Takes & Commentary
7. Quick Hits

## Market Movers

The Market Movers page lives at `/stocks/`. It reads from Jekyll data file `_data/stock_movers.json` and shows the top 10-15 absolute daily movers across a major technology stock universe, including ticker, company, price, percentage move, dollar move, volume, and a short explanation of the catalyst.

The generator uses `yfinance`, which the scheduled task installs in its sandbox before running:

```bash
python3 -m pip install yfinance
python3 scripts/generate_stock_movers.py --output _data/stock_movers.json
```

## Setup

Create a public GitHub repo. In **Settings -> Pages**, deploy from the `main` branch and root folder.

Create a fine-grained GitHub personal access token with **Contents: Read and write** permission for this repo only.

Save credentials in `.github-pages-config`:

```bash
GITHUB_TOKEN=github_pat_...
GITHUB_USERNAME=YourUsername
GITHUB_REPO_NAME=tech-briefing
```
