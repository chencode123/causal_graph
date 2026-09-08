---
name: psep-writing
description: Write manuscript content in PSEP (Process Safety and Environmental Protection) journal style. Use when drafting sections, paragraphs, or captions for submission to PSEP or similar process safety journals.
version: 1.0.0
tags: [Academic Writing, PSEP, Process Safety, Journal Writing]
---

# PSEP Journal Writing Style

## Conciseness Rules

Every sentence must be 25 words or fewer. If a drafted sentence exceeds 25 words, split it or restructure before outputting.

Always prefer the shorter word or phrase when two expressions mean the same thing:

| Avoid | Use instead |
|-------|-------------|
| due to | because of (or restructure with "by") |
| in order to | to |
| is able to | can |
| in the event that | if |
| prior to | before |
| subsequent to | after |
| with regard to | on / about |
| in spite of | despite |
| in the case of | for |
| it is important to note that | (delete or use "notably") |
| a large number of | many |
| make use of | use |
| utilise / utilize | use |
| facilitate | enable / help |
| demonstrate | show |
| investigate | study / examine |
| subsequently | then |
| furthermore | also |
| nevertheless | but / yet |
| approximately | about |
| commence | start |
| terminate | end |
| conduct an analysis | analyse |
| perform an evaluation | evaluate |

## Output Format Rules

NEVER use markdown formatting in output. All text must be plain prose suitable for direct pasting into a Word document:
- No bold (**text**), italics (*text*), or headers (##)
- No inline bold subheadings like "**Structural metrics.**"
- No bullet points or numbered lists inside paragraph text
- No em dashes (---, —); use commas or restructure the sentence
- No semicolons; split into two separate sentences instead
- No colons anywhere; replace with a full stop or restructure the sentence

## Writing Style

PSEP is an engineering journal. Writing should be:
- Formal and precise; avoid colloquial expressions
- **Default to passive voice** throughout. Methods, results, and descriptions of the system must use passive constructions ("was observed", "were calculated", "is reported", "are defined", "were excluded", "is constrained")
- Active voice is only acceptable for explicit statements of contribution: "This study proposes...", "The results show..."
- Never use "we" or "our" for routine procedural descriptions; reserve first person for framing contributions
- Present tense for reporting results and established facts
- Past tense for describing experimental procedures
- Condition names, method names, and experimental labels are lowercase in running text (e.g. "the no revision condition", "the revised graph"). Use title case only in tables, figure legends, and axis labels.

## Paragraph Structure

- Each paragraph covers one idea; do not use bold subheadings within a section
- Transition between topics within a section using topic sentences, not subheadings
- Target approximately 150 words per paragraph; never write a paragraph shorter than 80 words
- Numbers below 10 spelled out in text; 10 and above as numerals
- Percentages written as "2.68%" in text with the % symbol
- Decimal values reported consistently (3 decimal places for scores, 2 for percentages)

## Reporting Results

- Always cite the corresponding table or figure: "As shown in Table X..." or "As reported in Table X..."
- Report values in parentheses or inline: "WL kernel similarity increases from 0.727 to 0.752"
- When listing multiple values across conditions, use consistent order and semicolons: "(0.959, 0.959, and 0.960)"
- Avoid starting sentences with a numeral; restructure if needed

## Citation Style

- PSEP uses numbered citations in square brackets: [1], [2,3]
- Do not write "(Author et al., year)" style in-text; use numbered format
- Place citation number after the period if citing the whole sentence: "...across runs [1]."
- Place before the period if citing a specific claim mid-sentence

## Section Conventions for Results

A typical Results subsection contains:
1. One opening sentence stating what is reported and where (Table/Figure reference)
2. Two to four paragraphs organized by metric group or finding, flowing as continuous prose
3. A closing sentence summarizing the key takeaway or implication

Do not add a subsection title like "Structural metrics." as a bold inline label. Instead, open the paragraph with a topic sentence that names the metric group naturally: "Structural alignment is assessed using WL kernel similarity and 1-normGED."
