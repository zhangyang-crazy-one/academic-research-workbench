# Writing detection audit

The author needs a source-bound revision workflow that measures configured text detectors on both manuscript versions while preserving facts and asking for semantic review. Existing `writing.statistical_humanize` only compares surface metrics. This change extends the existing writing-humanization capability and its issue #6 amendment; it does not change manuscript text automatically.

The writing CLI consumes local source/revision files or an accepted source and exact-span proposal. It records distinct classification and algorithm-specific watermark observations, with model and input identity and honest unavailable states. External transmission requires an explicit flag. The existing fact-locked results checker and writing preservation review remain separate from detector scores.
