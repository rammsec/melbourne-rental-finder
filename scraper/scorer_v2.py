"""
Explainable 100-Point Scoring Engine V2 for Melbourne Rental Finder.

Implements the V2 scoring model:
- Hard Eligibility Criteria Separation (Entire place, Budget cap, Student-only exclusion)
- 100-Point Scoring Weight Distribution:
    1. Rent Affordability: 25 points
    2. Commute Convenience: 25 points
    3. Property Suitability: 20 points
    4. Move-in Timing: 15 points
    5. Amenities & Features: 10 points
    6. Freshness: 5 points
- Transparent Factor Explanation (Breakdown, Positive Factors, Potential Concerns)
- Confidence Assessment (High, Medium, Low)
- Score Versioning (score_version: "2.0")
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional, Tuple

from .config import USER_CRITERIA, HAWTHORN_DIRECT_SUBURBS
from .models import Property, PropertyScore
from .freshness import parse_iso_datetime


def evaluate_hard_eligibility(
    weekly_rent: Optional[float],
    is_furnished: bool,
    is_entire_property: bool,
    is_student_only: bool,
    is_sharehouse: bool,
    max_budget_cap: float = 650.0,
) -> Tuple[bool, List[str]]:
    """
    Evaluate strict non-negotiable eligibility constraints.
    Returns (is_eligible, disqualification_reasons).
    """
    reasons: List[str] = []

    if is_student_only:
        reasons.append("Restricted to student-only accommodation")

    if is_sharehouse or not is_entire_property:
        reasons.append("Sharehouse or individual room (solo entire place required)")

    if weekly_rent is None:
        reasons.append("No rental price specified")
    elif weekly_rent < 200:
        reasons.append("Price below legitimate rental threshold (<$200/wk suggests storage/carpark/scam)")
    elif weekly_rent > max_budget_cap:
        reasons.append(f"Rental price (${int(weekly_rent)}/wk) exceeds absolute maximum threshold (${int(max_budget_cap)}/wk)")

    return len(reasons) == 0, reasons


def score_property_v2(prop: Property) -> Property:
    """
    Evaluate and score a Property object using the 100-point explainable engine.
    Updates the Property object in-place with score breakdown, positive factors,
    potential concerns, and confidence rating.
    """
    full_text = f"{prop.title} {prop.description}".lower()
    weekly_rent = prop.weekly_rent
    is_furnished = bool(prop.furnished)
    is_entire = prop.property_entire and not prop.is_sharehouse
    suburb_clean = (prop.suburb or "").strip().lower()

    # 1. Evaluate Hard Eligibility Criteria
    budget_target = (
        USER_CRITERIA.get("max_rent_furnished", 560)
        if is_furnished
        else USER_CRITERIA.get("max_rent_unfurnished", 525)
    )
    is_eligible, disqualification_reasons = evaluate_hard_eligibility(
        weekly_rent=weekly_rent,
        is_furnished=is_furnished,
        is_entire_property=is_entire,
        is_student_only=prop.is_student_only,
        is_sharehouse=prop.is_sharehouse,
        max_budget_cap=650.0,
    )

    prop.pass_strict_filter = is_eligible and (weekly_rent is not None and weekly_rent <= budget_target)
    if not is_eligible:
        prop.rejection_reason = "; ".join(disqualification_reasons)
    elif not prop.pass_strict_filter:
        prop.rejection_reason = f"Above target budget (${int(weekly_rent)}/wk > ${budget_target}/wk)"
    else:
        prop.rejection_reason = None

    positive_factors: List[str] = []
    potential_concerns: List[str] = []

    # ----------------------------------------------------
    # Category 1: Rent Affordability (Max 25 pts)
    # ----------------------------------------------------
    rent_pts = 0.0
    rent_reason = ""
    if weekly_rent is not None and weekly_rent >= 200:
        if weekly_rent <= budget_target - 50:
            rent_pts = 25.0
            rent_reason = f"${int(weekly_rent)}/wk is well below the ${budget_target}/wk target (superb value)"
            positive_factors.append(f"Exceptional value at ${int(weekly_rent)}/wk (${int(budget_target - weekly_rent)}/wk under budget)")
        elif weekly_rent <= budget_target:
            diff = budget_target - weekly_rent
            rent_pts = round(20.0 + (diff / 50.0) * 4.0, 1)
            rent_reason = f"${int(weekly_rent)}/wk is within target budget (${budget_target}/wk)"
            positive_factors.append(f"Comfortably within budget (${int(weekly_rent)}/wk)")
        elif weekly_rent <= 600:
            over = weekly_rent - budget_target
            rent_pts = max(10.0, round(18.0 - (over / 75.0) * 8.0, 1))
            rent_reason = f"${int(weekly_rent)}/wk is slightly above ${budget_target}/wk target but under $600/wk ceiling"
            potential_concerns.append(f"Weekly rent of ${int(weekly_rent)} exceeds target of ${budget_target}/wk")
        else:
            rent_pts = 6.0
            rent_reason = f"${int(weekly_rent)}/wk exceeds the normal $600/wk budget window"
            potential_concerns.append(f"High weekly rent (${int(weekly_rent)}/wk)")
    else:
        rent_reason = "Price unlisted or invalid"
        potential_concerns.append("Rental price requires manual verification")

    # ----------------------------------------------------
    # Category 2: Commute Convenience to Hawthorn (Max 25 pts)
    # ----------------------------------------------------
    commute_pts = 0.0
    commute_reason = ""
    commute_info = HAWTHORN_DIRECT_SUBURBS.get(suburb_clean)
    if commute_info:
        tier = commute_info.get("tier", 2)
        mins = commute_info.get("commute_mins", 20)
        mode = commute_info.get("mode", "Train")

        if tier == 1:
            base_pts = 22.0
        elif tier == 2:
            base_pts = 17.0
        else:
            base_pts = 12.0

        # Station proximity bonus (+0 to +3 pts)
        dist_m = prop.station_distance_m
        if dist_m <= 400:
            dist_bonus = 3.0
            positive_factors.append(f"Short walk to {prop.station_name or 'station'} (~{dist_m}m, {prop.station_walking_mins} min)")
        elif dist_m <= 800:
            dist_bonus = 2.0
            positive_factors.append(f"Convenient station access (~{dist_m}m to {prop.station_name or 'station'})")
        elif dist_m <= 1200:
            dist_bonus = 1.0
        else:
            dist_bonus = 0.0
            potential_concerns.append(f"Longer walk to train station (~{dist_m}m, {prop.station_walking_mins} mins)")

        commute_pts = min(25.0, base_pts + dist_bonus)
        commute_reason = f"Direct {mode} to Hawthorn (~{mins} mins). {prop.station_distance_display or ''}".strip()
        positive_factors.append(f"Direct {mode} to Hawthorn (~{mins} min)")
    else:
        commute_pts = 5.0
        commute_reason = f"Indirect transit from {prop.suburb} (transfer required to reach Hawthorn)"
        potential_concerns.append(f"No direct train or tram to Hawthorn from {prop.suburb}")

    # ----------------------------------------------------
    # Category 3: Property Suitability & Space (Max 20 pts)
    # ----------------------------------------------------
    suitability_pts = 0.0
    suitability_reason = ""
    beds = prop.bedrooms
    ptype = prop.property_type.title()

    if is_entire:
        positive_factors.append("Entire private property (zero housemates)")
    else:
        potential_concerns.append("Not an entire property")

    if beds == 2:
        suitability_pts = 20.0
        suitability_reason = f"2-bedroom {ptype} perfectly matches preferred solo space requirement"
        positive_factors.append(f"2 Bedrooms (Preferred layout)")
    elif beds == 1:
        suitability_pts = 14.0
        suitability_reason = f"1-bedroom {ptype} provides private solo accommodation"
        positive_factors.append("1 Bedroom entire place")
    elif beds >= 3 and is_entire:
        suitability_pts = 16.0
        suitability_reason = f"{beds}-bedroom entire property offers generous living area"
        positive_factors.append(f"{beds} Bedrooms entire property")
    else:
        suitability_pts = 8.0
        suitability_reason = f"Studio / compact living format"

    # ----------------------------------------------------
    # Category 4: Move-in Timing & Lease Fit (Max 15 pts)
    # ----------------------------------------------------
    timing_pts = 0.0
    timing_reason = ""
    avail_fit = prop.availability_fit
    avail_display = prop.availability_display or "Flexible"

    if avail_fit == "ideal":
        timing_pts = 15.0
        timing_reason = f"Available {avail_display}, perfectly within Dec 5 – Jan 15 window"
        positive_factors.append(f"Ideal move-in timing ({avail_display})")
    elif avail_fit == "early_flex":
        timing_pts = 11.0
        timing_reason = f"Available {avail_display} (early flexible start before Dec 5)"
        positive_factors.append(f"Early move-in available ({avail_display})")
    elif avail_fit == "jan_tight":
        timing_pts = 7.0
        timing_reason = f"Available {avail_display} (close to Jan 10 lease end)"
        potential_concerns.append(f"Late move-in date ({avail_display}) requires careful transition")
    else:
        timing_pts = 4.0
        timing_reason = f"Available {avail_display}"

    if prop.lease_transfer:
        positive_factors.append("Lease transfer / break opportunity (frequently lower rent)")

    # ----------------------------------------------------
    # Category 5: Amenities & Features (Max 10 pts)
    # ----------------------------------------------------
    amenity_pts = 0.0
    amenity_items: List[str] = []

    if prop.parking > 0 or "parking" in full_text or "car space" in full_text or "garage" in full_text:
        amenity_pts += 3.5
        amenity_items.append("Parking included")
        positive_factors.append("Dedicated parking space")
    else:
        potential_concerns.append("No off-street parking confirmed")

    if is_furnished:
        amenity_pts += 3.5
        amenity_items.append("Furnished")
        positive_factors.append("Furnished interior")
    else:
        amenity_items.append("Unfurnished")

    if any(k in full_text for k in ("bills included", "inc. bills", "all bills included")):
        amenity_pts += 2.0
        amenity_items.append("Bills included")
        positive_factors.append("Utilities/bills included in rent")

    if any(k in full_text for k in ("balcony", "courtyard", "air conditioning", "cooling", "dishwasher")):
        amenity_pts += 1.5
        amenity_items.append("Modern features")

    amenity_pts = min(10.0, round(amenity_pts, 1))
    amenity_reason = ", ".join(amenity_items) if amenity_items else "Standard property amenities"

    # ----------------------------------------------------
    # Category 6: Freshness & Market Discovery (Max 5 pts)
    # ----------------------------------------------------
    freshness_pts = 0.0
    freshness_reason = ""
    now = datetime.now(timezone.utc)
    first_dt = parse_iso_datetime(prop.first_seen)
    age_hours = max(0.0, (now - first_dt).total_seconds() / 3600.0)

    if age_hours <= 24.0:
        freshness_pts = 5.0
        freshness_reason = f"Discovered in last 24 hours ({int(age_hours)}h ago)"
        positive_factors.append("New listing (discovered <24h ago)")
    elif age_hours <= 48.0:
        freshness_pts = 4.0
        freshness_reason = f"Discovered in last 48 hours ({int(age_hours / 24)}d ago)"
        positive_factors.append("Recently posted listing (<48h)")
    elif age_hours <= 168.0:  # 7 days
        freshness_pts = 2.5
        freshness_reason = f"Listed within the past week ({int(age_hours / 24)}d ago)"
    else:
        freshness_pts = 1.0
        freshness_reason = f"Listed {int(age_hours / 24)} days ago"

    # Total Score Calculation
    total = rent_pts + commute_pts + suitability_pts + timing_pts + amenity_pts + freshness_pts
    total = round(min(100.0, max(0.0, total)))

    # If disqualified by hard criteria, set total score to 0 or penalty
    if not is_eligible:
        total = 0.0

    # Confidence Rating Determination
    # High: Known address, explicit station distance, known rent, explicit availability
    # Medium: Suburb verified, station estimated from street, known rent
    # Low: Missing critical attributes
    has_explicit_station = prop.station_is_explicit
    has_known_rent = weekly_rent is not None
    has_avail = bool(prop.available_date or (prop.availability_display and "unspecified" not in prop.availability_display.lower()))

    if has_explicit_station and has_known_rent and has_avail and commute_info:
        confidence = "high"
    elif has_known_rent and commute_info:
        confidence = "medium"
    else:
        confidence = "low"

    breakdown = {
        "rent_affordability": {
            "score": rent_pts,
            "max": 25,
            "reason": rent_reason,
        },
        "commute_convenience": {
            "score": commute_pts,
            "max": 25,
            "reason": commute_reason,
        },
        "property_suitability": {
            "score": suitability_pts,
            "max": 20,
            "reason": suitability_reason,
        },
        "move_in_timing": {
            "score": timing_pts,
            "max": 15,
            "reason": timing_reason,
        },
        "amenities": {
            "score": amenity_pts,
            "max": 10,
            "reason": amenity_reason,
        },
        "freshness": {
            "score": freshness_pts,
            "max": 5,
            "reason": freshness_reason,
        },
    }

    # Store results onto Property object
    prop.match_score = total
    prop.score_version = "2.0"
    prop.score_confidence = confidence
    prop.score_breakdown = breakdown
    prop.positive_factors = positive_factors[:6]  # Top positive factors
    prop.potential_concerns = potential_concerns[:4]  # Key concerns

    return prop
