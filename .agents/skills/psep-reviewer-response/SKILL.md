---
name: psep-reviewer-response
description: Draft or revise evidence-aligned PSEP reviewer responses while jointly applying PSEP organization, style, manuscript-location, and paste-ready revision rules.
---

# PSEP Reviewer Response

Use this skill when a reviewer comment must be answered for a PSEP manuscript or response letter.

## Mandatory same-turn coordination

This skill must always be used together with `../psep-writing/SKILL.md`.

In every response-drafting turn, announce that both skills are being used. Read both instruction files completely before inspecting evidence or drafting text. A prior-turn invocation does not satisfy this requirement.

Use the PSEP skill to organize and write the entire response. Its rules apply to the response summary, revision-location statements, and proposed paste-ready manuscript passages.

Keep the final output as plain text. The structural labels `Response`, `Revisions in`, and `Revision in` may be retained without Markdown formatting.

Do not treat the PSEP skill as a final polishing pass. Apply its paragraph logic, sentence limits, passive voice, terminology, and claim calibration from the first draft.

## Chinese strategy preface

Before showing any revised response or manuscript wording, begin with a concise explanation in Chinese. Explain the response strategy and the main content that will be included.

The Chinese preface should identify the reviewer's central concern, the evidence-based position, and whether the request is fully addressed, partly addressed, or acknowledged as a limitation. It should also flag any factual conflict, unsupported claim, or manuscript inconsistency that must be corrected.

Keep this preface brief and practical. It is guidance for the user, not text for the response letter. Do not mix it into the paste-ready English response.

Use the following output order unless the user requests another format.

`修改思路`

[Two to five concise Chinese sentences describing the strategy and approximate content]

`当前 manuscript 原文`

[Exact, verbatim passage copied from the current manuscript]

`判断`

[Briefly explain in Chinese whether the quoted passage fully answers the comment and identify any remaining gap]

`Response`

[Paste-ready English reviewer response]

[Verified revised passage or clearly labelled proposed passage]

## Manuscript-first quotation and gap assessment

Always quote the relevant current manuscript passage verbatim before drafting or displaying modified wording. Do not silently correct grammar, terminology, numbering, punctuation, or factual content in this quotation.

After the verbatim quotation, assess whether it fully addresses every part of the reviewer comment. If it does, draft the response using only claims supported by that passage and other verified evidence.

If the current passage is insufficient, identify the precise gap before proposing new wording. Display the new wording only under `Proposed revision in` or `Proposed addition to`. Keep it visibly separate from the verbatim manuscript quotation.

Never place proposed, reconstructed, polished, or paraphrased wording below a completed-revision statement such as `The revision was made in Section X, as shown below.` Text following that statement must be copied verbatim from the inspected manuscript.

If a proposed change has not yet been inserted and verified, do not use `The revision was made`. State that a modification is recommended, then provide the proposed passage under an explicit proposal label.

## PSEP content organization

Organize the response around the reviewer's concerns rather than around the order in which revision work was performed.

Open by identifying the issue and its importance. Address each concern in a separate coherent paragraph and preserve the reviewer's order.

For each concern, connect three elements directly. State the study position, the action taken, and the resulting manuscript change.

Combine closely related corrections within one paragraph. Separate validation, baseline, statistical, ontology, and generalizability issues when they require different evidence.

End the summary by naming every verified revised location. Reproduce only exact current manuscript text beneath a completed-revision location statement.

Keep the response summary concise when the same evidence is shown in the manuscript excerpt. State the action and conclusion, but do not repeat every numerical value or sentence before quoting the passage.

For a completed revision, provide a concise response, identify the location, and paste the exact current passage. For an incomplete revision, quote the current passage first and show proposed wording separately.

Use transitions to make the reasoning continuous. Avoid fragmented acknowledgements, defensive language, repeated thanks, and lists of changes without methodological explanation.

## Evidence audit

Before writing, separate the request into distinct reviewer concerns. Check the manuscript, code, results, and project instructions when they are available.

Inspect the current manuscript before claiming that any revision was completed. For verified revisions, copy the displayed passage from the current manuscript rather than recreating or paraphrasing it.

If the manuscript has not yet been changed, first state that a modification is recommended. Introduce any draft under `Proposed revision in` or `Proposed addition to`, and do not claim that the revision was made. Proposed wording may be shown because it is not yet duplicated in the manuscript. If the manuscript cannot be inspected, state that the location and wording require verification before completion language is used.

Classify every proposed statement as one of the following.

- Already supported by existing evidence
- Added during the revision and verified
- Acknowledged as a limitation
- Planned future work
- Unsupported and therefore omitted

Never claim that an analysis, baseline, validation, manuscript edit, or experiment was completed unless its evidence is available.

Use present perfect only for completed and verified revisions. Use limitation language for work that was not completed. Do not present future work as a completed response.

Correct factual errors in reviewer wording politely. Distinguish source reports, analysis cases, development cases, held-out cases, runs, and experimental observations.

Do not invent section numbers, line numbers, citations, table numbers, figure numbers, numerical results, or quoted manuscript text. Use `XXX` placeholders when exact locations are unavailable.

## Response logic

Address every substantive concern in the order raised. For each concern, state one of four outcomes.

- The concern was addressed through a verified revision
- The existing method was clarified with supporting evidence
- The requested addition was not performed and its absence was acknowledged
- The claim was narrowed to match the available evidence

Explain why a requested comparison is unsuitable only when a concrete methodological incompatibility exists. Do not use incompatibility as a generic reason to avoid evaluation.

When only part of a request was completed, acknowledge the remaining gap explicitly. Avoid broad claims of superiority unless external comparisons support them.

## Standard output structure

Follow the user's established structure unless another format is requested.

Response

Begin with one concise sentence thanking the reviewer and naming the issue.

Use one paragraph for each concern. State what was clarified, added, corrected, acknowledged, or narrowed. Include methodological details needed to understand the response.

End the response summary with each exact revised location stated once. Do not use both a general location sentence and a second location label for the same passage.

For one revised location, use this form when line numbers are not final.

The revision was made in Section X, Section title, as shown below. Please see lines XXX–XXX in the revised manuscript.

[Exact passage copied from the current manuscript]

Never substitute an improved draft for the exact passage in this structure.

For several revised locations, introduce them once and place each exact passage immediately after its unique location line.

Use that completion statement only after the current manuscript has been inspected and every stated change has been verified. Otherwise use the following form.

A modification is recommended in Section X and the Limitations section. Proposed passages are provided below.

For completed changes, provide each location only once and follow it immediately with the exact text from the current manuscript.

For wording that is not yet present in the manuscript, use labels that make its proposed status explicit.

Proposed revision in Section X, Section title

[Proposed replacement passage]

Proposed addition to the Limitations section

[Proposed limitation passage]

Do not place either proposed passage beneath `The revision was made`, `The revisions were made`, or an equivalent completed-action statement.

Use plural `Revisions` only when more than one passage appears under the location. Use singular `Revision` for one passage.

## Manuscript passage rules

Write proposed passages as final manuscript prose, not as descriptions of intended edits.

Keep terminology identical across the response summary and manuscript passages. Define a term once and use it consistently.

Keep claims proportional to the study design. Distinguish narrative-supported causal relations from identified causal effects when relevant.

When a limitation is added, state the present boundary first. State future extensions only after that boundary is clear.

Do not duplicate the full manuscript passage inside the response summary. Present it once under the corresponding revision-location label.

## Final checks

Before returning the response, verify that every reviewer concern has a corresponding answer or limitation.

Verify that all stated revisions appear in the supplied manuscript. Reproduce their exact text under the corresponding location labels.

Verify that the relevant current manuscript text was quoted verbatim before any proposed replacement or addition was displayed.

Verify that no proposed wording appears beneath a completed-revision statement.

Verify that existing wording is labelled as a completed revision and absent wording is labelled as a proposed addition or proposed revision.

Verify that counts, conditions, runs, metrics, and dataset levels match the authoritative project evidence.

Verify that no placeholder is silently presented as final information.

Verify that the response summary, manuscript locations, and any proposed passages do not contradict each other.

Verify that no location is stated twice through both an introductory sentence and a repeated `Revision in` label.
