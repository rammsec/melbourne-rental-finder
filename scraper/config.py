"""
Hawthorn Commute & Criteria Configuration for Melbourne Rental & Lease Transfer Finder.

User Criteria:
- Solo occupant ("only for me")
- Entire property only (2BR preferred, 1BR/Studio acceptable; NO sharehouses/room-only)
- Budget:
  - Unfurnished: max $525/week
  - Furnished: max $560/week
- Move-in window: Dec 5, 2026 to Jan 15, 2027 (must find before Dec 3, 2026; current lease ends Jan 10, 2027)
- Direct train or tram commute to Hawthorn (Station / Burwood Rd / Riversdale Rd / Glenferrie Rd)
"""

from typing import Dict, Any, List

USER_CRITERIA = {
    # 2 BHK caps (Preferred)
    "max_rent_2bhk_unfurnished": 560,
    "max_rent_2bhk_furnished": 625,
    # 1 BHK / Studio caps
    "max_rent_1bhk_unfurnished": 400,
    "max_rent_1bhk_furnished": 500,
    # General / 2BHK default backward-compatibility
    "max_rent_unfurnished": 560,
    "max_rent_furnished": 625,
    "preferred_bedrooms": 2,
    "min_bedrooms": 1,
    "allow_sharehouse": False,
    "decision_deadline": "2026-12-03",
    "current_lease_end": "2027-01-10",
    "move_in_start": "2026-12-05",
    "move_in_end": "2027-01-15",
    "target_hub": "Hawthorn, VIC 3122",
}


def get_budget_cap(bedrooms: int = 1, is_furnished: bool = False) -> int:
    """
    Granular user budget caps:
    - 2 BHK (and 3+ BHK): Furnished <= 625, Unfurnished <= 560
    - 1 BHK / Studio: Furnished <= 500, Unfurnished <= 400
    """
    if (bedrooms or 1) >= 2:
        return 625 if is_furnished else 560
    return 500 if is_furnished else 400


# Suburbs with a DIRECT train (Belgrave / Lilydale / Alamein lines),
# DIRECT tram (Route 70, Route 75, Route 16), or DIRECT bus (Route 609) to Hawthorn.
HAWTHORN_DIRECT_SUBURBS: Dict[str, Dict[str, Any]] = {
    # Target & Immediate Neighbours (0 - 6 mins)
    "hawthorn": {
        "postcode": "3122",
        "mode": "Train / Tram 70, 75, 16",
        "line": "Belgrave/Lilydale/Alamein Line + Tram 70/75/16",
        "commute_mins": 2,
        "tier": 1,
    },
    "hawthorn east": {
        "postcode": "3123",
        "mode": "Train / Tram 70, 75",
        "line": "Auburn Station (Belgrave/Lilydale) + Tram 70/75",
        "commute_mins": 4,
        "tier": 1,
    },
    "glenferrie": {
        "postcode": "3122",
        "mode": "Train / Tram 16",
        "line": "Belgrave/Lilydale/Alamein Line (1 stop)",
        "commute_mins": 2,
        "tier": 1,
    },
    "auburn": {
        "postcode": "3123",
        "mode": "Train",
        "line": "Belgrave/Lilydale/Alamein Line (2 stops)",
        "commute_mins": 4,
        "tier": 1,
    },
    "richmond": {
        "postcode": "3121",
        "mode": "Train / Tram 70, 75",
        "line": "Belgrave/Lilydale/Alamein Line (1-2 stops) + Tram 70/75",
        "commute_mins": 4,
        "tier": 1,
    },
    "burnley": {
        "postcode": "3121",
        "mode": "Train / Tram 70",
        "line": "Belgrave/Lilydale/Alamein Line (1 stop) + Tram 70",
        "commute_mins": 3,
        "tier": 1,
    },
    "cremorne": {
        "postcode": "3121",
        "mode": "Train / Tram 70",
        "line": "East Richmond / Burnley (Belgrave/Lilydale) + Tram 70",
        "commute_mins": 5,
        "tier": 1,
    },
    "camberwell": {
        "postcode": "3124",
        "mode": "Train / Tram 70, 75",
        "line": "Belgrave/Lilydale/Alamein Line (3 stops) + Tram 70/75",
        "commute_mins": 6,
        "tier": 1,
    },
    "kew": {
        "postcode": "3101",
        "mode": "Tram 16 / Bus 609",
        "line": "Direct Tram 16 (Glenferrie Rd) & Bus 609 to Hawthorn",
        "commute_mins": 8,
        "tier": 1,
    },
    "kew east": {
        "postcode": "3102",
        "mode": "Bus / Tram 16 connection",
        "line": "High St / Glenferrie Rd Corridor",
        "commute_mins": 12,
        "tier": 2,
    },

    # Inner-East Direct Train Line (Belgrave / Lilydale / Alamein)
    "canterbury": {
        "postcode": "3126",
        "mode": "Train",
        "line": "Belgrave/Lilydale Line (direct to Hawthorn)",
        "commute_mins": 9,
        "tier": 1,
    },
    "surrey hills": {
        "postcode": "3127",
        "mode": "Train / Tram 70",
        "line": "Belgrave/Lilydale Line + Tram 70 (Riversdale Rd)",
        "commute_mins": 12,
        "tier": 1,
    },
    "mont albert": {
        "postcode": "3127",
        "mode": "Train",
        "line": "Belgrave/Lilydale Line (Union Station direct)",
        "commute_mins": 13,
        "tier": 2,
    },
    "box hill": {
        "postcode": "3128",
        "mode": "Train",
        "line": "Belgrave/Lilydale Express & Direct to Hawthorn",
        "commute_mins": 15,
        "tier": 1,
    },
    "box hill north": {
        "postcode": "3129",
        "mode": "Train",
        "line": "Box Hill Station (Belgrave/Lilydale direct)",
        "commute_mins": 18,
        "tier": 2,
    },
    "box hill south": {
        "postcode": "3128",
        "mode": "Tram 70 / Train",
        "line": "Tram 70 (Wattle Park) & Box Hill Station",
        "commute_mins": 18,
        "tier": 2,
    },
    "laburnum": {
        "postcode": "3130",
        "mode": "Train",
        "line": "Belgrave/Lilydale Line (direct to Hawthorn)",
        "commute_mins": 17,
        "tier": 2,
    },
    "blackburn": {
        "postcode": "3130",
        "mode": "Train",
        "line": "Belgrave/Lilydale Line (direct to Hawthorn)",
        "commute_mins": 19,
        "tier": 2,
    },
    "nunawading": {
        "postcode": "3131",
        "mode": "Train",
        "line": "Belgrave/Lilydale Line (direct to Hawthorn)",
        "commute_mins": 22,
        "tier": 2,
    },
    "mitcham": {
        "postcode": "3132",
        "mode": "Train",
        "line": "Belgrave/Lilydale Line (direct to Hawthorn)",
        "commute_mins": 25,
        "tier": 2,
    },
    "heatherdale": {
        "postcode": "3132",
        "mode": "Train",
        "line": "Belgrave/Lilydale Line (direct to Hawthorn)",
        "commute_mins": 27,
        "tier": 2,
    },
    "ringwood": {
        "postcode": "3134",
        "mode": "Train",
        "line": "Belgrave/Lilydale Line (direct to Hawthorn)",
        "commute_mins": 29,
        "tier": 2,
    },
    "ringwood east": {
        "postcode": "3135",
        "mode": "Train",
        "line": "Lilydale Line (direct to Hawthorn)",
        "commute_mins": 32,
        "tier": 3,
    },
    "croydon": {
        "postcode": "3136",
        "mode": "Train",
        "line": "Lilydale Line (direct to Hawthorn)",
        "commute_mins": 35,
        "tier": 3,
    },
    "mooroolbark": {
        "postcode": "3138",
        "mode": "Train",
        "line": "Lilydale Line (direct to Hawthorn)",
        "commute_mins": 38,
        "tier": 3,
    },
    "lilydale": {
        "postcode": "3140",
        "mode": "Train",
        "line": "Lilydale Line (direct to Hawthorn)",
        "commute_mins": 44,
        "tier": 3,
    },
    "heathmont": {
        "postcode": "3135",
        "mode": "Train",
        "line": "Belgrave Line (direct to Hawthorn)",
        "commute_mins": 32,
        "tier": 3,
    },
    "bayswater": {
        "postcode": "3153",
        "mode": "Train",
        "line": "Belgrave Line (direct to Hawthorn)",
        "commute_mins": 35,
        "tier": 3,
    },
    "boronia": {
        "postcode": "3155",
        "mode": "Train",
        "line": "Belgrave Line (direct to Hawthorn)",
        "commute_mins": 38,
        "tier": 3,
    },
    "ferntree gully": {
        "postcode": "3156",
        "mode": "Train",
        "line": "Belgrave Line (direct to Hawthorn)",
        "commute_mins": 41,
        "tier": 3,
    },
    "upper ferntree gully": {
        "postcode": "3156",
        "mode": "Train",
        "line": "Belgrave Line (direct to Hawthorn)",
        "commute_mins": 43,
        "tier": 3,
    },
    "upwey": {
        "postcode": "3158",
        "mode": "Train",
        "line": "Belgrave Line (direct to Hawthorn)",
        "commute_mins": 46,
        "tier": 3,
    },
    "tecoma": {
        "postcode": "3160",
        "mode": "Train",
        "line": "Belgrave Line (direct to Hawthorn)",
        "commute_mins": 48,
        "tier": 3,
    },
    "belgrave": {
        "postcode": "3160",
        "mode": "Train",
        "line": "Belgrave Line (direct to Hawthorn)",
        "commute_mins": 52,
        "tier": 3,
    },

    # Alamein Direct Train Line
    "riversdale": {
        "postcode": "3124",
        "mode": "Train / Tram 70",
        "line": "Alamein Line + Tram 70 (direct to Hawthorn)",
        "commute_mins": 9,
        "tier": 1,
    },
    "willison": {
        "postcode": "3124",
        "mode": "Train",
        "line": "Alamein Line (direct to Hawthorn)",
        "commute_mins": 11,
        "tier": 1,
    },
    "hartwell": {
        "postcode": "3124",
        "mode": "Train / Tram 75",
        "line": "Alamein Line + Tram 75 (direct to Hawthorn)",
        "commute_mins": 13,
        "tier": 1,
    },
    "burwood": {
        "postcode": "3125",
        "mode": "Train / Tram 75",
        "line": "Alamein Line (Burwood Stn) + Tram 75 (direct to Hawthorn)",
        "commute_mins": 15,
        "tier": 1,
    },
    "ashburton": {
        "postcode": "3147",
        "mode": "Train",
        "line": "Alamein Line (direct to Hawthorn)",
        "commute_mins": 17,
        "tier": 2,
    },
    "alamein": {
        "postcode": "3147",
        "mode": "Train",
        "line": "Alamein Line (direct to Hawthorn)",
        "commute_mins": 19,
        "tier": 2,
    },
    "burwood east": {
        "postcode": "3151",
        "mode": "Tram 75",
        "line": "Direct Tram 75 along Burwood Hwy to Hawthorn",
        "commute_mins": 24,
        "tier": 2,
    },
    "vermont south": {
        "postcode": "3133",
        "mode": "Tram 75",
        "line": "Direct Tram 75 to Hawthorn",
        "commute_mins": 29,
        "tier": 3,
    },

    # Direct Tram 16 Corridor (Glenferrie Rd -> Malvern -> Caulfield -> St Kilda)
    "kooyong": {
        "postcode": "3144",
        "mode": "Tram 16",
        "line": "Direct Tram 16 along Glenferrie Rd to Hawthorn",
        "commute_mins": 8,
        "tier": 1,
    },
    "toorak": {
        "postcode": "3142",
        "mode": "Tram 16",
        "line": "Direct Tram 16 along Glenferrie Rd to Hawthorn",
        "commute_mins": 10,
        "tier": 1,
    },
    "malvern": {
        "postcode": "3144",
        "mode": "Tram 16",
        "line": "Direct Tram 16 along Glenferrie Rd to Hawthorn",
        "commute_mins": 13,
        "tier": 1,
    },
    "armadale": {
        "postcode": "3143",
        "mode": "Tram 16",
        "line": "Direct Tram 16 (High St / Glenferrie Rd) to Hawthorn",
        "commute_mins": 14,
        "tier": 1,
    },
    "malvern east": {
        "postcode": "3145",
        "mode": "Tram 16",
        "line": "Tram 16 / Dandenong Rd corridor",
        "commute_mins": 18,
        "tier": 2,
    },
    "caulfield": {
        "postcode": "3162",
        "mode": "Tram 16",
        "line": "Direct Tram 16 via Dandenong/Glenferrie Rd to Hawthorn",
        "commute_mins": 20,
        "tier": 2,
    },
    "caulfield north": {
        "postcode": "3161",
        "mode": "Tram 16",
        "line": "Direct Tram 16 via Balaclava/Glenferrie Rd to Hawthorn",
        "commute_mins": 19,
        "tier": 2,
    },
    "balaclava": {
        "postcode": "3183",
        "mode": "Tram 16",
        "line": "Direct Tram 16 via Carlisle St / Glenferrie Rd",
        "commute_mins": 24,
        "tier": 2,
    },
    "st kilda": {
        "postcode": "3182",
        "mode": "Tram 16",
        "line": "Direct Tram 16 to Hawthorn (Glenferrie Rd)",
        "commute_mins": 28,
        "tier": 2,
    },
    "st kilda east": {
        "postcode": "3183",
        "mode": "Tram 16",
        "line": "Direct Tram 16 corridor to Hawthorn",
        "commute_mins": 25,
        "tier": 2,
    },

    # Direct City / Inner-West via Belgrave/Lilydale/Alamein & Tram 70/75
    "east melbourne": {
        "postcode": "3002",
        "mode": "Train / Tram 70, 75",
        "line": "Jolimont / East Richmond + Tram 70/75 to Hawthorn",
        "commute_mins": 8,
        "tier": 1,
    },
    "melbourne": {
        "postcode": "3000",
        "mode": "Train / Tram 70, 75",
        "line": "Flinders St / Parliament direct to Hawthorn (12 mins)",
        "commute_mins": 12,
        "tier": 1,
    },
    "cbd": {
        "postcode": "3000",
        "mode": "Train / Tram 70, 75",
        "line": "Flinders St / Parliament direct to Hawthorn (12 mins)",
        "commute_mins": 12,
        "tier": 1,
    },
    "melbourne cbd": {
        "postcode": "3000",
        "mode": "Train / Tram 70, 75",
        "line": "Flinders St / Parliament direct to Hawthorn (12 mins)",
        "commute_mins": 12,
        "tier": 1,
    },
    "docklands": {
        "postcode": "3008",
        "mode": "Train / Tram 70, 75",
        "line": "Southern Cross Train + Direct Tram 70/75 to Hawthorn",
        "commute_mins": 18,
        "tier": 2,
    },
    "abbotsford": {
        "postcode": "3067",
        "mode": "Bus 609 / Tram 109+16",
        "line": "Direct Bus 609 / Boroondara River Crossing to Hawthorn",
        "commute_mins": 10,
        "tier": 1,
    },
    "collingwood": {
        "postcode": "3066",
        "mode": "Bus 609 / Train via Richmond",
        "line": "Bus 609 or 5-min link via Victoria St to Hawthorn",
        "commute_mins": 14,
        "tier": 2,
    },
    "south yarra": {
        "postcode": "3141",
        "mode": "Train (1 stop via Richmond) / Tram",
        "line": "1 stop to Richmond -> Hawthorn (or Chapel/Church St Tram)",
        "commute_mins": 12,
        "tier": 2,
    },
    "prahran": {
        "postcode": "3181",
        "mode": "Tram 16 / Train via Richmond",
        "line": "Near Tram 16 (High St) or 2 stops via Richmond",
        "commute_mins": 15,
        "tier": 2,
    },
    "windsor": {
        "postcode": "3181",
        "mode": "Tram 16",
        "line": "Dandenong Rd / Glenferrie Rd Tram 16 to Hawthorn",
        "commute_mins": 16,
        "tier": 2,
    },
    "west melbourne": {
        "postcode": "3003",
        "mode": "Train (City Loop)",
        "line": "North Melbourne / Flagstaff -> Hawthorn",
        "commute_mins": 20,
        "tier": 2,
    },
    "carlton": {
        "postcode": "3053",
        "mode": "Tram 16 / Bus 200+609",
        "line": "Melbourne Uni Tram 16 direct to Hawthorn (Glenferrie)",
        "commute_mins": 25,
        "tier": 2,
    },
    # South-East Corridor (Pakenham/Cranbourne Line via Richmond)
    "clayton": {
        "postcode": "3168",
        "mode": "Train (Pakenham/Cranbourne Line)",
        "line": "Express to Richmond (18m) + 1-stop to Hawthorn (4m)",
        "commute_mins": 26,
        "tier": 2,
    },
    "clayton south": {
        "postcode": "3169",
        "mode": "Train via Richmond",
        "line": "Clayton Station / Westall corridor to Hawthorn",
        "commute_mins": 29,
        "tier": 2,
    },
}

# Domain / REA / Rent.com.au search suburb slugs (prioritizing inner-east & direct train/tram)
PRIORITY_SUBURB_SLUGS: List[str] = [
    "hawthorn-vic-3122",
    "hawthorn-east-vic-3123",
    "richmond-vic-3121",
    "camberwell-vic-3124",
    "kew-vic-3101",
    "burnley-vic-3121",
    "canterbury-vic-3126",
    "surrey-hills-vic-3127",
    "box-hill-vic-3128",
    "burwood-vic-3125",
    "ashburton-vic-3147",
    "malvern-vic-3144",
    "armadale-vic-3143",
    "toorak-vic-3142",
    "kooyong-vic-3144",
    "abbotsford-vic-3067",
    "south-yarra-vic-3141",
    "blackburn-vic-3130",
    "nunawading-vic-3131",
    "mitcham-vic-3132",
    "ringwood-vic-3134",
    "ringwood-east-vic-3135",
    "heathmont-vic-3135",
    "bayswater-vic-3153",
    "boronia-vic-3155",
    "ferntree-gully-vic-3156",
    "upper-ferntree-gully-vic-3156",
    "upwey-vic-3158",
    "tecoma-vic-3160",
    "belgrave-vic-3160",
    "croydon-vic-3136",
    "mooroolbark-vic-3138",
    "lilydale-vic-3140",
    "mont-albert-vic-3127",
    "clayton-vic-3168",
    "caulfield-north-vic-3161",
    "st-kilda-east-vic-3183",
    "east-melbourne-vic-3002",
    "melbourne-vic-3000",
]
