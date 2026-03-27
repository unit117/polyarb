# PMXT Mar 20-25 Validation Report

**Date:** 2026-03-27  
**Validation window:** 2026-03-20 to 2026-03-25  
**Database:** isolated `polyarb_backtest` only  
**Goal:** validate that the February spike fixes generalize on a higher-coverage window

---

## Summary

This validation window confirmed that the February spike fixes generalize when price coverage exists.

- Price coverage reached **98.9%** of markets in verified pairs
- The cleaned-up logic produced **1,792 opportunities**
- The backtest executed **238 trades**
- Ending return was **+0.13%**
- Sharpe was **9.98**

Conclusion: the February 22-27 window was primarily data-starved, not logic-limited.

---

## Comparison To Feb 22-27

| Metric | Feb 22-27, 2026 | Mar 20-25, 2026 |
|--------|------------------|-----------------|
| Coverage | 25.7% | 98.9% |
| Opportunities | 378 | 1,792 |
| Trades | 180 | 238 |
| Return | +0.01% | +0.13% |
| Sharpe | 1.91 | 9.98 |

---

## Interpretation

The important result is not just that March performed better. It is that the same post-spike logic baseline remained productive once price coverage was available:

- Conditional cleanup removed phantom arbitrage rather than suppressing real opportunities
- Implication-direction backfill recovered executable trades in a way that transferred to a new window
- Coverage, not pair logic, was the main limiter in February

This gives enough evidence to treat the current classifier/constraint baseline as the correct starting point for larger replay work.

---

## Next Step

No more micro-tuning is justified on the February slice.

The next meaningful task is to turn the validated spike workflow into a reproducible replay baseline and run it over a materially longer March 2026 range.
