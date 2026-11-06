"""
Criteria Evaluation & Scoring Engine for Melbourne Rental & Lease Transfer Finder.

Evaluates listings against the user's strict criteria:
1. Solo entire place ("preferred 2bhk, not sharehouse"):
   - Rejects sharehouses, flatshares, private rooms in shared houses, student-only rooms.
   - Prefers 2BR (+25 pts), accepts 1BR (+12 pts) or Studio (+5 pts).
2. Rent Budget:
   - Unfurnished: max $525/week
   - Furnished: max $560/week
   - Bonus points for being well under budget or including bills.
3. Direct Train or Tram to Hawthorn:
   - Matches suburb against HAWTHORN_DIRECT_SUBURBS (Belgrave/Lilydale/Alamein lines, Tram 70/75/16, Bus 609).
   - Scores Tier 1 (<15 min direct) highest, Tier 2 (15-29 min direct) medium, Tier 3 (30+ min direct) lower.
4. Move-in Window:
   - Target window: Dec 5, 2026 – Dec 30, 2026 (before current contract ends Jan 10, 2027; goal to secure before Dec 3).
   - Lease transfers / lease breaks get an explicit priority boost (+18 pts) because they often offer below-market rent and flexible December dates.
"""

import re
from datetime import datetime, date
from typing import Dict, Any, Optional, Tuple, List
from .config import HAWTHORN_DIRECT_SUBURBS, USER_CRITERIA


SHAREHOUSE_KEYWORDS = [
    r"\bshare\s*house\b",
    r"\bflat\s*share\b",
    r"\bhouse\s*share\b",
    r"\broom\s+for\s+rent\b",
    r"\bprivate\s+room\b",
    r"\bsingle\s+room\b",
    r"\bshared\s+bathroom\b",
    r"\bhousemates?\b",
    r"\bflatmates?\s+wanted\b",
    r"\blooking\s+for\s+a?\s*(?:new\s+)?(?:housemate|flatmate|roommate)\b",
    r"\b1\s+room\s+in\s+a\b",
    r"\broom\s+available\s+in\b",
    r"\bstudent\s+accommodation\b",
    r"\bunilodge\b",
    r"\bsha\s+student\b",
    r"\bscape\s+student\b",
    r"\byugo\b",
]

ENTIRE_PROPERTY_OVERRIDES = [
    r"\bwhole\s+property\b",
    r"\bentire\s+(?:apartment|unit|house|flat|place|property|home|townhouse)\b",
    r"\blease\s+transfer\s+(?:for\s+)?(?:entire|whole|1\s*bed|2\s*bed|one\s*bed|two\s*bed)\b",
    r"\bno\s+housemates\b",
    r"\bnot\s+a\s+share\s*house\b",
    r"\byour\s+own\s+(?:place|apartment|unit)\b",
]

LEASE_TRANSFER_KEYWORDS = [
    r"\blease\s+transfer\b",
    r"\blease\s+break\b",
    r"\bbreak\s+lease\b",
    r"\blease\s+take\s*over\b",
    r"\btake\s+over\s+(?:my|our|the)\s+lease\b",
    r"\btransferring\s+(?:my|our)\s+lease\b",
]

FURNISHED_KEYWORDS = [
    r"\bfully\s+furnished\b",
    r"\bfurnished\b",
    r"\bpartly\s+furnished\b",
    r"\bsemi[\s-]furnished\b",
    r"\bincludes?\s+furniture\b",
]

UNFURNISHED_KEYWORDS = [
    r"\bunfurnished\b",
    r"\bnot\s+furnished\b",
]


def detect_furnished(text: str) -> bool:
    """Return True if listing text indicates furnished (and not explicitly unfurnished)."""
    lower = text.lower()
    for pat in UNFURNISHED_KEYWORDS:
        if re.search(pat, lower):
            return False
    for pat in FURNISHED_KEYWORDS:
        if re.search(pat, lower):
            return True
    return False


def detect_lease_transfer(text: str) -> bool:
    """Return True if listing text mentions lease transfer / lease break / takeover."""
    lower = text.lower()
    return any(re.search(pat, lower) for pat in LEASE_TRANSFER_KEYWORDS)


def detect_sharehouse(text: str, listing_kind: str = "") -> bool:
    """
    Return True if the listing appears to be a room in a sharehouse or student-only room
    rather than an entire property.
    """
    lower = text.lower()
    if any(re.search(pat, lower) for pat in ENTIRE_PROPERTY_OVERRIDES):
        # Still reject if it says "whole property with 4 rooms" where price is per room
        if re.search(r"\bper\s+room\b|\beach\s+room\b", lower):
            return True
        return False

    for pat in SHAREHOUSE_KEYWORDS:
        if re.search(pat, lower):
            return True

    if listing_kind and listing_kind.lower() in ("room", "sharehouse", "flatshare"):
        return True

    return False


SUBURB_STATIONS: Dict[str, str] = {
    "hawthorn": "Hawthorn Station",
    "hawthorn east": "Auburn Station",
    "glenferrie": "Glenferrie Station",
    "auburn": "Auburn Station",
    "camberwell": "Camberwell Station",
    "richmond": "Richmond Station",
    "burnley": "Burnley Station",
    "east richmond": "East Richmond Station",
    "cremorne": "East Richmond Station",
    "canterbury": "Canterbury Station",
    "surrey hills": "Union Station",
    "mont albert": "Union Station",
    "box hill": "Box Hill Station",
    "box hill north": "Box Hill Station",
    "box hill south": "Box Hill Station",
    "laburnum": "Laburnum Station",
    "blackburn": "Blackburn Station",
    "nunawading": "Nunawading Station",
    "mitcham": "Mitcham Station",
    "heatherdale": "Heatherdale Station",
    "ringwood": "Ringwood Station",
    "ringwood east": "Ringwood East Station",
    "heathmont": "Heathmont Station",
    "bayswater": "Bayswater Station",
    "boronia": "Boronia Station",
    "ferntree gully": "Ferntree Gully Station",
    "croydon": "Croydon Station",
    "clayton": "Clayton Station",
    "clayton south": "Clayton Station",
    "oakleigh": "Oakleigh Station",
    "huntingdale": "Huntingdale Station",
    "burwood": "Burwood Station",
    "burwood east": "Burwood Station",
    "hartwell": "Hartwell Station",
    "riversdale": "Riversdale Station",
    "willison": "Willison Station",
    "ashburton": "Ashburton Station",
    "alamein": "Alamein Station",
    "malvern": "Malvern Station",
    "armadale": "Armadale Station",
    "toorak": "Toorak Station",
    "kooyong": "Kooyong Station",
    "caulfield": "Caulfield Station",
    "caulfield north": "Caulfield Station",
    "balaclava": "Balaclava Station",
    "south yarra": "South Yarra Station",
    "prahran": "Prahran Station",
    "windsor": "Windsor Station",
    "east melbourne": "Jolimont Station",
    "melbourne": "Flinders Street Station",
    "melbourne cbd": "Flinders Street Station",
    "cbd": "Flinders Street Station",
    "docklands": "Southern Cross Station",
    "abbotsford": "Collingwood Station",
    "collingwood": "Collingwood Station",
    "kew": "Glenferrie Station / Tram 16",
    "kew east": "Glenferrie Station / Tram 16",
    "carlton": "Melbourne Central / Tram 16",
    "st kilda": "Balaclava Station",
    "st kilda east": "Balaclava Station",
}


def extract_station_distance(suburb: str, full_text: str) -> Dict[str, Any]:
    """
    Extract or estimate distance and walking minutes to the nearest train station.
    Returns dict with station_name, distance_m, walking_mins, display, and is_explicit.
    """
    sub_clean = (suburb or "").lower().strip()
    primary_station = SUBURB_STATIONS.get(
        sub_clean,
        f"{suburb.title()} Station" if suburb and "outer" not in sub_clean else "Local Train Station"
    )

    lower = full_text.lower()

    # 1. Look for explicit metres: e.g. 350m to station, 400 metres from station
    m_m = re.search(
        r"\b(\d{2,4})\s*(?:m\b|metres\b|meters\b)\s*(?:walk\s+)?(?:to|from)?\s*(?:the\s+)?(?:([a-z\s]{3,20}?)\s+)?station",
        lower,
    )
    if m_m:
        dist_m = int(m_m.group(1))
        st_name = (
            m_m.group(2).strip().title() + " Station"
            if m_m.group(2) and len(m_m.group(2).strip()) > 3
            else primary_station
        )
        mins = max(1, round(dist_m / 80))
        return {
            "station_name": st_name,
            "distance_m": dist_m,
            "walking_mins": mins,
            "display": f"{dist_m}m to {st_name} ({mins} min walk)",
            "is_explicit": True,
        }

    # 2. Look for explicit walking minutes: e.g. 5 min walk to station, 8 minutes to train station
    m_min = re.search(
        r"\b(\d{1,2})\s*(?:min\b|mins\b|minute\b|minutes\b)\s*(?:walk\s+to|walk\s+from|to|from)\s*(?:the\s+)?(?:([a-z\s]{3,20}?)\s+)?station",
        lower,
    )
    if m_min:
        mins = int(m_min.group(1))
        dist_m = mins * 80
        st_name = (
            m_min.group(2).strip().title() + " Station"
            if m_min.group(2) and len(m_min.group(2).strip()) > 3
            else primary_station
        )
        return {
            "station_name": st_name,
            "distance_m": dist_m,
            "walking_mins": mins,
            "display": f"~{dist_m}m to {st_name} ({mins} min walk)",
            "is_explicit": True,
        }

    # 3. Direct adjacency keywords
    if any(k in lower for k in ["opposite station", "across from station", "next to station", "steps from station", "at the station"]):
        return {
            "station_name": primary_station,
            "distance_m": 120,
            "walking_mins": 2,
            "display": f"~120m to {primary_station} (2 min walk)",
            "is_explicit": True,
        }

    if "short walk to station" in lower or "walk to train" in lower:
        return {
            "station_name": primary_station,
            "distance_m": 350,
            "walking_mins": 4,
            "display": f"~350m to {primary_station} (4 min walk)",
            "is_explicit": True,
        }

    # 4. Standard rental hub estimate for the suburb
    est_m = 450
    est_mins = 6
    return {
        "station_name": primary_station,
        "distance_m": est_m,
        "walking_mins": est_mins,
        "display": f"~{est_m}m to {primary_station} (~{est_mins} min walk)",
        "is_explicit": False,
    }


def extract_suburb_info(address: str, title: str = "") -> Tuple[str, Optional[Dict[str, Any]]]:
    """
    Match suburb name from the listing's address against HAWTHORN_DIRECT_SUBURBS.
    Avoids false-matching generic ', Melbourne' suffixes on outer-suburb addresses.
    Returns (normalized_suburb_display, commute_info_dict_or_None).
    """
    # Strip trailing ", Melbourne" or "Melbourne, VIC" unless the primary suburb itself is Melbourne CBD (3000)
    parts = [p.strip() for p in address.split(",") if p.strip()]
    primary_suburb_candidate = parts[0].lower() if parts else address.lower()

    # Check if address has a 3xxx postcode
    m_pc = re.search(r"\b(3\d{3})\b", f"{address} {title}")
    postcode_found = m_pc.group(1) if m_pc else ""

    # If the primary part before comma is a specific suburb (not "melbourne"), match against our dictionary
    sorted_suburbs = sorted(
        [k for k in HAWTHORN_DIRECT_SUBURBS.keys() if k != "melbourne"],
        key=len,
        reverse=True,
    )

    # First check the primary address segment (e.g. "Box Hill, Melbourne" or "Campbell Rd, Hawthorn East")
    addr_without_city_suffix = re.sub(r",\s*melbourne\b", "", address.lower())
    for sub in sorted_suburbs:
        if re.search(r"\b" + re.escape(sub) + r"\b", addr_without_city_suffix):
            return sub.title(), HAWTHORN_DIRECT_SUBURBS[sub]

    # Check if primary suburb is genuinely Melbourne CBD (3000)
    if primary_suburb_candidate in ("melbourne", "melbourne cbd", "cbd") or postcode_found == "3000":
        return "Melbourne CBD", HAWTHORN_DIRECT_SUBURBS["melbourne"]

    # Check title if address didn't have suburb
    for sub in sorted_suburbs:
        if re.search(r"\b" + re.escape(sub) + r"\b", title.lower()):
            return sub.title(), HAWTHORN_DIRECT_SUBURBS[sub]

    # Fallback: non-corurb outer suburb (e.g., Truganina, Clyde, Tarneit)
    fallback_name = parts[0].title() if parts else "Outer Melbourne"
    return fallback_name, None


def parse_price_weekly(price_text: str) -> Optional[int]:
    """
    Parse weekly rent in AUD from strings like '$510', '$520/wk', '$2,200 pcm', etc.
    """
    if not price_text:
        return None
    clean = price_text.replace(",", "").lower()

    # Check if per calendar month (pcm / per month) -> convert to weekly
    m_pcm = re.search(r"\$\s*(\d{4})\s*(?:pcm|p\.c\.m|per\s+month|/month|/mth)", clean)
    if m_pcm:
        monthly = int(m_pcm.group(1))
        return round(monthly * 12 / 52)

    # Standard weekly price ($250 - $1200)
    m_wk = re.search(r"\$\s*(\d{3,4})", clean)
    if m_wk:
        val = int(m_wk.group(1))
        if val > 1400:
            # Likely monthly figure cited without 'pcm'
            return round(val * 12 / 52)
        return val
    return None


def parse_availability(avail_text: str, full_text: str = "") -> Tuple[str, str]:
    """
    Evaluate availability string and return (display_date, window_fit).
    window_fit is one of:
      - 'ideal' (Dec 5 – Dec 30, 2026)
      - 'early_flex' (Available now / late Nov / early Dec 1-4)
      - 'jan_tight' (Jan 1 – Jan 9, 2027 — before Jan 10 contract end)
      - 'outside' (After Jan 10, 2027 or 2027 late)
    """
    avail_lower = (avail_text or "").lower()
    combined = f"{avail_text} {full_text}".lower()

    # Check if availability date itself is in late 2027 (e.g., "Available 5 November 2027")
    if re.search(r"\b(?:feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\s+2027\b", avail_lower):
        return (avail_text or "Late 2027", "outside")

    # Look for December dates in avail_text first, then combined
    m_dec = re.search(
        r"\b(?:(\d{1,2})(?:st|nd|rd|th)?\s+(?:of\s+)?dec(?:ember)?|dec(?:ember)?\s+(\d{1,2})(?:st|nd|rd|th)?)\b",
        combined,
    )
    if m_dec:
        day = int(m_dec.group(1) or m_dec.group(2))
        if 5 <= day <= 30:
            return (f"Dec {day}, 2026", "ideal")
        elif 1 <= day <= 4:
            return (f"Dec {day}, 2026", "early_flex")
        else:
            return (f"Dec {day}, 2026", "ideal")

    if re.search(r"\b(?:mid|late|early)\s+dec(?:ember)?\b|\bdec(?:ember)?\s+2026\b", combined):
        return (avail_text or "December 2026", "ideal")

    # Look for late November
    m_nov = re.search(
        r"\b(?:(\d{1,2})(?:st|nd|rd|th)?\s+(?:of\s+)?nov(?:ember)?|nov(?:ember)?\s+(\d{1,2})(?:st|nd|rd|th)?)\b",
        avail_lower,
    )
    if m_nov:
        day = int(m_nov.group(1) or m_nov.group(2))
        return (f"Nov {day}, 2026", "early_flex")

    # Look for early January
    m_jan = re.search(
        r"\b(?:(\d{1,2})(?:st|nd|rd|th)?\s+(?:of\s+)?jan(?:uary)?|jan(?:uary)?\s+(\d{1,2})(?:st|nd|rd|th)?)\b",
        avail_lower,
    )
    if m_jan:
        day = int(m_jan.group(1) or m_jan.group(2))
        if day <= 9:
            return (f"Jan {day}, 2027", "jan_tight")
        return (f"Jan {day}, 2027", "outside")

    if "now" in avail_lower or "immediate" in combined or "flexible" in combined:
        return (avail_text or "Available Now (Flexible)", "early_flex")

    return (avail_text or "Check Listing", "early_flex")


def score_and_classify_listing(raw: Dict[str, Any]) -> Dict[str, Any]:
    """
    Enrich a raw listing dict with strict criteria evaluation and Hawthorn commute score.
    """
    title = raw.get("title", "") or ""
    description = raw.get("description", "") or ""
    address = raw.get("address", "") or ""
    subhead = raw.get("subhead", "") or ""
    full_text = f"{title} {subhead} {address} {description}"

    # 1. Price & Furnished status
    weekly_rent = raw.get("weekly_rent")
    if weekly_rent is None:
        weekly_rent = parse_price_weekly(raw.get("price_text", "") or full_text)

    is_furnished = raw.get("is_furnished")
    if is_furnished is None:
        is_furnished = detect_furnished(full_text)

    max_allowed_rent = (
        USER_CRITERIA["max_rent_furnished"]
        if is_furnished
        else USER_CRITERIA["max_rent_unfurnished"]
    )
    within_budget = weekly_rent is not None and 280 <= weekly_rent <= max_allowed_rent

    # 2. Bedrooms & Property Type
    bedrooms = raw.get("bedrooms")
    if bedrooms is None:
        m_bed = re.search(r"\b(\d)\s*(?:bed|br|bhk|bedroom)", full_text.lower())
        if m_bed:
            bedrooms = int(m_bed.group(1))
        elif "studio" in full_text.lower():
            bedrooms = 1
        else:
            bedrooms = 1

    is_sharehouse = detect_sharehouse(full_text, raw.get("listing_kind", ""))
    # Flag suspiciously cheap multi-room Flatmates listings (e.g. $240-$360 for 2-5 rooms = per-room sharehouse)
    if "flatmates" in (raw.get("source", "") or "").lower():
        if bedrooms >= 3 and (weekly_rent or 0) <= 550:
            is_sharehouse = True
        elif bedrooms == 2 and (weekly_rent or 0) < 380:
            is_sharehouse = True

    is_lease_transfer = raw.get("is_lease_transfer")
    if is_lease_transfer is None:
        is_lease_transfer = detect_lease_transfer(full_text)

    # 3. Suburb & Direct Commute to Hawthorn
    suburb, commute_info = extract_suburb_info(address, title)

    # 4. Availability Window (Dec 5 - Dec 30, 2026)
    avail_display, avail_fit = parse_availability(raw.get("date_available", ""), full_text)

    # 5. Compute Match Score (0 - 100) & Badges
    score = 0
    badges: List[str] = []
    rejection_reasons: List[str] = []

    if is_sharehouse:
        rejection_reasons.append("Sharehouse / Room only")
    if weekly_rent is None:
        rejection_reasons.append("Price unlisted")
    elif weekly_rent < 220:
        rejection_reasons.append("Likely room/carpark price (<$220/wk)")
    elif not within_budget:
        furn_label = "furnished (max $560)" if is_furnished else "unfurnished (max $525)"
        rejection_reasons.append(f"Over budget: ${weekly_rent}/wk {furn_label}")

    if avail_fit == "outside":
        rejection_reasons.append(f"Move-in outside window ({avail_display})")

    if commute_info is None:
        rejection_reasons.append("No direct train/tram to Hawthorn")

    # Budget score (up to 30 pts)
    if within_budget and weekly_rent:
        headroom = max_allowed_rent - weekly_rent
        score += 22 + min(8, int(headroom / 8))
        if is_furnished:
            badges.append(f"Furnished ≤ $560 (${weekly_rent}/wk)")
        else:
            badges.append(f"Unfurnished ≤ $525 (${weekly_rent}/wk)")
    elif weekly_rent and weekly_rent <= max_allowed_rent + 25:
        # Slightly over budget (negotiable lease transfer)
        score += 10

    # Bedrooms score (up to 25 pts — 2BHK preferred!)
    if bedrooms == 2:
        score += 25
        badges.append("2 BHK (Preferred)")
    elif bedrooms == 1:
        score += 14
        badges.append("1 BHK Entire Place")
    elif bedrooms >= 3 and not is_sharehouse:
        score += 18
        badges.append(f"{bedrooms} BHK Entire Place")

    # Commute to Hawthorn score (up to 25 pts)
    if commute_info:
        tier = commute_info["tier"]
        mins = commute_info["commute_mins"]
        if tier == 1:
            score += 25
        elif tier == 2:
            score += 19
        else:
            score += 13
        badges.append(f"Direct {commute_info['mode']} ({mins}m to Hawthorn)")

    # Move-in date & Lease Transfer bonus (up to 20 pts)
    if avail_fit == "ideal":
        score += 12
        badges.append(f"Dec 5–30 Move-In ({avail_display})")
    elif avail_fit == "early_flex":
        score += 8
    elif avail_fit == "jan_tight":
        score += 4

    if is_lease_transfer:
        score += 12
        badges.insert(0, "Lease Transfer / Break")

    if "inc. bills" in full_text.lower() or "includes all bills" in full_text.lower() or "bills included" in full_text.lower():
        score += 5
        badges.append("Bills Included")

    # Station proximity
    station_info = extract_station_distance(suburb, full_text)
    if station_info["is_explicit"] or station_info["distance_m"] <= 400:
        badges.append(f"🚆 {station_info['display']}")

    score = min(100, max(0, score))
    pass_strict = len(rejection_reasons) == 0

    enriched = dict(raw)
    enriched.update({
        "weekly_rent": weekly_rent,
        "is_furnished": is_furnished,
        "max_allowed_rent": max_allowed_rent,
        "within_budget": within_budget,
        "bedrooms": bedrooms,
        "is_lease_transfer": is_lease_transfer,
        "is_sharehouse": is_sharehouse,
        "suburb": suburb,
        "postcode": commute_info["postcode"] if commute_info else raw.get("postcode", ""),
        "commute_mode": commute_info["mode"] if commute_info else "Indirect / Transfer required",
        "commute_line": commute_info["line"] if commute_info else "Requires interchange to reach Hawthorn",
        "commute_mins": commute_info["commute_mins"] if commute_info else 45,
        "commute_tier": commute_info["tier"] if commute_info else 4,
        "has_direct_hawthorn_transit": commute_info is not None,
        "station_name": station_info["station_name"],
        "station_distance_m": station_info["distance_m"],
        "station_walking_mins": station_info["walking_mins"],
        "station_distance_display": station_info["display"],
        "station_is_explicit": station_info["is_explicit"],
        "availability_display": avail_display,
        "availability_fit": avail_fit,
        "match_score": score,
        "match_badges": badges,
        "pass_strict_filter": pass_strict,
        "rejection_reason": "; ".join(rejection_reasons) if rejection_reasons else None,
    })
    return enriched
