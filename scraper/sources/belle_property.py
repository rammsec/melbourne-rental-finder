"""
Belle Property Direct Rental Listing Adapter (WAF / HTTP 403 Isolated).

Feasibility Assessment:
- https://www.belleproperty.com/robots.txt and https://www.belleproperty.com/rent/
  return HTTP 403 Forbidden behind Cloudflare / WAF bot protection.
- Per Legal & Technical Requirements (Section 9): We do NOT attempt to bypass
  WAF, CAPTCHAs, or access controls.
- This adapter implements the full common adapter interface for fixture-based
  testing and future activation if public access is permitted, while gracefully
  recording HTTP 403 errors and setting health status to 'blocked' during live runs.
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


class BellePropertyAdapter(BaseAgencyAdapter):
    """Adapter for Belle Property with strict HTTP 403 WAF isolation."""

    source_name = "Belle Property"
    agency_brand = "Belle Property"
    base_url = "https://www.belleproperty.com"
    directory_url = "https://www.belleproperty.com/rent/"
    integration_status = "blocked"

    def __init__(
        self,
        http_fetcher: Optional[Callable[..., str]] = None,
        max_listings: int = 20,
    ) -> None:
        super().__init__(http_fetcher=http_fetcher, max_listings=max_listings)

    @classmethod
    def extract_listings_from_html(cls, html_text: str) -> List[Dict[str, Any]]:
        """
        Extract listings from Belle Property HTML (JSON-LD or server-rendered cards)
        when provided via test fixtures or permitted public response.
        """
        results: List[Dict[str, Any]] = []

        # 1. Check JSON-LD blocks
        ld_blocks = re.findall(
            r'<script\s+type="application/ld\+json"[^>]*>(.*?)</script>',
            html_text,
            flags=re.DOTALL | re.IGNORECASE,
        )
        for ld_raw in ld_blocks:
            try:
                data = json.loads(ld_raw.strip())
            except Exception:
                continue
            objs = data if isinstance(data, list) else [data]
            for obj in objs:
                if not isinstance(obj, dict):
                    continue
                if obj.get("@type") in ("Residence", "Apartment", "SingleFamilyResidence", "Product", "Offer"):
                    results.append(obj)

        # 2. Check standard Belle Property card blocks if present
        card_matches = re.finditer(
            r'<article([^>]*)>(.*?)</article>',
            html_text,
            flags=re.DOTALL | re.IGNORECASE,
        )
        for m in card_matches:
            attrs = m.group(1)
            block = m.group(2)
            m_lid = re.search(r'data-listing-id="([^"]+)"', attrs, flags=re.I)
            if not m_lid:
                continue
            lid = m_lid.group(1).strip()

            m_href = re.search(r'href="([^"]+)"', block, flags=re.I)
            m_addr = re.search(r'class="[^"]*address[^"]*"[^>]*>(.*?)</', block, flags=re.DOTALL | re.I)
            m_price = re.search(r'class="[^"]*price[^"]*"[^>]*>(.*?)</', block, flags=re.DOTALL | re.I)
            m_avail = re.search(r'class="[^"]*avail[^"]*"[^>]*>(.*?)</', block, flags=re.DOTALL | re.I)
            m_office = re.search(r'class="[^"]*office[^"]*"[^>]*>(.*?)</', block, flags=re.DOTALL | re.I)
            m_bed = re.search(r'data-beds="(\d+)"', attrs, flags=re.I) or re.search(r'data-beds="(\d+)"', block, flags=re.I)
            m_bath = re.search(r'data-baths="(\d+)"', attrs, flags=re.I) or re.search(r'data-baths="(\d+)"', block, flags=re.I)
            m_car = re.search(r'data-cars="(\d+)"', attrs, flags=re.I) or re.search(r'data-cars="(\d+)"', block, flags=re.I)
            m_img = re.search(r'<img[^>]+src="([^"]+)"', block, flags=re.I)

            rel_url = m_href.group(1).strip() if m_href else f"/listings/{lid}/"
            full_url = rel_url if rel_url.startswith("http") else f"{cls.base_url}{rel_url}"

            results.append({
                "listing_id": lid,
                "url": full_url,
                "address": clean_html_text(m_addr.group(1)) if m_addr else "",
                "price_text": clean_html_text(m_price.group(1)) if m_price else "",
                "available_date": clean_html_text(m_avail.group(1)) if m_avail else None,
                "agency_office": clean_html_text(m_office.group(1)) if m_office else "Belle Property",
                "bedrooms": int(m_bed.group(1)) if m_bed else None,
                "bathrooms": int(m_bath.group(1)) if m_bath else 1,
                "parking": int(m_car.group(1)) if m_car else 0,
                "images": [m_img.group(1).strip()] if m_img else [],
            })

        return results

    def fetch_listings(self) -> List[Dict[str, Any]]:
        """
        Attempt a single polite standard GET request to the public rental directory.
        If blocked by HTTP 403 WAF, raises HTTPError which is caught and isolated by collect().
        """
        html_text = self._request_url(self.directory_url, timeout=10.0)
        return self.extract_listings_from_html(html_text)[: self.max_listings]

    def parse_listing(self, raw_item: Any) -> Dict[str, Any]:
        """Parse a Belle Property fixture HTML or dict into standard adapter fields."""
        if isinstance(raw_item, str):
            extracted = self.extract_listings_from_html(raw_item)
            if not extracted:
                raise ValueError("No Belle Property listing found in HTML payload")
            item = extracted[0]
        elif isinstance(raw_item, dict):
            item = dict(raw_item)
        else:
            raise ValueError(f"Unsupported Belle Property raw_item type: {type(raw_item)}")

        listing_id = str(item.get("listing_id") or item.get("id") or item.get("sku") or "").strip()
        url = str(item.get("url") or "").strip()
        if not listing_id and url:
            m_id = re.search(r"/(\d+)/?$", url)
            if m_id:
                listing_id = m_id.group(1)
        if not listing_id:
            raise ValueError("Belle Property listing missing listing_id")

        if url.startswith("/"):
            url = f"{self.base_url}{url}"
        elif not url:
            url = f"{self.base_url}/listings/{listing_id}/"

        address = clean_html_text(item.get("address") or item.get("name") or "")
        suburb, postcode = extract_suburb_and_postcode(
            address,
            fallback_suburb=str(item.get("suburb") or ""),
            fallback_postcode=str(item.get("postcode") or ""),
        )

        price_text = str(item.get("price_text") or item.get("price") or "").strip()
        weekly_rent = parse_weekly_rent(
            item.get("weekly_rent") if item.get("weekly_rent") is not None else price_text
        )

        available_date = parse_availability_date(item.get("available_date"))
        bedrooms = item.get("bedrooms")
        bathrooms = item.get("bathrooms", 1)
        parking = item.get("parking", 0)
        title = clean_html_text(item.get("title") or address)
        description = clean_html_text(item.get("description") or "")
        prop_type = normalise_property_type(
            item.get("property_type"), title=title, description=description
        )

        images = [str(u).strip() for u in (item.get("images") or []) if str(u).strip()]
        inspection_times = [
            clean_html_text(str(t)) for t in (item.get("inspection_times") or []) if str(t).strip()
        ]
        agency_office = clean_html_text(
            item.get("agency_office") or (f"Belle Property {suburb}" if suburb else "Belle Property")
        )

        return {
            "source": self.source_name,
            "listing_id": listing_id,
            "address": address,
            "suburb": suburb,
            "postcode": postcode,
            "state": str(item.get("state") or "VIC"),
            "weekly_rent": weekly_rent,
            "price_text": price_text or (f"${int(weekly_rent)} per week" if weekly_rent else ""),
            "bedrooms": bedrooms,
            "bathrooms": bathrooms,
            "parking": parking,
            "property_type": prop_type,
            "title": title or address,
            "description": description,
            "images": images,
            "available_date": available_date,
            "inspection_times": inspection_times,
            "url": url,
            "agency_office": agency_office,
            "discovered_at": str(item.get("discovered_at") or datetime.now(timezone.utc).isoformat()),
        }
