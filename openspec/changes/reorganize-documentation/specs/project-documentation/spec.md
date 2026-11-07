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

### Requirement: Detailed documentation in docs/
Detailed material SHALL live in `docs/`, one file per concern: architecture, tools,
evaluation, monitoring, deployment and security, plus an index file listing every document
in `docs/`. The README SHALL summarise each topic briefly and link to its file.

#### Scenario: Index complete
- **WHEN** a Markdown file is added to `docs/`
- **THEN** the docs index lists it

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
The default test run SHALL fail when a relative link or image in `README.md` or any Markdown
file in `docs/` points to a missing file or to a heading anchor that does not exist. External
links SHALL NOT be fetched by this check.

#### Scenario: Broken file link
- **WHEN** the README links to a docs file that was renamed
- **THEN** the link test fails naming the README line's target

#### Scenario: Broken anchor
- **WHEN** a link targets `docs/evaluation.md#judge-iterations` and no such heading exists
- **THEN** the link test fails

#### Scenario: External links ignored
- **WHEN** a document links to an `https://` URL
- **THEN** the link test does not contact the network
