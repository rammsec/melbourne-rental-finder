"""
Cross-Source Duplicate Detection Engine for Melbourne Rental Finder V2.

Identifies identical or matching properties listed across multiple platforms
(e.g., Domain + RealEstate + Gumtree + Flatmates).

Calculates multi-criteria match confidence:
- High Confidence (>0.85): Merges into a single unified Property record with multiple sources.
- Medium Confidence (0.65 - 0.85): Flags as probable duplicate for review.
- Low Confidence (<0.65): Maintained as distinct separate properties.
"""

from __future__ import annotations

import difflib
import re
from typing import List, Tuple, Dict, Any, Optional

from .models import Property, ListingSource


STREET_ABBREVIATIONS = {
    r"\bstreet\b": "st",
    r"\broad\b": "rd",
    r"\bavenue\b": "ave",
    r"\bhighway\b": "hwy",
    r"\bboulevard\b": "blvd",
    r"\bparade\b": "pde",
    r"\bdrive\b": "dr",
    r"\bcrescent\b": "cres",
    r"\bplace\b": "pl",
    r"\bterrace\b": "tce",
    r"\blane\b": "ln",
    r"\bcourt\b": "ct",
}


def normalize_address(address: Optional[str]) -> str:
    """Normalize street address for fuzzy matching across portals."""
    if not address:
        return ""
    text = address.lower().strip()
    text = re.sub(r"[,#]", " ", text)
    for pattern, repl in STREET_ABBREVIATIONS.items():
        text = re.sub(pattern, repl, text)
    # Remove unit/apt/lot prefix variations
    text = re.sub(r"\b(?:unit|apt|apartment|suite|lot)\s*", "", text)
    # Collapse multiple whitespaces
    text = re.sub(r"\s+", " ", text).strip()
    return text


def compute_text_similarity(s1: str, s2: str) -> float:
    """Compute normalized token Jaccard and SequenceMatcher text similarity."""
    if not s1 or not s2:
        return 0.0
    w1 = set(re.findall(r"\w{3,}", s1.lower()))
    w2 = set(re.findall(r"\w{3,}", s2.lower()))
    if not w1 or not w2:
        return difflib.SequenceMatcher(None, s1.lower()[:200], s2.lower()[:200]).ratio()
    jaccard = len(w1 & w2) / len(w1 | w2)
    seq = difflib.SequenceMatcher(None, s1.lower()[:200], s2.lower()[:200]).ratio()
    return 0.6 * jaccard + 0.4 * seq


def calculate_match_confidence(p1: Property, p2: Property) -> Tuple[float, List[str]]:
    """
    Evaluate similarity between two properties across multiple dimensions:
    - Suburb & Postcode
    - Street Address
    - Weekly Rent
    - Bedroom & Bathroom counts
    - Property type
    - Title & Description similarity

    Returns (confidence_score [0.0 - 1.0], reasons_list).
    """
    reasons: List[str] = []
    confidence = 0.0

    # 1. Suburb must match
    sub1 = (p1.suburb or "").strip().lower()
    sub2 = (p2.suburb or "").strip().lower()
    if not sub1 or not sub2 or sub1 != sub2:
        return 0.0, ["Different suburbs"]

    # 2. Address matching
    addr1 = normalize_address(p1.address)
    addr2 = normalize_address(p2.address)
    address_matched = False

    if addr1 and addr2:
        if addr1 == addr2:
            confidence += 0.45
            reasons.append("Exact street address match")
            address_matched = True
        elif difflib.SequenceMatcher(None, addr1, addr2).ratio() > 0.8:
            confidence += 0.35
            reasons.append("High address similarity")
            address_matched = True

    # 3. Weekly rent comparison
    rent1 = p1.weekly_rent
    rent2 = p2.weekly_rent
    if rent1 is not None and rent2 is not None and rent1 > 0 and rent2 > 0:
        if rent1 == rent2:
            confidence += 0.25
            reasons.append(f"Identical weekly rent (${int(rent1)}/wk)")
        else:
            diff_pct = abs(rent1 - rent2) / max(rent1, rent2)
            if diff_pct <= 0.05:
                confidence += 0.20
                reasons.append(f"Rent within 5% (${int(rent1)} vs ${int(rent2)})")
            elif diff_pct <= 0.10:
                confidence += 0.10
                reasons.append(f"Rent within 10% (${int(rent1)} vs ${int(rent2)})")
            else:
                # Rent mismatch strongly suggests different properties
                confidence -= 0.30

    # 4. Bedroom & Bathroom matching
    if p1.bedrooms == p2.bedrooms:
        confidence += 0.15
        reasons.append(f"Matching bedroom count ({p1.bedrooms} BR)")
    else:
        # Different bedrooms almost always means different properties
        confidence -= 0.35

    if p1.bathrooms == p2.bathrooms:
        confidence += 0.05
        reasons.append("Matching bathroom count")

    # 5. Property type
    if p1.property_type == p2.property_type:
        confidence += 0.05
        reasons.append(f"Matching property type ({p1.property_type})")

    # 6. Title and description text similarity
    desc_sim = compute_text_similarity(
        f"{p1.title} {p1.description}",
        f"{p2.title} {p2.description}"
    )
    if desc_sim > 0.70:
        confidence += 0.20
        reasons.append(f"High description similarity ({int(desc_sim * 100)}%)")
    elif desc_sim > 0.45:
        confidence += 0.10
        reasons.append(f"Moderate description similarity ({int(desc_sim * 100)}%)")

    # If exact address and rent match, ensure minimum high confidence
    if address_matched and (rent1 == rent2 or (rent1 and rent2 and abs(rent1 - rent2) / max(rent1, rent2) <= 0.05)):
        confidence = max(confidence, 0.88)

    # Clamp confidence between 0.0 and 1.0
    final_confidence = round(max(0.0, min(1.0, confidence)), 3)
    return final_confidence, reasons


def merge_properties(primary: Property, secondary: Property) -> Property:
    """
    Merge secondary property details into primary property record,
    preserving all source URLs and highest-quality data.
    """
    # Ensure primary itself is in primary.sources
    if not primary.sources:
        primary.sources = [{
            "source_name": primary.source,
            "source_listing_id": primary.source_listing_id,
            "source_url": primary.source_url,
            "first_seen": primary.first_seen,
            "last_seen": primary.last_seen,
            "is_active": True,
        }]

    existing_source_urls = {s.get("source_url") or s.get("url") for s in primary.sources}
    
    # Add secondary sources
    for s in secondary.sources:
        s_url = s.get("source_url") or s.get("url")
        if s_url and s_url not in existing_source_urls:
            primary.sources.append(s)
            existing_source_urls.add(s_url)

    if secondary.source_url not in existing_source_urls:
        primary.sources.append({
            "source_name": secondary.source,
            "source_listing_id": secondary.source_listing_id,
            "source_url": secondary.source_url,
            "first_seen": secondary.first_seen,
            "last_seen": secondary.last_seen,
            "is_active": True,
        })

    # Pick the most complete address
    if not primary.address and secondary.address:
        primary.address = secondary.address

    # Pick earliest first_seen and latest last_seen
    if secondary.first_seen < primary.first_seen:
        primary.first_seen = secondary.first_seen
    if secondary.last_seen > primary.last_seen:
        primary.last_seen = secondary.last_seen

    # Prefer verified status if either is verified
    if secondary.verification_status == "verified":
        primary.verification_status = "verified"
        primary.last_verified = secondary.last_verified or primary.last_verified

    # Combine description length if secondary has richer content
    if len(secondary.description) > len(primary.description) + 50:
        primary.description = secondary.description

    return primary


def deduplicate_properties(
    properties: List[Property],
    high_threshold: float = 0.85,
    medium_threshold: float = 0.65,
) -> Tuple[List[Property], List[Dict[str, Any]]]:
    """
    Deduplicate a list of properties across sources.
    Returns:
    - deduplicated_list: Unified Property list with duplicates merged
    - flagged_review_list: Medium-confidence matches flagged for inspection
    """
    deduped: List[Property] = []
    flagged: List[Dict[str, Any]] = []
    merged_ids = set()

    # Pre-index by suburb and bedroom count for fast candidate filtering
    buckets: Dict[Tuple[str, int], List[int]] = {}
    for idx, p in enumerate(properties):
        key = ((p.suburb or "").strip().lower(), p.bedrooms)
        buckets.setdefault(key, []).append(idx)

    for i, p1 in enumerate(properties):
        if p1.property_id in merged_ids:
            continue

        target_prop = p1
        key = ((p1.suburb or "").strip().lower(), p1.bedrooms)
        candidates = [j for j in buckets.get(key, []) if j > i]

        for j in candidates:
            p2 = properties[j]
            if p2.property_id in merged_ids:
                continue

            conf, reasons = calculate_match_confidence(target_prop, p2)
            if conf >= high_threshold:
                # Merge duplicate into target_prop
                target_prop = merge_properties(target_prop, p2)
                merged_ids.add(p2.property_id)
            elif conf >= medium_threshold:
                # Flag for user / analytics review
                flagged.append({
                    "property_id_1": target_prop.property_id,
                    "property_id_2": p2.property_id,
                    "confidence": conf,
                    "reasons": reasons,
                    "source_1": target_prop.source,
                    "source_2": p2.source,
                    "suburb": target_prop.suburb,
                    "rent_1": target_prop.weekly_rent,
                    "rent_2": p2.weekly_rent,
                })

        deduped.append(target_prop)

    return deduped, flagged
