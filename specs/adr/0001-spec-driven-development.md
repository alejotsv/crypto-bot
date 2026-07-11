# ADR 0001: Adopt spec-driven development

Status: Accepted

## Context

This is a learning project where understanding *why* each piece works
matters as much as the code itself. Jumping straight to code risks
building things not fully understood or agreed on, and makes it harder
to reason about safety-critical behavior (order placement, credential
handling, account-fund exposure) after the fact.

## Decision

Every feature is specced under `specs/features/` before any
implementation code is written for it. Specs follow a common template
(see `CLAUDE.md`), start as `Draft`, and require explicit user approval
before implementation begins. Cross-cutting decisions (library choices,
safety rules) are recorded as ADRs under `specs/adr/` rather than being
implied by code.

## Consequences

- Slower to first line of code, but each feature has a reviewed,
  explicit contract before it's built.
- Specs become living documentation of the system, not just planning
  artifacts — they should be kept in sync as understanding evolves.
- Adds overhead for trivial changes; use judgment for typo-level fixes
  that don't need a spec update.
