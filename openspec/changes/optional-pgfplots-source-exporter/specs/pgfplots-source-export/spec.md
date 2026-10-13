## ADDED Requirements

### Requirement: Exact shared numerical inputs
The exporter SHALL consume the same compiled PlotValues and retain their exact values and IDs without deriving numerical results again.

#### Scenario: Rounded display collision
- **WHEN** two exact values share rounded display text
- **THEN** exported TeX retains distinct exact rational coordinates and the original plot_value_ids

### Requirement: Inert labels and owned syntax
The exporter MUST escape all user labels as ordinary TeX text and accept no arbitrary PGF keys or user macros.

#### Scenario: Adversarial label
- **WHEN** labels contain backslashes, braces, percent, dollar, ampersand or caret sequences
- **THEN** those characters remain inert text and cannot become commands, comments or options

### Requirement: Source export is unverified rendering
The operation SHALL remain deterministic and source-only with not_verified render/publication status and no added base dependency.

#### Scenario: Export without TeX
- **WHEN** the same compiled IR and exporter identity are exported twice
- **THEN** source bytes match and no TeX executable is called or qualification status promoted
