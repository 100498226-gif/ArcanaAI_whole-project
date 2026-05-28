# Arcana — Persistent Development Instructions

These instructions override default behavior and apply to every session.

---

## Mandatory auto-audit after every development task

**This rule is non-negotiable and requires no user prompt.**

Whenever you complete a unit of development work — defined as any response where you used
`Edit`, `Write`, or `Bash` to create or modify source code files — you MUST run the
3-pass quality audit from `.claude/commands/audit-phase.md` inline, before finalizing the response.

### When to run
- After implementing a feature, endpoint, service, CLI command, or UI component.
- After fixing a bug or applying a patch.
- For large features: after each logical block (e.g., after writing the service layer,
  after writing the router, after writing the tests) — do not wait until the very end.
- After the final implementation pass, always run one complete end-to-end audit.

### When NOT to run
- Reading files, exploring the codebase, answering questions, writing docs.
- Git operations only (commit, push, branch).
- CONTEXT.md / session log updates.

### How to run
Execute all three passes as described in `.claude/commands/audit-phase.md`:

1. **Pass 1 — Correctness & Bugs**: unused imports, interface lies, silent errors, validation gaps.
2. **Pass 2 — Production Readiness**: SQL portability, async correctness, security, migration coverage.
3. **Pass 3 — Homogeneity**: consistent auth, logging, test, and naming patterns with prior phases.

Fix every issue found within the same response. Re-run the affected pass after fixing.
Confirm test suite passes before declaring the audit complete.

### Output format
State the audit results concisely at the end of your response:
```
Audit — Pass 1: clean | Pass 2: 2 issues fixed (json_extract portability, is_active = 1) | Pass 3: clean
Tests: 277 passed, 1 skipped ✓
```
If a pass is clean with nothing to check (e.g., no DB queries written), note that explicitly.

---

## Project quick-reference

- **Venv:** `source .venv/bin/activate` — always use this, never the base conda env.
- **Tests:** `cd backend && python -m pytest tests/ -q` — count in CONTEXT.md is authoritative.
- **Branch:** feature branches → PR to `main`; never push directly to `main`.
- **Git account:** always `100498226-gif` for git/gh CLI on this project.
- **Commit:** one commit per feature; do not batch unrelated changes.
- **PR merge:** never use `--delete-branch` unless explicitly asked.
