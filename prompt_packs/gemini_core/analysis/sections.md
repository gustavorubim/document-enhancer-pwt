---
prompt_id: analysis.sections
stage: section_analysis
---

Map every source block to a target section, multiple target sections, or an explicit disposition.
Set each mapping's `disposition` to exactly one canonical value: `preserved`, `moved`, `merged`,
`split`, `omitted`, `uncertain`, or `blocking`. Never emit aliases such as `mapped` or `unmapped`.
Use exactly one target section for `preserved`, `moved`, and `merged`; use at least two target
sections for `split`; and use no target section for `omitted`. A `merged` mapping must cover at
least two source spans, while a `split` mapping must cover exactly one source span. Give every
mapping a non-empty rationale.
Identify missing required sections, contradictions, duplicated or misplaced content, terminology
drift, weak tables, and figures that contain logic not repeated in structured text. Preserve
source order and exact span evidence so the later content ledger can account for every block.
