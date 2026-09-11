# Phase 8.1 — Hardened Go-Live

Phase 8.1 closes the production-governance gaps identified in the Phase 8 audit.

## Runtime capital ramp

- First activation is forced to stage 0 = 10% of the human-approved capital allocation.
- The active stage is persisted under `artifacts/go_live/capital_ramp.json`.
- A live process cannot skip a stage or request a different stage than the persisted approved stage.
- Every opening action is checked by the independent risk layer against the current ramp notional limit.
- Advancement requires at least 7 days, positive PnL, acceptable drawdown, and explicit human approval.

Example:

```bash
python scripts/advance_ramp.py --days 7 --pnl-positive --max-drawdown 0.05 --reviewer "Human Reviewer" --human-signoff
```

## Continuous live telemetry

The live loop feeds every inference cycle into `RiskManager.observe()` with:

- account equity and return
- latest feature vector
- WebSocket health
- REST error state

Risk pauses are fail-closed: subsequent opening actions are vetoed. Reconciliation continues independently.

## Governance supervisor

`LiveGovernanceSupervisor` runs for the lifetime of the live process and:

- watches risk pause state;
- emits a critical review alert when trading is paused;
- optionally starts challenger retraining on drift/performance triggers;
- optionally starts scheduled retraining at a configurable interval;
- never promotes a challenger.

Set `--retrain-command` on `scripts/live_trade.py` to provide an offline training command. The command must itself create and validate a challenger artifact. The supervisor records the command outcome but cannot authorize production promotion.

## Human-only model promotion

Use:

```bash
python scripts/promotion.py register --model <candidate> --metadata <metadata>
python scripts/promotion.py promote --reviewer "Human Reviewer" --human-signoff
python scripts/promotion.py rollback --reviewer "Human Reviewer" --human-signoff
```

Promotion and rollback are explicitly human-gated. There is no automatic production promotion path.

## Security boundary

IP allowlisting and withdrawal disablement remain account-level Binance controls. Phase 8.1 treats them as mandatory human attestations; it does not falsely claim the local process can verify Binance account-security configuration.

## Database

Apply `sql/005_phase81_governance.sql` after the previous migrations. It records runtime governance events, capital-ramp approvals, and model lifecycle state.

## Operational invariant

The intended production state machine is:

`paper evidence -> human go-live approval -> stage-0 live -> supervised risk controls -> drift/reconciliation monitoring -> challenger retraining -> shadow -> human review -> optional promotion -> staged capital increase`

No edge in this state machine automatically grants production capital to a newly trained model.
