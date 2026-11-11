from pathlib import Path

from platformdirs import user_data_dir


def default_sessions_dir() -> Path:
    return Path.home() / ".claude" / "projects"


def default_db_path() -> Path:
    return Path(user_data_dir("tokenwise")) / "tokenwise.duckdb"
