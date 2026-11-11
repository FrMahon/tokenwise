# tokenwise

See where your Claude Code token spend goes, and how much of it you could save. Runs entirely on your machine.

Real output on 40 synthetic sessions (generated with `scripts/make_demo_sessions.py`, so the numbers say nothing about typical usage):

```
$ tokenwise report
Sessions analyzed: 40
Estimated spend: $202.24
Avoidable: $42.20 (21%)

Top leaks
  1. bulky_unused     $29.98
  2. repeat           $8.27
  3. other patterns   $3.96

Model: personal (AUC 0.78)
```

## Install

```
pipx install .        # or: uv tool install .
tokenwise report
```

By default it reads `~/.claude/projects`; use `--sessions-dir` and `--db` to change locations.
Commands: `ingest`, `train`, `report`. `train` and `report` save the trained model next to the database (`model.skops`) and reuse it until the data changes; `--retrain` forces a new one.

## How it works

![pipeline](docs/pipeline.svg)

1. **Ingest** the session files incrementally; unknown or truncated lines are skipped, never fatal.
2. **DuckDB layers** (SQL): raw events → deduplicated turns → tool-call steps.
3. **Labels** derived from the data: a step is *waste* if it repeats an identical earlier call+result, or returns a large result that nothing follows up on.
4. **Model** (gradient boosting) learns from your history to predict waste using only what is known when the tool is called. With fewer than 2000 steps it falls back to a bundled baseline.
5. **Report** prices the predicted waste with `pricing.toml`.

## Privacy

Nothing leaves your machine. Conversation text is never stored: only token counts, result sizes and SHA-1 hashes of inputs and results.

## Security

See [SECURITY.md](SECURITY.md). The bundled model is stored in a safe format (not pickle) and is checked against a type allowlist before loading.

## Limitations

- "Avoidable" has no ground truth. The model predicts *patterns* of waste defined above, not verdicts.
- Claude Code's session format is not a public API and may change; unreadable lines are counted and skipped.
- `pricing.toml` holds estimates. Override them with `--pricing FILE` or a `pricing.toml` in your user config folder (merged over the bundled prices; dated model ids match by prefix). Models without a price are listed and excluded. Cache writes with a 5-minute TTL are billed at 1.25x the input price (override with `cache_write_5m`); sessions ingested before this was recorded are billed at the 1-hour rate. Messages replayed by a resumed session are counted once. The report warns when the bundled prices were last checked more than 90 days ago.

## Development

```
pip install -e ".[dev]" && pytest
```
Tests use synthetic sessions only.

## License

MIT. See [LICENSE](LICENSE).
