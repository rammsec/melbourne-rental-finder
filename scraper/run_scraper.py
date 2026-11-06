#!/usr/bin/env python3
"""
Main CLI & GitHub Actions Runner for Melbourne Lease Transfer & Rental Finder.

Usage:
    python3 -m scraper.run_scraper

What it does:
1. Scrapes live whole-property & lease-transfer listings from Flatmates.com.au,
   Domain.com.au, and Reddit (plus merges existing tracked listings & Hawthorn corridor feeds).
2. Runs every listing through the strict criteria & Hawthorn commute scoring engine:
   - Unfurnished <= $525/wk, Furnished <= $560/wk
   - Entire property only (2BHK preferred, no sharehouses)
   - Direct train (Belgrave/Lilydale/Alamein) or direct tram (70/75/16) to Hawthorn
   - Move-in window Dec 5 – Dec 30, 2026 (before Dec 3 decision deadline / Jan 10 contract end)
3. Writes `docs/data/listings.json` for the live GitHub Pages dashboard and `docs/data/digest.md`
   for daily GitHub Actions job summaries.
"""

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, List

from .config import USER_CRITERIA, HAWTHORN_DIRECT_SUBURBS
from .scorer import score_and_classify_listing
from .sources import (
    scrape_flatmates_whole_properties,
    scrape_domain_corridor,
    scrape_reddit_lease_transfers,
    get_curated_hawthorn_corridor_listings,
)

ROOT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT_DIR / "docs" / "data"
LISTINGS_FILE = DATA_DIR / "listings.json"
DIGEST_FILE = DATA_DIR / "digest.md"


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
    Pre-filtered search deep-links for one-click checks on FB Marketplace, Fairy Floss,
    Domain, Realestate.com.au, Gumtree, and Flatmates tailored to the exact criteria.
    """
    return [
        {
            "name": "FB Marketplace: 2BR Lease Transfers (Hawthorn / Inner East ≤$560)",
            "category": "Facebook Marketplace",
            "url": "https://www.facebook.com/marketplace/melbourne/search?query=lease%20transfer%202%20bedroom%20hawthorn%20camberwell%20richmond&maxPrice=560",
            "note": "Filtered for lease transfers up to $560/wk in Hawthorn & surrounds",
        },
        {
            "name": "FB Marketplace: Direct Hawthorn / Kew / Box Hill Rentals (≤$525)",
            "category": "Facebook Marketplace",
            "url": "https://www.facebook.com/marketplace/melbourne/propertyrentals?maxPrice=525&minBedrooms=2&exact=false",
            "note": "2+ Bedroom entire property rentals up to $525/wk",
        },
        {
            "name": "Domain: 2BHK in Hawthorn + Direct Train/Tram Suburbs (≤$525 Unfurnished)",
            "category": "Domain.com.au",
            "url": "https://www.domain.com.au/rent/?suburb=hawthorn-vic-3122,hawthorn-east-vic-3123,camberwell-vic-3124,kew-vic-3101,richmond-vic-3121,surrey-hills-vic-3127,box-hill-vic-3128,burwood-vic-3125,malvern-vic-3144&bedrooms=2&price=0-525&excludedeposittaken=1&sort=dateupdated-desc",
            "note": "Sorted newest first across direct Belgrave/Lilydale/Alamein + Tram 70/75/16 suburbs",
        },
        {
            "name": "Domain: 1–2BHK Furnished along Hawthorn Corridor (≤$560 Furnished)",
            "category": "Domain.com.au",
            "url": "https://www.domain.com.au/rent/?suburb=hawthorn-vic-3122,hawthorn-east-vic-3123,camberwell-vic-3124,kew-vic-3101,richmond-vic-3121,box-hill-vic-3128,malvern-vic-3144,melbourne-vic-3000&bedrooms=1-2&price=0-560&features=furnished&excludedeposittaken=1&sort=dateupdated-desc",
            "note": "Furnished filter active up to $560/wk",
        },
        {
            "name": "Realestate.com.au: Hawthorn & Surrounds 2BR ≤$525/wk (Newest)",
            "category": "Realestate.com.au",
            "url": "https://www.realestate.com.au/rent/with-2-bedrooms-between-0-525-in-hawthorn,+vic+3122%3b+hawthorn+east,+vic+3123%3b+camberwell,+vic+3124%3b+kew,+vic+3101%3b+box+hill,+vic+3128%3b+surrey+hills,+vic+3127/list-1?activeSort=list-date&includeSurrounding=false",
            "note": "Exact suburbs on direct Hawthorn train/tram lines",
        },
        {
            "name": "Flatmates.com.au: Whole Properties & 1-Beds Melbourne (≤$560/wk)",
            "category": "Flatmates (Whole Properties)",
            "url": "https://flatmates.com.au/whole-properties/melbourne/max-560",
            "note": "Whole properties only (excludes room-shares)",
        },
        {
            "name": "Gumtree: Melbourne Lease Break / Lease Transfer (Entire Property)",
            "category": "Gumtree",
            "url": "https://www.gumtree.com.au/s-property-for-rent/melbourne/lease+transfer/k0c18364l3001317",
            "note": "Direct lease break search across Greater Melbourne",
        },
    ]


def main() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    existing_map = load_existing_listings()

    raw_listings: List[Dict[str, Any]] = []
    # 1. Curated Hawthorn corridor lease transfers & baseline benchmarks
    raw_listings.extend(get_curated_hawthorn_corridor_listings())
    # 2. Live Flatmates Whole Properties & 1-Beds scraper
    raw_listings.extend(scrape_flatmates_whole_properties(max_pages=2))
    # 3. Live Domain scraper (when accessible)
    raw_listings.extend(scrape_domain_corridor(max_suburbs=8))
    # 4. Live Reddit scraper (when accessible)
    raw_listings.extend(scrape_reddit_lease_transfers())

    processed_map: Dict[str, Dict[str, Any]] = {}
    new_matches_count = 0

    for raw in raw_listings:
        enriched = score_and_classify_listing(raw)
        lid = enriched["id"]
        if lid not in existing_map:
            enriched["is_new"] = True
            if enriched["pass_strict_filter"]:
                new_matches_count += 1
        else:
            enriched["is_new"] = existing_map[lid].get("is_new", False)
        processed_map[lid] = enriched

    # Sort: strict matches first, then by match_score descending, then by weekly_rent ascending
    all_listings = list(processed_map.values())
    all_listings.sort(
        key=lambda x: (
            1 if x.get("pass_strict_filter") else 0,
            1 if x.get("is_lease_transfer") else 0,
            x.get("match_score", 0),
            -(x.get("weekly_rent") or 9999),
        ),
        reverse=True,
    )

    strict_matches = [x for x in all_listings if x.get("pass_strict_filter")]
    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    payload = {
        "last_updated": now_iso,
        "criteria": USER_CRITERIA,
        "stats": {
            "total_scanned": len(all_listings),
            "strict_matches": len(strict_matches),
            "lease_transfers": sum(1 for x in strict_matches if x.get("is_lease_transfer")),
            "two_bhk_matches": sum(1 for x in strict_matches if x.get("bedrooms") == 2),
            "new_today": new_matches_count,
        },
        "portal_quick_links": build_portal_quick_links(),
        "hawthorn_corridor_suburbs": HAWTHORN_DIRECT_SUBURBS,
        "listings": all_listings,
    }

    LISTINGS_FILE.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    # Also write a Markdown digest for GitHub Actions Job Summary
    digest_lines = [
        f"# Melbourne Rental & Lease Transfer Digest ({now_iso[:10]})",
        "",
        f"- **Target Decision Deadline**: `Dec 3, 2026` (Current contract ends `Jan 10, 2027`)",
        f"- **Target Move-In Window**: `Dec 5 – Dec 30, 2026`",
        f"- **Budget Cap**: `≤ $525/wk` (Unfurnished) | `≤ $560/wk` (Furnished)",
        f"- **Total Listings Scanned**: `{len(all_listings)}` | **Strict Hawthorn Commute Matches**: `{len(strict_matches)}`",
        "",
        "## Top Matching Entire-Property Listings (Direct to Hawthorn)",
        "",
        "| Score | Rent | Type | Suburb & Transit to Hawthorn | Move-In | Link |",
        "| :---: | :---: | :---: | :--- | :---: | :---: |",
    ]
    for item in strict_matches[:15]:
        rent_badge = f"${item['weekly_rent']}/wk ({'Furn' if item['is_furnished'] else 'Unfurn'})"
        bed_badge = f"{item['bedrooms']}BHK" + (" 🔄 Lease Transfer" if item["is_lease_transfer"] else "")
        transit = f"**{item['suburb']}** ({item['commute_mode']}, ~{item['commute_mins']}m)"
        digest_lines.append(
            f"| **{item['match_score']}%** | {rent_badge} | {bed_badge} | {transit} | {item['availability_display']} | [View]({item['url']}) |"
        )

    DIGEST_FILE.write_text("\n".join(digest_lines) + "\n", encoding="utf-8")
    print(
        f"[Done] Wrote {len(all_listings)} listings ({len(strict_matches)} strict Hawthorn matches) to {LISTINGS_FILE}"
    )


if __name__ == "__main__":
    main()
