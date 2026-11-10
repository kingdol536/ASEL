# Domain Docs

How the engineering skills should consume this repo's domain documentation when exploring the codebase.

This repo is **single-context**, but it does not use the default paths (`GLOSSARY.md` at the root, `docs/adr/`).
The project's own locations below are authoritative; `CLAUDE.md` and `README.md` reference them.

## Before exploring, read these

- **`docs/10-GLOSSARY.md`**: the project glossary (Korean). It separates standard/academic terms from the project's narrower working definitions.
- **`docs/decisions/`**: decision records (ADRs), numbered `NNNN-<slug>.md`. Read the ones that touch the area you're about to work in.
- **`docs/00`–`docs/09`**: design docs. `docs/01-SCOPE-AND-REQUIREMENTS.md` holds the decision status (`확정` / `잠정` / `미결정` / `실험 검증 필요` / `장기 확장`) of each requirement.

If any of these files don't exist, **proceed silently**. Don't flag their absence; don't suggest creating them upfront.

## Writing new entries

- New glossary terms go into `docs/10-GLOSSARY.md` (keep its table format and language). Do **not** create a root `GLOSSARY.md`.
- New decisions go into `docs/decisions/` as the next number, using the format in `CLAUDE.md` §6:
  context / candidates / reason for choice / cost of the rejected alternative / risks / verification plan / revisit conditions, plus a status (`확정`, `잠정`, `미결정`, `실험 검증 필요`, `장기 확장`). Do **not** create `docs/adr/`.

## File structure

```
/
├── CLAUDE.md
├── docs/
│   ├── 00-PROJECT-VISION.md … 09-DEVELOPMENT-ROADMAP.md
│   ├── 10-GLOSSARY.md
│   ├── decisions/
│   │   ├── 0001-own-event-loop.md
│   │   └── 0002-python-package-layout.md
│   └── agents/
└── src/asel/
```

## Use the glossary's vocabulary

When your output names a domain concept (in an issue title, a refactor proposal, a hypothesis, a test name), use the term as defined in `docs/10-GLOSSARY.md`. Don't drift to synonyms the glossary explicitly avoids (see its "혼동하기 쉬운 개념" section).

If the concept you need isn't in the glossary yet, that's a signal: either you're inventing language the project doesn't use (reconsider) or there's a real gap (note it for `/domain-modeling`).

## Flag decision conflicts

If your output contradicts an existing decision record or a `확정` item in `docs/01`, surface it explicitly rather than silently overriding:

> _Contradicts decision 0001 (own event loop), but worth reopening because…_
