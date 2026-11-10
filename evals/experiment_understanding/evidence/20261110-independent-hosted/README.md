# Retained successful hosted isolation trial

The required real-boundary test passed on the existing Linux native-confinement
CI host. This packet retains only its **public synthetic actual-run files**,
not the other mocked fault-injection test directories in the hosted artifact.
It remains available after hosted artifact expiry. Earlier local failures remain
in the sibling evidence directories and are not relabeled as successes.

## Provenance

- Exact source head:
  [`a3acacdf43f58bc58973b1829d1d85e95d6424f1`](https://github.com/zhangyang-crazy-one/academic-research-workbench/commit/a3acacdf43f58bc58973b1829d1d85e95d6424f1)
- [CI run 42755403803](https://github.com/zhangyang-crazy-one/academic-research-workbench/actions/runs/42755403803)
- Artifact ID: `13735396836`, named `ci-independent-pilot`.
- Downloaded original ZIP SHA-256:
  `ba2e593c6e2f07a5117ee02e1b07f084fb15521c35295d89e7ea9b60ad93dcdb`.
  The ZIP digest was verified during download; this repository preserves the
  selected actual-run bytes, not the whole archive.
- Frozen protocol source `independent.py` SHA-256:
  `b781fb3a107251f571ed5c2e0f6b12c8f8d23674ef89131f4692de284ca798c5`.
- Freeze SHA-256:
  `952272d70e6718d21d890bd799671eca41f31c48f8abcf9d37562afc7906d6ad`.
- Retained receipt file SHA-256:
  `ab89bfbe9f64c16ee13de74c8126ab310edb98799446aa0bbdebb7c27aa2410f`.

`packet-sha256.json` enumerates every copied run file and the independently
prepared `hosted-summary.json`. `run/freeze.json` binds the exact method, public
inputs, source/scorer identities, required controls and limits. Public runner
paths in the method are the intentional file-access canary targets.

## Actual result and scope

**3/3 planned attempts completed and delivered**. Recorded wrapper elapsed
milliseconds are 30, 31 and 30 for batch, graph and buffer respectively. Tokens
and USD remain unavailable. All attempts, costs, inputs, predictions and raw
stdout/stderr are retained; none are replaced by a best-attempt summary.

The actual candidate asserted that host answer/cwd/log/resume paths and the
canary environment variable were unavailable, its cwd was `/work`, a network
connection could not succeed, and its prior-call resume file was absent on each
fresh call. It then predicted all configurations using only the public observed
mean. The run validated that bounded process-isolation protocol on this CI host,
not arbitrary model isolation or scientific quality. The mean method is a weak
plumbing fixture, not evidence of predictive improvement. Host/kernel/runtime
trust and the pilot's documented resource limits still apply.

After copying, source/method/public-input bindings, stdout-to-attempt values,
raw-log hashes, cost records, execution inventory, controls and receipt bindings
were checked again. All three mandatory scorer controls were independently
recomputed, and the existing numeric receipt replay passed from the **copied
bytes**. The retained method was inspected as data and **was not executed**
during extraction, copying or replay.

```bash
scripts/arw-experiment-eval verify \
  --attempts evals/experiment_understanding/evidence/20261110-independent-hosted/run/attempts.json \
  --receipt evals/experiment_understanding/evidence/20261110-independent-hosted/run/receipt.json
```
