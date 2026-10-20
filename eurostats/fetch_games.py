"""Download every game at the finest level the feed offers, one file per game.

Usage:
    python -m eurostats.fetch_games --from 2000 --to 2025
    python -m eurostats.fetch_games --kinds pbp,shots   # needs live.euroleague.net

Responses are stored untouched as gzipped JSON under data/games/E<season>/,
so nothing is lost and any table can be rebuilt from them later. Files already
on disk are skipped, so the download can be stopped and resumed. Run
eurostats.fetch first: the game list comes from the saved results.

Kinds:
    stats   box score with every player's line and bio (api-live, from 2000-01)
    game    game header: date, venue, referees, attendance, quarter scores
    pbp     play-by-play (live.euroleague.net)
    shots   shot locations (live.euroleague.net)
"""
import argparse
import gzip
import json
import os
import time
from pathlib import Path

import requests

from eurostats.fetch import COMPETITION, load_raw

GAMES_DIR = Path(os.environ.get(
    "EUROSTATS_GAMES_DIR",
    Path(__file__).resolve().parent.parent / "data" / "games",
))
PAUSE_SECONDS = 1.5
RATE_LIMIT_WAITS = [60, 120, 300, 600, 900, 900]
V2 = "https://api-live.euroleague.net/v2/competitions/{comp}/seasons/{comp}{season}/games/{game}"
V3 = "https://api-live.euroleague.net/v3/competitions/{comp}/seasons/{comp}{season}/games/{game}"
LIVE = "https://live.euroleague.net/api/{endpoint}?gamecode={game}&seasoncode={comp}{season}"
URLS = {
    "stats": V3 + "/stats",
    "game": V2,
    "pbp": LIVE.replace("{endpoint}", "PlaybyPlay"),
    "shots": LIVE.replace("{endpoint}", "Points"),
}


def game_path(kind: str, season: int, game: int) -> Path:
    return GAMES_DIR / f"{COMPETITION}{season}" / f"{game:04d}_{kind}.json.gz"


def load_game(kind: str, season: int, game: int):
    with gzip.open(game_path(kind, season, game), "rt", encoding="utf-8") as f:
        return json.load(f)


def fetch_game(session: requests.Session, kind: str, season: int, game: int) -> bool:
    """Save one response; return True if a request was made."""
    path = game_path(kind, season, game)
    if path.exists():
        return False
    url = URLS[kind].format(comp=COMPETITION, season=season, game=game)
    response = session.get(url, timeout=30)
    if response.status_code == 404:
        print(f"missing {kind} {COMPETITION}{season} game {game}")
        return True
    response.raise_for_status()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with gzip.open(tmp, "wb") as f:
        f.write(response.content)
    tmp.replace(path)
    return True


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--from", dest="start", type=int, default=2000)
    parser.add_argument("--to", dest="end", type=int, default=2025)
    parser.add_argument("--kinds", default="stats,game")
    args = parser.parse_args()
    kinds = args.kinds.split(",")

    results = load_raw("results")
    results = results[results["played"].astype(bool)
                      & results["season"].between(args.start, args.end)]
    session = requests.Session()
    for season, games in results.groupby("season"):
        codes = sorted(games["gameCode"].astype(int).unique())
        for game in codes:
            for kind in kinds:
                # The feed answers 429 when asked too fast; back off for minutes.
                for wait in RATE_LIMIT_WAITS:
                    try:
                        requested = fetch_game(session, kind, season, game)
                        break
                    except requests.RequestException as error:
                        print(f"retry {kind} {season} {game} in {wait}s: {error}", flush=True)
                        time.sleep(wait)
                else:
                    raise SystemExit(f"giving up on {kind} {season} game {game}")
                if requested:
                    time.sleep(PAUSE_SECONDS)
        print(f"done {COMPETITION}{season}: {len(codes)} games", flush=True)


if __name__ == "__main__":
    main()
