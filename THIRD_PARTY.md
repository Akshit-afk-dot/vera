# Third-party software, models and data

## Python dependencies (direct; versions as locked in `uv.lock` on 2026-10-18)

| Package | Version | Licence |
|---|---|---|
| fastapi | 0.146.0 | MIT |
| uvicorn | 0.54.0 | BSD-3-Clause |
| pydantic | 2.14.1 | MIT |
| openai (SDK, used as the client for Nebius Token Factory) | 3.35.1 | Apache-2.0 |
| httpx | 0.28.1 | BSD-3-Clause |
| contree-sdk (Nebius Token Factory Sandboxes) | 0.3.6 | Apache-2.0 |
| python-dotenv | 1.2.4 | BSD-3-Clause |
| PyYAML | 6.0.3 | MIT |
| numpy | 2.5.4 | BSD-3-Clause |
| pandas | 3.0.6 | BSD-3-Clause |
| scipy | 1.18.1 | BSD-3-Clause |
| scikit-learn | 1.9.1 | BSD-3-Clause |
| pyarrow | 26.0.0 | Apache-2.0 |
| h5py | 3.16.0 | BSD-3-Clause |
| openpyxl | 3.1.5 | MIT |
| python-multipart | 0.0.32 | Apache-2.0 |
| pytest, ruff (dev only) | 9.1.1, 0.17.1 | MIT |

Frontend dependencies will be listed here when `web/` is added.

## Models (called at runtime through Nebius Token Factory; not redistributed)

NVIDIA Nemotron models; the exact IDs and their licence terms are recorded from the live catalog in
`docs/phase0/catalog.json` once Phase 0 runs.

## Datasets (never re-hosted here; fetched by `scripts/fetch_data.py` or by hand, see `data/README.md`)

| Dataset | Terms as seen Oct 2026 | Use |
|---|---|---|
| UConn-ISU-ILCC 2025 battery dataset | CC BY 4.0 | REAL cells for planted-fault eval; the only source for bundled synthetic samples |
| University of Michigan fast-formation study (doi:10.7302/pa3f-4w30) | No licence shown; cited, not re-hosted | REAL formation data and lifetimes |
| MIT-Stanford cycle life (Severson et al., Nature Energy 4, 383–391, 2019) | Not stated; cited, not re-hosted | REAL lifetimes |
| NASA PCoE Li-ion battery aging | Use at own risk; repository and donors acknowledged | REAL, file-format variety |
| Oxford Battery Degradation Dataset 1 | ODbL 1.0; credited, not re-hosted | REAL, file-format variety |
| CALCE battery data | All rights reserved; cited, not re-hosted | REAL, file-format variety |
