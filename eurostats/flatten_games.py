"""Turn the per-game JSON files into CSV tables ready for a data model.

Usage:
    python -m eurostats.flatten_games --out data/csv

Tables (one row per ...):
    games.csv          game: phase, round, date, teams, score by quarter,
                       attendance, venue and referee codes
    team_games.csv     team in a game: box score totals, team-only stats
                       (such as team rebounds) and the coach
    player_games.csv   player in a game: full box score line
    players.csv        player: name, birth date, height, country
    clubs.csv          club in a season: the name it played under that season
    venues.csv         venue: name, capacity, address
    referees.csv       referee: name, country
    coaches.csv        coach: name
    plays.csv          play-by-play event: period, clock, team, player,
                       play type and running score (from 2007-08)
    shots.csv          shot: court coordinates, zone, made or missed,
                       fastbreak and second-chance flags (from 2007-08)

Play-by-play and shots name players by their live feed id, such as
"P002328"; dropping the leading "P" gives the box score player code.
"""
import argparse
import csv
import json
from pathlib import Path

from eurostats.fetch import COMPETITION
from eurostats.fetch_games import GAMES_DIR, load_game

STAT_FIELDS = [
    "timePlayed", "valuation", "points",
    "fieldGoalsMade2", "fieldGoalsAttempted2",
    "fieldGoalsMade3", "fieldGoalsAttempted3",
    "freeThrowsMade", "freeThrowsAttempted",
    "fieldGoalsMadeTotal", "fieldGoalsAttemptedTotal",
    "totalRebounds", "defensiveRebounds", "offensiveRebounds",
    "assistances", "steals", "turnovers", "blocksFavour", "blocksAgainst",
    "foulsCommited", "foulsReceived", "plusMinus",
]


def stats_columns(stats: dict, prefix: str = "") -> dict:
    return {prefix + field: (stats or {}).get(field) for field in STAT_FIELDS}


def game_rows(season: int, code: int, game: dict, tables: dict) -> None:
    row = {
        "season": season,
        "game_code": code,
        "phase": game["phaseType"]["code"],
        "group": game["group"]["rawName"],
        "round": game["round"],
        "local_date": game["localDate"],
        "utc_date": game["utcDate"],
        "neutral_venue": game.get("isNeutralVenue"),
        "audience": game.get("audience"),
        "venue_code": (game.get("venue") or {}).get("code"),
    }
    for side, prefix in (("local", "home"), ("road", "away")):
        team = game[side]
        row[f"{prefix}_club_code"] = team["club"]["code"]
        row[f"{prefix}_score"] = team["score"]
        partials = team.get("partials") or {}
        for quarter in range(1, 5):
            row[f"{prefix}_q{quarter}"] = partials.get(f"partials{quarter}")
        extra = partials.get("extraPeriods") or {}
        row[f"{prefix}_overtime"] = sum(extra.values()) if extra else None
        tables["clubs"][(season, team["club"]["code"])] = {
            "season": season,
            "club_code": team["club"]["code"],
            "name": team["club"]["name"],
            "editorial_name": team["club"].get("editorialName"),
            "tv_code": team["club"].get("tvCode"),
        }
    for n in range(1, 5):
        referee = game.get(f"referee{n}")
        row[f"referee{n}_code"] = referee["code"] if referee else None
        if referee:
            tables["referees"][referee["code"]] = {
                "referee_code": referee["code"],
                "name": referee["name"],
                "country_code": (referee.get("country") or {}).get("code"),
            }
    venue = game.get("venue")
    if venue and venue.get("code"):
        tables["venues"][venue["code"]] = {
            "venue_code": venue["code"],
            "name": venue["name"],
            "capacity": venue.get("capacity"),
            "address": venue.get("address"),
        }
    tables["games"].append(row)


def box_score_rows(season: int, code: int, box: dict, tables: dict,
                   clubs: dict | None = None) -> None:
    """clubs maps "local"/"road" to club codes, for box scores with no players."""
    for side in ("local", "road"):
        team = box[side]
        players = team["players"]
        club = (players[0]["player"]["club"]["code"] if players
                else (clubs or {}).get(side))
        coach = team.get("coach") or {}
        if coach.get("code"):
            tables["coaches"][coach["code"]] = {
                "coach_code": coach["code"], "name": coach["name"]}
        tables["team_games"].append({
            "season": season,
            "game_code": code,
            "club_code": club,
            "is_home": side == "local",
            "coach_code": coach.get("code"),
            **stats_columns(team["total"]),
            # Stats credited to the team rather than a player (team rebounds,
            # shot-clock turnovers and so on).
            **stats_columns(team.get("team"), prefix="team_only_"),
        })
        for entry in players:
            player = entry["player"]
            person = player["person"]
            stats = entry["stats"]
            tables["player_games"].append({
                "season": season,
                "game_code": code,
                "club_code": player["club"]["code"],
                "is_home": side == "local",
                "player_code": person["code"],
                "dorsal": stats.get("dorsal"),
                "starter": stats.get("startFive"),
                "position": player.get("positionName"),
                **stats_columns(stats),
            })
            tables["players"][person["code"]] = {
                "player_code": person["code"],
                "name": person["name"],
                "birth_date": (person.get("birthDate") or "")[:10] or None,
                "height_cm": person.get("height"),
                "country_code": (person.get("country") or {}).get("code"),
                "birth_country_code": (person.get("birthCountry") or {}).get("code"),
            }


PERIODS = ("FirstQuarter", "SecondQuarter", "ThirdQuarter", "ForthQuarter")


def clean(value):
    """The live feed pads codes with spaces and uses "" for missing."""
    if isinstance(value, str):
        value = value.strip()
        return value or None
    return value


def player_code(live_id):
    live_id = clean(live_id)
    return live_id[1:] if live_id and live_id.startswith("P") else live_id


def flag(value):
    return None if value in (None, "") else value in ("1", 1, True)


def play_rows(season: int, code: int, pbp: dict, tables: dict) -> None:
    # TeamA is always the home side, so POINTS_A is the home score.
    plays = [(period, play) for period, name in enumerate(PERIODS, 1)
             for play in pbp.get(name) or []]
    for play in pbp.get("ExtraTime") or []:
        # Overtimes share one list; each is five minutes after minute 40.
        plays.append((4 + max(1, -(-(play["MINUTE"] - 40) // 5)), play))
    for period, play in plays:
        tables["plays"].append({
            "season": season,
            "game_code": code,
            "play_number": play["NUMBEROFPLAY"],
            "period": period,
            "minute": play["MINUTE"],
            "clock": clean(play["MARKERTIME"]),
            "club_code": clean(play["CODETEAM"]),
            "player_code": player_code(play["PLAYER_ID"]),
            "dorsal": clean(play["DORSAL"]),
            "play_type": clean(play["PLAYTYPE"]),
            "play_info": clean(play["PLAYINFO"]),
            "comment": clean(play["COMMENT"]),
            "home_score": play["POINTS_A"],
            "away_score": play["POINTS_B"],
        })


def shot_rows(season: int, code: int, shots: dict, tables: dict) -> None:
    for shot in shots.get("Rows") or []:
        tables["shots"].append({
            "season": season,
            "game_code": code,
            "play_number": shot["NUM_ANOT"],
            "minute": shot["MINUTE"],
            "clock": clean(shot["CONSOLE"]),
            "club_code": clean(shot["TEAM"]),
            "player_code": player_code(shot["ID_PLAYER"]),
            "action": clean(shot["ID_ACTION"]),
            "points": shot["POINTS"],
            "coord_x": shot["COORD_X"],
            "coord_y": shot["COORD_Y"],
            "zone": clean(shot["ZONE"]),
            "fastbreak": flag(shot["FASTBREAK"]),
            "second_chance": flag(shot["SECOND_CHANCE"]),
            "points_off_turnover": flag(shot["POINTS_OFF_TURNOVER"]),
            "home_score": shot["POINTS_A"],
            "away_score": shot["POINTS_B"],
            "utc": clean(shot.get("UTC")),
        })


def write_csv(path: Path, rows: list) -> None:
    columns = list(dict.fromkeys(key for row in rows for key in row))
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)
    print(f"wrote {path.name} ({len(rows)} rows)")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", type=Path,
                        default=Path(__file__).resolve().parent.parent / "data" / "csv")
    args = parser.parse_args()

    tables = {name: [] for name in ("games", "team_games", "player_games",
                                         "plays", "shots")}
    tables |= {name: {} for name in ("players", "clubs", "venues", "referees", "coaches")}
    for season_dir in sorted(GAMES_DIR.glob(f"{COMPETITION}*")):
        season = int(season_dir.name[len(COMPETITION):])
        codes = sorted({int(p.name[:4]) for p in season_dir.glob("*.json.gz")})
        for code in codes:
            clubs = None
            if (season_dir / f"{code:04d}_game.json.gz").exists():
                game = load_game("game", season, code)
                game_rows(season, code, game, tables)
                clubs = {side: game[side]["club"]["code"] for side in ("local", "road")}
            if (season_dir / f"{code:04d}_stats.json.gz").exists():
                box_score_rows(season, code, load_game("stats", season, code), tables, clubs)
            for kind, rows in (("pbp", play_rows), ("shots", shot_rows)):
                path = season_dir / f"{code:04d}_{kind}.json.gz"
                if not path.exists():
                    continue
                try:
                    data = load_game(kind, season, code)
                except json.JSONDecodeError:
                    # Seasons before 2007-08 come back as empty responses.
                    continue
                rows(season, code, data, tables)

    args.out.mkdir(parents=True, exist_ok=True)
    for name, rows in tables.items():
        write_csv(args.out / f"{name}.csv",
                  list(rows.values()) if isinstance(rows, dict) else rows)


if __name__ == "__main__":
    main()
