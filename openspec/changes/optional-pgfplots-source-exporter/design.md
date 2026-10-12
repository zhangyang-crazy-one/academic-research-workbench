## Context

Existing SVG uses compile_plot, which derives PlotValue identities and exact fractions from original accepted evidence. PGFPlots is a source-export format; host rendering, fonts and publication review remain separately unverified.

## Goals / Non-Goals

Preserve exact value identities across SVG and TeX. Support compiler-owned point/line/bar/strip/interval marks and approved scales. No TeX installation, arbitrary keys, user macros, shell execution, or source-only export promotion into a qualified SVG receipt.

## Decisions

Compile once with the original compiler and pinned SVG renderer check. Export rational coordinates directly from PlotValue exact numerator/denominator, not rounded display text or new derivations. Retain the complete original plot_values in the source manifest. Layout/category offsets are display-only and cannot create new scientific values. Serialize keys from a fixed vocabulary; character-wise label escaping covers backslash/braces/percent/dollar/ampersand/hash/underscore/caret/tilde and removes line breaks as spaces. Source identity binds exporter implementation. Output is create-only under existing artifact candidates, keyed by IR and exporter identity.

## Risks / Trade-offs

TeX arithmetic and CJK/fonts are host-dependent -> always not_verified until a separately qualified engine/package/font environment exists. TeX parser control syntax -> escaped per character, no raw labels or option fragments. Very large exact fractions -> retain exact source but do not claim compiled rendering success. CTAN package version and unofficial HTML manual version are distinct observations, not compatibility pins.
