---
title: Project overview
---

# Project overview

## What this is

A crypto trading bot that connects to Alpaca's API to fetch price data,
place orders, and manage open positions programmatically, trading among
Alpaca's supported crypto pairs (majors only — BTC/USD, ETH/USD, and
similar; Alpaca supports 73 tradable pairs total, verified live
2026-07-11 — see `platform-decision.md`'s 2026-07-11 correction).

## Why

This is a **personal learning project** — the goal is to understand
algorithmic trading mechanics (market data, order placement,
position/risk management) end to end using plain rule-based logic,
applied to crypto markets. See `platform-decision.md` in this directory
for how Alpaca was chosen over Kraken, Binance, and Bybit.

## Environment progression

- **Now:** Alpaca paper trading account (fake money). All specs and code
  default to this environment.
- **Later, only on explicit instruction:** Alpaca live account. No
  preset dollar ceiling is designed into the system — spending is
  bounded by an explicit manual gate and/or a live check against real
  account funds. Moving to live is a deliberate, explicit decision the
  user will make — not something to default toward or suggest is "ready"
  without being asked.

## Non-goals (for now)

- No AI/LLM-driven trading decisions.
- No pairs beyond Alpaca's supported crypto list (73 tradable pairs,
  verified live 2026-07-11) — this is a platform limit, not a design
  choice to work around. Trading *majors only* within that list is this
  project's own choice, not a platform restriction (see
  `platform-decision.md`).
- No production concerns: no need for high availability, horizontal
  scaling, distributed infra, or advanced retry/backoff frameworks.
- No backtesting engine unless it comes up later.
- No web UI/dashboard.

See `constraints.md` in this same directory for the hard rules that
apply across all specs and code, and `platform-decision.md` for the
platform research/reasoning behind choosing Alpaca.
