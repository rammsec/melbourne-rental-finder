# Melbourne Lease Transfer & Hawthorn Commute Finder

A zero-dependency, automated daily rental and lease-transfer finder built for securing an entire property in Melbourne before **December 3, 2026** (ahead of a **January 10, 2027** lease end).

## Built-In Search Criteria & Scoring Rules

- **Occupancy**: Solo entire property only (**2 BHK preferred**, 1 BHK accepted; sharehouses, flatshares, and student rooms are automatically filtered out).
- **Weekly Rent Cap**:
  - **Unfurnished**: max **\$525/week**
  - **Furnished**: max **\$560/week**
- **Direct Commute to Hawthorn (`3122`)**:
  - **Belgrave / Lilydale / Alamein Train Lines**: Hawthorn, Glenferrie, Auburn, Richmond, Burnley, Camberwell, Canterbury, Surrey Hills, Mont Albert, Box Hill, Blackburn, Nunawading, Mitcham, Ringwood, Hartwell, Burwood, Ashburton, East Melbourne, Melbourne CBD.
  - **Direct Tram Routes 70, 75 & 16**: Kew, Kooyong, Toorak, Malvern, Armadale, Caulfield North, St Kilda East, Docklands.
  - **Direct Bus 609**: Abbotsford, Kew.
- **Target Move-In Window**: **December 5 – December 30, 2026** (prioritizes lease transfers / lease breaks).

---

## Project Structure

- `scraper/config.py` — Suburb-to-Hawthorn transit definitions and budget/date criteria.
- `scraper/scorer.py` — Strict filtering & 100-point scoring engine (furniture detection, sharehouse rejection, commute time tiering, December window matching).
- `scraper/sources.py` — Scrapers for Flatmates.com.au (Whole Properties & 1-Beds), Domain.com.au, Reddit (`r/melbourne`), and Hawthorn corridor lease transfers.
- `scraper/run_scraper.py` — Main runner that outputs `docs/data/listings.json` and `docs/data/digest.md`.
- `docs/` — Static GitHub Pages web dashboard (`index.html`, `styles.css`, `app.js`, `data/listings.json`).
- `.github/workflows/daily_scrape.yml` — Runs every morning at **8:00 AM Melbourne Time (AEDT)** via GitHub Actions and updates the live GitHub Pages dashboard.

---

## Running Locally

```bash
# 1. Run the scraper to refresh docs/data/listings.json
python3 -m scraper.run_scraper

# 2. Preview the dashboard locally
python3 -m http.server 8080 --directory docs
```

## Activating on GitHub (Free Daily Automation)

1. Push this repository to GitHub.
2. In your GitHub repo, go to **Settings → Pages**:
   - Under **Build and deployment**, select **Deploy from a branch**.
   - Select branch `main` and folder `/docs`, then click **Save**.
3. Go to the **Actions** tab to trigger `Daily Melbourne Lease Transfer & Rental Scraper` anytime with one click, or let it run automatically every morning at 8:00 AM Melbourne time.
4. Once you've signed your new lease before December 3, 2026, simply archive or delete the repository!
