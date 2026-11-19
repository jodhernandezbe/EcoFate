## ADDED Requirements

### Requirement: README scan layer for a quick reader
The README SHALL open with a section a reader can take in within about two minutes that
contains: a one-sentence description, the continuous-integration status badge, a live URL or
a recorded demo, a screenshot of a user prompt with the agent's answer, the problem the
project solves stated for a non-specialist, what the system does, a highlights table naming
the tools, knowledge base, tests, evaluation, monitoring, containerisation, CI/CD and
deployment, the headline evaluation figures with their source, a screenshot of the
monitoring dashboard, and the command that starts the whole system.

#### Scenario: Evidence on the first screens
- **WHEN** a reader opens the README on GitHub
- **THEN** the problem statement, a prompt-and-answer screenshot, the evaluation figures and the monitoring screenshot appear before the first reviewer section

### Requirement: One reviewer section per capstone criterion
The README SHALL contain one section for each capstone criterion, in the rubric's order and
under its name (Problem description, Knowledge base and retrieval, Agents and LLM, Code
organization, Testing, Evaluation, Monitoring, Reproducibility, Best coding practices,
Deployment), each stating what was built, linking to the code that implements it, giving a
command or link to check it, and linking to the detailed document in `docs/`. The Testing
section SHALL say how to run the unit tests and the judge tests separately. The Evaluation
section SHALL describe the hand-crafted ground-truth dataset, how it was labelled, the LLM
judge, and the tuning iterations with their figures. The Monitoring section SHALL say what is
logged, how logs are processed, and how to open the dashboard. The Reproducibility section
SHALL cover prerequisites, which keys are needed and who supplies each, starting the system,
and where the data comes from.

#### Scenario: Reviewer finds testing commands
- **WHEN** a reviewer reads the Testing section
- **THEN** it gives the command for the unit tests and the command for the judge tests, and says which ones cost tokens

#### Scenario: Reviewer finds the dashboard
- **WHEN** a reviewer reads the Monitoring section
- **THEN** it says who can open the dashboard, how to reach it locally and in production, and shows a screenshot

### Requirement: Honest self-evaluation
The README SHALL end with a self-evaluation table listing every capstone criterion and bonus
item with its maximum points, the points claimed and links to the evidence. An item that is
not met SHALL be listed with zero points. Figures quoted anywhere in the documentation SHALL
name the checked-in file they come from.

#### Scenario: Unmet item
- **WHEN** a bonus item has not been built
- **THEN** the table lists it with zero points claimed

#### Scenario: Figures traceable
- **WHEN** the documentation quotes a judge accuracy
- **THEN** the report file it was computed from is named next to it

### Requirement: Documentation lives next to what it describes
Each package folder with a role a reader needs to understand (`agent/`, `tools/`, `models/`,
`prompts/`, `config/`, `storage/`, `api/`, `worker/`, `frontend/`, `evals/`, `deploy/`) SHALL have
a `README.md` for people (its `CLAUDE.md` stays the rules for coding agents). It SHALL say what
the folder is for, how it fits the system, its main modules, how to run or test it, and how to
extend it, taking over the matching part of today's root README. Cross-cutting topics SHALL live
in `docs/`, one file per concern: architecture, security, monitoring and deployment, with
`docs/README.md` listing every file in `docs/`. The root `README.md` SHALL keep a short summary
per topic and link to its folder README or `docs/` file; no topic SHALL be described in full in
two places.

#### Scenario: Index complete
- **WHEN** a Markdown file is added to `docs/`
- **THEN** the docs index lists it

#### Scenario: Topic moved, not copied
- **WHEN** the tool reference moves to `tools/README.md`
- **THEN** the root README keeps at most a short summary and a link, not the reference itself

### Requirement: Navigation indices
The root `README.md` SHALL have a documentation index linking to every folder README and every
`docs/` file, grouped by purpose (use it, understand it, extend it, operate it). Every folder
README and `docs/` file SHALL start with a navigation line linking back to the root index (and
to its parent or related documents) and SHALL have a table of contents when it has more than
three sections.

#### Scenario: Back to the index
- **WHEN** a reader opens `worker/README.md`
- **THEN** its first line links to the root README's documentation index

#### Scenario: Every README indexed
- **WHEN** a folder README is added
- **THEN** the root documentation index links to it

### Requirement: draw.io system design diagrams
The documentation SHALL include draw.io diagrams stored as editable `.drawio.svg` files (the
diagram embedded in the SVG, so it opens in draw.io and renders on GitHub), under
`docs/diagrams/`, each referenced as an image with alt text from the document it explains.
High-level diagrams (in `docs/architecture.md`) SHALL cover the system context (users,
browser, Cloudflare, the VM, OpenAI and the public data services), the runtime containers and
the package layers with their allowed dependency directions. Low-level diagrams SHALL cover,
in the README of the folder they explain, the agent graph (`agent/`), the path of one turn from
browser to worker and back (`worker/` or `api/`), the batch assessment's tiers and the tools it
composes (`tools/`), the evaluation pipeline (`evals/`) and the release and rollback flow
(`deploy/`). Every element a diagram names SHALL exist in the code.

#### Scenario: Editable and rendered
- **WHEN** a `.drawio.svg` file is opened in draw.io
- **THEN** it opens as an editable diagram, and the same file renders as an image on GitHub

#### Scenario: Diagram matches the code
- **WHEN** the agent graph diagram names a node
- **THEN** that node is added in `agent/graph.py`

### Requirement: Screenshots from the running application
`docs/images/` SHALL contain screenshots captured from the running application showing at
least the prompt and answer with the dashboard, the monitoring dashboard, and the evaluation
results, each referenced with alt text, each small enough to pass the repository's
large-file check, and none showing an API key, session token or personal data. A listing
SHALL say which screen each image shows and how to reproduce it.

#### Scenario: No credentials in images
- **WHEN** the settings screen is captured
- **THEN** the image shows only whether the OpenAI key is set, not any part of it

### Requirement: Documentation links checked by tests
The default test run SHALL fail when a relative link or image in any tracked `README.md` or any
Markdown file in `docs/` points to a missing file or to a heading anchor that does not exist. External
links SHALL NOT be fetched by this check.

#### Scenario: Broken file link
- **WHEN** the README links to a docs file that was renamed
- **THEN** the link test fails naming the README line's target

#### Scenario: Broken anchor
- **WHEN** a link targets `evals/README.md#judge-iterations` and no such heading exists
- **THEN** the link test fails

#### Scenario: External links ignored
- **WHEN** a document links to an `https://` URL
- **THEN** the link test does not contact the network
