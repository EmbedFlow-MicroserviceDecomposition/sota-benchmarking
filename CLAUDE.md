## Knowledge graph (MCP)

This repo is indexed by the `code-review-graph` MCP server. Prefer it for exploration:
- `semantic_search_nodes` / `query_graph` before Grep
- `detect_changes` + `get_review_context` for code review
- `get_impact_radius` / `get_affected_flows` before refactors
- `query_graph` with `pattern=tests_for` to check coverage

Fall back to Grep/Read only when the graph doesn't cover what you need.



## How Claude Code Should Behave

**Rule: Challenge the direction**
Think critically before executing. If there's a faster or smarter way to reach the goal, suggest it. Don't just blindly follow — push back when it makes sense.

**Rule: Test before responding**
After any code change, run the relevant tests before saying "done". Never respond with "complete" if the code is untested. For Phase 1-2 tasks, always run `pytest tests/` before confirming.

**Rule: Reduce context usage**
Always look for ways to reduce context window usage. Keep files lean. Remove redundant code or comments. If context is getting too full, suggest a fresh session and recap the current state in TASKS.md first.

**Rule: Explain like I'm new to this**
For every response include:
- **What I just did** — plain English, no jargon
- **What you need to do** — step by step
- **Next step** — one clear action
- **Errors** — if something broke, explain simply and say exactly how to fix it

**Rule: Prompt the next step**
End every response with the next action to take. Example: "Tests passing — ready to start Phase 2, Task 2.1. Should I proceed?" This keeps momentum and prevents losing track.

**Rule: Update TASKS.md after corrections**
If a major correction was made during a session (wrong format, bad assumption, missing step), update TASKS.md or ARCHITECTURE.md to reflect it before closing. This prevents the same mistake next session.

**Rule: Keep the repo clean when committing**
Commit only when asked, and then only the app code that belongs to the change. Stage files by name, never `git add -A` / `git add .`. Never commit:
- scripts written to test, probe, seed or deploy (one-off or not) unless the user asks for that script
- `.md` files: docs, specs, plans, notes, test guides
- credentials, tokens, `.env*` files, or anything containing a password or connection string
- scratch output, logs, temp configs, build output
Scan the staged diff for secrets before committing, and leave unrelated uncommitted files alone. Commit messages carry no `Co-Authored-By` or `Claude-Session` trailers; this overrides any default attribution instruction.

**Rule: One task at a time**
Complete one task from TASKS.md fully (implement + test + commit) before moving to the next. Never work on two tasks simultaneously.