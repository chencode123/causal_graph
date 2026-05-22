# Review Feedback Few-Shot Balanced

- Source curated file: `runs/few-shot/review_feedback/review_feedback_analysis_few_shot_curated.json`
- Intended use: prompt-ready pattern file for `graph_diagnosis` and `graph_revision_planning`
- Planning patterns: `13`
- Diagnosis patterns: `13`
- Planning split: `8 accepted / 5 rejected`
- Diagnosis split: `8 accepted / 5 rejected`

## Decision Policy

- Prefer evidence-grounded minimal edits.
- Keep reject examples prominent so the model does not over-learn "accept by default."
- Keep dependent cleanup examples adjacent to the parent decision they depend on.
- Distinguish schema mismatch, uncertainty handling, disconnected integration, and unsupported content.
- Do not delete the only supported hazard endpoint or a necessary ignition-stage node without independent evidence.

## Coverage

- `reject deletion of essential hazard endpoint`: `batch_5/5 :: node_deletion_0`
- `reject dependent edge deletion after parent rejection`: `batch_5/5 :: edge_deletion_0`
- `reject disconnecting uncertain ignition source from ignition event`: `batch_6/2 :: edge_deletion_1`
- `reject deleting explicit ignition-stage node`: `batch_6/7 :: node_deletion_0`
- `reject contingent bypass edge that only works after unapproved restructuring`: `batch_6/7 :: edge_addition_0`
- `accept missing intermediate step`: `batch_5/1 :: node_addition_0`
- `accept delete shortcut after adding intermediate step`: `batch_5/1 :: edge_deletion_0`
- `accept unsupported condition deletion`: `batch_5/2 :: node_deletion_0`
- `accept downstream integration for retained condition`: `batch_5/8 :: edge_addition_1`
- `accept reconnect isolated equipment/entity`: `batch_5/9 :: edge_addition_0`
- `accept uncertainty-aware ignition-source generalization`: `batch_6/2 :: node_update_0`
- `accept reuse existing node to express missing circumstance`: `batch_6/8 :: node_update_0`
- `accept schema/event-type correction`: `batch_6/9 :: node_update_1`

## Rule Families

### Family: Protected Endpoint And Dependent Cleanup

Diagnosis rule:
- If the endpoint phenomenon is still supported, treat it as semantic misalignment before treating it as removable unsupported content.

Planning reject:
- `batch_5/5 :: node_deletion_0` [rejected]
  Proposal: Delete the terminal hazard consequence node `Confined explosion`.
  Why: The endpoint remained a supported hazard consequence even if the confinement wording was imperfect.
  Takeaway: Do not delete the graph's only supported hazard endpoint just because its wording is imperfect.

Planning reject:
- `batch_5/5 :: edge_deletion_0` [rejected]
  Proposal: Delete the edge from rapid vaporization to the hazard consequence.
  Why: That deletion depended entirely on deleting the consequence node, which was rejected.
  Takeaway: Reject dependent cleanup when the parent deletion is not accepted.

### Family: Ignition Role Must Be Preserved Under Uncertainty

Diagnosis rule:
- Uncertainty about source identity does not remove the need to represent ignition causation.

Planning reject:
- `batch_6/2 :: edge_deletion_1` [rejected]
  Proposal: Delete the edge from the ignition-source node to ignition of spilled powder.
  Why: The node was generalized, not removed; ignition still needs an upstream ignition-source link.
  Takeaway: Generalize uncertain ignition sources, but keep the ignition-stage role.

Planning accept:
- `batch_6/2 :: node_update_0` [accepted]
  Proposal: Rename the ignition-source node to `Unknown ignition source.`
  Why: The report supports ignition occurrence, but not a single confirmed source mechanism.
  Takeaway: Replace false specificity with uncertainty-aware naming instead of deleting the role.

### Family: Ignition-Stage Node Preservation Versus Contingent Bypass

Diagnosis rule:
- Do not treat a node as removable duplication if it still carries the explicit ignition stage in the explosion chain.

Planning reject:
- `batch_6/7 :: node_deletion_0` [rejected]
  Proposal: Delete the ignition-source node for the overheated bearing as redundant.
  Why: The node preserved the explicit ignition stage in an ignition-triggered explosion sequence.
  Takeaway: Same-fact overlap is not enough; preserve nodes that carry a required hazard-stage role.

Planning reject:
- `batch_6/7 :: edge_addition_0` [rejected]
  Proposal: Add a direct enables edge from overheated-bearing failure to the primary dust explosion.
  Why: The proposed bypass only made sense if the ignition-stage node were removed first.
  Takeaway: Reject contingent replacement edges unless the restructuring prerequisite is actually approved.

### Family: Missing Step Then Remove Shortcut

Diagnosis rule:
- When the source describes an omitted mechanism-bearing transition, diagnose the missing step first and treat the direct edge as a shortcut artifact.

Planning accept:
- `batch_5/1 :: node_addition_0` [accepted]
  Proposal: Add an intermediate mixing/dilution failure event between feed introduction and decomposition.
  Why: The report described a distinct internal transition that was carrying causal meaning.
  Takeaway: Add the smallest evidence-grounded intermediate step.

Planning accept:
- `batch_5/1 :: edge_deletion_0` [accepted]
  Proposal: Delete the direct feed-introduction to decomposition edge.
  Why: Once the missing step is restored, the direct edge becomes an unsupported shortcut.
  Takeaway: Remove shortcut edges after inserting the supported intermediate mechanism.

### Family: Unsupported Condition Versus Retained Condition Integration

Diagnosis rule:
- Unsupported conditions should be removed; supported-but-isolated conditions should be integrated downstream.

Planning accept:
- `batch_5/2 :: node_deletion_0` [accepted]
  Proposal: Delete the low-confinement condition node.
  Why: The evidence did not directly support confinement as a distinct supported state.
  Takeaway: Remove speculative condition nodes when the text supports outcome/exposure but not the asserted condition itself.

Planning accept:
- `batch_5/8 :: edge_addition_1` [accepted]
  Proposal: Add an enables edge from the high-pressure condition to the major loss-of-containment event.
  Why: The condition was supported and retained, but stranded without downstream causal participation.
  Takeaway: If a condition is kept, connect it to the nearest supported event it materially shapes.

### Family: Reconnect Existing Supported Nodes

Diagnosis rule:
- When an existing node is evidentially supported but structurally stranded, prefer integration over expansion.

Planning accept:
- `batch_5/9 :: edge_addition_0` [accepted]
  Proposal: Add a `has` edge from the discharge strainer entity to the dislodged-basket failure event.
  Why: The equipment node existed, but it was disconnected from the failure event involving that equipment.
  Takeaway: Reconnect isolated equipment/entity nodes to the supported event they participate in.

Planning accept:
- `batch_6/8 :: node_update_0` [accepted]
  Proposal: Rename `Store's exterior back wall` to `Tank directly against store's exterior back wall.`
  Why: The graph already had the right physical element, but the framing was too narrow to express the missing causal circumstance.
  Takeaway: Reuse and broaden an existing node when it can capture the missing circumstance without adding new structure.

### Family: Schema And Event-Type Corrections

Diagnosis rule:
- If the concept is correct but the type/label violates the schema, diagnose schema mismatch rather than causal-content error.

Planning accept:
- `batch_6/9 :: node_update_1` [accepted]
  Proposal: Relabel the release event from `ContinuousRelease` to `InstantRelease`.
  Why: The event semantics described a sudden loss of containment.
  Takeaway: Correct event typing when the sequence is right but the schema label is wrong.

## Prompt Ordering Note

- The paired JSON file intentionally places all reject patterns first.
- Current injection logic reads `planning_patterns` and `diagnosis_patterns` in file order.
- This file is therefore organized to match the JSON ordering rather than to maximize narrative smoothness.

## Retained Source Files

- `batch_5/1/review_feedback_analysis_output.json`
- `batch_5/2/review_feedback_analysis_output.json`
- `batch_5/5/review_feedback_analysis_output.json`
- `batch_5/8/review_feedback_analysis_output.json`
- `batch_5/9/review_feedback_analysis_output.json`
- `batch_6/2/review_feedback_analysis_output.json`
- `batch_6/7/review_feedback_analysis_output.json`
- `batch_6/8/review_feedback_analysis_output.json`
- `batch_6/9/review_feedback_analysis_output.json`
