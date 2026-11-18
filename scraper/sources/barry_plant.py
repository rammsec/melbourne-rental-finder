"""
Barry Plant Direct Rental Listing Adapter.

Official rental directory:
https://www.barryplant.com.au/rental-properties/properties-rent/
Official active listings sitemap (advertised in robots.txt):
https://www.barryplant.com.au/sitemap-active-listings.xml

Extraction method:
- Parses structured Next.js SSR JSON (`<script id="__NEXT_DATA__" type="application/json">`)
  from the official rental directory (`props.pageProps.pageProps.propertiesData.results`)
  and individual Hawthorn corridor rental detail pages discovered via `sitemap-active-listings.xml`
  (`props.pageProps.propertyData`).
- Strictly respects robots.txt: never calls `/api/` or disallowed filter query parameters.
"""

from __future__ import annotations

import json
import re
import time
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

from ..config import HAWTHORN_DIRECT_SUBURBS
from .base import (
    BaseAgencyAdapter,
    clean_html_text,
    extract_suburb_and_postcode,
    normalise_property_type,
    parse_availability_date,
    parse_weekly_rent,
)


class BarryPlantAdapter(BaseAgencyAdapter):
    """Adapter for Barry Plant rental listings."""

    source_name = "Barry Plant"
    agency_brand = "Barry Plant"
    base_url = "https://www.barryplant.com.au"
    directory_url = "https://www.barryplant.com.au/rental-properties/properties-rent/"
    sitemap_url = "https://www.barryplant.com.au/sitemap-active-listings.xml"
    integration_status = "integrated"

    def __init__(
        self,
        http_fetcher: Optional[Callable[..., str]] = None,
        max_listings: int = 30,
        max_detail_pages: int = 16,
    ) -> None:
        super().__init__(http_fetcher=http_fetcher, max_listings=max_listings)
        self.max_detail_pages = max_detail_pages

    @staticmethod
    def extract_next_data_payload(html_text: str) -> Dict[str, Any]:
        """Extract the parsed JSON object from Next.js <script id="__NEXT_DATA__">."""
        m = re.search(
            r'<script\s+id="__NEXT_DATA__"\s+type="application/json"[^>]*>(.*?)</script>',
            html_text,
            flags=re.DOTALL | re.IGNORECASE,
        )
        if not m:
            raise ValueError("Missing __NEXT_DATA__ script block in Barry Plant HTML")
        return json.loads(m.group(1))

    @classmethod
    def extract_directory_results(cls, html_text: str) -> List[Dict[str, Any]]:
        """Extract listing result objects from a Barry Plant directory page."""
        data = cls.extract_next_data_payload(html_text)
        page_props = data.get("props", {}).get("pageProps", {})
        inner_props = page_props.get("pageProps", page_props)
        results = inner_props.get("propertiesData", {}).get("results", [])
        if isinstance(results, list):
            return [r for r in results if isinstance(r, dict)]
        return []

    @classmethod
    def extract_detail_property(cls, html_text: str) -> Optional[Dict[str, Any]]:
        """Extract single propertyData object from a Barry Plant property detail page."""
        data = cls.extract_next_data_payload(html_text)
        page_props = data.get("props", {}).get("pageProps", {})
        prop_data = page_props.get("propertyData") or page_props.get("pageProps", {}).get("propertyData")
        if isinstance(prop_data, dict) and prop_data.get("id"):
            return prop_data
        return None

    @classmethod
    def filter_corridor_sitemap_urls(cls, sitemap_xml: str, limit: int = 16) -> List[str]:
        """
        Extract rental property URLs from Barry Plant's active listings sitemap
        that match Melbourne / Hawthorn corridor suburbs, sorted by newest listing ID.
        """
        urls = re.findall(
            r"<loc>(https://www\.barryplant\.com\.au/rental-properties/[^<]+)</loc>",
            sitemap_xml,
        )
        suburb_slugs = sorted(
            {s.lower().strip().replace(" ", "-") for s in HAWTHORN_DIRECT_SUBURBS},
            key=len,
            reverse=True,
        )
        sub_pattern = "|".join(re.escape(slug) for slug in suburb_slugs)
        regex = re.compile(rf"-(?:{sub_pattern})-vic-(3\d{{3}})-(\d+)/?$")

        matched: List[tuple[int, str]] = []
        for u in urls:
            if u.rstrip("/").endswith("/properties-rent"):
                continue
            m = regex.search(u)
            if m:
                listing_id = int(m.group(2))
                matched.append((listing_id, u))

        matched.sort(key=lambda item: item[0], reverse=True)
        return [u for _, u in matched[:limit]]

    def fetch_listings(self) -> List[Dict[str, Any]]:
        """
        Fetch raw Barry Plant rental listing objects from the official rental directory
        and active listings sitemap.
        """
        discovered_by_id: Dict[str, Dict[str, Any]] = {}

        # 1. Fetch official rental directory page
        dir_error: Optional[Exception] = None
        try:
            dir_html = self._request_url(self.directory_url)
            for item in self.extract_directory_results(dir_html):
                lid = str(item.get("id") or item.get("uniqueID") or "")
                if lid:
                    discovered_by_id[lid] = item
        except Exception as e:
            dir_error = e

        # 2. Fetch active listings sitemap for targeted Melbourne / Hawthorn corridor rentals
        if self.max_detail_pages > 0:
            try:
                sitemap_xml = self._request_url(self.sitemap_url)
                candidate_urls = self.filter_corridor_sitemap_urls(
                    sitemap_xml, limit=self.max_detail_pages
                )
                for url in candidate_urls:
                    if len(discovered_by_id) >= self.max_listings:
                        break
                    m_id = re.search(r"-(\d+)/?$", url)
                    if m_id and m_id.group(1) in discovered_by_id:
                        continue
                    try:
                        if self._http_fetcher is None and self.request_delay_seconds > 0:
                            time.sleep(self.request_delay_seconds)
                        detail_html = self._request_url(url)
                        prop_data = self.extract_detail_property(detail_html)
                        if prop_data:
                            lid = str(prop_data.get("id") or prop_data.get("uniqueID") or "")
                            if lid:
                                discovered_by_id[lid] = prop_data
                    except Exception:
                        continue
            except Exception as e:
                if not discovered_by_id and dir_error is not None:
                    raise dir_error from e

        if not discovered_by_id and dir_error is not None:
            raise dir_error

        return list(discovered_by_id.values())[: self.max_listings]

    def parse_listing(self, raw_item: Any) -> Dict[str, Any]:
        """Parse a Barry Plant property data object (or raw detail/directory HTML) into standard fields."""
        if isinstance(raw_item, str):
            detail = self.extract_detail_property(raw_item)
            if detail:
                item = detail
            else:
                results = self.extract_directory_results(raw_item)
                if not results:
                    raise ValueError("No Barry Plant property data found in HTML")
                item = results[0]
        elif isinstance(raw_item, dict):
            item = raw_item
        else:
            raise ValueError(f"Unsupported Barry Plant raw_item type: {type(raw_item)}")

        listing_id = str(item.get("id") or item.get("uniqueID") or "").strip()
        if not listing_id:
            raise ValueError("Barry Plant listing missing id")

        address = str(item.get("address_display_string") or "").strip()
        suburb_raw = str(item.get("address_suburb") or "").strip()
        postcode_raw = str(item.get("address_postcode") or "").strip()
        state_raw = str(item.get("address_state") or "VIC").upper().strip()

        if not address:
            parts = [
                str(item.get("address_sub_number") or "").strip(),
                str(item.get("address_street_number") or "").strip(),
                str(item.get("address_street_name") or "").strip(),
            ]
            street = " ".join(p for p in parts if p).strip()
            address = f"{street}, {suburb_raw}, {state_raw} {postcode_raw}".strip(", ")

        suburb, postcode = extract_suburb_and_postcode(
            address, fallback_suburb=suburb_raw, fallback_postcode=postcode_raw
        )

        price_text = str(item.get("price") or item.get("priceView") or "").strip()
        rent_val = item.get("rent")
        weekly_rent = parse_weekly_rent(rent_val if rent_val not in (None, "", 0) else price_text)
        if weekly_rent is None and price_text:
            weekly_rent = parse_weekly_rent(price_text)

        bedrooms = item.get("bedrooms")
        bathrooms = item.get("bathrooms")
        parking = item.get("total_parking") if item.get("total_parking") is not None else item.get("parking", 0)

        headline = clean_html_text(item.get("headline") or item.get("title") or address)
        description = clean_html_text(item.get("description") or "")
        category = str(item.get("category") or item.get("property_type") or "")
        prop_type = normalise_property_type(category, title=headline, description=description)

        # Images
        images: List[str] = []
        raw_images = item.get("images") or []
        if isinstance(raw_images, list):
            for img_entry in raw_images:
                if isinstance(img_entry, str) and img_entry.strip():
                    images.append(img_entry.strip())
                elif isinstance(img_entry, dict):
                    nested = img_entry.get("image")
                    if isinstance(nested, dict):
                        img_url = (
                            nested.get("image_800_600")
                            or nested.get("image_1680_1050")
                            or nested.get("image")
                            or ""
                        )
                        if img_url:
                            images.append(str(img_url).strip())
                    elif isinstance(nested, str) and nested.strip():
                        images.append(nested.strip())
                    elif img_entry.get("url"):
                        images.append(str(img_entry["url"]).strip())

        # Availability date
        available_date = parse_availability_date(
            item.get("dateAvailable") or item.get("available_date")
        )

        # Inspection times
        inspection_times: List[str] = []
        raw_inspections = item.get("inspections") or []
        if isinstance(raw_inspections, list):
            for insp in raw_inspections:
                if isinstance(insp, str) and insp.strip():
                    inspection_times.append(insp.strip())
                elif isinstance(insp, dict):
                    start_t = insp.get("inspection_time") or insp.get("start") or ""
                    end_t = insp.get("inspection_end_time") or insp.get("end") or ""
                    if start_t and end_t:
                        inspection_times.append(f"{start_t} - {end_t}")
                    elif start_t:
                        inspection_times.append(str(start_t))

        # Direct property URL
        rel_url = str(item.get("get_absolute_url") or item.get("url") or "").strip()
        if rel_url.startswith("/"):
            direct_url = f"{self.base_url}{rel_url}"
        elif rel_url.startswith(("http://", "https://")):
            direct_url = rel_url
        else:
            slug = re.sub(r"[^a-z0-9]+", "-", f"{address}".lower()).strip("-")
            direct_url = f"{self.base_url}/rental-properties/{slug}-{listing_id}/"

        # Agency office
        office_obj = item.get("office")
        if isinstance(office_obj, dict):
            office_title = str(office_obj.get("title") or office_obj.get("name") or "").strip()
            if office_title and not office_title.lower().startswith("barry plant"):
                agency_office = f"Barry Plant {office_title}"
            else:
                agency_office = office_title or "Barry Plant"
        elif isinstance(office_obj, str) and office_obj.strip():
            agency_office = office_obj.strip()
        else:
            agency_office = "Barry Plant"

        discovered_at = str(
            item.get("listing_creation_date")
            or item.get("created")
            or datetime.now(timezone.utc).isoformat()
        )

        return {
            "source": self.source_name,
            "listing_id": listing_id,
            "address": address,
            "suburb": suburb,
            "postcode": postcode,
            "state": state_raw or "VIC",
            "weekly_rent": weekly_rent,
            "price_text": price_text or (f"${int(weekly_rent)} per week" if weekly_rent else ""),
            "bedrooms": bedrooms if bedrooms is not None else 1,
            "bathrooms": bathrooms if bathrooms is not None else 1,
            "parking": parking if parking is not None else 0,
            "property_type": prop_type,
            "title": headline or address,
            "description": description,
            "images": images,
            "available_date": available_date,
            "inspection_times": inspection_times,
            "url": direct_url,
            "agency_office": agency_office,
            "discovered_at": discovered_at,
        }
