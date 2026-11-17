## ADDED Requirements

### Requirement: The workspace carries the run's worst-case chain
The workspace state SHALL carry `worst_case_chain`, the run-wide worst-case graph, in the same graph shape as a facility's exposure graph (lanes, nodes, edges). It SHALL be rebuilt from the facilities and the scenario drivers every time either changes, and it SHALL be sent in `workspace_update` and described in the generated schema and types. When no facility has been assessed, it SHALL be an empty graph, never absent. The per-facility exposure graphs SHALL be unchanged.

#### Scenario: Rebuilt on update
- **WHEN** a later tool result changes which facility drives the hazard quotient
- **THEN** the next `workspace_update` carries a chain whose outdoor-air lane holds the new driver's values

#### Scenario: Before any assessment
- **WHEN** the workspace has facilities but no scenario drivers
- **THEN** `worst_case_chain` has no lanes, nodes or edges

#### Scenario: Contract
- **WHEN** the schema is exported
- **THEN** the TypeScript types include `worst_case_chain` and the contract check passes
