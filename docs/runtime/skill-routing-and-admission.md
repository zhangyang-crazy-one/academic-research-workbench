# Skill routing and external admission

The installed plugin exposes three Agent Skills: `academic-research-workbench`
for parent control-plane operations, `academic-research-suite` for research and
paper methodology, and `submission` for packet/readiness/result work after a
manuscript exists. The ten former generic stubs are now ARW references. This
preserves their commands without registering generic names that can collide
with other plugins.

CI can run the source-tree check directly:

```bash
scripts/validate-skills
PYTHONPATH=src python3 -m pytest -q tests/unit/test_skill_conformance.py
```

After constructing a plugin stage, run `scripts/validate-skills --stage-root
<stage-root>`. The validator checks frontmatter, name/description limits,
local `SKILL.md` links, a 500-line warning, stage allowlist membership and the
four-skill cap. The bilingual corpus has 30 Chinese and 30 English requests;
its checks prove that curated cues map to disjoint descriptions. Live host
selection and stability remain a separate #38 evaluation.

The K-Dense `database-lookup` import is an archive-only admission case.
`third_party/admissions/k-dense-database-lookup/admission-receipt.json` binds
the source URL, commit, selected Git tree and file blob, content digest,
MIT declaration and repository license, notice search, scan policy/findings,
and the user's directive against direct staging. The source is kept as
`source-skill.md` outside the plugin skill tree. Reviewers may reproduce the
bounded text scan with:

```bash
scripts/scan-skill-import third_party/admissions/k-dense-database-lookup/source-skill.md
```

Scanning never executes imported content and does not certify safety. The
upstream skill's shell calls, key lookup and mandatory self-citation prohibit
direct registration. The locally modified advisory reference contains only
a database lookup proposal format. It is read after an explicit ARW
assignment; the parent controls retrieval decisions, evidence admission,
artifact acceptance and gates. Advisory labeling is not a sandbox. Trusted
admission of the upstream skill remains pending human review.
