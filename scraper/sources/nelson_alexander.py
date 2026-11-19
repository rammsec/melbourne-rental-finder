"""
Nelson Alexander Direct Rental Listing Adapter.

Official rental directory:
https://www.nelsonalexander.com.au/rent/properties-for-lease/

Extraction method:
- Parses server-rendered property cards (`<div class="property-card ...">`) from
  `https://www.nelsonalexander.com.au/rent/properties-for-lease/?page=1..N`.
- For listings within the Melbourne budget criteria, optionally enriches from the
  individual property detail page `/property/<id>/<slug>/` which exposes Schema.org
  JSON-LD (`@type: "Residence"` and `@type: "Event"` for inspections), availability date,
  and office identifier.
"""

from __future__ import annotations

import json
import re
import time
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


OFFICE_CODE_MAP = {
    "LO-NAHAWTHORN": "Nelson Alexander Hawthorn",
    "LO-NAKEW": "Nelson Alexander Kew",
    "LO-NARICHMOND": "Nelson Alexander Richmond",
    "LO-NAFITZROY": "Nelson Alexander Fitzroy",
    "LO-NACARLTON": "Nelson Alexander Carlton North",
    "LO-NABRUNSWICK": "Nelson Alexander Brunswick",
    "LO-NANORTHCOTE": "Nelson Alexander Northcote",
    "LO-NAIVANHOE": "Nelson Alexander Ivanhoe",
    "LO-NAASCOTVALE": "Nelson Alexander Ascot Vale",
    "LO-NAESSENDON": "Nelson Alexander Essendon",
    "LO-NAFLEMINGTON": "Nelson Alexander Flemington",
    "LO-NACOBURG": "Nelson Alexander Coburg",
    "LO-NAPRESTON": "Nelson Alexander Preston",
}


class NelsonAlexanderAdapter(BaseAgencyAdapter):
    """Adapter for Nelson Alexander rental listings."""

    source_name = "Nelson Alexander"
    agency_brand = "Nelson Alexander"
    base_url = "https://www.nelsonalexander.com.au"
    directory_url = "https://www.nelsonalexander.com.au/rent/properties-for-lease/"
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
        """Extract individual card data dictionaries from a Nelson Alexander directory HTML page."""
        cards: List[Dict[str, Any]] = []
        blocks = re.findall(
            r'<div class="property-card\b[^"]*">(.*?)(?=<div class="property-card\b|</section>|\Z)',
            html_text,
            flags=re.DOTALL | re.IGNORECASE,
        )
        for block in blocks:
            m_link = re.search(
                r'<a\s+class="property-card-url"\s+href="(/property/(\d+)/[^"]+)"(?:\s+title="([^"]*)")?',
                block,
                flags=re.IGNORECASE,
            )
            if not m_link:
                continue

            rel_url = m_link.group(1).strip()
            listing_id = m_link.group(2).strip()
            title_attr = clean_html_text(m_link.group(3) or "")

            m_h2 = re.search(r"<h2>(.*?)</h2>", block, flags=re.DOTALL | re.IGNORECASE)
            address = clean_html_text(m_h2.group(1)) if m_h2 else title_attr

            m_p = re.search(
                r'<div class="property-details">.*?<p>(.*?)</p>',
                block,
                flags=re.DOTALL | re.IGNORECASE,
            )
            price_line = clean_html_text(m_p.group(1)) if m_p else ""

            m_bed = re.search(r"icon-bed-secondary[^>]*></i>\s*<span>(\d+)</span>", block, flags=re.I)
            m_bath = re.search(r"icon-bath-secondary[^>]*></i>\s*<span>(\d+)</span>", block, flags=re.I)
            m_car = re.search(r"icon-car-secondary[^>]*></i>\s*<span>(\d+)</span>", block, flags=re.I)

            m_img = re.search(r'data-bgset="([^"]+)"', block, flags=re.I)
            image_url = m_img.group(1).split()[0].strip() if m_img else ""

            # Check if price_line starts with DD/MM/YYYY availability date
            avail_date = None
            m_date_prefix = re.search(r"\b(\d{1,2}/\d{1,2}/\d{4})\b", price_line)
            if m_date_prefix:
                avail_date = m_date_prefix.group(1)

            cards.append({
                "listing_id": listing_id,
                "url": f"{cls.base_url}{rel_url}",
                "address": address,
                "price_text": price_line,
                "available_date": avail_date,
                "bedrooms": int(m_bed.group(1)) if m_bed else 1,
                "bathrooms": int(m_bath.group(1)) if m_bath else 1,
                "parking": int(m_car.group(1)) if m_car else 0,
                "images": [image_url] if image_url else [],
            })
        return cards

    @classmethod
    def extract_detail_enrichment(cls, detail_html: str) -> Dict[str, Any]:
        """Extract Schema.org JSON-LD Residence, Event inspections, availability, and office from detail HTML."""
        enrichment: Dict[str, Any] = {}

        # 1. JSON-LD blocks
        ld_blocks = re.findall(
            r'<script\s+type="application/ld\+json"[^>]*>(.*?)</script>',
            detail_html,
            flags=re.DOTALL | re.IGNORECASE,
        )
        inspections: List[str] = []
        for ld_raw in ld_blocks:
            try:
                data = json.loads(ld_raw.strip())
            except Exception:
                continue
            items = data if isinstance(data, list) else [data]
            for obj in items:
                if not isinstance(obj, dict):
                    continue
                t = obj.get("@type")
                if t == "Residence":
                    if obj.get("description"):
                        enrichment["description"] = clean_html_text(obj["description"])
                    if obj.get("url"):
                        enrichment["url"] = str(obj["url"]).strip()
                    photos = obj.get("photos") or obj.get("image") or []
                    if isinstance(photos, list):
                        imgs = [str(p).strip() for p in photos if isinstance(p, str) and p.strip()]
                        if imgs:
                            enrichment["images"] = imgs
                    addr_obj = obj.get("address")
                    if isinstance(addr_obj, dict):
                        street = str(addr_obj.get("streetAddress") or "").strip()
                        sub = str(addr_obj.get("addressLocality") or "").strip()
                        state = str(addr_obj.get("addressRegion") or "VIC").strip()
                        pc = str(addr_obj.get("postalCode") or "").strip()
                        if sub:
                            enrichment["suburb"] = sub
                        if pc:
                            enrichment["postcode"] = pc
                        if street and sub:
                            enrichment["address"] = f"{street}, {sub} {state} {pc}".strip()
                elif t == "Event" and "inspection" in str(obj.get("name") or "").lower():
                    start_d = str(obj.get("startDate") or "").strip()
                    end_d = str(obj.get("endDate") or "").strip()
                    if start_d and end_d:
                        inspections.append(f"{start_d} - {end_d}")
                    elif start_d:
                        inspections.append(start_d)

        if inspections:
            enrichment["inspection_times"] = inspections

        # 2. Available date heading: <h2>Available</h2> <h3>Friday 27th November 2026</h3>
        m_avail = re.search(
            r"<h2>\s*Available\s*</h2>\s*<h3>(.*?)</h3>",
            detail_html,
            flags=re.DOTALL | re.IGNORECASE,
        )
        if m_avail:
            enrichment["available_date"] = clean_html_text(m_avail.group(1))

        # 3. Price heading: <h2>Price</h2> <h3>$575pw / $2499pcm</h3>
        m_price = re.search(
            r"<h2>\s*Price\s*</h2>\s*<h3>(.*?)</h3>",
            detail_html,
            flags=re.DOTALL | re.IGNORECASE,
        )
        if m_price:
            enrichment["price_text"] = clean_html_text(m_price.group(1))

        # 4. Agency office code from 2apply link or page metadata
        m_office = re.search(r"agentID=(LO-NA[A-Z0-9_-]+)", detail_html, flags=re.IGNORECASE)
        if m_office:
            code = m_office.group(1).upper()
            enrichment["agency_office"] = OFFICE_CODE_MAP.get(
                code, f"Nelson Alexander ({code.replace('LO-NA', '').title()})"
            )

        return enrichment

    def fetch_listings(self) -> List[Dict[str, Any]]:
        """Fetch Nelson Alexander rental cards and enrich top budget-matching items."""
        discovered: Dict[str, Dict[str, Any]] = {}
        first_error: Optional[Exception] = None

        for page in range(1, self.max_pages + 1):
            if len(discovered) >= self.max_listings:
                break
            page_url = self.directory_url if page == 1 else f"{self.directory_url}?page={page}"
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
                if page == 1:
                    first_error = e
                break

        if not discovered and first_error is not None:
            raise first_error

        # Enrich budget-aligned listings with detail page JSON-LD
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
        """Parse a Nelson Alexander card dict or raw HTML (directory or detail page)."""
        if isinstance(raw_item, str):
            cards = self.extract_cards_from_directory_html(raw_item)
            enrichment = self.extract_detail_enrichment(raw_item)
            if cards:
                item = dict(cards[0])
                item.update({k: v for k, v in enrichment.items() if v})
            elif enrichment.get("url") or enrichment.get("address"):
                item = enrichment
                m_id = re.search(r"/property/(\d+)/", str(item.get("url") or ""))
                if m_id:
                    item["listing_id"] = m_id.group(1)
            else:
                raise ValueError("Unable to extract Nelson Alexander listing from HTML")
        elif isinstance(raw_item, dict):
            item = dict(raw_item)
        else:
            raise ValueError(f"Unsupported Nelson Alexander raw_item type: {type(raw_item)}")

        listing_id = str(item.get("listing_id") or item.get("id") or "").strip()
        if not listing_id:
            m_id = re.search(r"/property/(\d+)/", str(item.get("url") or ""))
            if m_id:
                listing_id = m_id.group(1)
        if not listing_id:
            raise ValueError("Nelson Alexander listing missing listing_id")

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

        avail_raw = item.get("available_date")
        if not avail_raw and price_text:
            m_date = re.search(r"\b(\d{1,2}/\d{1,2}/\d{4})\b", price_text)
            if m_date:
                avail_raw = m_date.group(1)
        available_date = parse_availability_date(avail_raw)

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
        url = str(item.get("url") or f"{self.base_url}/property/{listing_id}/").strip()
        if url.startswith("/"):
            url = f"{self.base_url}{url}"

        agency_office = clean_html_text(
            item.get("agency_office") or (f"Nelson Alexander {suburb}" if suburb else "Nelson Alexander")
        )

        return {
            "source": self.source_name,
            "listing_id": listing_id,
            "address": address,
            "suburb": suburb,
            "postcode": postcode,
            "state": "VIC",
            "weekly_rent": weekly_rent,
            "price_text": price_text or (f"${int(weekly_rent)}pw" if weekly_rent else ""),
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
