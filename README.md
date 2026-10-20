# EuroLeague History & Trends

A free fan site about how EuroLeague basketball has changed over the years:
league-wide trends since 2007, club histories and player career arcs.

## Run it

```bash
pip install -r requirements.txt
python -m eurostats.fetch --from 2000 --to 2025   # downloads into data/raw/
python -m eurostats.app                           # opens http://localhost:8080
```

For per-game detail (box scores for every player in every game since 2000-01):

```bash
python -m eurostats.fetch_games      # raw JSON per game into data/games/, resumable
python -m eurostats.flatten_games    # CSV tables into data/csv/
```

For club crests and player and coach photos (private use only, see
[docs/image-rights.md](docs/image-rights.md)):

```bash
python -m eurostats.fetch_media list       # images.csv: every image URL with its credit
python -m eurostats.fetch_media download   # saves them under data/media/, resumable
```

The image hosts (`media-cdn.cortextech.io`, `media-cdn.incrowdsports.com`) are
not reachable from the cloud environment, so the download runs locally.

## Data

Data comes from EuroLeague's public stats feed (`api-live.euroleague.net`)
through the [euroleague-api](https://pypi.org/project/euroleague-api/) package.
The fetch step pauses between requests and caches every season on disk, so it
only downloads what is missing.

What the feed has (checked October 2026):

- Results and team season totals for every season from 2000-01, all phases.
- Per-game box scores with player details from 2000-01
  (`/v3/competitions/E/seasons/E2000/games/1/stats` on `api-live.euroleague.net`).
- Play-by-play and shot locations live on a second host, `live.euroleague.net`,
  which is not reachable from the cloud environment yet.
- Team names in season totals are today's club names, not the name the club
  played under that season. The results file keeps the historical names.

This is a non-commercial fan project. Statistics belong to Euroleague
Basketball; no logos or photos are used.
