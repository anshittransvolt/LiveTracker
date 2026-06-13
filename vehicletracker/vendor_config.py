# ============================
# DYNAMIC VENDOR CONFIGURATION
# ============================
# This file provides completely configurable vendor settings for the battery dashboard
# NO MORE HARDCODING! All vendor settings are now fully dynamic and configurable.

# Vendor display name mappings - completely customizable
# If a vendor is not in this mapping, the system will automatically use 
# the first 2 uppercase letters of the vendor name as display name
VENDOR_DISPLAY_NAMES = {
    'intangles': 'IN',
    'iplt': 'IP',
    # Add more vendor display mappings as needed:
    # 'mahindra': 'MH',
    # 'tatamotors': 'TM',
    # 'ashokleyland': 'AL',
}

# Common vendor list for API discovery
# The system will try these vendors and automatically detect which ones have data
# API will return 404/empty for vendors that don't exist for a project
COMMON_VENDORS = ['intangles', 'iplt']

# Full fleet of 70 vehicles.
# Primary source is intangles; vehicles missing there fall back to iplt automatically.
KNOWN_FLEET = [
    'MH18BZ2689', 'MH18BZ2647', 'MH18BZ2690', 'MH18BZ2649', 'MH18BZ2648',
    'MH18BZ3370', 'MH18BZ3380', 'MH18BZ3346', 'MH18BZ3369', 'MH18BZ3374',
    'MH18BZ3378', 'MH18BZ3381', 'MH18BZ3344', 'MH18BZ3341', 'MH18BZ3196',
    'MH18BZ3392', 'MH18BZ3342', 'MH18BZ3376', 'MH18BZ3198', 'MP09AR9487',
    'MH18BZ3476', 'MH18BZ3384', 'MH18BZ3201', 'MH18BZ3389', 'MH18BZ3383',
    'MH18BZ3386', 'MH18BZ3345', 'MH18BZ3347', 'MH18BZ3382', 'MH18BZ3194',
    'MH18BZ3391', 'MH18BZ3426', 'MH18BZ3387', 'MH18BZ3343', 'MH18BZ3375',
    'MH18BZ3195', 'MH18BZ3368', 'MH18BZ3379', 'MH18BZ3390', 'MH18BZ3372',
    'MH18BZ3032', 'MH18BZ3112', 'MH18BZ3034', 'MH18BZ3028', 'MH18BZ3164',
    'MH18BZ2958', 'MH18BZ3036', 'MH18BZ3109', 'MH18BZ3161', 'MH18BZ3163',
    'MH18BZ2961', 'MH18BZ3024', 'MH18BZ2968', 'MH18BZ3160', 'MH18BZ3039',
    'MH18BZ3108', 'MH18BZ2962', 'MH18BZ3029', 'MH18BZ3038', 'MH18BZ3162',
    'MH18BZ2960', 'MH18BZ2963', 'MH18BZ3165', 'MH18BZ3110', 'MH18BZ3113',
    'MH18BZ2872', 'MH18BZ2871', 'MH18BZ2869', 'MH18BZ2873', 'MH18BZ2874',
]

# ============================
# ENVIRONMENT VARIABLE OVERRIDES
# ============================
# You can override these settings via environment variables:
#
# VENDOR_DISPLAY_NAMES='{"intangles": "IN", "iplt": "IP", "newvendor": "NV"}'
# COMMON_VENDORS='["intangles", "iplt", "newvendor"]'
#
# This allows for complete runtime configuration without code changes!

# ============================
# HOW IT WORKS
# ============================
# 1. System queries API for all vendors in COMMON_VENDORS list
# 2. Only vendors with actual data are shown in the UI
# 3. Multi-vendor features only appear when multiple vendors have data
# 4. Display names come from VENDOR_DISPLAY_NAMES or auto-generated
# 5. Everything is project and date-range aware - no static assumptions!