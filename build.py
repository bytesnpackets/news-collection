"""Daily calm Burmese news page. Stdlib only. Needs ANTHROPIC_API_KEY.

Fetches RSS from a fixed list of trusted outlets, has Claude rewrite a few
stories per section in calm Burmese, adds Yangon weather + gold price, and
writes docs/index.html. On any failure it exits non-zero and leaves the old
page untouched.
"""
import gzip
import html
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone

MODEL = "claude-haiku-5-5"
PER_SECTION = {"breaking": 3, "uk": 4, "singapore": 4, "politics": 3, "world": 3}
TITLES = {
    "weather": "ရာသီဥတု", "breaking": "အရေးကြီးသတင်း", "uk": "ဗြိတိန်",
    "singapore": "စင်ကာပူ", "politics": "နိုင်ငံရေး", "world": "ကမ္ဘာ့သတင်း",
    "gold": "ရွှေဈေး",
}
# Only these feeds are ever read. Edit this list to change sources.
FEEDS = {
    "breaking": [("BBC", "https://feeds.bbci.co.uk/news/rss.xml")],
    "uk": [
        ("BBC", "https://feeds.bbci.co.uk/news/uk/rss.xml"),
        ("The Guardian", "https://www.theguardian.com/uk/rss"),
        ("The Independent", "https://www.independent.co.uk/news/uk/rss"),
    ],
    "singapore": [("The Straits Times", "https://www.straitstimes.com/news/singapore/rss.xml")],
    "politics": [
        ("BBC", "https://feeds.bbci.co.uk/news/politics/rss.xml"),
        ("The Guardian", "https://www.theguardian.com/politics/rss"),
    ],
    "world": [
        ("BBC မြန်မာ", "https://feeds.bbci.co.uk/burmese/rss.xml"),  # keep name == BURMESE_SOURCE
        ("BBC", "https://feeds.bbci.co.uk/news/world/rss.xml"),
        ("The Guardian", "https://www.theguardian.com/world/rss"),
    ],
}
BURMESE_SOURCE = "BBC မြန်မာ"  # already Burmese, so its links skip translation
YANGON = (16.8661, 96.1951)
KYAT_THAR_G = 16.329  # one Burmese gold "kyat-thar" in grams
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "docs")


def get(url, data=None, headers=None, timeout=30):
    req = urllib.request.Request(url, data=data, headers={"User-Agent": "calm-news/1.0", **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read()
    except urllib.error.HTTPError as e:  # show the API's reason, not just the status
        raise RuntimeError(f"{e.code} from {url}: {e.read()[:500]!r}") from None
    return gzip.decompress(raw) if raw[:2] == b"\x1f\x8b" else raw  # some feeds gzip unasked


def parse_rss(xml_bytes, source, limit=8):
    items = []
    for it in ET.fromstring(xml_bytes).iter("item"):
        title = (it.findtext("title") or "").strip()
        link = (it.findtext("link") or "").strip()
        desc = (it.findtext("description") or "").strip()
        if title and link:
            items.append({"source": source, "title": title, "desc": desc[:300], "link": link})
        if len(items) >= limit:
            break
    return items


def collect():
    pool = {}  # id -> item, grouped by section for the prompt
    sections = {}
    n = 0
    for sec, feeds in FEEDS.items():
        sections[sec] = []
        for source, url in feeds:
            try:
                items = parse_rss(get(url), source)
            except Exception as e:  # one dead feed must not kill the page
                print(f"skip {url}: {e}", file=sys.stderr)
                continue
            for it in items:
                n += 1
                pool[f"n{n}"] = it
                sections[sec].append(f"n{n}")
    return pool, sections


def weather():
    lat, lon = YANGON
    d = json.loads(get(
        "https://api.open-meteo.com/v1/forecast?latitude=%s&longitude=%s&timezone=Asia%%2FYangon"
        "&daily=weather_code,temperature_2m_max,temperature_2m_min,precipitation_sum,wind_speed_10m_max"
        "&forecast_days=1" % (lat, lon)))["daily"]
    w = {k: d[k][0] for k in d if k != "time"}
    # Open-Meteo has no official alerts; these thresholds are our own rule of thumb.
    w["warning"] = w["weather_code"] >= 95 or w["precipitation_sum"] >= 50 or w["wind_speed_10m_max"] >= 60
    return w


def gold(prev_kyat=None):
    usd_oz = json.loads(get("https://api.gold-api.com/price/XAU"))["price"]
    mmk = json.loads(get("https://open.er-api.com/v6/latest/USD"))["rates"]["MMK"]
    kyat = round(usd_oz / 31.1035 * KYAT_THAR_G * mmk, -3)
    change = None if prev_kyat is None else ("up" if kyat > prev_kyat else "down" if kyat < prev_kyat else "same")
    return {"kyat_thar": kyat, "change": change}


def ask_claude(pool, sections, w, g):
    lines = []
    for sec, ids in sections.items():
        lines.append(f"[{sec}] choose up to {PER_SECTION[sec]}")
        lines += [f"{i} | {pool[i]['source']} | {pool[i]['title']} | {pool[i]['desc']}" for i in ids]
    system = (
        "You write a daily news page for an elderly Burmese woman who is easily worried by news. "
        "Pick the most important stories per section (skip opinion, celebrity, crime gore, and pure scare stories "
        "unless truly major). Rewrite each as 2-3 short, calm, plain Burmese sentences. No alarming words, no "
        "exaggeration, no clickbait, add nothing not in the source, and say plainly when something is unconfirmed. "
        "Never repeat a story across sections. Also write one short Burmese weather line for Yangon from the data "
        "(mention if a warning is true and what it means), and one short Burmese gold line (say it is an approximate "
        "world-market price per ကျပ်သား (the Burmese gold weight unit; use exactly that word) and whether it moved). "
        'Reply with JSON only: {"weather": str, "gold": str, "stories": {"<section>": [{"id": str, "text": str}]}}'
    )
    user = f"WEATHER: {json.dumps(w)}\nGOLD: {json.dumps(g)}\n\nSTORIES:\n" + "\n".join(lines)
    body = json.dumps({"model": MODEL, "max_tokens": 8000, "system": system, "thinking": {"type": "disabled"},
                       "messages": [{"role": "user", "content": user}]}).encode()
    resp = json.loads(get("https://api.anthropic.com/v1/messages", body, {
        "x-api-key": os.environ["ANTHROPIC_API_KEY"], "anthropic-version": "2023-06-01",
        "content-type": "application/json"}, timeout=300))  # Burmese output is slow to generate
    text = "".join(b["text"] for b in resp["content"] if b.get("type") == "text")
    if "{" not in text:
        raise RuntimeError(f"no JSON in reply: stop_reason={resp.get('stop_reason')} "
                           f"blocks={[b.get('type') for b in resp['content']]} text={text[:300]!r}")
    return json.loads(text[text.index("{"): text.rindex("}") + 1])


def translated(url):
    """Link that opens the article through Google's translate proxy (host.com -> host-com.translate.goog)."""
    p = urllib.parse.urlsplit(url)
    host = p.netloc.replace("-", "--").replace(".", "-") + ".translate.goog"
    q = (p.query + "&" if p.query else "") + "_x_tr_sl=auto&_x_tr_tl=my&_x_tr_hl=my"
    return urllib.parse.urlunsplit(("https", host, p.path, q, p.fragment))


def render(out, pool, now):
    def card(text, extra=""):
        return f'<div class="c">{html.escape(text)}{extra}</div>'

    parts = [f'<h2>{TITLES["weather"]}</h2>' + card(out["weather"])]
    for sec in ("breaking", "uk", "singapore", "politics", "world"):
        cards = []
        for s in out["stories"].get(sec, []):
            it = pool.get(s["id"])  # unknown ids are dropped so links can never be invented
            if it:
                href = it["link"] if it["source"] == BURMESE_SOURCE else translated(it["link"])
                link = f' <a href="{html.escape(href)}">{html.escape(it["source"])} ›</a>'
                cards.append(card(s["text"], link))
        if cards:
            parts.append(f'<h2>{TITLES[sec]}</h2>' + "".join(cards))
    parts.append(f'<h2>{TITLES["gold"]}</h2>' + card(out["gold"]))
    return f"""<!doctype html><html lang="my"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>နေ့စဉ်သတင်း</title>
<style>body{{font:22px/1.7 "Noto Sans Myanmar","Padauk",sans-serif;margin:0 auto;max-width:640px;padding:16px;background:#fffdf7;color:#222}}
h1{{font-size:26px}}h2{{font-size:24px;margin:28px 0 8px;color:#14532d}}
.c{{background:#fff;border:1px solid #e5e0d0;border-radius:12px;padding:14px;margin:10px 0}}
a{{display:block;margin-top:6px;color:#1d4ed8;font-size:18px}}small{{color:#666}}</style></head>
<body><h1>နေ့စဉ်သတင်း</h1><small>{now:%Y-%m-%d %H:%M} (ရန်ကုန်)</small>
{"".join(parts)}</body></html>"""


def main():
    now = datetime.now(timezone(timedelta(hours=6, minutes=30)))
    state_path = os.path.join(OUT, "state.json")
    prev = None
    if os.path.exists(state_path):
        prev = json.load(open(state_path)).get("kyat_thar")
    pool, sections = collect()
    w, g = weather(), gold(prev)
    out = ask_claude(pool, sections, w, g)
    page = render(out, pool, now)
    os.makedirs(OUT, exist_ok=True)
    open(os.path.join(OUT, "index.html"), "w", encoding="utf-8").write(page)
    json.dump({"kyat_thar": g["kyat_thar"]}, open(state_path, "w"))
    print("wrote docs/index.html")


if __name__ == "__main__":
    main()
