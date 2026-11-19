"""
Woodards Direct Rental Listing Adapter.

Official rental directory:
https://www.woodards.com.au/property/?category=Rent

Extraction method:
- Parses server-rendered property cards (`<div class="property-list-item card-item">`)
  from `https://www.woodards.com.au/property/?category=Rent` (and paginated `&start=18`).
- Enriches budget-aligned listings from individual detail pages
  `/property/<slug>-<postcode>-<id>/` for property type, inspection times, description,
  and office attribution.
"""

from __future__ import annotations

import re
import time
import urllib.parse
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


class WoodardsAdapter(BaseAgencyAdapter):
    """Adapter for Woodards rental listings."""

    source_name = "Woodards"
    agency_brand = "Woodards"
    base_url = "https://www.woodards.com.au"
    directory_url = "https://www.woodards.com.au/property/?category=Rent"
    integration_status = "integrated"

    def __init__(
        self,
        http_fetcher: Optional[Callable[..., str]] = None,
        max_listings: int = 36,
        max_pages: int = 2,
        max_detail_fetches: int = 6,
    ) -> None:
        super().__init__(http_fetcher=http_fetcher, max_listings=max_listings)
        self.max_pages = max_pages
        self.max_detail_fetches = max_detail_fetches

    @classmethod
    def extract_cards_from_directory_html(cls, html_text: str) -> List[Dict[str, Any]]:
        """Extract rental property cards from Woodards directory HTML."""
        cards: List[Dict[str, Any]] = []
        pattern = re.compile(
            r'<a\s+href="(/property/([^"]+?)-(\d{4})-(\d+)/?)"[^>]*>\s*<div class="property-list-item card-item">(.*?)</div>\s*</a>',
            flags=re.DOTALL | re.IGNORECASE,
        )
        for m in pattern.finditer(html_text):
            rel_url = m.group(1).strip()
            postcode = m.group(3).strip()
            listing_id = m.group(4).strip()
            block = m.group(5)

            m_img = re.search(r'<img\s+src="([^"]+)"', block, flags=re.I)
            img_url = m_img.group(1).strip() if m_img else ""

            m_status = re.search(
                r'<div class="status-label">(.*?)</div>',
                block,
                flags=re.DOTALL | re.I,
            )
            status_text = clean_html_text(m_status.group(1)) if m_status else ""

            m_title = re.search(
                r'<div class="title">(.*?)</div>',
                block,
                flags=re.DOTALL | re.I,
            )
            suburb = clean_html_text(m_title.group(1)) if m_title else ""

            m_sub = re.search(
                r'<p class="subtitle">(.*?)</p>',
                block,
                flags=re.DOTALL | re.I,
            )
            street = clean_html_text(m_sub.group(1)) if m_sub else ""

            m_price = re.search(
                r'<div class="price">(.*?)</div>',
                block,
                flags=re.DOTALL | re.I,
            )
            price_text = clean_html_text(m_price.group(1)) if m_price else ""

            m_bed = re.search(
                r"<li>\s*<span>(\d+)</span>\s*<span class=\"icons bedroom-icon\">",
                block,
                flags=re.I,
            )
            m_bath = re.search(
                r"<li>\s*<span>(\d+)</span>\s*<span class=\"icons bathroom-icon\">",
                block,
                flags=re.I,
            )
            m_car = re.search(
                r"<li>\s*<span>(\d+)</span>\s*<span class=\"icons parking-icon\">",
                block,
                flags=re.I,
            )

            address = f"{street}, {suburb}, VIC {postcode}".strip(", ")

            cards.append({
                "listing_id": listing_id,
                "url": f"{cls.base_url}{rel_url}",
                "address": address,
                "suburb": suburb,
                "postcode": postcode,
                "price_text": price_text,
                "available_date": status_text if status_text else None,
                "bedrooms": int(m_bed.group(1)) if m_bed else 1,
                "bathrooms": int(m_bath.group(1)) if m_bath else 1,
                "parking": int(m_car.group(1)) if m_car else 0,
                "images": [img_url] if img_url else [],
            })
        return cards

    @classmethod
    def extract_detail_enrichment(cls, detail_html: str) -> Dict[str, Any]:
        """Extract property type, inspection times, description, and office from Woodards detail HTML."""
        enrichment: Dict[str, Any] = {}

        # 1. Property Type
        m_type = re.search(
            r'<div class="title">\s*Property Type\s*</div>\s*<p class="subtitle">(.*?)</p>',
            detail_html,
            flags=re.DOTALL | re.IGNORECASE,
        )
        if m_type:
            enrichment["property_type"] = clean_html_text(m_type.group(1))

        # 2. Inspection times
        m_insp_section = re.search(
            r'<div class="title">\s*Inspection times\s*</div>(.*?)</div>\s*</div>',
            detail_html,
            flags=re.DOTALL | re.IGNORECASE,
        )
        if m_insp_section:
            times = re.findall(
                r'<p class="mr-auto[^"]*">(.*?)</p>',
                m_insp_section.group(1),
                flags=re.DOTALL | re.IGNORECASE,
            )
            cleaned_times = [clean_html_text(t) for t in times if clean_html_text(t)]
            if cleaned_times:
                enrichment["inspection_times"] = cleaned_times

        # 3. Description
        m_og_desc = re.search(
            r'<meta\s+property="og:description"\s+content="([^"]+)"',
            detail_html,
            flags=re.IGNORECASE,
        )
        if m_og_desc:
            enrichment["description"] = clean_html_text(m_og_desc.group(1))

        # 4. All images from gallery
        gallery_imgs = re.findall(
            r'href="(https://images\.listonce\.com\.au/[^"]+)"',
            detail_html,
            flags=re.IGNORECASE,
        )
        if gallery_imgs:
            dedup_imgs: List[str] = []
            for u in gallery_imgs:
                if u not in dedup_imgs:
                    dedup_imgs.append(u)
            enrichment["images"] = dedup_imgs[:10]

        # 5. Office from 2apply link
        m_office = re.search(
            r"2apply\.com\.au/agency/([^?&\"']+)",
            detail_html,
            flags=re.IGNORECASE,
        )
        if m_office:
            decoded_office = urllib.parse.unquote(m_office.group(1)).strip()
            decoded_office = re.sub(r"(?i)^woodards\s*", "Woodards ", decoded_office).strip()
            enrichment["agency_office"] = decoded_office.title()

        return enrichment

    def fetch_listings(self) -> List[Dict[str, Any]]:
        """Fetch Woodards rental cards and enrich budget-matching listings."""
        discovered: Dict[str, Dict[str, Any]] = {}
        first_error: Optional[Exception] = None

        for page_idx in range(self.max_pages):
            if len(discovered) >= self.max_listings:
                break
            start_offset = page_idx * 18
            page_url = (
                self.directory_url
                if start_offset == 0
                else f"{self.directory_url}&start={start_offset}"
            )
            try:
                html_text = self._request_url(page_url)
                cards = self.extract_cards_from_directory_html(html_text)
                if not cards:
                    break
                for card in cards:
                    lid = card["listing_id"]
                    if lid not in discovered:
                        discovered[lid] = card
            except Exception as e:
                if page_idx == 0:
                    first_error = e
                break

        if not discovered and first_error is not None:
            raise first_error

        detail_count = 0
        for lid, card in list(discovered.items()):
            if detail_count >= self.max_detail_fetches:
                break
            wk_rent = parse_weekly_rent(card.get("price_text"))
            if wk_rent is not None and 200 <= wk_rent <= 650 and card.get("url"):
                try:
                    if self._http_fetcher is None and self.request_delay_seconds > 0:
                        time.sleep(self.request_delay_seconds)
                    detail_html = self._request_url(card["url"])
                    enrichment = self.extract_detail_enrichment(detail_html)
                    card.update({k: v for k, v in enrichment.items() if v})
                    detail_count += 1
                except Exception:
                    continue

        return list(discovered.values())[: self.max_listings]

    def parse_listing(self, raw_item: Any) -> Dict[str, Any]:
        """Parse a Woodards card dictionary or raw HTML into standard fields."""
        if isinstance(raw_item, str):
            cards = self.extract_cards_from_directory_html(raw_item)
            enrichment = self.extract_detail_enrichment(raw_item)
            if cards:
                item = dict(cards[0])
                item.update({k: v for k, v in enrichment.items() if v})
            elif enrichment:
                item = enrichment
            else:
                raise ValueError("Unable to extract Woodards listing from HTML")
        elif isinstance(raw_item, dict):
            item = dict(raw_item)
        else:
            raise ValueError(f"Unsupported Woodards raw_item type: {type(raw_item)}")

        listing_id = str(item.get("listing_id") or item.get("id") or "").strip()
        if not listing_id:
            m_id = re.search(r"-(\d+)/?$", str(item.get("url") or ""))
            if m_id:
                listing_id = m_id.group(1)
        if not listing_id:
            raise ValueError("Woodards listing missing listing_id")

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

        available_date = parse_availability_date(item.get("available_date"))
        bedrooms = item.get("bedrooms", 1)
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
        url = str(item.get("url") or "").strip()
        if url.startswith("/"):
            url = f"{self.base_url}{url}"

        agency_office = clean_html_text(
            item.get("agency_office") or (f"Woodards {suburb}" if suburb else "Woodards")
        )

        return {
            "source": self.source_name,
            "listing_id": listing_id,
            "address": address,
            "suburb": suburb,
            "postcode": postcode,
            "state": "VIC",
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
