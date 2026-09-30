#!/usr/bin/env python3
"""Build the Frame Art library catalog from museum open data.

Sources:
  - National Gallery of Art open data CSVs (objects, published_images, objects_terms), CC0 images via IIIF.
  - Cleveland Museum of Art Open Access API (CC0), hotlinked web/print renditions.

Usage:
  python3 tools/build_catalog.py candidates   # -> build/candidates.json (NGA + Cleveland, filtered, themed)
  python3 tools/build_catalog.py publish      # candidates - curation/rejects.txt -> docs/catalog/v1.json (1000)

Stdlib only. NGA CSVs are read from .cache/nga/ (downloaded from GitHub when missing).
"""
import concurrent.futures
import csv
import datetime
import html
import json
import os
import re
import struct
import sys
import threading
import time
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(ROOT, ".cache")
BUILD = os.path.join(ROOT, "build")
UA = "frame-art-library-builder/1.0 (+https://github.com/WacLabs/frame-art-library)"
NGA_DATA = "https://github.com/NationalGalleryOfArt/opendata/raw/main/data/"
CMA_API = "https://openaccess-api.clevelandart.org/api/artworks/"

TARGET_TOTAL = 1000
TARGET_NGA = 830          # candidates, trimmed to ~750 after review
TARGET_CMA = 280          # candidates, trimmed to ~250 after review
MIN_LONG_SIDE = 3000
FULL_MAX = 3840
PER_ARTIST_CAP = 18
DESC_MAX = 600

THEMES = ["landscape", "seascape", "flowers", "still_life", "city", "japan_asia", "portrait", "modern", "classic"]

SENSITIVE = [
    r"nudes?", r"naked", r"unclothed", r"undressed", r"partially clothed", r"bare[- ]breasted", r"bare[- ]chested",
    r"breasts?", r"topless", r"loincloth", r"bathers?", r"bathing", r"venus", r"leda", r"susanna", r"odalisque",
    r"crucifixion", r"crucified", r"martyr\w*", r"massacre", r"execution", r"executed", r"corpses?",
    r"dead", r"death", r"dying", r"lamentation", r"piet[aà]", r"entombment", r"deposition", r"battle", r"war",
    r"blood\w*", r"severed", r"decapitat\w*", r"behead\w*", r"judith", r"holofernes", r"salome", r"slaughter\w*",
    r"kill\w*", r"skulls?", r"wounded", r"wounds?", r"hanged", r"sebastian", r"flagellation",
    r"mocking", r"hell", r"devils?", r"demons?", r"slaves?", r"slavery", r"lynch\w*", r"weapons?", r"guns?",
    r"rifles?", r"swords?", r"hunt\w*", r"game piece", r"dead game", r"prey", r"suicide", r"rape", r"abduction",
    r"torture\w*", r"abalone", r"shunga", r"erotic\w*", r"temptation", r"satyrs?", r"bacchanal\w*", r"cupid", r"putti", r"sacrifice",
]
SENSITIVE_RE = re.compile(r"\b(" + "|".join(SENSITIVE) + r")\b", re.I)
SENSITIVE_TERMS = {"nude", "female nude", "male nude", "death", "weapons", "crucifixion", "nudes", "female nudes",
                   "male nudes", "battles", "hunting", "violence"}

THEME_WORDS = {
    "seascape": r"seas?|ocean|marine|seascape|harbou?r|coast\w*|beach(es)?|shore|ships?|boats?|sail\w*|waves?|"
                r"fishing fleet|lighthouse|bay|port",
    "flowers": r"flowers?|floral|bouquet|roses?|peon(y|ies)|tulips?|lil(y|ies)|chrysanthemums?|irises|sunflowers?|"
               r"poppies|camellias?|blossoms?",
    "still_life": r"still[- ]life|fruit|grapes|peaches|apples|lemons|oranges|basket of|bowl of|vase|jug",
    "city": r"city|cityscape|urban|street|venice|venetian|paris|london|rome|town|square|piazza|canal|boulevard|"
            r"rooftops|cathedral|church|palace|bridge",
    "portrait": r"portrait|self-portrait|bust of|head of",
    "landscape": r"landscape|river|mountains?|valley|forest|woods|trees?|fields?|meadow|lake|waterfall|countryside|"
                 r"village|garden|sunset|sunrise|snow|winter|hills?|pastoral|farm|orchard|path|road|pond|park",
}
THEME_RES = {k: re.compile(r"\b(" + v + r")\b", re.I) for k, v in THEME_WORDS.items()}
MODERN_STYLES = {"abstract expressionist", "cubist", "fauve", "minimalist", "abstraction", "german expressionist",
                 "non-representational", "geometric", "color field", "pop art", "surrealist"}
RELIGIOUS_RE = re.compile(r"\b(madonna|virgin|christ|saints?|apostles?|annunciation|nativity|holy family|"
                          r"adoration|angels?|st\.|san |santa |altarpiece|triptych|polyptych|crucif)\b", re.I)

csv.field_size_limit(10 ** 9)


# ---------------------------------------------------------------- helpers

def http_get(url, headers=None, timeout=30, retries=3):
    req = urllib.request.Request(url, headers={"User-Agent": UA, **(headers or {})})
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.status, dict(r.headers), r.read()
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503, 504) and attempt < retries - 1:
                time.sleep(2 * (attempt + 1))
                continue
            return e.code, dict(e.headers or {}), b""
        except Exception:
            if attempt < retries - 1:
                time.sleep(2 * (attempt + 1))
                continue
            return None, {}, b""


class RateLimiter:
    def __init__(self, per_second):
        self.interval = 1.0 / per_second
        self.lock = threading.Lock()
        self.next = 0.0

    def wait(self):
        with self.lock:
            now = time.monotonic()
            t = max(now, self.next)
            self.next = t + self.interval
        time.sleep(max(0.0, t - now))


def clean_desc(text):
    if not text:
        return None
    text = html.unescape(re.sub(r"<[^>]+>", " ", text))
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return None
    if len(text) > DESC_MAX:
        cut = text[:DESC_MAX]
        end = max(cut.rfind(". "), cut.rfind("! "), cut.rfind("? "))
        text = cut[: end + 1] if end > 200 else cut.rsplit(" ", 1)[0] + "…"
    return text


def full_dims(w, h, cap=FULL_MAX):
    k = min(1.0, cap / max(w, h))
    return max(1, round(w * k)), max(1, round(h * k))


def is_sensitive(*texts, terms=()):
    if any(t.lower() in SENSITIVE_TERMS for t in terms):
        return True
    return any(t and SENSITIVE_RE.search(t) for t in texts)


def pick_theme(text, terms, styles, year, asian=False):
    if asian:
        return "japan_asia"
    low_terms = {t.lower() for t in terms}
    for theme in ("seascape", "flowers", "still_life", "city", "portrait", "landscape"):
        if THEME_RES[theme].search(text):
            return theme
    if low_terms & MODERN_STYLES or {s.lower() for s in styles} & MODERN_STYLES:
        return "modern"
    if year and year >= 1880:
        return "modern"
    return "classic"


def jpeg_size(data):
    """(width, height) from the SOF marker of a JPEG prefix, or None."""
    i = 2
    while i + 9 < len(data):
        if data[i] != 0xFF:
            i += 1
            continue
        marker = data[i + 1]
        if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:
            i += 2
            continue
        seg = struct.unpack(">H", data[i + 2:i + 4])[0]
        if marker in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
            h, w = struct.unpack(">HH", data[i + 5:i + 9])
            return w, h
        i += 2 + seg
    return None


# ---------------------------------------------------------------- NGA

def nga_csv(name):
    path = os.path.join(CACHE, "nga", name)
    if not os.path.exists(path):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        print(f"downloading {name}…", file=sys.stderr)
        urllib.request.urlretrieve(NGA_DATA + name, path)
    return open(path, encoding="utf-8", newline="")


def nga_candidates():
    objects = {}
    for r in csv.DictReader(nga_csv("objects.csv")):
        if r["classification"] == "Painting" and r["isvirtual"] != "1":
            objects[r["objectid"]] = r
    images = {}
    for r in csv.DictReader(nga_csv("published_images.csv")):
        oid = r["depictstmsobjectid"]
        if oid not in objects or r["viewtype"] != "primary" or r["openaccess"] != "1":
            continue
        try:
            w, h = int(r["width"]), int(r["height"])
        except ValueError:
            continue
        if max(w, h) < MIN_LONG_SIDE:
            continue
        if r["maxpixels"] and int(r["maxpixels"]) < FULL_MAX:
            continue
        if oid not in images or int(r["sequence"] or 0) < int(images[oid]["sequence"] or 0):
            images[oid] = r
    terms, styles = {}, {}
    for r in csv.DictReader(nga_csv("objects_terms.csv")):
        oid = r["objectid"]
        if oid not in images:
            continue
        if r["termtype"] in ("Keyword", "Theme"):
            terms.setdefault(oid, []).append(r["term"])
        elif r["termtype"] == "Style":
            styles.setdefault(oid, []).append(r["term"])

    out = []
    for oid, img in images.items():
        o = objects[oid]
        title = (o["title"] or "").strip()
        desc = clean_desc(img["assistivetext"])
        t, s = terms.get(oid, []), styles.get(oid, [])
        if not title or is_sensitive(title, desc or "", " ".join(t), terms=t):
            continue
        w, h = int(img["width"]), int(img["height"])
        fw, fh = full_dims(w, h)
        year = int(o["beginyear"]) if (o["beginyear"] or "").lstrip("-").isdigit() else None
        text = f"{title} {' '.join(t)} {(desc or '')[:300]}"
        theme = pick_theme(text, t, s, year)
        base = img["iiifurl"].rstrip("/")
        out.append({
            "id": f"nga-{oid}",
            "source": "nga",
            "title": title,
            "artist": (o["attribution"] or "").strip(),
            "date": (o["displaydate"] or "").strip(),
            "medium": (o["medium"] or "").strip(),
            "description": desc,
            "descriptionLang": "en",
            "theme": theme,
            "width": fw,
            "height": fh,
            "thumb": f"{base}/full/!400,400/0/default.jpg",
            "full": f"{base}/full/!{FULL_MAX},{FULL_MAX}/0/default.jpg",
            "page": f"https://www.nga.gov/collection/art-object-page.{oid}.html",
            "license": "CC0",
            "_score": score(theme, fw, fh, desc, text, s),
        })
    return out


def score(theme, w, h, desc, text, styles):
    sc = 0.0
    if w / h >= 1.2:
        sc += 3            # landscape orientation fits a 16:9 TV
    elif w / h >= 0.9:
        sc += 1
    if desc:
        sc += 1
    sc += {"landscape": 3, "seascape": 3, "flowers": 3, "city": 2.5, "still_life": 2, "japan_asia": 3,
           "modern": 1.5, "portrait": 0.5, "classic": 0}[theme]
    if {x.lower() for x in styles} & {"impressionist", "post-impressionist", "romantic", "realist"}:
        sc += 1.5
    if RELIGIOUS_RE.search(text):
        sc -= 2.5
    return sc


# ---------------------------------------------------------------- Cleveland

CMA_QUERIES = [
    # Asian art is what NGA lacks: ukiyo-e prints and scroll paintings, all themed japan_asia.
    ({"department": "Japanese Art", "type": "Print"}, ["landscape", "Hiroshige", "Hokusai", "Fuji", "flowers", "birds",
                                                      "snow", "moon", "river", "bridge", "waterfall", "rain"]),
    ({"department": "Japanese Art", "type": "Painting"}, ["landscape", "flowers", "birds", "autumn", "spring"]),
    ({"department": "Chinese Art", "type": "Painting"}, ["landscape", "flowers", "birds", "bamboo", "mountain", "lotus"]),
    ({"department": "Korean Art", "type": "Painting"}, [""]),
]
CMA_MAX_RATIO = 2.4   # handscrolls / tall hanging scrolls do not fit a 16:9 TV


def cma_candidates():
    seen, out = set(), []
    for base, queries in CMA_QUERIES:
        for q in queries:
            params = {**base, "cc0": "1", "has_image": "1", "limit": "1000"}
            if q:
                params["q"] = q
            status, _, body = http_get(CMA_API + "?" + urllib.parse.urlencode(params), timeout=90)
            data = json.loads(body).get("data", []) if status == 200 else []
            print(f"cma {base['department']}/{base['type']} q={q!r}: {len(data)}", file=sys.stderr)
            for d in data:
                item = cma_item(d)
                if item and item["id"] not in seen:
                    seen.add(item["id"])
                    out.append(item)
    return out


def cma_item(d):
    if d.get("share_license_status") != "CC0":
        return None
    img = (d.get("images") or {}).get("print") or {}
    web = (d.get("images") or {}).get("web") or {}
    try:
        w, h = int(img.get("width") or 0), int(img.get("height") or 0)
    except ValueError:
        return None
    if not img.get("url") or not web.get("url") or min(w, h) <= 0:
        return None
    if max(w, h) < MIN_LONG_SIDE or max(w, h) / min(w, h) > CMA_MAX_RATIO:
        return None
    title = (d.get("title") or "").strip()
    desc = clean_desc(d.get("description") or "")
    if not title or is_sensitive(title, desc or ""):
        return None
    artist = next((c.get("description") or "" for c in d.get("creators") or [] if c.get("role") == "artist"), "")
    artist = artist.split(" (")[0].strip() or ", ".join(d.get("culture") or [])[:80]
    fw, fh = full_dims(w, h)
    text = f"{title} {desc or ''}"
    return {
        "id": f"cma-{d['id']}",
        "source": "cma",
        "title": title,
        "artist": artist,
        "date": (d.get("creation_date") or "").strip(),
        "medium": (d.get("technique") or "").strip(),
        "description": desc,
        "descriptionLang": "en",
        "theme": "japan_asia",
        "width": fw,
        "height": fh,
        "thumb": web["url"],
        "full": img["url"],
        "page": d.get("url") or f"https://www.clevelandart.org/art/{d.get('accession_number')}",
        "license": "CC0",
        "_score": score("japan_asia", w, h, desc, text, []) + (2 if d.get("is_highlight") else 0),
    }


# ---------------------------------------------------------------- selection

def select(items, n):
    """Top-n by score with a per-artist cap and a floor per theme where the pool allows."""
    items = sorted(items, key=lambda x: -x["_score"])
    per_artist, chosen = {}, []
    for it in items:
        a = it["artist"].lower() or it["id"]
        if per_artist.get(a, 0) >= PER_ARTIST_CAP:
            continue
        per_artist[a] = per_artist.get(a, 0) + 1
        chosen.append(it)
        if len(chosen) == n:
            break
    return chosen


def interleave(items):
    """Default display order: round-robin across themes so the first screen is varied."""
    by_theme = {}
    for it in sorted(items, key=lambda x: -x["_score"]):
        by_theme.setdefault(it["theme"], []).append(it)
    order = sorted(by_theme, key=lambda t: THEMES.index(t))
    out = []
    while any(by_theme.values()):
        for t in order:
            if by_theme[t]:
                out.append(by_theme[t].pop(0))
    return out


def read_list(name):
    path = os.path.join(ROOT, "curation", name)
    if not os.path.exists(path):
        return set()
    return {ln.split("#")[0].strip() for ln in open(path) if ln.split("#")[0].strip()}


def cmd_candidates():
    os.makedirs(BUILD, exist_ok=True)
    nga = nga_candidates()
    print(f"nga pool {len(nga)}", file=sys.stderr)
    cma = cma_candidates()
    print(f"cma pool {len(cma)}", file=sys.stderr)
    cands = select(nga, TARGET_NGA) + select(cma, TARGET_CMA)
    json.dump(cands, open(os.path.join(BUILD, "candidates.json"), "w"), ensure_ascii=False, indent=1)
    json.dump(nga + cma, open(os.path.join(BUILD, "pool.json"), "w"), ensure_ascii=False)
    summary(cands)


def cmd_publish():
    cands = json.load(open(os.path.join(BUILD, "candidates.json")))
    rejects, pins = read_list("rejects.txt"), read_list("pins.txt")
    kept = [c for c in cands if c["id"] not in rejects]
    pinned = [c for c in kept if c["id"] in pins]
    rest = [c for c in kept if c["id"] not in pins]
    cma = [c for c in rest if c["source"] == "cma"][:250]
    nga = [c for c in rest if c["source"] == "nga"][: TARGET_TOTAL - len(pinned) - len(cma)]
    final = interleave(pinned + nga + cma)[:TARGET_TOTAL]
    items = [{k: v for k, v in c.items() if not k.startswith("_")} for c in final]
    path = os.path.join(ROOT, "docs", "catalog", "v1.json")
    version_path = os.path.join(ROOT, "docs", "catalog", "v1.version.json")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    # The app keeps its cached catalog until it sees a higher version, so every publish that changes the
    # items bumps it. v1.version.json is the small file the app polls; v1.json carries the same number.
    previous = json.load(open(path)) if os.path.exists(path) else {}
    version = previous.get("version", 0)
    if previous.get("items") == items and version > 0:
        print(f"items unchanged, keeping version {version}", file=sys.stderr)
    else:
        version += 1
    updated_at = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    catalog = {"schemaVersion": 1, "version": version, "updatedAt": updated_at, "items": items}
    with open(path, "w") as f:
        json.dump(catalog, f, ensure_ascii=False, separators=(",", ":"))
    with open(version_path, "w") as f:
        json.dump({"version": version, "updatedAt": updated_at, "count": len(items)}, f)
    print(f"wrote {len(items)} items -> {path} ({os.path.getsize(path) // 1024} KB)", file=sys.stderr)
    summary(final)


def cmd_validate():
    """Every thumb/full URL of the published catalog must answer 200/206 with an image."""
    items = json.load(open(os.path.join(ROOT, "docs", "catalog", "v1.json")))["items"]
    limiter = RateLimiter(8)

    def check(url):
        limiter.wait()
        status, headers, _ = http_get(url, headers={"Range": "bytes=0-1023"}, timeout=60)
        ok = status in (200, 206) and headers.get("Content-Type", "").startswith("image/")
        return None if ok else f"{status} {url}"

    urls = [u for it in items for u in (it["thumb"], it["full"])]
    with concurrent.futures.ThreadPoolExecutor(8) as ex:
        bad = [b for b in ex.map(check, urls) if b]
    ids = {len(items), len({it["id"] for it in items})}
    print(f"{len(items)} items, unique ids {ids}, {len(urls)} urls, {len(bad)} bad", file=sys.stderr)
    for b in bad:
        print(b)
    sys.exit(1 if bad else 0)


def summary(items):
    from collections import Counter
    print("sources", Counter(i["source"] for i in items), file=sys.stderr)
    print("themes", Counter(i["theme"] for i in items), file=sys.stderr)
    print("with description", sum(1 for i in items if i["description"]), file=sys.stderr)
    print("landscape orientation", sum(1 for i in items if i["width"] >= i["height"]), file=sys.stderr)


if __name__ == "__main__":
    import urllib.parse  # noqa: E402  (used in cma_candidates)
    {"candidates": cmd_candidates, "publish": cmd_publish, "validate": cmd_validate}[sys.argv[1] if len(sys.argv) > 1 else "candidates"]()
