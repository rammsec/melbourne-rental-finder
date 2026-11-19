"""
Fletchers Direct Rental Listing Adapter.

Official rental directory:
https://www.fletchers.net.au/properties-for-lease

Extraction method:
- Respects https://www.fletchers.net.au/robots.txt (which allows `/properties-for-lease`
  and specifies `Crawl-delay: 5`).
- Fetches server-rendered `<li data-propertyid="..." class="...">` rental tiles from
  `https://www.fletchers.net.au/properties-for-lease` (72 eastern suburbs rental properties
  on page 1 covering Canterbury, Balwyn, Blackburn, Mitcham, Ringwood, Surrey Hills, etc.).
- Extracts listing ID, property type, street address, suburb, weekly rent, bedrooms,
  bathrooms, parking, images, and canonical property URL.
"""

from __future__ import annotations

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


class FletchersAdapter(BaseAgencyAdapter):
    """Adapter for Fletchers Real Estate Melbourne Eastern Suburbs rental listings."""

    source_name = "Fletchers"
    agency_brand = "Fletchers"
    base_url = "https://fletchers.net.au"
    directory_url = "https://www.fletchers.net.au/properties-for-lease"
    integration_status = "integrated"
    request_delay_seconds = 5.0  # Honour Fletchers robots.txt Crawl-delay: 5

    def __init__(
        self,
        http_fetcher: Optional[Callable[..., str]] = None,
        max_listings: int = 50,
    ) -> None:
        super().__init__(http_fetcher=http_fetcher, max_listings=max_listings)

    @classmethod
    def extract_cards_from_html(cls, html_text: str) -> List[Dict[str, Any]]:
        """Extract rental property cards from Fletchers `/properties-for-lease` HTML."""
        cards: List[Dict[str, Any]] = []
        pattern = re.compile(
            r'<li\s+data-propertyid="(\d+)"(?:\s+class="([^"]*)")?[^>]*>(.*?)</li>',
            flags=re.DOTALL | re.IGNORECASE,
        )
        for m in pattern.finditer(html_text):
            listing_id = m.group(1).strip()
            li_class = (m.group(2) or "").strip()
            block = m.group(3)

            m_href = re.search(
                r'<a\b[^>]*href="(https?://(?:www\.)?fletchers\.net\.au/\d+/[^"]+)"',
                block,
                flags=re.IGNORECASE,
            )
            url = m_href.group(1).strip() if m_href else f"{cls.base_url}/{listing_id}"

            m_sub = re.search(
                r'<span\s+class="suburb"[^>]*>(.*?)</span>',
                block,
                flags=re.DOTALL | re.IGNORECASE,
            )
            suburb_raw = clean_html_text(m_sub.group(1)) if m_sub else ""

            m_street = re.search(
                r'<span\s+class="streetaddress"[^>]*>(.*?)</span>',
                block,
                flags=re.DOTALL | re.IGNORECASE,
            )
            street_raw = clean_html_text(m_street.group(1)) if m_street else ""

            m_price = re.search(
                r'<div\s+class="pricetext"[^>]*>(.*?)</div>',
                block,
                flags=re.DOTALL | re.IGNORECASE,
            )
            price_text = clean_html_text(m_price.group(1)) if m_price else ""
            price_text = re.sub(r"^For\s+Lease\s*", "", price_text, flags=re.IGNORECASE).strip()

            images: List[str] = []
            for m_img in re.finditer(r'<img\b[^>]*src="([^"]+)"', block, flags=re.IGNORECASE):
                img_u = m_img.group(1).strip()
                if img_u and img_u.startswith("http") and img_u not in images:
                    images.append(img_u)

            m_bed = re.search(r'(\d+)\s*<i\s+class="[^"]*fa-bed[^"]*"', block, flags=re.I)
            m_bath = re.search(r'(\d+)\s*<i\s+class="[^"]*fa-bath[^"]*"', block, flags=re.I)
            m_car = re.search(r'(\d+)\s*<i\s+class="[^"]*fa-car[^"]*"', block, flags=re.I)

            m_type_attr = re.search(r'data-property-type="([^"]+)"', block, flags=re.I)
            raw_type = li_class or (m_type_attr.group(1) if m_type_attr else "")

            suburb, postcode = extract_suburb_and_postcode(
                f"{street_raw}, {suburb_raw}", fallback_suburb=suburb_raw
            )
            address = f"{street_raw}, {suburb}, VIC {postcode}".strip(", ") if street_raw else suburb

            cards.append({
                "listing_id": listing_id,
                "url": url,
                "address": address,
                "suburb": suburb,
                "postcode": postcode,
                "price_text": price_text,
                "bedrooms": int(m_bed.group(1)) if m_bed else 1,
                "bathrooms": int(m_bath.group(1)) if m_bath else 1,
                "parking": int(m_car.group(1)) if m_car else 0,
                "property_type": raw_type,
                "images": images,
                "agency_office": f"Fletchers {suburb}" if suburb else "Fletchers Canterbury",
            })

        return cards

    def fetch_listings(self) -> List[Dict[str, Any]]:
        """Fetch server-rendered rental listing cards from Fletchers."""
        html_text = self._request_url(self.directory_url)
        cards = self.extract_cards_from_html(html_text)
        return cards[: self.max_listings]

    def parse_listing(self, raw_item: Any) -> Dict[str, Any]:
        """Parse a Fletchers card dictionary or HTML snippet into standard adapter fields."""
        if isinstance(raw_item, str):
            cards = self.extract_cards_from_html(raw_item)
            if not cards:
                raise ValueError("No Fletchers listing card found in HTML")
            item = dict(cards[0])
        elif isinstance(raw_item, dict):
            item = dict(raw_item)
        else:
            raise ValueError(f"Unsupported Fletchers raw_item type: {type(raw_item)}")

        listing_id = str(item.get("listing_id") or item.get("id") or "").strip()
        if not listing_id:
            raise ValueError("Fletchers listing missing listing_id")

        address = clean_html_text(item.get("address") or "")
        suburb, postcode = extract_suburb_and_postcode(
            address,
            fallback_suburb=str(item.get("suburb") or ""),
            fallback_postcode=str(item.get("postcode") or ""),
        )
        if postcode and postcode not in address:
            address = f"{address} {postcode}".strip()

        price_text = str(item.get("price_text") or "").strip()
        weekly_rent = parse_weekly_rent(
            item.get("weekly_rent") if item.get("weekly_rent") is not None else price_text
        )

        title = clean_html_text(item.get("title") or address)
        description = clean_html_text(item.get("description") or "")
        prop_type = normalise_property_type(item.get("property_type"), title=title, description=description)

        images = [str(u).strip() for u in (item.get("images") or []) if str(u).strip()]
        available_date = parse_availability_date(item.get("available_date"))
        url = str(item.get("url") or f"{self.base_url}/{listing_id}").strip()
        agency_office = clean_html_text(
            item.get("agency_office") or (f"Fletchers {suburb}" if suburb else "Fletchers")
        )

        return {
            "source": self.source_name,
            "listing_id": listing_id,
            "address": address,
            "suburb": suburb,
            "postcode": postcode,
            "state": "VIC",
            "weekly_rent": weekly_rent,
            "price_text": price_text or (f"${int(weekly_rent)} pw" if weekly_rent else ""),
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
