# Lead enrichment pipeline

Buying a B2B lead list gets you rows, not reachable people. A large share of
any purchased or scraped list is dead on arrival: the business has no website,
the site no longer resolves, or there is no email address anywhere on it. The
expensive way to find that out is to hand the whole list to a paid enrichment
or verification vendor and pay per record to learn that most records were
worthless. This pipeline inverts that order. It spends money once, up front,
on getting a clean list of businesses out of Google Maps, then runs a free
HTTP pass over every domain to throw away everything unreachable and to pull
a contact address off the site itself — and only what survives that free pass
is ever handed to a paid per-email verification step. In a measured run, the
free pass cut 1,349 businesses down to 834 with a usable email before a cent
of verification budget was spent.

## Status

This repository is incomplete, and it is worth being upfront about what is
here and what is not.

**Runs today**

- `stage1_scrape.py` — Google Maps scrape via the Apify API, plus a
  `--synthetic` mode that generates fake records so the rest of the pipeline
  can be exercised without spending credit.
- `stage2.py` — the free homepage/contact-page enrichment pass. This is the
  stage the measured numbers below come from.
- `stage2b_names.py` — targeted About-page crawl to recover owner first names
  for rows that don't have one.

**Missing**

- **`config.py` is not in the tree.** `stage1_scrape.py` imports it and reads
  seven settings from it. I have reconstructed it as `config.py` with
  placeholder values — every field name and type is derivable unambiguously
  from how stage 1 uses it, but the actual values I ran with are not
  recoverable from the code, so they are marked as placeholders in that file.
- **`stage3_extract.py` and `stage4_verify_load.py` do not exist here.**
  `RUN.md` (my own run notes, not committed) calls for them: stage 3 turns the
  scraped page text into structured fields via an LLM API, stage 4 runs paid
  per-email verification and writes the final CSV. Neither is included.
- **`merge_exports.py`**, referenced in my run notes for folding in a metro
  already downloaded as a file, is also not here.

**Known interface gaps between the files that are here**

- `stage1_scrape.py` writes `stage1_raw.json`; `stage2.py` reads
  `stage1_survivors.json`. Something renamed or merged that file between the
  two stages and it is not in the repo. [CONFIRM]
- `stage1_scrape.py`'s `normalize_apify()` emits a `domain` key but no
  `website` key, and `stage2.py`'s `work()` reads `rec['website']`. As
  committed, stage 2 would raise `KeyError` on stage 1's output. This is real
  and I have not papered over it.
- `stage1_scrape.py` prints `next: python3 stage2_fetch.py`; the file is named
  `stage2.py`.
- My run notes say to lower `FETCH_WORKERS` "in config" if sites hang, but
  `stage2.py` hardcodes `WORKERS = 12` and does not import `config` at all.

Treat this as a working pipeline captured mid-refactor, not a packaged tool.

## Architecture

Four stages, deliberately ordered cheapest-filter-first.

```
  metro list + search terms
            |
   [ STAGE 1 ]  stage1_scrape.py          COST: Apify credit, per result
   Apify Google Maps actor, one run       (~$0.004/place as budgeted in
   per metro. Dedupe by placeId, drop     the script) [CONFIRM]
   closed / no-website / no-phone /
   low-review / off-category rows.
   Checkpoints after every metro.
            |
            v  stage1_survivors.json
            |
   [ STAGE 2 ]  stage2.py                 COST: none. Plain HTTP.
   Fetch each homepage. Retry http://
   and www. variants. Follow up to 3
   contact/about links found on the
   page. Harvest emails, including
   Cloudflare data-cfemail. Flag Meta
   Pixel. Capture body text for later
   extraction.
            |
            +---> dead sites dropped here, for free
            |
            v  stage2_enriched.json + stage2_report.txt
            |
   [ STAGE 3 ]  stage3_extract.py         COST: LLM tokens [CONFIRM]
   NOT IN THIS REPO. Turns the captured
   page text into structured fields
   (ticket band, service lines, years
   operating, residential/commercial,
   owner first name).
            |
            v  stage3_qualified.csv
            |
   [ STAGE 2b ] stage2b_names.py          COST: none. Plain HTTP.
   Second pass over only the rows whose
   first_name is blank. Crawls /about,
   /our-team etc. and keeps text windows
   around owner-indicating phrases.
            |
            v  about_snippets.json
            |
   [ STAGE 4 ]  stage4_verify_load.py     COST: per email verified
   NOT IN THIS REPO. Paid mailbox
   verification, then final CSV.
```

The cost shape is the whole point: the only two paid steps sit at the very
start and the very end, and the free stage in the middle exists to shrink the
input to the expensive one at the end.

## Design decisions

**Apify instead of a homemade Google Maps scraper.** From the stage 1
docstring: "Google is actively hostile to Maps scraping and maintaining it is
not where your time should go. Pay-per-result, no subscription." Writing the
scraper is the easy day; keeping it alive through layout and anti-bot changes
is the expensive year. Paying per result also means the cost line is a
function of output, not a monthly subscription that bills whether or not the
project is running.

**One Apify run per metro, not one big run.** The `run_one_metro` docstring
gives the reasoning directly: "The actor's UI says 'use only one location per
run', and `locationQuery` is the field the console sets — so this mirrors
exactly what a manual console run does, which is the configuration we verified
against real output." The point is that the API call is made to match a
configuration that was actually observed producing correct data in the vendor
console, rather than a plausible-looking multi-location payload that has never
been checked against real output. Per-metro runs also make the failure unit
small: a run that ends `FAILED` or `ABORTED` costs one metro and the loop
continues.

**Checkpoint after every metro.** From the code comment: "Runs take minutes
each; losing an hour of scraping to one crashed request would be avoidable
waste." The checkpoint is a dumb full rewrite of `stage1_checkpoint.json` after
each metro. It is not clever and it does not need to be — the write is
milliseconds against a per-metro run measured in minutes, and it converts a
crash from "lose the batch" into "lose one metro."

**The free stage 2 pass runs before buying more scrape credit.** Two of the
biggest unknowns in the whole plan are how many scraped businesses have a site
that actually resolves and how many expose an email at all. Both are
assumptions until measured, and both are measurable for free. Running stage 2
on the first batch turns them into numbers, and if the numbers are much worse
than assumed, more metros do not fix it — the stage 1 filters do. Buying more
scrape credit before that measurement risks buying more of a thing that
doesn't convert.

**Meta Pixel was demoted from a filter to a priority flag in v2.** In v1,
having a Meta Pixel on the site was a qualification filter. The measured
numbers explain the demotion: of 834 businesses with an email, only 107 had a
pixel. Keeping it as a filter would have discarded roughly seven of every eight
otherwise-good leads on a signal that only indicates a business already runs
paid social. In v2 it is carried as `has_pixel` and used to split the list into
send batches — pixel first — which keeps the ordering value without paying the
volume cost. The stage 2 report labels this explicitly: "priority split (not a
filter — nothing dropped)".

**Cloudflare `data-cfemail` obfuscation had to be decoded.** Cloudflare's Email
Address Obfuscation feature rewrites `mailto:` addresses out of the HTML and
replaces them with a placeholder element carrying a `data-cfemail="..."`
attribute — a hex string that a small piece of Cloudflare JavaScript decodes in
the browser. A regex scan of the raw HTML sees no email at all, which is
exactly the point of the feature. v1 of stage 2 missed these entirely. The
encoding is trivial once you know it: the hex string decodes to bytes, the
first byte is an XOR key, and every remaining byte XORed with that key gives
the ASCII of the address. That is the whole of `decode_cf()`. Skipping it means
silently writing off every lead whose host happens to have one Cloudflare
toggle switched on — a systematic loss, not a random one.

**http:// and www. variants are retried before calling a site dead.** A single
failed `https://example.com` request is weak evidence of a dead business.
Small contractor sites are routinely served only over http, only on the `www.`
host, or with a certificate that doesn't cover the bare domain. `try_variants`
tries the given URL, the www-toggled host, and both over http before returning
"dead". Since "dead" is a permanent drop from a list that cost money to build,
the asymmetry justifies three extra cheap requests. (Relatedly,
`ssl.CERT_NONE` is set: a broken certificate is a fact about the host's ops,
not a reason to lose the lead. That is a defensible tradeoff here because the
pages are only being read for public contact text, never authenticated
against.)

**Owner names come from /about, not the homepage.** From the stage 2b
docstring: "the owner's name almost never appears on a homepage. It lives on
/about or /our-team. v1 of stage 2 truncated that text away." Stage 2 caps
homepage text at 4,000 characters and each followed page at 2,000, which is
right for finding an email and wrong for finding a person. Stage 2b is a
separate, narrower pass: it runs only over rows whose `first_name` is blank,
follows about/team links found on the page and then falls back to a list of
guessed paths, and keeps only ±450-character windows around owner-indicating
phrases ("owner", "founder", "family owned", "was founded by",
"second-generation", and similar) rather than the whole page. Narrowing before
handing text to the extraction step is both cheaper and more accurate than
sending whole pages.

**The thread pool is capped at 12 workers.** Both crawling stages use
`ThreadPoolExecutor(12)` with a 15-second timeout. The code does not state a
reason, so this is my reconstruction [CONFIRM]: the work is almost entirely
network wait, so threads are the right primitive and the useful range is well
above one; but every request in a batch goes to a *different* small business
host, many of them on shared hosting, so the ceiling exists to stay
unremarkable rather than to stay under any one site's rate limit. Twelve
workers against a 15-second timeout bounds the worst case at a modest, steady
request rate, and the measured throughput was acceptable without going higher:
1,349 sites in 675 seconds, about two sites per second end to end. My run notes
list "sites hanging" as a known failure mode with "lower the worker count" as
the fix, which is consistent with 12 being an empirically-settled ceiling
rather than a computed one.

## Measured results

These are real aggregate numbers from two runs of `stage2.py` over two
segments of one campaign [CONFIRM], read from the report files the script
writes itself. No per-record data appears here or anywhere in this repo.

Segment 1 — source: `stage2_report.txt`

| | count | rate |
|---|---|---|
| input | 1349 | |
| site reachable | 1105 | 81.9% |
| dead | 244 | |
| **email found** | **834** | **61.8%** |
| email on own domain | 513 | 61.5% of emails found |
| has pixel (batch 1) | 107 | |
| no pixel (batch 2) | 727 | |
| elapsed | 675s | |

Segment 2 — source: `seg2_stage2_report.txt`

| | count | rate |
|---|---|---|
| input | 681 | |
| site reachable | 599 | 88.0% |
| dead | 82 | |
| **email found** | **429** | **63.0%** |
| email on own domain | 273 | 63.6% of emails found |
| has pixel (batch 1) | 34 | |
| no pixel (batch 2) | 395 | |
| elapsed | 324s | |

Reading these: across both segments that is 2,030 businesses in and 1,263 with
a usable email out (sums of the two reports above), meaning about 38% of what
stage 1 produced was removed for free, before the paid verification step, by a
pass that cost nothing but 999 seconds of wall clock. The two segments agree
closely on the email-discovery rate (61.8% and 63.0%) despite different
reachability (81.9% vs 88.0%), which is the sort of stability that makes the
number usable for forecasting the next batch.

Note that the segment-2 run used a copy of `stage2.py` differing only in its
three input/output filenames — same logic, same thresholds.

## Stack

- Python 3 standard library for the crawling stages: `urllib.request`, `ssl`,
  `gzip`, `re`, `csv`, `json`, `concurrent.futures.ThreadPoolExecutor`. Stage 2
  and 2b have no third-party dependencies at all.
- `requests` in stage 1, for the Apify REST API.
- Apify (`compass~crawler-google-places` actor) for the Google Maps scrape.
- Regex-based HTML handling rather than a parser — deliberate for stage 2,
  since the targets are emails, `data-cfemail` attributes, `href`s and pixel
  script tags, all of which survive malformed markup better than a DOM walk
  does. It is the wrong choice for anything structural.
- A downstream LLM API for the structured-extraction stage, and a per-email
  verification service for the final stage — neither of those stages is in
  this repo.

## Running it locally

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install requests
cp .env.example .env      # then fill in your own values
```

Fill in `config.py` — it ships with placeholder values that will not produce a
useful list as-is.

**Dry run with no API calls and no cost:**

```bash
python3 stage1_scrape.py --synthetic --n 200 --out stage1_raw.json
```

This generates records shaped like real ones (invented company names built
from a fixed word list, `555-` phone numbers, made-up domains) so the filter
logic and the file plumbing can be exercised for free.

**Real scrape, one metro first:**

```bash
export APIFY_TOKEN=your_token_here
python3 stage1_scrape.py --metros "Springfield, ZZ"
```

Test on one metro before committing to the full list; it confirms the API path
and the field names before spending on the rest. Then:

```bash
python3 stage1_scrape.py --skip "Springfield"
```

which loops the remaining metros, one Apify run each, checkpointing to
`stage1_checkpoint.json` after every one.

**Stage 2 — free, and the one worth running before buying more credit:**

```bash
python3 stage2.py 50     # smoke test on 50 rows first
python3 stage2.py        # full run
```

Writes `stage2_enriched.json` and `stage2_report.txt`. A record in the output
looks like this — entirely invented, for shape only:

```json
{
  "company": "Northgate Design Build",
  "domain": "northgate-example.test",
  "website": "https://northgate-example.test",
  "city": "Springfield",
  "state": "ZZ",
  "review_count": 64,
  "rating": 4.7,
  "status": "ok",
  "pages": 2,
  "best_email": "info@northgate-example.test",
  "email_on_domain": true,
  "emails": ["info@northgate-example.test"],
  "has_pixel": false,
  "facebook": "",
  "body_text": "..."
}
```

**Stage 2b — name recovery:**

```bash
python3 stage2b_names.py 40   # smoke test
python3 stage2b_names.py      # full run
```

Reads `stage3_qualified.csv` (columns: `email, first_name, company, city,
state, metro, phone, website, reviews, rating, category, ticket_band,
service_lines, years_operating, res_comm, has_pixel, email_on_domain`) and
processes only rows where `first_name` is blank. Note that this file is
produced by the stage 3 script, which is not in this repo — so stage 2b cannot
currently be run end-to-end from a fresh checkout.

Every output file this pipeline writes is excluded by `.gitignore`. That is
deliberate; see below.

## Known limitations and what I'd do next

**Completeness**

- Write `stage3_extract.py` and `stage4_verify_load.py`, the two stages my run
  notes call for and this repo does not contain.
- Fix the `domain`/`website` key mismatch between stage 1's output and stage
  2's input, and reconcile the `stage1_raw.json` / `stage1_survivors.json`
  filename gap, so the stages actually chain from a clean checkout.
- Move `WORKERS`/`TIMEOUT` in stages 2 and 2b into `config.py` as
  `FETCH_WORKERS`, which is where my own run notes already assume they live.

**Engineering**

- There are no tests. The tractable ones are the pure functions:
  `decode_cf()` against a known hex string, `clean_domain()`, `rank()`'s
  ordering rules, and `apply_filters()` against fixture records. The scraper
  itself needs a different approach — see the interview notes for how I'd
  handle a target that changes underneath the code.
- No retry-with-backoff or per-host politeness. Failures are swallowed with a
  bare `except Exception: continue`, which is why a site that is merely slow is
  indistinguishable in the output from a site that is genuinely gone. A
  structured failure reason per row would make the 244 "dead" figure far more
  actionable.
- `ssl.CERT_NONE` disables certificate verification globally in these scripts.
  Acceptable for reading public marketing pages, and it should never be copied
  into code that sends anything.
- Regex email harvesting picks up whatever the page exposes. The `JUNK` and
  `ROLE_GOOD` lists are hand-tuned heuristics and will drift as website
  builders change their boilerplate.
- The Apify actor's field names are a hard dependency. When they drift,
  `normalize_apify()` is the single place that breaks — that concentration was
  intentional, but nothing currently detects the drift automatically.

**Data protection**

This pipeline collects and stores business contact data, and some of it —
an owner's first name attached to an email address — is personal data under
GDPR regardless of the fact that it was published on a public website.
Operating this for real outreach carries obligations I would want handled
before any send, not after:

- **CAN-SPAM** (US): accurate From and subject lines, a physical postal
  address in every message, a working opt-out honored promptly, and no
  harvesting-based sending to addresses obtained without regard for the
  above.
- **GDPR / UK GDPR** (any EU or UK recipient): a documented lawful basis —
  legitimate interest is the usual one for B2B prospecting, and it requires
  an actual balancing assessment, not an assertion — plus notice at first
  contact of who is processing the data and where it came from, and a real
  path for erasure and objection requests. Scraped-from-public-web is not by
  itself a lawful basis.
- **Operationally**: a suppression list that survives across runs, retention
  limits on the enriched JSON rather than keeping it indefinitely, and no
  scraped data in the repository, ever.

The last point is enforced here rather than just stated: `.gitignore` excludes
every output extension this pipeline produces, so a stray `git add .` cannot
commit a lead file. The ~1,700 real business records this code processed are
not in this repository and no example in this README or in any file here is
taken from them — every sample value above is invented.
