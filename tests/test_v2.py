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
from scraper.sources import is_outside_melbourne, scrape_facebook_marketplace_aligned, FB_MARKETPLACE_PRIMARY_URL
from scraper.run_scraper import build_portal_quick_links
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
from scraper.ai_agent import RentalAIEvaluatorAgent, evaluate_property_ai


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
            suburb="Ringwood",
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
        self.assertEqual(payload["listings"][0]["suburb"], "Ringwood")

    def test_sync_user_decisions_and_skipped_suppression(self):
        # 1. Insert 3 active properties (one matched by ID, one by address, one by URL)
        p1 = Property(
            property_id="prop_skip_id",
            source="raywhite",
            source_listing_id="rw_1",
            source_url="https://raywhite.com/rent/prop1",
            address="15 Burwood Rd, Hawthorn",
            suburb="Hawthorn",
            bedrooms=2,
            weekly_rent=500.0,
            match_score=85.0,
            pass_strict_filter=True,
            listing_status="active",
        )
        p2 = Property(
            property_id="prop_skip_addr",
            source="barryplant",
            source_listing_id="bp_2",
            source_url="https://barryplant.com.au/rent/prop2",
            address="10 Glenferrie Road, Hawthorn VIC 3122",
            suburb="Hawthorn",
            bedrooms=2,
            weekly_rent=520.0,
            match_score=88.0,
            pass_strict_filter=True,
            listing_status="active",
        )
        p3 = Property(
            property_id="prop_skip_url",
            source="jelliscraig",
            source_listing_id="jc_3",
            source_url="https://www.jelliscraig.com.au/property/123-church-st-richmond?utm_source=ad",
            address="123 Church St, Richmond",
            suburb="Richmond",
            bedrooms=2,
            weekly_rent=540.0,
            match_score=82.0,
            pass_strict_filter=True,
            listing_status="active",
        )
        p4 = Property(
            property_id="prop_active_keep",
            source="woodards",
            source_listing_id="wd_4",
            source_url="https://woodards.com.au/rent/prop4",
            address="88 Riversdale Rd, Hawthorn",
            suburb="Hawthorn",
            bedrooms=2,
            weekly_rent=510.0,
            match_score=90.0,
            pass_strict_filter=True,
            listing_status="active",
        )

        for p in (p1, p2, p3, p4):
            self.db.upsert_property(p)

        # 2. Write a mock user_decisions.json
        decisions_path = Path(self.temp_dir.name) / "test_user_decisions.json"
        decisions_data = {
            "version": "1.0",
            "updated_at": "2026-11-24T00:00:00Z",
            "statuses": {
                "prop_skip_id": "skipped",
                "prop_active_keep": "shortlist",
            },
            "skipped_addresses": [
                "10 glenferrie rd hawthorn",
            ],
            "skipped_urls": [
                "https://www.jelliscraig.com.au/property/123-church-st-richmond",
            ],
            "inspections": {},
            "notes": {},
        }
        decisions_path.write_text(json.dumps(decisions_data), encoding="utf-8")

        # 3. Sync decisions
        sync_result = self.db.sync_user_decisions(decisions_path)
        self.assertGreater(sync_result.get("skipped_marked", 0), 0)

        # 4. Verify skipped properties are marked in DB
        with self.db.get_connection() as conn:
            cur = conn.cursor()
            for pid in ("prop_skip_id", "prop_skip_addr", "prop_skip_url"):
                cur.execute("SELECT listing_status, pass_strict_filter, match_score FROM properties WHERE property_id = ?", (pid,))
                row = cur.fetchone()
                self.assertEqual(row["listing_status"], "skipped", f"Property {pid} should be marked skipped")
                self.assertEqual(row["pass_strict_filter"], 0, f"Property {pid} should fail strict filter")
                self.assertEqual(row["match_score"], 0.0, f"Property {pid} match score should be 0.0")

            # p4 must remain active
            cur.execute("SELECT listing_status, pass_strict_filter FROM properties WHERE property_id = ?", ("prop_active_keep",))
            row = cur.fetchone()
            self.assertEqual(row["listing_status"], "active")
            self.assertEqual(row["pass_strict_filter"], 1)

        # 5. Verify get_skipped_identifiers
        skipped = self.db.get_skipped_identifiers()
        self.assertIn("prop_skip_id", skipped["ids"])
        self.assertIn("10 glenferrie rd hawthorn", skipped["addresses"])
        self.assertIn("https://www.jelliscraig.com.au/property/123-church-st-richmond", skipped["urls"])

        # 6. Verify export_to_listings_json completely excludes skipped properties
        export_file = Path(self.temp_dir.name) / "test_clean_export.json"
        exported = self.db.export_to_listings_json(export_file)
        exported_ids = [item["id"] for item in exported["listings"]]
        self.assertEqual(exported_ids, ["prop_active_keep"])
        self.assertNotIn("prop_skip_id", exported_ids)
        self.assertNotIn("prop_skip_addr", exported_ids)
        self.assertNotIn("prop_skip_url", exported_ids)


class TestV1Regression(unittest.TestCase):
    """Ensure all V1 criteria, suburb transit mappings, and scoring baselines remain intact."""

    def test_hawthorn_direct_corridor_suburbs(self):
        # All target suburbs must exist and have transit mappings; Clayton must be excluded
        self.assertNotIn("clayton", HAWTHORN_DIRECT_SUBURBS)
        self.assertNotIn("clayton south", HAWTHORN_DIRECT_SUBURBS)
        key_suburbs = ["hawthorn", "richmond", "burnley", "camberwell", "box hill", "mitcham", "ringwood", "bayswater", "boronia"]
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
    """Test strict 2+ bedroom minimum requirement and budget rules:
    - Studio: rejected
    - 1BR: rejected
    - 2BR unfurnished at $560: eligible
    - 2BR unfurnished above $560: over budget
    - 2BR furnished at $625: eligible
    - 2BR furnished above $625: over budget
    - Entire 3BR property: eligible if within budget
    - Sharehouse: rejected
    - Unknown bedroom count: unverified and excluded from eligible recommendations
    """

    def test_budget_cap_helper(self):
        # 2+ BHK caps
        self.assertEqual(get_budget_cap(2, is_furnished=True), 625)
        self.assertEqual(get_budget_cap(2, is_furnished=False), 560)
        self.assertEqual(get_budget_cap(3, is_furnished=True), 625)
        self.assertEqual(get_budget_cap(3, is_furnished=False), 560)
        # Fallback / backward compat defaults to canonical caps
        self.assertEqual(get_budget_cap(1, is_furnished=True), 625)
        self.assertEqual(get_budget_cap(1, is_furnished=False), 560)
        self.assertEqual(get_budget_cap(None, is_furnished=False), 560)

    def test_2br_unfurnished_at_560_eligible(self):
        # 2BR unfurnished at exactly $560: eligible
        ok, reasons = evaluate_hard_eligibility(
            weekly_rent=560.0, is_furnished=False, is_entire_property=True,
            is_student_only=False, is_sharehouse=False, bedrooms=2
        )
        self.assertTrue(ok)
        self.assertEqual(len(reasons), 0)

    def test_2br_unfurnished_above_560_over_budget(self):
        # 2BR unfurnished above $560: over budget
        ok, reasons = evaluate_hard_eligibility(
            weekly_rent=565.0, is_furnished=False, is_entire_property=True,
            is_student_only=False, is_sharehouse=False, bedrooms=2
        )
        self.assertFalse(ok)
        self.assertTrue(any("Over budget" in r and "560" in r for r in reasons))

    def test_2br_furnished_at_625_eligible(self):
        # 2BR furnished at exactly $625: eligible
        ok, reasons = evaluate_hard_eligibility(
            weekly_rent=625.0, is_furnished=True, is_entire_property=True,
            is_student_only=False, is_sharehouse=False, bedrooms=2
        )
        self.assertTrue(ok)
        self.assertEqual(len(reasons), 0)

    def test_2br_furnished_above_625_over_budget(self):
        # 2BR furnished above $625: over budget
        ok, reasons = evaluate_hard_eligibility(
            weekly_rent=630.0, is_furnished=True, is_entire_property=True,
            is_student_only=False, is_sharehouse=False, bedrooms=2
        )
        self.assertFalse(ok)
        self.assertTrue(any("Over budget" in r and "625" in r for r in reasons))

    def test_entire_3br_property_eligible_within_budget(self):
        # Entire 3BR property within budget ($540 unfurnished, $600 furnished): eligible
        ok_unfurn, reasons_unfurn = evaluate_hard_eligibility(
            weekly_rent=540.0, is_furnished=False, is_entire_property=True,
            is_student_only=False, is_sharehouse=False, bedrooms=3
        )
        self.assertTrue(ok_unfurn)
        self.assertEqual(len(reasons_unfurn), 0)

        ok_furn, reasons_furn = evaluate_hard_eligibility(
            weekly_rent=600.0, is_furnished=True, is_entire_property=True,
            is_student_only=False, is_sharehouse=False, bedrooms=3
        )
        self.assertTrue(ok_furn)
        self.assertEqual(len(reasons_furn), 0)

        # 3BR above budget: over budget
        ok_over, reasons_over = evaluate_hard_eligibility(
            weekly_rent=650.0, is_furnished=False, is_entire_property=True,
            is_student_only=False, is_sharehouse=False, bedrooms=3
        )
        self.assertFalse(ok_over)
        self.assertTrue(any("Over budget" in r for r in reasons_over))

    def test_studio_rejected(self):
        # Studio properties explicitly rejected
        ok, reasons = evaluate_hard_eligibility(
            weekly_rent=350.0, is_furnished=False, is_entire_property=True,
            is_student_only=False, is_sharehouse=False, bedrooms=0,
            property_type="studio"
        )
        self.assertFalse(ok)
        self.assertTrue(any("Studio properties are ineligible" in r for r in reasons))

    def test_1br_rejected(self):
        # 1-bedroom properties explicitly rejected
        ok, reasons = evaluate_hard_eligibility(
            weekly_rent=380.0, is_furnished=False, is_entire_property=True,
            is_student_only=False, is_sharehouse=False, bedrooms=1,
            property_type="apartment"
        )
        self.assertFalse(ok)
        self.assertTrue(any("Ineligible bedroom count (1BR; minimum 2 bedrooms required)" in r for r in reasons))

    def test_sharehouse_rejected(self):
        # Sharehouse explicitly rejected even with 2+ bedrooms
        ok, reasons = evaluate_hard_eligibility(
            weekly_rent=300.0, is_furnished=True, is_entire_property=False,
            is_student_only=False, is_sharehouse=True, bedrooms=2
        )
        self.assertFalse(ok)
        self.assertTrue(any("Sharehouse" in r for r in reasons))

    def test_unknown_bedroom_count_unverified_and_excluded(self):
        # Unknown/missing bedroom count: unverified and excluded
        ok, reasons = evaluate_hard_eligibility(
            weekly_rent=500.0, is_furnished=False, is_entire_property=True,
            is_student_only=False, is_sharehouse=False, bedrooms=None
        )
        self.assertFalse(ok)
        self.assertTrue(any("Missing or unverified bedroom count" in r for r in reasons))

        # Scorer v2 sets pass_strict_filter=False and match_score=0.0
        prop_unknown = Property(
            property_id="p_unknown_beds",
            source="domain",
            source_listing_id="999",
            source_url="https://domain.com/999",
            title="Apartment in Hawthorn",
            suburb="Hawthorn",
            weekly_rent=500.0,
            bedrooms=None,
        )
        scored = score_property_v2(prop_unknown)
        self.assertFalse(scored.pass_strict_filter)
        self.assertEqual(scored.match_score, 0.0)
        self.assertEqual(scored.listing_status, "ineligible")


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
        direct_examples = ["Hawthorn", "Camberwell", "Box Hill", "Mitcham", "Ringwood", "Bayswater", "Boronia", "Richmond", "Belgrave"]
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
        indirect_examples = ["Clayton", "Tarneit", "Geelong", "Ballarat", "Craigieburn", "Werribee"]
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


class TestFacebookMarketplaceSource(unittest.TestCase):
    """Test Facebook Marketplace source ingestion and strict suburb corridor alignment."""

    def test_aligned_facebook_marketplace_ingestion(self):
        items = scrape_facebook_marketplace_aligned()
        self.assertGreater(len(items), 0, "Should return verified FB Marketplace listings")

        for item in items:
            self.assertEqual(item["source"], "Facebook Marketplace")
            self.assertEqual(item["source_key"], "facebook_marketplace")
            suburb_clean = item["suburb"].strip().lower()
            # Must strictly belong to the 27 Hawthorn transit corridors
            self.assertIn(suburb_clean, HAWTHORN_DIRECT_SUBURBS)
            # Must not be interstate
            self.assertFalse(is_outside_melbourne(item.get("address", ""), item.get("title", ""), item.get("description", ""), suburb_clean))
            # Must satisfy BHK budget rules
            bedrooms = item.get("bedrooms") or 2
            is_furn = bool(item.get("is_furnished"))
            cap = get_budget_cap(bedrooms, is_furn)
            self.assertLessEqual(item["weekly_rent"], cap)
            self.assertTrue(item.get("is_lease_transfer"))
            # Must use direct individual /marketplace/item/<id>/ URLs rather than a common search page
            self.assertIn("https://www.facebook.com/marketplace/item/", item["url"])
            self.assertNotIn("/marketplace/melbourne/search", item["url"])

    def test_primary_search_url_in_quick_links(self):
        portal_links = build_portal_quick_links()
        self.assertGreater(len(portal_links), 0)
        # The primary FB Marketplace URL must be present in portal quick links
        fb_links = [l for l in portal_links if "facebook.com" in l["url"]]
        self.assertGreater(len(fb_links), 0)
        self.assertEqual(fb_links[0]["url"], FB_MARKETPLACE_PRIMARY_URL)
        self.assertIn("lease%20transfer%202%20bedroom", fb_links[0]["url"])


class TestAIEvaluatorAgent(unittest.TestCase):
    """Test AI Evaluator Agent assessments for solo renter lifestyle, WFH, noise, and amenities."""

    def setUp(self):
        self.agent = RentalAIEvaluatorAgent()
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db = PropertyDatabase(Path(self.temp_dir.name) / "test_ai.sqlite")

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_high_match_wfh_lifestyle_evaluation(self):
        p = Property(
            property_id="ai_p1",
            source="jelliscraig",
            source_listing_id="jc1",
            source_url="https://jelliscraig.com.au/rent/jc1",
            title="Sunny 2 Bedroom Unit with Study Potential",
            address="14 Victoria Rd, Camberwell",
            suburb="Camberwell",
            bedrooms=2,
            bathrooms=1,
            parking=1,
            weekly_rent=500.0,
            commute_mins=4,
            commute_mode="Train",
            has_direct_hawthorn_transit=True,
            description="Tucked away in a quiet street, this sun-drenched rear of block apartment offers split-system heating and cooling, dishwasher, internal laundry, balcony, and a generous second bedroom ideal for a work-from-home study.",
        )
        eval_res = self.agent.evaluate(p)
        self.assertEqual(eval_res["verdict"], "HIGH_MATCH")
        self.assertGreaterEqual(eval_res["match_score"], 82)
        self.assertIn("Top AI Match", eval_res["badge_label"])
        self.assertTrue(any("study" in s.lower() or "work-from-home" in s.lower() or "work and rest" in s.lower() for s in eval_res["strengths"]))
        self.assertTrue(any("split-system" in s.lower() for s in eval_res["strengths"]))

    def test_noisy_corridor_and_communal_laundry_cautions(self):
        p = Property(
            property_id="ai_p2",
            source="barryplant",
            source_listing_id="bp2",
            source_url="https://barryplant.com.au/rent/bp2",
            title="2 Bedroom Flat on Burwood Road",
            address="520 Burwood Rd, Hawthorn",
            suburb="Hawthorn",
            bedrooms=2,
            weekly_rent=540.0,
            commute_mins=2,
            commute_mode="Train",
            has_direct_hawthorn_transit=True,
            description="Standard 2BR apartment. Electric wall panel heaters. Shared communal laundry facilities in the building. Close to shops and transport.",
        )
        eval_res = self.agent.evaluate(p)
        self.assertIn(eval_res["verdict"], ("CONSIDER_WITH_CAUTION", "NOT_RECOMMENDED"))
        self.assertLess(eval_res["match_score"], 70)
        self.assertTrue(any("major road" in c.lower() or "burwood" in c.lower() for c in eval_res["cautions"]))
        self.assertTrue(any("communal" in c.lower() or "laundry" in c.lower() for c in eval_res["cautions"]))

    def test_sqlite_persistence_and_roundtrip(self):
        p = Property(
            property_id="ai_p3_db",
            source="raywhite",
            source_listing_id="rw3",
            source_url="https://raywhite.com/rent/rw3",
            title="Modern 2BR in Hawthorn East",
            address="20 Auburn Rd, Hawthorn East",
            suburb="Hawthorn East",
            bedrooms=2,
            weekly_rent=520.0,
            commute_mins=4,
            has_direct_hawthorn_transit=True,
            description="Lovely 2-bedroom home with split-system cooling and dishwasher.",
        )
        eval_res = self.agent.evaluate(p)
        p.ai_evaluation = eval_res

        # Upsert into database
        self.db.upsert_property(p)

        # Retrieve from database and verify ai_evaluation preserved
        retrieved = self.db.get_property("ai_p3_db")
        self.assertIsNotNone(retrieved)
        self.assertIsNotNone(retrieved.ai_evaluation)
        self.assertEqual(retrieved.ai_evaluation["verdict"], eval_res["verdict"])
        self.assertEqual(retrieved.ai_evaluation["match_score"], eval_res["match_score"])

        # Verify export_to_listings_json includes ai_evaluation
        out_file = Path(self.temp_dir.name) / "test_export.json"
        payload = self.db.export_to_listings_json(out_file)
        self.assertEqual(len(payload["listings"]), 1)
        self.assertIn("ai_evaluation", payload["listings"][0])
        self.assertEqual(payload["listings"][0]["ai_evaluation"]["verdict"], eval_res["verdict"])


if __name__ == "__main__":
    unittest.main()

