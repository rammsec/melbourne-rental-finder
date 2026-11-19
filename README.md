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

- `scraper/config.py` — Suburb-to-Hawthorn transit definitions, centralised Eastern/South-Eastern suburb targets (`PRIMARY_SUBURBS`, `SECONDARY_SUBURBS`), and budget/date criteria.
- `scraper/scorer.py` — Strict filtering & 100-point scoring engine (furniture detection, sharehouse rejection, commute time tiering, December window matching).
- `scraper/sources/` — Modular direct real estate agency adapters (`BaseAgencyAdapter`) plus marketplace scrapers (`Gumtree`, `Flatmates`, `Facebook Marketplace`, `Reddit`).
- `scraper/deduplicator.py` — Cross-agency duplicate detection consolidating multi-source listings while preserving all agency provenance links.
- `scraper/run_scraper.py` — Main runner that outputs `docs/data/listings.json`, `docs/data/database.sqlite`, and `docs/data/digest.md`.
- `docs/` — Static GitHub Pages web dashboard (`index.html`, `styles.css`, `app.js`, `data/listings.json`) with multi-select agency filters and per-agency health telemetry.
- `.github/workflows/daily_scrape.yml` — Runs every morning at **8:00 AM Melbourne Time (AEDT)** via GitHub Actions with concurrency protection and request retries.

---

## Direct Real Estate Agency Sources (Phase 1 Status)

| Priority | Agency | Adapter Module | Status | Extraction Method & Notes |
| :--- | :--- | :--- | :--- | :--- |
| **P1** | **Barry Plant** | `scraper/sources/barry_plant.py` | **Live (`integrated`)** | Public rental directory cards + detail page JSON-LD (`Offer`, `PostalAddress`) |
| **P1** | **Ray White** | `scraper/sources/ray_white.py` | **Live (`integrated`)** | Next.js SSR `__NEXT_DATA__` structured JSON payload (`initialListings` / `results`) |
| **P1** | **Jellis Craig** | `scraper/sources/jellis_craig.py` | **Live (`integrated`)** | Eastern suburbs search HTML cards + detail page base64 description payload |
| **P1** | **Nelson Alexander** | `scraper/sources/nelson_alexander.py` | **Live (`integrated`)** | Public rental search directory + detail page JSON-LD (`RealEstateListing`) |
| **P2** | **Harcourts** | `scraper/sources/harcourts.py` | **Live (`integrated`)** | Server-rendered HTML cards from `harcourts.net/au/listings/rent` |
| **P2** | **Belle Property** | `scraper/sources/belle_property.py` | **Blocked (`blocked`)** | Edge WAF blocks automated HTTP requests with `HTTP 403 Forbidden`; isolated safely |
| **P2** | **McGrath** | `scraper/sources/mcgrath.py` | **Blocked (`blocked`)** | Edge WAF blocks automated requests with `HTTP 429 Too Many Requests`; isolated safely |
| **P2** | **Woodards** | `scraper/sources/woodards.py` | **Live (`integrated`)** | Public rental search cards + detail page availability/agency metadata |
| **P2** | **Buxton** | `scraper/sources/buxton.py` | **Live (`integrated`)** | Official JSON API (`cms.buxton.com.au/api/v1/listings/`) + Next.js SSR fallback |
| **P2** | **Fletchers** | `scraper/sources/fletchers.py` | **Live (`integrated`)** | Public `/properties-for-lease` HTML tiles (respecting `Crawl-delay: 5` in `robots.txt`) |

---

## Running Locally

```bash
# 1. Run the scraper to refresh docs/data/listings.json
python3 -m scraper.run_scraper

# 2. Run unit and fixture test suite
python3 -m unittest discover -s tests -v

# 3. Preview the dashboard locally
python3 -m http.server 8080 --directory docs
```

## Activating on GitHub (Free Daily Automation)

1. Push this repository to GitHub.
2. In your GitHub repo, go to **Settings → Pages**:
   - Under **Build and deployment**, select **Deploy from a branch**.
   - Select branch `main` and folder `/docs`, then click **Save**.
3. Go to the **Actions** tab to trigger `Daily Melbourne Lease Transfer & Rental Scraper` anytime with one click, or let it run automatically every morning at 8:00 AM Melbourne time.
4. Once you've signed your new lease before December 3, 2026, simply archive or delete the repository!
