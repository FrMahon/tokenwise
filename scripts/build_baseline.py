"""Train the bundled baseline model from a sessions folder. Saves only the fitted model."""
import argparse
from pathlib import Path

import joblib

from tokenwise import model as M
from tokenwise.db import connect
from tokenwise.features import build_features
from tokenwise.ingest.loader import ingest_dir
from tokenwise.labels import build_labels
from tokenwise.paths import default_sessions_dir
from tokenwise.transform import build_layers


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sessions-dir", type=Path, default=default_sessions_dir())
    ap.add_argument("--out", type=Path, default=Path("src/tokenwise/baseline.joblib"))
    a = ap.parse_args()
    con = connect(":memory:")
    ingest_dir(a.sessions_dir, con)
    build_layers(con)
    build_labels(con)
    df = build_features(con)
    res = M.train(df, min_steps=0)  # force a personal fit, then refit on everything for shipping
    pipe = M.fit(df)
    joblib.dump(pipe, a.out, compress=3)
    print(f"steps={len(df)} wasted={df.wasted.mean():.1%} validation={res.metrics} -> {a.out}")


if __name__ == "__main__":
    main()
