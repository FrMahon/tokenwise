# Skill overhead report (design)

## Intent
The user has many skills/plugins installed. Each session loads every skill's name and description into the prompt, and that text is re-read every turn. They want to see which installed skills cost the most and which they never use, so they can uninstall them.

## Goals
- New command `tokenwise skills`: lists **all** skills ordered by estimated cost, with uses next to each; skills with zero uses are marked `unused`.
- Plugin rollup above the list (skills grouped by the prefix before `:`), since uninstalling happens per plugin.
- Window: last 30 days by default, `--days N` to change.

## Non-goals
- MCP tool schemas, CLAUDE.md, deferred tools (possible later stage).
- Generating uninstall commands or reading `~/.claude/skills` / `plugins/`.
- Any ML; this is plain SQL over ingested data.

## Anti-goals
- Storing conversation text. Only skill names and description lengths are kept, never description text or prompts.

## Approaches considered
1. **Read the `skill_listing` record already in session logs (chosen).** Reflects what was really loaded each day, stays inside the existing ingest pipeline and privacy model.
2. Scan `~/.claude/skills` and `plugins/`: shows only what is installed today, worse cost estimate, new filesystem reads.
3. Both: more complete, more work and surface; can be added later for uninstall commands.

## Design
- **Parser:** `attachment` lines of type `skill_listing` become one `skill_listed` row per `- name: description` line (`skill_name`, `result_chars` = line length). `tool_use` of `Skill` stores the invoked name in `skill_name`. User messages containing `<command-name>/x</command-name>` (slash-command invocations) become a `skill_used` row, because typing `/skill` does not go through the Skill tool and would otherwise be undercounted. `skill_name` is a new last column in `raw_events`, same migration pattern as `cache_write_5m_tokens`.
- **Cost:** per session, dedupe listings (max chars per skill). tokens = chars / `CHARS_PER_TOKEN` (an estimate, stated in the output). Cost = existing `step_cost` with the session's turn count and model price (one cache write plus cache reads on later turns). Summed over sessions in the window.
- **Uses:** count of `Skill` tool calls plus slash invocations in the window, matched by name.
- **Output:** plugin rollup (skills, ~tokens/session, uses, cost), then every skill by cost descending, `unused` flagged on zero uses. Skills without a `plugin:` prefix (user or built-in) are grouped as `(no plugin)` in the rollup.
- **Plugin skill:** `skills/report/SKILL.md` gains a mention of `tokenwise skills`.
- **Tests:** parser tests for the three row kinds, a synthetic-sessions test for the report ordering and `unused` marker.

## Known limits
- Sessions from before Claude Code logged `skill_listing` have no overhead data.
- Token counts are estimates from character length.

## Left to the builder
Exact column layout, handling of listing records that repeat within a session, flag name for the window.
