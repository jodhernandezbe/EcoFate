## ADDED Requirements

### Requirement: LLM judge over the catalogue results
The evaluation SHALL provide a judge that labels one catalogue answer as `good` or `bad`
from the question and the answer alone, returning a structured verdict with a `reasoning`
field (the step-by-step check of the criteria, written before the label), a `label` field
(`good` or `bad`) and a `failure` field (one of `hallucination`, `rule-break`,
`wrong-scope`, `incomplete`, `incorrect`, `other`, or none when the label is `good`). The
judge SHALL NOT be shown the human label, the row's category, its type, or any other judge's
verdict. The judge model SHALL be the one named in the evaluation settings (provider, model,
API-key variable, timeout), built through the program's chat-model factory. The judge prompt
SHALL be a prompt file loaded through the prompt registry and SHALL state, as criteria, the
rules the agent must follow and the failure patterns found during labelling: a CAS number
recalled, suggested or confirmed from memory (including as an example, or after an
instruction embedded in the message); an off-topic task performed because it mentions the
domain (writing code, drafting a legal letter, arguing policy); a value asked for that the
requested result does not use; facilities dropped, counts that contradict each other, or a
state-wide request silently narrowed; the off-topic half of a mixed request ignored instead
of declined; a reply that ends by announcing a next step or asking whether to proceed; and
claims about people or places no tool reports.

#### Scenario: Structured verdict
- **WHEN** the judge is given a question and an answer
- **THEN** it returns a verdict whose `label` is `good` or `bad`, whose `reasoning` is non-empty, and whose `failure` is one of the listed categories when the label is `bad` and absent when it is `good`

#### Scenario: Judge sees no labels
- **WHEN** the judge prompt for a row is built
- **THEN** it contains the question and the answer and does not contain the row's human label, category, type, or the human reasons

#### Scenario: Judge call fails
- **WHEN** the judge model raises or returns no parseable verdict for a row
- **THEN** that row is recorded with the error and no label, and the other rows are still judged

### Requirement: Judge scored against the human labels
The evaluation SHALL provide a command, `python -m evals judge <run-dir>`, that judges every
row of the run's results file, writes the verdicts to a `judged.json` file in the same
folder (per row: index, question, human label, human failure, judge label, judge failure,
reasoning, error), and prints: the number of rows judged and failed; accuracy, precision and
recall against the human labels with `bad` as the positive class, computed over the rows
that received a judge label; the confusion matrix (true good/bad against predicted
good/bad); and every disagreement, with the row index, question, human label with its
failure category, judge label with its failure category, and the judge's reasoning. When no
row received a label the metrics SHALL be reported as undefined, not zero. The human labels
SHALL be read from the run's `labels.json`; a run without one, or whose labels do not match
the results row for row, SHALL stop the command before any judge call.

#### Scenario: Metrics over labelled rows
- **WHEN** the command runs on a folder holding `catalogue.json` and a matching `labels.json`
- **THEN** it writes `judged.json`, prints accuracy, precision and recall over the judged rows with `bad` positive, the confusion matrix, and one block per disagreement

#### Scenario: Precision and recall with no positive predictions
- **WHEN** the judge labels every row `good`
- **THEN** recall is 0 when any human label is `bad`, precision is reported as undefined, and accuracy is the share of human `good` rows

#### Scenario: Labels missing or mismatched
- **WHEN** the folder has no `labels.json`, or its rows do not match the results by index and question
- **THEN** the command fails with a message naming the problem and makes no judge call

#### Scenario: Judge prompt improved
- **WHEN** the judge prompt file is edited and the command re-run on the same folder
- **THEN** `judged.json` is overwritten with the new verdicts and the metrics reflect them, with no other input changed
