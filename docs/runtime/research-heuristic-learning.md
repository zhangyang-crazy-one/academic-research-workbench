# Governed research learning

The research-learning extension provides project-scoped, evidence-bound lessons
for subsequent research decisions. Its standalone acceptance example is:

```bash
uv run --frozen python extensions/research-learning/examples/qualified_lesson.py OUTPUT
```

The example exercises canonical observation capture, manual candidate publication,
receipt-based shadow evaluation, explicit qualification, consented project
promotion, applicability matching, and an accepted author choice. Numeric inputs
are synthetic fixtures. The later decision explicitly retains an unmeasured
outcome rather than claiming an improvement.

The implementation supports six evaluator modes over accepted sample receipts,
three evidence buckets, deduplication, policy-change re-evaluation, rejection and
successor versions, opt-in activation, authorized retention, and disposable
SQLite projections. Versioned reader contracts remain in core when the extension
is absent. No memory or figure-compiler extension is required.

Tests are `tests/integration/test_research_learning.py` and
`tests/compat/test_research_learning_events.py`. They cover lifecycle behavior,
policy and scope failures, exact retries, process termination at durability
boundaries, historical byte fixtures, schema drift and import direction. The
fixture is an engineering acceptance case, not evidence of research efficacy.

See the [extension guide](../../extensions/research-learning/README.md) for CLI,
configuration, evaluation semantics and actual limits. `research-workflow-evolver`
remains a separate future change: this extension does not generate or execute a
workflow, policy, or skill.
