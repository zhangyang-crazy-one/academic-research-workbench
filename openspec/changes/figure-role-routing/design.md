## Context
The Codex overlay loads manuscript boundaries while bundled ARS retains its original image and statistics prompts. #151 concerns effective instructions, not renderer expansion.

## Goals / Non-Goals
Goals: deterministic explicit-role briefs, consistent typography/title instructions, excluded mismatched rules and backend gaps. Non-goals: replacing v1 artifacts, adding a renderer, claiming visual quality or admitting scientific evidence.

## Decisions
Use a bounded stdlib JSON planner and one declarative matrix in the ARW-owned overlay. Root and academic-paper-team load the overlay first; full upstream visualization/image templates are contextual references rather than a second normative checklist. Scientific/source/security requirements are invariant. Verified venue constraints and explicit author choices precede role defaults; irreconcilable factual/safety conflicts are reported. A brief declares its font family and target physical size; fixed-font backends report a font gap rather than silently substituting. Style profiles are opt-in. Strict-box rules require explicit selection. Composite children are routed independently and do not inherit quantitative axes globally.

## Risks / Trade-offs
Instruction routing cannot establish source truth, venue verification or actual pixel quality; output labels these not_evaluated. Backend capability records describe existing deterministic v1 SVG only, and unsupported distributions/depth/composition remain unavailable. Changes to these records require renderer-backed evidence. No vendored ARS bytes or source pins change.
