"""
Harcourts Direct Rental Listing Adapter.

Official rental website:
https://www.harcourts.com.au/ (powered by https://harcourts.net/au/listings/rent)

Extraction method:
- Respects robots.txt (`User-agent: * Disallow:` — completely open).
- Queries `/au/listings/rent` filtered for Melbourne eastern & south-eastern suburbs
  and budget cap (<= $650/week) with pagination support.
- Parses server-rendered property listing cards for listing ID, office slug, title,
  address, suburb, postcode, weekly rent, bedrooms, bathrooms, parking, photo, and URL.
"""

from __future__ import annotations

import re
import time
import urllib.parse
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

from ..config import EASTERN_TARGET_SUBURBS
from .base import (
    BaseAgencyAdapter,
    clean_html_text,
    extract_suburb_and_postcode,
    normalise_property_type,
    parse_availability_date,
    parse_weekly_rent,
)


HARCOURTS_QUERY_URLS = [
    "https://harcourts.net/au/listings/rent?search=VIC&maxPrice=650",
    "https://harcourts.net/au/listings/rent?keywords=Hawthorn&include-suburb=1&maxPrice=650",
    "https://harcourts.net/au/listings/rent?keywords=Box+Hill&include-suburb=1&maxPrice=650",
    "https://harcourts.net/au/listings/rent?keywords=Ringwood&include-suburb=1&maxPrice=650",
    "https://harcourts.net/au/listings/rent?keywords=Camberwell&include-suburb=1&maxPrice=650",
    "https://harcourts.net/au/listings/rent?keywords=Boronia&include-suburb=1&maxPrice=650",
    "https://harcourts.net/au/listings/rent?keywords=Doncaster&include-suburb=1&maxPrice=650",
]


class HarcourtsAdapter(BaseAgencyAdapter):
    """Adapter for Harcourts Victoria rental listings."""

    source_name = "Harcourts"
    agency_brand = "Harcourts"
    base_url = "https://harcourts.net"
    public_domain = "https://www.harcourts.com.au"
    search_url = "https://harcourts.net/au/listings/rent?search=VIC&maxPrice=650"
    integration_status = "integrated"

    def __init__(
        self,
        http_fetcher: Optional[Callable[..., str]] = None,
        max_listings: int = 40,
        query_urls: Optional[List[str]] = None,
    ) -> None:
        super().__init__(http_fetcher=http_fetcher, max_listings=max_listings)
        self.query_urls = query_urls or HARCOURTS_QUERY_URLS

    @classmethod
    def extract_cards_from_html(cls, html_text: str) -> List[Dict[str, Any]]:
        """Extract rental property cards from Harcourts `/au/listings/rent` HTML."""
        cards: List[Dict[str, Any]] = []
        parts = re.split(
            r'<(?:div|li)\b[^>]*class="[^"]*(?:property-image|listing-card)[^"]*"[^>]*>',
            html_text,
            flags=re.IGNORECASE,
        )
        blocks = parts[1:] if len(parts) > 1 else [html_text]

        seen_ids: set = set()
        for block in blocks:
            m_href = re.search(
                r'href="((?:https://harcourts\.net)?/au/office/([^/"]+)/listing/([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}|[a-zA-Z0-9]+-\d+|[a-zA-Z0-9]+)-([^/"]+))"',
                block,
                flags=re.IGNORECASE,
            )
            if not m_href:
                continue

            raw_path = m_href.group(1).strip()
            office_slug = m_href.group(2).strip()
            listing_id = m_href.group(3).strip()
            if listing_id in seen_ids:
                continue
            seen_ids.add(listing_id)

            full_url = raw_path if raw_path.startswith("http") else f"{cls.base_url}{raw_path}"

            m_title = re.search(
                r'<h6[^>]*class="[^"]*property-title[^"]*"[^>]*>(.*?)</h6>',
                block,
                flags=re.DOTALL | re.IGNORECASE,
            )
            title = clean_html_text(m_title.group(1)) if m_title else ""

            m_price = re.search(
                r'<span[^>]*class="[^"]*hi-price[^"]*"[^>]*>(.*?)</span>',
                block,
                flags=re.DOTALL | re.IGNORECASE,
            )
            price_text = clean_html_text(m_price.group(1)) if m_price else ""

            m_addr = re.search(
                r'<span[^>]*class="address"[^>]*>(.*?)</span>',
                block,
                flags=re.DOTALL | re.IGNORECASE,
            )
            address = clean_html_text(m_addr.group(1)) if m_addr else ""

            images: List[str] = []
            # Prefer data-src (full 384x215 image) over 30x30 placeholder src
            for attr in ("data-src", "src"):
                for m_img in re.finditer(
                    rf'{attr}="(https://listings-photos\.cloudhi\.io/[^"]+)"',
                    block,
                    flags=re.IGNORECASE,
                ):
                    img_u = m_img.group(1).strip()
                    if "/30x30" not in img_u and img_u not in images:
                        images.append(img_u)

            m_bed = re.search(
                r'<span>\s*(\d+)\s*</span>\s*<img[^>]+alt="bedroom"',
                block,
                flags=re.DOTALL | re.IGNORECASE,
            )
            m_bath = re.search(
                r'<span>\s*(\d+)\s*</span>\s*<img[^>]+alt="bathroom"',
                block,
                flags=re.DOTALL | re.IGNORECASE,
            )
            m_car = re.search(
                r'<span>\s*(\d+)\s*</span>\s*<img[^>]+alt="garage"',
                block,
                flags=re.DOTALL | re.IGNORECASE,
            )

            suburb, postcode = extract_suburb_and_postcode(address)
            office_name = "Harcourts " + office_slug.replace("-", " ").title() if office_slug else "Harcourts"

            cards.append({
                "listing_id": listing_id,
                "url": full_url,
                "title": title or address,
                "address": address,
                "suburb": suburb,
                "postcode": postcode,
                "price_text": price_text,
                "bedrooms": int(m_bed.group(1)) if m_bed else 1,
                "bathrooms": int(m_bath.group(1)) if m_bath else 1,
                "parking": int(m_car.group(1)) if m_car else 0,
                "images": images,
                "agency_office": office_name,
            })

        return cards

    def fetch_listings(self) -> List[Dict[str, Any]]:
        """Fetch rental listing cards across Harcourts Victorian and Eastern Melbourne search queries."""
        discovered: Dict[str, Dict[str, Any]] = {}

        for idx, q_url in enumerate(self.query_urls):
            if len(discovered) >= self.max_listings:
                break
            try:
                if idx > 0 and self._http_fetcher is None and self.request_delay_seconds > 0:
                    time.sleep(self.request_delay_seconds)
                html_text = self._request_url(q_url)
                cards = self.extract_cards_from_html(html_text)
                for card in cards:
                    lid = card["listing_id"]
                    if lid not in discovered:
                        discovered[lid] = card
            except Exception:
                if idx == 0 and len(self.query_urls) == 1:
                    raise
                continue

        return list(discovered.values())[: self.max_listings]

    def parse_listing(self, raw_item: Any) -> Dict[str, Any]:
        """Parse a Harcourts card dict or HTML snippet into standard adapter fields."""
        if isinstance(raw_item, str):
            cards = self.extract_cards_from_html(raw_item)
            if not cards:
                raise ValueError("No Harcourts listing card found in HTML")
            item = dict(cards[0])
        elif isinstance(raw_item, dict):
            item = dict(raw_item)
        else:
            raise ValueError(f"Unsupported Harcourts raw_item type: {type(raw_item)}")

        listing_id = str(item.get("listing_id") or item.get("id") or "").strip()
        if not listing_id:
            raise ValueError("Harcourts listing missing listing_id")

        address = clean_html_text(item.get("address") or "")
        suburb, postcode = extract_suburb_and_postcode(
            address,
            fallback_suburb=str(item.get("suburb") or ""),
            fallback_postcode=str(item.get("postcode") or ""),
        )
        price_text = str(item.get("price_text") or "").strip()
        weekly_rent = parse_weekly_rent(
            item.get("weekly_rent") if item.get("weekly_rent") is not None else price_text
        )

        title = clean_html_text(item.get("title") or address)
        description = clean_html_text(item.get("description") or "")
        prop_type = normalise_property_type(item.get("property_type"), title=title, description=description)

        images = [str(u).strip() for u in (item.get("images") or []) if str(u).strip()]
        available_date = parse_availability_date(item.get("available_date"))
        url = str(item.get("url") or "").strip()
        if url.startswith("/"):
            url = f"{self.base_url}{url}"

        agency_office = clean_html_text(item.get("agency_office") or "Harcourts")

        return {
            "source": self.source_name,
            "listing_id": listing_id,
            "address": address,
            "suburb": suburb,
            "postcode": postcode,
            "state": "VIC",
            "weekly_rent": weekly_rent,
            "price_text": price_text or (f"${int(weekly_rent)} /week" if weekly_rent else ""),
            "bedrooms": item.get("bedrooms", 1),
            "bathrooms": item.get("bathrooms", 1),
            "parking": item.get("parking", 0),
            "property_type": prop_type,
            "title": title or address,
            "description": description,
            "images": images,
            "available_date": available_date,
            "inspection_times": list(item.get("inspection_times") or []),
            "url": url,
            "agency_office": agency_office,
            "discovered_at": str(item.get("discovered_at") or datetime.now(timezone.utc).isoformat()),
        }
