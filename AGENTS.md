# Context and Guidelines for AI Agents

## Context and references

Before deciding on conventions, flows or rules, check `docs/`. What is documented there is normative: it prevails over assumptions and must be followed. If a decision changes something already documented, update the corresponding document.

For general orientation:

- `README.md` — high-level view for humans; points to `docs/` when something needs detail.
- `docs/` — the project idea, requirements, and reference material.

## Tool-agnostic AI strategy

This project adopts a tool-agnostic strategy to support multiple AIs without duplicating instructions.

**Editable source of truth:** `AGENTS.md` — operational rules common to any agent.

Compatibility files such as `CLAUDE.md` are only pointers to that source of truth. Never edit the pointer directly when the intent is to change a rule — edit `AGENTS.md` instead.

**How each tool loads the instructions:**

- **Claude Code** — loads the rules through `CLAUDE.md`, which includes `@AGENTS.md` and must not be edited.
- **Cursor** — reads `AGENTS.md` directly as its native instructions file.
- **Codex CLI / other tools** — read `AGENTS.md` directly.

There are no project skills yet. If any tool-specific skill is added later, follow the same principle: keep the authored content in one place and let each tool's own convention point to it.

## Language

The repository is written entirely in **English**: code, comments, configuration, documentation (`README.md`, `docs/`), commit messages, and any operator-facing runtime output (logs, CLI messages, errors).

Sample data (paths, URLs, filenames used as examples in docs or tests) may follow whatever locale makes the example realistic — it is not subject to the English-only rule, which applies to prose and code, not data.

Chat communication with the operator follows the operator's language (pt-BR).

In pt-BR text for humans (chat), avoid overusing the em dash ("—") to interleave asides mid-sentence; prefer commas or parentheses, as a pt-BR copywriter normally would. This is not a ban: the em dash remains correct in dialogue, titles and occasional emphasis; the problem is repetitive, unidiomatic use.

## Commits

- Messages always in **English**.
- **Conventional Commits** format: `type: concise subject` (subject up to ~72 characters).
- Valid types: `feat`, `fix`, `docs`, `refactor`, `chore`.
- Subject and body in the imperative mood, describing what the commit does: `add`, `fix`, `update`, `remove`, `refactor`, `document`.
- Body required, with a short paragraph summarizing the goal of the change and a bullet list describing the changes made.
- Before running `git push`, present the proposal and wait for explicit operator approval.
- Use explicit files in `git add`; never broad staging like `git add .`.
- If there are files unrelated to the task outside staging, ask the operator what to do. Never mention pending files in the commit message.
- **NEVER** add AI authorship or attribution trailers (e.g. `Co-Authored-By`, as Claude Code inserts by default), regardless of the tool in use.
- `git push` may be blocked by the tool's sandbox. If that happens, run the push outside the sandbox — do not delegate it to the operator because of a network failure.

## Agent skills

### Issue tracker

Issues live in this repo's GitHub Issues, driven by the `gh` CLI. See `docs/agents/issue-tracker.md`.

### Triage labels

The five canonical triage roles, each label string equal to its name. See `docs/agents/triage-labels.md`.

### Domain docs

Single-context: `CONTEXT.md` at the root and the ADRs in `docs/adr/`. See `docs/agents/domain.md`.
