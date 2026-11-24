"""
AI Evaluator Agent for Melbourne Rental Finder.

Acts as an autonomous personal property advisor for a solo renter seeking:
- An entire property with 2+ bedrooms (specifically to use 2nd bedroom as a dedicated WFH office/study)
- Direct train or tram commute to Hawthorn (Belgrave/Lilydale lines, Tram 70/75/16)
- Budget constraints (≤ $560/wk unfurnished, ≤ $625/wk furnished)
- Move-in window: Dec 5, 2026 – Jan 15, 2027

Evaluates deep property characteristics from descriptions, specs, and transit data:
1. Work-From-Home (WFH) Suitability & Layout Flexibility
2. Street Noise, Traffic Exposure & Location Tranquility
3. Climate Control & Thermal Comfort (Split-system vs panel heaters)
4. Kitchen & Laundry Essentials (Dishwasher, internal vs communal laundry)
5. Natural Light & Outdoor Living (Balcony, orientation, windows)
6. Parking & Transit Convenience
7. Financial Value & Timeline Fit

Generates an explainable structured assessment:
- verdict: HIGH_MATCH | GOOD_MATCH | CONSIDER_WITH_CAUTION | NOT_RECOMMENDED
- badge_label: Short UI display tag
- lifestyle_score: 0 - 100
- one_liner: Quick summary verdict
- lifestyle_fit: Dimension breakdown
- strengths: Top positive matches
- cautions: Compromises / items needing acoustic/space verification
- inspection_tips: Targeted questions to check at the open for inspection
"""

from __future__ import annotations

import re
from typing import Dict, Any, List, Optional
from datetime import datetime

from .models import Property


BUSY_MELBOURNE_CORRIDORS = [
    r"\bburwood\s+r(?:oa)?d\b",
    r"\bcamberwell\s+r(?:oa)?d\b",
    r"\briversdale\s+r(?:oa)?d\b",
    r"\btoorak\s+r(?:oa)?d\b",
    r"\bbarkers\s+r(?:oa)?d\b",
    r"\bwhitehorse\s+r(?:oa)?d\b",
    r"\bcanterbury\s+r(?:oa)?d\b",
    r"\bwarrigal\s+r(?:oa)?d\b",
    r"\bmaroondah\s+h(?:igh)?w(?:a)?y\b",
    r"\bdandenong\s+r(?:oa)?d\b",
    r"\bhigh\s+st(?:reet)?\b",
    r"\bpunts?\s+r(?:oa)?d\b",
]

QUIET_INDICATORS = [
    r"\brear\s+of\s+(?:the\s+)?block\b",
    r"\bquiet\s+(?:street|cul-de-sac|pocket|location|setting)\b",
    r"\bpeaceful\b",
    r"\bserene\b",
    r"\btucked\s+away\b",
    r"\bset\s+back\b",
    r"\btree-lined\s+street\b",
    r"\bdouble\s+glazed\b",
    r"\bdouble-glazed\b",
    r"\bsoundproof\b",
    r"\bacoustic\b",
    r"\bprivate\s+sanctuary\b",
]


class RentalAIEvaluatorAgent:
    """
    Intelligent evaluation agent that assesses rental properties against
    personal lifestyle needs and criteria.
    """

    def __init__(self, agent_name: str = "Aria (Melbourne Rental AI Advisor)"):
        self.agent_name = agent_name

    def evaluate(self, prop: Property) -> Dict[str, Any]:
        """Perform multi-dimensional lifestyle evaluation of a single property."""
        text = f"{prop.title or ''} {prop.description or ''} {prop.address or ''}".lower()
        suburb = (prop.suburb or "").lower().strip()
        address = (prop.address or "").lower().strip()

        score = 70.0  # Baseline
        strengths: List[str] = []
        cautions: List[str] = []
        inspection_tips: List[str] = []

        # -----------------------------------------------------------------
        # 1. Work From Home (WFH) & Second Bedroom Utility
        # -----------------------------------------------------------------
        wfh_status = "Good (2BR for Dedicated Study)"
        has_wfh_keyword = bool(re.search(r"\b(?:study|home office|wfh|work from home|study nook|second bedroom|desk space)\b", text))
        has_flexible_layout = bool(re.search(r"\b(?:generous living|spacious living|flexible floorplan|versatile layout|open plan)\b", text))
        has_nbn = bool(re.search(r"\b(?:nbn|fibre|high speed internet|broadband)\b", text))

        if prop.bedrooms and prop.bedrooms >= 2:
            if has_wfh_keyword:
                score += 8
                wfh_status = "Exceptional (Study/Office Highlighted)"
                strengths.append("Second bedroom or dedicated study area ideal for a quiet work-from-home setup")
            elif has_flexible_layout:
                score += 5
                wfh_status = "High (Spacious Layout for Desk/WFH)"
                strengths.append("Generous 2BR floorplan accommodating a comfortable remote workstation")
            else:
                score += 3
                strengths.append("Entire 2-bedroom property provides dedicated separation for work and rest")
            
            if has_nbn:
                strengths.append("NBN / high-speed internet readiness indicated")
        else:
            wfh_status = "Limited"
            cautions.append("Fewer than 2 bedrooms; restricted remote working separation")

        # -----------------------------------------------------------------
        # 2. Acoustic Tranquility & Street Noise Exposure
        # -----------------------------------------------------------------
        is_on_busy_corridor = any(re.search(p, address) or re.search(p, text) for p in BUSY_MELBOURNE_CORRIDORS)
        is_quiet_pocket = any(re.search(p, text) for p in QUIET_INDICATORS)
        is_top_floor = bool(re.search(r"\b(?:top floor|penthouse|upper level)\b", text))

        if is_quiet_pocket:
            score += 7
            noise_level = "Quiet / Low Traffic"
            strengths.append("Set in a quiet pocket, rear of block, or features acoustic sound-insulation")
        elif is_on_busy_corridor:
            score -= 10
            noise_level = "Potential Traffic Noise"
            cautions.append(f"Located on or near a major road ({prop.address or 'arterial corridor'}); check bedroom acoustic exposure")
            inspection_tips.append("Listen closely for traffic or tram rumblings with windows open and closed during inspection")
        else:
            noise_level = "Moderate Residential"
            if is_top_floor:
                score += 3
                strengths.append("Top-floor position minimizes overhead footfall noise")

        # -----------------------------------------------------------------
        # 3. Climate Control & Thermal Comfort
        # -----------------------------------------------------------------
        has_split_system = bool(re.search(r"\b(?:split-system|split system|reverse cycle|air-conditioning|air conditioning|a/c)\b", text))
        has_ducted = bool(re.search(r"\b(?:ducted heating|ducted air|central heating|climate control)\b", text))
        has_panel_only = bool(re.search(r"\b(?:panel heater|electric wall heater|no cooling)\b", text)) and not (has_split_system or has_ducted)

        if has_split_system or has_ducted:
            score += 6
            climate_fit = "Split-System A/C & Heating"
            strengths.append("Equipped with split-system reverse-cycle heating and cooling for year-round Melbourne comfort")
        elif has_panel_only:
            score -= 6
            climate_fit = "Electric Panel Heaters (No Cooling Noted)"
            cautions.append("Panel heaters only with no cooling mentioned; can become warm during Melbourne summer heatwaves")
            inspection_tips.append("Confirm orientation and cross-ventilation, and ask if a portable A/C unit is allowed")
        else:
            climate_fit = "Standard / Unspecified"
            inspection_tips.append("Verify presence of split-system A/C or heating unit at the property")

        # -----------------------------------------------------------------
        # 4. Kitchen & Laundry Essentials
        # -----------------------------------------------------------------
        has_dishwasher = bool(re.search(r"\b(?:dishwasher|miele|bosch|smeg|fisher & paykel)\b", text))
        has_gas_cook = bool(re.search(r"\b(?:gas cooktop|gas cooking|induction)\b", text))
        has_communal_laundry = bool(re.search(r"\b(?:communal laundry|shared laundry|coin laundry|coin-operated)\b", text))
        has_internal_laundry = bool(re.search(r"\b(?:internal laundry|euro laundry|european laundry|separate laundry|laundry space)\b", text))

        if has_dishwasher:
            score += 4
            strengths.append("Modern kitchen complete with dishwasher")
        if has_internal_laundry:
            score += 3
            strengths.append("Private internal/Euro laundry facilities")
        elif has_communal_laundry:
            score -= 8
            cautions.append("Communal / shared laundry facilities instead of in-unit laundry")
            inspection_tips.append("Inspect the shared laundry area (cleanliness, machine availability, payment methods)")

        kitchen_laundry_fit = (
            "Full (Dishwasher & Internal Laundry)" if (has_dishwasher and has_internal_laundry)
            else "Communal Laundry" if has_communal_laundry
            else "Standard Kitchen & Laundry"
        )

        # -----------------------------------------------------------------
        # 5. Natural Light & Outdoor Living
        # -----------------------------------------------------------------
        has_balcony = bool(re.search(r"\b(?:balcony|private balcony|courtyard|terrace|private garden|deck|patio)\b", text))
        has_north_light = bool(re.search(r"\b(?:north-facing|north facing|east-facing|east facing|sun-drenched|bathed in light|sun-filled)\b", text))

        if has_balcony:
            score += 4
            strengths.append("Private balcony or courtyard for fresh air and outdoor relaxation")
        if has_north_light:
            score += 3
            strengths.append("Sun-drenched orientation capturing desirable northern or eastern natural light")

        # -----------------------------------------------------------------
        # 6. Secure Parking & Hawthorn Transit Link
        # -----------------------------------------------------------------
        parking_count = prop.parking or 0
        has_secure_parking = bool(re.search(r"\b(?:secure parking|basement parking|lock up garage|remote garage|undercover parking)\b", text))

        if parking_count >= 1 or has_secure_parking:
            score += 4
            strengths.append(f"Dedicated off-street parking included ({parking_count} space{'s' if parking_count > 1 else ''})")
            parking_status = "Off-street parking included"
        else:
            parking_status = "On-street / permit zone"
            if "permit" in text:
                cautions.append("Parking may require a local council street permit; check parking restrictions")

        commute_mins = prop.commute_mins or 15
        if prop.has_direct_hawthorn_transit and commute_mins <= 12:
            score += 6
            strengths.append(f"Superb commute: direct {prop.commute_mode} to Hawthorn (~{commute_mins} mins)")
        elif prop.has_direct_hawthorn_transit:
            score += 4
            strengths.append(f"Direct corridor transit: ~{commute_mins} mins via {prop.commute_mode} ({prop.commute_line})")

        # -----------------------------------------------------------------
        # 7. Rent Value & Move-in Window
        # -----------------------------------------------------------------
        weekly_rent = prop.weekly_rent or 550
        is_furn = bool(prop.furnished)
        budget_cap = 625 if is_furn else 560

        if weekly_rent <= (budget_cap - 60):
            score += 5
            strengths.append(f"High budget surplus: ${weekly_rent}/wk is well below the ${budget_cap}/wk cap")
        elif weekly_rent > budget_cap:
            score -= 15
            cautions.append(f"Rent of ${weekly_rent}/wk exceeds target cap of ${budget_cap}/wk")

        # Availability fit
        avail_str = (prop.available_date or "").lower()
        if "dec" in avail_str or "jan" in avail_str or prop.availability_fit == "ideal":
            score += 3
            strengths.append(f"Move-in availability matches target window ({prop.availability_display or 'Dec-Jan'})")
        elif "now" in avail_str or "immediate" in avail_str:
            inspection_tips.append("Available immediately; verify if the agency allows lease commencement in early December")

        # -----------------------------------------------------------------
        # Synthesize Final Verdict and Category
        # -----------------------------------------------------------------
        final_score = int(max(35, min(98, score)))

        if final_score >= 82:
            verdict = "HIGH_MATCH"
            badge_label = "🎯 Top AI Match"
            badge_color = "#16a34a"
            one_liner = f"High-confidence match: Excellent 2BR WFH layout, {climate_fit.lower()}, and fast direct commute to Hawthorn."
        elif final_score >= 70:
            verdict = "GOOD_MATCH"
            badge_label = "✨ Strong Contender"
            badge_color = "#0284c7"
            one_liner = f"Solid option meeting core 2BR budget and Hawthorn corridor commute requirements."
        elif final_score >= 55:
            verdict = "CONSIDER_WITH_CAUTION"
            badge_label = "⚠️ Review Compromises"
            badge_color = "#d97706"
            compromise_summary = cautions[0] if cautions else "contains a few lifestyle compromises"
            one_liner = f"Viable location but note: {compromise_summary}."
        else:
            verdict = "NOT_RECOMMENDED"
            badge_label = "❌ Lifestyle Mismatch"
            badge_color = "#dc2626"
            one_liner = "Significant compromises detected (noise, climate control, or layout suitability)."

        # Ensure at least 1 inspection tip
        if not inspection_tips:
            inspection_tips.append("Inspect bedroom 2 dimensions to ensure comfortable desk/workstation fit alongside storage.")

        return {
            "verdict": verdict,
            "badge_label": badge_label,
            "badge_color": badge_color,
            "match_score": final_score,
            "one_liner": one_liner,
            "agent_name": self.agent_name,
            "evaluated_at": datetime.now().strftime("%Y-%m-%d"),
            "lifestyle_fit": {
                "wfh_suitability": wfh_status,
                "noise_level": noise_level,
                "climate_comfort": climate_fit,
                "kitchen_laundry": kitchen_laundry_fit,
                "parking_status": parking_status,
            },
            "strengths": strengths[:4],
            "cautions": cautions[:3],
            "inspection_tips": inspection_tips[:3],
        }


# Singleton evaluator instance for clean reuse
default_ai_agent = RentalAIEvaluatorAgent()


def evaluate_property_ai(prop: Property) -> Dict[str, Any]:
    """Helper function to run the AI evaluator agent on a property."""
    return default_ai_agent.evaluate(prop)
