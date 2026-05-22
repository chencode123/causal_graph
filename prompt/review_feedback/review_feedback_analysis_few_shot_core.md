# Review Feedback Few-Shot Core

- Source curated file: `runs/few-shot/review_feedback/review_feedback_analysis_few_shot_curated.json`
- Retained source files: `8`
- Planning patterns: `9`
- Diagnosis patterns: `9`

## Coverage

- `missing intermediate step`: `batch_5/1 :: node_addition_0`
- `delete shortcut edge after adding intermediate step`: `batch_5/1 :: edge_deletion_0`
- `unsupported/speculative condition deletion`: `batch_5/2 :: node_deletion_0`
- `disconnected node integration`: `batch_5/8 :: edge_addition_1; batch_5/9 :: edge_addition_0`
- `schema relabel / precise rename`: `batch_6/8 :: node_update_0; batch_6/9 :: node_update_1`
- `reject deletion of essential hazard node`: `batch_5/5 :: node_deletion_0`
- `uncertainty-aware generalization`: `batch_6/2 :: node_update_0`

## Retained Source Files

- `batch_5/1/review_feedback_analysis_output.json`
- `batch_5/2/review_feedback_analysis_output.json`
- `batch_5/8/review_feedback_analysis_output.json`
- `batch_5/9/review_feedback_analysis_output.json`
- `batch_6/8/review_feedback_analysis_output.json`
- `batch_6/9/review_feedback_analysis_output.json`
- `batch_5/5/review_feedback_analysis_output.json`
- `batch_6/2/review_feedback_analysis_output.json`

## Planning Patterns

- `batch_5/1/review_feedback_analysis_output.json` :: `node_addition_0` [accepted] Add an intermediate event for inadequate dilution/mixing of concentrated feed in the vessel between feed introduction and decomposition.
  Rule: Add the smallest evidence-grounded intermediate step when the source describes a distinct process transition between an upstream action and a downstream reaction.
  Takeaway: When the report explicitly describes an internal transition that explains why a later event occurred, represent it as its own node instead of collapsing it into adjacent events.
- `batch_5/1/review_feedback_analysis_output.json` :: `edge_deletion_0` [accepted] Delete the direct enables edge from feed introduction to decomposition after inserting the intermediate mixing/dilution step.
  Rule: Delete a direct causal edge when a supported intermediate step lies between the same endpoints; keeping the direct link preserves the omission.
  Takeaway: If a new intermediate node makes an older direct link a shortcut, remove the shortcut so the graph reflects the full supported mechanism.
- `batch_5/2/review_feedback_analysis_output.json` :: `node_deletion_0` [accepted] Delete the low-confinement condition node because the cited text does not directly establish confinement as a supported condition.
  Rule: Remove a condition node when the cited evidence does not directly establish that condition as a distinct supported state.
  Takeaway: Accept deletion of speculative condition nodes when the evidence supports exposure or outcome but not the asserted condition itself.
- `batch_5/8/review_feedback_analysis_output.json` :: `edge_addition_1` [accepted] Add enables edge from the high-pressure condition to the major loss-of-containment event.
  Rule: Retained condition nodes should gain an evidence-backed downstream link or be removed.
  Takeaway: If a condition is kept, connect it to the nearest downstream event it materially shapes.
- `batch_5/9/review_feedback_analysis_output.json` :: `edge_addition_0` [accepted] Add a has edge from the discharge strainer entity to the dislodged-basket failure event.
  Rule: Integrate an isolated equipment/entity node by linking it to the supported failure event it participates in.
  Takeaway: When an equipment node is stranded outside the main path, reconnect it to the specific failure event already supported by the narrative.
- `batch_6/8/review_feedback_analysis_output.json` :: `node_update_0` [accepted] Rename the existing node from "Store's exterior back wall" to "Tank directly against store's exterior back wall."
  Rule: Reuse an existing node to represent a missing causal circumstance when the evidence supports it, instead of adding a new node.
  Takeaway: If the graph already contains the right physical element but names it too narrowly, prefer a rename that captures the causal circumstance over creating another node.
- `batch_6/9/review_feedback_analysis_output.json` :: `node_update_1` [accepted] Relabel the release event from ContinuousRelease to InstantRelease.
  Rule: Use the schema label that matches the cited event semantics; a sudden loss of containment should be typed as instantaneous.
  Takeaway: Correct event typing when the evidence clearly describes a sudden release rather than an ongoing discharge.
- `batch_5/5/review_feedback_analysis_output.json` :: `node_deletion_0` [rejected] Delete the terminal hazard consequence node "Confined explosion".
  Rule: Do not delete the only terminal hazard node when the evidence still supports a real consequence and the issue is mainly mechanism or label alignment.
  Takeaway: If the endpoint is semantically imperfect but still represents the supported accident consequence, keep it rather than deleting the graph’s only hazard outcome.
- `batch_6/2/review_feedback_analysis_output.json` :: `node_update_0` [accepted] Rename the ignition-source node from a specific hand-truck spark/friction source to "Unknown ignition source."
  Rule: When the exact ignition source is not definitively identified, model it as an uncertain ignition-source node rather than a specific mechanism.
  Takeaway: If the report confirms ignition but not the exact source, generalize the ignition-source node instead of committing the graph to one candidate source.

## Diagnosis Patterns

- `batch_5/1/review_feedback_analysis_output.json` :: `node_addition_0` [accepted] A distinct internal process step between an input action and a reaction event was missing.
  Interpretation: The issue should be framed as a missing-step diagnosis: the causal narrative required an explicit intermediate state rather than a tighter direct link between existing nodes.
  Rule: The graph skips a supported in-system poor-dilution/poor-mixing overconcentration step between feed entry and decomposition.
  Takeaway: Diagnose a missing-step problem when the source gives a separate mechanism-bearing transition that changes the state of the system before the next event.
- `batch_5/1/review_feedback_analysis_output.json` :: `edge_deletion_0` [accepted] A direct edge was removed once an omitted intermediate mechanism was recognized.
  Interpretation: The connectivity problem is best diagnosed as an omitted intermediate causal step, with the direct edge treated as a shortcut created by that omission.
  Rule: The main connectivity problem is better characterized as a missing causal step rather than a separate weak-edge issue.
  Takeaway: When a direct edge only exists because an intermediate mechanism was omitted, diagnose the omission first and treat the edge as a shortcut artifact.
- `batch_5/2/review_feedback_analysis_output.json` :: `node_deletion_0` [accepted] A condition is asserted from text that does not directly describe that state variable.
  Interpretation: This should be diagnosed as an unsupported condition-node problem rather than as a missing causal step or consequence issue.
  Rule: A node is unsupported when the incident text does not directly establish the asserted condition as a distinct supported state.
  Takeaway: If evidence describes who was affected or what happened, but not the claimed condition, diagnose unsupported condition semantics rather than a pathway gap.
- `batch_5/8/review_feedback_analysis_output.json` :: `edge_addition_1` [accepted] Retained equipment condition needed downstream integration into the release sequence.
  Interpretation: The diagnosis is lack of causal integration for an otherwise valid condition node, not invalid node content.
  Rule: Terminal condition nodes need evidence-supported downstream integration or removal.
  Takeaway: When a condition is well supported but isolated, diagnose the problem as missing integration rather than node invalidity.
- `batch_5/9/review_feedback_analysis_output.json` :: `edge_addition_0` [accepted] An equipment/entity node is present but not connected to the failure event involving that equipment.
  Interpretation: The issue is best framed as poor integration of an existing node into the established event chain, rather than as absent accident content.
  Rule: An isolated composition subgraph that does not connect to the failure/propagation sequence is a disconnected-node issue.
  Takeaway: When a physical asset is isolated from its own failure event, diagnose the problem as missing integration into the main path.
- `batch_6/8/review_feedback_analysis_output.json` :: `node_update_0` [accepted] An existing node partially captures the missing circumstance but is framed too narrowly.
  Interpretation: This should be diagnosed as a missing-step framing issue that can be resolved by recasting an existing node, not necessarily by adding a new one.
  Rule: The missing causal circumstance can be made explicit by reusing an existing node to represent it.
  Takeaway: When evidence supports a broader causal reading of an existing node, diagnose the gap as weak framing of a missing step rather than missing extraction.
- `batch_6/9/review_feedback_analysis_output.json` :: `node_update_1` [accepted] Event type does not match evidence semantics.
  Interpretation: The problem is a schema-mismatch diagnosis about event classification rather than a missing-causality problem.
  Rule: A sudden loss of containment should be classified with the schema-preferred instantaneous release type.
  Takeaway: When the sequence is intact but the event label conflicts with report wording, frame the issue as schema mismatch.
- `batch_5/5/review_feedback_analysis_output.json` :: `node_deletion_0` [rejected] Terminal consequence semantics are disputed, but an explosion consequence is still supported.
  Interpretation: The issue should be framed as mismatch in consequence wording or confinement characterization, not as absence of a valid hazard endpoint. The reviewer treated the node as imperfectly labeled rather than unsupported enough to remove.
  Rule: If evidence still supports the endpoint phenomenon, diagnose it as semantic misalignment before diagnosing it as removable unsupported content.
  Takeaway: Distinguish between a wrong consequence label and no supported consequence at all.
- `batch_6/2/review_feedback_analysis_output.json` :: `node_update_0` [accepted] An over-specific ignition-source label was generalized while the ignition-source role was preserved.
  Interpretation: The issue is best framed as uncertainty/schema handling, not as absence of an ignition-source concept.
  Rule: If the report says the exact ignition source was not definitively identified, diagnose the problem as over-specific ignition-source modeling.
  Takeaway: Diagnose named candidate ignition sources as a schema-mismatch problem when the evidence supports ignition occurrence but not source certainty.

## Usage Note

- This file is the prompt-ready core subset. Use it when prompt budget is limited.
- The larger curated file remains the backup pool for swapping examples within the same rule family.