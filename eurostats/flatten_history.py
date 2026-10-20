"""Turn the history downloads into CSV tables ready for a data model.

Usage:
    python -m eurostats.flatten_history --out data/csv \
        --results data/raw/results.csv

Tables from the EuroLeague feed (2000-01 on), one row per ...:
    season_phases.csv          phase of a season: regular season, Top 16,
                               play-in, playoffs, Final Four; dates, rounds,
                               number of groups and teams
    season_rounds.csv          round of a season: phase, name, dates
    standings.csv              club in a group phase: final position, record,
                               points for and against, home and away record
    season_finish.csv          club in a season: last phase and round played,
                               final place (1 to 4 where known), who knocked
                               it out
    final_four_games.csv       Final Four game: semifinal, third place or final
    player_bios.csv            player: name, birth date and country,
                               nationality, height, weight, latest position
    player_registrations.csv   player on a club's roster in a season: shirt
                               number, position, height and weight then,
                               registration dates

Tables from Wikipedia and Wikidata (all years, 1957-58 on), one row per ...:
    titles.csv                 season: champion, runner-up, final score, venue
    final_four_places.csv      club in a Final Four or final tournament: place
    awards.csv                 award given to a player or coach in a season
                               (MVP, Final Four MVP, All-EuroLeague teams,
                               Coach of the Year, Rising Star)
    wiki_tables.csv            every cell of every table on those pages, as
                               downloaded, for anything the tables above miss
    wikidata_player_codes.csv  Wikidata item to EuroLeague player code

Club and player codes are the feed's, the same as in the box score tables.
Wikipedia rows carry the linked page's Wikidata ID (QID) and, for players,
the feed player code when Wikidata records it. Clubs before 2000 have no feed
code; match them on QID.

Seasons are named by the year they start (2000 = 2000-01), like the feed.
"""
import argparse
import csv
import gzip
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

import pandas as pd

from eurostats.fetch_history import (COMPETITION, HISTORY_DIR, PEOPLE_DIRS,
                                     WIKI_PAGES, items, load)

FEED_DIR = HISTORY_DIR / "feed"
WIKI_DIR = HISTORY_DIR / "wikipedia"
WIKIDATA_DIR = HISTORY_DIR / "wikidata"


def feed_file(season: int, kind: str):
    for directory in (FEED_DIR, *PEOPLE_DIRS):
        path = directory / f"{COMPETITION}{season}_{kind}.json.gz"
        if path.exists():
            return load(path)
    return None


def feed_seasons() -> list:
    return sorted(int(p.name[len(COMPETITION):len(COMPETITION) + 4])
                  for p in FEED_DIR.glob(f"{COMPETITION}*_phases.json.gz"))


# ---------------------------------------------------------------- feed ---

def standings_files(season: int) -> dict:
    """{phase code: standings} for the last round of each group phase."""
    found = {}
    for path in FEED_DIR.glob(f"{COMPETITION}{season}_standings_*.json.gz"):
        phase = path.name.split("_")[2]
        found[phase] = load(path)
    return found


def season_tables(results: pd.DataFrame, tables: dict) -> None:
    for season in feed_seasons():
        phases = items(feed_file(season, "phases"))
        rounds = items(feed_file(season, "rounds"))
        standings = standings_files(season)
        played = results[results["season"] == season]
        for r in sorted(rounds, key=lambda r: r["round"]):
            tables["season_rounds"].append({
                "season": season,
                "phase_code": r["phaseTypeCode"],
                "round": r["round"],
                "name": r["name"],
                "start_date": r["minGameStartDate"][:10],
                "end_date": r["maxGameStartDate"][:10],
            })
        for p in sorted(phases, key=lambda p: p["order"]):
            code = p["phaseType"]["code"]
            phase_rounds = [r["round"] for r in rounds if r["phaseTypeCode"] == code]
            games = played[played["Phase"] == code]
            teams = standings.get(code, {}).get("teams", [])
            tables["season_phases"].append({
                "season": season,
                "phase_code": code,
                "phase_name": p["phaseType"]["name"],
                "phase_order": p["order"],
                "is_group_phase": p["phaseType"]["isGroupPhase"],
                # The feed lists some phases that were never played, such as
                # 2000-01 eighthfinals (played inside the playoffs).
                "has_games": p["hasGames"],
                "start_date": (p.get("startDate") or "")[:10] or None,
                "end_date": (p.get("endDate") or "")[:10] or None,
                "first_round": min(phase_rounds, default=None),
                "last_round": max(phase_rounds, default=None),
                "round_count": len(phase_rounds),
                "group_count": len({t["groupName"] for t in teams}) or None,
                "team_count": len(set(games["homecode"]) | set(games["awaycode"])) or None,
                "game_count": len(games),
            })
        for phase, data in standings.items():
            for t in data["teams"]:
                tables["standings"].append({
                    "season": season,
                    "phase_code": phase,
                    "group": t["groupName"],
                    "position": t["position"],
                    "club_code": t["club"]["code"],
                    "club_name": t["club"]["name"],
                    "games_played": t["gamesPlayed"],
                    "won": t["gamesWon"],
                    "lost": t["gamesLost"],
                    "points_for": t["pointsFor"],
                    "points_against": t["pointsAgainst"],
                    "home_record": t["homeRecord"],
                    "away_record": t["awayRecord"],
                    "neutral_record": t["neutralRecord"],
                    "overtime_record": t["overtimeRecord"],
                    # Only filled in for recent seasons; false everywhere before.
                    "qualified": t["qualified"],
                })
        winner = next((d["winner"]["code"] for d in standings.values()
                       if d.get("winner")), None)
        finish_rows(season, played, phases, rounds, winner, tables)


def finish_rows(season, played, phases, rounds, champion, tables) -> None:
    order = {p["phaseType"]["code"]: p["order"] for p in phases}
    round_names = {r["round"]: r["name"] for r in rounds}
    games = played.assign(order=played["Phase"].map(order)).sort_values(
        ["order", "Round", "gameCode"])
    games = games.assign(winner=games["homecode"].where(
        games["homescore"] > games["awayscore"], games["awaycode"]))
    places = {}
    if champion is not None:
        places[champion] = 1
        final = games[(games["homecode"] == champion) | (games["awaycode"] == champion)].iloc[-1]
        runner_up = final["awaycode"] if final["homecode"] == champion else final["homecode"]
        places[runner_up] = 2
        ff = games[games["Phase"] == "FF"]
        if len(ff):
            last_round = ff[ff["Round"] == ff["Round"].max()]
            for _, game in last_round.iterrows():
                is_final = champion in (game["homecode"], game["awaycode"])
                if not is_final:
                    loser = game["awaycode"] if game["winner"] == game["homecode"] else game["homecode"]
                    places[game["winner"]], places[loser] = 3, 4
            for _, game in ff.iterrows():
                if game["Round"] == ff["Round"].max():
                    stage = "Final" if champion in (game["homecode"], game["awaycode"]) else "Third place"
                else:
                    stage = round_names.get(game["Round"], "Semifinal")
                tables["final_four_games"].append({
                    "season": season,
                    "game_code": game["gameCode"],
                    "stage": stage,
                    "home_club_code": game["homecode"],
                    "home_score": game["homescore"],
                    "away_club_code": game["awaycode"],
                    "away_score": game["awayscore"],
                    "winner_club_code": game["winner"],
                })
            # Seasons without a third-place game share third place.
            for club in set(ff["homecode"]) | set(ff["awaycode"]):
                places.setdefault(club, 3)
    for club in sorted(set(games["homecode"]) | set(games["awaycode"])):
        mine = games[(games["homecode"] == club) | (games["awaycode"] == club)]
        last = mine.iloc[-1]
        knocked_out_by = None
        if order.get(last["Phase"], 0) > 1 and last["winner"] != club:
            knocked_out_by = last["winner"]
        tables["season_finish"].append({
            "season": season,
            "club_code": club,
            "games": len(mine),
            "won": int((mine["winner"] == club).sum()),
            "last_phase_code": last["Phase"],
            "last_round": last["Round"],
            "last_round_name": round_names.get(last["Round"]),
            "final_place": places.get(club),
            "champion": club == champion,
            "knocked_out_by_club_code": knocked_out_by,
        })


PERSON_FIELDS = {
    "name": lambda p: p["name"],
    "passport_name": lambda p: p.get("passportName"),
    "passport_surname": lambda p: p.get("passportSurname"),
    "birth_date": lambda p: (p.get("birthDate") or "")[:10] or None,
    "birth_country_code": lambda p: (p.get("birthCountry") or {}).get("code"),
    "country_code": lambda p: (p.get("country") or {}).get("code"),
    "country_name": lambda p: (p.get("country") or {}).get("name"),
    "height_cm": lambda p: p.get("height") or None,
    "weight_kg": lambda p: p.get("weight") or None,
}


def player_tables(tables: dict) -> None:
    """Bios from each season's people list; type J is a player."""
    bios = {}
    for season in feed_seasons():
        for entry in items(feed_file(season, "people")):
            if entry["type"] != "J":
                continue
            person = entry["person"]
            code = person["code"]
            tables["player_registrations"].append({
                "season": season,
                "player_code": code,
                "club_code": entry["club"]["code"],
                "dorsal": entry.get("dorsal"),
                "position": entry.get("positionName"),
                "height_cm": person.get("height") or None,
                "weight_kg": person.get("weight") or None,
                "start_date": (entry.get("startDate") or "")[:10] or None,
                "end_date": (entry.get("endDate") or "")[:10] or None,
                "active": entry.get("active"),
            })
            bio = bios.setdefault(code, {"player_code": code, "first_season": season})
            bio["last_season"] = season
            # Later seasons win, but a missing value never hides a known one.
            for field, get in PERSON_FIELDS.items():
                value = get(person)
                if value not in (None, ""):
                    bio[field] = value
            if entry.get("positionName"):
                bio["position"] = entry["positionName"]
    for bio in bios.values():
        tables["player_bios"].append({
            "player_code": bio["player_code"],
            **{field: bio.get(field) for field in PERSON_FIELDS},
            "position": bio.get("position"),
            "first_season": bio["first_season"],
            "last_season": bio["last_season"],
        })


# ---------------------------------------------------------- wikipedia ---

def wiki_page(key: str):
    path = WIKI_DIR / f"{key}.json.gz"
    if not path.exists():
        return None
    data = load(path)
    return data.get("parse")


def table_grids(html: str) -> list:
    """Each wikitable as a grid of cells, with rowspan and colspan filled in.

    A cell is {"text", "links", "header"}; links are linked page titles.
    """
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "lxml")
    grids = []
    for table in soup.select("table.wikitable"):
        grid, pending = [], {}
        for tr in table.find_all("tr"):
            row, col = [], 0
            cells = tr.find_all(["th", "td"], recursive=False)
            while cells or col in pending:
                if col in pending:
                    cell, left = pending[col]
                    row.append(cell)
                    if left > 1:
                        pending[col] = (cell, left - 1)
                    else:
                        del pending[col]
                    col += 1
                    continue
                tag = cells.pop(0)
                for sup in tag.select("sup.reference"):
                    sup.decompose()
                cell = {
                    "text": " ".join(tag.get_text(" ", strip=True).split()),
                    "links": [a["title"] for a in tag.select("a[title]")
                              if not a.get("href", "").startswith("#")
                              and "redlink=1" not in a.get("href", "")],
                    "header": tag.name == "th",
                }
                span = int(re.sub(r"\D", "", tag.get("colspan", "1")) or 1)
                down = int(re.sub(r"\D", "", tag.get("rowspan", "1")) or 1)
                for _ in range(span):
                    row.append(cell)
                    if down > 1:
                        pending[col] = (cell, down - 1)
                    col += 1
            if row:
                grid.append(row)
        grids.append(grid)
    return grids


def split_header(grid: list) -> tuple:
    """Header names (joined across header rows) and the data rows."""
    head = []
    while grid and all(c["header"] for c in grid[0]):
        head.append(grid[0])
        grid = grid[1:]
    width = max((len(r) for r in head + grid), default=0)
    names = []
    for i in range(width):
        parts = [r[i]["text"] for r in head if i < len(r) and r[i]["text"]]
        names.append(" / ".join(dict.fromkeys(parts)))
    return names, grid


SEASON = re.compile(r"\b(19[5-9]\d|20\d\d)\s*[–\-/]\s*(\d{2,4})\b")
YEAR = re.compile(r"\b(19[5-9]\d|20\d\d)\b")


def parse_season(text: str):
    """1957–58 -> 1957. A bare year is the year the season ended."""
    if not text:
        return None
    match = SEASON.search(text)
    if match:
        return int(match.group(1))
    match = YEAR.search(text)
    return int(match.group(1)) - 1 if match else None


def wiki_link_titles() -> set:
    titles = set()
    for key in WIKI_PAGES:
        page = wiki_page(key)
        if page:
            for grid in table_grids(page["text"]):
                titles.update(t for row in grid for c in row for t in c["links"])
    return titles


def qid_map() -> dict:
    """Linked page title -> Wikidata ID, following redirects."""
    titles = {}
    for path in sorted(WIKI_DIR.glob("pageprops_*.json.gz")):
        query = load(path).get("query", {})
        qids = {p["title"]: p.get("pageprops", {}).get("wikibase_item")
                for p in query.get("pages", [])}
        for step in ("normalized", "redirects"):
            for r in query.get(step, []):
                titles[r["from"]] = r["to"]
        titles.update({t: t for t in qids})
        for source, target in list(titles.items()):
            while target in titles and titles[target] != target:
                target = titles[target]
            titles[source] = qids.get(target, titles[source])
    return {t: q for t, q in titles.items() if q and q.startswith("Q")}


def wikidata_player_codes(tables: dict) -> dict:
    """QID -> feed player code, from Wikidata's EuroLeague player ID."""
    path = WIKIDATA_DIR / "euroleague_properties.json.gz"
    if not path.exists():
        return {}
    codes = {}
    for prop in load(path)["results"]["bindings"]:
        pid = prop["property"]["value"].rsplit("/", 1)[-1]
        label = prop["label"]["value"]
        values = WIKIDATA_DIR / f"{pid}_values.json.gz"
        if "player" not in label.lower() or not values.exists():
            continue
        for row in load(values)["results"]["bindings"]:
            qid = row["item"]["value"].rsplit("/", 1)[-1]
            # euroleague.net player IDs are the feed code, sometimes with
            # the live feed's leading "P".
            value = row["value"]["value"].strip()
            code = value[1:] if re.fullmatch(r"P\w+", value) and len(value) > 3 else value
            tables["wikidata_player_codes"].append({
                "qid": qid, "name": row.get("itemLabel", {}).get("value"),
                "player_code": code, "wikidata_property": pid,
                "wikidata_value": value})
            codes.setdefault(qid, code)
    return codes


def column(names: list, *words, avoid=()) -> int | None:
    for i, name in enumerate(names):
        low = name.lower()
        if any(w in low for w in words) and not any(a in low for a in avoid):
            return i
    return None


def cell_link(row, i, qids):
    if i is None or i >= len(row):
        return None, None, None
    cell = row[i]
    title = cell["links"][0] if cell["links"] else None
    # Flag links come first in some cells; the name is the last link.
    named = [t for t in cell["links"] if not t.lower().startswith(("flag of", "list of"))]
    title = named[-1] if named else title
    return cell["text"] or None, title, qids.get(title)


def wiki_tables(tables: dict) -> None:
    qids = qid_map()
    player_codes = wikidata_player_codes(tables)
    for key in WIKI_PAGES:
        page = wiki_page(key)
        if not page:
            continue
        for t, grid in enumerate(table_grids(page["text"])):
            names, rows = split_header(grid)
            for r, row in enumerate(rows):
                for c, cell in enumerate(row):
                    tables["wiki_tables"].append({
                        "page": page["title"], "revision": page["revid"],
                        "table": t, "row": r, "column": c,
                        "header": names[c] if c < len(names) else None,
                        "text": cell["text"],
                        "links": "|".join(cell["links"]) or None,
                        "qids": "|".join(filter(None, (qids.get(x) for x in cell["links"]))) or None,
                    })
            awards_from_table(key, page, names, rows, qids, player_codes, tables)


def awards_from_table(key, page, names, rows, qids, player_codes, tables) -> None:
    season_col = column(names, "season", "year", "edition")
    if season_col is None:
        return
    if key == "finals" or key == "final_four":
        champ = column(names, "champion", "winner", "first")
        runner = column(names, "runner", "second", "finalist")
        third = column(names, "third")
        fourth = column(names, "fourth")
        score = column(names, "score", "result")
        venue = column(names, "venue", "arena", "host", "location", "city")
        for row in rows:
            season = parse_season(row[season_col]["text"]) if season_col < len(row) else None
            if season is None:
                continue
            if key == "finals" and champ is not None:
                c_text, c_title, c_qid = cell_link(row, champ, qids)
                r_text, r_title, r_qid = cell_link(row, runner, qids)
                v_text, _, v_qid = cell_link(row, venue, qids)
                tables["titles"].append({
                    "season": season, "champion": c_text, "champion_qid": c_qid,
                    "runner_up": r_text, "runner_up_qid": r_qid,
                    "final_score": cell_link(row, score, qids)[0],
                    "venue": v_text, "venue_qid": v_qid,
                    "source": page["title"]})
            for place, col in ((1, champ), (2, runner), (3, third), (4, fourth)):
                text, title, qid = cell_link(row, col, qids)
                if text:
                    tables["final_four_places"].append({
                        "season": season, "place": place, "club": text,
                        "club_qid": qid, "source": page["title"]})
        return
    # Award pages: every linked person in a row is an award winner; the
    # column header says which team (All-EuroLeague first or second team).
    club_col = column(names, "team", "club", avoid=("first", "second", "all-"))
    for row in rows:
        season = parse_season(row[season_col]["text"]) if season_col < len(row) else None
        if season is None:
            continue
        club_text, _, club_qid = cell_link(row, club_col, qids)
        seen = set()
        for c, cell in enumerate(row):
            if c in (season_col, club_col) or id(cell) in seen:
                continue
            seen.add(id(cell))
            header = names[c] if c < len(names) else ""
            low = header.lower()
            if any(w in low for w in ("nationality", "country", "position", "ref", "note")):
                continue
            for title in cell["links"]:
                qid = qids.get(title)
                if title.lower().startswith(("flag of", "list of")) or not qid:
                    continue
                tables["awards"].append({
                    "award": key, "season": season, "detail": header or None,
                    "name": title, "qid": qid,
                    "player_code": player_codes.get(qid),
                    "club": club_text, "club_qid": club_qid,
                    "source": page["title"]})


def write_csv(path: Path, rows: list) -> None:
    if not rows:
        print(f"skipped {path.name} (nothing downloaded for it yet)")
        return
    columns = list(dict.fromkeys(key for row in rows for key in row))
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)
    print(f"wrote {path.name} ({len(rows)} rows)")


def load_results(path: Path | None) -> pd.DataFrame:
    if path:
        return pd.read_csv(path)
    from eurostats.fetch import load_raw
    return load_raw("results")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", type=Path,
                        default=Path(__file__).resolve().parent.parent / "data" / "csv")
    parser.add_argument("--results", type=Path,
                        help="results CSV; default is the parquet files from eurostats.fetch")
    args = parser.parse_args()

    tables = defaultdict(list)
    results = load_results(args.results)
    results = results[results["played"].astype(bool)]
    season_tables(results, tables)
    player_tables(tables)
    wiki_tables(tables)

    args.out.mkdir(parents=True, exist_ok=True)
    for name in ("season_phases", "season_rounds", "standings", "season_finish",
                 "final_four_games", "player_bios", "player_registrations",
                 "titles", "final_four_places", "awards", "wiki_tables",
                 "wikidata_player_codes"):
        write_csv(args.out / f"{name}.csv", tables[name])


if __name__ == "__main__":
    main()
