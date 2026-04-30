# scripts

Operational helper scripts for deployment, cron scheduling, and local development.

| File | Purpose |
|------|---------|
| `setup_cron.sh` | Installs the daily inference cron job (`pipelines/daily_inference.py`) |
| `start.sh` | Production server start script (API + optional UI) |
| `start_dev.py` | Local development server launcher with hot-reload |

These are **not** part of the core ML/optimization pipeline; they are infrastructure glue.
