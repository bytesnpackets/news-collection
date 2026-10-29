# Calm daily news (Burmese)

`build.py` reads a fixed list of trusted RSS feeds, has Claude rewrite a few stories per section as calm Burmese,
adds Yangon weather and an approximate gold price in kyats, and writes `docs/index.html`.

Setup:
1. Push this folder to a GitHub repo.
2. Repo Settings > Secrets > Actions: add `ANTHROPIC_API_KEY`.
3. Settings > Pages: deploy from branch `main`, folder `/docs`.
4. Actions > daily-news > Run workflow once. It then runs daily at 05:00 Yangon time.
5. On her phone (Chrome): open the Pages URL > menu > Add to Home screen.

Local run: `ANTHROPIC_API_KEY=... python build.py`. Test: `python -m pytest test_build.py` (or `python -c "import test_build as t; t.test_parse_rss_skips_items_without_link(); t.test_render_drops_invented_ids_and_escapes()"`).

Edit sources in `FEEDS` at the top of `build.py`.
