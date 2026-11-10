"""
Comprehensive Test & Validation Suite for Melbourne Rental Finder V2.

Validates:
1. Unified Property Data Model & Backward Compatibility
2. Cross-Source Duplicate Detection & Confidence Ratings
3. Listing Freshness & Availability Lifecycle
4. 100-Point Explainable Scoring Engine & Hard Eligibility
5. Persistent Relational SQLite Database & Snapshots
6. V1 Regression & Suburb Transit Compatibility
"""

import json
import tempfile
import unittest
from datetime import datetime, timezone, timedelta
from pathlib import Path

from scraper.config import USER_CRITERIA, HAWTHORN_DIRECT_SUBURBS, get_budget_cap
from scraper.sources import is_outside_melbourne
from scraper.models import Property, ListingSource, ListingSnapshot, PropertyScore, ScraperExecutionLog
from scraper.dedup import (
    calculate_match_confidence,
    deduplicate_properties,
    normalize_address,
    compute_text_similarity,
)
from scraper.freshness import (
    compute_freshness_status,
    update_property_freshness,
    update_catalog_freshness,
)
from scraper.scorer_v2 import score_property_v2, evaluate_hard_eligibility
from scraper.scorer import score_and_classify_listing
from scraper.db import PropertyDatabase


class TestUnifiedPropertyModel(unittest.TestCase):
    """Test schema normalization, serialization, and legacy backward compatibility."""

    def test_legacy_conversion_preserves_all_fields(self):
        legacy = {
            "id": "gumtree_12345",
            "source": "gumtree",
            "url": "https://www.gumtree.com.au/web/listing/property-for-rent/12345",
            "title": "2 Bedroom Townhouse in Hawthorn",
            "address": "12 Burwood Rd, Hawthorn VIC 3122",
            "suburb": "Hawthorn",
            "postcode": "3122",
            "weekly_rent": 510.0,
            "is_furnished": False,
            "bedrooms": 2,
            "bathrooms": 1,
            "parking": 1,
            "is_lease_transfer": True,
            "is_sharehouse": False,
            "is_student_only": False,
            "match_score": 88.0,
            "commute_mins": 2,
            "station_name": "Hawthorn Station",
            "station_distance_m": 280,
            "listed_at": "2026-11-10T10:00:00Z",
        }

        prop = Property.from_legacy(legacy)
        self.assertEqual(prop.property_id, "prop_gumtree_12345")
        self.assertEqual(prop.suburb, "Hawthorn")
        self.assertEqual(prop.weekly_rent, 510.0)
        self.assertEqual(prop.bedrooms, 2)
        self.assertTrue(prop.lease_transfer)
        self.assertFalse(prop.furnished)

        # Convert back to legacy format
        exported = prop.to_legacy_dict()
        self.assertEqual(exported["id"], "prop_gumtree_12345")
        self.assertEqual(exported["url"], legacy["url"])
        self.assertEqual(exported["suburb"], "Hawthorn")
        self.assertEqual(exported["weekly_rent"], 510.0)
        self.assertEqual(exported["bedrooms"], 2)
        self.assertTrue(exported["is_lease_transfer"])
        self.assertFalse(exported["is_furnished"])
        self.assertTrue(exported["is_normal_listing"] is False)  # Because it's a lease transfer

    def test_direct_v2_dictionary_roundtrip(self):
        prop = Property(
            property_id="prop_direct_99",
            source="domain",
            source_listing_id="99",
            source_url="https://domain.com/99",
            title="Modern Flat",
            suburb="Richmond",
            postcode="3121",
            bedrooms=1,
            bathrooms=1,
            weekly_rent=450.0,
            match_score=82.0,
        )

        d = prop.to_dict()
        reconstituted = Property.from_dict(d)
        self.assertEqual(reconstituted.property_id, prop.property_id)
        self.assertEqual(reconstituted.suburb, "Richmond")
        self.assertEqual(reconstituted.weekly_rent, 450.0)


class TestDuplicateDetection(unittest.TestCase):
    """Test cross-source matching, confidence calculation, and multi-source merging."""

    def setUp(self):
        self.p_domain = Property(
            property_id="prop_domain_100",
            source="domain",
            source_listing_id="100",
            source_url="https://domain.com.au/100",
            title="Sunny 2BR Townhouse near Boronia Station",
            address="15 Campbell Road",
            suburb="Boronia",
            bedrooms=2,
            bathrooms=1,
            weekly_rent=520.0,
            description="Modern 2 bedroom townhouse, 300m to Boronia train station, private garage and courtyard.",
        )
        self.p_gumtree = Property(
            property_id="prop_gumtree_200",
            source="gumtree",
            source_listing_id="200",
            source_url="https://gumtree.com.au/200",
            title="2 Bed Townhouse Boronia - Campbell Rd",
            address="15 Campbell Rd",
            suburb="Boronia",
            bedrooms=2,
            bathrooms=1,
            weekly_rent=520.0,
            description="2 bed townhouse in Boronia near train station, garage included, courtyard.",
        )
        self.p_different = Property(
            property_id="prop_flatmates_300",
            source="flatmates",
            source_listing_id="300",
            source_url="https://flatmates.com.au/300",
            title="1BR Studio in Richmond",
            address="100 Swan Street",
            suburb="Richmond",
            bedrooms=1,
            bathrooms=1,
            weekly_rent=420.0,
            description="Compact studio apartment in Richmond near nightlife.",
        )

    def test_address_normalization(self):
        self.assertEqual(normalize_address("15 Campbell Road"), "15 campbell rd")
        self.assertEqual(normalize_address("Unit 3/14 Station Street"), "3/14 station st")
        self.assertEqual(normalize_address("Apt 5, 88 Burwood Highway"), "5 88 burwood hwy")

    def test_high_confidence_duplicate(self):
        conf, reasons = calculate_match_confidence(self.p_domain, self.p_gumtree)
        self.assertGreaterEqual(conf, 0.85)
        self.assertTrue(any("Exact street address" in r for r in reasons))

        deduped, flagged = deduplicate_properties([self.p_domain, self.p_gumtree])
        self.assertEqual(len(deduped), 1)
        self.assertEqual(len(deduped[0].sources), 2)

    def test_different_suburbs_zero_confidence(self):
        conf, reasons = calculate_match_confidence(self.p_domain, self.p_different)
        self.assertEqual(conf, 0.0)
        self.assertIn("Different suburbs", reasons)


class TestFreshnessTracking(unittest.TestCase):
    """Test listing age calculations, stale detection, and lifecycle status."""

    def test_freshness_lifecycle_states(self):
        now = datetime.now(timezone.utc)

        # Discovered 6 hours ago
        first_6h = (now - timedelta(hours=6)).isoformat()
        last_now = now.isoformat()
        status, age, is_new = compute_freshness_status(first_6h, last_now, current_time=now)
        self.assertEqual(status, "active")
        self.assertTrue(is_new)
        self.assertAlmostEqual(age, 6.0, delta=0.5)

        # Unseen for 10 days -> potentially_unavailable
        first_old = (now - timedelta(days=20)).isoformat()
        last_10d = (now - timedelta(days=10)).isoformat()
        status, age, is_new = compute_freshness_status(first_old, last_10d, current_time=now)
        self.assertEqual(status, "potentially_unavailable")
        self.assertFalse(is_new)

        # Unseen for 25 days -> expired
        last_25d = (now - timedelta(days=25)).isoformat()
        status, _, _ = compute_freshness_status(first_old, last_25d, current_time=now)
        self.assertEqual(status, "expired")

    def test_catalog_freshness_update(self):
        p1 = Property(
            property_id="p1",
            source="gumtree",
            source_listing_id="1",
            source_url="http://example.com/1",
            first_seen=datetime.now(timezone.utc).isoformat(),
            last_seen=datetime.now(timezone.utc).isoformat(),
        )
        catalog, stats = update_catalog_freshness([p1], current_run_ids={"p1"})
        self.assertEqual(stats["active"], 1)
        self.assertEqual(catalog[0].listing_status, "active")


class TestScoringEngineV2(unittest.TestCase):
    """Test 100-point explainable scoring engine, hard criteria, and factor transparency."""

    def test_hard_eligibility_exclusions(self):
        # Sharehouse rejected
        is_ok, reasons = evaluate_hard_eligibility(
            weekly_rent=400.0,
            is_furnished=False,
            is_entire_property=False,
            is_student_only=False,
            is_sharehouse=True,
        )
        self.assertFalse(is_ok)
        self.assertTrue(any("Sharehouse" in r for r in reasons))

        # Student only rejected
        is_ok, reasons = evaluate_hard_eligibility(
            weekly_rent=400.0,
            is_furnished=False,
            is_entire_property=True,
            is_student_only=True,
            is_sharehouse=False,
        )
        self.assertFalse(is_ok)
        self.assertTrue(any("student-only" in r.lower() for r in reasons))

        # Unrealistic price rejected
        is_ok, reasons = evaluate_hard_eligibility(
            weekly_rent=150.0,
            is_furnished=False,
            is_entire_property=True,
            is_student_only=False,
            is_sharehouse=False,
        )
        self.assertFalse(is_ok)

    def test_100_point_weight_distribution(self):
        prop = Property(
            property_id="p_top_match",
            source="domain",
            source_listing_id="777",
            source_url="https://domain.com/777",
            title="Stunning 2BR Townhouse near Station",
            suburb="Hawthorn",
            bedrooms=2,
            bathrooms=1,
            parking=1,
            weekly_rent=480.0,
            furnished=False,
            property_entire=True,
            station_name="Hawthorn Station",
            station_distance_m=250,
            station_walking_mins=3,
            station_distance_display="~250m to Hawthorn Station (3 min walk)",
            station_is_explicit=True,
            availability_fit="ideal",
            availability_display="Dec 15, 2026",
            description="Beautiful 2 bedroom townhouse, parking space, balcony, steps to Hawthorn station.",
        )

        scored = score_property_v2(prop)
        self.assertEqual(scored.score_version, "2.0")
        self.assertEqual(scored.score_confidence, "high")
        self.assertGreaterEqual(scored.match_score, 85)

        bd = scored.score_breakdown
        self.assertEqual(bd["rent_affordability"]["max"], 25)
        self.assertEqual(bd["commute_convenience"]["max"], 25)
        self.assertEqual(bd["property_suitability"]["max"], 20)
        self.assertEqual(bd["move_in_timing"]["max"], 15)
        self.assertEqual(bd["amenities"]["max"], 10)
        self.assertEqual(bd["freshness"]["max"], 5)
        self.assertEqual(sum(b["max"] for b in bd.values()), 100)

        # Check positive factors and concerns
        self.assertGreaterEqual(len(scored.positive_factors), 4)
        self.assertTrue(any("within budget" in f.lower() or "value" in f.lower() for f in scored.positive_factors))


class TestPersistentDatabase(unittest.TestCase):
    """Test SQLite persistence, automatic snapshots, interactions, and JSON export."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test_rentals.sqlite"
        self.db = PropertyDatabase(self.db_path)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_upsert_and_snapshot_generation(self):
        prop = Property(
            property_id="prop_db_1",
            source="domain",
            source_listing_id="db1",
            source_url="https://domain.com/db1",
            title="Spacious Unit in Boronia",
            suburb="Boronia",
            bedrooms=2,
            weekly_rent=500.0,
            match_score=82.0,
        )

        # 1. First insert creates initial snapshot
        is_new = self.db.upsert_property(prop)
        self.assertTrue(is_new)

        snapshots = self.db.get_price_history("prop_db_1")
        self.assertEqual(len(snapshots), 1)
        self.assertEqual(snapshots[0]["weekly_rent"], 500.0)

        # 2. Update without price/availability change should NOT create redundant snapshot
        prop.title = "Spacious Unit in Boronia (Updated Title)"
        is_new = self.db.upsert_property(prop)
        self.assertFalse(is_new)
        snapshots = self.db.get_price_history("prop_db_1")
        self.assertEqual(len(snapshots), 1)

        # 3. Price drop creates second snapshot
        prop.weekly_rent = 475.0
        self.db.upsert_property(prop)
        snapshots = self.db.get_price_history("prop_db_1")
        self.assertEqual(len(snapshots), 2)
        self.assertEqual(snapshots[1]["weekly_rent"], 475.0)

    def test_user_interaction_logging(self):
        prop = Property(
            property_id="prop_db_interact",
            source="gumtree",
            source_listing_id="g1",
            source_url="https://gumtree.com/g1",
            suburb="Richmond",
            weekly_rent=530.0,
        )
        self.db.upsert_property(prop)
        self.db.record_user_interaction("prop_db_interact", "inspect", {"inspection_date": "2026-12-08 14:00"})

        with self.db.get_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM user_interactions WHERE property_id = ?", ("prop_db_interact",))
            row = cur.fetchone()
            self.assertIsNotNone(row)
            self.assertEqual(row["action_type"], "inspect")
            payload = json.loads(row["payload_json"])
            self.assertEqual(payload["inspection_date"], "2026-12-08 14:00")

    def test_export_to_listings_json(self):
        prop = Property(
            property_id="prop_db_export",
            source="flatmates",
            source_listing_id="f1",
            source_url="https://flatmates.com/f1",
            suburb="Clayton",
            bedrooms=2,
            weekly_rent=490.0,
            match_score=84.0,
            listing_status="active",
        )
        self.db.upsert_property(prop)

        export_file = Path(self.temp_dir.name) / "exported_listings.json"
        payload = self.db.export_to_listings_json(export_file)

        self.assertTrue(export_file.exists())
        self.assertIn("listings", payload)
        self.assertEqual(len(payload["listings"]), 1)
        self.assertEqual(payload["listings"][0]["id"], "prop_db_export")
        self.assertEqual(payload["listings"][0]["suburb"], "Clayton")


class TestV1Regression(unittest.TestCase):
    """Ensure all V1 criteria, suburb transit mappings, and scoring baselines remain intact."""

    def test_hawthorn_direct_corridor_suburbs(self):
        # All target suburbs must exist and have transit mappings
        key_suburbs = ["hawthorn", "richmond", "burnley", "camberwell", "box hill", "clayton", "bayswater", "boronia"]
        for sub in key_suburbs:
            self.assertIn(sub, HAWTHORN_DIRECT_SUBURBS)
            info = HAWTHORN_DIRECT_SUBURBS[sub]
            self.assertIn("mode", info)
            self.assertIn("commute_mins", info)
            self.assertIn("tier", info)

    def test_v1_legacy_scorer_output_integrity(self):
        raw = {
            "id": "v1_test_listing",
            "title": "2 Bedroom Apartment in Camberwell",
            "address": "Camberwell",
            "price_text": "$500 pw",
            "description": "Lovely 2BR apartment 200m from Camberwell train station.",
        }
        enriched = score_and_classify_listing(raw)

        # Must have legacy keys
        self.assertEqual(enriched["id"], "v1_test_listing")
        self.assertEqual(enriched["suburb"], "Camberwell")
        self.assertEqual(enriched["weekly_rent"], 500)
        self.assertEqual(enriched["bedrooms"], 2)
        self.assertTrue(enriched["pass_strict_filter"])
        self.assertGreater(enriched["match_score"], 70)

        # Must also have V2 enhanced keys
        self.assertEqual(enriched.get("score_version"), "2.0")
        self.assertIn("rent_affordability", enriched.get("score_breakdown", {}))
        self.assertGreater(len(enriched.get("positive_factors", [])), 0)


class TestBHKBudgetRules(unittest.TestCase):
    """Test granular BHK & furnishing budget rules:
    - 2 BHK house: Furnished up to $625/wk, Unfurnished up to $560/wk
    - 1 BHK: Furnished up to $500/wk, Unfurnished up to $400/wk
    """

    def test_budget_cap_helper(self):
        # 2 BHK
        self.assertEqual(get_budget_cap(2, is_furnished=True), 625)
        self.assertEqual(get_budget_cap(2, is_furnished=False), 560)
        self.assertEqual(get_budget_cap(3, is_furnished=True), 625)
        self.assertEqual(get_budget_cap(3, is_furnished=False), 560)
        # 1 BHK
        self.assertEqual(get_budget_cap(1, is_furnished=True), 500)
        self.assertEqual(get_budget_cap(1, is_furnished=False), 400)
        self.assertEqual(get_budget_cap(0, is_furnished=True), 500)
        self.assertEqual(get_budget_cap(0, is_furnished=False), 400)

    def test_2bhk_furnished_budget_enforcement(self):
        # $620 <= $625: passes
        ok, reasons = evaluate_hard_eligibility(
            weekly_rent=620.0, is_furnished=True, is_entire_property=True,
            is_student_only=False, is_sharehouse=False, bedrooms=2
        )
        self.assertTrue(ok)
        self.assertEqual(len(reasons), 0)

        # $630 > $625: fails
        ok, reasons = evaluate_hard_eligibility(
            weekly_rent=630.0, is_furnished=True, is_entire_property=True,
            is_student_only=False, is_sharehouse=False, bedrooms=2
        )
        self.assertFalse(ok)
        self.assertTrue(any("Over budget" in r and "625" in r for r in reasons))

    def test_2bhk_unfurnished_budget_enforcement(self):
        # $550 <= $560: passes
        ok, reasons = evaluate_hard_eligibility(
            weekly_rent=550.0, is_furnished=False, is_entire_property=True,
            is_student_only=False, is_sharehouse=False, bedrooms=2
        )
        self.assertTrue(ok)
        self.assertEqual(len(reasons), 0)

        # $575 > $560: fails
        ok, reasons = evaluate_hard_eligibility(
            weekly_rent=575.0, is_furnished=False, is_entire_property=True,
            is_student_only=False, is_sharehouse=False, bedrooms=2
        )
        self.assertFalse(ok)
        self.assertTrue(any("Over budget" in r and "560" in r for r in reasons))

    def test_1bhk_furnished_budget_enforcement(self):
        # $490 <= $500: passes
        ok, reasons = evaluate_hard_eligibility(
            weekly_rent=490.0, is_furnished=True, is_entire_property=True,
            is_student_only=False, is_sharehouse=False, bedrooms=1
        )
        self.assertTrue(ok)
        self.assertEqual(len(reasons), 0)

        # $510 > $500: fails
        ok, reasons = evaluate_hard_eligibility(
            weekly_rent=510.0, is_furnished=True, is_entire_property=True,
            is_student_only=False, is_sharehouse=False, bedrooms=1
        )
        self.assertFalse(ok)
        self.assertTrue(any("Over budget" in r and "500" in r for r in reasons))

    def test_1bhk_unfurnished_budget_enforcement(self):
        # $395 <= $400: passes
        ok, reasons = evaluate_hard_eligibility(
            weekly_rent=395.0, is_furnished=False, is_entire_property=True,
            is_student_only=False, is_sharehouse=False, bedrooms=1
        )
        self.assertTrue(ok)
        self.assertEqual(len(reasons), 0)

        # $430 > $400: fails
        ok, reasons = evaluate_hard_eligibility(
            weekly_rent=430.0, is_furnished=False, is_entire_property=True,
            is_student_only=False, is_sharehouse=False, bedrooms=1
        )
        self.assertFalse(ok)
        self.assertTrue(any("Over budget" in r and "400" in r for r in reasons))


class TestInterstateListingExclusion(unittest.TestCase):
    """Test detection and exclusion of listings outside Greater Melbourne (ACT, NSW, QLD, etc.)."""

    def test_interstate_detection_rules(self):
        # Canberra / ACT
        self.assertTrue(is_outside_melbourne(suburb="Canberra City", address="Canberra City, ACT 2601"))
        self.assertTrue(is_outside_melbourne(suburb="Barton", address="Barton, ACT 2600"))

        # Sydney / NSW
        self.assertTrue(is_outside_melbourne(suburb="Wolli Creek", address="Wolli Creek, NSW 2205"))
        self.assertTrue(is_outside_melbourne(suburb="Surry Hills", address="Surry Hills, NSW 2010"))
        self.assertTrue(is_outside_melbourne(suburb="Parramatta", address="Parramatta NSW"))

        # Melbourne Surrey Hills (VIC 3127) must NOT be excluded
        self.assertFalse(is_outside_melbourne(suburb="Surrey Hills", address="Surrey Hills, VIC 3127"))
        self.assertFalse(is_outside_melbourne(suburb="Hawthorn", address="Hawthorn, VIC 3122"))
        self.assertFalse(is_outside_melbourne(suburb="Boronia", address="Boronia VIC 3155"))

    def test_scoring_rejects_interstate(self):
        # Canberra listing scored via score_property_v2
        p_act = Property(
            property_id="p_act_1",
            source="gumtree",
            source_listing_id="1345474789",
            source_url="https://gumtree.com.au/1345474789",
            title="Apartment in Canberra City",
            suburb="Canberra City",
            address="Canberra City, ACT 2601",
            bedrooms=2,
            weekly_rent=550.0,
        )
        scored = score_property_v2(p_act)
        self.assertFalse(scored.pass_strict_filter)
        self.assertTrue(any("outside greater melbourne" in r.lower() for r in scored.rejection_reasons))

        # Legacy score_and_classify_listing rejects interstate
        raw_nsw = {
            "id": "raw_nsw_1",
            "title": "Apartment in Wolli Creek",
            "address": "Wolli Creek, NSW 2205",
            "suburb": "Wolli Creek",
            "price_text": "$520 pw",
        }
        res = score_and_classify_listing(raw_nsw)
        self.assertFalse(res["pass_strict_filter"])
        self.assertIn("Outside Greater Melbourne", res.get("rejection_reason", ""))


class TestHawthornTransitFilter(unittest.TestCase):
    """Test direct train or tram line to Hawthorn classification."""

    def test_direct_suburbs_flagged(self):
        direct_examples = ["Hawthorn", "Camberwell", "Box Hill", "Bayswater", "Boronia", "Clayton", "Richmond", "Belgrave"]
        for sub in direct_examples:
            p = Property(
                property_id=f"p_{sub.lower()}",
                source="domain",
                source_listing_id="1",
                source_url="https://domain.com/1",
                title=f"2BR in {sub}",
                suburb=sub,
                bedrooms=2,
                weekly_rent=520.0,
            )
            scored = score_property_v2(p)
            self.assertTrue(scored.has_direct_hawthorn_transit, f"{sub} should have direct Hawthorn transit")

    def test_indirect_or_distant_suburbs_flagged_false(self):
        indirect_examples = ["Tarneit", "Geelong", "Ballarat", "Craigieburn", "Werribee"]
        for sub in indirect_examples:
            p = Property(
                property_id=f"p_{sub.lower()}",
                source="domain",
                source_listing_id="1",
                source_url="https://domain.com/1",
                title=f"2BR in {sub}",
                suburb=sub,
                bedrooms=2,
                weekly_rent=400.0,
            )
            scored = score_property_v2(p)
            self.assertFalse(scored.has_direct_hawthorn_transit, f"{sub} should NOT have direct Hawthorn transit")


if __name__ == "__main__":
    unittest.main()
