---
name: report
description: Show where Claude Code tokens go, which skills, plugins and MCP tools are loaded but unused, and how much is avoidable, by running the local tokenwise CLI on the user's own sessions. Use when the user asks about token usage, spend, wasted tokens, unused skills or plugins, repeated reads, or how to spend fewer tokens.
allowed-tools: Bash(tokenwise report*), Bash(tokenwise skills*), Bash(tokenwise ingest*), Bash(tokenwise train*), Bash(tokenwise --help)
---

# tokenwise report

tokenwise is a command line tool that reads the user's local Claude Code sessions (`~/.claude/projects`), stores only token counts, result sizes and hashes in a local database, and prints where the spend goes. Nothing is sent anywhere.

## Steps

1. Check that the CLI is installed by running `tokenwise --help`.
   - If the command is not found, do NOT install anything yourself. Tell the user to install it, show them the command, and wait until they confirm:
     `pipx install git+https://github.com/FrMahon/tokenwise.git` (or `uv tool install git+https://github.com/FrMahon/tokenwise.git`).
2. Tell the user the first run can take about a minute (it trains a small model on their history) and later runs take a few seconds. Then run `tokenwise report`.
3. Explain the output in the user's language. Do not read or quote the session files themselves; the report is enough.

## Reading the output

- **Tokens processed** is the sum of input, output, cache-write and cache-read tokens. No prices are involved, so there is nothing to keep up to date.
- **Avoidable** is the part the model predicts as waste, with its share of the total.
- **Top leaks** can only be:
  - `repeat`: the same tool call with the same input returned an identical result earlier in the session (for example reading an unchanged file twice).
  - `bulky_unused`: a large result (about 4,000 tokens or more) that was not followed by an edit of the same target within the next 10 steps.
  - `other patterns`: predicted waste that fits neither label.
- Each leak is counted as the result's tokens written once and re-read on every later turn, up to the next compaction.
- Lines starting with `Note` matter: they say when input lines were skipped.

- After the report, the same command prints **Skills loaded** (each skill's description is in every session's prompt; "tokens carried" is that text written once and re-read every later turn, rolled up by plugin, with `unused` where a skill or plugin had zero uses in the last 30 days) and **MCP tools by plugin / server** (tools listed, tools used, calls; no size, because transcripts do not store tool schemas). "No skill listings found" just means there is nothing to show.
- Tokens, not dollars: cache reads count like fresh tokens, so shares are not the share of a bill.

## Be honest about limits

"Avoidable" is an estimate, not a verdict: there is no ground truth, the model predicts patterns of waste. A flagged read may have been useful. Suggest concrete habits only when they follow from the leaks shown (for example, reading a narrower range of a large file, or not re-reading a file that has not changed).

## Other commands

`tokenwise ingest` only loads new sessions. `tokenwise train` prints the model metrics. `--retrain` forces a new model. `--sessions-dir` and `--db` change the locations.

`tokenwise skills` prints only the skills and MCP sections, ordered by tokens carried, and flags the ones with zero uses (`--days N` changes the window; `report` always uses 30). Suggest uninstalling a plugin only when it is flagged `unused`, and say that the user decides. Token counts are estimates from description length.
