"""Download club crests and player and staff photos, with a credit for each.

Usage:
    python -m eurostats.fetch_media list       # find every image URL (api-live)
    python -m eurostats.fetch_media download   # save the images listed in images.csv

Steps:
    list      saves each season's club and people records as gzipped JSON
              under data/media/raw/ and writes images.csv, one row per image
              URL: what it shows, the seasons it was used, the rights holder,
              the licence and the file it will be saved as.
    download  saves every image in images.csv under data/media/crests/<club>/
              and data/media/people/<person>/ and records the result in
              the status column. Images are hosted on media-cdn.cortextech.io
              and media-cdn.incrowdsports.com.

Every request is cached on disk, so both steps can be stopped and resumed.
The feed only carries each club's current crest, and photos exist from
2015-16 on, for players and head coaches. Images are for private use only:
crests are club trademarks and photos belong to Euroleague Basketball and its
photographers. See docs/image-rights.md.
"""
import argparse
import csv
import gzip
import hashlib
import json
import os
import time
from pathlib import Path

import requests

from eurostats.fetch import COMPETITION

MEDIA_DIR = Path(os.environ.get(
    "EUROSTATS_MEDIA_DIR",
    Path(__file__).resolve().parent.parent / "data" / "media",
))
PAUSE_SECONDS = 0.5
SEASONS = "https://api-live.euroleague.net/v2/competitions/{comp}/seasons/{comp}{season}"
META_URLS = {
    "clubs": SEASONS + "/clubs",
    "people": SEASONS + "/people?limit=5000",
}
USER_AGENT = "eurostats/0.1 (non-commercial EuroLeague fan project)"
CREST_RIGHTS = "the club (trademark); hosted by Euroleague Basketball"
PHOTO_RIGHTS = "Euroleague Basketball and its photographers; player image rights"
LICENCE = "all rights reserved; private use only"


def raw_path(kind: str, season: int) -> Path:
    return MEDIA_DIR / "raw" / f"{COMPETITION}{season}_{kind}.json.gz"


def get_with_retry(session: requests.Session, url: str, **kwargs) -> requests.Response:
    for attempt in range(6):
        try:
            response = session.get(url, timeout=30, **kwargs)
            if response.status_code < 500 and response.status_code != 429:
                return response
            print(f"retry {url}: HTTP {response.status_code}")
        except requests.RequestException as error:
            print(f"retry {url}: {error}")
        time.sleep(5 * 2 ** attempt)
    raise SystemExit(f"giving up on {url}")


def fetch_json(session: requests.Session, kind: str, season: int):
    path = raw_path(kind, season)
    if not path.exists():
        url = META_URLS[kind].format(comp=COMPETITION, season=season)
        response = get_with_retry(session, url)
        response.raise_for_status()
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        with gzip.open(tmp, "wb") as f:
            f.write(response.content)
        tmp.replace(path)
        time.sleep(PAUSE_SECONDS)
    with gzip.open(path, "rt", encoding="utf-8") as f:
        data = json.load(f)
    return data["data"] if isinstance(data, dict) else data


def write_csv(name: str, rows: list[dict]) -> None:
    path = MEDIA_DIR / name
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    print(f"wrote {path} ({len(rows)} rows)")


def read_csv(name: str) -> list[dict]:
    with open(MEDIA_DIR / name, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def image_file(folder: str, owner: str, url: str) -> str:
    """Local path for an image, relative to MEDIA_DIR; one file per URL."""
    digest = hashlib.sha1(url.encode()).hexdigest()[:12]
    suffix = Path(url.split("?")[0]).suffix or ".png"
    return f"{folder}/{owner}/{digest}{suffix}"


def list_images(start: int, end: int) -> None:
    session = requests.Session()
    images = {}

    def add_image(url, kind, subject_type, code, name, club, season, folder, rights):
        if not url:
            return
        entry = images.setdefault(url, {
            "url": url,
            "kind": kind,
            "subject_type": subject_type,
            "subject_code": code,
            "subject_name": name,
            "club_code": club,
            "role": "",
            "first_season": season,
            "last_season": season,
            "source": "api-live.euroleague.net",
            "rights_holder": rights,
            "licence": LICENCE,
            "local_path": image_file(folder, code, url),
            "status": "",
        })
        entry["first_season"] = min(entry["first_season"], season)
        entry["last_season"] = max(entry["last_season"], season)
        return entry

    for season in range(start, end + 1):
        for club in fetch_json(session, "clubs", season):
            add_image((club.get("images") or {}).get("crest"), "crest", "club",
                      club["code"], club.get("name"), club["code"], season,
                      "crests", CREST_RIGHTS)
        for entry in fetch_json(session, "people", season):
            person = entry["person"]
            club = (entry.get("club") or {}).get("code")
            photos = dict(person.get("images") or {})
            photos.update(entry.get("images") or {})
            for kind, url in photos.items():
                image = add_image(url, kind, "person", person["code"], person.get("name"),
                                  club, season, "people", PHOTO_RIGHTS)
                if image:
                    image["role"] = entry.get("typeName")
        print(f"listed {COMPETITION}{season}: {len(images)} images so far", flush=True)

    # Keep download results from an earlier run so a rebuild does not lose them.
    previous = {}
    if (MEDIA_DIR / "images.csv").exists():
        previous = {row["url"]: row["status"] for row in read_csv("images.csv")}
    for url, entry in images.items():
        entry["status"] = previous.get(url, "")
    write_csv("images.csv", list(images.values()))


def download_images(kinds: set[str]) -> None:
    rows = read_csv("images.csv")
    session = requests.Session()
    session.headers["User-Agent"] = USER_AGENT
    todo = [row for row in rows if row["kind"] in kinds]
    for count, row in enumerate(todo, 1):
        path = MEDIA_DIR / row["local_path"]
        if path.exists():
            row["status"] = "ok"
            continue
        response = get_with_retry(session, row["url"])
        if response.ok and response.headers.get("content-type", "").startswith("image/"):
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".tmp")
            tmp.write_bytes(response.content)
            tmp.replace(path)
            row["status"] = "ok"
        else:
            row["status"] = f"HTTP {response.status_code}"
            print(f"failed {row['url']}: {row['status']}")
        time.sleep(PAUSE_SECONDS)
        if count % 200 == 0:
            print(f"{count}/{len(todo)} images", flush=True)
            write_csv("images.csv", rows)
    write_csv("images.csv", rows)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("step", choices=["list", "download"])
    parser.add_argument("--from", dest="start", type=int, default=2000)
    parser.add_argument("--to", dest="end", type=int, default=2025)
    parser.add_argument("--kinds", default="crest,headshot,action",
                        help="image kinds to download (download step)")
    args = parser.parse_args()
    if args.step == "list":
        list_images(args.start, args.end)
    else:
        download_images(set(args.kinds.split(",")))


if __name__ == "__main__":
    main()
