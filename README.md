# EuroLeague History & Trends

A free fan site about how EuroLeague basketball has changed over the years:
league-wide trends since 2007, club histories and player career arcs.

## Run it

```bash
pip install -r requirements.txt
python -m eurostats.fetch --from 2007 --to 2025   # downloads into data/raw/
python -m eurostats.app                           # opens http://localhost:8080
```

## Data

Data comes from EuroLeague's public stats feed (`api-live.euroleague.net`)
through the [euroleague-api](https://pypi.org/project/euroleague-api/) package.
The fetch step pauses between requests and caches every season on disk, so it
only downloads what is missing.

This is a non-commercial fan project. Statistics belong to Euroleague
Basketball; no logos or photos are used.
