# Domain Docs

How the engineering skills should consume this repo's domain documentation when exploring the codebase.

## Before exploring, read these

- **`CONTEXT.md`** at the repo root.
- **`docs/adr/`** — read ADRs that touch the area you're about to work in.
- **[`docs/stack.md`](../stack.md)** — the settled technical strategy, stage by stage. It consolidates every ADR into one current-state account and points back at the decision record behind each choice. When a question is about *what the tool does*, start here and zoom into the ADR only for the reasoning.

If any of these files don't exist, **proceed silently**. Don't flag their absence; don't suggest creating them upfront. The `/domain-modeling` skill (reached via `/grill-with-docs` and `/improve-codebase-architecture`) creates them lazily when terms or decisions actually get resolved.

`CONTEXT.md` does not exist yet — this repo reached a settled strategy through `/wayfinder` rather than through `/grill-with-docs`, so no glossary was built along the way. Treat that as a gap to be filled lazily, not a task to schedule.

## File structure

This is a single-context repo:

```
/
├── AGENTS.md                ← the normative instruction source
├── CLAUDE.md                ← pointer only: @AGENTS.md, never edited directly
├── CONTEXT.md               ← not created yet
├── docs/
│   ├── idea.md              ← the idea and requirements
│   ├── stack.md             ← the settled strategy, stage by stage
│   ├── adr/
│   │   ├── 0004-capture-generously-delete-afterwards.md
│   │   ├── 0005-pass-1-pinned-anchor-edge-signal-watchdog.md
│   │   └── …                ← 0001 through 0010
│   ├── agents/              ← this directory
│   └── research/            ← primary-source research behind the decisions
└── tools/
```

There is no `CONTEXT-MAP.md`: there are no separate bounded contexts, and no monorepo.

## Use the glossary's vocabulary

When your output names a domain concept (in an issue title, a refactor proposal, a hypothesis, a test name), use the term as defined in `CONTEXT.md`. Don't drift to synonyms the glossary explicitly avoids.

Until `CONTEXT.md` exists, `docs/stack.md` carries the working vocabulary — *capture*, *anchor*, *watchdog*, *instant*, *manifest*, *pass 1* and *pass 2*, *drop* and *prune*. Use those words as it uses them.

If the concept you need isn't there either, that's a signal — either you're inventing language the project doesn't use (reconsider) or there's a real gap (note it for `/domain-modeling`).

## Flag ADR conflicts

If your output contradicts an existing ADR, surface it explicitly rather than silently overriding:

> _Contradicts ADR 0006 (crop by cutting the presenter away) — but worth reopening because…_

Note that ADR 0003 is **superseded** by ADR 0004, and several ADRs carry amendments. `docs/stack.md` reflects the current state of all of them; an ADR read on its own may not.
