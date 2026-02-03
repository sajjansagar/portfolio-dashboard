# Added derived exit fields and rule-based exit classification.
import numpy as np
import pandas as pd


NUMERIC_COLUMNS = [
    "Qty",
    "Avg Cost",
    "CMP",
    "Value at Cost",
    "Value at Market Price",
    "Realized P&L",
    "Unrealized P&L",
    "Unrealized P&L %",
]


def _clean_numeric(series: pd.Series) -> pd.Series:
    cleaned = (
        series.astype(str)
        .str.replace(",", "", regex=False)
        .str.replace("₹", "", regex=False)
        .str.replace("%", "", regex=False)
        .str.replace(" ", "", regex=False)
        .str.replace("(", "-", regex=False)
        .str.replace(")", "", regex=False)
        .str.replace("+", "", regex=False)
        .str.strip()
        .replace({"": np.nan, "nan": np.nan, "None": np.nan})
    )
    return pd.to_numeric(cleaned, errors="coerce")


def normalize_numeric_columns(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    for column in NUMERIC_COLUMNS:
        if column in df.columns:
            df[column] = _clean_numeric(df[column])
    return df


def add_unrealized_bucket(df: pd.DataFrame) -> pd.DataFrame:
    if "Unrealized P&L % Bucket" in df.columns:
        return df
    if "Unrealized P&L %" not in df.columns:
        df["Unrealized P&L % Bucket"] = pd.Series(dtype="object")
        return df
    buckets = [-float("inf"), -20, -10, 0, 10, 20, float("inf")]
    labels = [
        "<= -20%",
        "-20% to -10%",
        "-10% to 0%",
        "0% to 10%",
        "10% to 20%",
        "> 20%",
    ]
    df["Unrealized P&L % Bucket"] = pd.cut(
        df["Unrealized P&L %"],
        bins=buckets,
        labels=labels,
        include_lowest=True,
    )
    return df


def _ensure_required_columns(df: pd.DataFrame, required: list[str]) -> None:
    missing = [col for col in required if col not in df.columns]
    if missing:
        raise ValueError(f"Missing required columns: {', '.join(missing)}")


def add_exit_fields(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    required = ["Unrealized P&L", "Unrealized P&L %",
                "Value at Market Price", "Avg Cost", "CMP"]
    _ensure_required_columns(df, required)

    df["pnl_abs"] = df["Unrealized P&L"].fillna(0)
    df["pnl_pct"] = df["Unrealized P&L %"].fillna(0)
    df["exposure"] = df["Value at Market Price"].fillna(0)
    total_value = df["exposure"].sum()
    df["total_value"] = total_value
    df["exposure_pct"] = np.where(
        total_value > 0, df["exposure"] / total_value * 100, 0)
    df["recovery_required_pct"] = np.where(
        df["CMP"].fillna(0) > 0,
        (df["Avg Cost"] / df["CMP"] - 1) * 100,
        np.nan,
    )
    df["drag_score"] = (-df["pnl_abs"].clip(upper=0)) * \
        (df["exposure_pct"] / 100)

    tagged = df.apply(classify_exit, axis=1, result_type="expand")
    df["exit_tag"] = tagged["tag"]
    df["exit_bucket"] = tagged["bucket"]
    df["exit_reasons"] = tagged["reasons"]
    df["suggested_sell_pct"] = tagged["suggested_sell_pct"]
    df["tranche_plan"] = tagged["tranche_plan"]
    df["risk_flag"] = tagged["risk_flag"]

    return df


def classify_exit(row: pd.Series) -> dict:
    pnl_pct = row.get("pnl_pct", 0)
    exposure_pct = row.get("exposure_pct", 0)
    recovery_required_pct = row.get("recovery_required_pct", np.nan)

    reasons = []
    tag = "HOLD"
    bucket = "Hold"

    if pnl_pct <= -50 or recovery_required_pct >= 70:
        tag = "EXIT"
        bucket = "Structural Loser"
        if pnl_pct <= -50:
            reasons.append("Loss > 50%")
        if recovery_required_pct >= 70:
            reasons.append("Recovery required > 70%")
    elif pnl_pct <= -30 and exposure_pct >= 5:
        tag = "EXIT"
        bucket = "High Drag"
        reasons.append("High exposure drag (>=5%)")
    elif (-30 < pnl_pct <= -15) or (pnl_pct <= -15 and 2 <= exposure_pct < 5):
        tag = "PARTIAL EXIT"
        bucket = "Controlled Exit"
        reasons.append("Moderate loss; controlled exit suggested")
    else:
        tag = "HOLD"
        bucket = "Hold"
        reasons.append("Loss manageable")

    risk_flag = pnl_pct <= -25
    if tag == "EXIT":
        suggested_sell_pct = 100
        tranche_plan = "Sell in 2–3 tranches over 3–7 sessions depending on liquidity."
    elif tag == "PARTIAL EXIT":
        suggested_sell_pct = 35
        tranche_plan = (
            "Sell 30–40% now; place stop-loss ~10% below CMP on remainder; exit if breakdown."
        )
    else:
        suggested_sell_pct = 0
        tranche_plan = "Hold; review if loss breaches -25% or recovery_required_pct rises sharply."

    return {
        "tag": tag,
        "bucket": bucket,
        "reasons": "; ".join(reasons),
        "suggested_sell_pct": suggested_sell_pct,
        "tranche_plan": tranche_plan,
        "risk_flag": risk_flag,
    }


def load_portfolio(data: pd.DataFrame) -> pd.DataFrame:
    df = data.copy()

    rename_map = {
        "Average Cost Price": "Avg Cost",
        "Current Market Price": "CMP",
        "Value At Cost": "Value at Cost",
        "Value At Market Price": "Value at Market Price",
        "Realized Profit / Loss": "Realized P&L",
        "Unrealized Profit/Loss": "Unrealized P&L",
        "Unrealized Profit/Loss %": "Unrealized P&L %",
    }
    df = df.rename(
        columns={k: v for k, v in rename_map.items() if k in df.columns})

    if "% Change" in df.columns and "Unrealized P&L %" not in df.columns:
        df = df.rename(columns={"% Change": "Unrealized P&L %"})
    if "% Change over prev close" in df.columns and "Unrealized P&L %" not in df.columns:
        df = df.rename(
            columns={"% Change over prev close": "Unrealized P&L %"})

    df = normalize_numeric_columns(df)

    unnamed = [col for col in df.columns if col.startswith("Unnamed")]
    df = df.drop(columns=unnamed)

    unused = [col for col in df.columns if df[col].isna().all()]
    df = df.drop(columns=unused)

    if "Value at Cost" not in df.columns:
        if {"Qty", "Avg Cost"}.issubset(df.columns):
            df["Value at Cost"] = df["Qty"] * df["Avg Cost"]
        else:
            df["Value at Cost"] = 0.0
    if "Value at Market Price" not in df.columns:
        if {"Qty", "CMP"}.issubset(df.columns):
            df["Value at Market Price"] = df["Qty"] * df["CMP"]
        else:
            df["Value at Market Price"] = 0.0

    realized = df.get("Realized P&L", pd.Series(0, index=df.index)).fillna(0)
    unrealized = df.get("Unrealized P&L", pd.Series(
        0, index=df.index)).fillna(0)
    df["Total P&L"] = realized + unrealized
    df["Total P&L %"] = np.where(
        df["Value at Cost"].fillna(0) > 0,
        df["Total P&L"] / df["Value at Cost"] * 100,
        np.nan,
    )

    df = add_unrealized_bucket(df)
    return add_exit_fields(df)
