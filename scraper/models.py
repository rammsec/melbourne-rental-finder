"""
Unified Property Data Model & Normalized Schema for Melbourne Rental Finder V2.

Provides standard structures regardless of whether listings originate from:
- Gumtree (lease transfers & rentals)
- Flatmates (whole properties)
- Reddit (lease transfers)
- Domain / RealEstate (normal listings)
- Manual user submissions

Maintains 100% backward compatibility with legacy listing dictionaries.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional


def generate_property_id(source: str, source_listing_id: str, address: str = "", suburb: str = "") -> str:
    """Generate a consistent unique identifier for a property."""
    if source_listing_id:
        clean_id = re.sub(r"[^a-zA-Z0-9_-]", "", str(source_listing_id))
        if clean_id.startswith("prop_"):
            return clean_id
        clean_src = re.sub(r"[^a-zA-Z0-9_-]", "", source.lower()) if source else ""
        if clean_src and clean_id.lower().startswith(f"{clean_src}_"):
            return f"prop_{clean_id}"
        if clean_src:
            return f"prop_{clean_src}_{clean_id}"
        return f"prop_{clean_id}"
    
    # Hash address + suburb if listing ID missing
    seed = f"{suburb.lower()}|{address.lower()}"
    h = hashlib.sha256(seed.encode("utf-8")).hexdigest()[:12]
    return f"prop_gen_{h}"


@dataclass
class ListingSource:
    """Represents an individual source listing for a property (supports multi-source deduplication)."""
    source_name: str
    source_listing_id: str
    source_url: str
    raw_title: str = ""
    raw_price_text: str = ""
    raw_description: str = ""
    first_seen: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    last_seen: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    is_active: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> ListingSource:
        return cls(
            source_name=data.get("source_name") or data.get("source") or "unknown",
            source_listing_id=str(data.get("source_listing_id") or data.get("id") or ""),
            source_url=data.get("source_url") or data.get("url") or "",
            raw_title=data.get("raw_title") or data.get("title") or "",
            raw_price_text=data.get("raw_price_text") or data.get("price_text") or "",
            raw_description=data.get("raw_description") or data.get("description") or "",
            first_seen=data.get("first_seen") or datetime.now(timezone.utc).isoformat(),
            last_seen=data.get("last_seen") or datetime.now(timezone.utc).isoformat(),
            is_active=bool(data.get("is_active", True)),
        )


@dataclass
class ListingSnapshot:
    """Historical snapshot tracking price and availability changes over time."""
    property_id: str
    weekly_rent: Optional[float]
    available_date: Optional[str]
    listing_status: str
    snapshot_timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class PropertyScore:
    """Explainable 100-point compatibility score."""
    total_score: float = 0.0
    confidence: str = "medium"  # "high", "medium", "low"
    score_version: str = "2.0"
    breakdown: Dict[str, Any] = field(default_factory=dict)
    positive_factors: List[str] = field(default_factory=list)
    potential_concerns: List[str] = field(default_factory=list)
    is_eligible: bool = True
    ineligibility_reasons: List[str] = field(default_factory=list)
    scored_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ScraperExecutionLog:
    """Execution telemetry and reliability metrics for scraper runs."""
    run_timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    source: str = "all"
    listings_scanned: int = 0
    listings_new: int = 0
    listings_updated: int = 0
    errors_logged: int = 0
    duration_seconds: float = 0.0
    status: str = "success"  # "success", "partial", "failed"
    error_message: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class Property:
    """
    Unified Property Model.
    Standardized schema preserving original source information, extracted attributes,
    and transit intelligence.
    """
    property_id: str
    source: str
    source_listing_id: str
    source_url: str

    title: str = ""
    address: Optional[str] = None
    suburb: str = ""
    postcode: str = ""
    state: str = "VIC"

    property_type: str = "apartment"  # "apartment", "unit", "townhouse", "house", "studio"
    bedrooms: int = 1
    bathrooms: int = 1
    parking: int = 0

    weekly_rent: Optional[float] = None
    furnished: Optional[bool] = None
    property_entire: bool = True
    lease_transfer: bool = False

    available_date: Optional[str] = None
    lease_duration: Optional[str] = None
    description: str = ""
    photo: str = ""

    first_seen: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    last_seen: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    last_verified: Optional[str] = None

    listing_status: str = "active"  # "active", "potentially_unavailable", "removed", "expired"
    verification_status: str = "unverified"  # "verified", "unverified"

    match_score: Optional[float] = None
    score_version: Optional[str] = "2.0"
    score_confidence: str = "medium"

    # Multi-source and breakdown relationships
    sources: List[Dict[str, Any]] = field(default_factory=list)
    score_breakdown: Dict[str, Any] = field(default_factory=dict)
    positive_factors: List[str] = field(default_factory=list)
    potential_concerns: List[str] = field(default_factory=list)

    # Hawthorn Transit & Commute Intelligence
    commute_mode: str = "Train"
    commute_line: str = "Belgrave/Lilydale Line"
    commute_mins: int = 15
    commute_tier: int = 2
    has_direct_hawthorn_transit: bool = True
    station_name: str = ""
    station_distance_m: int = 500
    station_walking_mins: int = 6
    station_distance_display: str = ""
    station_is_explicit: bool = False
    availability_display: str = ""
    availability_fit: str = "ideal"

    # Strict Criteria Flags
    is_student_only: bool = False
    is_sharehouse: bool = False
    is_new: bool = False
    pass_strict_filter: bool = True
    rejection_reason: Optional[str] = None

    # Raw metadata preserved for rollback/extension
    raw_metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to fully normalized V2 dictionary."""
        d = asdict(self)
        # Ensure id alias is present for frontend compatibility
        d["id"] = self.property_id
        d["url"] = self.source_url
        d["photo"] = self.photo
        d["is_furnished"] = self.furnished
        d["is_lease_transfer"] = self.lease_transfer
        d["is_normal_listing"] = (not self.lease_transfer) and self.property_entire and (not self.is_student_only)
        d["is_under_600"] = self.weekly_rent is not None and 200 <= self.weekly_rent <= 600
        return d

    def to_legacy_dict(self) -> Dict[str, Any]:
        """
        Export dictionary compatible with both V1 and V2 frontends and scrapers.
        Guarantees all legacy keys exist.
        """
        d = self.to_dict()
        # Aliases for legacy V1 consumer compatibility
        d.update({
            "id": self.property_id,
            "url": self.source_url,
            "photo": self.photo,
            "title": self.title,
            "address": self.address or f"{self.suburb}, VIC {self.postcode}".strip(),
            "suburb": self.suburb,
            "postcode": self.postcode,
            "weekly_rent": self.weekly_rent,
            "is_furnished": bool(self.furnished),
            "bedrooms": self.bedrooms,
            "bathrooms": self.bathrooms,
            "parking": self.parking,
            "is_lease_transfer": self.lease_transfer,
            "is_entire_property": self.property_entire,
            "is_sharehouse": self.is_sharehouse,
            "is_student_only": self.is_student_only,
            "is_normal_listing": (not self.lease_transfer) and self.property_entire and (not self.is_student_only),
            "is_under_600": self.weekly_rent is not None and 200 <= self.weekly_rent <= 600,
            "is_new": self.is_new,
            "listed_at": self.first_seen,
            "first_seen": self.first_seen,
            "last_seen": self.last_seen,
            "last_verified": self.last_verified,
            "listing_status": self.listing_status,
            "verification_status": self.verification_status,
            "match_score": self.match_score,
            "score_version": self.score_version,
            "score_confidence": self.score_confidence,
            "score_breakdown": self.score_breakdown,
            "positive_factors": self.positive_factors,
            "potential_concerns": self.potential_concerns,
            "commute_mode": self.commute_mode,
            "commute_line": self.commute_line,
            "commute_mins": self.commute_mins,
            "commute_tier": self.commute_tier,
            "has_direct_hawthorn_transit": self.has_direct_hawthorn_transit,
            "station_name": self.station_name,
            "station_distance_m": self.station_distance_m,
            "station_walking_mins": self.station_walking_mins,
            "station_distance_display": self.station_distance_display,
            "station_is_explicit": self.station_is_explicit,
            "availability_display": self.availability_display,
            "availability_fit": self.availability_fit,
            "pass_strict_filter": self.pass_strict_filter,
            "rejection_reason": self.rejection_reason,
            "sources": self.sources if self.sources else [{
                "source": self.source,
                "url": self.source_url,
                "first_seen": self.first_seen,
            }],
        })
        return d

    @classmethod
    def from_legacy(cls, d: Dict[str, Any]) -> Property:
        """Convert a legacy V1 listing dictionary into a normalized Property object."""
        source = d.get("source") or "unknown"
        source_id = str(d.get("id") or d.get("source_id") or "")
        prop_id = generate_property_id(source, source_id, d.get("address", ""), d.get("suburb", ""))

        # Property type inference
        prop_type = "apartment"
        title_desc = f"{d.get('title', '')} {d.get('description', '')}".lower()
        if "townhouse" in title_desc:
            prop_type = "townhouse"
        elif "unit" in title_desc:
            prop_type = "unit"
        elif "house" in title_desc:
            prop_type = "house"
        elif "studio" in title_desc:
            prop_type = "studio"

        # Safe parsing of numeric values
        bedrooms = d.get("bedrooms")
        if bedrooms is None:
            bedrooms = 1
        try:
            bedrooms = int(bedrooms)
        except (ValueError, TypeError):
            bedrooms = 1

        bathrooms = d.get("bathrooms", 1)
        try:
            bathrooms = int(bathrooms)
        except (ValueError, TypeError):
            bathrooms = 1

        parking = d.get("parking", 0)
        try:
            parking = int(parking)
        except (ValueError, TypeError):
            parking = 0

        weekly_rent = d.get("weekly_rent")
        if weekly_rent is not None:
            try:
                weekly_rent = float(weekly_rent)
            except (ValueError, TypeError):
                weekly_rent = None

        first_seen = d.get("first_seen") or d.get("listed_at") or datetime.now(timezone.utc).isoformat()
        last_seen = d.get("last_seen") or datetime.now(timezone.utc).isoformat()

        sources = d.get("sources") or []
        if not sources and d.get("url"):
            sources = [{
                "source_name": source,
                "source_listing_id": source_id,
                "source_url": d.get("url", ""),
                "first_seen": first_seen,
                "last_seen": last_seen,
                "is_active": True,
            }]

        return cls(
            property_id=prop_id,
            source=source,
            source_listing_id=source_id,
            source_url=d.get("url") or d.get("source_url") or "",
            title=d.get("title") or "",
            address=d.get("address"),
            suburb=d.get("suburb") or "",
            postcode=str(d.get("postcode") or ""),
            state=d.get("state") or "VIC",
            property_type=d.get("property_type") or prop_type,
            bedrooms=bedrooms,
            bathrooms=bathrooms,
            parking=parking,
            weekly_rent=weekly_rent,
            furnished=d.get("furnished") if "furnished" in d else d.get("is_furnished"),
            property_entire=not bool(d.get("is_sharehouse")),
            lease_transfer=bool(d.get("is_lease_transfer")),
            available_date=d.get("available_date") or d.get("date_available"),
            lease_duration=d.get("lease_duration"),
            description=d.get("description") or d.get("subhead") or "",
            photo=d.get("photo") or "",
            first_seen=first_seen,
            last_seen=last_seen,
            last_verified=d.get("last_verified"),
            listing_status=d.get("listing_status") or "active",
            verification_status=d.get("verification_status") or "unverified",
            match_score=float(d["match_score"]) if d.get("match_score") is not None else None,
            score_version=d.get("score_version") or "2.0",
            score_confidence=d.get("score_confidence") or "medium",
            sources=sources,
            score_breakdown=d.get("score_breakdown") or {},
            positive_factors=d.get("positive_factors") or d.get("match_badges") or [],
            potential_concerns=d.get("potential_concerns") or [],
            commute_mode=d.get("commute_mode") or "Train",
            commute_line=d.get("commute_line") or "Belgrave/Lilydale Line",
            commute_mins=int(d.get("commute_mins", 15)),
            commute_tier=int(d.get("commute_tier", 2)),
            has_direct_hawthorn_transit=bool(d.get("has_direct_hawthorn_transit", True)),
            station_name=d.get("station_name") or "",
            station_distance_m=int(d.get("station_distance_m", 500)),
            station_walking_mins=int(d.get("station_walking_mins", 6)),
            station_distance_display=d.get("station_distance_display") or "",
            station_is_explicit=bool(d.get("station_is_explicit", False)),
            availability_display=d.get("availability_display") or "",
            availability_fit=d.get("availability_fit") or "ideal",
            is_student_only=bool(d.get("is_student_only", False)),
            is_sharehouse=bool(d.get("is_sharehouse", False)),
            is_new=bool(d.get("is_new", False)),
            pass_strict_filter=bool(d.get("pass_strict_filter", True)),
            rejection_reason=d.get("rejection_reason"),
            raw_metadata=d.get("raw_metadata") or {},
        )

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> Property:
        """Parse from dictionary with fallback to from_legacy for robust deserialization."""
        if "property_id" in d and "source" in d:
            # Direct V2 structure
            return cls(
                property_id=d["property_id"],
                source=d.get("source", "unknown"),
                source_listing_id=str(d.get("source_listing_id", "")),
                source_url=d.get("source_url") or d.get("url", ""),
                title=d.get("title", ""),
                address=d.get("address"),
                suburb=d.get("suburb", ""),
                postcode=str(d.get("postcode", "")),
                state=d.get("state", "VIC"),
                property_type=d.get("property_type", "apartment"),
                bedrooms=int(d.get("bedrooms", 1)),
                bathrooms=int(d.get("bathrooms", 1)),
                parking=int(d.get("parking", 0)),
                weekly_rent=float(d["weekly_rent"]) if d.get("weekly_rent") is not None else None,
                furnished=d.get("furnished") if "furnished" in d else d.get("is_furnished"),
                property_entire=bool(d.get("property_entire", True)),
                lease_transfer=bool(d.get("lease_transfer", False)),
                available_date=d.get("available_date"),
                lease_duration=d.get("lease_duration"),
                description=d.get("description", ""),
                first_seen=d.get("first_seen") or datetime.now(timezone.utc).isoformat(),
                last_seen=d.get("last_seen") or datetime.now(timezone.utc).isoformat(),
                last_verified=d.get("last_verified"),
                listing_status=d.get("listing_status", "active"),
                verification_status=d.get("verification_status", "unverified"),
                match_score=float(d["match_score"]) if d.get("match_score") is not None else None,
                score_version=d.get("score_version", "2.0"),
                score_confidence=d.get("score_confidence", "medium"),
                sources=d.get("sources", []),
                score_breakdown=d.get("score_breakdown", {}),
                positive_factors=d.get("positive_factors", []),
                potential_concerns=d.get("potential_concerns", []),
                commute_mode=d.get("commute_mode", "Train"),
                commute_line=d.get("commute_line", "Belgrave/Lilydale Line"),
                commute_mins=int(d.get("commute_mins", 15)),
                commute_tier=int(d.get("commute_tier", 2)),
                has_direct_hawthorn_transit=bool(d.get("has_direct_hawthorn_transit", True)),
                station_name=d.get("station_name", ""),
                station_distance_m=int(d.get("station_distance_m", 500)),
                station_walking_mins=int(d.get("station_walking_mins", 6)),
                station_distance_display=d.get("station_distance_display", ""),
                station_is_explicit=bool(d.get("station_is_explicit", False)),
                availability_display=d.get("availability_display", ""),
                availability_fit=d.get("availability_fit", "ideal"),
                is_student_only=bool(d.get("is_student_only", False)),
                is_sharehouse=bool(d.get("is_sharehouse", False)),
                is_new=bool(d.get("is_new", False)),
                pass_strict_filter=bool(d.get("pass_strict_filter", True)),
                rejection_reason=d.get("rejection_reason"),
                raw_metadata=d.get("raw_metadata", {}),
            )
        return cls.from_legacy(d)
