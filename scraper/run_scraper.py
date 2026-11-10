#!/usr/bin/env python3
"""
Main CLI & GitHub Actions Runner for Melbourne Lease Transfer & Rental Finder V2.

Features:
- Scrapes live Gumtree Lease Transfers & Rentals
- Scrapes live Flatmates Whole Properties
- Scrapes live Reddit Lease Transfer posts
- Normalizes into unified Property models
- Multi-criteria cross-source deduplication with confidence scoring
- 100-point explainable scoring engine V2
- Lifecycle and freshness tracking
- Persistent relational SQLite storage (docs/data/database.sqlite)
- Optional Supabase PostgreSQL cloud sync (when credentials configured)
- Exports backward-compatible JSON to docs/data/listings.json
- Generates daily Markdown digest to docs/data/digest.md
"""

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, List

from .config import USER_CRITERIA, HAWTHORN_DIRECT_SUBURBS
from .models import Property, ScraperExecutionLog
from .scorer import score_and_classify_listing
from .scorer_v2 import score_property_v2
from .dedup import deduplicate_properties
from .freshness import update_property_freshness, update_catalog_freshness
from .db import PropertyDatabase
from .sources import (
    scrape_gumtree_lease_transfers,
    scrape_flatmates_whole_properties,
    scrape_reddit_lease_transfers,
    scrape_facebook_marketplace_aligned,
    get_listing_age_days,
    is_outside_melbourne,
)

ROOT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT_DIR / "docs" / "data"
LISTINGS_FILE = DATA_DIR / "listings.json"
DIGEST_FILE = DATA_DIR / "digest.md"
DATABASE_FILE = DATA_DIR / "database.sqlite"


def load_existing_listings() -> Dict[str, Dict[str, Any]]:
    if not LISTINGS_FILE.exists():
        return {}
    try:
        data = json.loads(LISTINGS_FILE.read_text(encoding="utf-8"))
        return {item["id"]: item for item in data.get("listings", []) if "id" in item}
    except Exception:
        return {}


def build_portal_quick_links() -> List[Dict[str, str]]:
    """
    Direct pre-filtered search portals tailored for Hawthorn & direct transit corridors.
    """
    return [
        {
            "name": "Domain: Full Belgrave & Lilydale Line Corridor (≤$600/wk)",
            "category": "Domain.com.au (Live)",
            "url": "https://www.domain.com.au/rent/?suburb=melbourne-vic-3000,east-melbourne-vic-3002,richmond-vic-3121,burnley-vic-3121,hawthorn-vic-3122,hawthorn-east-vic-3123,camberwell-vic-3124,canterbury-vic-3126,surrey-hills-vic-3127,mont-albert-vic-3127,box-hill-vic-3128,blackburn-vic-3130,nunawading-vic-3131,mitcham-vic-3132,ringwood-vic-3134,heathmont-vic-3135,bayswater-vic-3153,boronia-vic-3155,ferntree-gully-vic-3156,upper-ferntree-gully-vic-3156,upwey-vic-3158,tecoma-vic-3160,belgrave-vic-3160,ringwood-east-vic-3135,croydon-vic-3136,mooroolbark-vic-3138,lilydale-vic-3140,clayton-vic-3168&bedrooms=1-3&price=0-600&excludedeposittaken=1&sort=dateupdated-desc",
            "note": "Complete 27-suburb search across the entire Belgrave and Lilydale lines plus Inner East and Clayton under $600/wk.",
        },
        {
            "name": "Domain: Hawthorn, Box Hill, Clayton, Bayswater, Boronia (≤$525/wk)",
            "category": "Domain.com.au (Live)",
            "url": "https://www.domain.com.au/rent/?suburb=hawthorn-vic-3122,hawthorn-east-vic-3123,camberwell-vic-3124,kew-vic-3101,richmond-vic-3121,surrey-hills-vic-3127,box-hill-vic-3128,burwood-vic-3125,malvern-vic-3144,clayton-vic-3168,bayswater-vic-3153,boronia-vic-3155&bedrooms=1-2&price=0-525&excludedeposittaken=1&sort=dateupdated-desc",
            "note": "Live 1-2BR listings under $525/wk across Hawthorn, Box Hill, Clayton, Bayswater, and Boronia corridors.",
        },
        {
            "name": "Domain: Clayton, Bayswater & Boronia Direct Search (≤$525/wk)",
            "category": "Domain.com.au (Live)",
            "url": "https://www.domain.com.au/rent/?suburb=clayton-vic-3168,bayswater-vic-3153,boronia-vic-3155&bedrooms=1-2&price=0-525&excludedeposittaken=1&sort=dateupdated-desc",
            "note": "Focused search for Clayton (Pakenham line), Bayswater (Belgrave line), and Boronia (Belgrave line).",
        },
        {
            "name": "Domain: 1–2BHK Furnished along Corridor (≤$560 Furnished)",
            "category": "Domain.com.au (Live)",
            "url": "https://www.domain.com.au/rent/?suburb=hawthorn-vic-3122,hawthorn-east-vic-3123,camberwell-vic-3124,kew-vic-3101,richmond-vic-3121,box-hill-vic-3128,malvern-vic-3144,clayton-vic-3168,bayswater-vic-3153,boronia-vic-3155,melbourne-vic-3000&bedrooms=1-2&price=0-560&features=furnished&excludedeposittaken=1&sort=dateupdated-desc",
            "note": "Furnished 1-2BR properties up to $560/wk on direct train/tram lines to Hawthorn.",
        },
        {
            "name": "Realestate.com.au: 2BR Hawthorn, Clayton, Bayswater, Boronia ≤$525/wk",
            "category": "Realestate.com.au (Live)",
            "url": "https://www.realestate.com.au/rent/with-2-bedrooms-between-0-525-in-hawthorn,+vic+3122%3b+hawthorn+east,+vic+3123%3b+camberwell,+vic+3124%3b+kew,+vic+3101%3b+box+hill,+vic+3128%3b+clayton,+vic+3168%3b+bayswater,+vic+3153%3b+boronia,+vic+3155/list-1?activeSort=list-date&includeSurrounding=false",
            "note": "Exact suburb matches on the Belgrave/Lilydale & Pakenham lines.",
        },
        {
            "name": "FB Marketplace: 2BR Lease Transfers (Ascending Distance)",
            "category": "Facebook Marketplace (Live)",
            "url": "https://www.facebook.com/marketplace/melbourne/search?sortBy=distance_ascend&query=lease%20transfer%202%20bedroom&exact=false",
            "note": "Primary user search: 2BR lease transfers sorted by distance from Melbourne. Copy and paste promising posts into our analyzer!",
        },
        {
            "name": "FB Marketplace: Hawthorn, Camberwell & Richmond",
            "category": "Facebook Marketplace (Live)",
            "url": "https://www.facebook.com/marketplace/melbourne/search?sortBy=distance_ascend&query=lease%20transfer%202%20bedroom%20hawthorn%20camberwell%20richmond&exact=false",
            "note": "Inner-East direct train/tram corridor (Belgrave/Lilydale Line & Tram 70/75).",
        },
        {
            "name": "FB Marketplace: Clayton, Bayswater & Boronia",
            "category": "Facebook Marketplace (Live)",
            "url": "https://www.facebook.com/marketplace/melbourne/search?sortBy=distance_ascend&query=lease%20transfer%202%20bedroom%20clayton%20boronia%20bayswater&exact=false",
            "note": "Focused search for Clayton (Pakenham Line), Bayswater & Boronia (Belgrave Line).",
        },
        {
            "name": "Fairy Floss Real Estate (Facebook Group)",
            "category": "Facebook Groups (Live)",
            "url": "https://www.facebook.com/groups/fairyflossrealestate/",
            "note": "Melbourne's most active lease transfer group. Paste any post into our analyzer to verify Hawthorn transit and budget caps.",
        },
        {
            "name": "Flatmates.com.au: Whole Properties Melbourne (≤$560/wk)",
            "category": "Flatmates (Live)",
            "url": "https://flatmates.com.au/whole-properties/melbourne/max-560",
            "note": "Whole properties only (automatically filters out room shares).",
        },
        {
            "name": "Gumtree: Melbourne Lease Break / Lease Transfer Category",
            "category": "Gumtree (Live)",
            "url": "https://www.gumtree.com.au/s-property-for-rent/melbourne/lease+transfer/k0c18364l3001317",
            "note": "Full Gumtree search page with all active lease transfers in Melbourne.",
        },
    ]


def main() -> None:
    start_time = time.time()
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    db = PropertyDatabase(DATABASE_FILE)
    existing_map = load_existing_listings()

    raw_listings: List[Dict[str, Any]] = []
    errors_logged = 0

    # 1. Scrape live Gumtree lease transfers
    try:
        raw_listings.extend(scrape_gumtree_lease_transfers())
    except Exception as e:
        print(f"[Warn] Gumtree scraper error: {e}")
        errors_logged += 1

    # 2. Scrape live Flatmates Whole Properties
    try:
        raw_listings.extend(scrape_flatmates_whole_properties(max_pages=3))
    except Exception as e:
        print(f"[Warn] Flatmates scraper error: {e}")
        errors_logged += 1

    # 3. Scrape live Reddit lease transfers
    try:
        raw_listings.extend(scrape_reddit_lease_transfers())
    except Exception as e:
        print(f"[Warn] Reddit scraper error: {e}")
        errors_logged += 1

    # 4. Ingest live aligned Facebook Marketplace lease transfer listings
    try:
        raw_listings.extend(scrape_facebook_marketplace_aligned())
    except Exception as e:
        print(f"[Warn] Facebook Marketplace scraper error: {e}")
        errors_logged += 1

    # Ingest existing listings if raw scrape yields fewer items (safety guard)
    if not raw_listings and existing_map:
        print("[Info] Preserving existing listings from backup/state")
        raw_listings.extend(list(existing_map.values()))

    # Process and score raw listings
    processed_properties: List[Property] = []
    seen_ids = set()

    for raw in raw_listings:
        enriched = score_and_classify_listing(raw)

        # Exclude non-Melbourne / interstate listings (e.g. Canberra, Sydney, NSW, ACT)
        if is_outside_melbourne(enriched.get("address", ""), enriched.get("title", ""), enriched.get("description", ""), enriched.get("suburb", "")):
            continue

        # Exclude Student Only Accommodation & Rooming Houses
        if enriched.get("is_student_only"):
            continue

        # Exclude missing prices or sub-$200 listings
        weekly_rent = enriched.get("weekly_rent")
        if weekly_rent is None or weekly_rent < 200:
            continue
        if (enriched.get("title") or "").strip().lower() in ("lease listing", "wanted:"):
            continue

        # Enforce freshness cutoffs: 15 days for lease transfers, 10 days for normal listings
        age_days = get_listing_age_days(enriched.get("listed_at", ""))
        if enriched.get("is_lease_transfer"):
            if age_days > 15.0:
                continue
        else:
            if age_days > 10.0:
                continue

        # Convert to unified Property model
        prop_obj = Property.from_legacy(enriched)
        # Apply 100-point explainable scoring engine
        prop_obj = score_property_v2(prop_obj)

        processed_properties.append(prop_obj)
        seen_ids.add(prop_obj.property_id)
        seen_ids.add(prop_obj.source_listing_id)

    # Cross-source duplicate detection
    deduped_properties, flagged_duplicates = deduplicate_properties(processed_properties)

    # Freshness and lifecycle tracking
    updated_catalog, freshness_stats = update_catalog_freshness(
        catalog=deduped_properties,
        current_run_ids=seen_ids,
        verify_sample_size=0,
    )

    # Persist into relational SQLite database
    new_count = 0
    updated_count = 0
    for prop in updated_catalog:
        is_new = db.upsert_property(prop)
        if is_new:
            new_count += 1
        else:
            updated_count += 1

    # Log execution telemetry
    duration = time.time() - start_time
    exec_log = ScraperExecutionLog(
        run_timestamp=datetime.now(timezone.utc).isoformat(),
        source="all",
        listings_scanned=len(raw_listings),
        listings_new=new_count,
        listings_updated=updated_count,
        errors_logged=errors_logged,
        duration_seconds=round(duration, 2),
        status="success" if errors_logged == 0 else "partial",
    )
    db.log_execution(exec_log)

    # Export to docs/data/listings.json for static site deployment
    portal_links = build_portal_quick_links()
    export_payload = db.export_to_listings_json(
        output_file=LISTINGS_FILE,
        criteria=USER_CRITERIA,
        portal_links=portal_links,
    )

    all_listings = export_payload.get("listings", [])
    strict_matches = [x for x in all_listings if x.get("pass_strict_filter")]
    now_iso = export_payload.get("last_updated", "")

    # Generate daily digest Markdown
    digest_lines = [
        f"# Melbourne Rental & Lease Transfer Digest ({now_iso[:10]})",
        "",
        f"- **Decision Goal**: `Dec 3, 2026` (Current contract ends `Jan 10, 2027`)",
        f"- **Move-In Window**: `Dec 5, 2026 – Jan 15, 2027`",
        f"- **Budget Cap**: `≤ $525/wk` Unfurnished | `≤ $560/wk` Furnished",
        f"- **Scanned Live Ads**: `{len(all_listings)}` | **Strict Hawthorn Matches**: `{len(strict_matches)}`",
        "",
        "## Top Matching Entire Properties (Direct Train/Tram to Hawthorn)",
        "",
        "| Score | Rent | Type | Suburb & Direct Transit | Station Proximity | Move-In | Direct Link |",
        "| :---: | :---: | :---: | :--- | :--- | :---: | :---: |",
    ]
    for item in strict_matches[:20]:
        rent_badge = f"${item['weekly_rent']}/wk ({'Furn' if item['is_furnished'] else 'Unfurn'})"
        bed_badge = f"{item['bedrooms']}BHK" + (" 🔄 Lease Transfer" if item["is_lease_transfer"] else "")
        transit = f"**{item['suburb']}** ({item['commute_mode']}, ~{item['commute_mins']}m)"
        station = item.get("station_distance_display", "Near station")
        score_val = item.get("match_score", 0)
        digest_lines.append(
            f"| **{score_val}%** | {rent_badge} | {bed_badge} | {transit} | {station} | {item.get('availability_display', 'Flexible')} | [Open Property]({item['url']}) |"
        )

    DIGEST_FILE.write_text("\n".join(digest_lines) + "\n", encoding="utf-8")
    print(
        f"[Done V2] Processed {len(all_listings)} properties ({len(strict_matches)} strict Hawthorn matches) saved to {DATABASE_FILE} and {LISTINGS_FILE}"
    )


if __name__ == "__main__":
    main()
