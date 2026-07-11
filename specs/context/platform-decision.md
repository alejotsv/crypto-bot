---
title: Platform decision (Alpaca vs Kraken/Binance/Bybit)
---

# Platform decision

## Goal

Market data, order placement, position monitoring, and stop-loss/take-
profit computed once and attached natively to a trade at order-placement
time (not re-evaluated on a poll loop), for crypto majors.

## Constraints

- Order size: at most ~$400/month total (the user's own expected usage —
  not a system constraint to enforce in code; see `constraints.md`).
- Trading majors only (BTC/ETH and similar) — no need for altcoins or
  exotic pairs.
- US-based, so platform must be legally available in the US.
- Paper trading first: start on Alpaca's paper environment and move to
  live only on explicit instruction — see `constraints.md`.

## Platforms considered

**Binance** — largest global exchange by far, but Binance.com blocks US
persons. US users are routed to Binance.US, which has much thinner
liquidity than the global site and has faced real regulatory pressure
(CFTC/SEC actions in 2023) — real platform risk, ruled out.

**Bybit** — also blocks US residents/KYC. Ruled out.

**Kraken** — US-legal, ~200+ pairs, real exchange order book (deep
liquidity, especially BTC/ETH), claimed native conditional "close"
orders attached at entry (same concept as a bracket order) — **this
claim was not independently verified against Kraken's own docs the way
the Alpaca bracket-order claim below was later checked and found wrong;
treat it as unconfirmed, not fact, if this decision is ever revisited.**
Downsides: older, more idiosyncratic REST API (manual nonce/signature
handling), thin official Python tooling (`krakenex` is a bare low-level
wrapper, more boilerplate than a modern SDK).

**Alpaca** — US-regulated broker-dealer (SEC/FINRA for equities, crypto
arm under state money-transmitter licenses), clean modern REST API,
official Python SDK (`alpaca-py`). Downsides: liquidity sourced from
Alpaca's own market makers rather than a public order book.

> **Correction (2026-07-10, see ADR 0004):** this comparison originally
> credited Alpaca with "native bracket orders (entry + stop-loss +
> take-profit in one call)" as a deciding factor. Verified directly
> against Alpaca's own docs: **bracket/OCO orders are not supported for
> crypto at all** — only Market, Limit, and Stop Limit orders are. That
> specific point was wrong. The rest of the comparison (liquidity,
> US-legal availability, library quality) still holds and wasn't based
> on this error, but the bracket-order advantage should not be counted
> if this decision is ever revisited.

> **Correction (2026-07-11):** this comparison originally said "only
> ~20 supported pairs (majors only)." Verified live against Alpaca's own
> `get_all_assets` API (not docs, not search results): **73 tradable
> crypto pairs** as of 2026-07-11 — well beyond majors (includes DOGE,
> SHIB, PEPE, WIF, BONK, TRUMP, HYPE, and USDC/USDT/BTC-quoted pairs
> alongside the USD-quoted names). The ~20 figure was stale and the
> "hard pair-count ceiling" framing in the Liquidity reality check
> section below no longer holds — this project still trades majors only
> by choice (see Constraints above), not because Alpaca limits it to
> that.

## Liquidity reality check

Execution speed is not meaningfully different between Alpaca and Kraken
— market orders fill near-instantly on both. The liquidity gap only
shows up as *slippage on large orders*; at retail scale (low hundreds of
dollars per trade, matching this project's ~$400/month), Alpaca's
BTC/ETH liquidity is not expected to be a practical problem. (Alpaca's
own reported volume is itself modest — e.g. ~$84k 24h dollar volume on
BTC/USD, verified live 2026-07-11 — since it reflects only Alpaca's own
market-maker flow, not a public order book; still not expected to be a
practical problem at this project's trade sizes.)

## Decision

**Alpaca.** Given the ~$400/month scale and majors-only pair requirement,
Alpaca's 73 tradable pairs (see correction above) comfortably cover
majors, and the clean API/SDK quality gives the least friction to build
against. (The native bracket-order point originally cited here turned
out to be wrong for crypto — see the correction above and ADR 0004 for
how stop-loss/take-profit is actually being built instead.) Codified as
this project's library choice in `constraints.md`; see ADR 0002 for the
library choice and ADR 0004 for the stop-loss/take-profit design
correction.
