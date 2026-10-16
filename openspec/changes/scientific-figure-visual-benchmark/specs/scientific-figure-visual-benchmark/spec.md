## ADDED Requirements
### Requirement: Frozen public tasks and structural candidates
The benchmark SHALL freeze four synthetic tasks, physical sizes, expected objects/relations/values and licensing before generation. Loop/mixed tasks MUST retain three structurally different actual previews with identical facts and explicit selection reasons.
#### Scenario: Source inventory drift
- **WHEN** task bytes differ from their frozen digest
- **THEN** generation fails instead of adapting expected answers to the output
### Requirement: Actual final-size rendering
Available backends SHALL render real runtime SVG to PNG with recorded dimensions, rasterizer/font versions and hashes. Missing dependencies or fonts MUST remain unavailable. Mechanical results MUST retain actual small-text/clipping/glyph findings.
#### Scenario: Renderer unavailable
- **WHEN** the optional rasterizer cannot execute
- **THEN** output reports unavailable and does not claim pixel/visual PASS
### Requirement: Separate review and fault evidence
The report SHALL separate provenance/numeric, mechanical, scientific-argument critique and independent human acceptance. Six fault classes MUST be observable through appropriate checks or independent review. Human acceptance MUST bind exact IR/SVG/PNG/environment/font identity and never be fabricated by the producer.
#### Scenario: Changed output or pending review
- **WHEN** any bound output changes or no non-producer review exists
- **THEN** human acceptance remains stale or pending and publication visual approval is not granted
