# Data

Raw datasets are **never committed**. They live under `DATA_DIR` (default `data/raw/`, gitignored). If this repo
sits in OneDrive or Dropbox, point `DATA_DIR` at a folder outside it: several GB would otherwise sync.

`scripts/fetch_data.py` (Phase 1) downloads what a script can reach. Manual steps:

- **Michigan fast-formation** (doi:10.7302/pa3f-4w30, 2.37 GB CSV): a scripted download returned HTTP 403. Download in a
  browser or with Globus into `$DATA_DIR/michigan/`.
- **MIT-Stanford cycle life** (https://data.matr.io/1/): the site needs JavaScript. Download the batch files in a
  browser into `$DATA_DIR/mit/`. File format not yet verified.

Terms and citations: see `THIRD_PARTY.md`.
