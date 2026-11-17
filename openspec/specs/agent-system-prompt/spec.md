# agent-system-prompt Specification

## Purpose

The system prompt that teaches the agent how an exposure assessor reasons, so that it decides what to do from the task, the tool descriptions and the tool results, and keeps working when tools are added or changed.

## Requirements

### Requirement: The prompt teaches the assessment, not the tools
The system prompt SHALL describe the process of an exposure assessment (the chain from chemical and sources through transport and receptors to exposure and risk, the quality of evidence, screening conservatism and uncertainty) and how to decide from results. It SHALL NOT name any tool and SHALL NOT prescribe an order of calls. An automated test SHALL fail when the prompt contains the name of a registered tool or a numbered list of steps.

#### Scenario: A tool name appears
- **WHEN** the prompt contains the name of a registered tool
- **THEN** the test fails and names the tool

#### Scenario: A new tool is registered
- **WHEN** a tool is added to the registry
- **THEN** the prompt needs no change for the agent to be able to use it

#### Scenario: A step list is added
- **WHEN** the prompt contains a numbered list of steps
- **THEN** the test fails

### Requirement: Decisions come from tool descriptions and results
Every tool description SHALL state what the tool is for and when it applies (including any condition on using it, such as only after a better source returned nothing), what each output means, what a null value, a `source` or a `warnings` entry implies, and what situation calls for a different tool. The prompt SHALL tell the agent to rely on these descriptions and to read each result critically before using it.

#### Scenario: A fallback tool
- **WHEN** the description of a tool that is a fallback is read
- **THEN** it says under what condition to use it and what its output does not represent

#### Scenario: Quality signals
- **WHEN** the description of a tool that can return a default is read
- **THEN** it says how a default is labelled and that the agent must report it

### Requirement: Evidence quality, alternatives and honesty
The prompt SHALL state that facility-specific evidence is preferred over process-typical and that over generic defaults, that a more generic source is used only when a better one is unavailable and is then disclosed, that several credible alternatives are each evaluated and reported as a range, that worst-case and typical results are both reported, that numbers, names and identifiers are never invented, estimated or converted by the agent (a chemical is called by the name a tool result gives, else by its CAS number alone), that a branch with no defensible answer is stopped with the reason, and that the user is asked when something essential and not obtainable by a tool is missing.

#### Scenario: Default in the data
- **WHEN** the prompt is read
- **THEN** it requires the final answer to say which inputs were defaults or generic and why

#### Scenario: Alternatives
- **WHEN** the prompt is read
- **THEN** it says to evaluate every credible alternative and report the range

#### Scenario: Chemical without a name
- **WHEN** the properties result carries no name for the chemical
- **THEN** the prompt requires the report to refer to it by its CAS number and never to supply a name

### Requirement: Output format and structure
The prompt SHALL ask for a short summary, per-facility results with units, ranges (for a facility with several stacks the range over its stacks, given for both the worst case and the typical case, as two separate things) and the origin of each input named as the results name it (the source text of the weather, the residents, the stacks' tier and the toxicity benchmarks), plain-language comment on results beyond a health benchmark, and a Limitations section listing the method's limits, defaults or generic inputs and data gaps, and SHALL be structured with the `role`, `context`, `instructions` and `output_format` XML tags in that order. When the assessment cannot start because something only the user can give is missing, the prompt SHALL ask for a reply containing just that request and why it is needed, not the report format.

#### Scenario: Structure
- **WHEN** the prompt is loaded
- **THEN** it contains the four tags in that order

#### Scenario: Sources as the results give them
- **WHEN** the prompt is read
- **THEN** it asks that each input's source be named with the text the result gives, not paraphrased ("actual local weather" is not a source)

#### Scenario: Nothing to report yet
- **WHEN** the assessment cannot start because the user has not given the chemical's CAS number
- **THEN** the reply is the request alone, with no summary, results table or Limitations section

### Requirement: How an assessor treats a missing chemical
The prompt SHALL explain, as assessment reasoning and without naming a tool, the three ways a
chemical can be missing from the evidence and how each is treated: a chemical named without
a CAS registry number is not identified, so the user is asked for the number and none is
supplied; an identified chemical that is not on the TRI list or has no inhalation benchmark
may be estimated from a well-characterized chemical of similar structure (read-across), with
the similarity and its defensibility stated, the borrowed value never presented as measured,
and the gap reported when no defensible analogue exists; and an identified chemical absent
from the release inventory shows no reported releases, not that nobody emits it.

#### Scenario: Name without a CAS number
- **WHEN** the user asks for an assessment of a chemical by name only
- **THEN** the agent's reply is a request for the CAS number, it calls no tool and it writes no CAS number

#### Scenario: Borrowed value
- **WHEN** the prompt is read
- **THEN** it says a value taken from a structural analogue is an estimate, never a measured value for the chemical

### Requirement: The CAS rule stands on its own
The prompt SHALL state the rule that a chemical is identified only by a CAS number the user
has written as its own unconditional instruction, separate from the general instruction to
ask for anything essential that no tool can supply, and SHALL forbid writing a CAS number as
a suggestion, an example or something to confirm. The wording SHALL be the one measured
clean against the evaluation model, and an automated test SHALL pin it, because paraphrases
of the same rule were measured to change the model's compliance.

#### Scenario: Rule pinned
- **WHEN** the CAS rule's wording is changed
- **THEN** the prompt test fails until the new wording is measured and pinned

### Requirement: Every facility is covered
The prompt SHALL tell the agent to cover every facility of the chemical, not only the largest emitters, leaving a facility out only when a conservative screen shows it cannot reach a level of concern, and to report how many were screened out and against which thresholds, every facility assessed and every one kept at the worst case only (the person sees each one on the map); to narrow the scope only when the user asks for particular facilities or a place and to say so, and to request the inputs of several facilities together in one turn. The prompt SHALL NOT tell the agent to keep the scope manageable by choosing a subset itself.

#### Scenario: Prompt read
- **WHEN** the prompt is read
- **THEN** it says to cover every facility, screening rather than ranking them out, and names no tool

#### Scenario: User narrows the scope
- **WHEN** the user asks about one facility or one place
- **THEN** the prompt allows assessing only those and asks that the narrowing be stated

### Requirement: The reply does the work
The prompt SHALL tell the agent never to end a reply by announcing what it will do next, never to ask whether to proceed, and that a reply ends only when the assessment is written or something only the user can give is missing.

#### Scenario: Prompt read
- **WHEN** the prompt is read
- **THEN** it says to do the work rather than announce it and when a reply may end

### Requirement: Asking the user for a missing value
The prompt SHALL explain, as assessment reasoning and without naming a tool or a call order,
when a value the analysis needs is missing and the missing value changes the result: the
assessor stops before concluding, asks the user once, in one message, for every such value,
says what each one is needed for, and offers the two answers the user may give (proceed without
it, or enter it with its unit). The prompt SHALL NOT tell the assessor to guess, estimate or
borrow a value that is missing from the evidence as a substitute for asking, except where the
read-across rule already allows a labelled estimate.

#### Scenario: Missing value that changes the result
- **WHEN** the prompt is read
- **THEN** it says to ask the user once, in one message, for every missing value that changes the result, and to name what each is needed for

#### Scenario: Missing value that does not change the result
- **WHEN** the prompt is read
- **THEN** it says a missing value that the requested result does not use is not raised with the user

#### Scenario: User's answers
- **WHEN** the prompt is read
- **THEN** it says a value the user entered is used as the user's own figure and is reported as user-provided, and a value the user declined is reported as absent, not estimated

### Requirement: Missing-value rule does not reopen the CAS rule
The missing-value request SHALL NOT ask for, or accept, a CAS registry number that the user did
not give; the CAS rule of the prompt stands unchanged.

#### Scenario: Missing CAS number is not a property
- **WHEN** the chemical's CAS number is missing
- **THEN** the reply asks for the CAS number as before and does not open a missing-value request for it

### Requirement: A category match is disclosed and reasoned about
The prompt SHALL explain, as assessment reasoning and without naming a tool, that TRI reports
some chemicals only as members of a category rather than under their own CAS number. It SHALL
say that when a chemical is found in a category, the assessor tells the user plainly that the
chemical was matched through that category, names the category, and explains that the
reported releases cover every member of the category together, so they are an upper bound on
what that one chemical contributes and not a measured release of it. It SHALL say that a
category match is tried before an analogue is sought, and that an analogue is sought only
when the chemical is in no category; and that the chemical's own toxicity benchmark is still
required and is not taken from the category.

#### Scenario: Category match
- **WHEN** the prompt is read
- **THEN** it says the user is told when a category stood in for a chemical, and that category releases cover all members

#### Scenario: Order of fallbacks
- **WHEN** the prompt is read
- **THEN** it says a category is checked before an analogue is sought

#### Scenario: Prompt names no tool
- **WHEN** the prompt is read
- **THEN** it names no tool and no call order

### Requirement: Neighbours and workers are reasoned about together
The prompt SHALL explain, as assessment reasoning and without naming a tool or a call order, that people near a plant and people who work in it are exposed differently (a stack release reaches the neighbours through outdoor air; workers breathe the vapour their own tasks generate), that the community and the worker results are reported side by side with which one drives the concern at a facility, and that both are read in the same screening bands (high, moderate, low) which are priorities for further work and not findings. It SHALL explain that a worker figure rests on the best evidence available, measured samples of the industry before an activity model with generic ventilation, and that the answer says which; that the worker figures are a screening, not a compliance finding; that the site's fugitive release is not a measure of worker exposure; and that a worker figure that could not be computed is reported as not computed with its reason.

#### Scenario: Both audiences
- **WHEN** the prompt is read
- **THEN** it says to report the community and the worker result side by side and to say which drives the concern

#### Scenario: Bands are priorities
- **WHEN** the prompt is read
- **THEN** it says the bands are screening priorities and never that a limit is exceeded or an exposure acceptable

#### Scenario: Evidence named
- **WHEN** the prompt is read
- **THEN** it says to state whether a worker figure rests on measured samples or on a model

#### Scenario: Not a compliance finding
- **WHEN** the prompt is read
- **THEN** it says the worker figures are a screening, not a compliance finding

#### Scenario: Not computed
- **WHEN** the prompt is read
- **THEN** it says a worker figure that could not be computed is reported as not computed, with the reason
