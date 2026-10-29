from datetime import datetime

import build

RSS = b"""<rss><channel>
<item><title>Storm hits coast</title><link>http://x/1</link><description>Heavy rain</description></item>
<item><title>No link</title></item>
</channel></rss>"""


def test_parse_rss_skips_items_without_link():
    items = build.parse_rss(RSS, "BBC")
    assert items == [{"source": "BBC", "title": "Storm hits coast", "desc": "Heavy rain", "link": "http://x/1"}]


def test_translated_link():
    assert build.translated("https://www.bbc.co.uk/news/articles/abc-1?at=x") == (
        "https://www-bbc-co-uk.translate.goog/news/articles/abc-1?at=x&_x_tr_sl=auto&_x_tr_tl=my&_x_tr_hl=my")
    assert build.translated("https://my-site.com/a").startswith("https://my--site-com.translate.goog/a?")


def test_render_drops_invented_ids_and_escapes():
    pool = {"n1": {"source": "BBC", "title": "t", "desc": "", "link": "http://x/1"}}
    out = {"weather": "w", "gold": "g", "stories": {"uk": [
        {"id": "n1", "text": "<b>ok</b>"}, {"id": "n99", "text": "invented"}]}}
    page = build.render(out, pool, datetime(2026, 1, 1))
    assert "x.translate.goog/1" in page and "invented" not in page and "<b>ok</b>" not in page
