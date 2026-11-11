from importlib import resources


def build_layers(con) -> None:
    """(Re)build the `turns` and `steps` tables from raw_events."""
    sql = resources.files("tokenwise").joinpath("sql", "clean.sql").read_text(encoding="utf-8")
    con.execute(sql)
