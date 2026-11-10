"""
Listing Freshness & Availability Lifecycle Tracking for Melbourne Rental Finder V2.

Tracks:
- first_seen: Timestamp when the property was first discovered
- last_seen: Timestamp when the property was most recently observed in a scrape
- last_verified: Timestamp of explicit HTTP or presence verification
- listing_status:
    * 'active': Observed in recent scrape and verified reachable
    * 'potentially_unavailable': Not observed in recent scrapes (>7 days)
    * 'removed': Explicitly detected as leased, removed, or returning 404
    * 'expired': Stale for >21 days without re-observation
"""

from __future__ import annotations

import re
import urllib.request
import urllib.error
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional, Tuple

from .models import Property


REMOVAL_KEYWORDS = [
    r"\bdeposit\s+taken\b",
    r"\bunder\s+application\b",
    r"\bleased\b",
    r"\bno\s+longer\s+available\b",
    r"\blisting\s+has\s+expired\b",
    r"\bthis\s+ad\s+is\s+no\s+longer\s+available\b",
    r"\bthis\s+listing\s+has\s+been\s+removed\b",
    r"\bproperty\s+off\s+market\b",
    r"\bapplication\s+pending\b",
]


def parse_iso_datetime(dt_str: Optional[str]) -> datetime:
    """Safely parse ISO datetime string, defaulting to current UTC time on failure."""
    if not dt_str:
        return datetime.now(timezone.utc)
    try:
        clean_str = dt_str.replace("Z", "+00:00")
        return datetime.fromisoformat(clean_str)
    except Exception:
        return datetime.now(timezone.utc)


def compute_freshness_status(
    first_seen_iso: str,
    last_seen_iso: str,
    current_time: Optional[datetime] = None,
) -> Tuple[str, float, bool]:
    """
    Compute listing status and age metrics.
    Returns:
    - status: 'active', 'potentially_unavailable', or 'expired'
    - age_hours: total hours since first discovery
    - is_new: whether discovered in the last 48 hours
    """
    now = current_time or datetime.now(timezone.utc)
    first_dt = parse_iso_datetime(first_seen_iso)
    last_dt = parse_iso_datetime(last_seen_iso)

    age_hours = max(0.0, (now - first_dt).total_seconds() / 3600.0)
    unseen_days = max(0.0, (now - last_dt).total_seconds() / 86400.0)

    is_new = age_hours <= 48.0

    if unseen_days > 21.0:
        status = "expired"
    elif unseen_days > 7.0:
        status = "potentially_unavailable"
    else:
        status = "active"

    return status, age_hours, is_new


def verify_listing_url(url: str, timeout: float = 6.0) -> Tuple[bool, str]:
    """
    Check if a listing URL is still active and not leased/removed.
    Returns (is_active, status_reason).
    """
    if not url or not url.startswith("http"):
        return False, "Invalid URL"

    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        },
    )

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            status_code = resp.getcode()
            if status_code in (404, 410):
                return False, f"HTTP {status_code} Not Found"

            # Check content for leased/removed cues in the first 30KB
            content = resp.read(30000).decode("utf-8", errors="ignore").lower()
            for pattern in REMOVAL_KEYWORDS:
                if re.search(pattern, content):
                    return False, f"Page indicates property is leased or removed"

            return True, "Reachable and active"
    except urllib.error.HTTPError as e:
        if e.code in (404, 410):
            return False, f"HTTP {e.code} Listing Removed"
        # 403/429 usually means anti-scraping / rate limit, don't assume removed
        return True, f"HTTP {e.code} Gate (assumed active)"
    except Exception as e:
        return True, f"Network timeout or error ({str(e)[:40]}), assumed active"


def update_property_freshness(
    prop: Property,
    seen_in_current_run: bool,
    now_iso: Optional[str] = None,
    verify_online: bool = False,
) -> Property:
    """
    Update freshness and lifecycle status on a Property object.
    """
    now = datetime.now(timezone.utc)
    now_str = now_iso or now.isoformat()

    if seen_in_current_run:
        prop.last_seen = now_str
        prop.listing_status = "active"
    else:
        status, _, _ = compute_freshness_status(prop.first_seen, prop.last_seen, current_time=now)
        prop.listing_status = status

    # Evaluate is_new flag
    first_dt = parse_iso_datetime(prop.first_seen)
    prop.is_new = max(0.0, (now - first_dt).total_seconds() / 3600.0) <= 48.0

    if verify_online and prop.source_url:
        is_active, reason = verify_listing_url(prop.source_url)
        prop.last_verified = now_str
        if is_active:
            prop.verification_status = "verified"
        else:
            prop.listing_status = "removed"
            prop.verification_status = "verified"
            prop.rejection_reason = f"Verified unavailable: {reason}"

    return prop


def update_catalog_freshness(
    catalog: List[Property],
    current_run_ids: set,
    verify_sample_size: int = 0,
) -> Tuple[List[Property], Dict[str, int]]:
    """
    Update lifecycle state for an entire catalog of properties.
    Returns (updated_properties, summary_stats).
    """
    now_str = datetime.now(timezone.utc).isoformat()
    stats = {
        "active": 0,
        "potentially_unavailable": 0,
        "removed": 0,
        "expired": 0,
        "new": 0,
    }

    updated: List[Property] = []
    verified_count = 0

    for prop in catalog:
        seen = prop.property_id in current_run_ids or prop.source_listing_id in current_run_ids
        should_verify = verified_count < verify_sample_size and prop.source_url.startswith("http")
        if should_verify:
            verified_count += 1

        update_property_freshness(prop, seen_in_current_run=seen, now_iso=now_str, verify_online=should_verify)

        st = prop.listing_status
        stats[st] = stats.get(st, 0) + 1
        if prop.is_new:
            stats["new"] += 1

        updated.append(prop)

    return updated, stats
