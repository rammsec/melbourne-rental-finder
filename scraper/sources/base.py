"""
Base Agency Adapter Interface, Source Health Telemetry, and Shared Extraction Utilities.

Implements the standard contract required for all direct real estate agency adapters:
- fetch_listings()
- parse_listing()
- normalise_listing()
- validate_listing()
- get_source_health()
"""

from __future__ import annotations

import html
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from abc import ABC, abstractmethod
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Tuple

from ..config import (
    EASTERN_TARGET_SUBURBS,
    HAWTHORN_DIRECT_SUBURBS,
    PRIMARY_SUBURBS,
    SECONDARY_SUBURBS,
    USER_CRITERIA,
)
from ..models import Property, ScraperExecutionLog, generate_property_id, generate_source_key
from .legacy import DEFAULT_HEADERS, is_outside_melbourne


# Canonical Melbourne & Hawthorn Corridor Suburb -> Postcode lookup
SUBURB_POSTCODE_MAP: Dict[str, str] = {
    "melbourne": "3000",
    "east melbourne": "3002",
    "west melbourne": "3003",
    "st kilda road": "3004",
    "southbank": "3006",
    "docklands": "3008",
    "footscray": "3011",
    "yarraville": "3013",
    "newport": "3015",
    "williamstown": "3016",
    "parkville": "3052",
    "carlton": "3053",
    "carlton north": "3054",
    "brunswick": "3056",
    "brunswick east": "3057",
    "coburg": "3058",
    "fitzroy": "3065",
    "collingwood": "3066",
    "abbotsford": "3067",
    "clifton hill": "3068",
    "fitzroy north": "3068",
    "northcote": "3070",
    "thornbury": "3071",
    "preston": "3072",
    "reservoir": "3073",
    "ivanhoe": "3079",
    "heidelberg": "3084",
    "kew": "3101",
    "kew east": "3102",
    "balwyn": "3103",
    "balwyn north": "3104",
    "bulleen": "3105",
    "templestowe": "3106",
    "doncaster": "3108",
    "doncaster east": "3109",
    "burnley": "3121",
    "richmond": "3121",
    "cremorne": "3121",
    "hawthorn": "3122",
    "glenferrie": "3122",
    "auburn": "3123",
    "hawthorn east": "3123",
    "camberwell": "3124",
    "burwood": "3125",
    "canterbury": "3126",
    "surrey hills": "3127",
    "mont albert": "3127",
    "box hill": "3128",
    "box hill north": "3129",
    "box hill south": "3128",
    "blackburn": "3130",
    "blackburn north": "3130",
    "blackburn south": "3130",
    "Laburnum": "3130",
    "nunawading": "3131",
    "forest hill": "3131",
    "mitcham": "3132",
    "vermont": "3133",
    "ringwood": "3134",
    "ringwood north": "3134",
    "heathmont": "3135",
    "ringwood east": "3135",
    "croydon": "3136",
    "mooroolbark": "3138",
    "lilydale": "3140",
    "south yarra": "3141",
    "toorak": "3142",
    "armadale": "3143",
    "malvern": "3144",
    "kooyong": "3144",
    "caulfield": "3162",
    "caulfield north": "3161",
    "caulfield east": "3145",
    "malvern east": "3145",
    "glen iris": "3146",
    "ashburton": "3147",
    "chadstone": "3148",
    "mount waverley": "3149",
    "glen waverley": "3150",
    "wantirna": "3152",
    "bayswater": "3153",
    "boronia": "3155",
    "ferntree gully": "3156",
    "upper ferntree gully": "3156",
    "upwey": "3158",
    "tecoma": "3160",
    "belgrave": "3160",
    "prahran": "3181",
    "windsor": "3181",
    "st kilda": "3182",
    "st kilda east": "3183",
    "elwood": "3184",
    "elsternwick": "3185",
    "brighton": "3186",
    "carnegie": "3163",
    "murrumbeena": "3163",
    "hughesdale": "3166",
    "oakleigh": "3166",
    "clayton": "3168",
}

CORRIDOR_POSTCODES: List[str] = sorted(
    list({SUBURB_POSTCODE_MAP[s] for s in HAWTHORN_DIRECT_SUBURBS if s in SUBURB_POSTCODE_MAP})
)

ELIGIBLE_PROPERTY_TYPES = {"apartment", "unit", "townhouse", "house", "studio"}
INELIGIBLE_PROPERTY_KEYWORDS = (
    "car space",
    "carspace",
    "car park",
    "carpark",
    "parking space",
    "garage only",
    "storage cage",
    "commercial",
    "retail",
    "office space",
    "warehouse",
)

MONTH_MAP = {
    "jan": 1, "january": 1,
    "feb": 2, "february": 2,
    "mar": 3, "march": 3,
    "apr": 4, "april": 4,
    "may": 5,
    "jun": 6, "june": 6,
    "jul": 7, "july": 7,
    "aug": 8, "august": 8,
    "sep": 9, "sept": 9, "september": 9,
    "oct": 10, "october": 10,
    "nov": 11, "november": 11,
    "dec": 12, "december": 12,
}


@dataclass
class SourceHealth:
    """
    Comprehensive health and execution metrics for an individual agency source adapter.
    Captures all Phase 1 Section 7 monitoring and logging fields.
    """
    source_name: str
    source_key: str = ""
    integration_status: str = "integrated"  # "integrated", "partial", "blocked"
    scrape_start_time: Optional[str] = None
    scrape_end_time: Optional[str] = None
    scrape_completion_time: Optional[str] = None
    successful_requests: int = 0
    listings_discovered: int = 0
    listings_accepted: int = 0
    valid_listings: int = 0
    duplicates_count: int = 0
    listings_rejected: int = 0
    parsing_failures: int = 0
    http_errors: int = 0
    last_successful_collection: Optional[str] = None
    status: str = "idle"  # "idle", "running", "success", "partial", "failed", "blocked"
    last_error: Optional[str] = None
    errors: List[str] = field(default_factory=list)
    failure_reasons: List[str] = field(default_factory=list)
    rejection_reasons: Dict[str, int] = field(default_factory=dict)
    duration_seconds: float = 0.0

    def __post_init__(self) -> None:
        if not self.source_key:
            self.source_key = generate_source_key(self.source_name)

    def to_dict(self) -> Dict[str, Any]:
        self.scrape_completion_time = self.scrape_completion_time or self.scrape_end_time
        self.valid_listings = self.listings_accepted
        return asdict(self)


def clean_html_text(raw_html: Optional[str]) -> str:
    """Strip HTML tags, unescape entities, and normalize whitespace."""
    if not raw_html:
        return ""
    text = re.sub(r"(?i)<br\s*/?>", " ", str(raw_html))
    text = re.sub(r"(?i)</p>", " ", text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def parse_weekly_rent(price_val: Any) -> Optional[float]:
    """
    Parse weekly rent from a numeric value or raw agency price string.
    Handles:
    - Numeric floats/ints: 560, 560.0 -> 560.0
    - Weekly text: "$560 per week", "$575 pw", "$550/wk", "$580 p.w."
    - Date + rent prefix: "18/11/2026 - $575", "Available Now - $540"
    - Combined weekly & monthly: "$650pw / $2824pcm" -> 650.0
    - Monthly-only text: "$2,433 pcm" or "$2400 per calendar month" -> round(val * 12 / 52, 2)
    """
    if price_val is None:
        return None
    if isinstance(price_val, (int, float)):
        val = float(price_val)
        return val if 100 <= val <= 5000 else None

    text = str(price_val).strip()
    if not text:
        return None

    # Remove date prefixes like "18/11/2026 -" or "2026-11-18"
    text_no_dates = re.sub(r"\b\d{1,2}/\d{1,2}/\d{2,4}\b", " ", text)
    text_no_dates = re.sub(r"\b\d{4}-\d{2}-\d{2}\b", " ", text_no_dates)
    # Remove bond clauses like "Bond $2,400"
    text_no_dates = re.sub(r"(?i)\bbond\s*\$?\s*[\d,]+(?:\.\d+)?", " ", text_no_dates)

    # 1. Explicit weekly pattern: $560 pw / per week / /wk / p.w.
    m_wk = re.search(
        r"\$\s*([\d,]+(?:\.\d+)?)\s*(?:p/?w|per\s+week|/\s*wk|/\s*week|p\.w\.|weekly)\b",
        text_no_dates,
        flags=re.IGNORECASE,
    )
    if m_wk:
        try:
            val = float(m_wk.group(1).replace(",", ""))
            if 100 <= val <= 5000:
                return round(val, 2)
        except ValueError:
            pass

    # 2. Explicit monthly (pcm / per calendar month / per month) when no weekly marker exists
    has_weekly_marker = bool(re.search(r"(?i)\b(?:p/?w|per\s+week|/\s*wk|/\s*week|p\.w\.|weekly)\b", text_no_dates))
    m_pcm = re.search(
        r"\$\s*([\d,]+(?:\.\d+)?)\s*(?:pcm|p\.c\.m\.|per\s+calendar\s+month|per\s+month|/\s*month|/\s*mth)\b",
        text_no_dates,
        flags=re.IGNORECASE,
    )
    if m_pcm and not has_weekly_marker:
        # Check if there is a preceding dollar amount before the monthly figure (e.g. "$550 / $2390 pcm")
        all_dollars = re.findall(r"\$\s*([\d,]+(?:\.\d+)?)", text_no_dates)
        if len(all_dollars) >= 2:
            try:
                first_val = float(all_dollars[0].replace(",", ""))
                if 150 <= first_val <= 2000:
                    return round(first_val, 2)
            except ValueError:
                pass
        try:
            pcm_val = float(m_pcm.group(1).replace(",", ""))
            wk_val = round(pcm_val * 12.0 / 52.0, 2)
            if 100 <= wk_val <= 5000:
                return wk_val
        except ValueError:
            pass

    # 3. Dollar sign with number (e.g. "$575" or "18/11/2026 - $575")
    m_dollar = re.search(r"\$\s*([\d,]+(?:\.\d+)?)", text_no_dates)
    if m_dollar:
        try:
            val = float(m_dollar.group(1).replace(",", ""))
            if 100 <= val <= 5000:
                return round(val, 2)
        except ValueError:
            pass

    # 4. Bare numeric string (e.g. "560" or "560.00")
    m_bare = re.fullmatch(r"([\d,]+(?:\.\d+)?)", text_no_dates.strip())
    if m_bare:
        try:
            val = float(m_bare.group(1).replace(",", ""))
            if 100 <= val <= 5000:
                return round(val, 2)
        except ValueError:
            pass

    return None


def normalise_property_type(raw_type: Optional[str], title: str = "", description: str = "") -> str:
    """Normalize agency property category into standard Property model types."""
    combined_raw = (raw_type or "").strip().lower()
    full_text = f"{combined_raw} {title} {description}".lower()

    for bad_kw in INELIGIBLE_PROPERTY_KEYWORDS:
        if bad_kw in combined_raw or (not combined_raw and bad_kw in title.lower()):
            return "carspace"

    if "studio" in combined_raw or "studio" in title.lower():
        return "studio"
    if any(k in combined_raw for k in ("townhouse", "town house", "ths")):
        return "townhouse"
    if any(k in combined_raw for k in ("unit", "unt", "villa", "duplex", "flat")):
        return "unit"
    if any(k in combined_raw for k in ("apartment", "apt")):
        return "apartment"
    if any(k in combined_raw for k in ("house", "hse", "terrace", "cottage", "semi-detached", "acreage")):
        return "house"

    # Fallback inference from title/description
    if "townhouse" in full_text:
        return "townhouse"
    if "studio" in full_text:
        return "studio"
    if "unit" in full_text or "villa" in full_text:
        return "unit"
    if "house" in full_text or "cottage" in full_text:
        return "house"
    return "apartment"


def parse_availability_date(raw_date: Any, reference_year: int = 2026) -> Optional[str]:
    """
    Normalize agency availability date strings into ISO date (YYYY-MM-DD) or 'Available Now'.
    Supports:
    - '2026-12-17T00:00:00+11:00' -> '2026-12-17'
    - 'Available Now' / 'Now' -> 'Available Now'
    - '18/11/2026' -> '2026-11-18'
    - 'Friday 27th November 2026' -> '2026-11-27'
    - 'Available November 27th 2026' -> '2026-11-27'
    - 'Available 22 Dec' -> '2026-12-22'
    """
    if not raw_date:
        return None
    text = str(raw_date).strip()
    if not text:
        return None

    low = text.lower()
    if low in ("now", "available now", "available", "immediate", "immediately"):
        return "Available Now"

    # 1. ISO format YYYY-MM-DD (including YYYY-MM-DDTHH:MM:SS)
    m_iso = re.search(r"(\d{4})-(\d{2})-(\d{2})(?:[T\s]|\b|$)", text)
    if m_iso:
        return f"{m_iso.group(1)}-{m_iso.group(2)}-{m_iso.group(3)}"

    # 2. Australian slash format DD/MM/YYYY or DD/MM/YY
    m_slash = re.search(r"\b(\d{1,2})/(\d{1,2})/(\d{2,4})\b", text)
    if m_slash:
        day, month, year = int(m_slash.group(1)), int(m_slash.group(2)), int(m_slash.group(3))
        if year < 100:
            year += 2000
        try:
            return datetime(year, month, day).strftime("%Y-%m-%d")
        except ValueError:
            pass

    # 3. Day Month [Year]: e.g. "Friday 27th November 2026" or "Available 22 Dec"
    m_dm = re.search(
        r"\b(\d{1,2})(?:st|nd|rd|th)?\s+(?:of\s+)?([A-Za-z]{3,9})(?:\s+(\d{4}))?\b",
        text,
    )
    if m_dm:
        day = int(m_dm.group(1))
        month_str = m_dm.group(2).lower()
        year = int(m_dm.group(3)) if m_dm.group(3) else reference_year
        if month_str in MONTH_MAP:
            try:
                return datetime(year, MONTH_MAP[month_str], day).strftime("%Y-%m-%d")
            except ValueError:
                pass

    # 4. Month Day [Year]: e.g. "Available November 27th 2026"
    m_md = re.search(
        r"\b([A-Za-z]{3,9})\s+(\d{1,2})(?:st|nd|rd|th)?(?:,?\s+(\d{4}))?\b",
        text,
    )
    if m_md:
        month_str = m_md.group(1).lower()
        day = int(m_md.group(2))
        year = int(m_md.group(3)) if m_md.group(3) else reference_year
        if month_str in MONTH_MAP:
            try:
                return datetime(year, MONTH_MAP[month_str], day).strftime("%Y-%m-%d")
            except ValueError:
                pass

    if "available now" in low:
        return "Available Now"

    return text


def extract_suburb_and_postcode(
    address: str,
    fallback_suburb: str = "",
    fallback_postcode: str = "",
) -> Tuple[str, str]:
    """Extract normalized Melbourne suburb (Title Case) and 4-digit Victorian postcode."""
    suburb = (fallback_suburb or "").strip()
    postcode = str(fallback_postcode or "").strip()

    addr = (address or "").strip()
    if addr:
        if not postcode:
            m_pc = re.search(r"\b(3\d{3})\b", addr)
            if m_pc:
                postcode = m_pc.group(1)

        if not suburb:
            # 1. Inspect comma-separated segments from right to left (suburb is after street segment)
            segments = [s.strip() for s in addr.split(",") if s.strip()]
            for seg in reversed(segments):
                seg_clean = re.sub(r"\b(?:VIC|Victoria|3\d{3})\b", " ", seg, flags=re.IGNORECASE)
                seg_clean = re.sub(r"\s+", " ", seg_clean).strip()
                if not seg_clean:
                    continue
                seg_low = seg_clean.lower()
                if seg_low in SUBURB_POSTCODE_MAP:
                    suburb = seg_clean.title()
                    break
                for known_sub in sorted(SUBURB_POSTCODE_MAP.keys(), key=len, reverse=True):
                    if re.search(rf"\b{re.escape(known_sub)}\b", seg_low):
                        # Avoid matching a street name like "Glenferrie Road" as suburb "Glenferrie"
                        if re.search(
                            rf"\b{re.escape(known_sub)}\s+(?:road|rd|street|st|avenue|ave|parade|pde|drive|dr|lane|ln)\b",
                            seg_low,
                        ):
                            continue
                        suburb = known_sub.title()
                        break
                if suburb:
                    break

        if not suburb:
            # 1b. If comma-separated segments exist (e.g. "61 Cotters Road, Epping, VIC 3076")
            # and none matched SUBURB_POSTCODE_MAP, take the non-street segment before VIC 3XXX
            if len(segments) >= 2:
                for idx in range(len(segments) - 1, 0, -1):
                    seg_clean = re.sub(r"\b(?:VIC|Victoria|Australia|3\d{3})\b", " ", segments[idx], flags=re.IGNORECASE)
                    seg_clean = re.sub(r"\s+", " ", seg_clean).strip(" ,-")
                    if not seg_clean or re.search(r"\d", seg_clean):
                        continue
                    if seg_clean.lower() in ("vic", "victoria", "australia"):
                        continue
                    suburb = seg_clean.title()
                    break

        if not suburb:
            # 2. Match explicit "<Suburb> [VIC] 3XXX" at end of un-comma'd string
            m_tail = re.search(
                r"\b([A-Za-z][A-Za-z\s]{1,22}?)\s+(?:VIC\s+)?(3\d{3})\b",
                addr,
                flags=re.IGNORECASE,
            )
            if m_tail:
                cand_low = m_tail.group(1).strip().lower()
                for known_sub in sorted(SUBURB_POSTCODE_MAP.keys(), key=len, reverse=True):
                    if cand_low.endswith(known_sub):
                        suburb = known_sub.title()
                        break
                if not suburb and cand_low not in ("vic", "victoria", "australia"):
                    suburb = m_tail.group(1).strip().title()

    if suburb and not postcode:
        postcode = SUBURB_POSTCODE_MAP.get(suburb.lower(), "")

    return suburb.title() if suburb else "", postcode


class BaseAgencyAdapter(ABC):
    """
    Common interface and execution harness for direct real estate agency adapters.

    Every agency adapter must implement:
    - fetch_listings()
    - parse_listing(raw_item)
    - normalise_listing(parsed_item)
    - validate_listing(prop)
    - get_source_health()
    """

    source_name: str = "Agency"
    agency_brand: str = "Agency"
    base_url: str = ""
    integration_status: str = "integrated"  # "integrated", "partial", "blocked"
    request_delay_seconds: float = 0.25
    max_retries: int = 2
    retry_backoff_seconds: float = 0.6

    def __init__(
        self,
        http_fetcher: Optional[Callable[..., str]] = None,
        max_listings: int = 30,
    ) -> None:
        self._http_fetcher = http_fetcher
        self.max_listings = max_listings
        self.health = SourceHealth(
            source_name=self.source_name,
            source_key=generate_source_key(self.source_name),
            integration_status=self.integration_status,
        )

    def _record_error(self, msg: str) -> None:
        """Record an error message into health telemetry."""
        self.health.last_error = msg
        if msg not in self.health.errors:
            self.health.errors.append(msg)
        if msg not in self.health.failure_reasons:
            self.health.failure_reasons.append(msg)

    def _request_url(
        self,
        url: str,
        method: str = "GET",
        data: Optional[bytes] = None,
        headers: Optional[Dict[str, str]] = None,
        timeout: float = 15.0,
    ) -> str:
        """
        Perform an HTTP request with health telemetry tracking, sensible timeouts,
        and exponential backoff retries for transient network or 5xx errors.
        """
        if self._http_fetcher is not None:
            try:
                resp = self._http_fetcher(url, method=method, data=data, headers=headers, timeout=timeout)
                self.health.successful_requests += 1
                return resp
            except urllib.error.HTTPError as e:
                self.health.http_errors += 1
                self._record_error(f"HTTP {e.code}: {e.reason} ({url})")
                raise
            except Exception as e:
                self.health.http_errors += 1
                self._record_error(f"{type(e).__name__}: {e} ({url})")
                raise

        req_headers = dict(DEFAULT_HEADERS)
        if headers:
            req_headers.update(headers)

        attempts = max(1, self.max_retries + 1)
        for attempt in range(attempts):
            req = urllib.request.Request(url, data=data, headers=req_headers, method=method)
            try:
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    body = resp.read().decode("utf-8", errors="ignore")
                    self.health.successful_requests += 1
                    return body
            except urllib.error.HTTPError as e:
                # Do not retry deterministic 403/404/429 WAF blocks
                if e.code in (401, 403, 404, 429) or attempt == attempts - 1:
                    self.health.http_errors += 1
                    self._record_error(f"HTTP {e.code}: {e.reason} ({url})")
                    raise
                time.sleep(self.retry_backoff_seconds * (2 ** attempt))
            except Exception as e:
                if attempt == attempts - 1:
                    self.health.http_errors += 1
                    self._record_error(f"{type(e).__name__}: {e} ({url})")
                    raise
                time.sleep(self.retry_backoff_seconds * (2 ** attempt))

        raise RuntimeError(f"Request retries exhausted for {url}")

    @abstractmethod
    def fetch_listings(self) -> List[Any]:
        """Fetch raw listing payloads from the agency source."""
        raise NotImplementedError

    @abstractmethod
    def parse_listing(self, raw_item: Any) -> Dict[str, Any]:
        """
        Extract structured fields from a raw agency listing item:
        - listing_id
        - address
        - suburb
        - postcode
        - state
        - weekly_rent
        - price_text
        - bedrooms
        - bathrooms
        - parking
        - property_type
        - title
        - description
        - images
        - available_date
        - inspection_times
        - url
        - agency_office
        - discovered_at
        """
        raise NotImplementedError

    def normalise_listing(self, parsed_item: Dict[str, Any]) -> Property:
        """
        Convert a parsed agency listing dictionary into the unified Property model,
        preserving agency provenance and applying Hawthorn corridor transit & V2 scoring.
        """
        if not parsed_item or not isinstance(parsed_item, dict):
            raise ValueError("parsed_item must be a non-empty dictionary")

        source_name = parsed_item.get("source") or self.source_name
        source_key = generate_source_key(source_name)
        listing_id = str(parsed_item.get("listing_id") or parsed_item.get("id") or "").strip()
        url = str(parsed_item.get("url") or parsed_item.get("source_url") or "").strip()
        address = str(parsed_item.get("address") or "").strip()
        suburb, postcode = extract_suburb_and_postcode(
            address,
            fallback_suburb=str(parsed_item.get("suburb") or ""),
            fallback_postcode=str(parsed_item.get("postcode") or ""),
        )
        state = str(parsed_item.get("state") or "VIC").upper().strip()

        weekly_rent = parsed_item.get("weekly_rent")
        if weekly_rent is None or not isinstance(weekly_rent, (int, float)):
            weekly_rent = parse_weekly_rent(
                parsed_item.get("weekly_rent")
                if parsed_item.get("weekly_rent") is not None
                else parsed_item.get("price_text")
            )
        else:
            weekly_rent = float(weekly_rent)

        try:
            bedrooms = int(parsed_item.get("bedrooms") if parsed_item.get("bedrooms") is not None else 1)
        except (ValueError, TypeError):
            bedrooms = 1

        try:
            bathrooms = int(parsed_item.get("bathrooms") if parsed_item.get("bathrooms") is not None else 1)
        except (ValueError, TypeError):
            bathrooms = 1

        try:
            parking = int(parsed_item.get("parking") if parsed_item.get("parking") is not None else 0)
        except (ValueError, TypeError):
            parking = 0

        title = clean_html_text(parsed_item.get("title") or address or f"{bedrooms} Bedroom Rental in {suburb}")
        description = clean_html_text(parsed_item.get("description") or "")
        prop_type = normalise_property_type(parsed_item.get("property_type"), title=title, description=description)

        # Infer furnished status ONLY when explicitly stated; otherwise use None/null per Section 4
        explicit_furnished = parsed_item.get("is_furnished") if "is_furnished" in parsed_item else parsed_item.get("furnished")
        if explicit_furnished is None:
            combined_f = f"{title} {description}".lower()
            if "unfurnished" in combined_f:
                explicit_furnished = False
            elif re.search(r"\b(?:fully\s+furnished|furnished\s+apartment|furnished\s+unit|comes\s+furnished)\b", combined_f):
                explicit_furnished = True

        images = [str(img).strip() for img in (parsed_item.get("images") or []) if str(img).strip()]
        photo = str(parsed_item.get("photo") or (images[0] if images else "")).strip()
        if photo and photo not in images:
            images.insert(0, photo)

        available_date = parse_availability_date(parsed_item.get("available_date") or parsed_item.get("date_available"))
        inspection_times = [
            clean_html_text(str(t)) for t in (parsed_item.get("inspection_times") or []) if str(t).strip()
        ]
        agency_office = clean_html_text(parsed_item.get("agency_office") or parsed_item.get("agency_name") or self.source_name)
        discovered_at = str(parsed_item.get("discovered_at") or parsed_item.get("scraped_at") or datetime.now(timezone.utc).isoformat())
        listed_at = str(parsed_item.get("listed_at") or discovered_at)

        prop_id = generate_property_id(source_name, listing_id, address=address, suburb=suburb)

        provenance_entry = {
            "source_name": source_name,
            "source": source_name,
            "source_key": source_key,
            "agency_name": agency_office,
            "source_listing_id": listing_id,
            "source_url": url,
            "url": url,
            "agency_office": agency_office,
            "raw_title": title,
            "raw_price_text": str(parsed_item.get("price_text") or (f"${int(weekly_rent)}/wk" if weekly_rent else "")),
            "discovered_at": discovered_at,
            "first_seen": listed_at,
            "last_seen": discovered_at,
            "is_active": True,
        }

        legacy_candidate: Dict[str, Any] = {
            "id": listing_id or prop_id,
            "property_id": prop_id,
            "source": source_name,
            "source_key": source_key,
            "agency_name": agency_office,
            "source_listing_id": listing_id,
            "url": url,
            "source_url": url,
            "title": title,
            "address": address or f"{suburb}, {state} {postcode}".strip(),
            "suburb": suburb,
            "postcode": postcode,
            "state": state,
            "property_type": prop_type,
            "bedrooms": bedrooms,
            "bathrooms": bathrooms,
            "parking": parking,
            "weekly_rent": weekly_rent,
            "furnished": explicit_furnished,
            "is_furnished": explicit_furnished,
            "available_date": available_date,
            "date_available": available_date,
            "description": description,
            "photo": photo,
            "images": images,
            "inspection_times": inspection_times,
            "agency_office": agency_office,
            "listed_at": listed_at,
            "scraped_at": discovered_at,
            "first_seen": listed_at,
            "last_seen": discovered_at,
            "is_lease_transfer": False,
            "sources": [provenance_entry],
            "source_provenance": [provenance_entry],
            "raw_metadata": {
                "agency_office": agency_office,
                "images": images,
                "inspection_times": inspection_times,
                "price_text": parsed_item.get("price_text"),
                "raw_category": parsed_item.get("property_type"),
            },
        }

        # Apply existing V1 classification & Hawthorn transit enrichment (does not alter eligibility rules)
        from ..scorer import score_and_classify_listing
        from ..scorer_v2 import score_property_v2

        enriched = score_and_classify_listing(legacy_candidate)
        enriched["property_id"] = prop_id
        enriched["source_listing_id"] = listing_id
        if suburb:
            enriched["suburb"] = suburb
        enriched["property_type"] = prop_type
        enriched["postcode"] = postcode or enriched.get("postcode", "")
        enriched["state"] = state
        enriched["furnished"] = explicit_furnished
        enriched["is_furnished"] = explicit_furnished
        enriched["available_date"] = available_date
        enriched["date_available"] = available_date
        enriched["images"] = images
        enriched["photo"] = photo
        enriched["inspection_times"] = inspection_times
        enriched["agency_office"] = agency_office
        enriched["sources"] = [provenance_entry]
        enriched["source_provenance"] = [provenance_entry]

        prop = Property.from_legacy(enriched)
        prop.furnished = explicit_furnished
        prop = score_property_v2(prop)
        return prop

    def validate_listing(self, prop: Property) -> Tuple[bool, List[str]]:
        """
        Validate a normalized Property against required fields and Melbourne suburb,
        property type, bedroom, and budget filtering criteria.
        Returns (is_valid, list_of_rejection_reasons).
        """
        reasons: List[str] = []

        if not prop.source_listing_id and not prop.property_id:
            reasons.append("Missing listing identifier")

        if not prop.source_url or not prop.source_url.startswith(("http://", "https://")):
            reasons.append("Missing or invalid direct property URL")

        if not prop.suburb:
            reasons.append("Missing suburb")

        if (prop.state or "VIC").upper() != "VIC" or is_outside_melbourne(
            prop.address or "", prop.title or "", prop.description or "", prop.suburb or ""
        ):
            reasons.append(f"Outside Melbourne/Victoria ({prop.suburb}, {prop.state})")

        if prop.property_type not in ELIGIBLE_PROPERTY_TYPES:
            reasons.append(f"Ineligible property type ({prop.property_type})")

        for bad_kw in INELIGIBLE_PROPERTY_KEYWORDS:
            if bad_kw in (prop.title or "").lower():
                reasons.append(f"Non-residential listing keyword ({bad_kw})")
                break

        if not prop.property_entire or prop.is_sharehouse:
            reasons.append("Shared accommodation / room-only listing")

        if prop.is_student_only:
            reasons.append("Student-only accommodation")

        if prop.bedrooms < 1 or prop.bedrooms > 3:
            reasons.append(f"Bedroom count outside 1-3BR criteria ({prop.bedrooms} BR)")

        if prop.weekly_rent is None:
            reasons.append("Missing weekly rent")
        elif prop.weekly_rent < 200:
            reasons.append(f"Weekly rent below minimum threshold (${prop.weekly_rent}/wk)")
        elif prop.weekly_rent > 650:
            reasons.append(f"Weekly rent exceeds Melbourne filter cap (${prop.weekly_rent}/wk > $650/wk)")

        return (len(reasons) == 0), reasons

    def get_source_health(self) -> Dict[str, Any]:
        """Return structured health telemetry for this source adapter."""
        return self.health.to_dict()

    def collect(self) -> List[Property]:
        """
        Execute the full fetch -> parse -> normalise -> validate pipeline with
        strict fault isolation. Never raises an unhandled exception to callers.
        """
        start_ts = time.time()
        self.health.scrape_start_time = datetime.now(timezone.utc).isoformat()
        self.health.status = "running"
        self.health.listings_discovered = 0
        self.health.listings_accepted = 0
        self.health.valid_listings = 0
        self.health.duplicates_count = 0
        self.health.listings_rejected = 0
        self.health.parsing_failures = 0
        self.health.rejection_reasons = {}

        accepted: List[Property] = []
        seen_keys: set = set()

        try:
            raw_items = self.fetch_listings()
        except Exception as e:
            now_iso = datetime.now(timezone.utc).isoformat()
            self.health.scrape_end_time = now_iso
            self.health.scrape_completion_time = now_iso
            self.health.duration_seconds = round(time.time() - start_ts, 2)
            err_msg = self.health.last_error or f"{type(e).__name__}: {e}"
            self._record_error(err_msg)
            if self.integration_status == "blocked" or "403" in str(e) or "429" in str(e):
                self.health.status = "blocked"
            else:
                self.health.status = "failed"
            return []

        self.health.listings_discovered = len(raw_items)

        for raw_item in raw_items:
            try:
                parsed = self.parse_listing(raw_item)
                prop = self.normalise_listing(parsed)
            except Exception as e:
                self.health.parsing_failures += 1
                self._record_error(f"Parse error: {e}")
                continue

            # Track intra-source duplicates by property_id or source_url
            dedup_key = (prop.property_id, prop.source_url)
            if prop.property_id in seen_keys or (prop.source_url and prop.source_url in seen_keys):
                self.health.duplicates_count += 1
                continue

            is_valid, reasons = self.validate_listing(prop)
            if is_valid:
                seen_keys.add(prop.property_id)
                if prop.source_url:
                    seen_keys.add(prop.source_url)
                accepted.append(prop)
                self.health.listings_accepted += 1
                self.health.valid_listings = self.health.listings_accepted
            else:
                self.health.listings_rejected += 1
                for r in reasons:
                    self.health.rejection_reasons[r] = self.health.rejection_reasons.get(r, 0) + 1

        now_iso = datetime.now(timezone.utc).isoformat()
        self.health.scrape_end_time = now_iso
        self.health.scrape_completion_time = now_iso
        self.health.valid_listings = self.health.listings_accepted
        self.health.duration_seconds = round(time.time() - start_ts, 2)

        if self.health.successful_requests > 0 and self.health.http_errors == 0:
            self.health.last_successful_collection = now_iso
            self.health.status = "success"
        elif self.health.successful_requests > 0:
            self.health.last_successful_collection = now_iso
            self.health.status = "partial"
        elif self.integration_status == "blocked":
            self.health.status = "blocked"
        else:
            self.health.status = "failed"

        return accepted

    def to_execution_log(self) -> ScraperExecutionLog:
        """Convert adapter health metrics into a database ScraperExecutionLog record."""
        return ScraperExecutionLog(
            run_timestamp=self.health.scrape_end_time or datetime.now(timezone.utc).isoformat(),
            source=self.source_name,
            listings_scanned=self.health.listings_discovered,
            listings_new=self.health.listings_accepted,
            listings_updated=0,
            errors_logged=self.health.http_errors + self.health.parsing_failures,
            duration_seconds=self.health.duration_seconds,
            status=self.health.status if self.health.status in ("success", "partial", "failed") else "failed",
            error_message=self.health.last_error,
        )
