#!/usr/bin/env python3
"""
STAGE 2b -- targeted About-page crawl to recover owner first names.

Only touches the rows in stage3_qualified.csv that have a BLANK first_name.
Free. No API keys. ~10-20 min.

Reads  : stage3_qualified.csv
Writes : about_snippets.json   <- upload this back to Claude

Strategy: the owner's name almost never appears on a homepage. It lives on
/about or /our-team. v1 of stage 2 truncated that text away. This goes and
gets it properly, then keeps only the parts likely to contain a person.

Usage:  python3 stage2b_names.py 40    <- test on 40 first
        python3 stage2b_names.py       <- full run
"""
import csv, json, re, sys, time, threading, gzip, io
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urljoin, urlparse
import urllib.request, ssl

IN  = 'stage3_qualified.csv'
OUT = 'about_snippets.json'
WORKERS, TIMEOUT = 12, 15
UA = ('Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/126.0 Safari/537.36')

# paths worth guessing when the homepage gives us no usable links
GUESS = ['/about','/about-us','/about-us/','/our-team','/team','/meet-the-team',
         '/our-story','/who-we-are','/company','/staff','/leadership']

LINK_RE = re.compile(r'href=["\']([^"\']+)["\']', re.I)
ABOUT_HINT = re.compile(r'about|team|story|who-we-are|staff|leadership|founder|meet', re.I)
PERSON_HINT = re.compile(
    r'\b(owner|founder|co-founder|president|principal|proprietor|CEO|'
    r'started (?:the|this) (?:company|business)|family[- ]owned|family owned and operated|'
    r'meet (?:the|our)|our founder|was founded by|established by|'
    r'second[- ]generation|third[- ]generation)\b', re.I)

ctx = ssl.create_default_context(); ctx.check_hostname=False; ctx.verify_mode=ssl.CERT_NONE
lock = threading.Lock(); done=[0]

def get(url):
    req = urllib.request.Request(url, headers={'User-Agent':UA,
        'Accept':'text/html,application/xhtml+xml','Accept-Encoding':'gzip'})
    with urllib.request.urlopen(req, timeout=TIMEOUT, context=ctx) as r:
        raw = r.read(900_000)
        if r.headers.get('Content-Encoding')=='gzip':
            try: raw = gzip.GzipFile(fileobj=io.BytesIO(raw)).read()
            except Exception: pass
        return raw.decode('utf-8','ignore'), r.geturl()

def clean(html):
    h = re.sub(r'(?is)<(script|style|noscript|svg|head)[^>]*>.*?</\1>',' ',html)
    h = re.sub(r'(?is)<(h[1-6]|p|div|li|br)[^>]*>', ' \n', h)
    h = re.sub(r'(?s)<[^>]+>',' ',h)
    h = re.sub(r'&nbsp;?|&amp;|&#39;|&quot;|&[a-z]+;',' ',h)
    h = re.sub(r'[ \t]+',' ',h)
    return re.sub(r'\n\s*\n+','\n',h).strip()

def snippets(text, width=450):
    """Keep only windows around person-indicating phrases."""
    out=[]
    for m in PERSON_HINT.finditer(text):
        a=max(0,m.start()-width); b=min(len(text),m.end()+width)
        out.append(text[a:b])
        if len(out)>=6: break
    return out

def work(row):
    site = row['website'] or ''
    if not site.startswith('http'): site='https://'+site
    rec = {'email':row['email'],'company':row['company'],'website':site,
           'snippets':[], 'about_head':'', 'pages_hit':[]}
    # 1. homepage -> find real about links
    links=[]
    try:
        html, final = get(site)
        base = final
        for href in LINK_RE.findall(html):
            if not ABOUT_HINT.search(href): continue
            u = urljoin(base, href)
            if urlparse(u).netloc != urlparse(base).netloc: continue
            if u.rstrip('/')==base.rstrip('/'): continue
            if u not in links: links.append(u)
            if len(links)>=4: break
    except Exception:
        base = site
    # 2. add guessed paths
    for g in GUESS:
        u = urljoin(base, g)
        if u not in links: links.append(u)
    # 3. fetch, best-effort, stop once we have signal
    text_all=''
    for u in links[:8]:
        try:
            h,_ = get(u)
        except Exception:
            continue
        t = clean(h)
        if len(t) < 200: continue
        rec['pages_hit'].append(u)
        text_all += '\n' + t
        if not rec['about_head']: rec['about_head']=t[:1200]
        if len(snippets(text_all))>=3: break
    rec['snippets'] = snippets(text_all)[:6]
    with lock:
        done[0]+=1
        if done[0]%50==0: print(f'  {done[0]} processed', flush=True)
    return rec

def main():
    rows=[r for r in csv.DictReader(open(IN)) if not (r.get('first_name') or '').strip()]
    if len(sys.argv)>1: rows=rows[:int(sys.argv[1])]
    print(f'{len(rows)} rows with no owner name -- crawling About pages\n')
    t0=time.time()
    with ThreadPoolExecutor(WORKERS) as ex: res=list(ex.map(work,rows))
    keep=[r for r in res if r['snippets'] or r['about_head']]
    json.dump(keep, open(OUT,'w'), indent=1)
    hit=[r for r in res if r['snippets']]
    print(f'\ncrawled            {len(res)}')
    print(f'about page found   {sum(1 for r in res if r["pages_hit"])}')
    print(f'person-phrase hit  {len(hit)}   <- candidates for a name')
    print(f'written            {len(keep)} records -> {OUT}')
    print(f'elapsed {time.time()-t0:.0f}s')
    print('\nUpload about_snippets.json back to Claude.')

if __name__=='__main__': main()
