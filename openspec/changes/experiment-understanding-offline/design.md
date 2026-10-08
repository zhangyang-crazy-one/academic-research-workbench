## Data and trust boundary

The original producer and hidden reference are committed and digest-bound so a
reviewer can regenerate them. `prepare` loads only the public taskset,
observations and manifest. The operator passes only its JSON output to a
candidate model. `score` alone loads the hidden reference and checks it against
the frozen producer, observed values and manifest. This gives an offline
reproducible fixture, not secrecy from someone with repository access.

All three tasks use a preselected eight-row subset of sixteen configurations.
The same rows and observation digest feed each route and the pure-Python
pair-effect ridge (fixed regularization lambda 1). A later sampling-policy
comparison needs a separate contract.

## Scoring and replay

The attempt file declares one task slot per route before scoring. Missing slots
and extra submissions remain in the denominator. A delivered attempt must bind
the public task and observation digests, use the exact approved eight rows,
choose one configuration, and provide each of sixteen finite predictions once.
Failure yields typed reasons, `delivery=0`, null raw errors and zero bounded
quality. For delivery, the scorer computes true selection regret, mean absolute
conditional contrasts over factor/context pairs, and mean absolute second
differences over factor pairs/context combinations. Fixed scales in the taskset
map each raw error to bounded quality `max(0, 1 - error/scale)`; the delivery
rate is the fourth axis. Summaries expose all-attempt quality, delivered-only
error and quality, and counts. Missing cost data is `unavailable`.

The receipt hashes exact attempt bytes and frozen fixture bytes, then hashes
its canonical body. Verification recomputes the full receipt from retained
inputs. The receipt always states live comparison `not_measured`; a separate
authorized run would need new evidence and an explicit reporting contract.
