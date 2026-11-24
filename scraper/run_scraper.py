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
from .ai_agent import evaluate_property_ai
from .sources import (
    scrape_gumtree_lease_transfers,
    scrape_flatmates_whole_properties,
    scrape_reddit_lease_transfers,
    scrape_facebook_marketplace_aligned,
    collect_all_agency_sources,
    get_listing_age_days,
    is_outside_melbourne,
)

ROOT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT_DIR / "docs" / "data"
LISTINGS_FILE = DATA_DIR / "listings.json"
DIGEST_FILE = DATA_DIR / "digest.md"
DATABASE_FILE = DATA_DIR / "database.sqlite"
DECISIONS_FILE = DATA_DIR / "user_decisions.json"


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
            "url": "https://www.domain.com.au/rent/?suburb=melbourne-vic-3000,east-melbourne-vic-3002,richmond-vic-3121,burnley-vic-3121,hawthorn-vic-3122,hawthorn-east-vic-3123,camberwell-vic-3124,canterbury-vic-3126,surrey-hills-vic-3127,mont-albert-vic-3127,box-hill-vic-3128,blackburn-vic-3130,nunawading-vic-3131,mitcham-vic-3132,ringwood-vic-3134,heathmont-vic-3135,bayswater-vic-3153,boronia-vic-3155,ferntree-gully-vic-3156,upper-ferntree-gully-vic-3156,upwey-vic-3158,tecoma-vic-3160,belgrave-vic-3160,ringwood-east-vic-3135,croydon-vic-3136,mooroolbark-vic-3138,lilydale-vic-3140&bedrooms=1-3&price=0-600&excludedeposittaken=1&sort=dateupdated-desc",
            "note": "Complete Belgrave and Lilydale line plus Inner-East corridor search under $600/wk.",
        },
        {
            "name": "Domain: Hawthorn, Box Hill, Mitcham, Ringwood, Bayswater, Boronia (≤$560/wk)",
            "category": "Domain.com.au (Live)",
            "url": "https://www.domain.com.au/rent/?suburb=hawthorn-vic-3122,hawthorn-east-vic-3123,camberwell-vic-3124,kew-vic-3101,richmond-vic-3121,surrey-hills-vic-3127,box-hill-vic-3128,mitcham-vic-3132,ringwood-vic-3134,bayswater-vic-3153,boronia-vic-3155&bedrooms=1-2&price=0-560&excludedeposittaken=1&sort=dateupdated-desc",
            "note": "Live 1-2BR listings up to $560/wk across Hawthorn, Box Hill, Mitcham, Ringwood, Bayswater, and Boronia.",
        },
        {
            "name": "Domain: Mitcham, Ringwood, Bayswater & Boronia Direct Search (≤$560/wk)",
            "category": "Domain.com.au (Live)",
            "url": "https://www.domain.com.au/rent/?suburb=mitcham-vic-3132,ringwood-vic-3134,bayswater-vic-3153,boronia-vic-3155&bedrooms=1-2&price=0-560&excludedeposittaken=1&sort=dateupdated-desc",
            "note": "Focused search for Mitcham, Ringwood, Bayswater, and Boronia on the direct Belgrave/Lilydale train line.",
        },
        {
            "name": "Domain: 2+ BHK Furnished along Corridor (≤$625 Furnished)",
            "category": "Domain.com.au (Live)",
            "url": "https://www.domain.com.au/rent/?suburb=hawthorn-vic-3122,hawthorn-east-vic-3123,camberwell-vic-3124,kew-vic-3101,richmond-vic-3121,box-hill-vic-3128,mitcham-vic-3132,ringwood-vic-3134,bayswater-vic-3153,boronia-vic-3155,melbourne-vic-3000&bedrooms=2-3&price=0-625&features=furnished&excludedeposittaken=1&sort=dateupdated-desc",
            "note": "Furnished 2+ BR properties up to $625/wk on direct train/tram lines to Hawthorn.",
        },
        {
            "name": "Realestate.com.au: 2BR Hawthorn, Mitcham, Ringwood, Bayswater, Boronia ≤$560/wk",
            "category": "Realestate.com.au (Live)",
            "url": "https://www.realestate.com.au/rent/with-2-bedrooms-between-0-560-in-hawthorn,+vic+3122%3b+hawthorn+east,+vic+3123%3b+camberwell,+vic+3124%3b+box+hill,+vic+3128%3b+mitcham,+vic+3132%3b+ringwood,+vic+3134%3b+bayswater,+vic+3153%3b+boronia,+vic+3155/list-1?activeSort=list-date&includeSurrounding=false",
            "note": "Exact suburb matches on the Belgrave & Lilydale lines.",
        },
        {
            "name": "Barry Plant: Official Victorian Rental Directory",
            "category": "Direct Agency (Live)",
            "url": "https://www.barryplant.com.au/rental-properties/properties-rent/",
            "note": "Direct agency listings from Barry Plant offices across Whitehorse, Boroondara, Maroondah & Melbourne.",
        },
        {
            "name": "Ray White: Victorian Rental Search",
            "category": "Direct Agency (Live)",
            "url": "https://www.raywhite.com/listing",
            "note": "Direct agency listings from Ray White offices across Melbourne & Eastern corridor.",
        },
        {
            "name": "Nelson Alexander: Properties for Lease",
            "category": "Direct Agency (Live)",
            "url": "https://www.nelsonalexander.com.au/rent/properties-for-lease/",
            "note": "Direct agency rentals across Hawthorn, Kew, Richmond, Fitzroy & Inner Melbourne.",
        },
        {
            "name": "Jellis Craig: Inner-East & Whitehorse Rentals (≤$625/wk)",
            "category": "Direct Agency (Live)",
            "url": "https://www.jelliscraig.com.au/rent/list?suburb=Hawthorn;Hawthorn%20East;Richmond;Camberwell;Kew;Surrey%20Hills;Box%20Hill;Blackburn;Mitcham;Ringwood&max_price=625",
            "note": "Direct Jellis Craig rentals filtered for the Hawthorn transit corridor.",
        },
        {
            "name": "Woodards: Melbourne Rental Properties",
            "category": "Direct Agency (Live)",
            "url": "https://www.woodards.com.au/property/?category=Rent",
            "note": "Direct Woodards rental listings across Camberwell, Hawthorn, Blackburn & Inner Melbourne.",
        },
        {
            "name": "Harcourts: Victoria & Eastern Melbourne Rentals (≤$650/wk)",
            "category": "Direct Agency (Live)",
            "url": "https://harcourts.net/au/listings/rent?search=VIC&maxPrice=650",
            "note": "Direct Harcourts rental listings across Hawthorn, Box Hill, Ringwood, Boronia & Victoria.",
        },
        {
            "name": "Buxton: Properties for Lease",
            "category": "Direct Agency (Live)",
            "url": "https://buxton.com.au/properties-for-lease/",
            "note": "Direct Buxton rental listings across Box Hill, Camberwell, Glen Iris, Malvern & Melbourne.",
        },
        {
            "name": "Fletchers: Eastern Suburbs Properties for Lease",
            "category": "Direct Agency (Live)",
            "url": "https://www.fletchers.net.au/properties-for-lease",
            "note": "Direct Fletchers rental properties across Canterbury, Balwyn, Blackburn, Mitcham & Ringwood.",
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
            "name": "FB Marketplace: Ringwood, Mitcham, Bayswater & Boronia",
            "category": "Facebook Marketplace (Live)",
            "url": "https://www.facebook.com/marketplace/melbourne/search?sortBy=distance_ascend&query=lease%20transfer%202%20bedroom%20ringwood%20mitcham%20bayswater%20boronia&exact=false",
            "note": "Focused search for Ringwood, Mitcham, Bayswater & Boronia (Belgrave/Lilydale Line direct to Hawthorn).",
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
    db = PropertyDatabase(DATABASE_FILE)
    # Sync persistent user decisions (skips, shortlists, inspections) into SQLite
    decision_stats = db.sync_user_decisions(DECISIONS_FILE)
    if decision_stats["synced"] or decision_stats["skipped_properties"]:
        print(f"[User Decisions] Synced {decision_stats['synced']} user actions, {decision_stats['skipped_properties']} properties marked skipped.")
    skipped_ident = db.get_skipped_identifiers()
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

    # 5. Collect from all 10 Direct Real Estate Agency Adapters (Priority 1 & Priority 2)
    agency_properties, agency_health_map, agency_exec_logs = collect_all_agency_sources()
    for a_log in agency_exec_logs:
        db.log_execution(a_log)
        if a_log.status != "success":
            errors_logged += a_log.errors_logged

    # Ingest existing listings if raw scrape yields fewer items (safety guard)
    if not raw_listings and not agency_properties and existing_map:
        print("[Info] Preserving existing listings from backup/state")
        raw_listings.extend(list(existing_map.values()))

    # Process and score raw listings
    processed_properties: List[Property] = []
    seen_ids = set()

    for prop_obj in agency_properties:
        if prop_obj.property_id in skipped_ident["ids"]:
            continue
        if prop_obj.address and any(a in prop_obj.address.lower() for a in skipped_ident["addresses"]):
            continue
        if prop_obj.source_url and prop_obj.source_url.lower() in skipped_ident["urls"]:
            continue
        processed_properties.append(prop_obj)
        seen_ids.add(prop_obj.property_id)
        seen_ids.add(prop_obj.source_listing_id)

    for raw in raw_listings:
        enriched = score_and_classify_listing(raw)
        prop_id_check = enriched.get("id") or enriched.get("property_id") or ""
        raw_addr = (enriched.get("address") or "").lower()
        raw_url = (enriched.get("url") or "").lower()
        if prop_id_check in skipped_ident["ids"]:
            continue
        if raw_addr and any(a in raw_addr for a in skipped_ident["addresses"]):
            continue
        if raw_url and raw_url in skipped_ident["urls"]:
            continue

        # Exclude non-Melbourne / interstate listings (e.g. Canberra, Sydney, NSW, ACT)
        if is_outside_melbourne(enriched.get("address", ""), enriched.get("title", ""), enriched.get("description", ""), enriched.get("suburb", "")):
            continue

        # Exclude Student Only Accommodation & Rooming Houses
        if enriched.get("is_student_only"):
            continue

        # Exclude studios, 1BR listings, and sharehouses (exclusively 2+ bedrooms entire properties)
        if (enriched.get("property_type") or "").lower() == "studio":
            continue
        beds = enriched.get("bedrooms")
        if beds is None or beds < 2:
            continue
        if enriched.get("is_sharehouse") or not enriched.get("is_entire_property", True):
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

    # Attribute merged cross-source duplicates back to source_health telemetry
    for prop in deduped_properties:
        prov = prop.source_provenance or prop.sources or []
        if len(prov) > 1:
            for entry in prov[1:]:
                s_name = entry.get("source_name") or entry.get("source")
                if s_name and s_name in agency_health_map:
                    agency_health_map[s_name]["duplicates_count"] = (
                        int(agency_health_map[s_name].get("duplicates_count", 0)) + 1
                    )

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
        listings_scanned=len(raw_listings) + sum(h.get("listings_discovered", 0) for h in agency_health_map.values()),
        listings_new=new_count,
        listings_updated=updated_count,
        errors_logged=errors_logged,
        duration_seconds=round(duration, 2),
        status="success" if errors_logged == 0 else "partial",
    )
    db.log_execution(exec_log)

    # Sync user decisions into DB before re-evaluation and export
    db.sync_user_decisions(DECISIONS_FILE)

    # Re-evaluate all existing stored listings against canonical 2+ BR eligibility
    reeval_stats = db.reevaluate_stored_listings()
    print(f"[Database] Re-evaluated stored listings: {reeval_stats['active']} active (2+ BR), {reeval_stats['ineligible']} historical/ineligible preserved for audit.")

    # Run AI Evaluator Agent on all active eligible properties
    print("[AI Agent] Running AI Evaluator Agent to assess personal lifestyle & WFH fit...")
    active_props = db.list_properties(status="active", limit=1000)
    for p in active_props:
        p.ai_evaluation = evaluate_property_ai(p)
        db.upsert_property(p)

    # Export to docs/data/listings.json for static site deployment
    portal_links = build_portal_quick_links()
    export_payload = db.export_to_listings_json(
        output_file=LISTINGS_FILE,
        criteria=USER_CRITERIA,
        portal_links=portal_links,
        source_health=agency_health_map,
    )

    all_listings = export_payload.get("listings", [])
    strict_matches = [x for x in all_listings if x.get("pass_strict_filter")]
    now_iso = export_payload.get("last_updated", "")

    # Generate daily digest Markdown
    digest_lines = [
        f"# Melbourne Rental & Lease Transfer Digest ({now_iso[:10]})",
        "",
        f"- **Requirement**: `Entire properties · 2+ bedrooms · No sharehouses`",
        f"- **Decision Goal**: `Dec 3, 2026` (Current contract ends `Jan 10, 2027`)",
        f"- **Move-In Window**: `Dec 5, 2026 – Jan 15, 2027`",
        f"- **Budget Cap**: `≤ $560/wk` Unfurnished | `≤ $625/wk` Furnished",
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

    # -----------------------------------------------------------------
    # AI Evaluator Agent Verdict Section
    # -----------------------------------------------------------------
    ai_candidates = [x for x in strict_matches if x.get("ai_evaluation")]
    # Sort by AI lifestyle match score
    ai_candidates.sort(key=lambda x: (x.get("ai_evaluation", {}).get("match_score", 0)), reverse=True)

    if ai_candidates:
        digest_lines.extend([
            "",
            "## 🤖 AI Evaluator Agent – Lifestyle & WFH Compatibility",
            "",
            "> [!NOTE]",
            "> Evaluated for solo occupant: 2nd bedroom dedicated as quiet WFH office, split-system heating/cooling, street noise levels, and kitchen/laundry essentials.",
            "",
            "| AI Verdict | Lifestyle | Rent | Suburb | WFH & Second Room | Climate & Noise | Link |",
            "| :--- | :---: | :---: | :--- | :--- | :--- | :---: |",
        ])

        for item in ai_candidates[:12]:
            ai = item.get("ai_evaluation", {})
            fit = ai.get("lifestyle_fit", {})
            badge = ai.get("badge_label", "🎯 Top Match")
            ai_score = ai.get("match_score", item.get("match_score", 0))
            rent_str = f"${item['weekly_rent']}/wk"
            wfh = fit.get("wfh_suitability", "2BR Layout")
            climate_noise = f"{fit.get('climate_comfort', 'Standard')}; {fit.get('noise_level', 'Quiet')}"
            digest_lines.append(
                f"| **{badge}** | **{ai_score}/100** | {rent_str} | **{item['suburb']}** | {wfh} | {climate_noise} | [Open Listing]({item['url']}) |"
            )

        # Detailed breakdown of top 3 AI picks
        digest_lines.extend([
            "",
            "### 🎯 Top AI Advisor Property Deep-Dives",
            "",
        ])
        for idx, item in enumerate(ai_candidates[:3], 1):
            ai = item.get("ai_evaluation", {})
            strengths = ai.get("strengths", [])
            cautions = ai.get("cautions", [])
            tips = ai.get("inspection_tips", [])
            digest_lines.extend([
                f"#### {idx}. {item.get('address', item['suburb'])} – {ai.get('badge_label', 'Top Match')} ({ai.get('match_score', item.get('match_score', 0))}/100)",
                f"- **Rent**: `${item['weekly_rent']}/wk` ({'Furnished' if item['is_furnished'] else 'Unfurnished'}) · **Commute**: {item.get('commute_mode', 'Train')} to Hawthorn (~{item.get('commute_mins', 12)} mins)",
                f"- **Agent Appraisal**: *\"{ai.get('one_liner', 'Strong match for 2BR solo occupant.')}\"*",
                "- **Key Lifestyle Fits**:",
            ])
            for s in strengths[:3]:
                digest_lines.append(f"  - ✅ {s}")
            if cautions:
                digest_lines.append("- **Points of Caution / Tradeoffs**:")
                for c in cautions[:2]:
                    digest_lines.append(f"  - ⚠️ {c}")
            if tips:
                digest_lines.append("- **Inspection Advice**:")
                for t in tips[:2]:
                    digest_lines.append(f"  - 📋 {t}")
            digest_lines.append(f"- **Listing**: [View Property on {item.get('source', 'Web')}]({item['url']})\n")

    DIGEST_FILE.write_text("\n".join(digest_lines) + "\n", encoding="utf-8")
    print(
        f"[Done V2] Processed {len(all_listings)} properties ({len(strict_matches)} strict Hawthorn matches) saved to {DATABASE_FILE} and {LISTINGS_FILE}"
    )


if __name__ == "__main__":
    main()
