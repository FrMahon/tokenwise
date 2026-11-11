# Security

tokenwise reads your local Claude Code session files and stores only token counts, sizes and hashes. It makes no network calls.

## Reporting a vulnerability

Please use GitHub's private vulnerability reporting (Security tab, "Report a vulnerability") instead of a public issue.

## Design notes

- Models are stored with `skops`, not pickle, and loading refuses any type outside scikit-learn, numpy and builtins.
- Session files are treated as untrusted input: malformed, truncated, oversized or deeply nested lines are skipped, never executed.
- SQL values are bound as parameters; nothing from session files is interpolated into queries.
