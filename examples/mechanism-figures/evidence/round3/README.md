# Round3 producer repair packet — review pending

已验证：retained round2 normal-figure repairs are implemented and mechanically
screened. This directory is **not** an independent third review. Independent
pixel/reference review: `not_run`; human acceptance: `human_pending`;
publication visual PASS: `false`. OpenSpec 3.4 remains unchecked until the main
agent completes the separate review of these new pixels.

| Finding | Implemented change | Evidence / remaining limit |
| --- | --- | --- |
| R2-EDGE-WRAP / R1-EDGE-LABELS | Intact relation name above the reserved horizontal route segment; no narrow-gutter word splitting | Actual PNG plus librsvg text-ink/orthogonal-edge clearance; independent reader check pending |
| R2-INIT-SCOPE | Separate initialize-once component; initial and retry inputs enter the repeated increment/request component separately | Two-missing toy-rule regression reaches attempts 1 then 2 and stop; this is a synthetic rule evaluation, not an executed model/tool experiment |
| R1-REPRESENTATION-PRIMITIVES | Operand rows with separate red/blue coordinate columns; `1 + 0 = 1` and `0 + 1 = 1` under a sum bar | Exact supplied algebra and source-step consistency, actual PNG/PDF; reader comprehension pending |
| R1-CONSTRAINT-DIFF | Aligned unchanged clauses/conclusion with isolated bold, bordered `AND not penguin` | Source-linked comparison; unknown-flight qualification retained; independent readability pending |
| Local conditional predicates | Direct predicate-to-output leader and relation-port binding, independent of port list order | Reordered-port regression and endpoint screening; not color-only grouping |

The source-author synthetic amendment is explicit in `../../tasks.json` revision
3. `../../tasks.v2.json` and SHA preserve old source bytes. Undoing only the
declared initialization decomposition and new structured display fields restores
all v2 facts exactly (`mechanical.json`). Outcomes, attempts bound, token order,
vector values, retained counterexample and unknown-flight claims are unchanged.
All round1/2 files and reviews are untouched.

- `reviewer-input.json`: new source/IR/SVG/PNG/font/environment exact bindings,
  with no producer scores. Give this to the main agent's separate read-only
  pixel/reference reviewer. No reference downloads or comparison were performed
  in this producer repair.
- `representation.png`, `tool-loop.png`, `constraint.png`: actual 180mm-wide,
  150dpi outputs; corresponding editable SVG, vector PDF, gray PNG and IR are
  adjacent. Heights are 323.497mm, 500mm and 312.914mm respectively. These tall
  authored profiles are not venue qualification; any rescaling needs rechecking
  its actual minimum font size.
- `report.json`: actual accepted exploratory artifacts, successful reproduction,
  blocked publication without review, 3 normal/0 flagged and 16 detected SVG
  corruptions. These are structural checks, not pixel sensitivity estimates.
- `mechanical.json`: actual librsvg font ink bounds, source preservation, exact
  coordinate/guard/predicate checks and edge-label clearance. It screens this
  orthogonal fixture packet, not arbitrary layouts or reader comprehension.
- `run/`: real canonical ledger/source/manifests plus accepted/candidate files
  and quiescent lock files, all synthetic.
- `validation.json`, `pytest.txt`, `reproduction-red.json`, `lint-baseline.json`:
  commands/results and TDD/lint evidence. Full existing-file lint retains 8
  baseline findings with 0 new findings; new files and fatal Python rules pass.
- `manifest.json`: SHA-256/size inventory of this directory except itself.

Actual rasterizer/font/library identities and hashes are recorded per figure in
`report.json`. All 3 rendered with zero unknown glyphs and no border ink. Those
checks do not certify visual quality. The old 1.0.0 renderer identity is
historical; 1.1.0 does not silently reproduce an old renderer digest.

Reproduction commands (from the isolated worktree; choose a fresh output path):

```sh
PYTHONPATH=src:extensions/research-artifact/src \
  /home/zhangyangrui/my_programes/academic-research-workbench/.venv/bin/python \
  examples/mechanism-figures/run.py build/round3-reproduction \
  --raster-python /usr/bin/python3
/usr/bin/python3 examples/mechanism-figures/check_readability.py build/round3-reproduction
```

Task 3.2 stays unimplemented; see `../../strategy-assessment.md` for the exact
representation contrast-source gap and view/trace implementation breakdown.
Native file-base, full plugin staging and host canary were not run here. The ARS
adapter tree is unchanged and its existing pin was recomputed and tested; no pin
change was needed. No CI/dependency/asset-pack changes, push, PR or comments.
