"""Download titles, awards, season formats, standings and player bios.

Usage:
    python -m eurostats.fetch_history feed --from 2000 --to 2025
    python -m eurostats.fetch_history wiki

Sources:
    feed   api-live.euroleague.net: each season's phases, rounds, the
           standings after the last round of every group phase, and the
           people registered with each club (players' bios).
    wiki   en.wikipedia.org: the champions, Final Four and award pages.
           query.wikidata.org: the Wikidata ID of every page those tables
           link to, and every Wikidata item with a EuroLeague player or
           coach ID, so award winners can be matched to feed codes.

Wikipedia's API (w/api.php) answers 429 to busy shared addresses such as
cloud machines, so pages are read as ordinary article pages and linked
titles are looked up on Wikidata's query service instead. A linked title
Wikidata doesn't know (usually a redirect) is opened as an article page to
read the Wikidata ID of the page it redirects to.

Responses are stored untouched as gzipped JSON under data/raw/history/ and
skipped when already on disk, so the download can be stopped and resumed.
Then run eurostats.flatten_history to build the CSV tables.

Wikidata is CC0. Wikipedia text is CC BY-SA, so only facts (who won what,
when, the score) are taken from its tables, never prose.
"""
import argparse
import csv
import gzip
import hashlib
import json
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

COMPETITION = "E"
HISTORY_DIR = Path(os.environ.get(
    "EUROSTATS_HISTORY_DIR",
    Path(__file__).resolve().parent.parent / "data" / "raw" / "history",
))
# The images download already saved each season's people list; reuse it
# rather than asking the feed again.
PEOPLE_DIRS = [Path(p) for p in os.environ.get("EUROSTATS_PEOPLE_DIRS", "").split(os.pathsep) if p]
PAUSE_SECONDS = 2.0
USER_AGENT = "eurostats/0.1 (non-commercial EuroLeague history fan site; github.com/asphericaldream/eurostats)"

FEED = "https://api-live.euroleague.net"
FEED_URLS = {
    "phases": FEED + "/v2/competitions/{comp}/seasons/{comp}{season}/phases",
    "rounds": FEED + "/v2/competitions/{comp}/seasons/{comp}{season}/rounds",
    "people": FEED + "/v2/competitions/{comp}/seasons/{comp}{season}/people?limit=5000",
    "standings": FEED + "/v3/competitions/{comp}/seasons/{comp}{season}/rounds/{round}/basicstandings",
}

WIKIPEDIA = "https://en.wikipedia.org/wiki/"
WIKIDATA_SPARQL = "https://query.wikidata.org/sparql"
# English Wikipedia pages whose tables hold the facts we want.
WIKI_PAGES = {
    "finals": "List of EuroLeague finals",
    "final_four": "EuroLeague Final Four",
    "mvp": "EuroLeague MVP",
    "final_four_mvp": "EuroLeague Final Four MVP",
    "all_euroleague": "All-EuroLeague Team",
    "coach_of_the_year": "Alexander Gomelsky EuroLeague Coach of the Year",
    "rising_star": "EuroLeague Rising Star",
}
# Wikidata properties whose English label mentions EuroLeague, such as the
# EuroLeague player ID. Looked up by label so no property number is guessed.
EUROLEAGUE_PROPERTIES = """
SELECT ?property ?label WHERE {
  ?property a wikibase:Property ; rdfs:label ?label .
  FILTER(LANG(?label) = "en" && CONTAINS(LCASE(?label), "euroleague"))
}"""
# Wikidata IDs of English Wikipedia articles, by exact title.
ARTICLE_QIDS = """
SELECT ?title ?item WHERE {
  VALUES ?title { %s }
  ?article schema:about ?item ; schema:isPartOf <https://en.wikipedia.org/> ;
           schema:name ?title .
}"""
PROPERTY_VALUES = """
SELECT ?item ?itemLabel ?value WHERE {
  ?item wdt:%s ?value .
  SERVICE wikibase:label { bd:serviceParam wikibase:language "en". }
}"""


def raw_path(name: str) -> Path:
    return HISTORY_DIR / f"{name}.json.gz"


def save(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with gzip.open(tmp, "wt", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    tmp.replace(path)


def load(path: Path):
    with gzip.open(path, "rt", encoding="utf-8") as f:
        return json.load(f)


def get_json(session: requests.Session, url: str, params: dict | None = None,
             parse=None):
    """GET with a pause after every request and patient retries.

    The feed refuses requests when several downloads run at once, so a 429
    or 5xx waits and tries again instead of giving up. Returns None on 404.
    parse turns the response into the data to keep (default: its JSON).
    """
    for attempt in range(6):
        try:
            response = session.get(url, params=params, timeout=60)
        except requests.RequestException as error:
            print(f"retry {url}: {error}")
        else:
            if response.status_code == 404:
                time.sleep(PAUSE_SECONDS)
                return None
            if response.status_code < 400:
                time.sleep(PAUSE_SECONDS)
                return parse(response) if parse else response.json()
            print(f"retry {url}: HTTP {response.status_code}")
        time.sleep(10 * 2 ** attempt)
    raise SystemExit(f"giving up on {url}")


def cached(session, name: str, url: str, params: dict | None = None, parse=None):
    path = raw_path(name)
    if path.exists():
        return load(path)
    data = get_json(session, url, params, parse)
    if data is not None:
        save(path, data)
        log_download(path, response_url(url, params))
    return data


def response_url(url: str, params: dict | None) -> str:
    return requests.Request("GET", url, params=params).prepare().url


def log_download(path: Path, url: str) -> None:
    """Where and when each file came from, for the credits and sources.csv."""
    log = HISTORY_DIR / "downloads.csv"
    new = not log.exists()
    with log.open("a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        if new:
            writer.writerow(["file", "source_url", "downloaded_at"])
        writer.writerow([path.relative_to(HISTORY_DIR).as_posix(), url,
                         datetime.now(timezone.utc).isoformat(timespec="seconds")])


def items(data) -> list:
    return data.get("data", []) if isinstance(data, dict) else (data or [])


def fetch_feed(session: requests.Session, seasons: range) -> None:
    for season in seasons:
        fmt = {"comp": COMPETITION, "season": season}
        name = f"{COMPETITION}{season}"
        phases = cached(session, f"feed/{name}_phases", FEED_URLS["phases"].format(**fmt))
        rounds = cached(session, f"feed/{name}_rounds", FEED_URLS["rounds"].format(**fmt))
        if not any(d.exists() for d in
                   (p / f"{name}_people.json.gz" for p in PEOPLE_DIRS)):
            cached(session, f"feed/{name}_people", FEED_URLS["people"].format(**fmt))
        group_phases = {p["phaseType"]["code"] for p in items(phases)
                        if p["phaseType"].get("isGroupPhase")}
        for phase in group_phases:
            last = max((r["round"] for r in items(rounds) if r["phaseTypeCode"] == phase),
                       default=None)
            if last is not None:
                cached(session, f"feed/{name}_standings_{phase}_{last}",
                       FEED_URLS["standings"].format(round=last, **fmt))
        print(f"done {name}: phases {sorted(group_phases)} have standings", flush=True)


def article(response: requests.Response) -> dict:
    """An article page's content and the facts MediaWiki puts in its head.

    Kept in the shape of the API's action=parse answer, so pages saved
    either way read the same.
    """
    html = response.text

    def setting(name):
        match = re.search(rf'"{name}":("(?:[^"\\]|\\.)*"|\d+)', html)
        return json.loads(match.group(1)) if match else None

    start = html.find('<div id="mw-content-text"')
    end = html.find('<div class="printfooter"', start)
    return {"parse": {
        "title": (setting("wgPageName") or "").replace("_", " "),
        "revid": setting("wgRevisionId"),
        "wikibase_item": setting("wgWikibaseItemId"),
        "text": html[start:end if end > 0 else None] if start >= 0 else html,
    }}


def article_url(title: str) -> str:
    return WIKIPEDIA + requests.utils.quote(title.replace(" ", "_"), safe="")


def sparql_string(text: str) -> str:
    escaped = text.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"@en'


def fetch_wiki(session: requests.Session) -> None:
    for key, title in WIKI_PAGES.items():
        page = cached(session, f"wikipedia/{key}", article_url(title), parse=article)
        if page is None or "parse" not in page:
            print(f"no Wikipedia page for {title!r}", flush=True)
            continue
        print(f"saved Wikipedia {page['parse']['title']} (revision {page['parse']['revid']})",
              flush=True)

    # Wikidata IDs of every page linked from those tables, 50 titles a call.
    from eurostats.flatten_history import wiki_link_titles
    titles = sorted(wiki_link_titles())
    found = {}
    for start in range(0, len(titles), 50):
        chunk = titles[start:start + 50]
        data = cached(session, f"wikidata/article_qids_{start // 50:03d}", WIKIDATA_SPARQL, {
            "query": ARTICLE_QIDS % " ".join(map(sparql_string, chunk)), "format": "json"})
        for row in data["results"]["bindings"]:
            found[row["title"]["value"]] = row["item"]["value"].rsplit("/", 1)[-1]
    print(f"Wikidata knows {len(found)} of {len(titles)} linked pages", flush=True)

    # The rest are mostly redirects: the article page names the target's ID.
    missing = [t for t in titles if t not in found]
    for n, title in enumerate(missing, 1):
        digest = hashlib.sha1(title.encode()).hexdigest()[:12]
        cached(session, f"wikipedia/links/{digest}", article_url(title), parse=lambda r, t=title: {
            "link": t, **{k: v for k, v in article(r)["parse"].items() if k != "text"}})
        if n % 25 == 0:
            print(f"opened {n} of {len(missing)} redirected pages", flush=True)

    properties = cached(session, "wikidata/euroleague_properties", WIKIDATA_SPARQL,
                        {"query": EUROLEAGUE_PROPERTIES, "format": "json"})
    for row in properties["results"]["bindings"]:
        pid = row["property"]["value"].rsplit("/", 1)[-1]
        print(f"Wikidata {pid}: {row['label']['value']}", flush=True)
        cached(session, f"wikidata/{pid}_values", WIKIDATA_SPARQL,
               {"query": PROPERTY_VALUES % pid, "format": "json"})


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("source", choices=["feed", "wiki"])
    parser.add_argument("--from", dest="start", type=int, default=2000)
    parser.add_argument("--to", dest="end", type=int, default=2025)
    args = parser.parse_args()
    session = requests.Session()
    session.headers["User-Agent"] = USER_AGENT
    if args.source == "feed":
        fetch_feed(session, range(args.start, args.end + 1))
    else:
        fetch_wiki(session)


if __name__ == "__main__":
    main()
