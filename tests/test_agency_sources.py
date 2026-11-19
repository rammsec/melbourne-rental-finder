"""
Fixture-Based Unit & Integration Test Suite for Direct Real Estate Agency Sources (V1).

Covers:
1. Common interface compliance across all 6 agency adapters:
   - BarryPlantAdapter
   - RayWhiteAdapter
   - NelsonAlexanderAdapter
   - JellisCraigAdapter
   - WoodardsAdapter
   - BellePropertyAdapter
2. Rent parsing (weekly, monthly/pcm conversions, date-prefixed prices, bond clauses).
3. Property identification & canonical Property model normalization.
4. Availability date parsing across ISO, slash, ordinal, and relative formats.
5. Cross-source duplicate detection & multi-URL source_provenance retention.
6. Filtering & validation (Melbourne suburb, property type, bedroom, and budget criteria).
7. Source health telemetry & failure isolation (HTTP 403 WAF, HTTP 500, malformed payloads).
"""

import base64
import json
import tempfile
import unittest
import urllib.error
from pathlib import Path

from scraper.models import Property, generate_property_id
from scraper.dedup import deduplicate_properties, calculate_match_confidence
from scraper.db import PropertyDatabase
from scraper.sources import (
    BaseAgencyAdapter,
    BarryPlantAdapter,
    RayWhiteAdapter,
    NelsonAlexanderAdapter,
    JellisCraigAdapter,
    HarcourtsAdapter,
    BellePropertyAdapter,
    McGrathAdapter,
    WoodardsAdapter,
    BuxtonAdapter,
    FletchersAdapter,
    collect_all_agency_sources,
    parse_weekly_rent,
    parse_availability_date,
    normalise_property_type,
    extract_suburb_and_postcode,
)


# ---------------------------------------------------------------------------
# Realistic Agency Fixtures
# ---------------------------------------------------------------------------

BARRY_PLANT_DIRECTORY_HTML_FIXTURE = """<!DOCTYPE html>
<html>
<head><title>Barry Plant Rentals</title></head>
<body>
<script id="__NEXT_DATA__" type="application/json">
{
  "props": {
    "pageProps": {
      "pageProps": {
        "propertiesData": {
          "count": 2,
          "results": [
            {
              "id": 213056,
              "uniqueID": "banto-54597",
              "headline": "Sunlit 2 Bedroom Unit Steps from Box Hill Station",
              "description": "Spacious two bedroom unit with polished floorboards, split system heating/cooling and lock-up garage. 400m walk to Box Hill train station.",
              "address_display_string": "5/11 Brougham Street, Box Hill, VIC 3128",
              "address_suburb": "Box Hill",
              "address_postcode": "3128",
              "address_state": "vic",
              "price": "$540 per week",
              "rent": 540,
              "bedrooms": 2,
              "bathrooms": 1,
              "total_parking": 1,
              "category": "Unit",
              "dateAvailable": "2026-12-12T00:00:00+11:00",
              "listing_creation_date": "2026-11-18T02:00:00Z",
              "get_absolute_url": "/rental-properties/5-11-brougham-street-box-hill-vic-3128-213056/",
              "office": {"title": "Whitehorse"},
              "images": [
                {"image": {"image_800_600": "https://barryplant-media.s3.amazonaws.com/213056_1.jpg"}},
                {"image": {"image_800_600": "https://barryplant-media.s3.amazonaws.com/213056_2.jpg"}}
              ],
              "inspections": [
                {
                  "inspection_time": "2026-11-21T11:25:00+11:00",
                  "inspection_end_time": "2026-11-21T11:40:00+11:00"
                }
              ]
            },
            {
              "id": 213099,
              "uniqueID": "banto-99999",
              "headline": "Luxury 4 Bedroom Family Residence",
              "description": "Expansive four bedroom home with pool.",
              "address_display_string": "42 Mont Albert Road, Canterbury, VIC 3126",
              "address_suburb": "Canterbury",
              "address_postcode": "3126",
              "address_state": "vic",
              "price": "$1,250 per week",
              "rent": 1250,
              "bedrooms": 4,
              "bathrooms": 3,
              "total_parking": 2,
              "category": "House",
              "dateAvailable": "2026-12-01T00:00:00+11:00",
              "get_absolute_url": "/rental-properties/42-mont-albert-road-canterbury-vic-3126-213099/",
              "office": {"title": "Boroondara"},
              "images": [],
              "inspections": []
            }
          ]
        }
      }
    }
  }
}
</script>
</body>
</html>
"""

RAY_WHITE_API_JSON_FIXTURE = json.dumps({
    "total": 1,
    "data": [
        {
            "id": "3618403",
            "value": {
                "id": 3618403,
                "sourceId": "R4554644",
                "title": "Modern 2BR Townhouse Near Boronia Station",
                "description": "Well presented 2 bedroom townhouse.<br/><br/>Walking distance to Boronia train station and shops.",
                "rentPrice": 520.0,
                "displayPrice": "$520 per week",
                "price": "520",
                "bedrooms": 2,
                "bathrooms": 1,
                "carSpaces": 1,
                "categories": [{"code": "THS", "category": "Townhouse"}],
                "availableDate": "2026-12-10T00:00:00",
                "creationTime": "2026-11-18T03:30:00+11:00",
                "address": {
                    "unitNumber": "4",
                    "streetNumber": "1",
                    "streetName": "Rosella",
                    "streetType": "Avenue",
                    "suburb": "Boronia",
                    "stateCode": "VIC",
                    "postCode": "3155",
                    "formatted": "4/1 Rosella Avenue, Boronia, VIC 3155"
                },
                "images": [
                    {"url": "https://cdn6.ep.dynamics.net/rw/3618403_1.jpg"},
                    {"url": "https://cdn6.ep.dynamics.net/rw/3618403_2.jpg"}
                ],
                "inspections": [
                    {"start": "2026-11-22T10:00:00+11:00", "end": "2026-11-22T10:15:00+11:00"}
                ],
                "office": {
                    "displayName": "Ferntree Gully",
                    "businessName": "Ray White Ferntree Gully"
                }
            }
        }
    ]
})

NELSON_ALEXANDER_DIRECTORY_HTML_FIXTURE = """<!DOCTYPE html>
<html>
<body>
<section class="properties-grid">
  <div class="property-card large-4 cell">
    <a class="property-card-url" href="/property/1084512/3-163-burwood-road-hawthorn-vic-3122/" title="3/163 Burwood Road, Hawthorn VIC 3122"></a>
    <div class="lazyload" data-bgset="https://images.listonce.com.au/na/1084512_main.jpg"></div>
    <div class="property-details">
      <h2>3/163 Burwood Road, Hawthorn VIC 3122 </h2>
      <p>14/12/2026 - $525pw / $2281pcm</p>
      <ul class="property-meta">
        <li><i class="icon-bed-secondary"></i><span>2</span></li>
        <li><i class="icon-bath-secondary"></i><span>1</span></li>
        <li><i class="icon-car-secondary"></i><span>1</span></li>
      </ul>
    </div>
  </div>
</section>
</body>
</html>
"""

NELSON_ALEXANDER_DETAIL_HTML_FIXTURE = """<!DOCTYPE html>
<html>
<head>
<script type="application/ld+json">
[
  {
    "@context": "https://schema.org",
    "@type": "Residence",
    "address": {
      "@type": "PostalAddress",
      "streetAddress": "3/163 Burwood Road",
      "addressLocality": "Hawthorn",
      "addressRegion": "VIC",
      "postalCode": "3122"
    },
    "description": "Bright 2 bedroom apartment located 350m from Glenferrie Station and Swinburne University.",
    "url": "https://www.nelsonalexander.com.au/property/1084512/3-163-burwood-road-hawthorn-vic-3122/",
    "photos": [
      "https://images.listonce.com.au/na/1084512_main.jpg",
      "https://images.listonce.com.au/na/1084512_kitchen.jpg"
    ]
  },
  {
    "@context": "https://schema.org",
    "@type": "Event",
    "name": "Inspection",
    "startDate": "2026-11-21T12:00:00+11:00",
    "endDate": "2026-11-21T12:15:00+11:00"
  }
]
</script>
</head>
<body>
  <h2>Available</h2>
  <h3>Monday 14th December 2026</h3>
  <h2>Price</h2>
  <h3>$525pw / $2281pcm</h3>
  <a href="https://www.2apply.com.au/Form?agentID=LO-NAHAWTHORN">Apply</a>
</body>
</html>
"""

_JC_DESC_B64 = base64.b64encode(
    json.dumps([
        "Renovated 2 bedroom apartment in a quiet leafy street.",
        "Only 5 minutes walk to Hawthorn train station and Burwood Road trams."
    ]).encode("utf-8")
).decode("utf-8")

JELLIS_CRAIG_LIST_HTML_FIXTURE = """<!DOCTYPE html>
<html>
<body>
<article class="property-card">
  <a href="/property-details-2-18-power-street-hawthorn/1654935">
    <img src="https://images.listonce.com.au/jc/1654935_1.jpg" alt="2/18 Power Street Hawthorn 3122" />
  </a>
  <h4>2/18 Power Street</h4>
  <p>Hawthorn</p>
  <div class="price">Rent: $520 pw</div>
  <ul>
    <li aria-label="2 Bed">2</li>
    <li aria-label="1 Bath">1</li>
    <li aria-label="1 Car">1</li>
  </ul>
</article>
</body>
</html>
"""

JELLIS_CRAIG_DETAIL_HTML_FIXTURE = f"""<!DOCTYPE html>
<html>
<head>
  <meta property="og:title" content="2/18 Power Street, Hawthorn | Jellis Craig" />
  <meta property="og:description" content="Fallback og description" />
</head>
<body>
  <div>FOR LEASE - Available December 11th 2026</div>
  <div data-full_desc='{_JC_DESC_B64}'></div>
  <input id="rentalEnquireHere_loAgentId" value="LO-JCBM-HAWT" />
</body>
</html>
"""

WOODARDS_DIRECTORY_HTML_FIXTURE = """<!DOCTYPE html>
<html>
<body>
<a href="/property/4-22-station-street-mitcham-3132-2009123/">
  <div class="property-list-item card-item">
    <img src="https://images.listonce.com.au/wd/2009123_1.jpg" />
    <div class="status-label">Available 15 Dec</div>
    <div class="title">Mitcham</div>
    <p class="subtitle">4/22 Station Street</p>
    <div class="price">$510 per week</div>
    <ul>
      <li><span>2</span><span class="icons bedroom-icon"></span></li>
      <li><span>1</span><span class="icons bathroom-icon"></span></li>
      <li><span>1</span><span class="icons parking-icon"></span></li>
    </ul>
  </div>
</a>
</body>
</html>
"""

WOODARDS_DETAIL_HTML_FIXTURE = """<!DOCTYPE html>
<html>
<head>
  <meta property="og:description" content="Delightful 2 bedroom unit just 300m to Mitcham Station on the direct Belgrave/Lilydale line to Hawthorn." />
</head>
<body>
  <div class="title">Property Type</div>
  <p class="subtitle">Unit</p>
  <div class="title">Inspection times</div>
  <div class="inspections-list">
    <div><p class="mr-auto pr-2">Sat, 21 November at 11:00AM</p></div>
  </div>
  <a href="https://www.2apply.com.au/agency/woodards%20blackburn?form=0">Apply</a>
</body>
</html>
"""

BELLE_PROPERTY_FIXTURE_HTML = """<!DOCTYPE html>
<html>
<body>
<article data-listing-id="BP-778899" data-beds="2" data-baths="1" data-cars="1">
  <a href="/listings/778899/12-glenferrie-road-hawthorn-vic-3122/"></a>
  <img src="https://images.belleproperty.com/778899_1.jpg" />
  <h3 class="property-address">12/88 Glenferrie Road, Hawthorn, VIC 3122</h3>
  <div class="property-price">$525 per week</div>
  <div class="property-avail">Available 10/12/2026</div>
  <div class="property-office">Belle Property Hawthorn</div>
</article>
</body>
</html>
"""

HARCOURTS_LIST_HTML_FIXTURE = """<!DOCTYPE html>
<html>
<body>
<ul class="card-list">
  <li class="card listing-card">
    <a href="/au/office/box-hill/listing/r2-4807867-7-82-campbell-road-hawthorn-east-vic-3123" data-category="rent">
      <div class="card-image">
        <div class="swiper-slide" data-src="https://listings-photos.cloudhi.io/harcourts/4807867_1.jpg"></div>
      </div>
      <div class="card-body">
        <div class="card-text">
          <h6 class="card-title property-title">Bright 2BR Unit Steps from Auburn Station</h6>
          <p>
            <span class="price d-block hi-price">$540 /week</span>
            <span class="address">7/82 Campbell Road, HAWTHORN EAST, VIC 3123</span>
          </p>
        </div>
        <div class="card-footer">
          <ul class="summary align-items-center">
            <li><span>2</span><img src="/bedroom.svg" alt="bedroom"></li>
            <li><span>1</span><img src="/bathroom.svg" alt="bathroom"></li>
            <li><span>1</span><img src="/garage.svg" alt="garage"></li>
          </ul>
        </div>
      </div>
    </a>
  </li>
</ul>
</body>
</html>
"""

BUXTON_API_JSON_FIXTURE = json.dumps({
    "results": [
        {
            "id": 133708,
            "source": "listonce",
            "listing_type": "rental",
            "transaction_type": "lease",
            "external_id": "2005888",
            "listonce_listing_id": 2005888,
            "title": "",
            "status": "available",
            "street_address": "4/19 Carrington Road",
            "suburb": "Box Hill",
            "postcode": "3128",
            "address_state": "VIC",
            "slug": "2005888-box-hill",
            "bedrooms": 2,
            "bathrooms": 1,
            "parking": 1,
            "price": 530.0,
            "publish_date": "2026-11-18T05:00:00Z",
            "card_badge_payload": {
                "rent_period": "Weekly",
                "rent": "530.00",
                "headline": "Walk to Box Hill Central & Express Trains"
            },
            "card_image_urls": [
                "https://images.listonce.com.au/custom/buxton/2005888_1.jpg",
                "https://images.listonce.com.au/custom/buxton/2005888_2.jpg"
            ]
        }
    ],
    "next_cursor": None
})

FLETCHERS_DIRECTORY_HTML_FIXTURE = """<!DOCTYPE html>
<html>
<body>
<ul class="properties-list">
  <li data-propertyid="48385" class="unit">
    <a class="block" href="https://fletchers.net.au/48385/2-14-canterbury-road-blackburn">
      <div class="photo">
        <img src="https://docspropertyme.clodflare.pushcreative.com.au/listing/48385_1.jpg" alt="2/14 Canterbury Road, Blackburn" />
      </div>
      <div class="details">
        <h2 class="address">
          <span class="suburb">Blackburn</span>
          <span class="streetaddress">2/14 Canterbury Road</span>
        </h2>
        <div class="pricetext">
          <span class="status">For Lease</span> $535 pw
        </div>
        <div class="icons">
          2 <i class="fal fa-bed"></i>
          1 <i class="fal fa-bath"></i>
          1 <i class="fal fa-car"></i>
          Unit
        </div>
      </div>
    </a>
  </li>
</ul>
</body>
</html>
"""

MCGRATH_JSONLD_HTML_FIXTURE = """<!DOCTYPE html>
<html>
<head>
<script type="application/ld+json">
{
  "@context": "https://schema.org",
  "@type": "Apartment",
  "id": "MC-901234",
  "name": "Sunlit 2 Bedroom Apartment in Blackburn",
  "description": "Unfurnished 2 bedroom apartment 350m from Blackburn Station.",
  "url": "https://www.mcgrath.com.au/rent/apartment-vic-blackburn-901234",
  "price": "$540 per week",
  "bedrooms": 2,
  "bathrooms": 1,
  "parking": 1,
  "available_date": "2026-12-12",
  "address": {
    "@type": "PostalAddress",
    "streetAddress": "6/24 South Parade",
    "addressLocality": "Blackburn",
    "addressRegion": "VIC",
    "postalCode": "3130"
  },
  "image": ["https://images.mcgrath.com.au/901234_1.jpg"]
}
</script>
</head>
<body></body>
</html>
"""


class TestDirectAgencySourcesV1(unittest.TestCase):
    """Comprehensive tests for all 10 Australian real estate agency adapters and utilities."""

    def test_rent_parsing_variations(self):
        """Test weekly rent extraction across agency price strings, date prefixes, and pcm."""
        self.assertEqual(parse_weekly_rent(560), 560.0)
        self.assertEqual(parse_weekly_rent("$560 per week"), 560.0)
        self.assertEqual(parse_weekly_rent("Rent: $575 pw"), 575.0)
        self.assertEqual(parse_weekly_rent("$525pw / $2281pcm"), 525.0)
        self.assertEqual(parse_weekly_rent("18/11/2026 - $545"), 545.0)
        self.assertEqual(parse_weekly_rent("$550/wk (Bond $2,200)"), 550.0)
        # Monthly-only conversion: $2,166.67 pcm -> ~$500/wk
        pcm_converted = parse_weekly_rent("$2,166.67 pcm")
        self.assertIsNotNone(pcm_converted)
        self.assertAlmostEqual(pcm_converted, 500.0, delta=0.5)
        self.assertIsNone(parse_weekly_rent("Contact Agent"))
        self.assertIsNone(parse_weekly_rent(""))

    def test_availability_date_parsing(self):
        """Test availability date normalization across all agency formats."""
        self.assertEqual(parse_availability_date("2026-12-17T00:00:00+11:00"), "2026-12-17")
        self.assertEqual(parse_availability_date("14/12/2026"), "2026-12-14")
        self.assertEqual(parse_availability_date("Monday 14th December 2026"), "2026-12-14")
        self.assertEqual(parse_availability_date("Available December 11th 2026"), "2026-12-11")
        self.assertEqual(parse_availability_date("Available 15 Dec", reference_year=2026), "2026-12-15")
        self.assertEqual(parse_availability_date("Available Now"), "Available Now")
        self.assertIsNone(parse_availability_date(None))

    def test_property_type_and_suburb_extraction(self):
        """Test property category normalization and suburb/postcode extraction."""
        self.assertEqual(normalise_property_type("THS", "Modern Townhouse"), "townhouse")
        self.assertEqual(normalise_property_type("Unit"), "unit")
        self.assertEqual(normalise_property_type("Apartment"), "apartment")
        self.assertEqual(normalise_property_type("Studio Apartment"), "studio")
        self.assertEqual(normalise_property_type("Car Space", "Secure Car Park Only"), "carspace")

        sub, pc = extract_suburb_and_postcode("5/11 Brougham Street, Box Hill, VIC 3128")
        self.assertEqual(sub, "Box Hill")
        self.assertEqual(pc, "3128")

        sub2, pc2 = extract_suburb_and_postcode("2/18 Power Street", fallback_suburb="Hawthorn")
        self.assertEqual(sub2, "Hawthorn")
        self.assertEqual(pc2, "3122")

    def test_adapter_common_interface_compliance(self):
        """Verify all 10 agency adapters implement the required 5-method common interface."""
        adapters = [
            BarryPlantAdapter(),
            RayWhiteAdapter(),
            JellisCraigAdapter(),
            NelsonAlexanderAdapter(),
            HarcourtsAdapter(),
            BellePropertyAdapter(),
            McGrathAdapter(),
            WoodardsAdapter(),
            BuxtonAdapter(),
            FletchersAdapter(),
        ]
        required_methods = (
            "fetch_listings",
            "parse_listing",
            "normalise_listing",
            "validate_listing",
            "get_source_health",
        )
        for adapter in adapters:
            self.assertIsInstance(adapter, BaseAgencyAdapter)
            for method_name in required_methods:
                self.assertTrue(
                    callable(getattr(adapter, method_name, None)),
                    f"{adapter.source_name} missing required method {method_name}",
                )

    def test_barry_plant_adapter_fixture_pipeline(self):
        """Test Barry Plant fetch, parse, normalise, validate, and health reporting."""
        def fake_fetcher(url, **kwargs):
            return BARRY_PLANT_DIRECTORY_HTML_FIXTURE

        adapter = BarryPlantAdapter(http_fetcher=fake_fetcher, max_detail_pages=0)
        props = adapter.collect()

        # Fixture has 2 items: 1 valid Box Hill 2BR @ $540/wk, 1 rejected Canterbury 4BR @ $1250/wk
        self.assertEqual(len(props), 1)
        prop = props[0]
        self.assertIsInstance(prop, Property)
        self.assertEqual(prop.source, "Barry Plant")
        self.assertEqual(prop.source_listing_id, "213056")
        self.assertEqual(prop.suburb, "Box Hill")
        self.assertEqual(prop.postcode, "3128")
        self.assertEqual(prop.weekly_rent, 540.0)
        self.assertEqual(prop.bedrooms, 2)
        self.assertEqual(prop.bathrooms, 1)
        self.assertEqual(prop.parking, 1)
        self.assertEqual(prop.property_type, "unit")
        self.assertEqual(prop.available_date, "2026-12-12")
        self.assertEqual(prop.agency_office, "Barry Plant Whitehorse")
        self.assertEqual(
            prop.source_url,
            "https://www.barryplant.com.au/rental-properties/5-11-brougham-street-box-hill-vic-3128-213056/",
        )
        self.assertEqual(len(prop.images), 2)
        self.assertEqual(len(prop.inspection_times), 1)
        self.assertTrue(prop.has_direct_hawthorn_transit)
        self.assertTrue(prop.pass_strict_filter)
        self.assertIsNotNone(prop.match_score)

        # Verify Phase 1 Section 4 standardised listing dictionary structure
        std_dict = prop.to_legacy_dict()
        required_std_keys = (
            "id", "source", "source_key", "agency_name", "title", "address",
            "suburb", "postcode", "weekly_rent", "bedrooms", "bathrooms",
            "parking", "property_type", "is_furnished", "date_available",
            "description", "photo", "url", "listed_at", "scraped_at",
            "last_verified_at", "verification_status",
        )
        for k in required_std_keys:
            self.assertIn(k, std_dict, f"Missing standardised key {k}")
        self.assertEqual(std_dict["source_key"], "barry_plant")
        self.assertEqual(std_dict["agency_name"], "Barry Plant Whitehorse")
        self.assertIsNone(std_dict["is_furnished"])

        # Verify source_provenance structure
        self.assertEqual(len(prop.source_provenance), 1)
        self.assertEqual(prop.source_provenance[0]["source_name"], "Barry Plant")
        self.assertEqual(prop.source_provenance[0]["source_listing_id"], "213056")
        self.assertEqual(prop.source_provenance[0]["agency_office"], "Barry Plant Whitehorse")

        # Verify source health metrics (including Phase 1 Section 7 fields)
        health = adapter.get_source_health()
        self.assertEqual(health["listings_discovered"], 2)
        self.assertEqual(health["listings_accepted"], 1)
        self.assertEqual(health["valid_listings"], 1)
        self.assertEqual(health["duplicates_count"], 0)
        self.assertEqual(health["listings_rejected"], 1)
        self.assertEqual(health["parsing_failures"], 0)
        self.assertEqual(health["http_errors"], 0)
        self.assertEqual(health["status"], "success")
        self.assertIsNotNone(health["scrape_start_time"])
        self.assertIsNotNone(health["scrape_end_time"])
        self.assertIsNotNone(health["scrape_completion_time"])
        self.assertIsNotNone(health["last_successful_collection"])

    def test_ray_white_adapter_fixture_pipeline(self):
        """Test Ray White JSON payload fetch, parse, normalise, and validate."""
        def fake_fetcher(url, **kwargs):
            return RAY_WHITE_API_JSON_FIXTURE

        adapter = RayWhiteAdapter(http_fetcher=fake_fetcher)
        props = adapter.collect()
        self.assertEqual(len(props), 1)

        prop = props[0]
        self.assertEqual(prop.source, "Ray White")
        self.assertEqual(prop.source_listing_id, "3618403")
        self.assertEqual(prop.address, "4/1 Rosella Avenue, Boronia, VIC 3155")
        self.assertEqual(prop.suburb, "Boronia")
        self.assertEqual(prop.postcode, "3155")
        self.assertEqual(prop.weekly_rent, 520.0)
        self.assertEqual(prop.bedrooms, 2)
        self.assertEqual(prop.bathrooms, 1)
        self.assertEqual(prop.parking, 1)
        self.assertEqual(prop.property_type, "townhouse")
        self.assertEqual(prop.available_date, "2026-12-10")
        self.assertEqual(prop.agency_office, "Ray White Ferntree Gully")
        self.assertEqual(prop.source_url, "https://www.raywhite.com/vic/boronia/3618403")
        self.assertEqual(len(prop.images), 2)
        self.assertEqual(len(prop.inspection_times), 1)
        self.assertTrue(prop.has_direct_hawthorn_transit)
        self.assertTrue(prop.pass_strict_filter)

    def test_nelson_alexander_adapter_fixture_pipeline(self):
        """Test Nelson Alexander directory + JSON-LD detail page extraction."""
        def fake_fetcher(url, **kwargs):
            if "/property/1084512/" in url:
                return NELSON_ALEXANDER_DETAIL_HTML_FIXTURE
            return NELSON_ALEXANDER_DIRECTORY_HTML_FIXTURE

        adapter = NelsonAlexanderAdapter(http_fetcher=fake_fetcher, max_pages=1)
        props = adapter.collect()
        self.assertEqual(len(props), 1)

        prop = props[0]
        self.assertEqual(prop.source, "Nelson Alexander")
        self.assertEqual(prop.source_listing_id, "1084512")
        self.assertEqual(prop.suburb, "Hawthorn")
        self.assertEqual(prop.postcode, "3122")
        self.assertEqual(prop.weekly_rent, 525.0)
        self.assertEqual(prop.bedrooms, 2)
        self.assertEqual(prop.available_date, "2026-12-14")
        self.assertEqual(prop.agency_office, "Nelson Alexander Hawthorn")
        self.assertEqual(len(prop.images), 2)
        self.assertEqual(len(prop.inspection_times), 1)
        self.assertIn("Glenferrie Station", prop.description)
        self.assertTrue(prop.pass_strict_filter)

    def test_jellis_craig_adapter_fixture_pipeline(self):
        """Test Jellis Craig list HTML + base64 detail description extraction."""
        def fake_fetcher(url, **kwargs):
            if "/property-details-" in url:
                return JELLIS_CRAIG_DETAIL_HTML_FIXTURE
            return JELLIS_CRAIG_LIST_HTML_FIXTURE

        adapter = JellisCraigAdapter(http_fetcher=fake_fetcher)
        props = adapter.collect()
        self.assertEqual(len(props), 1)

        prop = props[0]
        self.assertEqual(prop.source, "Jellis Craig")
        self.assertEqual(prop.source_listing_id, "1654935")
        self.assertEqual(prop.suburb, "Hawthorn")
        self.assertEqual(prop.postcode, "3122")
        self.assertEqual(prop.weekly_rent, 520.0)
        self.assertEqual(prop.bedrooms, 2)
        self.assertEqual(prop.available_date, "2026-12-11")
        self.assertEqual(prop.agency_office, "Jellis Craig Hawthorn")
        self.assertIn("Hawthorn train station", prop.description)
        self.assertTrue(prop.pass_strict_filter)

    def test_harcourts_adapter_fixture_pipeline(self):
        """Test Harcourts HTML card extraction, normalisation, and validation."""
        adapter = HarcourtsAdapter(
            http_fetcher=lambda url, **kw: HARCOURTS_LIST_HTML_FIXTURE,
            query_urls=["https://harcourts.net/au/listings/rent?search=VIC&maxPrice=650"],
        )
        props = adapter.collect()
        self.assertEqual(len(props), 1)
        prop = props[0]
        self.assertEqual(prop.source, "Harcourts")
        self.assertEqual(prop.source_listing_id, "r2-4807867")
        self.assertEqual(prop.suburb, "Hawthorn East")
        self.assertEqual(prop.postcode, "3123")
        self.assertEqual(prop.weekly_rent, 540.0)
        self.assertEqual(prop.bedrooms, 2)
        self.assertEqual(prop.bathrooms, 1)
        self.assertEqual(prop.parking, 1)
        self.assertEqual(prop.agency_office, "Harcourts Box Hill")
        self.assertTrue(prop.source_url.startswith("https://harcourts.net/au/office/box-hill/listing/"))
        self.assertTrue(prop.has_direct_hawthorn_transit)

    def test_buxton_adapter_fixture_pipeline(self):
        """Test Buxton JSON API extraction, normalisation, and validation."""
        adapter = BuxtonAdapter(
            http_fetcher=lambda url, **kw: BUXTON_API_JSON_FIXTURE,
            target_suburbs=[],
        )
        props = adapter.collect()
        self.assertEqual(len(props), 1)
        prop = props[0]
        self.assertEqual(prop.source, "Buxton")
        self.assertEqual(prop.source_listing_id, "2005888")
        self.assertEqual(prop.suburb, "Box Hill")
        self.assertEqual(prop.postcode, "3128")
        self.assertEqual(prop.weekly_rent, 530.0)
        self.assertEqual(prop.bedrooms, 2)
        self.assertEqual(prop.bathrooms, 1)
        self.assertEqual(prop.parking, 1)
        self.assertTrue(prop.source_url.startswith("https://buxton.com.au/property/2005888/"))
        self.assertTrue(prop.has_direct_hawthorn_transit)

    def test_fletchers_adapter_fixture_pipeline(self):
        """Test Fletchers eastern suburbs HTML tile extraction, normalisation, and validation."""
        adapter = FletchersAdapter(
            http_fetcher=lambda url, **kw: FLETCHERS_DIRECTORY_HTML_FIXTURE,
        )
        props = adapter.collect()
        self.assertEqual(len(props), 1)
        prop = props[0]
        self.assertEqual(prop.source, "Fletchers")
        self.assertEqual(prop.source_listing_id, "48385")
        self.assertEqual(prop.suburb, "Blackburn")
        self.assertEqual(prop.postcode, "3130")
        self.assertEqual(prop.weekly_rent, 535.0)
        self.assertEqual(prop.bedrooms, 2)
        self.assertEqual(prop.property_type, "unit")
        self.assertEqual(prop.source_url, "https://fletchers.net.au/48385/2-14-canterbury-road-blackburn")
        self.assertTrue(prop.has_direct_hawthorn_transit)

    def test_mcgrath_fixture_and_http_429_isolation(self):
        """Test McGrath JSON-LD fixture parsing AND live HTTP 429 rate-limit failure isolation."""
        adapter_ok = McGrathAdapter(http_fetcher=lambda url, **kw: MCGRATH_JSONLD_HTML_FIXTURE)
        props = adapter_ok.collect()
        self.assertEqual(len(props), 1)
        self.assertEqual(props[0].source, "McGrath")
        self.assertEqual(props[0].suburb, "Blackburn")
        self.assertEqual(props[0].weekly_rent, 540.0)
        self.assertEqual(props[0].furnished, False)

        def rate_limited_fetcher(url, **kwargs):
            raise urllib.error.HTTPError(url=url, code=429, msg="Too Many Requests", hdrs=None, fp=None)

        adapter_blocked = McGrathAdapter(http_fetcher=rate_limited_fetcher)
        blocked_props = adapter_blocked.collect()
        self.assertEqual(blocked_props, [])
        health = adapter_blocked.get_source_health()
        self.assertEqual(health["status"], "blocked")
        self.assertEqual(health["http_errors"], 1)
        self.assertIn("429", health["last_error"])

    def test_woodards_adapter_fixture_pipeline(self):
        """Test Woodards directory card + detail page extraction."""
        def fake_fetcher(url, **kwargs):
            if "4-22-station-street-mitcham" in url:
                return WOODARDS_DETAIL_HTML_FIXTURE
            return WOODARDS_DIRECTORY_HTML_FIXTURE

        adapter = WoodardsAdapter(http_fetcher=fake_fetcher, max_pages=1)
        props = adapter.collect()
        self.assertEqual(len(props), 1)

        prop = props[0]
        self.assertEqual(prop.source, "Woodards")
        self.assertEqual(prop.source_listing_id, "2009123")
        self.assertEqual(prop.suburb, "Mitcham")
        self.assertEqual(prop.postcode, "3132")
        self.assertEqual(prop.weekly_rent, 510.0)
        self.assertEqual(prop.bedrooms, 2)
        self.assertEqual(prop.property_type, "unit")
        self.assertEqual(prop.available_date, "2026-12-15")
        self.assertEqual(prop.agency_office, "Woodards Blackburn")
        self.assertEqual(prop.inspection_times, ["Sat, 21 November at 11:00AM"])
        self.assertTrue(prop.pass_strict_filter)

    def test_belle_property_fixture_and_http_403_isolation(self):
        """Test Belle Property fixture parsing AND live HTTP 403 WAF failure isolation."""
        # 1. Fixture parsing when HTML is provided
        adapter_ok = BellePropertyAdapter(http_fetcher=lambda url, **kw: BELLE_PROPERTY_FIXTURE_HTML)
        props = adapter_ok.collect()
        self.assertEqual(len(props), 1)
        self.assertEqual(props[0].source, "Belle Property")
        self.assertEqual(props[0].source_listing_id, "BP-778899")
        self.assertEqual(props[0].suburb, "Hawthorn")
        self.assertEqual(props[0].weekly_rent, 525.0)
        self.assertEqual(props[0].available_date, "2026-12-10")
        self.assertEqual(props[0].agency_office, "Belle Property Hawthorn")

        # 2. HTTP 403 Forbidden WAF simulation
        def blocked_fetcher(url, **kwargs):
            raise urllib.error.HTTPError(
                url=url, code=403, msg="Forbidden", hdrs=None, fp=None
            )

        adapter_blocked = BellePropertyAdapter(http_fetcher=blocked_fetcher)
        blocked_props = adapter_blocked.collect()
        self.assertEqual(blocked_props, [])
        health = adapter_blocked.get_source_health()
        self.assertEqual(health["status"], "blocked")
        self.assertEqual(health["http_errors"], 1)
        self.assertIn("403", health["last_error"])

    def test_cross_agency_deduplication_and_provenance_retention(self):
        """
        Verify that when the same property appears on multiple sources (e.g. Barry Plant
        and Ray White or Gumtree), deduplicate_properties merges them into a single
        Property record and retains all source URLs in source_provenance.
        """
        bp_adapter = BarryPlantAdapter(
            http_fetcher=lambda url, **kw: BARRY_PLANT_DIRECTORY_HTML_FIXTURE,
            max_detail_pages=0,
        )
        bp_prop = bp_adapter.collect()[0]

        # Simulate the same Box Hill property also appearing on a second source
        secondary_prop = Property.from_legacy({
            "id": "rw-998877",
            "source": "Ray White",
            "url": "https://www.raywhite.com/vic/box-hill/998877",
            "title": "2 Bedroom Unit Near Box Hill Station",
            "address": "Unit 5, 11 Brougham St, Box Hill",
            "suburb": "Box Hill",
            "postcode": "3128",
            "bedrooms": 2,
            "bathrooms": 1,
            "parking": 1,
            "property_type": "unit",
            "weekly_rent": 540.0,
            "agency_office": "Ray White Box Hill",
            "description": "Spacious two bedroom unit with polished floorboards and lock-up garage. 400m walk to Box Hill train station.",
        })

        conf, reasons = calculate_match_confidence(bp_prop, secondary_prop)
        self.assertGreaterEqual(conf, 0.85, f"Expected high confidence, got {conf}: {reasons}")

        deduped, flagged = deduplicate_properties([bp_prop, secondary_prop])
        self.assertEqual(len(deduped), 1)
        merged = deduped[0]

        self.assertEqual(len(merged.source_provenance), 2)
        prov_urls = {p["source_url"] for p in merged.source_provenance}
        self.assertIn(
            "https://www.barryplant.com.au/rental-properties/5-11-brougham-street-box-hill-vic-3128-213056/",
            prov_urls,
        )
        self.assertIn("https://www.raywhite.com/vic/box-hill/998877", prov_urls)

        # Persist merged property to SQLite and verify round-trip provenance retention
        with tempfile.TemporaryDirectory() as tmpdir:
            db = PropertyDatabase(Path(tmpdir) / "test.sqlite")
            db.upsert_property(merged)
            loaded = db.get_property(merged.property_id)
            self.assertIsNotNone(loaded)
            self.assertEqual(len(loaded.source_provenance), 2)
            self.assertEqual(loaded.agency_office, "Barry Plant Whitehorse")

    def test_multi_adapter_orchestration_isolates_failures(self):
        """
        Verify collect_all_agency_sources continues collecting when one or more
        agency scrapers fail with HTTP 403/500 or malformed payloads.
        """
        def failing_500_fetcher(url, **kwargs):
            raise urllib.error.HTTPError(url=url, code=500, msg="Internal Server Error", hdrs=None, fp=None)

        def failing_403_fetcher(url, **kwargs):
            raise urllib.error.HTTPError(url=url, code=403, msg="Forbidden", hdrs=None, fp=None)

        adapters = [
            BarryPlantAdapter(
                http_fetcher=lambda url, **kw: BARRY_PLANT_DIRECTORY_HTML_FIXTURE,
                max_detail_pages=0,
            ),
            RayWhiteAdapter(http_fetcher=failing_500_fetcher),
            BellePropertyAdapter(http_fetcher=failing_403_fetcher),
            WoodardsAdapter(
                http_fetcher=lambda url, **kw: WOODARDS_DIRECTORY_HTML_FIXTURE,
                max_pages=1,
                max_detail_fetches=0,
            ),
        ]

        props, health_map, logs = collect_all_agency_sources(adapters=adapters)
        # Barry Plant (1 accepted) + Woodards (1 accepted) = 2 properties despite Ray White 500 & Belle 403
        self.assertEqual(len(props), 2)
        self.assertEqual(health_map["Barry Plant"]["status"], "success")
        self.assertEqual(health_map["Ray White"]["status"], "failed")
        self.assertEqual(health_map["Ray White"]["http_errors"], 1)
        self.assertEqual(health_map["Belle Property"]["status"], "blocked")
        self.assertEqual(health_map["Woodards"]["status"], "success")
        self.assertEqual(len(logs), 4)


if __name__ == "__main__":
    unittest.main()
