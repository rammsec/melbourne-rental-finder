#!/usr/bin/env python3
"""
Main CLI & GitHub Actions Runner for Melbourne Lease Transfer & Rental Finder.

Only scrapes and publishes 100% genuine, active listings with direct property URLs:
- Live Gumtree Lease Transfers & Rentals (Direct /web/listing/property-for-rent/<ad_id> links)
- Live Flatmates Whole Properties (Direct /whole-property-melbourne-...-P<id> links)
- Live Reddit Lease Transfer posts (Direct reddit.com/r/melbourne/comments/... links)

Every listing is strictly scored against:
- Solo occupancy (2BHK preferred, entire place only, zero sharehouses)
- Unfurnished <= $525/wk | Furnished <= $560/wk
- Direct train or tram commute to Hawthorn (Belgrave/Lilydale/Alamein line, Tram 70/75/16)
- Move-in window Dec 5 – Dec 30, 2026
"""

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, List

from .config import USER_CRITERIA, HAWTHORN_DIRECT_SUBURBS
from .scorer import score_and_classify_listing
from .sources import (
    scrape_gumtree_lease_transfers,
    scrape_flatmates_whole_properties,
    scrape_reddit_lease_transfers,
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
    Direct pre-filtered search portals tailored for Hawthorn & direct transit corridors.
    """
    return [
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
            "name": "FB Marketplace: Clayton, Bayswater, Boronia & Hawthorn (≤$560)",
            "category": "Facebook Marketplace (Live)",
            "url": "https://www.facebook.com/marketplace/melbourne/search?query=lease%20transfer%20clayton%20bayswater%20boronia%20hawthorn&maxPrice=560",
            "note": "Opens Facebook Marketplace under your login. Copy any post text and paste into the 'FB Post Analyzer' tab to score and save it!",
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
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    existing_map = load_existing_listings()

    raw_listings: List[Dict[str, Any]] = []

    # 1. Scrape live Gumtree lease transfers (100% real ads with direct URLs)
    raw_listings.extend(scrape_gumtree_lease_transfers())

    # 2. Scrape live Flatmates Whole Properties (100% real ads with direct URLs)
    raw_listings.extend(scrape_flatmates_whole_properties(max_pages=3))

    # 3. Scrape live Reddit lease transfers (when accessible)
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

    # Sort: strict matches first, then lease transfers, then score descending, then rent
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

    # Generate daily digest Markdown
    digest_lines = [
        f"# Melbourne Rental & Lease Transfer Digest ({now_iso[:10]})",
        "",
        f"- **Decision Goal**: `Dec 3, 2026` (Current contract ends `Jan 10, 2027`)",
        f"- **Move-In Window**: `Dec 5 – Dec 30, 2026`",
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
        digest_lines.append(
            f"| **{item['match_score']}%** | {rent_badge} | {bed_badge} | {transit} | {station} | {item['availability_display']} | [Open Property]({item['url']}) |"
        )

    DIGEST_FILE.write_text("\n".join(digest_lines) + "\n", encoding="utf-8")
    print(
        f"[Done] Wrote {len(all_listings)} 100% real listings ({len(strict_matches)} strict Hawthorn matches) to {LISTINGS_FILE}"
    )


if __name__ == "__main__":
    main()
