"""
Jellis Craig Direct Rental Listing Adapter.

Official rental directory:
https://www.jelliscraig.com.au/rent/list

Extraction method:
- Queries the public `/rent/list` page filtered for Hawthorn corridor suburbs and
  Melbourne budget criteria (strictly respecting robots.txt, which disallows
  `/searchJsonProperty` and `/get-listing-map`).
- Parses `<article>` property cards and optionally enriches from `/property-details-<slug>/<id>`
  for availability dates, base64 full descriptions, and office codes.
"""

from __future__ import annotations

import base64
import json
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


JC_TARGET_SUBURBS = [
    "Hawthorn",
    "Hawthorn East",
    "Richmond",
    "Camberwell",
    "Kew",
    "Surrey Hills",
    "Box Hill",
    "Blackburn",
    "Nunawading",
    "Mitcham",
    "Ringwood",
    "Bayswater",
    "Boronia",
    "Melbourne",
    "East Melbourne",
    "Collingwood",
    "Abbotsford",
    "South Yarra",
    "Malvern",
    "Armadale",
    "Toorak",
]

JC_OFFICE_MAP = {
    "LO-JCBM-RICH": "Jellis Craig Richmond",
    "LO-JCBM-HAWT": "Jellis Craig Hawthorn",
    "LO-JCBM-BORO": "Jellis Craig Boroondara",
    "LO-JCBM-WHIT": "Jellis Craig Whitehorse",
    "LO-JCBM-RING": "Jellis Craig Ringwood",
    "LO-JCBM-DONC": "Jellis Craig Doncaster",
    "LO-JCBM-FITZ": "Jellis Craig Fitzroy",
    "LO-JCBM-SYAR": "Jellis Craig South Yarra",
    "LO-JCBM-ARM": "Jellis Craig Armadale",
}


class JellisCraigAdapter(BaseAgencyAdapter):
    """Adapter for Jellis Craig rental listings."""

    source_name = "Jellis Craig"
    agency_brand = "Jellis Craig"
    base_url = "https://www.jelliscraig.com.au"
    list_endpoint = "https://www.jelliscraig.com.au/rent/list"
    integration_status = "integrated"

    def __init__(
        self,
        http_fetcher: Optional[Callable[..., str]] = None,
        max_listings: int = 30,
        max_detail_fetches: int = 6,
    ) -> None:
        super().__init__(http_fetcher=http_fetcher, max_listings=max_listings)
        self.max_detail_fetches = max_detail_fetches

    def build_search_url(self) -> str:
        """Build the robot-compliant `/rent/list` URL for Hawthorn corridor suburbs."""
        suburb_param = ";".join(urllib.parse.quote(s) for s in JC_TARGET_SUBURBS)
        return f"{self.list_endpoint}?suburb={suburb_param}&max_price=625"

    @classmethod
    def extract_cards_from_list_html(cls, html_text: str) -> List[Dict[str, Any]]:
        """Extract rental listing cards from Jellis Craig `/rent/list` HTML."""
        cards: List[Dict[str, Any]] = []
        articles = re.findall(r"<article\b[^>]*>(.*?)</article>", html_text, flags=re.DOTALL | re.IGNORECASE)
        for art in articles:
            m_href = re.search(
                r'href="((?:https://www\.jelliscraig\.com\.au)?/property-details-[^"]+/(\d+))"',
                art,
                flags=re.IGNORECASE,
            )
            if not m_href:
                continue

            raw_url = m_href.group(1).strip()
            listing_id = m_href.group(2).strip()
            full_url = raw_url if raw_url.startswith("http") else f"{cls.base_url}{raw_url}"

            # Image and alt text (often contains "Street Suburb Postcode")
            images: List[str] = []
            alt_address = ""
            for m_img in re.finditer(r'<img\b[^>]*>', art, flags=re.IGNORECASE):
                tag = m_img.group(0)
                m_src = re.search(r'src="(https://images\.listonce\.com\.au/[^"]+)"', tag, flags=re.I)
                if m_src:
                    img_u = m_src.group(1).strip()
                    if img_u not in images:
                        images.append(img_u)
                m_alt = re.search(r'alt="([^"]+)"', tag, flags=re.I)
                if m_alt and not alt_address:
                    cand_alt = clean_html_text(m_alt.group(1))
                    if cand_alt and "jellis craig" not in cand_alt.lower():
                        alt_address = cand_alt

            m_h4 = re.search(r"<h4[^>]*>(.*?)</h4>", art, flags=re.DOTALL | re.I)
            street = clean_html_text(m_h4.group(1)) if m_h4 else ""

            m_sub = re.search(
                r"<h4[^>]*>.*?</h4>\s*<p[^>]*>(.*?)</p>",
                art,
                flags=re.DOTALL | re.I,
            )
            suburb = clean_html_text(m_sub.group(1)) if m_sub else ""

            postcode = ""
            if alt_address:
                m_pc = re.search(r"\b(3\d{3})\b", alt_address)
                if m_pc:
                    postcode = m_pc.group(1)

            if street and suburb:
                address = f"{street}, {suburb}, VIC {postcode}".strip()
            else:
                address = alt_address or street or suburb

            m_rent = re.search(
                r"(?:Rent:\s*)?(\$\s*[\d,]+(?:\.\d+)?\s*(?:pw|per\s+week|/wk)?)",
                art,
                flags=re.IGNORECASE,
            )
            price_text = clean_html_text(m_rent.group(1)) if m_rent else ""

            m_bed = re.search(r'aria-label="(\d+)\s*Bed', art, flags=re.I)
            m_bath = re.search(r'aria-label="(\d+)\s*Bath', art, flags=re.I)
            m_car = re.search(r'aria-label="(\d+)\s*Car', art, flags=re.I)

            cards.append({
                "listing_id": listing_id,
                "url": full_url,
                "address": address,
                "suburb": suburb,
                "postcode": postcode,
                "price_text": price_text,
                "bedrooms": int(m_bed.group(1)) if m_bed else 1,
                "bathrooms": int(m_bath.group(1)) if m_bath else 1,
                "parking": int(m_car.group(1)) if m_car else 0,
                "images": images,
            })
        return cards

    @classmethod
    def extract_detail_enrichment(cls, detail_html: str) -> Dict[str, Any]:
        """Extract availability date, full description, inspection times, and office from detail HTML."""
        enrichment: Dict[str, Any] = {}

        # 1. FOR LEASE - Available November 27th 2026
        m_avail = re.search(
            r"FOR\s+LEASE\s*-\s*Available\s+([^<\n\r]+)",
            detail_html,
            flags=re.IGNORECASE,
        )
        if m_avail:
            enrichment["available_date"] = clean_html_text(m_avail.group(1))

        # 2. Base64-encoded JSON description in data-full_desc='...'
        m_b64 = re.search(r"data-full_desc=['\"]([A-Za-z0-9+/=]+)['\"]", detail_html)
        if m_b64:
            try:
                decoded = base64.b64decode(m_b64.group(1)).decode("utf-8", errors="ignore")
                parsed = json.loads(decoded)
                if isinstance(parsed, list):
                    enrichment["description"] = clean_html_text(" ".join(str(p) for p in parsed))
                elif isinstance(parsed, str):
                    enrichment["description"] = clean_html_text(parsed)
            except Exception:
                pass

        if not enrichment.get("description"):
            m_og_desc = re.search(
                r'<meta\s+property="og:description"\s+content="([^"]+)"',
                detail_html,
                flags=re.IGNORECASE,
            )
            if m_og_desc:
                enrichment["description"] = clean_html_text(m_og_desc.group(1))

        m_og_title = re.search(
            r'<meta\s+property="og:title"\s+content="([^"]+)"',
            detail_html,
            flags=re.IGNORECASE,
        )
        if m_og_title:
            raw_t = clean_html_text(m_og_title.group(1))
            enrichment["title"] = re.sub(r"\s*\|\s*Jellis Craig.*$", "", raw_t, flags=re.I).strip()

        # 3. Office code
        m_office = re.search(
            r'id="rentalEnquireHere_loAgentId"\s+value="([^"]+)"',
            detail_html,
            flags=re.IGNORECASE,
        )
        if m_office:
            code = m_office.group(1).strip().upper()
            enrichment["agency_office"] = JC_OFFICE_MAP.get(code, f"Jellis Craig ({code})")

        return enrichment

    def fetch_listings(self) -> List[Dict[str, Any]]:
        """Fetch Jellis Craig rental cards and enrich top listings from detail pages."""
        html_text = self._request_url(self.build_search_url())
        cards = self.extract_cards_from_list_html(html_text)

        discovered: Dict[str, Dict[str, Any]] = {}
        for card in cards:
            lid = card["listing_id"]
            if lid not in discovered:
                discovered[lid] = card

        detail_count = 0
        for lid, card in list(discovered.items()):
            if detail_count >= self.max_detail_fetches:
                break
            if card.get("url"):
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
        """Parse a Jellis Craig card dictionary or raw HTML into standard fields."""
        if isinstance(raw_item, str):
            cards = self.extract_cards_from_list_html(raw_item)
            enrichment = self.extract_detail_enrichment(raw_item)
            if cards:
                item = dict(cards[0])
                item.update({k: v for k, v in enrichment.items() if v})
            elif enrichment:
                item = enrichment
            else:
                raise ValueError("Unable to extract Jellis Craig listing from HTML")
        elif isinstance(raw_item, dict):
            item = dict(raw_item)
        else:
            raise ValueError(f"Unsupported Jellis Craig raw_item type: {type(raw_item)}")

        listing_id = str(item.get("listing_id") or item.get("id") or "").strip()
        if not listing_id:
            m_id = re.search(r"/property-details-[^/]+/(\d+)", str(item.get("url") or ""))
            if m_id:
                listing_id = m_id.group(1)
        if not listing_id:
            raise ValueError("Jellis Craig listing missing listing_id")

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
            item.get("agency_office") or (f"Jellis Craig {suburb}" if suburb else "Jellis Craig")
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
