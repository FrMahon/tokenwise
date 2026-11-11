# tokenwise

See where your Claude Code token spend goes, and how much of it you could save. Runs entirely on your machine.

Example output (illustrative numbers):

```
$ tokenwise report
Sessions analyzed: 12
Estimated spend: $48.20
Avoidable: $6.10 (13%)

Top leaks
  1. bulky_unused     $3.90
  2. repeat           $1.80
  3. other patterns   $0.40

Model: personal (AUC 0.91)
```

## Install

```
pipx install .        # or: uv tool install .
tokenwise report
```

By default it reads `~/.claude/projects`; use `--sessions-dir` and `--db` to change locations.
Commands: `ingest`, `train`, `report`.

## How it works

![pipeline](docs/pipeline.svg)

1. **Ingest** the session files incrementally; unknown or truncated lines are skipped, never fatal.
2. **DuckDB layers** (SQL): raw events → deduplicated turns → tool-call steps.
3. **Labels** derived from the data: a step is *waste* if it repeats an identical earlier call+result, or returns a large result that nothing follows up on.
4. **Model** (gradient boosting) learns from your history to predict waste using only what is known when the tool is called. With fewer than 2000 steps it falls back to a bundled baseline.
5. **Report** prices the predicted waste with `pricing.toml`.

## Privacy

Nothing leaves your machine. Conversation text is never stored: only token counts, result sizes and SHA-1 hashes of inputs and results.

## Limitations

- "Avoidable" has no ground truth. The model predicts *patterns* of waste defined above, not verdicts.
- Claude Code's session format is not a public API and may change; unreadable lines are counted and skipped.
- `pricing.toml` holds estimates. Override them with `--pricing FILE` or a `pricing.toml` in your user config folder (merged over the bundled prices; dated model ids match by prefix). Models without a price are listed and excluded.

## Development

```
pip install -e ".[dev]" && pytest
```
Tests use synthetic sessions only.
