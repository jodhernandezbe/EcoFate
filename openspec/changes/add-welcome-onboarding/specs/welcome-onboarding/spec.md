## Purpose

A short first-visit welcome that tells a new user what EcoFate does and the three things to do
first (add the OpenAI key, ask a question, read the results), then gets out of the way.

## ADDED Requirements

### Requirement: Welcome sheet on the first visit
When a signed-in user opens the workspace and has not dismissed the welcome in this browser, the
workspace SHALL show a welcome sheet over it (the `BottomDrawer` primitive at its content height,
over a scrim, focus inside, Escape and its close control dismiss it). The workspace, chat and map
SHALL stay mounted underneath. The sheet SHALL have a title ("Welcome to EcoFate"), one sentence
saying the app produces screening-level chemical exposure and risk assessments from public
inventories, and three numbered steps in order: "Add your OpenAI key", "Ask a question", "Read
the results". It SHALL end with a primary "Get started" action that dismisses it.

#### Scenario: First visit
- **WHEN** a user signs in for the first time in this browser
- **THEN** the welcome sheet is shown with the three steps in order

#### Scenario: Dismissed
- **WHEN** the user chooses "Get started", the close control or Escape
- **THEN** the sheet closes, focus returns to the workspace, and it is not shown on the next visit in this browser

#### Scenario: Storage unavailable
- **WHEN** browser storage cannot be read or written
- **THEN** the sheet still works and is simply shown again on the next visit; no error is shown

#### Scenario: Per user
- **WHEN** another user signs in on the same browser
- **THEN** that user sees the welcome on their own first visit

### Requirement: Step 1 shows the key state and leads to Settings
The first step SHALL say that the assistant runs on the user's own OpenAI key, billed to their
OpenAI account, and stored encrypted. It SHALL show the state in words: "Key stored" (with the
`ok` tint) or "No key yet", and an "Open Settings" action that closes the welcome and opens the
Settings drawer. The welcome SHALL never contain a key input or any part of a key.

#### Scenario: No key
- **WHEN** the user has no key stored
- **THEN** step 1 reads "No key yet" and "Open Settings" opens the Settings drawer

#### Scenario: Key stored
- **WHEN** the user's key is stored
- **THEN** step 1 reads "Key stored"

### Requirement: Step 2 offers the example questions
The second step SHALL show the configured example prompts (the client configuration's
`suggestions`) as chips. Choosing one SHALL close the welcome and send that prompt as the user's
message, exactly as the chat's suggestion chips do. While no key is stored or a reply is running
the chips SHALL be disabled and say why (tooltip and `aria-description`). Without configured
suggestions the step SHALL say to type a question in the chat.

#### Scenario: Pick an example
- **WHEN** a user with a stored key chooses an example
- **THEN** the welcome closes and that prompt is sent in the chat

#### Scenario: No key yet
- **WHEN** no key is stored
- **THEN** the examples are disabled and say a key is needed first

### Requirement: Step 3 explains where the results appear
The third step SHALL say in one line each: the Overview summarises the screening results and
their bands, the Map shows the facilities and the people around them, the Chat explains each step
and asks when a value is missing, and the rail's report downloads the assessment. It SHALL state
that results are screening level, not a regulatory determination.

#### Scenario: Results explained
- **WHEN** the welcome is shown
- **THEN** step 3 names the Overview, the Map, the Chat and the report, and says results are screening level

### Requirement: Reopen from the rail
The navigation rail SHALL have a "Welcome" item (Lucide icon, labelled when collapsed) that opens
the welcome sheet at any time, whatever was dismissed before.

#### Scenario: Reopen
- **WHEN** a user who dismissed the welcome chooses Welcome in the rail
- **THEN** the welcome sheet opens with the current key state
