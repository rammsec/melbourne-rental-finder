"""
Buxton Direct Rental Listing Adapter.

Official rental directory:
https://www.buxton.com.au/properties-for-lease/
Permitted public CMS JSON API used by the official Next.js frontend:
GET https://cms.buxton.com.au/api/v1/listings/?fields=card&paginated=true&status=available&listing_types=rental&transaction_type=lease

Respects https://buxton.com.au/robots.txt (`User-Agent: * Allow: /`).
Also supports extracting `initialListings` embedded in Next.js App Router Flight data
on `/properties-for-lease/`.
"""

from __future__ import annotations

import json
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


BUXTON_TARGET_SUBURBS = [
    "Hawthorn",
    "Hawthorn East",
    "Camberwell",
    "Glen Iris",
    "Kew",
    "Balwyn",
    "Box Hill",
    "Blackburn",
    "Mitcham",
    "Ringwood",
    "Burwood",
    "Malvern",
    "Mount Waverley",
]


class BuxtonAdapter(BaseAgencyAdapter):
    """Adapter for Buxton real estate rental listings."""

    source_name = "Buxton"
    agency_brand = "Buxton"
    base_url = "https://buxton.com.au"
    listing_page_url = "https://buxton.com.au/properties-for-lease/"
    api_url = "https://cms.buxton.com.au/api/v1/listings/"
    integration_status = "integrated"

    def __init__(
        self,
        http_fetcher: Optional[Callable[..., str]] = None,
        max_listings: int = 50,
        target_suburbs: Optional[List[str]] = None,
    ) -> None:
        super().__init__(http_fetcher=http_fetcher, max_listings=max_listings)
        self.target_suburbs = target_suburbs if target_suburbs is not None else BUXTON_TARGET_SUBURBS

    def build_api_url(self, offset: int = 0, limit: int = 48, suburb: Optional[str] = None) -> str:
        """Build Buxton CMS API URL for available rental listings."""
        params: Dict[str, Any] = {
            "fields": "card",
            "paginated": "true",
            "status": "available",
            "listing_types": "rental",
            "transaction_type": "lease",
            "sort": "date_desc",
            "limit": limit,
            "offset": offset,
        }
        if suburb:
            params["suburb"] = suburb
        return f"{self.api_url}?{urllib.parse.urlencode(params)}"

    @classmethod
    def extract_initial_listings_from_html(cls, html_text: str) -> List[Dict[str, Any]]:
        """Extract `initialListings` JSON array from Buxton Next.js SSR HTML."""
        idx = html_text.find('\\"initialListings\\":[')
        raw_slice = ""
        if idx != -1:
            raw_slice = html_text[idx: idx + 60000].replace('\\"', '"').replace('\\\\', '\\')
        else:
            idx2 = html_text.find('"initialListings":[')
            if idx2 != -1:
                raw_slice = html_text[idx2: idx2 + 60000]

        if not raw_slice:
            return []

        arr_start = raw_slice.find("[")
        if arr_start == -1:
            return []

        depth = 0
        in_str = False
        esc = False
        arr_end = -1
        for i, ch in enumerate(raw_slice[arr_start:], start=arr_start):
            if esc:
                esc = False
                continue
            if ch == "\\":
                esc = True
                continue
            if ch == '"':
                in_str = not in_str
                continue
            if not in_str:
                if ch == "[":
                    depth += 1
                elif ch == "]":
                    depth -= 1
                    if depth == 0:
                        arr_end = i + 1
                        break

        if arr_end != -1:
            try:
                items = json.loads(raw_slice[arr_start:arr_end])
                if isinstance(items, list):
                    return items
            except Exception:
                pass
        return []

    def fetch_listings(self) -> List[Dict[str, Any]]:
        """
        Fetch Buxton rental listings via the official CMS API with pagination,
        falling back to Next.js SSR `initialListings` if needed.
        """
        discovered: Dict[str, Dict[str, Any]] = {}
        headers = {
            "Accept": "application/json",
            "Referer": self.listing_page_url,
        }

        # 1. Fetch general newest rental listings across Melbourne
        try:
            raw_text = self._request_url(self.build_api_url(offset=0, limit=48), headers=headers)
            if raw_text.lstrip().startswith("{"):
                data = json.loads(raw_text)
                for item in data.get("results", []):
                    lid = str(item.get("listonce_listing_id") or item.get("external_id") or item.get("id") or "")
                    if lid and lid not in discovered:
                        discovered[lid] = item
            else:
                for item in self.extract_initial_listings_from_html(raw_text):
                    lid = str(item.get("listonce_listing_id") or item.get("external_id") or item.get("id") or "")
                    if lid and lid not in discovered:
                        discovered[lid] = item
        except Exception:
            # Fallback to HTML page
            html_text = self._request_url(self.listing_page_url)
            for item in self.extract_initial_listings_from_html(html_text):
                lid = str(item.get("listonce_listing_id") or item.get("external_id") or item.get("id") or "")
                if lid and lid not in discovered:
                    discovered[lid] = item

        # 2. If running live without custom mock fetcher, also query key eastern suburbs
        if self._http_fetcher is None and self.target_suburbs:
            for sub in self.target_suburbs[:5]:
                if len(discovered) >= self.max_listings:
                    break
                try:
                    if self.request_delay_seconds > 0:
                        time.sleep(self.request_delay_seconds)
                    sub_json = self._request_url(
                        self.build_api_url(offset=0, limit=20, suburb=sub),
                        headers=headers,
                    )
                    sub_data = json.loads(sub_json)
                    for item in sub_data.get("results", []):
                        lid = str(item.get("listonce_listing_id") or item.get("external_id") or item.get("id") or "")
                        if lid and lid not in discovered:
                            discovered[lid] = item
                except Exception:
                    continue

        return list(discovered.values())[: self.max_listings]

    def parse_listing(self, raw_item: Any) -> Dict[str, Any]:
        """Parse a Buxton listing JSON object (or HTML/JSON string) into standard adapter fields."""
        if isinstance(raw_item, str):
            text = raw_item.strip()
            if text.startswith("{"):
                loaded = json.loads(text)
                if isinstance(loaded.get("results"), list) and loaded["results"]:
                    item = dict(loaded["results"][0])
                else:
                    item = loaded
            else:
                extracted = self.extract_initial_listings_from_html(text)
                if not extracted:
                    raise ValueError("Unable to extract Buxton listing from string")
                item = dict(extracted[0])
        elif isinstance(raw_item, dict):
            item = dict(raw_item)
        else:
            raise ValueError(f"Unsupported Buxton raw_item type: {type(raw_item)}")

        listing_id = str(
            item.get("listonce_listing_id") or item.get("external_id") or item.get("id") or ""
        ).strip()
        if not listing_id:
            raise ValueError("Buxton listing missing id")

        street = clean_html_text(str(item.get("street_address") or ""))
        suburb_raw = clean_html_text(str(item.get("suburb") or ""))
        postcode_raw = str(item.get("postcode") or "").strip()
        state_raw = str(item.get("address_state") or "VIC").upper().strip()

        if street and suburb_raw:
            address = f"{street}, {suburb_raw}, {state_raw} {postcode_raw}".strip()
        else:
            address = clean_html_text(str(item.get("address") or street or suburb_raw))

        suburb, postcode = extract_suburb_and_postcode(
            address, fallback_suburb=suburb_raw, fallback_postcode=postcode_raw
        )

        badge = item.get("card_badge_payload") if isinstance(item.get("card_badge_payload"), dict) else {}
        price_val = item.get("price") if item.get("price") not in (None, "", 0) else badge.get("rent")
        price_text = str(item.get("price_statement") or (f"${price_val} pw" if price_val else "")).strip()
        weekly_rent = parse_weekly_rent(price_val if price_val is not None else price_text)

        headline = clean_html_text(str(badge.get("headline") or item.get("title") or ""))
        title = headline or address
        description = clean_html_text(str(item.get("description") or headline or ""))
        prop_type = normalise_property_type(
            str(item.get("property_type") or ""), title=title, description=description
        )

        images = [
            str(u).strip()
            for u in (item.get("card_image_urls") or item.get("images") or [])
            if isinstance(u, str) and u.strip()
        ]

        # Build canonical Buxton property URL
        if item.get("url") and str(item["url"]).startswith(("http://", "https://")):
            direct_url = str(item["url"]).strip()
        else:
            addr_slug = re.sub(
                r"[^a-z0-9]+",
                "-",
                f"{street} {suburb} {state_raw} {postcode}".lower(),
            ).strip("-")
            if not addr_slug:
                addr_slug = str(item.get("slug") or listing_id)
            direct_url = f"{self.base_url}/property/{listing_id}/{addr_slug}/"

        available_date = parse_availability_date(item.get("available_date") or item.get("date_available"))
        agency_office = clean_html_text(
            str(item.get("agency_office") or (f"Buxton {suburb}" if suburb else "Buxton"))
        )
        discovered_at = str(
            item.get("publish_date") or item.get("source_updated_at") or datetime.now(timezone.utc).isoformat()
        )

        return {
            "source": self.source_name,
            "listing_id": listing_id,
            "address": address,
            "suburb": suburb,
            "postcode": postcode,
            "state": state_raw or "VIC",
            "weekly_rent": weekly_rent,
            "price_text": price_text or (f"${int(weekly_rent)} pw" if weekly_rent else ""),
            "bedrooms": item.get("bedrooms") if item.get("bedrooms") is not None else 1,
            "bathrooms": item.get("bathrooms") if item.get("bathrooms") is not None else 1,
            "parking": item.get("parking") if item.get("parking") is not None else 0,
            "property_type": prop_type,
            "title": title,
            "description": description,
            "images": images,
            "available_date": available_date,
            "inspection_times": list(item.get("inspection_times") or []),
            "url": direct_url,
            "agency_office": agency_office,
            "listed_at": discovered_at,
            "discovered_at": discovered_at,
        }
