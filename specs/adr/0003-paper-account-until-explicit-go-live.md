# ADR 0003: Paper trading account only, until explicit instruction to go live

Status: Accepted

## Context

This bot will place real orders against a real brokerage API. A bug, a
misconfigured environment variable, or an over-eager default could cause
real financial loss. Moving to a live account is expected eventually,
but has not been decided yet.

## Decision

Every spec and every default configuration targets Alpaca's paper
trading environment. The environment (paper vs. live) is an explicit,
human-set configuration value, never inferred or defaulted to live. Code
must not silently work against live even if live credentials happen to
be present — moving to live is a deliberate act the user takes, not
something Claude suggests is "ready" or switches on proactively. When
live is eventually enabled, order sizing must be bounded only by an
explicit manual gate and/or a live check against real account funds —
never a preset dollar figure hardcoded into sizing logic (see
`specs/context/constraints.md`).

## Consequences

- Slightly more setup friction (an explicit environment flag to set), in
  exchange for a strong safety default.
- Feature specs for order placement and position management must include
  the environment flag and default it to paper explicitly.
