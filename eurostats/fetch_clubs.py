"""Download club data for every EuroLeague club since 2000-01 and write CSVs.

Usage:
    python -m eurostats.fetch_clubs --from 2000 --to 2025 --out data/clubs/csv
    python -m eurostats.fetch_clubs --skip-wikidata      # EuroLeague feed only

Sources:
    api-live.euroleague.net   season club lists (the name and sponsor a club
                              played under that season), club records (city,
                              address, president, website, current arena) and
                              every venue the feed knows
    raw game files            the arena each home game was played in, so arena
                              history comes from what actually happened
                              (run eurostats.fetch_games first; optional)
    query.wikidata.org        founding year, owners, home venue, city (CC0,
                              credit "Wikidata")

Responses are stored untouched as gzipped JSON under data/clubs/raw/; files
already on disk are skipped, so re-running only fetches what is missing.
Crest URLs in the feed are dropped: images are handled separately.

Tables (one row per ...):
    club_info.csv          club: today's name, country, city, address,
                           president, website, current arena
    club_seasons.csv       club in a season: the name, sponsor and short
                           names it played under
    club_home_venues.csv   club, season and arena: home games played there,
                           arena capacity, average attendance
    all_venues.csv         venue in the feed: name, capacity, address
    club_wikidata.csv      club: Wikidata id, founding date, owners, home
                           venue and city with map coordinates, and how the
                           match was made

Wikidata matches are found by searching for the club's name, so check them.
Fix a wrong one by adding a row to eurostats/club_wikidata_ids.csv.
"""
import argparse
import csv
import gzip
import json
import os
import time
from collections import Counter, defaultdict
from pathlib import Path

import requests

from eurostats.fetch import COMPETITION
from eurostats.fetch_games import GAMES_DIR

ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = Path(os.environ.get("EUROSTATS_CLUBS_DIR", ROOT / "data" / "clubs" / "raw"))
OVERRIDES = Path(__file__).resolve().parent / "club_wikidata_ids.csv"
PAUSE_SECONDS = 0.5
API = "https://api-live.euroleague.net/v2"
WIKIDATA_SPARQL = "https://query.wikidata.org/sparql"
# Wikimedia asks every client to say who it is.
USER_AGENT = "eurostats/0.1 (non-commercial EuroLeague fan project; github.com/asphericaldream/eurostats)"


def cached_get(session: requests.Session, path: Path, url: str, params=None):
    """Return the JSON at url, downloading it only if path is not on disk."""
    if not path.exists():
        for attempt in range(4):
            try:
                response = session.get(url, params=params, timeout=60)
                if response.status_code == 404:
                    return None
                response.raise_for_status()
                break
            except requests.RequestException as error:
                print(f"retry {url}: {error}")
                time.sleep(5 * 2 ** attempt)
        else:
            raise SystemExit(f"giving up on {url}")
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        with gzip.open(tmp, "wb") as f:
            f.write(response.content)
        tmp.replace(path)
        time.sleep(PAUSE_SECONDS)
    with gzip.open(path, "rt", encoding="utf-8") as f:
        return json.load(f)


def fetch_euroleague(session, start: int, end: int):
    seasons = {}
    for season in range(start, end + 1):
        data = cached_get(session, RAW_DIR / f"season_{COMPETITION}{season}_clubs.json.gz",
                          f"{API}/competitions/{COMPETITION}/seasons/{COMPETITION}{season}/clubs")
        seasons[season] = (data or {}).get("data", [])
    codes = sorted({club["code"] for clubs in seasons.values() for club in clubs})
    clubs = {code: cached_get(session, RAW_DIR / "clubs" / f"{code}.json.gz",
                              f"{API}/clubs/{code}") for code in codes}
    venues = cached_get(session, RAW_DIR / "venues.json.gz", f"{API}/venues",
                        params={"limit": 2000})
    print(f"EuroLeague feed: {len(codes)} clubs, {len(venues['data'])} venues")
    return seasons, clubs, venues["data"]


def clean(text):
    """Feed text sometimes carries HTML line breaks."""
    if not isinstance(text, str):
        return text
    return " ".join(text.replace("<br>", " ").replace("<br/>", " ").split()) or None


def club_info_rows(clubs: dict, seasons: dict) -> list:
    last_season = defaultdict(int)
    first_season = {}
    for season, rows in seasons.items():
        for club in rows:
            last_season[club["code"]] = max(last_season[club["code"]], season)
            first_season.setdefault(club["code"], season)
    rows = []
    for code, club in clubs.items():
        club = club or {}
        venue = club.get("venue") or {}
        rows.append({
            "club_code": code,
            "name": club.get("name"),
            "alias": club.get("alias"),
            "country_code": (club.get("country") or {}).get("code"),
            "country": (club.get("country") or {}).get("name"),
            "city": clean(club.get("city")),
            "address": clean(club.get("address")),
            "president": clean(club.get("president")),
            "website": club.get("website") or None,
            "twitter": club.get("twitterAccount") or None,
            "instagram": club.get("instagramAccount") or None,
            "facebook": club.get("facebookAccount") or None,
            "venue_code": venue.get("code"),
            "venue_name": venue.get("name"),
            "venue_capacity": venue.get("capacity"),
            "first_season": first_season.get(code),
            "last_season": last_season.get(code),
        })
    return rows


def club_season_rows(seasons: dict) -> list:
    return [{
        "season": season,
        "club_code": club["code"],
        "name": club.get("name"),
        "abbreviated_name": club.get("abbreviatedName"),
        "editorial_name": club.get("editorialName") or None,
        "sponsor": club.get("sponsor"),
        "tv_code": club.get("tvCode"),
        "permanent_name": club.get("clubPermanentName"),
        "permanent_alias": club.get("clubPermanentAlias"),
    } for season, clubs in seasons.items() for club in clubs]


def venue_rows(venues: list) -> list:
    return [{
        "venue_code": venue["code"],
        "name": venue.get("name"),
        "capacity": venue.get("capacity"),
        "address": clean(venue.get("address")),
        "active": venue.get("active"),
    } for venue in venues]


def home_venue_rows(start: int, end: int) -> list:
    """Count home games per club, season and arena from the raw game files."""
    games = Counter()
    audience = defaultdict(list)
    names = {}
    for season in range(start, end + 1):
        for path in sorted((GAMES_DIR / f"{COMPETITION}{season}").glob("*_game.json.gz")):
            with gzip.open(path, "rt", encoding="utf-8") as f:
                game = json.load(f)
            venue = game.get("venue") or {}
            if not venue.get("code") or game.get("isNeutralVenue"):
                continue
            key = (season, game["local"]["club"]["code"], venue["code"])
            games[key] += 1
            if game.get("audience"):
                audience[key].append(game["audience"])
            names[venue["code"]] = (venue.get("name"), venue.get("capacity"))
    if not games:
        print(f"no game files under {GAMES_DIR}; club_home_venues.csv will be empty")
    return [{
        "season": season,
        "club_code": club,
        "venue_code": venue,
        "venue_name": names[venue][0],
        "venue_capacity": names[venue][1],
        "home_games": count,
        "average_audience": round(sum(audience[key]) / len(audience[key]))
        if audience[key] else None,
    } for key, count in sorted(games.items()) for season, club, venue in [key]]


def load_overrides() -> dict:
    if not OVERRIDES.exists():
        return {}
    with OVERRIDES.open(encoding="utf-8") as f:
        return {row["club_code"]: row["wikidata_id"] for row in csv.DictReader(f)
                if row.get("wikidata_id")}


SEARCH = """
SELECT ?item ?label ?desc WHERE {
  SERVICE wikibase:mwapi {
    bd:serviceParam wikibase:endpoint "www.wikidata.org"; wikibase:api "Search";
                    mwapi:srsearch "%s haswbstatement:P641=Q5372"; mwapi:srlimit "10".
    ?item wikibase:apiOutputItem mwapi:title. ?ordinal wikibase:apiOrdinal true.
  }
  ?item wdt:P31/wdt:P279* wd:Q13393265 .
  OPTIONAL { ?item rdfs:label ?label FILTER(LANG(?label) = "en") }
  OPTIONAL { ?item schema:description ?desc FILTER(LANG(?desc) = "en") }
} ORDER BY ?ordinal
"""
NOT_FIRST_TEAM = ("women", "reserve", "youth", "academy", "junior", " b team")


def search_wikidata(session, code: str, names: list):
    """Return the best search hit that is a men's first basketball team.

    The search runs on query.wikidata.org (Wikidata's own search, limited to
    items whose sport is basketball), because the www.wikidata.org API
    rate-limits shared cloud addresses.
    """
    for n, name in enumerate(names):
        text = name.replace('"', " ").replace("\\", " ")
        data = cached_get(session, RAW_DIR / "wikidata" / f"search_{code}_{n}.json.gz",
                          WIKIDATA_SPARQL, params={"query": SEARCH % text, "format": "json"})
        for b in (data or {}).get("results", {}).get("bindings", []):
            text = " ".join(b.get(k, {}).get("value", "") for k in ("label", "desc")).lower()
            if not any(word in text for word in NOT_FIRST_TEAM):
                return b["item"]["value"].rsplit("/", 1)[-1], f"search: {name}"
    return None, None


SPARQL = """
SELECT ?item ?itemLabel ?inception ?dissolved ?website
  (GROUP_CONCAT(DISTINCT ?ownerLabel; separator="; ") AS ?owners)
  (GROUP_CONCAT(DISTINCT ?venueLabel; separator="; ") AS ?venues)
  (GROUP_CONCAT(DISTINCT ?cityLabel; separator="; ") AS ?cities)
  (GROUP_CONCAT(DISTINCT ?countryLabel; separator="; ") AS ?countries)
  (SAMPLE(?venueCoord) AS ?venueCoords) (SAMPLE(?cityCoord) AS ?cityCoords)
WHERE {
  VALUES ?item { %s }
  OPTIONAL { ?item wdt:P571 ?inception }
  OPTIONAL { ?item wdt:P576 ?dissolved }
  OPTIONAL { ?item wdt:P856 ?website }
  OPTIONAL { ?item wdt:P127 ?owner . ?owner rdfs:label ?ownerLabel FILTER(LANG(?ownerLabel) = "en") }
  OPTIONAL { ?item wdt:P115 ?venue . ?venue rdfs:label ?venueLabel FILTER(LANG(?venueLabel) = "en")
             OPTIONAL { ?venue wdt:P625 ?venueCoord } }
  OPTIONAL { ?item wdt:P131|wdt:P159 ?city . ?city rdfs:label ?cityLabel FILTER(LANG(?cityLabel) = "en")
             OPTIONAL { ?city wdt:P625 ?cityCoord } }
  OPTIONAL { ?item wdt:P17 ?country . ?country rdfs:label ?countryLabel FILTER(LANG(?countryLabel) = "en") }
  SERVICE wikibase:label { bd:serviceParam wikibase:language "en". }
}
GROUP BY ?item ?itemLabel ?inception ?dissolved ?website
"""


def point(wkt):
    """Turn Wikidata's "Point(lon lat)" into (lat, lon)."""
    if not wkt or not wkt.startswith("Point("):
        return None, None
    lon, lat = wkt[len("Point("):-1].split()
    return float(lat), float(lon)


def wikidata_rows(session, clubs: dict, seasons: dict) -> list:
    overrides = load_overrides()
    permanent = {}
    for rows in seasons.values():
        for club in rows:
            permanent[club["code"]] = [club.get("clubPermanentName"), club.get("name")]
    matches = {}
    for code, club in clubs.items():
        if code in overrides:
            matches[code] = (overrides[code], "manual")
            continue
        names = permanent.get(code, []) + [(club or {}).get("name")]
        names = list(dict.fromkeys(n for n in names if n))
        qid, how = search_wikidata(session, code, names)
        if qid:
            matches[code] = (qid, how)
    qids = sorted({qid for qid, _ in matches.values()})
    facts = {}
    if qids:
        query = SPARQL % " ".join(f"wd:{q}" for q in qids)
        data = cached_get(session, RAW_DIR / "wikidata" / f"sparql_{len(qids)}.json.gz",
                          WIKIDATA_SPARQL, params={"query": query, "format": "json"})
        for b in data["results"]["bindings"]:
            qid = b["item"]["value"].rsplit("/", 1)[-1]
            value = {k: v["value"] for k, v in b.items()}
            # A club can have several inception dates; keep the earliest.
            if qid not in facts or value.get("inception", "") < facts[qid].get("inception", "~"):
                facts[qid] = value
    print(f"Wikidata: matched {len(matches)} of {len(clubs)} clubs")
    rows = []
    for code in clubs:
        qid, how = matches.get(code, (None, None))
        fact = facts.get(qid, {})
        inception = fact.get("inception", "")
        city_lat, city_lon = point(fact.get("cityCoords"))
        venue_lat, venue_lon = point(fact.get("venueCoords"))
        rows.append({
            "club_code": code,
            "wikidata_id": qid,
            "wikidata_label": fact.get("itemLabel"),
            "match_method": how,
            "founded": inception[:10] or None,
            "founded_year": int(inception[:4]) if inception[:4].isdigit() else None,
            "dissolved": fact.get("dissolved", "")[:10] or None,
            "owners": fact.get("owners") or None,
            "home_venue": fact.get("venues") or None,
            "home_venue_lat": venue_lat,
            "home_venue_lon": venue_lon,
            "city": fact.get("cities") or None,
            "city_lat": city_lat,
            "city_lon": city_lon,
            "country": fact.get("countries") or None,
            "website": fact.get("website"),
            "wikidata_url": f"https://www.wikidata.org/wiki/{qid}" if qid else None,
        })
    return rows


def write_csv(path: Path, rows: list) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    print(f"wrote {path.name} ({len(rows)} rows)")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--from", dest="start", type=int, default=2000)
    parser.add_argument("--to", dest="end", type=int, default=2025)
    parser.add_argument("--out", type=Path, default=ROOT / "data" / "clubs" / "csv")
    parser.add_argument("--skip-wikidata", action="store_true")
    args = parser.parse_args()

    session = requests.Session()
    session.headers["User-Agent"] = USER_AGENT
    seasons, clubs, venues = fetch_euroleague(session, args.start, args.end)
    args.out.mkdir(parents=True, exist_ok=True)
    write_csv(args.out / "club_info.csv", club_info_rows(clubs, seasons))
    write_csv(args.out / "club_seasons.csv", club_season_rows(seasons))
    write_csv(args.out / "all_venues.csv", venue_rows(venues))
    write_csv(args.out / "club_home_venues.csv", home_venue_rows(args.start, args.end))
    if not args.skip_wikidata:
        write_csv(args.out / "club_wikidata.csv", wikidata_rows(session, clubs, seasons))


if __name__ == "__main__":
    main()
