# Persistent project requirements

## Trading robot: retain experience and use it

The user explicitly requires persistent learning as a core product requirement, not an optional report. Preserve this requirement across sessions and implementation changes.

- Keep durable records of trading decisions, abstentions and their reasons, candidate strategy scores, exploration choices, entry-time market context, news evidence and interpretations, order requests and execution acknowledgements, failures, exits, fees, realized outcomes and learning updates. Retain unsuccessful and incomplete cases as well as successful ones.
- Label records with account, symbol, timeframe, strategy, policy/code version, timestamps and stable identifiers. Keep facts, model interpretations and outcome-based assessments distinct.
- Preserve prior records across restarts, upgrades and changes of strategy. Compact summaries must not silently destroy the underlying history. Back up or migrate records before changing storage schemas; do not delete or reset learning history without explicit user authorization.
- Separate retention from eligibility for scoring: retain incomplete, rejected, unverified and legacy data with explicit reasons. Do not invent missing entry evidence, treat open positions as completed successes, count duplicates or use future information in entry decisions.
- Feed verified closed-trade outcomes and entry-time context into subsequent strategy selection. Keep a trace of how and why scores change. Distinguish simulated forward results from executed demo results and live results.
- Learn tendencies from repeated evidence; a loss alone does not prove a decision was wrong, and a win alone does not prove it was right. Avoid claiming guaranteed profitability or permanent prevention of all mistakes.
- Fixed single-strategy execution must not silently replace adaptive learning. The current user-authorized experiment uses adaptive DEMO selection among nine strategies, excludes MACD from entry candidates and keeps news report-only. Existing approved risk and account scope remain independently enforced. The user explicitly removed the DEMO trial's execution time limit on 2026-10-23; do not reintroduce expiry automatically.
- Do not describe the retention requirement as fully implemented without checking coverage, failure handling and restore behavior. Explicitly document gaps and preserve the evidence needed to fix them.

See `docs/trading/LEARNING_REQUIREMENTS_FA.md` for the user-facing requirement and current limitations.

## User approval before trading restrictions or other proposed changes

On 2026-10-23 the user explicitly required disclosure and approval before introducing or changing robot restrictions. Do not silently add test durations, authorization expiries, cooldowns, trade-count or risk limits, entry/exit gates, or other restrictions. Existing session authorization remains valid for the specific actions it covers; do not ask again for those actions.

The user subsequently explicitly approved removing the USD10/per-entry trial risk cap, post-trade cooldown, losing-stop cluster pause and economic-calendar entry block, and implementing all proposals in `docs/trading/RESTRICTIONS_AUDIT_20261023_FA.md`. These changes are installed in EA 3.51. Do not reintroduce those restrictions silently. Entry sizing now uses the existing portfolio allocation and native limits; it is not fixed at USD10. Existing stop losses, demo-only scope, portfolio/account limits, signal rules and other unremoved controls remain. Other changes beyond this approval must be explained and approved before implementation. Report actual current restrictions and distinguish application rules from broker constraints.

Current settings are in `configs/trading_controls.json` and `configs/trading_execution.json`; inspect with `scripts/trading_review.py rules`. Durable revision journals and policy-scoped learning supplement the original records without deleting them. See `docs/trading/APPROVED_CONTROLS_20261023_FA.md` for deployment, verification, commands and limitations.

On 2026-10-23 the user explicitly authorized fixing selection of strategies with negative final scores. Adaptive entry selection now excludes candidates whose unrounded final score is below zero; zero remains eligible. Preserve rejected candidates and reasons in learning records, and do not apply this entry filter to position exits. Scoring weights and exploration remain unchanged. See `docs/trading/NONNEGATIVE_SELECTION_20261023_FA.md` for verification.
