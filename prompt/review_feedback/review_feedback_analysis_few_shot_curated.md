# Review Feedback Few-Shot Curated

- Source aggregated file: `runs/few-shot/review_feedback/review_feedback_analysis_aggregated.json`
- Retained source files: `10`
- Core subset source files: `8`
- Planning patterns: `42`
- Diagnosis patterns: `42`
- Accepted planning patterns: `37`
- Rejected planning patterns: `5`

## Curation Policy

- Keep only matched planning/diagnosis patterns from the recommended clean `batch_5` and `batch_6` cases.
- Exclude `batch_4` by default because many cases contain stale analysis output, legacy decisions, or untracked manual edits.
- Exclude unresolved decisions, `untracked_*` edits, `No matching ... exists` records, and implicitly covered suggestions from the main few-shot pool.

## Retained Source Files

- `batch_5/1/review_feedback_analysis_output.json` (Core subset)
- `batch_5/2/review_feedback_analysis_output.json` (Core subset)
- `batch_5/5/review_feedback_analysis_output.json` (Core subset)
- `batch_5/8/review_feedback_analysis_output.json` (Core subset)
- `batch_5/9/review_feedback_analysis_output.json` (Core subset)
- `batch_6/2/review_feedback_analysis_output.json` (Core subset)
- `batch_6/4/review_feedback_analysis_output.json`
- `batch_6/7/review_feedback_analysis_output.json` (Core subset)
- `batch_6/8/review_feedback_analysis_output.json`
- `batch_6/9/review_feedback_analysis_output.json` (Core subset)

## Planning Patterns By Case

### `batch_5/1/review_feedback_analysis_output.json`

- `node_addition_0` [accepted] Add an intermediate event for inadequate dilution/mixing of concentrated feed in the vessel between feed introduction and decomposition.
  Rule: Add the smallest evidence-grounded intermediate step when the source describes a distinct process transition between an upstream action and a downstream reaction.
  Takeaway: When the report explicitly describes an internal transition that explains why a later event occurred, represent it as its own node instead of collapsing it into adjacent events.
- `edge_deletion_0` [accepted] Delete the direct enables edge from feed introduction to decomposition after inserting the intermediate mixing/dilution step.
  Rule: Delete a direct causal edge when a supported intermediate step lies between the same endpoints; keeping the direct link preserves the omission.
  Takeaway: If a new intermediate node makes an older direct link a shortcut, remove the shortcut so the graph reflects the full supported mechanism.
- `node_update_0` [accepted] Relabel the hazard node so its label uses the schema-required value HazardConsequence rather than the hazard name.
  Rule: Correct schema-only label mismatches while preserving the existing node meaning.
  Takeaway: When a node is semantically correct but structurally mislabeled, prefer a label fix over replacing the node or changing its meaning.

### `batch_5/2/review_feedback_analysis_output.json`

- `node_deletion_0` [accepted] Delete the low-confinement condition node because the cited text does not directly establish confinement as a supported condition.
  Rule: Remove a condition node when the cited evidence does not directly establish that condition as a distinct supported state.
  Takeaway: Accept deletion of speculative condition nodes when the evidence supports exposure or outcome but not the asserted condition itself.
- `edge_addition_0` [accepted] Add a material-to-vapor-phase 'has' edge to give the vapor condition an incoming grounding connection.
  Rule: Add a minimal grounding edge when a condition node is otherwise disconnected from supported upstream context.
  Takeaway: Accept the smallest edge addition that restores grounding for an under-integrated condition instead of expanding the graph with new nodes.
- `edge_deletion_0` [accepted] Delete the low-confinement-to-flash-fire edge because it depends on a condition that is not distinctly supported.
  Rule: When a supporting condition is not distinctly supported, remove its dependent causal edge as well.
  Takeaway: Accept removal of edges that rely entirely on an unsupported node to keep the graph evidence-grounded.

### `batch_5/5/review_feedback_analysis_output.json`

- `node_deletion_0` [rejected] Delete the terminal hazard consequence node "Confined explosion".
  Rule: Do not delete the only terminal hazard node when the evidence still supports a real consequence and the issue is mainly mechanism or label alignment.
  Takeaway: If the endpoint is semantically imperfect but still represents the supported accident consequence, keep it rather than deleting the graph’s only hazard outcome.
- `edge_deletion_0` [rejected] Delete the edge from rapid vaporization to the hazard consequence.
  Rule: Do not remove an attachment edge when its deletion was justified only by deletion of a node that is being retained.
  Takeaway: When a node-deletion proposal is rejected, reject dependent edge removals unless there is an independent edge-level diagnosis.
- `node_deletion_1` [accepted] Delete the steam-venting event as a dead-end observation.
  Rule: Remove supported but disconnected observations when they have no distinct downstream causal role.
  Takeaway: A factually supported event can still be removed if it only serves as a dead-end observation and does not advance the causal chain.
- `edge_deletion_1` [accepted] Delete the edge from boiling to the steam-venting event.
  Rule: When deleting a dead-end node, also remove incident edges that only feed that deleted observation.
  Takeaway: Clean up edges attached solely to a deleted disconnected node.

### `batch_5/8/review_feedback_analysis_output.json`

- `edge_addition_0` [accepted] Add enables edge from the no-venting repair state to the pressure-buildup step.
  Rule: When evidence shows a state affects pressure retention rather than leak formation, reconnect it to the pressure-buildup step.
  Takeaway: Fix unsupported causation by rerouting the edge to the specific downstream mechanism the evidence actually supports.
- `edge_deletion_0` [accepted] Delete the enables edge from the no-venting repair state to the internal leak event.
  Rule: Delete edges that contradict the locally stated mechanism for how a leak path formed.
  Takeaway: If the narrative assigns a leak path to a different physical cause, remove the unsupported upstream edge.
- `node_deletion_0` [accepted] Delete the two-phase condition node.
  Rule: Remove disconnected background conditions when no distinct downstream causal role is supported.
  Takeaway: Delete terminal condition stubs instead of forcing weak causal links.
- `edge_addition_1` [accepted] Add enables edge from the high-pressure condition to the major loss-of-containment event.
  Rule: Retained condition nodes should gain an evidence-backed downstream link or be removed.
  Takeaway: If a condition is kept, connect it to the nearest downstream event it materially shapes.
- `edge_addition_2` [accepted] Add enables edge from the low-confinement condition to the dispersion event.
  Rule: Retained release-environment conditions should be linked to the step they influence, such as dispersion.
  Takeaway: Use environmental condition nodes only when they are integrated into a supported release or dispersion mechanism.
- `edge_deletion_1` [accepted] Delete the has edge from the ACSR location to the two-phase condition.
  Rule: When a disconnected condition node is removed, remove its dependent support edge as cleanup.
  Takeaway: After deleting a nonfunctional node, also delete the attachment edges that only existed to support it.

### `batch_5/9/review_feedback_analysis_output.json`

- `node_deletion_0` [accepted] Delete the standalone material node for steel wool.
  Rule: Remove a standalone node when it lacks a separate evidence-grounded causal role and only preserves a disconnected subgraph.
  Takeaway: If a material-detail node does not contribute its own supported causal step, prefer deleting it rather than keeping an isolated side branch.
- `edge_addition_0` [accepted] Add a has edge from the discharge strainer entity to the dislodged-basket failure event.
  Rule: Integrate an isolated equipment/entity node by linking it to the supported failure event it participates in.
  Takeaway: When an equipment node is stranded outside the main path, reconnect it to the specific failure event already supported by the narrative.
- `edge_addition_1` [accepted] Add an enables edge from mechanical-seal dry-running damage to the hot mechanical seal ignition-source event.
  Rule: Give a dangling damage or observation node a supported downstream role when evidence ties it to an existing causal step.
  Takeaway: If a failure-evidence node ends the chain prematurely, connect it to the next supported event instead of leaving it as a terminal leaf.
- `edge_deletion_0` [accepted] Delete the has edge from the discharge strainer to the steel wool node.
  Rule: Remove a composition edge when its only effect is to preserve an isolated subgraph after the dependent node is deleted.
  Takeaway: After deleting an unsupported standalone node, also remove any leftover composition edge that would keep the disconnected fragment alive.

### `batch_6/2/review_feedback_analysis_output.json`

- `node_update_0` [accepted] Rename the ignition-source node from a specific hand-truck spark/friction source to "Unknown ignition source."
  Rule: When the exact ignition source is not definitively identified, model it as an uncertain ignition-source node rather than a specific mechanism.
  Takeaway: If the report confirms ignition but not the exact source, generalize the ignition-source node instead of committing the graph to one candidate source.
- `edge_deletion_0` [accepted] Remove the edge from rain-driven relocation activity to the ignition-source node.
  Rule: Do not anchor an uncertain ignition source to one specific upstream activity when the evidence lists multiple possible sources.
  Takeaway: Delete upstream links that force an uncertain ignition source into a single specific pathway unsupported by the report.
- `edge_deletion_1` [rejected] Delete the edge from the ignition-source node to ignition of spilled powder.
  Rule: After generalizing an uncertain ignition source, retain a generic causal link from the ignition-source node to the ignition event.
  Takeaway: Do not remove a required ignition-source-to-ignition link just because the ignition source has been renamed to reflect uncertainty.
- `edge_addition_1` [accepted] Add an edge from the Solid condition node to the powder spill event.
  Rule: A condition node that is disconnected downstream should be linked to an evidence-supported mechanism step or else removed.
  Takeaway: When a condition node is causally unused, add the most directly supported downstream connection that gives it an active role in the mechanism.

### `batch_6/4/review_feedback_analysis_output.json`

- `node_addition_0` [accepted] Add an intermediate event for propagation from the Dry Grit Filter to other previously uninvolved process equipment before broader facility-wide explosions.
  Rule: Add an intermediate node when the source material explicitly describes a distinct causal step that is currently collapsed into a broader transition.
  Takeaway: When a report names a separate propagation stage, represent it as its own event node rather than folding it into a downstream consequence.
- `edge_deletion_0` [accepted] Delete the direct enables edge from Dry Grit Filter propagation to multiple secondary dust explosions.
  Rule: Remove a direct edge when an explicitly supported intermediate step should sit between the same source and target.
  Takeaway: If a direct link skips over a documented intermediate event, delete the shortcut edge after inserting the missing step.
- `edge_addition_0` [accepted] Add an enables edge from the solid-phase condition node to the dust-lofting event.
  Rule: Connect a supported but disconnected condition node to a supported downstream event when that gives the condition an explicit causal role.
  Takeaway: Do not leave supported condition nodes isolated; attach them to a concrete downstream event if the evidence supports a causal contribution.

### `batch_6/7/review_feedback_analysis_output.json`

- `node_addition_0` [accepted] Add a housekeeping-failure event for inadequate housekeeping practices allowing sugar and dust accumulations to remain, linked to the accumulation event.
  Rule: Add an explicit missing step when the source identifies a separate contributor that allowed hazardous accumulations to persist.
  Takeaway: When hazardous deposits are attributed to both release and failure to remove material, model housekeeping as its own causal step.
- `node_deletion_0` [rejected] Delete the ignition-source node for the overheated bearing as redundant with the mechanical-failure node.
  Rule: Do not delete a supported node when it preserves the explicit ignition stage in an ignition-triggered explosion chain.
  Takeaway: Treat apparent duplicates cautiously if one node carries a necessary ignition-stage role in the hazard sequence.
- `edge_addition_0` [rejected] Add a direct enables edge from the overheated-bearing mechanical failure to the primary dust explosion.
  Rule: Do not add a direct replacement edge when its justification depends on a node deletion that was not approved.
  Takeaway: If an intermediate node is retained, avoid adding a bypass edge that only existed to replace it.
- `edge_addition_1` [accepted] Add an enables edge from the solid-phase condition to the hazardous accumulation event.
  Rule: Connect disconnected condition nodes to the operative event they enable when they otherwise remain dead ends.
  Takeaway: Use downstream links from condition nodes to integrate isolated material-property subgraphs into the main accident chain.
- `edge_addition_2` [accepted] Add an enables edge from combustibility to the secondary-explosion event.
  Rule: Link a fuel-property condition to the explosion event where that property is functionally used as fuel.
  Takeaway: When combustibility is isolated, connect it to the explosion step it makes possible.
- `edge_deletion_0` [accepted] Delete the enables edge from the overheated-bearing mechanical-failure node to the overheated-bearing ignition-source node.
  Rule: Remove an edge that exists only to support a redundant local duplication and is not needed for the retained chain structure.
  Takeaway: If two nearby nodes express nearly the same local fact, pruning the connecting edge can reduce redundancy even when both nodes stay.

### `batch_6/8/review_feedback_analysis_output.json`

- `edge_addition_0` [accepted] Add an enables edge from indoor flammable-mixture accumulation to the ignition event.
  Rule: Restore a broken downstream chain by linking the accumulated hazardous state to the ignition event.
  Takeaway: When a key process event is a dead end just before the loss event, add the minimal downstream edge that reconnects the main sequence.
- `node_update_0` [accepted] Rename the existing node from "Store's exterior back wall" to "Tank directly against store's exterior back wall."
  Rule: Reuse an existing node to represent a missing causal circumstance when the evidence supports it, instead of adding a new node.
  Takeaway: If the graph already contains the right physical element but names it too narrowly, prefer a rename that captures the causal circumstance over creating another node.
- `edge_addition_1` [accepted] Add an enables edge from the tank-placement circumstance to propane entry into the store.
  Rule: Make an already extracted causal circumstance explicit by connecting it to the event it enables.
  Takeaway: When an evidence-backed circumstance node already exists but is not in the chain, connect it to the affected event rather than adding parallel structure.
- `node_update_1` [accepted] Relabel the hazard consequence node from "Confined explosion" to "HazardConsequence."
  Rule: Hazard consequence nodes should use the schema label, with the specific consequence kept in the name field.
  Takeaway: Fix schema-only node errors with a relabel, without changing the underlying consequence meaning.

### `batch_6/9/review_feedback_analysis_output.json`

- `node_update_0` [accepted] Rename the suction-valve event to include the mistaken closed indication from wrench position while noting that the valve actually remained open.
  Rule: If an explicit initiating mechanism is missing, refine the existing event node to capture it with minimal graph change.
  Takeaway: Prefer a precise rename over a new node when the omitted mechanism is a more specific explanation of an existing event.
- `node_update_1` [accepted] Relabel the release event from ContinuousRelease to InstantRelease.
  Rule: Use the schema label that matches the cited event semantics; a sudden loss of containment should be typed as instantaneous.
  Takeaway: Correct event typing when the evidence clearly describes a sudden release rather than an ongoing discharge.
- `edge_addition_0` [accepted] Add an enables edge from liquid phase to the release event.
  Rule: Condition nodes should not remain stranded descriptors; add downstream causal links when the condition participates in the accident sequence.
  Takeaway: When a condition is evidenced as part of the loss event, connect it downstream instead of leaving it only as a material attribute.
- `edge_addition_1` [accepted] Add an enables edge from high temperature to the release event.
  Rule: Condition nodes should not remain stranded descriptors; add downstream causal links when the condition participates in the accident sequence.
  Takeaway: Give supported process conditions a causal role when they are currently disconnected from the event chain.
- `edge_addition_2` [accepted] Add an enables edge from combustibility to the jet-fire consequence.
  Rule: Connect a condition node to the consequence it materially enables when ignition-and-burning evidence supports that role.
  Takeaway: Tie combustible or flammable properties to the fire consequence when they are otherwise left disconnected.

## Diagnosis Patterns By Case

### `batch_5/1/review_feedback_analysis_output.json`

- `node_addition_0` [accepted] A distinct internal process step between an input action and a reaction event was missing.
  Interpretation: The issue should be framed as a missing-step diagnosis: the causal narrative required an explicit intermediate state rather than a tighter direct link between existing nodes.
  Rule: The graph skips a supported in-system poor-dilution/poor-mixing overconcentration step between feed entry and decomposition.
  Takeaway: Diagnose a missing-step problem when the source gives a separate mechanism-bearing transition that changes the state of the system before the next event.
- `edge_deletion_0` [accepted] A direct edge was removed once an omitted intermediate mechanism was recognized.
  Interpretation: The connectivity problem is best diagnosed as an omitted intermediate causal step, with the direct edge treated as a shortcut created by that omission.
  Rule: The main connectivity problem is better characterized as a missing causal step rather than a separate weak-edge issue.
  Takeaway: When a direct edge only exists because an intermediate mechanism was omitted, diagnose the omission first and treat the edge as a shortcut artifact.
- `node_update_0` [accepted] Node meaning stayed the same while only the schema label changed.
  Interpretation: This should be diagnosed as a schema-mismatch issue, not as an unsupported hazard definition or a wrong hazard selection.
  Rule: The hazard consequence node uses the hazard name as its label instead of the schema-required label HazardConsequence.
  Takeaway: If the content is right but the field value violates the schema, diagnose it as schema mismatch rather than as a substantive causal-model error.

### `batch_5/2/review_feedback_analysis_output.json`

- `node_deletion_0` [accepted] A condition is asserted from text that does not directly describe that state variable.
  Interpretation: This should be diagnosed as an unsupported condition-node problem rather than as a missing causal step or consequence issue.
  Rule: A node is unsupported when the incident text does not directly establish the asserted condition as a distinct supported state.
  Takeaway: If evidence describes who was affected or what happened, but not the claimed condition, diagnose unsupported condition semantics rather than a pathway gap.
- `edge_addition_0` [accepted] A condition participates only downstream and lacks any incoming grounding link.
  Interpretation: This should be framed as a disconnected or under-integrated condition-layer issue, not as evidence that a new event or condition must be introduced.
  Rule: A condition lacking an incoming grounding connection is a disconnected-node problem.
  Takeaway: When a condition is only used downstream, diagnose missing grounding connectivity before diagnosing a missing step.
- `edge_deletion_0` [accepted] An edge is questionable only because its source condition is weakly supported.
  Interpretation: This should be treated as derivative cleanup from an unsupported-node diagnosis rather than as a standalone edge-type, direction, or relation error.
  Rule: No separate unsupported-edge diagnosis is needed when the edge problem follows from a speculative source condition.
  Takeaway: If an edge becomes invalid only because its source node is unsupported, diagnose the node first and treat the edge as secondary cleanup.

### `batch_5/5/review_feedback_analysis_output.json`

- `node_deletion_0` [rejected] Terminal consequence semantics are disputed, but an explosion consequence is still supported.
  Interpretation: The issue should be framed as mismatch in consequence wording or confinement characterization, not as absence of a valid hazard endpoint. The reviewer treated the node as imperfectly labeled rather than unsupported enough to remove.
  Rule: If evidence still supports the endpoint phenomenon, diagnose it as semantic misalignment before diagnosing it as removable unsupported content.
  Takeaway: Distinguish between a wrong consequence label and no supported consequence at all.
- `edge_deletion_0` [rejected] The edge challenge was entirely dependent on the disputed terminal-node diagnosis.
  Interpretation: This was not treated as an independent edge defect. The reviewer implicitly prioritized resolving the endpoint framing first, so the edge remained because the downstream consequence node remained.
  Rule: Do not diagnose a dependent edge as separately removable when its only problem comes from a node diagnosis that is not accepted.
  Takeaway: Resolve node validity before escalating attached-edge deletions that have no stand-alone diagnostic basis.
- `node_deletion_1` [accepted] A supported event node has no downstream causal participation.
  Interpretation: The reviewer accepted the diagnosis that a node can be evidentially true yet still be a disconnected-node problem if it functions only as an observation and not as part of a complete causal path.
  Rule: A node with no supported downstream causal role is a disconnected observation and may be diagnosed as nonfunctional in the graph.
  Takeaway: Diagnose dead-end observations as structural disconnects even when the report explicitly mentions them.
- `edge_deletion_1` [accepted] An incoming edge exists only to support a deleted dead-end observation.
  Interpretation: Once the observation was diagnosed as nonfunctional, its feeder edge no longer represented a needed causal step. The accepted cleanup shows the diagnosis was centered on local connectivity, not on disputing the upstream event.
  Rule: If a node is removed for lacking downstream causal role, remove the incident edge that only serves that disconnected node.
  Takeaway: After diagnosing a node as disconnected, treat its feeder edge as graph cleanup rather than as a separate causal mechanism.

### `batch_5/8/review_feedback_analysis_output.json`

- `edge_addition_0` [accepted] Repair/isolation state was misattached to leak creation instead of pressure buildup.
  Interpretation: This should be diagnosed as a local unsupported-edge problem: the condition affects retention and overpressure after leakage, not the origin of the leak path.
  Rule: The no-venting repair state contributed to trapping and pressure buildup rather than to creation of the internal leak path.
  Takeaway: When a precursor changes what happens after leakage, diagnose it as pressure-buildup influence rather than leak causation.
- `edge_deletion_0` [accepted] Leak event had the wrong immediate cause attached.
  Interpretation: The issue is best framed as unsupported attribution of a mechanism, because the narrative names a different physical cause for the leak path.
  Rule: If the report attributes leakage to a specific physical defect, competing causes should not be attached to that leak event without separate evidence.
  Takeaway: Diagnose wrongly attributed leak causes as unsupported edges, not as alternative parallel causes by default.
- `node_deletion_0` [accepted] Descriptive service condition remained a terminal stub.
  Interpretation: This is a disconnected-node issue, not an unsupported-node issue, because the condition is textually supported but not causally used.
  Rule: Condition nodes that have only an incoming has edge and no downstream role do not function as meaningful causal conditions.
  Takeaway: Treat isolated descriptive conditions as removable background unless the record supports a concrete downstream effect.
- `edge_addition_1` [accepted] Retained equipment condition needed downstream integration into the release sequence.
  Interpretation: The diagnosis is lack of causal integration for an otherwise valid condition node, not invalid node content.
  Rule: Terminal condition nodes need evidence-supported downstream integration or removal.
  Takeaway: When a condition is well supported but isolated, diagnose the problem as missing integration rather than node invalidity.
- `edge_addition_2` [accepted] Release-area condition needed integration into dispersion.
  Interpretation: This indicates the condition was relevant, but only if framed as shaping the released cloud's behavior rather than left as standalone context.
  Rule: Release-setting conditions should participate in the downstream mechanism they influence, such as dispersion.
  Takeaway: Diagnose environmental condition nodes by asking which release or dispersion step they materially modify.
- `edge_deletion_1` [accepted] Support edge disappeared because its condition node was removed.
  Interpretation: This implies the deleted condition was treated as nonessential background, so its attachment edge was cleanup rather than an independent causal issue.
  Rule: When a disconnected background condition lacks a strong downstream role and is deleted, its supporting attachment edge should also be removed.
  Takeaway: If a node is deleted for lacking causal function, diagnose its remaining support edges as cleanup artifacts.

### `batch_5/9/review_feedback_analysis_output.json`

- `node_deletion_0` [accepted] A material-detail node exists only inside an isolated composition subgraph.
  Interpretation: This should be diagnosed as a disconnected-node problem with an extraneous detail, not as a missing causal step in the accident sequence.
  Rule: Nodes that do not participate in a valid supported path to the hazard function as isolated or dangling elements.
  Takeaway: Diagnose isolated descriptive details as removable connectivity artifacts when they lack an independent causal role.
- `edge_addition_0` [accepted] An equipment/entity node is present but not connected to the failure event involving that equipment.
  Interpretation: The issue is best framed as poor integration of an existing node into the established event chain, rather than as absent accident content.
  Rule: An isolated composition subgraph that does not connect to the failure/propagation sequence is a disconnected-node issue.
  Takeaway: When a physical asset is isolated from its own failure event, diagnose the problem as missing integration into the main path.
- `edge_addition_1` [accepted] A damage-evidence event appears as a terminal leaf despite evidence of later causal significance.
  Interpretation: This should be diagnosed as an incomplete downstream linkage for an otherwise supported node, not as an unsupported extraction.
  Rule: A dangling terminal node that does not lead to any further causal step indicates a connectivity defect.
  Takeaway: If observed damage is supported but causally stranded, diagnose missing downstream linkage before considering node removal.
- `edge_deletion_0` [accepted] A leftover composition edge survives only as residue of an isolated side branch.
  Interpretation: The diagnosis should treat such edges as part of the same disconnected-node cleanup, not as meaningful structure that deserves preservation.
  Rule: Keeping an isolated composition edge preserves the disconnected subgraph rather than integrating the information into the main event chain.
  Takeaway: Diagnose residual composition links as cleanup targets when they only maintain disconnected fragments.

### `batch_6/2/review_feedback_analysis_output.json`

- `node_update_0` [accepted] An over-specific ignition-source label was generalized while the ignition-source role was preserved.
  Interpretation: The issue is best framed as uncertainty/schema handling, not as absence of an ignition-source concept.
  Rule: If the report says the exact ignition source was not definitively identified, diagnose the problem as over-specific ignition-source modeling.
  Takeaway: Diagnose named candidate ignition sources as a schema-mismatch problem when the evidence supports ignition occurrence but not source certainty.
- `edge_deletion_0` [accepted] A specific precursor activity was detached from an ignition source that remained uncertain.
  Interpretation: The diagnostic problem is over-commitment of causation to one candidate precursor, not a missing causal step.
  Rule: When multiple ignition sources are possible, do not diagnose one upstream activity as the definitive generator of the ignition source.
  Takeaway: Treat unjustified upstream anchoring of an uncertain ignition source as an over-specific diagnosis rather than as a connectivity gap.
- `edge_deletion_1` [rejected] The ignition-source node stayed connected to the ignition event after being generalized.
  Interpretation: The diagnosis should preserve the ignition function in the causal chain while relaxing only the source specificity.
  Rule: Uncertain identification of the source does not remove the need to represent an ignition-source-to-ignition transition.
  Takeaway: Do not diagnose uncertainty about source identity as permission to disconnect ignition causation from the ignition event.
- `edge_addition_1` [accepted] A previously downstream-disconnected condition was given a supported mechanism role.
  Interpretation: The issue is a participation gap for a condition node, which should be framed as a disconnected-node problem when evidence supports a downstream effect.
  Rule: If a condition node has no downstream causal use, diagnose it as disconnected unless it can be tied to an evidence-supported step.
  Takeaway: When a condition node is only descriptive and not mechanistic, diagnose a disconnected-node issue and seek a supported downstream link.

### `batch_6/4/review_feedback_analysis_output.json`

- `node_addition_0` [accepted] A documented propagation sequence was compressed into a single broader transition.
  Interpretation: This should be diagnosed as a missing intermediate step, not merely as a vague propagation edge.
  Rule: Treat explicitly described local propagation stages as distinct missing-step issues when they are absent from the graph.
  Takeaway: When the narrative separates two propagation stages, diagnose the omission as a missing step.
- `edge_deletion_0` [accepted] A direct causal edge bypassed a newly supported intermediate stage.
  Interpretation: Once the intermediate stage is recognized, the original direct link is best framed as a shortcut structure rather than a complete causal representation.
  Rule: Do not keep a direct edge that skips over an explicitly supported intermediate event in the same causal chain.
  Takeaway: If a direct edge survives only by skipping a documented step, diagnose the problem as structural compression.
- `edge_addition_0` [accepted] A supported condition node had no downstream participation in the causal chain.
  Interpretation: This should be framed as a disconnected-node issue where the condition is valid but under-integrated, not as an unsupported node problem.
  Rule: When a condition is supported by evidence but unused in the mechanism, diagnose it as disconnected and link it only to a supported downstream event.
  Takeaway: A supported condition without causal participation is a connectivity diagnosis, not a support diagnosis.

### `batch_6/7/review_feedback_analysis_output.json`

- `node_addition_0` [accepted] Independent accumulation-management failure was missing from the deposit pathway.
  Interpretation: The accumulation problem should be diagnosed as incomplete because release alone does not explain why deposits remained and reached hazardous levels.
  Rule: The graph omits the explicitly cited housekeeping contributor to hazardous accumulations.
  Takeaway: When the source separately blames poor housekeeping for hazardous deposits, diagnose it as a missing causal step.
- `node_deletion_0` [rejected] An apparent duplicate also served as the explicit ignition-stage representation.
  Interpretation: Duplicate-node diagnoses should be limited when one node preserves the ignition stage in the core explosion narrative.
  Rule: The main causal sequence includes a distinct dust-cloud-to-ignition-to-explosion progression.
  Takeaway: Do not frame every same-fact pair as removable duplication if one node captures a critical hazard stage such as ignition.
- `edge_addition_0` [rejected] The proposed direct link was conditional on removing an intermediate ignition node.
  Interpretation: This is not an independent missing-edge diagnosis; it only becomes relevant under an alternative node structure where the ignition-stage node is removed.
  Rule: A direct replacement edge is only warranted after the duplicate ignition-source node is removed.
  Takeaway: Distinguish true missing edges from contingent replacement edges that only apply if the graph is restructured first.
- `edge_addition_1` [accepted] A condition node was a dead end relative to the accumulation event.
  Interpretation: The disconnected-node issue is best framed as missing participation of material state in the event where deposited material actually accumulates.
  Rule: The material/property subgraph was not integrated into the operative causal chain, and the condition nodes had no outgoing role.
  Takeaway: When a material-condition node has no downstream use, diagnose where that condition becomes operational in the event chain.
- `edge_addition_2` [accepted] A fuel-property node was disconnected from the propagation event it powers.
  Interpretation: The isolation of combustibility should be diagnosed as missing functional linkage to the explosion event, not as a problem with the property label itself.
  Rule: The material/property subgraph was not integrated into the operative causal chain.
  Takeaway: If a fuel property is stranded, diagnose the event where that property is actually consumed as explosion fuel.
- `edge_deletion_0` [accepted] Redundancy was handled at the edge level instead of by deleting a node.
  Interpretation: The duplicate-mechanism concern can be framed as over-connection between near-equivalent local nodes even when both semantic labels are retained.
  Rule: Remove the edge that exists only because of the redundant local duplication.
  Takeaway: If reviewers keep both nodes for semantic clarity, diagnose and prune only the redundant bridging edge.

### `batch_6/8/review_feedback_analysis_output.json`

- `edge_addition_0` [accepted] A key process event ends without any path into ignition or loss.
  Interpretation: This should be diagnosed as a broken main accident chain, not as an isolated ignition event.
  Rule: A key event that has no outgoing connection to the ignition/explosion sequence is a disconnected-node problem.
  Takeaway: If a central pre-loss event does not feed the final outcome, diagnose missing chain continuity before searching for new content.
- `node_update_0` [accepted] An existing node partially captures the missing circumstance but is framed too narrowly.
  Interpretation: This should be diagnosed as a missing-step framing issue that can be resolved by recasting an existing node, not necessarily by adding a new one.
  Rule: The missing causal circumstance can be made explicit by reusing an existing node to represent it.
  Takeaway: When evidence supports a broader causal reading of an existing node, diagnose the gap as weak framing of a missing step rather than missing extraction.
- `edge_addition_1` [accepted] A documented contextual circumstance exists in the graph but does not participate in causation.
  Interpretation: This should be diagnosed as an omitted causal link for an existing circumstance, rather than as absent evidence or absent nodes.
  Rule: A causal circumstance that is already present but not connected leaves the major causal step effectively absent.
  Takeaway: If a supporting circumstance node is present but idle, diagnose the issue as missing integration into the chain.
- `node_update_1` [accepted] The consequence meaning is correct, but the node label violates the schema.
  Interpretation: This should be diagnosed as a schema-mismatch issue, not as a content-selection error.
  Rule: The hazard consequence node should use the required generic label, while the specific consequence stays in the name field.
  Takeaway: Separate schema violations from causal-content problems; a correct concept in the wrong field is a schema diagnosis.

### `batch_6/9/review_feedback_analysis_output.json`

- `node_update_0` [accepted] Initiating event is underspecified.
  Interpretation: The issue is best framed as a missing initiating mechanism within an existing event, not as a separate new branch.
  Rule: The explicit operator misidentification mechanism is missing from the initiation sequence.
  Takeaway: Diagnose omitted belief, indication, or position-reading details as missing-step refinement when they explain why an existing initiating event occurred.
- `node_update_1` [accepted] Event type does not match evidence semantics.
  Interpretation: The problem is a schema-mismatch diagnosis about event classification rather than a missing-causality problem.
  Rule: A sudden loss of containment should be classified with the schema-preferred instantaneous release type.
  Takeaway: When the sequence is intact but the event label conflicts with report wording, frame the issue as schema mismatch.
- `edge_addition_0` [accepted] Condition node has no downstream causal role.
  Interpretation: The issue should be diagnosed as disconnected-node cleanup: the condition is supported, but it remains only descriptive until linked into the release sequence.
  Rule: Supported condition nodes should participate downstream in the causal chain rather than remain attribute-only descriptors.
  Takeaway: Diagnose supported-but-stranded conditions as connectivity problems, not unsupported nodes.
- `edge_addition_1` [accepted] Process condition is stranded as an attribute.
  Interpretation: The temperature issue is best framed as missing downstream participation for a retained condition node, not as a need to delete the node.
  Rule: Several condition nodes lack downstream participation in the causal chain.
  Takeaway: If a condition is evidenced and relevant, diagnose the problem as missing connectivity before considering removal.
- `edge_addition_2` [accepted] Hazard-relevant material property is disconnected from the consequence.
  Interpretation: The combustibility issue is a diagnosis of missing consequence linkage for an otherwise supported condition node.
  Rule: Connect retained hazard conditions to the event or consequence they materially enable when evidence shows participation.
  Takeaway: For fire scenarios, diagnose disconnected combustibility or flammability nodes as missing links to the fire consequence.

## Suggested Core Subset

- Use this smaller set first when prompt budget is tight:
- `batch_5/1/review_feedback_analysis_output.json`
- `batch_5/2/review_feedback_analysis_output.json`
- `batch_5/5/review_feedback_analysis_output.json`
- `batch_5/8/review_feedback_analysis_output.json`
- `batch_5/9/review_feedback_analysis_output.json`
- `batch_6/2/review_feedback_analysis_output.json`
- `batch_6/7/review_feedback_analysis_output.json`
- `batch_6/9/review_feedback_analysis_output.json`

## Excluded By Default

- `batch_4/*` cases
- unresolved decisions
- `untracked_*` manual edits
- stale / legacy review-state mismatches
- implicitly covered suggestions without explicit review decisions
