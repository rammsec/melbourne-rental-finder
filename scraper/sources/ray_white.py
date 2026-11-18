"""
Ray White Direct Rental Listing Adapter.

Official national listing page:
https://www.raywhite.com/listing
Permitted public listing search endpoint used by the official search UI:
POST https://www.raywhite.com/api/rw/listings

Respects https://www.raywhite.com/robots.txt (which only disallows Craft CMS
internal paths `/cpresources/`, `/vendor/`, `/.env`, `/actions/`).
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

from .base import (
    BaseAgencyAdapter,
    CORRIDOR_POSTCODES,
    clean_html_text,
    extract_suburb_and_postcode,
    normalise_property_type,
    parse_availability_date,
    parse_weekly_rent,
)


class RayWhiteAdapter(BaseAgencyAdapter):
    """Adapter for Ray White national and Victorian office rental listings."""

    source_name = "Ray White"
    agency_brand = "Ray White"
    base_url = "https://www.raywhite.com"
    listing_page_url = "https://www.raywhite.com/listing"
    api_url = "https://www.raywhite.com/api/rw/listings"
    integration_status = "integrated"

    def __init__(
        self,
        http_fetcher: Optional[Callable[..., str]] = None,
        max_listings: int = 50,
        target_postcodes: Optional[List[str]] = None,
    ) -> None:
        super().__init__(http_fetcher=http_fetcher, max_listings=max_listings)
        self.target_postcodes = target_postcodes or CORRIDOR_POSTCODES

    def build_search_payload(self) -> Dict[str, Any]:
        """Build the JSON search payload for Victorian current rental listings."""
        payload: Dict[str, Any] = {
            "from": 0,
            "size": self.max_listings,
            "countryCode": ["AU"],
            "stateCode": ["VIC"],
            "typeCode": {"in": ["REN"]},
            "statusCode": {"in": ["CUR"]},
            "sort": [{"field": "creationTime", "order": "desc"}],
        }
        if self.target_postcodes:
            payload["postCode"] = list(self.target_postcodes)
        return payload

    def fetch_listings(self) -> List[Dict[str, Any]]:
        """Fetch raw rental listing objects from the Ray White listings endpoint."""
        payload_bytes = json.dumps(self.build_search_payload()).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Referer": self.listing_page_url,
        }
        raw_text = self._request_url(
            self.api_url,
            method="POST",
            data=payload_bytes,
            headers=headers,
        )
        data = json.loads(raw_text)
        items = data.get("data", [])
        if not isinstance(items, list):
            raise ValueError("Ray White API response 'data' is not a list")
        return items[: self.max_listings]

    def parse_listing(self, raw_item: Any) -> Dict[str, Any]:
        """Parse a Ray White listing item (or JSON string) into standard adapter fields."""
        if isinstance(raw_item, str):
            loaded = json.loads(raw_item)
            if isinstance(loaded, dict) and isinstance(loaded.get("data"), list) and loaded["data"]:
                raw_item = loaded["data"][0]
            else:
                raw_item = loaded

        if not isinstance(raw_item, dict):
            raise ValueError(f"Unsupported Ray White raw_item type: {type(raw_item)}")

        val = raw_item.get("value") if isinstance(raw_item.get("value"), dict) else raw_item
        listing_id = str(val.get("id") or raw_item.get("id") or val.get("sourceId") or "").strip()
        if not listing_id:
            raise ValueError("Ray White listing missing id")

        addr_obj = val.get("address") if isinstance(val.get("address"), dict) else {}
        unit_no = str(addr_obj.get("unitNumber") or "").strip()
        street_no = str(addr_obj.get("streetNumber") or "").strip()
        street_name = str(addr_obj.get("streetName") or "").strip()
        street_type = str(addr_obj.get("streetType") or "").strip()
        suburb_raw = str(addr_obj.get("suburb") or val.get("suburb") or "").strip()
        state_raw = str(addr_obj.get("stateCode") or val.get("state") or "VIC").upper().strip()
        postcode_raw = str(addr_obj.get("postCode") or val.get("postcode") or "").strip()

        formatted_addr = clean_html_text(str(addr_obj.get("formatted") or ""))
        formatted_addr = re.sub(r",?\s*\bAustralia\b$", "", formatted_addr, flags=re.IGNORECASE).strip()
        if not formatted_addr:
            num_prefix = f"{unit_no}/{street_no}" if (unit_no and street_no) else (unit_no or street_no)
            street_part = " ".join(p for p in (num_prefix, street_name, street_type) if p).strip()
            formatted_addr = f"{street_part}, {suburb_raw}, {state_raw} {postcode_raw}".strip(", ")
        elif postcode_raw and postcode_raw not in formatted_addr:
            formatted_addr = f"{formatted_addr}, {state_raw} {postcode_raw}".strip(", ")

        suburb, postcode = extract_suburb_and_postcode(
            formatted_addr, fallback_suburb=suburb_raw, fallback_postcode=postcode_raw
        )

        # Weekly rent
        price_text = str(val.get("displayPrice") or val.get("price") or "").strip()
        rent_price = val.get("rentPrice")
        weekly_rent = parse_weekly_rent(rent_price if rent_price not in (None, "", 0) else price_text)
        if weekly_rent is None and price_text:
            weekly_rent = parse_weekly_rent(price_text)

        bedrooms = val.get("bedrooms")
        bathrooms = val.get("bathrooms")
        car_spaces = val.get("carSpaces")
        if car_spaces is None:
            car_spaces = (
                int(val.get("garages") or 0)
                + int(val.get("carports") or 0)
                + int(val.get("openSpaces") or 0)
            )

        # Category / Property type
        categories = val.get("categories") or []
        raw_cat = ""
        if isinstance(categories, list) and categories:
            first_cat = categories[0]
            if isinstance(first_cat, dict):
                raw_cat = str(first_cat.get("category") or first_cat.get("code") or "")
            elif isinstance(first_cat, str):
                raw_cat = first_cat
        elif isinstance(val.get("propertyType"), str):
            raw_cat = val["propertyType"]

        title = clean_html_text(val.get("title") or formatted_addr)
        description = clean_html_text(val.get("description") or "")
        prop_type = normalise_property_type(raw_cat, title=title, description=description)

        # Images
        images: List[str] = []
        for img in (val.get("images") or []):
            if isinstance(img, str) and img.strip():
                images.append(img.strip())
            elif isinstance(img, dict) and img.get("url"):
                images.append(str(img["url"]).strip())
        if not images and isinstance(val.get("heroImage"), dict) and val["heroImage"].get("url"):
            images.append(str(val["heroImage"]["url"]).strip())

        # Availability date
        available_date = parse_availability_date(val.get("availableDate") or val.get("available_date"))

        # Inspection times
        inspection_times: List[str] = []
        for insp in (val.get("inspections") or []):
            if isinstance(insp, str) and insp.strip():
                inspection_times.append(insp.strip())
            elif isinstance(insp, dict):
                start_t = insp.get("start") or insp.get("startAtUtc") or ""
                end_t = insp.get("end") or insp.get("finishAtUtc") or ""
                if start_t and end_t:
                    inspection_times.append(f"{start_t} - {end_t}")
                elif start_t:
                    inspection_times.append(str(start_t))

        # Direct property URL
        if val.get("url") and str(val["url"]).startswith(("http://", "https://")):
            direct_url = str(val["url"]).strip()
        else:
            state_slug = (state_raw or "vic").lower()
            suburb_slug = re.sub(r"[^a-z0-9]+", "-", (suburb or "melbourne").lower()).strip("-")
            direct_url = f"{self.base_url}/{state_slug}/{suburb_slug}/{listing_id}"

        # Agency office
        office_obj = val.get("office")
        if isinstance(office_obj, dict):
            b_name = str(office_obj.get("businessName") or "").strip()
            d_name = str(office_obj.get("displayName") or office_obj.get("name") or "").strip()
            if b_name:
                agency_office = b_name
            elif d_name:
                agency_office = d_name if d_name.lower().startswith("ray white") else f"Ray White {d_name}"
            else:
                agency_office = "Ray White"
        elif isinstance(office_obj, str) and office_obj.strip():
            agency_office = office_obj.strip()
        else:
            agency_office = "Ray White"

        discovered_at = str(val.get("creationTime") or datetime.now(timezone.utc).isoformat())

        return {
            "source": self.source_name,
            "listing_id": listing_id,
            "address": formatted_addr,
            "suburb": suburb,
            "postcode": postcode,
            "state": state_raw or "VIC",
            "weekly_rent": weekly_rent,
            "price_text": price_text or (f"${int(weekly_rent)} per week" if weekly_rent else ""),
            "bedrooms": bedrooms if bedrooms is not None else 1,
            "bathrooms": bathrooms if bathrooms is not None else 1,
            "parking": car_spaces if car_spaces is not None else 0,
            "property_type": prop_type,
            "title": title or formatted_addr,
            "description": description,
            "images": images,
            "available_date": available_date,
            "inspection_times": inspection_times,
            "url": direct_url,
            "agency_office": agency_office,
            "discovered_at": discovered_at,
        }
