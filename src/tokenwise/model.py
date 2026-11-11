"""Waste-prediction model with a bundled baseline for users with little data."""
from dataclasses import dataclass
from importlib import resources
from pathlib import Path

import numpy as np
import skops.io as sio
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.metrics import precision_score, roc_auc_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OrdinalEncoder

from .features import CATEGORICAL, FEATURES, NUMERIC, TARGET

THRESHOLD = 0.5
VAL_FRACTION = 0.2


@dataclass
class TrainResult:
    model: Pipeline
    metrics: dict
    source: str  # "personal" | "baseline"


def fit(df: pd.DataFrame) -> Pipeline:
    pre = ColumnTransformer([
        ("cat", OrdinalEncoder(handle_unknown="use_encoded_value", unknown_value=-1), CATEGORICAL),
        ("num", "passthrough", NUMERIC),
    ])
    pipe = Pipeline([("pre", pre), ("clf", HistGradientBoostingClassifier(random_state=0))])
    X = df[FEATURES].astype({"same_input_seen_before": int})
    return pipe.fit(X, df[TARGET].astype(int))


def temporal_split(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Last VAL_FRACTION of sessions (by first timestamp) are validation."""
    start = df.groupby("session_id")["ts"].min().sort_values(kind="stable")
    n_val = max(1, int(round(len(start) * VAL_FRACTION)))
    val_ids = set(start.index[-n_val:])
    mask = df["session_id"].isin(val_ids)
    return df[~mask], df[mask]


def _predict(pipe: Pipeline, df: pd.DataFrame) -> np.ndarray:
    X = df[FEATURES].astype({"same_input_seen_before": int})
    return pipe.predict_proba(X)[:, 1]


def _metrics(pipe: Pipeline, df: pd.DataFrame) -> dict:
    y = df[TARGET].astype(int)
    if y.nunique() < 2:
        return {"roc_auc": None, "precision_at_threshold": None, "n_eval": int(len(df))}
    p = _predict(pipe, df)
    return {"roc_auc": float(roc_auc_score(y, p)),
            "precision_at_threshold": float(precision_score(y, p >= THRESHOLD, zero_division=0)),
            "n_eval": int(len(df))}


ALLOWED_TYPE_PREFIXES = ("sklearn.", "numpy.", "builtins.")


def _safe_load(path):
    """Load a skops file, refusing any type outside scikit-learn/numpy/builtins (no pickle)."""
    untrusted = sio.get_untrusted_types(file=path)
    bad = [t for t in untrusted if not t.startswith(ALLOWED_TYPE_PREFIXES)]
    if bad:
        raise ValueError(f"refusing to load model file with unexpected types: {bad}")
    return sio.load(path, trusted=untrusted)


def load_baseline() -> Pipeline | None:
    path = resources.files("tokenwise").joinpath("baseline.skops")
    if not path.is_file():
        return None
    try:
        with resources.as_file(path) as p:
            return _safe_load(p)
    except Exception:  # incompatible numpy/scikit-learn build: fall back instead of crashing
        return None


def train(df: pd.DataFrame, *, min_steps: int = 2000) -> TrainResult:
    enough = len(df) >= min_steps and df[TARGET].nunique() == 2 and df["session_id"].nunique() >= 5
    if not enough:
        base = load_baseline()
        if base is not None:
            return TrainResult(base, _metrics(base, df), "baseline")
        if df[TARGET].nunique() < 2:
            raise ValueError("Not enough data to train and no baseline model is bundled.")
    train_df, val_df = temporal_split(df)
    pipe = fit(train_df)
    return TrainResult(pipe, _metrics(pipe, val_df), "personal")


def predict_proba(result: TrainResult, df: pd.DataFrame) -> np.ndarray:
    return _predict(result.model, df)


def save(result: TrainResult, path: Path) -> None:
    sio.dump({"model": result.model, "metrics": result.metrics, "source": result.source}, path)


def load(path: Path) -> TrainResult:
    d = _safe_load(path)
    return TrainResult(d["model"], d["metrics"], d["source"])
