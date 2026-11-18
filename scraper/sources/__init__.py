"""
Modular Rental Discovery Sources Package for Melbourne Rental Finder V2.

Exposes:
1. Legacy & community rental discovery scrapers (Gumtree, Flatmates, Reddit, FB Marketplace)
2. Direct Australian Real Estate Agency Adapters implementing the standard interface:
   - fetch_listings()
   - parse_listing()
   - normalise_listing()
   - validate_listing()
   - get_source_health()
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from ..models import Property, ScraperExecutionLog
from .legacy import (
    DEFAULT_HEADERS,
    FB_MARKETPLACE_PRIMARY_URL,
    fetch_url,
    get_listing_age_days,
    is_outside_melbourne,
    parse_gumtree_age_to_iso,
    scrape_facebook_marketplace_aligned,
    scrape_flatmates_whole_properties,
    scrape_gumtree_lease_transfers,
    scrape_reddit_lease_transfers,
)
from .base import (
    BaseAgencyAdapter,
    CORRIDOR_POSTCODES,
    ELIGIBLE_PROPERTY_TYPES,
    SUBURB_POSTCODE_MAP,
    SourceHealth,
    clean_html_text,
    extract_suburb_and_postcode,
    normalise_property_type,
    parse_availability_date,
    parse_weekly_rent,
)
from .barry_plant import BarryPlantAdapter
from .ray_white import RayWhiteAdapter
from .nelson_alexander import NelsonAlexanderAdapter
from .jellis_craig import JellisCraigAdapter
from .woodards import WoodardsAdapter
from .belle_property import BellePropertyAdapter


AGENCY_ADAPTER_CLASSES = [
    BarryPlantAdapter,
    RayWhiteAdapter,
    NelsonAlexanderAdapter,
    JellisCraigAdapter,
    WoodardsAdapter,
    BellePropertyAdapter,
]


def get_default_agency_adapters() -> List[BaseAgencyAdapter]:
    """Instantiate all registered direct real estate agency adapters."""
    return [
        BarryPlantAdapter(),
        RayWhiteAdapter(),
        NelsonAlexanderAdapter(),
        JellisCraigAdapter(),
        WoodardsAdapter(),
        BellePropertyAdapter(),
    ]


def collect_all_agency_sources(
    adapters: Optional[List[BaseAgencyAdapter]] = None,
) -> Tuple[List[Property], Dict[str, Dict[str, Any]], List[ScraperExecutionLog]]:
    """
    Run all direct real estate agency adapters with full fault isolation.
    A failure in any single agency adapter never stops other agency sources.

    Returns:
    - collected_properties: List[Property]
    - source_health_map: Dict[source_name, health_dict]
    - execution_logs: List[ScraperExecutionLog]
    """
    active_adapters = adapters if adapters is not None else get_default_agency_adapters()
    all_properties: List[Property] = []
    health_map: Dict[str, Dict[str, Any]] = {}
    exec_logs: List[ScraperExecutionLog] = []

    for adapter in active_adapters:
        try:
            props = adapter.collect()
            all_properties.extend(props)
        except Exception as e:
            # Extra outer safety guard in case a custom adapter overrides collect()
            adapter.health.status = "failed"
            adapter.health.last_error = f"Unhandled adapter error: {e}"
        health_map[adapter.source_name] = adapter.get_source_health()
        exec_logs.append(adapter.to_execution_log())

    return all_properties, health_map, exec_logs


__all__ = [
    "DEFAULT_HEADERS",
    "FB_MARKETPLACE_PRIMARY_URL",
    "fetch_url",
    "get_listing_age_days",
    "is_outside_melbourne",
    "parse_gumtree_age_to_iso",
    "scrape_facebook_marketplace_aligned",
    "scrape_flatmates_whole_properties",
    "scrape_gumtree_lease_transfers",
    "scrape_reddit_lease_transfers",
    "BaseAgencyAdapter",
    "SourceHealth",
    "SUBURB_POSTCODE_MAP",
    "CORRIDOR_POSTCODES",
    "ELIGIBLE_PROPERTY_TYPES",
    "clean_html_text",
    "extract_suburb_and_postcode",
    "normalise_property_type",
    "parse_availability_date",
    "parse_weekly_rent",
    "BarryPlantAdapter",
    "RayWhiteAdapter",
    "NelsonAlexanderAdapter",
    "JellisCraigAdapter",
    "WoodardsAdapter",
    "BellePropertyAdapter",
    "AGENCY_ADAPTER_CLASSES",
    "get_default_agency_adapters",
    "collect_all_agency_sources",
]
