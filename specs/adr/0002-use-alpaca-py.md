# ADR 0002: Use `alpaca-py` for broker API access

Status: Accepted

## Context

This project needs a Python client for market data, order placement,
position monitoring, and native bracket-order stop-loss/take-profit
against a crypto brokerage account. The platform itself (Alpaca) was
chosen over Kraken, Binance, and Bybit based on US legal availability,
liquidity adequacy at this project's trading scale, and native
bracket-order support (see `specs/context/platform-decision.md` for the
full comparison). This ADR covers the client *library* choice, given
Alpaca as the platform.

## Decision

Use `alpaca-py`, Alpaca's official Python SDK, for all API access
(market data, orders, positions, account info). Switching to a different
client library (a community wrapper, raw `requests` calls, `ccxt`, etc.)
requires a new ADR justifying the change.

## Consequences

- Ties implementation to Alpaca-specific request/response shapes and
  whatever `alpaca-py` exposes — acceptable since ADR-level platform
  lock-in was already accepted when Alpaca was chosen as the broker.
- Official SDK means better alignment with Alpaca's own documentation and
  faster adoption of new Alpaca features (e.g. bracket orders) without
  waiting on a third-party wrapper.
