# Skill Overhead Report Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `tokenwise skills`, which lists every installed skill by estimated cost of carrying its description, with usage counts and an `unused` flag.

**Architecture:** The parser turns `skill_listing` attachments, `Skill` tool calls and `/skill` slash commands into `raw_events` rows (names and lengths only). A new `skills.py` aggregates them in SQL plus Python using existing pricing helpers, and a new CLI subcommand renders the result.

**Tech Stack:** Python 3.10+, DuckDB, pandas, pytest (existing).

**Spec:** `docs/superpowers/specs/2026-11-13-skill-overhead-design.md`

## Global Constraints

- Never store conversation text or skill description text: only skill names and description lengths.
- Window defaults to the last 30 days; flag `--days N`.
- Token estimate = chars / `CHARS_PER_TOKEN` (4, in `pricing.py`); output states these are estimates.
- Cost uses `step_cost(price, tokens, turns_remaining)` with the session's model price and `turns - 1` remaining turns.
- Zero uses is flagged `unused`; all skills are shown, ordered by cost descending.
- Skills without a `plugin:` prefix roll up under `(no plugin)`.
- `skill_name` is a new LAST column of `raw_events` and `COLUMNS`, with the same migration pattern as `cache_write_5m_tokens`.
- Commit messages end with `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`.

## Real log shapes (verified on local sessions)

- Listing line: `{"type":"attachment","timestamp":...,"attachment":{"type":"skill_listing","content":"- name: description\n- name2: ...","names":[...],"skillCount":17,"isInitial":true}}`. A session can hold several listings.
- Slash command: `{"type":"user","message":{"content":"<command-name>/model</command-name>\n  <command-message>...</command-message>..."}}`; `content` is a string (could also be a list of `{"type":"text","text":...}` blocks). Built-ins like `/model` and `/plugin` look the same as skills; they are filtered later by matching listed skill names.
- Skill tool call: `tool_use` with `name == "Skill"` and `input == {"skill": "<name>", "args": ...}`.

## Review Focus

- A `/model` or `/plugin` slash command (not a skill) must not appear in the output or crash it.
- A skill listed in two listings of one session, or whose description contains `: ` or newlines, is counted once with its full length.
- Text inside a `tool_result` that contains `<command-name>` must not count as a use.
- A session on a model with no price must give a `Warning: no price for ...` line, not a crash.
- No listings in the window (new install, or `--days 0`) prints a clear message and exits 0.
- A database created before `skill_name` existed must keep working.

---

### Task 1: Store skill names and description lengths

**Files:**
- Modify: `src/tokenwise/ingest/parser.py` (COLUMNS, `parse_line`)
- Modify: `src/tokenwise/db.py` (SCHEMA, migration in `connect`)
- Test: `tests/test_parser.py`, `tests/test_db.py`

**Interfaces:**
- Produces: `raw_events.skill_name VARCHAR`. Row kinds: `type="skill_listed"` (`skill_name`, `result_chars` = length of that skill's entry in the listing text, `ts`); `type="skill_used"` (`skill_name`, from a slash command, name without leading `/`); existing `type="tool_use"` rows with `tool_name=="Skill"` also carry `skill_name` from `input["skill"]` (only if it is a str).
- Produces: `parser.split_listing(content: str) -> dict[str, int]` mapping skill name to entry length. Entries start at line beginnings matching `- <name>: ` where `<name>` has no whitespace; the entry is the text after the leading `- ` up to the next such start (newlines inside included, the trailing newline stripped), so its length counts `name: description`.

- [ ] **Step 1: Write failing parser tests** in `tests/test_parser.py`:
  - `test_skill_listing_rows`: attachment line of type `skill_listing` with content `"- a:b: Use when x: y\n  more\n- c: short"` gives two rows of type `skill_listed`, names `a:b` and `c`, `result_chars` equal to `len("a:b: Use when x: y\n  more")` and `len("c: short")`, and `"Use when"` not in `json.dumps(rows)`.
  - `test_skill_tool_call_stores_name`: `tool_use` named `Skill` with input `{"skill": "superpowers:brainstorming"}` yields a tool_use row with `skill_name == "superpowers:brainstorming"`; a `Bash` tool_use has `skill_name is None`.
  - `test_slash_command_is_skill_used`: user line with string content `"<command-name>/superpowers:brainstorming</command-name>\n<command-args>secret</command-args>"` yields one `skill_used` row with `skill_name == "superpowers:brainstorming"` and `"secret"` not in the dumped rows; same result for list content with one text block.
  - `test_command_name_inside_tool_result_ignored`: user line whose content is a `tool_result` block containing `"<command-name>/x</command-name>"` yields only the `tool_result` row.
  - `test_plain_user_text_ignored`: user line with string content `"hello"` yields `[]`.
- [ ] **Step 2: Run** `pytest tests/test_parser.py -v`. Expected: the new tests FAIL.
- [ ] **Step 3: Add `"skill_name"` as the last item of `COLUMNS`; implement `split_listing`, the attachment branch (before the `msg = d.get("message")` check), the `Skill` name capture, and the slash branch in `parse_line`.** For the slash branch take text from a str `content`, or from `text` blocks of a list (never `tool_result` blocks); require `text.lstrip().startswith("<command-name>")`, then regex `<command-name>/?([^<\s]+)</command-name>`. A `skill_listing` attachment with non-str `content` yields `[]`.
- [ ] **Step 4: Write failing db tests** in `tests/test_db.py`: `test_new_database_has_skill_name_column`, and `test_old_database_gains_skill_name` (create a file DB with the previous 18-column `raw_events` and a row, call `connect`, assert `skill_name` is in `DESCRIBE raw_events` and the row is preserved).
- [ ] **Step 5: Implement** the column in `SCHEMA` and a second migration branch in `connect` (`ALTER TABLE raw_events ADD COLUMN skill_name VARCHAR`).
- [ ] **Step 6: Run** `pytest -q`. Expected: all pass (the loader's text branch already handles the new string column).
- [ ] **Step 7: Commit** `feat: record skill listings, skill tool calls and slash commands`.

### Task 2: Aggregate skill cost and usage

**Files:**
- Create: `src/tokenwise/skills.py`
- Modify: `tests/synth.py` (helpers)
- Test: `tests/test_skills.py`

**Interfaces:**
- Consumes: `connect`, `ingest_dir`, `build_layers` (so `turns` exists), `pricing.step_cost`, `blended_step_price`, `price_for`, `load_effective_prices`, `CHARS_PER_TOKEN`.
- Produces in `tests/synth.py`: `write_raw(dir: Path, name: str, lines: list[dict]) -> Path` (writes the dicts as jsonl, returns the path); `listing_line(ts: str, entries: dict[str, str]) -> dict` (content is `"- name: desc"` joined by newlines); `asst_line(ts: str, msg_id: str, model: str = "claude-sonnet-5-5") -> dict` (uses `DEFAULT_USAGE`); `skill_call_line(ts: str, tool_id: str, skill: str) -> dict`; `slash_line(ts: str, command: str) -> dict`.
- Produces in `skills.py`:
  - `@dataclass SkillStat`: `name: str`, `plugin: str`, `tokens_per_session: float`, `sessions: int`, `uses: int`, `cost: float`.
  - `@dataclass SkillReport`: `skills: list[SkillStat]` (cost descending, ties by name), `sessions: int` (sessions with a listing in the window), `unpriced: list[str]` (sorted model ids without a price), `days: int`.
  - `plugin_of(name: str) -> str`: text before the first `:`, else `"(no plugin)"`.
  - `skill_report(con, prices: dict, *, days: int = 30, now: datetime | None = None) -> SkillReport`.

Behavior of `skill_report`: the cutoff is `now - days` (UTC; default now is the current UTC time), compared with the ISO `ts` strings. Sessions in scope are those whose first `skill_listed` row is inside the window. Per session and skill take the max `result_chars` across listing rows. The session model is the first non-`<synthetic>` model in `turns` by `turn_idx`; sessions with 0 turns are skipped. A session whose model has no price still counts in `sessions` and `tokens_per_session` but adds no cost, and its model id goes in `unpriced`. Per-session skill cost = `step_cost(blended_step_price(price, share_5m), chars / CHARS_PER_TOKEN, turns - 1)`, where `share_5m` is that model's share of 5-minute cache writes over all `turns` (0 when there are no writes). `tokens_per_session` = sum of tokens over the sessions where the skill was listed, divided by the number of those sessions. `uses` = rows in the window that are either `tool_use` with `tool_name == "Skill"` and non-null `skill_name`, or `skill_used`, whose `skill_name` equals a listed skill; names never listed in the window are ignored.

- [ ] **Step 1: Add the `synth.py` helpers** above.
- [ ] **Step 2: Write failing tests** in `tests/test_skills.py`, using a temp DB, `write_raw`, `ingest_dir`, `build_layers` and `load_prices()` (bundled), with `now=datetime(2026, 1, 31, tzinfo=timezone.utc)` and January timestamps:
  - `test_cost_and_uses`: two sessions, each with a listing `{"p:big": "x"*396, "p:small": "y"*36, "solo": "z"*76}` and 3 assistant turns; session one also has a `skill_call_line` for `p:small`, `slash_line("/solo")` and `slash_line("/model")`. Assert: order is `p:big`, `solo`, `p:small`; `p:big.uses == 0`, `p:small.uses == 1`, `solo.uses == 1`; `sessions == 2`; no stat named `model`; `p:big.cost` equals `2 * step_cost(price, (len("p:big") + 2 + 396) / 4, 2)` within 1e-9 (default usage has no 5m field, so the blend share is 0).
  - `test_description_with_colons_and_newlines_counted_once`: one session with two listing lines that both contain `p:a` (the second shorter) and a multi-line description containing `": "`; assert a single stat for `p:a` and `tokens_per_session` based on the longer entry.
  - `test_command_name_in_tool_result_not_a_use`: a `tool_result` text containing `<command-name>/p:big</command-name>`; assert `p:big.uses == 0`.
  - `test_window_excludes_old_sessions`: one session dated 2025-11-01 and one in January with `days=30`; assert `sessions == 1`.
  - `test_unpriced_model_reported`: session on model `"mystery-model"`; assert `unpriced == ["mystery-model"]` and the skills are still listed with `cost == 0.0`.
  - `test_no_listings`: a DB without listings gives `skills == []` and `sessions == 0`.
  - `test_plugin_of`: `plugin_of("superpowers:brainstorming") == "superpowers"` and `plugin_of("init") == "(no plugin)"`.
- [ ] **Step 3: Run** `pytest tests/test_skills.py -v`. Expected: FAIL (module missing).
- [ ] **Step 4: Implement `skills.py`** per the behavior above (SQL for per-session max chars and session start, turns and model, and uses; Python for pricing).
- [ ] **Step 5: Run** `pytest -q`. Expected: all pass.
- [ ] **Step 6: Commit** `feat: aggregate skill description cost and usage`.

### Task 3: Render and CLI command

**Files:**
- Modify: `src/tokenwise/skills.py` (add `render_skills`)
- Modify: `src/tokenwise/cli.py`
- Test: `tests/test_skills.py`, `tests/test_cli.py`

**Interfaces:**
- Consumes: `SkillReport`, `plugin_of`, `skill_report` from Task 2; `_prepare`, `build_layers`, `load_effective_prices` in `cli.py`.
- Produces: `render_skills(report: SkillReport) -> str`; CLI `tokenwise skills [--sessions-dir] [--db] [--pricing] [--days N]` (default 30).

Output layout (labels exact, spacing free):
```
Skills loaded in N sessions (last D days)
Estimated cost of carrying skill descriptions: $X (~T tokens/session). Token counts are estimates.

By plugin
  <plugin>   <k> skills  ~<tok> tokens/session  <u> uses  $<cost>[  unused]
All skills
  <name>   ~<tok> tokens/session  <u> uses  $<cost>[  unused]
```
The plugin rollup is ordered by cost descending; a plugin is flagged `unused` when the sum of its uses is 0, a skill when its uses are 0. When `unpriced` is non-empty, append `Warning: no price for <models> - their cost is excluded.` With no skills the output is `No skill listings found in the last D days.`

- [ ] **Step 1: Write failing tests.** In `tests/test_skills.py`: `test_render_flags_unused_and_orders` (hand-built `SkillReport` with 3 skills; assert `unused` appears on exactly the zero-use skill lines, the plugin lines come before the `All skills` heading, skills appear in the given order, and `Warning: no price for mystery-model` is present when `unpriced=["mystery-model"]`) and `test_render_empty` (exact empty message). In `tests/test_cli.py`: `test_skills_command_end_to_end` (sessions written with `write_raw` under `tmp_path/"sess"/"proj"` using today's UTC date so the default window includes them; run `main(["skills", "--sessions-dir", ..., "--db", ...])`; assert exit 0, `By plugin` and `All skills` in stdout, and the unused skill's line contains `unused`) and `test_skills_command_no_listings_exits_zero` (using existing `make_sessions`: exit 0, stdout contains `No skill listings found`).
- [ ] **Step 2: Run** the new tests. Expected: FAIL.
- [ ] **Step 3: Implement `render_skills`** and the `skills` subparser (`--sessions-dir`, `--db`, `--pricing`, plus `--days`, int, default 30; `--retrain` stays only on `train` and `report`). In `main`, after `_prepare` and `build_layers(con)`, if `args.cmd == "skills"`: print `render_skills(skill_report(con, load_effective_prices(args.pricing), days=args.days))` and return 0, before the labels and model code.
- [ ] **Step 4: Run** `pytest -q`. Expected: all pass.
- [ ] **Step 5: Commit** `feat: add tokenwise skills command`.

### Task 4: Docs and plugin skill

**Files:**
- Modify: `README.md`, `skills/report/SKILL.md`
- Test: `tests/test_plugin.py` (run; update only if it pins SKILL.md text)

- [ ] **Step 1: README:** add `skills` to the commands list and a short section "Which skills cost you tokens" with the output shape (synthetic numbers, said so), the `--days` flag, and that costs are estimates from description length.
- [ ] **Step 2: `skills/report/SKILL.md`:** under "Other commands" add `tokenwise skills` (lists every installed skill by the estimated cost of its description and flags those with zero uses in the last 30 days; suggest uninstalling a plugin only when it is flagged `unused`, and say the user decides). Leave `allowed-tools: Bash(tokenwise *)` unchanged.
- [ ] **Step 3: Run** `pytest -q`. Expected: all pass.
- [ ] **Step 4: Manual check** on real data: `tokenwise skills --db <scratchpad>\check.duckdb`; confirm the `superpowers` skills appear with plausible token counts and that `/model`-type commands do not appear.
- [ ] **Step 5: Commit** `docs: document the skills command`.
