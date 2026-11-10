"""
Persistent Property Database Architecture for Melbourne Rental Finder V2.

Features:
- Relational SQLite database with full schema:
    * properties
    * listing_sources (multi-source deduplication tracking)
    * listing_snapshots (price & availability history)
    * property_scores (explainable score history)
    * user_interactions (shortlist, skip, inspect, notes)
    * scraper_executions (telemetry & scraper health)
- Automatic snapshotting on price or status changes
- Optional Supabase PostgreSQL adapter interface using environment variables (SUPABASE_URL, SUPABASE_KEY)
- Automated export to docs/data/listings.json for static site deployment
"""

from __future__ import annotations

import json
import os
import sqlite3
import urllib.request
import urllib.error
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple

from .models import Property, ListingSource, ListingSnapshot, PropertyScore, ScraperExecutionLog
from .freshness import parse_iso_datetime
from .config import HAWTHORN_DIRECT_SUBURBS


DEFAULT_DB_PATH = Path(__file__).resolve().parent.parent / "docs" / "data" / "database.sqlite"


class PropertyDatabase:
    """Manages SQLite storage, history tracking, and optional Supabase synchronization."""

    def __init__(self, db_path: Optional[Path | str] = None):
        self.db_path = Path(db_path or DEFAULT_DB_PATH)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._supabase_url = os.getenv("SUPABASE_URL", "").rstrip("/")
        self._supabase_key = os.getenv("SUPABASE_KEY", "")
        self.init_db()

    def get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON;")
        return conn

    def init_db(self) -> None:
        """Create tables and indexes if they do not exist."""
        with self.get_connection() as conn:
            conn.executescript("""
            CREATE TABLE IF NOT EXISTS properties (
                property_id TEXT PRIMARY KEY,
                source TEXT NOT NULL,
                source_listing_id TEXT,
                source_url TEXT NOT NULL,
                title TEXT,
                address TEXT,
                suburb TEXT,
                postcode TEXT,
                state TEXT DEFAULT 'VIC',
                property_type TEXT DEFAULT 'apartment',
                bedrooms INTEGER DEFAULT 1,
                bathrooms INTEGER DEFAULT 1,
                parking INTEGER DEFAULT 0,
                weekly_rent REAL,
                furnished INTEGER,
                property_entire INTEGER DEFAULT 1,
                lease_transfer INTEGER DEFAULT 0,
                available_date TEXT,
                lease_duration TEXT,
                description TEXT,
                photo TEXT,
                first_seen TEXT NOT NULL,
                last_seen TEXT NOT NULL,
                last_verified TEXT,
                listing_status TEXT DEFAULT 'active',
                verification_status TEXT DEFAULT 'unverified',
                match_score REAL,
                score_version TEXT DEFAULT '2.0',
                score_confidence TEXT DEFAULT 'medium',
                score_breakdown_json TEXT,
                positive_factors_json TEXT,
                potential_concerns_json TEXT,
                commute_mode TEXT,
                commute_line TEXT,
                commute_mins INTEGER,
                commute_tier INTEGER,
                has_direct_hawthorn_transit INTEGER DEFAULT 0,
                station_name TEXT,
                station_distance_m INTEGER,
                station_walking_mins INTEGER,
                station_distance_display TEXT,
                station_is_explicit INTEGER,
                availability_display TEXT,
                availability_fit TEXT,
                is_student_only INTEGER DEFAULT 0,
                is_sharehouse INTEGER DEFAULT 0,
                is_new INTEGER DEFAULT 0,
                pass_strict_filter INTEGER DEFAULT 1,
                rejection_reason TEXT,
                raw_metadata_json TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS listing_sources (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                property_id TEXT NOT NULL,
                source_name TEXT NOT NULL,
                source_listing_id TEXT,
                source_url TEXT NOT NULL,
                raw_title TEXT,
                raw_price_text TEXT,
                raw_description TEXT,
                first_seen TEXT NOT NULL,
                last_seen TEXT NOT NULL,
                is_active INTEGER DEFAULT 1,
                FOREIGN KEY (property_id) REFERENCES properties(property_id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS listing_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                property_id TEXT NOT NULL,
                weekly_rent REAL,
                available_date TEXT,
                listing_status TEXT NOT NULL,
                snapshot_timestamp TEXT NOT NULL,
                FOREIGN KEY (property_id) REFERENCES properties(property_id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS property_scores (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                property_id TEXT NOT NULL,
                score_version TEXT NOT NULL,
                total_score REAL NOT NULL,
                confidence TEXT NOT NULL,
                breakdown_json TEXT,
                positive_factors_json TEXT,
                potential_concerns_json TEXT,
                scored_at TEXT NOT NULL,
                FOREIGN KEY (property_id) REFERENCES properties(property_id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS user_interactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                property_id TEXT NOT NULL,
                action_type TEXT NOT NULL,
                payload_json TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY (property_id) REFERENCES properties(property_id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS scraper_executions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_timestamp TEXT NOT NULL,
                source TEXT NOT NULL,
                listings_scanned INTEGER DEFAULT 0,
                listings_new INTEGER DEFAULT 0,
                listings_updated INTEGER DEFAULT 0,
                errors_logged INTEGER DEFAULT 0,
                duration_seconds REAL DEFAULT 0.0,
                status TEXT DEFAULT 'success',
                error_message TEXT
            );

            CREATE INDEX IF NOT EXISTS idx_properties_suburb ON properties(suburb);
            CREATE INDEX IF NOT EXISTS idx_properties_rent ON properties(weekly_rent);
            CREATE INDEX IF NOT EXISTS idx_properties_status ON properties(listing_status);
            CREATE INDEX IF NOT EXISTS idx_snapshots_prop_id ON listing_snapshots(property_id);
            CREATE INDEX IF NOT EXISTS idx_sources_prop_id ON listing_sources(property_id);
            """)

            # Schema migration: ensure photo and transit columns exist in older database files
            try:
                conn.execute("ALTER TABLE properties ADD COLUMN photo TEXT;")
            except Exception:
                pass
            try:
                conn.execute("ALTER TABLE properties ADD COLUMN has_direct_hawthorn_transit INTEGER DEFAULT 0;")
            except Exception:
                pass

    def upsert_property(self, prop: Property) -> bool:
        """
        Insert or update a property record.
        Automatically tracks price and status changes in listing_snapshots.
        Returns True if newly inserted, False if updated.
        """
        now_iso = datetime.now(timezone.utc).isoformat()
        is_new = False

        with self.get_connection() as conn:
            # Check existing record
            cur = conn.cursor()
            cur.execute(
                "SELECT weekly_rent, available_date, listing_status FROM properties WHERE property_id = ?",
                (prop.property_id,)
            )
            existing = cur.fetchone()

            should_record_snapshot = False
            if existing is None:
                is_new = True
                should_record_snapshot = True
            else:
                old_rent = existing["weekly_rent"]
                old_avail = existing["available_date"]
                old_status = existing["listing_status"]
                if (old_rent != prop.weekly_rent) or (old_avail != prop.available_date) or (old_status != prop.listing_status):
                    should_record_snapshot = True

            # Upsert into properties
            conn.execute(
                """
                INSERT INTO properties (
                    property_id, source, source_listing_id, source_url, title, address, suburb, postcode, state,
                    property_type, bedrooms, bathrooms, parking, weekly_rent, furnished, property_entire,
                    lease_transfer, available_date, lease_duration, description, photo, first_seen, last_seen, last_verified,
                    listing_status, verification_status, match_score, score_version, score_confidence,
                    score_breakdown_json, positive_factors_json, potential_concerns_json,
                    commute_mode, commute_line, commute_mins, commute_tier, has_direct_hawthorn_transit,
                    station_name, station_distance_m, station_walking_mins, station_distance_display, station_is_explicit,
                    availability_display, availability_fit, is_student_only, is_sharehouse, is_new,
                    pass_strict_filter, rejection_reason, raw_metadata_json, created_at, updated_at
                ) VALUES (
                    ?, ?, ?, ?, ?, ?, ?, ?, ?,
                    ?, ?, ?, ?, ?, ?, ?,
                    ?, ?, ?, ?, ?, ?, ?, ?,
                    ?, ?, ?, ?, ?,
                    ?, ?, ?,
                    ?, ?, ?, ?, ?,
                    ?, ?, ?, ?, ?,
                    ?, ?, ?, ?, ?,
                    ?, ?, ?, ?, ?
                )
                ON CONFLICT(property_id) DO UPDATE SET
                    source = excluded.source,
                    source_url = excluded.source_url,
                    title = excluded.title,
                    address = coalesce(excluded.address, properties.address),
                    suburb = excluded.suburb,
                    postcode = excluded.postcode,
                    weekly_rent = excluded.weekly_rent,
                    furnished = excluded.furnished,
                    property_entire = excluded.property_entire,
                    lease_transfer = excluded.lease_transfer,
                    available_date = coalesce(excluded.available_date, properties.available_date),
                    description = excluded.description,
                    photo = coalesce(excluded.photo, properties.photo),
                    last_seen = excluded.last_seen,
                    last_verified = coalesce(excluded.last_verified, properties.last_verified),
                    listing_status = excluded.listing_status,
                    verification_status = excluded.verification_status,
                    match_score = excluded.match_score,
                    score_version = excluded.score_version,
                    score_confidence = excluded.score_confidence,
                    score_breakdown_json = excluded.score_breakdown_json,
                    positive_factors_json = excluded.positive_factors_json,
                    potential_concerns_json = excluded.potential_concerns_json,
                    has_direct_hawthorn_transit = excluded.has_direct_hawthorn_transit,
                    station_distance_m = excluded.station_distance_m,
                    station_distance_display = excluded.station_distance_display,
                    station_is_explicit = excluded.station_is_explicit,
                    availability_display = excluded.availability_display,
                    availability_fit = excluded.availability_fit,
                    pass_strict_filter = excluded.pass_strict_filter,
                    rejection_reason = excluded.rejection_reason,
                    updated_at = excluded.updated_at
                """,
                (
                    prop.property_id, prop.source, prop.source_listing_id, prop.source_url, prop.title, prop.address,
                    prop.suburb, prop.postcode, prop.state, prop.property_type, prop.bedrooms, prop.bathrooms, prop.parking,
                    prop.weekly_rent, 1 if prop.furnished else (0 if prop.furnished is not None else None),
                    1 if prop.property_entire else 0, 1 if prop.lease_transfer else 0,
                    prop.available_date, prop.lease_duration, prop.description, prop.photo, prop.first_seen, prop.last_seen,
                    prop.last_verified, prop.listing_status, prop.verification_status, prop.match_score,
                    prop.score_version, prop.score_confidence, json.dumps(prop.score_breakdown),
                    json.dumps(prop.positive_factors), json.dumps(prop.potential_concerns),
                    prop.commute_mode, prop.commute_line, prop.commute_mins, prop.commute_tier,
                    1 if prop.has_direct_hawthorn_transit else 0,
                    prop.station_name, prop.station_distance_m, prop.station_walking_mins, prop.station_distance_display,
                    1 if prop.station_is_explicit else 0, prop.availability_display, prop.availability_fit,
                    1 if prop.is_student_only else 0, 1 if prop.is_sharehouse else 0, 1 if prop.is_new else 0,
                    1 if prop.pass_strict_filter else 0, prop.rejection_reason, json.dumps(prop.raw_metadata),
                    prop.first_seen, now_iso
                )
            )

            # Record snapshot of price/availability change
            if should_record_snapshot:
                conn.execute(
                    """
                    INSERT INTO listing_snapshots (property_id, weekly_rent, available_date, listing_status, snapshot_timestamp)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (prop.property_id, prop.weekly_rent, prop.available_date, prop.listing_status, now_iso)
                )

            # Sync multi-sources
            if prop.sources:
                for s in prop.sources:
                    s_url = s.get("source_url") or s.get("url")
                    if not s_url:
                        continue
                    cur.execute(
                        "SELECT id FROM listing_sources WHERE property_id = ? AND source_url = ?",
                        (prop.property_id, s_url)
                    )
                    if not cur.fetchone():
                        conn.execute(
                            """
                            INSERT INTO listing_sources (
                                property_id, source_name, source_listing_id, source_url,
                                raw_title, raw_price_text, raw_description, first_seen, last_seen, is_active
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """,
                            (
                                prop.property_id,
                                s.get("source_name") or s.get("source") or prop.source,
                                str(s.get("source_listing_id") or s.get("id") or ""),
                                s_url,
                                s.get("raw_title") or prop.title,
                                s.get("raw_price_text") or "",
                                s.get("raw_description") or "",
                                s.get("first_seen") or now_iso,
                                s.get("last_seen") or now_iso,
                                1 if s.get("is_active", True) else 0,
                            )
                        )

            # Record score history if score present
            if prop.match_score is not None:
                conn.execute(
                    """
                    INSERT INTO property_scores (
                        property_id, score_version, total_score, confidence,
                        breakdown_json, positive_factors_json, potential_concerns_json, scored_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        prop.property_id,
                        prop.score_version or "2.0",
                        prop.match_score,
                        prop.score_confidence or "medium",
                        json.dumps(prop.score_breakdown),
                        json.dumps(prop.positive_factors),
                        json.dumps(prop.potential_concerns),
                        now_iso,
                    )
                )

        # Optional Supabase synchronization
        self._sync_to_supabase(prop)
        return is_new

    def get_property(self, property_id: str) -> Optional[Property]:
        """Fetch a single property with attached sources."""
        with self.get_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM properties WHERE property_id = ?", (property_id,))
            row = cur.fetchone()
            if not row:
                return None
            return self._row_to_property(row, conn)

    def list_properties(self, status: Optional[str] = "active", limit: int = 500) -> List[Property]:
        """List properties from the database."""
        with self.get_connection() as conn:
            cur = conn.cursor()
            if status:
                cur.execute(
                    "SELECT * FROM properties WHERE listing_status = ? ORDER BY match_score DESC, weekly_rent ASC LIMIT ?",
                    (status, limit)
                )
            else:
                cur.execute("SELECT * FROM properties ORDER BY match_score DESC, weekly_rent ASC LIMIT ?", (limit,))
            rows = cur.fetchall()
            return [self._row_to_property(r, conn) for r in rows]

    def record_user_interaction(self, property_id: str, action_type: str, payload: Optional[Dict[str, Any]] = None) -> None:
        """Record user actions (shortlist, skip, inspect, notes)."""
        now_iso = datetime.now(timezone.utc).isoformat()
        with self.get_connection() as conn:
            conn.execute(
                "INSERT INTO user_interactions (property_id, action_type, payload_json, created_at) VALUES (?, ?, ?, ?)",
                (property_id, action_type, json.dumps(payload or {}), now_iso)
            )

    def log_execution(self, log: ScraperExecutionLog) -> None:
        """Record scraper execution metrics."""
        with self.get_connection() as conn:
            conn.execute(
                """
                INSERT INTO scraper_executions (
                    run_timestamp, source, listings_scanned, listings_new, listings_updated,
                    errors_logged, duration_seconds, status, error_message
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    log.run_timestamp, log.source, log.listings_scanned, log.listings_new, log.listings_updated,
                    log.errors_logged, log.duration_seconds, log.status, log.error_message
                )
            )

    def get_price_history(self, property_id: str) -> List[Dict[str, Any]]:
        """Retrieve price and availability snapshots for a property."""
        with self.get_connection() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT weekly_rent, available_date, listing_status, snapshot_timestamp FROM listing_snapshots WHERE property_id = ? ORDER BY snapshot_timestamp ASC",
                (property_id,)
            )
            return [dict(r) for r in cur.fetchall()]

    def export_to_listings_json(
        self,
        output_file: Optional[Path | str] = None,
        criteria: Optional[Dict[str, Any]] = None,
        portal_links: Optional[List[Dict[str, str]]] = None,
    ) -> Dict[str, Any]:
        """Export active database records to docs/data/listings.json for static site deployment."""
        target_path = Path(output_file or self.db_path.parent / "listings.json")
        target_path.parent.mkdir(parents=True, exist_ok=True)

        props = self.list_properties(status="active", limit=1000)
        legacy_list = [p.to_legacy_dict() for p in props]

        now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        strict_matches = [x for x in legacy_list if x.get("pass_strict_filter")]

        payload = {
            "last_updated": now_iso,
            "version": "2.0",
            "criteria": criteria or {},
            "stats": {
                "total_scanned": len(legacy_list),
                "strict_matches": len(strict_matches),
                "normal_under_600": sum(1 for x in legacy_list if x.get("is_normal_listing") and x.get("is_under_600")),
                "total_under_600": sum(1 for x in legacy_list if x.get("is_under_600")),
                "lease_transfers": sum(1 for x in legacy_list if x.get("is_lease_transfer")),
                "two_bhk_matches": sum(1 for x in legacy_list if x.get("bedrooms") == 2 and x.get("is_under_600")),
                "new_today": sum(1 for x in legacy_list if x.get("is_new")),
            },
            "portal_quick_links": portal_links or [],
            "listings": legacy_list,
        }

        target_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return payload

    def _row_to_property(self, row: sqlite3.Row, conn: sqlite3.Connection) -> Property:
        """Map a SQLite row to a Property instance."""
        prop_id = row["property_id"]
        cur = conn.cursor()
        cur.execute("SELECT * FROM listing_sources WHERE property_id = ?", (prop_id,))
        sources = [dict(s) for s in cur.fetchall()]

        score_breakdown = {}
        if row["score_breakdown_json"]:
            try:
                score_breakdown = json.loads(row["score_breakdown_json"])
            except Exception:
                pass

        pos_factors = []
        if row["positive_factors_json"]:
            try:
                pos_factors = json.loads(row["positive_factors_json"])
            except Exception:
                pass

        concerns = []
        if row["potential_concerns_json"]:
            try:
                concerns = json.loads(row["potential_concerns_json"])
            except Exception:
                pass

        raw_meta = {}
        if row["raw_metadata_json"]:
            try:
                raw_meta = json.loads(row["raw_metadata_json"])
            except Exception:
                pass

        return Property(
            property_id=prop_id,
            source=row["source"],
            source_listing_id=row["source_listing_id"] or "",
            source_url=row["source_url"],
            title=row["title"] or "",
            address=row["address"],
            suburb=row["suburb"] or "",
            postcode=row["postcode"] or "",
            state=row["state"] or "VIC",
            property_type=row["property_type"] or "apartment",
            bedrooms=int(row["bedrooms"] or 1),
            bathrooms=int(row["bathrooms"] or 1),
            parking=int(row["parking"] or 0),
            weekly_rent=float(row["weekly_rent"]) if row["weekly_rent"] is not None else None,
            furnished=bool(row["furnished"]) if row["furnished"] is not None else None,
            property_entire=bool(row["property_entire"]),
            lease_transfer=bool(row["lease_transfer"]),
            available_date=row["available_date"],
            lease_duration=row["lease_duration"],
            description=row["description"] or "",
            photo=row["photo"] if ("photo" in row.keys() and row["photo"]) else "",
            first_seen=row["first_seen"],
            last_seen=row["last_seen"],
            last_verified=row["last_verified"],
            listing_status=row["listing_status"] or "active",
            verification_status=row["verification_status"] or "unverified",
            match_score=float(row["match_score"]) if row["match_score"] is not None else None,
            score_version=row["score_version"] or "2.0",
            score_confidence=row["score_confidence"] or "medium",
            sources=sources,
            score_breakdown=score_breakdown,
            positive_factors=pos_factors,
            potential_concerns=concerns,
            commute_mode=row["commute_mode"] or "Train",
            commute_line=row["commute_line"] or "Belgrave/Lilydale Line",
            commute_mins=int(row["commute_mins"] or 15),
            commute_tier=int(row["commute_tier"] or 2),
            has_direct_hawthorn_transit=bool(row["has_direct_hawthorn_transit"]) if ("has_direct_hawthorn_transit" in row.keys() and row["has_direct_hawthorn_transit"] is not None) else ((row["suburb"] or "").lower().strip() in HAWTHORN_DIRECT_SUBURBS),
            station_name=row["station_name"] or "",
            station_distance_m=int(row["station_distance_m"] or 500),
            station_walking_mins=int(row["station_walking_mins"] or 6),
            station_distance_display=row["station_distance_display"] or "",
            station_is_explicit=bool(row["station_is_explicit"]),
            availability_display=row["availability_display"] or "",
            availability_fit=row["availability_fit"] or "ideal",
            is_student_only=bool(row["is_student_only"]),
            is_sharehouse=bool(row["is_sharehouse"]),
            is_new=bool(row["is_new"]),
            pass_strict_filter=bool(row["pass_strict_filter"]),
            rejection_reason=row["rejection_reason"],
            raw_metadata=raw_meta,
        )

    def _sync_to_supabase(self, prop: Property) -> None:
        """
        Optional adapter to sync property to Supabase PostgreSQL table 'properties'
        if SUPABASE_URL and SUPABASE_KEY environment variables are configured.
        Silently returns if not configured.
        """
        if not self._supabase_url or not self._supabase_key:
            return

        endpoint = f"{self._supabase_url}/rest/v1/properties"
        payload = json.dumps(prop.to_dict()).encode("utf-8")
        headers = {
            "apikey": self._supabase_key,
            "Authorization": f"Bearer {self._supabase_key}",
            "Content-Type": "application/json",
            "Prefer": "resolution=merge-duplicates",
        }

        try:
            req = urllib.request.Request(endpoint, data=payload, headers=headers, method="POST")
            with urllib.request.urlopen(req, timeout=4.0):
                pass
        except Exception:
            # Gracefully ignore network or sync errors; local SQLite is authoritative
            pass
