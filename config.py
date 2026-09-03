"""
Stage 1 configuration.

Values are the ones the measured 14-metro run used (Aug 2026). Changing any of
them invalidates the yield figures quoted in the README.
"""
import os

# ---------------------------------------------------------------- credentials
# Never hardcode. Stage 1 is the only stage that costs money, and it reads the
# token from the environment so a committed config can never spend credit.
#   export APIFY_TOKEN=apify_api_xxxxx
APIFY_TOKEN = os.environ.get("APIFY_TOKEN", "")

# ---------------------------------------------------------------- scrape shape
# One Apify run per metro, three terms per run. The actor's own guidance is one
# location per run, and locationQuery is the field its console sets.
SEARCH_TERMS = ["remodeling", "kitchen remodel", "bathroom remodel"]

# Depth cap per term. Measured on a 900-deep Dallas run: results ranked 1-50
# survived stage 1 at 23.3%, ranks 250-300 at 10.0%, while every place costs the
# same $0.004. The last hundred per term yield half what the first fifty do, so
# width beats depth -- 200/term across 14 metros returned 70 survivors per
# dollar against 58 for Dallas at 300/term.
PLACES_PER_TERM = 200

# The 14 metros actually scraped. Columbus and Indianapolis were specced but
# dropped when Apify credit ran out at ~$26.30; re-add them only if the list
# comes up short.
METROS = [
    "Dallas, TX",
    "Houston, TX",
    "Atlanta, GA",
    "Phoenix, AZ",
    "Denver, CO",
    "Tampa, FL",
    "Charlotte, NC",
    "Nashville, TN",
    "Orlando, FL",
    "San Antonio, TX",
    "Raleigh, NC",
    "Las Vegas, NV",
    "Jacksonville, FL",
    "Kansas City, MO",
]

# ---------------------------------------------------------------- filters
REQUIRE_WEBSITE = True   # no site means no stage 2 and no email to find
REQUIRE_PHONE = True

# Dominant filter -- it removed 645 of 900 on the Dallas run. Set to 20 after a
# real run showed the median review count is ~10 and a threshold of 50 left only
# 13% surviving, pushing the scrape bill for 1,000 finals to ~$160. Median among
# survivors is 38, so 20 sits about right. Lowering it to 10 would take the same
# already-purchased datasets from 1,349 unique businesses to 2,027.
MIN_REVIEWS = 20

# Google Maps matches on category and page text, not intent -- a roofer whose
# site mentions bathroom remodeling matches "bathroom remodel". That cannot be
# filtered at query level, so precision is applied here instead. This list is
# the set of categories that actually survived the measured run; it excludes the
# roofers, handymen, plumbers, painters, pool contractors, cabinet stores and
# HVAC firms that Maps drags in.
ALLOWED_CATEGORIES = {
    "Kitchen remodeler",
    "Bathroom remodeler",
    "General contractor",
    "Remodeler",
    "Construction company",
    "Contractor",
    "Flooring contractor",
    "Cabinet maker",
    "Tile contractor",
    "Countertop contractor",
    "Home builder",
    "Custom home builder",
    "Carpenter",
    "Interior construction contractor",
}
