# archive

Legacy scripts from the pre-modular phase of BatteryOS (early 2023).  
These were monolithic notebooks/scripts that have been superseded by the modular `src/` packages.

| File | Replacement in production |
|------|---------------------------|
| `build_master_ml_dataset.py` | `src/features/builder.py` |
| `clean_dam_data.py` | `src/ingest/enex.py` |
| `download_and_combine_dam.py` | `src/ingest/enex.py` |
| `engineer_advanced_features.py` | `src/features/advanced.py` |
| `fetch_entsoe_dam_prices.py` | `src/ingest/entsoe.py` |
| `fetch_entsoe_entsoepy.py` | `src/ingest/entsoe.py` |
| `fetch_entsoe_residual_load.py` | `src/ingest/entsoe.py` |
| `fetch_openmeteo_weather.py` | `src/ingest/weather.py` |
| `final_preprocessing.py` | `src/features/preprocessing.py` |
| `train_lightgbm_quantile.py` | `src/forecast/train.py` |
| `train_xgboost_baseline.py` | `src/forecast/train.py` |

**No file in this directory is imported by the current production pipeline.** They are preserved for reference and reproducibility of early experiments.
