#!/usr/bin/env python3
"""
STAGE 2 v2 -- homepage enrichment. Free, no API keys.

Changes from v1:
  * Meta Pixel is now a PRIORITY FLAG, not a filter. Nothing is dropped for it.
  * Decodes Cloudflare-obfuscated emails (data-cfemail) -- v1 missed these entirely.
  * Reads real contact/about links off the homepage instead of guessing paths.
  * Retries http:// and www. variants before calling a site dead.
  * Also grabs the Facebook page URL.

Input : stage1_survivors.json
Output: stage2_enriched.json + stage2_report.txt

Usage:  python3 stage2.py 50     <- test first
        python3 stage2.py        <- full run
"""
import json, re, sys, time, threading, gzip, io
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urljoin, urlparse
import urllib.request, ssl

IN, OUT, RPT = 'stage1_survivors.json', 'stage2_enriched.json', 'stage2_report.txt'
WORKERS, TIMEOUT = 12, 15
UA = ('Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/126.0 Safari/537.36')

EMAIL_RE = re.compile(r'[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}')
CFEMAIL_RE = re.compile(r'data-cfemail=["\']([0-9a-fA-F]+)["\']')
FB_RE = re.compile(r'https?://(?:www\.)?facebook\.com/[A-Za-z0-9._\-/]+')
LINK_RE = re.compile(r'href=["\']([^"\']+)["\']', re.I)
CONTACT_HINT = re.compile(r'contact|about|team|estimate|quote|get-a-quote', re.I)

JUNK = ('sentry.io','wixpress.com','example.com','godaddy.com','squarespace.com',
        'yourdomain','domain.com','email.com','.png','.jpg','.jpeg','.gif','.svg',
        '.webp','.css','.js','core-js','react','npm','schema.org','sentry-next',
        'godaddysites','wordpress.org','gravatar','w3.org')
ROLE_GOOD = ('info','contact','office','hello','admin','sales','service','team',
             'estimating','estimates','scheduling','inquiries')

ctx = ssl.create_default_context(); ctx.check_hostname=False; ctx.verify_mode=ssl.CERT_NONE
lock = threading.Lock(); done=[0]

def decode_cf(hexstr):
    """Cloudflare email obfuscation: first byte is the XOR key."""
    try:
        b = bytes.fromhex(hexstr); k = b[0]
        return ''.join(chr(c ^ k) for c in b[1:])
    except Exception:
        return ''

def get(url):
    req = urllib.request.Request(url, headers={'User-Agent':UA,
        'Accept':'text/html,application/xhtml+xml','Accept-Encoding':'gzip',
        'Accept-Language':'en-US,en;q=0.9'})
    with urllib.request.urlopen(req, timeout=TIMEOUT, context=ctx) as r:
        raw = r.read(700_000)
        if r.headers.get('Content-Encoding')=='gzip':
            try: raw = gzip.GzipFile(fileobj=io.BytesIO(raw)).read()
            except Exception: pass
        return raw.decode('utf-8','ignore'), r.geturl()

def try_variants(site):
    """Return (html, final_url) or (None, None). Tries https/http and www toggle."""
    if not site.startswith('http'): site = 'https://' + site
    p = urlparse(site)
    host = p.netloc
    alt = host[4:] if host.startswith('www.') else 'www.'+host
    cands = [site,
             f'{p.scheme}://{alt}{p.path or "/"}',
             f'http://{host}{p.path or "/"}',
             f'http://{alt}{p.path or "/"}']
    for c in dict.fromkeys(cands):
        try:
            return get(c)
        except Exception:
            continue
    return None, None

def clean_text(html):
    h = re.sub(r'(?is)<(script|style|noscript|svg)[^>]*>.*?</\1>',' ',html)
    h = re.sub(r'(?s)<[^>]+>',' ',h)
    h = re.sub(r'&nbsp;?|&[a-z]+;',' ',h)
    return re.sub(r'\s+',' ',h).strip()

def harvest_emails(html):
    out = set(EMAIL_RE.findall(html))
    for hx in CFEMAIL_RE.findall(html):
        d = decode_cf(hx)
        if '@' in d: out.add(d)
    return out

def rank(emails, domain):
    ok=[]
    for e in emails:
        e=e.strip('.').lower()
        if any(j in e for j in JUNK) or len(e)>60: continue
        if '@' not in e: continue
        ok.append(e)
    return sorted(set(ok), key=lambda e:(
        0 if e.split('@')[1]==domain else 1,
        0 if e.split('@')[0] in ROLE_GOOD else 1,
        len(e)))

def work(rec):
    o = dict(rec)
    o.update(emails=[], best_email='', email_on_domain=False, has_pixel=False,
             facebook='', body_text='', pages=0, status='dead')
    html, final = try_variants(rec['website'])
    if html is None:
        with lock: done[0]+=1
        return o
    o['status']='ok'; o['pages']=1
    blob = html
    texts = [clean_text(html)[:4000]]

    # follow up to 3 real contact/about links found on the homepage
    seen=set()
    for href in LINK_RE.findall(html):
        if len(seen)>=3: break
        if not CONTACT_HINT.search(href): continue
        u = urljoin(final, href)
        if urlparse(u).netloc != urlparse(final).netloc: continue
        if u in seen or u==final: continue
        seen.add(u)
        try:
            h2,_ = get(u); blob += h2; o['pages']+=1
            texts.append(clean_text(h2)[:2000])
        except Exception: pass

    o['has_pixel'] = ('connect.facebook.net' in blob) or ('fbq(' in blob)
    fb = FB_RE.findall(blob)
    o['facebook'] = next((f for f in fb if not re.search(r'/(sharer|plugins|tr\?)',f)), '')
    ranked = rank(harvest_emails(blob), rec['domain'])
    o['emails']=ranked[:5]
    if ranked:
        o['best_email']=ranked[0]
        o['email_on_domain'] = ranked[0].split('@')[1]==rec['domain']
    o['body_text']=' '.join(texts)[:6000]
    with lock:
        done[0]+=1
        if done[0]%50==0: print(f'  {done[0]} processed', flush=True)
    return o

def main():
    data=json.load(open(IN))
    n_all=len(data)
    if len(sys.argv)>1: data=data[:int(sys.argv[1])]
    print(f'Stage 2 v2: {len(data)} sites, {WORKERS} workers\n')
    t0=time.time()
    with ThreadPoolExecutor(WORKERS) as ex: res=list(ex.map(work,data))
    json.dump(res,open(OUT,'w'),indent=1)

    live=[r for r in res if r['status']=='ok']
    em  =[r for r in live if r['best_email']]
    ond =[r for r in em if r['email_on_domain']]
    pix =[r for r in em if r['has_pixel']]
    rate=len(em)/len(data)

    L=[];A=L.append
    A('='*54); A('STAGE 2 v2 REPORT   (measured)'); A('='*54)
    A(f'input                  {len(data):>6}')
    A(f'site reachable         {len(live):>6}  {100*len(live)/len(data):5.1f}%')
    A(f'  dead                 {len(data)-len(live):>6}')
    A('')
    A(f'>> EMAIL FOUND         {len(em):>6}  {100*rate:5.1f}%   <-- this is the list')
    A(f'   on own domain       {len(ond):>6}  {100*len(ond)/max(len(em),1):5.1f}%')
    A('')
    A('priority split (not a filter -- nothing dropped):')
    A(f'   batch 1  has pixel  {len(pix):>6}')
    A(f'   batch 2  no pixel   {len(em)-len(pix):>6}')
    A('')
    A(f'elapsed {time.time()-t0:.0f}s')
    A(f'projected across all {n_all}:  {round(n_all*rate)} into Stage 3')
    r='\n'.join(L); print('\n'+r); open(RPT,'w').write(r)

if __name__=='__main__': main()
