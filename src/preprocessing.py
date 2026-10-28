"""
Preprocessing and feature engineering for the Metro Interstate (I-94) traffic dataset.

The SAME functions are used by the Task 1 notebook (training) and by the Task 4
forecast script (inference), so training and serving features always match.
"""
import numpy as np
import pandas as pd

TARGET = "traffic_volume"
NUMERIC_COLS = ["temp", "rain_1h", "snow_1h", "clouds_all", "traffic_volume"]
MAX_INTERP_HOURS = 6          # longest gap (hours) we are willing to fill
TEMP_MIN_K = 200              # temp of 0 K is a sensor error
RAIN_MAX_MM = 100             # 9831 mm of rain in one hour is a sensor error
LAGS = [1, 2, 3, 24, 48, 168]
ROLL_WINDOWS = [3, 24, 168]
WEATHER_CATS = ["Clear", "Clouds", "Drizzle", "Fog", "Haze", "Mist",
                "Rain", "Smoke", "Snow", "Squall", "Thunderstorm"]


def load_raw(path):
    """Read the raw CSV and parse the timestamp."""
    return pd.read_csv(path, parse_dates=["date_time"])


def _fill_short_gaps(s, max_gap, method="interp"):
    """
    Fill runs of consecutive NaN no longer than `max_gap` hours; leave longer runs untouched.
    (pandas' `limit=` would wrongly fill the first `max_gap` hours of a long gap.)
    """
    if method == "interp":
        filled = s.interpolate(method="time", limit_area="inside")
    else:
        filled = s.ffill()
    isna = s.isna()
    run_id = (isna != isna.shift()).cumsum()
    run_len = isna.groupby(run_id).transform("sum")
    return filled.where(~(isna & (run_len > max_gap)), np.nan)


def clean(df, max_interp=MAX_INTERP_HOURS):
    """
    Raw rows -> a regular hourly grid with documented handling of every problem.

    1. Duplicate timestamps (one row per weather description) -> one row per hour.
    2. Impossible sensor values (temp 0 K, rain > 100 mm/h) -> NaN.
    3. Reindex to a complete hourly grid so missing hours become explicit NaN.
    4. Interpolate only SHORT gaps (<= max_interp hours); longer gaps stay NaN
       because inventing days of traffic would corrupt the signal.
    5. Holiday label -> binary `is_holiday` applied to the whole calendar day.
    """
    df = df.copy()
    df["is_holiday_row"] = df["holiday"].notna()

    # 1. one row per timestamp
    agg = {c: "mean" for c in NUMERIC_COLS}
    agg.update({"weather_main": "first", "is_holiday_row": "max"})
    df = df.groupby("date_time").agg(agg).sort_index()

    # 2. impossible values -> NaN
    df.loc[df["temp"] < TEMP_MIN_K, "temp"] = np.nan
    df.loc[df["rain_1h"] > RAIN_MAX_MM, "rain_1h"] = np.nan

    # 3. complete hourly grid
    grid = pd.date_range(df.index.min(), df.index.max(), freq="h", name="date_time")
    df = df.reindex(grid)
    df["observed"] = df[TARGET].notna()       # True = real traffic reading

    # 4. interpolate short gaps only (a gap is filled completely or not at all)
    for c in NUMERIC_COLS:
        df[c] = _fill_short_gaps(df[c], max_interp, method="interp")
    df["weather_main"] = _fill_short_gaps(df["weather_main"], max_interp, method="ffill")

    # 5. holiday flag for the whole day
    day = df.index.normalize()
    holiday_days = pd.Index(day[df["is_holiday_row"].fillna(False).astype(bool)]).unique()
    df["is_holiday"] = day.isin(holiday_days).astype(int)
    return df.drop(columns="is_holiday_row")


def add_features(df, lags=LAGS, windows=ROLL_WINDOWS):
    """
    Feature engineering on a cleaned HOURLY frame (index = timestamp).
    Lag / rolling features use only past values (shift(1)) -> no leakage.
    """
    out = df.copy()
    idx = out.index

    # calendar features
    out["hour"] = idx.hour
    out["dayofweek"] = idx.dayofweek
    out["month"] = idx.month
    out["is_weekend"] = (idx.dayofweek >= 5).astype(int)
    out["hour_sin"] = np.sin(2 * np.pi * idx.hour / 24)
    out["hour_cos"] = np.cos(2 * np.pi * idx.hour / 24)
    out["dow_sin"] = np.sin(2 * np.pi * idx.dayofweek / 7)
    out["dow_cos"] = np.cos(2 * np.pi * idx.dayofweek / 7)
    out["month_sin"] = np.sin(2 * np.pi * idx.month / 12)
    out["month_cos"] = np.cos(2 * np.pi * idx.month / 12)

    # weather category -> fixed one-hot columns (same columns at inference time)
    for cat in WEATHER_CATS:
        out[f"weather_{cat}"] = (out["weather_main"] == cat).astype(int)

    # lag features
    for k in lags:
        out[f"lag_{k}"] = out[TARGET].shift(k)

    # rolling means of the PAST (shifted by 1 so the current hour is excluded)
    past = out[TARGET].shift(1)
    for w in windows:
        out[f"roll_mean_{w}"] = past.rolling(w, min_periods=w).mean()
    out["roll_std_24"] = past.rolling(24, min_periods=24).std()
    return out


WEATHER_FEATURES = ["temp", "rain_1h", "snow_1h", "clouds_all"] + [f"weather_{c}" for c in WEATHER_CATS]
CALENDAR_FEATURES = ["hour_sin", "hour_cos", "dow_sin", "dow_cos", "month_sin", "month_cos",
                     "is_weekend", "is_holiday"]
LAG_FEATURES = [f"lag_{k}" for k in LAGS] + [f"roll_mean_{w}" for w in ROLL_WINDOWS] + ["roll_std_24"]
ALL_FEATURES = WEATHER_FEATURES + CALENDAR_FEATURES + LAG_FEATURES
