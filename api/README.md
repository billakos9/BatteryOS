# api

Lightweight REST API for dispatch inference and baseline computation.

| File | Purpose |
|------|---------|
| `server.py` | FastAPI/Flask entrypoint exposing health, forecast, and optimize endpoints |
| `inference.py` | Model loading and prediction utilities used by the server |
| `compute_baselines.py` | Baseline forecast generators (naive, seasonal, etc.) for API consumers |

**Status:** Experimental — not wired into the core training or backtest pipelines.
