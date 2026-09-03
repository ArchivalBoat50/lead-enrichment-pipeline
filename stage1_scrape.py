"""
STAGE 1 - Scrape Google Maps via Apify.

Why Apify and not a homemade scraper: Google is actively hostile to Maps
scraping and maintaining it is not where your time should go. Pay-per-result,
no subscription.

Run with --synthetic to generate fake records and exercise the rest of the
pipeline without spending a credit.
"""

import argparse
import json
import os
import random
import time

import requests

import config

APIFY_ACTOR = "compass~crawler-google-places"
APIFY_BASE = "https://api.apify.com/v2"


def run_one_metro(token: str, metro: str) -> list[dict]:
    """
    One Apify run per metro. The actor's UI says 'use only one location per
    run', and locationQuery is the field the console sets - so this mirrors
    exactly what a manual console run does, which is the configuration we
    verified against real output.
    """
    payload = {
        "searchStringsArray": config.SEARCH_TERMS,
        "locationQuery": metro,
        "maxCrawledPlacesPerSearch": config.PLACES_PER_TERM,
        "language": "en",
        "skipClosedPlaces": True,
    }

    run = requests.post(
        f"{APIFY_BASE}/acts/{APIFY_ACTOR}/runs",
        params={"token": token}, json=payload, timeout=30,
    )
    run.raise_for_status()
    data = run.json()["data"]
    run_id, dataset_id = data["id"], data["defaultDatasetId"]

    while True:
        time.sleep(15)
        status = requests.get(
            f"{APIFY_BASE}/actor-runs/{run_id}", params={"token": token}, timeout=30
        ).json()["data"]["status"]
        if status in ("SUCCEEDED", "FAILED", "ABORTED", "TIMED-OUT"):
            break

    if status != "SUCCEEDED":
        print(f"  ! {metro}: run ended {status} - skipping")
        return []

    items = requests.get(
        f"{APIFY_BASE}/datasets/{dataset_id}/items",
        params={"token": token, "format": "json"}, timeout=180,
    ).json()

    return [normalize_apify(i, metro) for i in items]


def scrape_apify(token: str, metros: list[str]) -> list[dict]:
    per_metro = len(config.SEARCH_TERMS) * config.PLACES_PER_TERM
    total = per_metro * len(metros)
    print(f"[stage1] {len(metros)} metros x {len(config.SEARCH_TERMS)} terms "
          f"x {config.PLACES_PER_TERM} = ~{total} places (~${total * 0.004:.2f})")

    all_rows = []
    for i, metro in enumerate(metros, 1):
        print(f"[stage1] ({i}/{len(metros)}) {metro} ...", flush=True)
        rows = run_one_metro(token, metro)
        kept = apply_filters(rows)
        print(f"           {len(rows)} raw -> {len(kept)} pass "
              f"({len(kept)/max(1,len(rows))*100:.1f}%)")
        all_rows.extend(rows)
        # Checkpoint after every metro. Runs take minutes each; losing an
        # hour of scraping to one crashed request would be avoidable waste.
        json.dump(all_rows, open("stage1_checkpoint.json", "w"))

    return all_rows


STATE_ABBR = {
    "Texas": "TX", "Georgia": "GA", "Arizona": "AZ", "Colorado": "CO",
    "Florida": "FL", "North Carolina": "NC", "Tennessee": "TN",
}


def normalize_apify(item: dict, fallback_metro: str = "") -> dict:
    """
    Field names verified against a real run (compass/crawler-google-places,
    Aug 2026).

    Two real-data quirks handled here:
      - `state` comes back as a full name ("Texas"), not an abbreviation.
      - ~37% of records are service-area businesses with NO address at all:
        city, state, street and address are all None. These are legitimate
        contractors who hide their address on Maps, not junk - many have
        websites and good review counts. Fall back to the metro the run
        targeted rather than dropping them.
    """
    city = item.get("city")
    state = item.get("state")
    if state and len(state) > 2:
        state = STATE_ABBR.get(state, state)
    if not city and fallback_metro:
        city, _, st = fallback_metro.partition(", ")
        state = state or st

    return {
        "company": item.get("title"),
        "domain": clean_domain(item.get("website")),
        "phone": item.get("phone"),
        "city": city,
        "state": state,
        "review_count": item.get("reviewsCount") or 0,
        "rating": item.get("totalScore"),
        "category": item.get("categoryName"),
        "place_id": item.get("placeId"),
        "permanently_closed": bool(item.get("permanentlyClosed")),
    }


def clean_domain(url):
    if not url:
        return None
    d = url.split("//")[-1].split("/")[0].lower()
    return d[4:] if d.startswith("www.") else d


def scrape_synthetic(n: int = 200) -> list[dict]:
    """Fake records shaped exactly like real ones, for dry runs."""
    random.seed(42)
    stems = ["Summit", "Ironwood", "Cardinal", "Bluebird", "Granite", "Harbor",
             "Northstar", "Copper Creek", "Redline", "Vantage", "Oakfield", "Trueline"]
    kinds = ["Remodeling", "Home Renovations", "Design Build", "Kitchen & Bath",
             "Contracting", "Renovation Co"]
    out = []
    for i in range(n):
        stem = random.choice(stems)
        kind = random.choice(kinds)
        company = f"{stem} {kind}"
        metro = random.choice(config.METROS)
        city, state = metro.split(", ")
        # ~12% have no website at all - they get dropped by the filter below.
        has_site = random.random() > 0.12
        slug = (stem + kind.split()[0]).lower().replace(" ", "")
        out.append({
            "company": company,
            "domain": f"{slug}{i}.com" if has_site else None,
            "phone": f"({random.randint(200,989)}) 555-{random.randint(1000,9999)}",
            "city": city,
            "state": state,
            "review_count": random.choice([8, 22, 47, 51, 63, 88, 140, 210, 355]),
            "rating": round(random.uniform(3.6, 5.0), 1),
        })
    return out


def apply_filters(rows: list[dict]) -> list[dict]:
    """
    Scrape-time filters. Every downstream stage costs money or time, so
    killing junk here is the cheapest filtering that exists.

    Review count is a proxy for job volume, which is a proxy for database
    size - the only thing DBR actually needs.
    """
    kept, seen = [], set()
    for r in rows:
        pid = r.get("place_id")
        if pid and pid in seen:      # same business surfaces on several terms
            continue
        if r.get("permanently_closed"):
            continue
        if config.REQUIRE_WEBSITE and not r.get("domain"):
            continue
        if config.REQUIRE_PHONE and not r.get("phone"):
            continue
        if (r.get("review_count") or 0) < config.MIN_REVIEWS:
            continue
        cat = r.get("category")
        if cat and cat not in config.ALLOWED_CATEGORIES:
            continue
        if pid:
            seen.add(pid)
        kept.append(r)
    return kept


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--synthetic", action="store_true", help="fake data, no API calls")
    ap.add_argument("--n", type=int, default=200, help="synthetic record count")
    ap.add_argument("--metros", default="", help="comma-separated subset, e.g. 'Houston, TX'")
    ap.add_argument("--skip", default="", help="comma-separated metros to skip, e.g. Dallas")
    ap.add_argument("--out", default="stage1_raw.json")
    args = ap.parse_args()

    if args.synthetic:
        rows = scrape_synthetic(args.n)
        print(f"[stage1] {len(rows)} synthetic records")
    else:
        token = os.environ.get("APIFY_TOKEN")
        if not token:
            raise SystemExit("APIFY_TOKEN not set")

        metros = [m.strip() for m in args.metros.split(";") if m.strip()] if args.metros else list(config.METROS)
        if args.skip:
            skip = [s.strip().lower() for s in args.skip.split(",")]
            metros = [m for m in metros if not any(s in m.lower() for s in skip)]

        rows = scrape_apify(token, metros)
        print(f"[stage1] {len(rows)} scraped across {len(metros)} metros")

    kept = apply_filters(rows)
    dropped = len(rows) - len(kept)
    print(f"[stage1] filters: kept {len(kept)}, dropped {dropped} "
          f"({dropped/max(1,len(rows))*100:.0f}%)")

    with open(args.out, "w") as f:
        json.dump(kept, f, indent=2)
    print(f"[stage1] wrote {args.out}")
    print("[stage1] next: python3 stage2_fetch.py")


if __name__ == "__main__":
    main()
