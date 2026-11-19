"""
McGrath Estate Agents Direct Rental Listing Adapter.

Feasibility & Technical Compliance Note:
- `https://www.mcgrath.com.au` enforces strict edge WAF rate-limiting / anti-bot
  controls that return `HTTP 429 Too Many Requests` (or `HTTP 403 Forbidden`)
  to automated requests, including `https://www.mcgrath.com.au/robots.txt`.
- Per Phase 1 Legal and Technical Requirements ("Respect robots.txt, website terms,
  rate limits and access restrictions. Do not bypass authentication, CAPTCHAs or
  anti-bot controls. If a source cannot be reliably accessed, report it as blocked
  or unsupported rather than generating sample listings"):
  - This adapter never attempts to spoof challenges or bypass rate-limiting controls.
  - When the upstream endpoint returns HTTP 429/403, `collect()` records the HTTP
    status in `get_source_health()` and marks the source as `blocked` without
    disrupting other agency sources.
  - If an authorized feed or HTML/JSON fixture is supplied (e.g. in unit tests),
    `parse_listing()` normalises the listing into the standard Property schema.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

from .base import (
    BaseAgencyAdapter,
    clean_html_text,
    extract_suburb_and_postcode,
    normalise_property_type,
    parse_availability_date,
    parse_weekly_rent,
)


class McGrathAdapter(BaseAgencyAdapter):
    """Adapter for McGrath Estate Agents rental listings (WAF/429-aware with fault isolation)."""

    source_name = "McGrath"
    agency_brand = "McGrath"
    base_url = "https://www.mcgrath.com.au"
    rent_url = "https://www.mcgrath.com.au/rent/offices/vic"
    integration_status = "blocked"
    max_retries = 0  # Do not hammer rate-limited 429 endpoints

    def __init__(
        self,
        http_fetcher: Optional[Callable[..., str]] = None,
        max_listings: int = 20,
    ) -> None:
        super().__init__(http_fetcher=http_fetcher, max_listings=max_listings)

    def fetch_listings(self) -> List[Any]:
        """Attempt a single standard polite request to the McGrath rental page."""
        html_text = self._request_url(self.rent_url, timeout=10.0)
        items = self.extract_listings_from_html(html_text)
        return items[: self.max_listings]

    @classmethod
    def extract_listings_from_html(cls, html_text: str) -> List[Dict[str, Any]]:
        """Extract JSON-LD or Next.js property listings from McGrath HTML when accessible."""
        items: List[Dict[str, Any]] = []
        for m in re.finditer(
            r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
            html_text,
            flags=re.DOTALL | re.IGNORECASE,
        ):
            try:
                data = json.loads(m.group(1).strip())
                candidates = data if isinstance(data, list) else [data]
                for obj in candidates:
                    if isinstance(obj, dict) and obj.get("address"):
                        items.append(obj)
            except Exception:
                continue
        return items

    def parse_listing(self, raw_item: Any) -> Dict[str, Any]:
        """Parse a McGrath dictionary or HTML fixture into standard adapter fields."""
        if isinstance(raw_item, str):
            extracted = self.extract_listings_from_html(raw_item)
            if not extracted:
                raise ValueError("No structured McGrath listing found in HTML")
            item = extracted[0]
        elif isinstance(raw_item, dict):
            item = dict(raw_item)
        else:
            raise ValueError(f"Unsupported McGrath raw_item type: {type(raw_item)}")

        url = str(item.get("url") or "").strip()
        listing_id = str(item.get("listing_id") or item.get("id") or "").strip()
        if not listing_id and url:
            m_id = re.search(r"(\d{4,})", url)
            if m_id:
                listing_id = m_id.group(1)
        if not listing_id:
            raise ValueError("McGrath listing missing listing_id")

        addr_obj = item.get("address")
        if isinstance(addr_obj, dict):
            street = str(addr_obj.get("streetAddress") or "").strip()
            sub_raw = str(addr_obj.get("addressLocality") or "").strip()
            state_raw = str(addr_obj.get("addressRegion") or "VIC").strip()
            pc_raw = str(addr_obj.get("postalCode") or "").strip()
            address = f"{street}, {sub_raw}, {state_raw} {pc_raw}".strip(", ")
        else:
            address = clean_html_text(str(addr_obj or ""))
            sub_raw = str(item.get("suburb") or "")
            pc_raw = str(item.get("postcode") or "")
            state_raw = str(item.get("state") or "VIC")

        suburb, postcode = extract_suburb_and_postcode(
            address, fallback_suburb=sub_raw, fallback_postcode=pc_raw
        )

        price_text = str(item.get("price_text") or item.get("price") or "").strip()
        weekly_rent = parse_weekly_rent(
            item.get("weekly_rent") if item.get("weekly_rent") is not None else price_text
        )

        title = clean_html_text(item.get("title") or item.get("name") or address)
        description = clean_html_text(item.get("description") or "")
        prop_type = normalise_property_type(
            str(item.get("property_type") or item.get("@type") or ""),
            title=title,
            description=description,
        )

        raw_imgs = item.get("images") or item.get("image") or []
        if isinstance(raw_imgs, str):
            images = [raw_imgs]
        elif isinstance(raw_imgs, list):
            images = [str(u).strip() for u in raw_imgs if str(u).strip()]
        else:
            images = []

        return {
            "source": self.source_name,
            "listing_id": listing_id,
            "address": address,
            "suburb": suburb,
            "postcode": postcode,
            "state": state_raw or "VIC",
            "weekly_rent": weekly_rent,
            "price_text": price_text or (f"${int(weekly_rent)}/wk" if weekly_rent else ""),
            "bedrooms": item.get("bedrooms", 1),
            "bathrooms": item.get("bathrooms", 1),
            "parking": item.get("parking", 0),
            "property_type": prop_type,
            "title": title or address,
            "description": description,
            "images": images,
            "available_date": parse_availability_date(item.get("available_date")),
            "inspection_times": list(item.get("inspection_times") or []),
            "url": url or f"{self.base_url}/rent/{listing_id}",
            "agency_office": clean_html_text(item.get("agency_office") or "McGrath"),
            "discovered_at": str(item.get("discovered_at") or datetime.now(timezone.utc).isoformat()),
        }
