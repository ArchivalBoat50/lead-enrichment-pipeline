"""
Settings for stage1_scrape.py.

RECONSTRUCTED FILE. The original config.py was not committed. Every name and
type below is derived directly from how stage1_scrape.py reads it -- those are
exact. The VALUES are placeholders and are not the values the measured run
used; that information is not recoverable from the code. Replace all of them
before running against the real API.
"""

# Google Maps search strings, passed to the Apify actor as searchStringsArray.
# PLACEHOLDER VALUES.
SEARCH_TERMS = [
    "home remodeling contractor",
    "kitchen and bath remodeler",
    "design build firm",
    "home renovation company",
]

# maxCrawledPlacesPerSearch -- cap per search term, per metro.
# PLACEHOLDER VALUE.
#
# Note: stage1 budgets cost as len(SEARCH_TERMS) * PLACES_PER_TERM * $0.004
# per metro. My run notes describe a single metro as "~600 places, ~$2.40",
# so in the real run the product of these two numbers was about 600. How that
# 600 was split between term count and per-term cap is not recoverable. [CONFIRM]
PLACES_PER_TERM = 150

# One Apify run is issued per entry, as "City, ST". Used both as locationQuery
# and as the fallback for records that come back with no address at all.
# PLACEHOLDER VALUES -- my run notes reference fifteen metros; the states that
# appear in stage1's STATE_ABBR map are TX, GA, AZ, CO, FL, NC and TN, which
# suggests but does not confirm the real list. [CONFIRM]
METROS = [
    "Houston, TX",
    "Dallas, TX",
    "Atlanta, GA",
    "Phoenix, AZ",
    "Denver, CO",
]

# --- Scrape-time filters, applied in apply_filters() ---

# Drop rows with no website. Stage 2 has nothing to fetch without one.
REQUIRE_WEBSITE = True

# Drop rows with no phone number.
REQUIRE_PHONE = True

# Minimum Google review count. Used as a proxy for job volume.
# PLACEHOLDER VALUE.
MIN_REVIEWS = 15

# Google Maps categoryName values to keep. A row whose category is set and is
# NOT in this collection is dropped; a row with no category at all is kept.
# PLACEHOLDER VALUES.
ALLOWED_CATEGORIES = {
    "General contractor",
    "Home builder",
    "Bathroom remodeler",
    "Kitchen remodeler",
    "Remodeler",
    "Construction company",
}
