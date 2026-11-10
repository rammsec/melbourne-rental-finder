# Melbourne Rental Finder — Rollback & Recovery Guide

## 1. Development Checkpoint Information
- **Baseline Git Tag**: `v1-stable-before-v2`
- **Baseline Commit SHA**: `f7d43f08da9c33f4d8e1d00b2faa54185bbf27a7`
- **Development Branch**: `feature/rental-finder-v2`
- **Production / Stable Branch**: `main` (Untouched during V2 development)
- **Snapshot Directory**: `backup/v1_checkpoint/` (Preserves exact copies of `scraper/`, `docs/`, and `README.md`)

---

## 2. Emergency Rollback Instructions

If any part of the V2 upgrade fails or needs to be completely backed out:

### A. Quick Revert to Stable V1 Branch
```bash
# Ensure uncommitted files are stashed or discarded
git stash

# Return to main branch at stable v1 tag
git checkout main
git reset --hard v1-stable-before-v2

# Force-verify working tree is clean
git status
```

### B. Restoring Data & Scraper Files from Physical Backup
If files were modified or corrupted:
```bash
cp -r backup/v1_checkpoint/scraper .
cp -r backup/v1_checkpoint/docs .
cp backup/v1_checkpoint/README.md .
```

### C. Database Rollback
- V2 maintains dual-mode operation: the normalized database layer writes to `docs/data/listings.json` and `docs/data/database.sqlite` (or Supabase via adapter).
- The frontend always includes a fallback mechanism: if V2 database endpoints fail or are unavailable, it seamlessly falls back to reading `docs/data/listings.json`.
- To discard SQLite/database changes without losing raw scraped data:
  ```bash
  rm -f docs/data/database.sqlite docs/data/database.sqlite-journal
  cp backup/v1_checkpoint/docs/data/listings.json docs/data/listings.json
  ```

---

## 3. Current Architecture (V1 Baseline)

### Scraper Components (`scraper/`)
1. **`scraper/config.py`**:
   - `USER_CRITERIA`: Move-in window (`2026-12-05` to `2027-01-15`), budget cap ($525 unfurnished / $560 furnished), solo occupancy, preferred 2BHK.
   - `HAWTHORN_DIRECT_SUBURBS`: 27 corridor suburbs along Belgrave & Lilydale lines, Tram 70/75/16 corridors, and Clayton.
2. **`scraper/sources.py`**:
   - Gumtree RSS feeds for 27 corridor suburbs + explicit lease transfer search feeds (`?price=0.00__600.00`).
   - Flatmates whole property scraper.
   - Strict freshness filters: `<= 15 days` for lease transfers, `<= 10 days` for normal rentals.
3. **`scraper/scorer.py`**:
   - Availability parsing (`parse_availability`), station distance extraction (`extract_station_distance`), weekly rent normalization (`parse_price_weekly`), sharehouse & student-only filters.
4. **`scraper/run_scraper.py`**:
   - CLI & scheduled runner producing `docs/data/listings.json` and `docs/data/digest.md`.

### Frontend Components (`docs/`)
1. **`docs/index.html`**:
   - Dashboard hosted on GitHub Pages (`https://rammsec.github.io/melbourne-rental-finder/`).
   - Tabs: Strict Matches & All Listings, Normal Listings (≤$600), Shortlist, FB Analyzer, Portals, Transit Reference.
2. **`docs/app.js`**:
   - Client-side filtering, localStorage management (`melb_rental_statuses_v1`, `melb_rental_custom_fb_v1`), 3-state star toggle.
3. **`docs/styles.css`**:
   - Responsive styling with CSS variables.

### GitHub Actions (`.github/workflows/daily_scrape.yml`)
- Runs daily at 07:00 UTC (6:00 PM Melbourne AEDT) and commits updated `docs/data/listings.json` and `docs/data/digest.md`.

---

## 4. V2 Staged Upgrade Plan
- **Stage 1**: Checkpoint, Git tag, backup, ROLLBACK.md
- **Stage 2**: Dashboard readability & card progressive disclosure redesign (Sections A-E)
- **Stage 3**: Unified property data model (`Property`, `ListingSource`, `ListingSnapshot`)
- **Stage 4**: Multi-source duplicate detection & freshness tracking (high/medium/low confidence)
- **Stage 5**: 100-point explainable scoring engine with confidence levels & version control
- **Stage 6**: Persistent database architecture (SQLite + Supabase PostgreSQL adapter interface)
- **Stage 7**: Snapshots, scoring history, and user interaction logging
- **Stage 8**: Property comparison tool (2-4 properties side-by-side) & preference insights engine
- **Stage 9**: Regression testing, validation suite, and documentation
