from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd


DB_PATH = Path("data") / "portfolio.db"
TABLE_NAME = "portfolio_holdings"


def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    return sqlite3.connect(DB_PATH)


def _normalize_loaded_at(df: pd.DataFrame) -> pd.DataFrame:
    if "loaded_at" not in df.columns:
        return df
    return df.assign(loaded_at=pd.to_datetime(df["loaded_at"], errors="coerce"))


def load_table(latest_only: bool = False) -> pd.DataFrame:
    if not DB_PATH.exists():
        return pd.DataFrame()
    with _connect() as conn:
        try:
            df = pd.read_sql(f"SELECT * FROM {TABLE_NAME}", conn)
        except Exception:
            return pd.DataFrame()
    df = _normalize_loaded_at(df)
    if latest_only and not df.empty and "loaded_at" in df.columns:
        latest = df["loaded_at"].max()
        df = df[df["loaded_at"] == latest]
    return df


def upsert_holdings(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df

    loaded_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    new_df = df.copy()
    new_df["loaded_at"] = loaded_at

    existing = load_table()
    combined = pd.concat([existing, new_df], ignore_index=True)

    dedupe_cols = [col for col in combined.columns if col != "loaded_at"]
    combined = combined.drop_duplicates(subset=dedupe_cols, keep="first")
    if "loaded_at" in combined.columns:
        combined["loaded_at"] = combined["loaded_at"].astype(str)

    with _connect() as conn:
        combined.to_sql(TABLE_NAME, conn, if_exists="replace", index=False)

    latest = combined[combined["loaded_at"] == loaded_at] if "loaded_at" in combined.columns else combined
    return latest


def clear_table() -> None:
    if not DB_PATH.exists():
        return
    with _connect() as conn:
        conn.execute(f"DROP TABLE IF EXISTS {TABLE_NAME}")
