import argparse
import sys
from pathlib import Path

from . import model as M
from .db import connect
from .features import build_features
from .ingest.loader import ingest_dir
from .labels import build_labels
from .pricing import load_effective_prices
from .paths import default_db_path, default_sessions_dir
from .report import render
from .skills import render_skills, skill_report
from .transform import build_layers


def _parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="tokenwise",
                                 description="Where your Claude Code token spend goes, and what you could save.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name, help_ in (("ingest", "load sessions into the local database"),
                        ("train", "train the waste model and print its metrics"),
                        ("report", "run everything and print the report")):
        p = sub.add_parser(name, help=help_)
        p.add_argument("--sessions-dir", type=Path, default=default_sessions_dir())
        p.add_argument("--db", type=Path, default=default_db_path())
        p.add_argument("--pricing", type=Path, default=None, help="extra pricing.toml (USD per million tokens)")
        if name != "ingest":
            p.add_argument("--retrain", action="store_true", help="ignore the saved model and train again")
    p = sub.add_parser("skills", help="list installed skills by the cost of their descriptions and flag unused ones")
    p.add_argument("--sessions-dir", type=Path, default=default_sessions_dir())
    p.add_argument("--db", type=Path, default=default_db_path())
    p.add_argument("--pricing", type=Path, default=None, help="extra pricing.toml (USD per million tokens)")
    p.add_argument("--days", type=int, default=30, help="only sessions from the last N days (default 30)")
    return ap


def _prepare(args):
    if not args.sessions_dir.is_dir():
        print(f"Sessions folder not found: {args.sessions_dir} (use --sessions-dir)", file=sys.stderr)
        return None, None
    con = connect(args.db)
    stats = ingest_dir(args.sessions_dir, con)
    if con.execute("SELECT count(*) FROM raw_events").fetchone()[0] == 0:
        print(f"No sessions found in {args.sessions_dir}", file=sys.stderr)
        return None, None
    return con, stats


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    con, stats = _prepare(args)
    if con is None:
        return 1
    if args.cmd == "ingest":
        print(f"files={stats.files} new_rows={stats.new_rows} skipped_lines={stats.skipped_lines}")
        return 0
    build_layers(con)
    if args.cmd == "skills":
        print(render_skills(skill_report(con, load_effective_prices(args.pricing), days=args.days)))
        return 0
    build_labels(con)
    df = build_features(con)
    if df.empty:
        print("No tool calls found in these sessions; nothing to analyze.", file=sys.stderr)
        return 1
    try:
        result = M.train_cached(df, args.db.with_name("model.skops"), force=args.retrain)
    except ValueError as e:
        print(str(e), file=sys.stderr)
        return 1
    if args.cmd == "train":
        print(f"source={result.source} metrics={result.metrics}")
        return 0
    print(render(con, result, M.predict_proba(result, df), skipped_lines=stats.skipped_lines,
                 prices=load_effective_prices(args.pricing)))
    return 0
