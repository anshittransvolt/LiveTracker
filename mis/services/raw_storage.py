"""
Raw Storage Service
===================
Stores fetched telemetry raw data by day under a month-partitioned folder.

File layout (default): <project_root>/data/raw/<YYYY-MM>/<YYYY-MM-DD>.csv.gz
"""
from __future__ import annotations

import os
from pathlib import Path
from datetime import date
import pandas as pd
from django.conf import settings
import logging

logger = logging.getLogger(__name__)


def _get_base_dir() -> Path:
    # Default under project base dir
    base = getattr(settings, "RAW_DATA_ROOT", None)
    if base:
        return Path(base)
    # Fallback: project root two levels up from this file
    return Path(settings.BASE_DIR) / "data" / "raw"


def save_daily_raw(df: pd.DataFrame, day: date) -> str:
    """Save dataframe as gzipped CSV under month/day path.

    Returns the full file path saved (string).
    """
    base = _get_base_dir()
    month_dir = base / day.strftime("%Y-%m")
    month_dir.mkdir(parents=True, exist_ok=True)
    file_path = month_dir / f"{day.strftime('%Y-%m-%d')}.csv.gz"

    try:
        # Ensure consistent column order for stability
        df.to_csv(file_path, index=False, compression="gzip")
        logger.info(f"Saved raw telemetry: {file_path}")
        return str(file_path)
    except Exception as e:
        logger.error(f"Failed to save raw telemetry for {day}: {e}")
        raise
