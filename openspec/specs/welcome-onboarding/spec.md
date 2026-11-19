# welcome-onboarding Specification

## Purpose

A short first-visit welcome that tells a new user what EcoFate does and the three things to know
first (bring the OpenAI key, ask in plain words, read the results), then gets out of the way.

## Requirements


### Requirement: Welcome sheet on the first visit
When a signed-in user opens the workspace and has not dismissed the welcome in this browser, the
workspace SHALL show a welcome sheet in the manner of a "What's New" screen: a centered card over a
blurred scrim with the EcoFate mark, a large title ("Welcome to EcoFate"), one line saying it gives
screening-level chemical exposure and risk from public inventories, three features (each an accent
Lucide icon, a bold title and one or two sentences) in this order: "Bring your OpenAI key", "Ask
in plain words", "See the risk at a glance", and one full-width primary "Continue" action. Focus
SHALL start on Continue and stay inside the card; Continue, Escape or the scrim dismiss it. The
workspace, chat and map SHALL stay mounted underneath.

#### Scenario: First visit
- **WHEN** a user signs in for the first time in this browser
- **THEN** the welcome sheet is shown with the three features in order and focus on Continue

#### Scenario: Dismissed
- **WHEN** the user chooses Continue, presses Escape or clicks the scrim
- **THEN** the sheet closes, focus returns to the workspace, and it is not shown on the next visit in this browser

#### Scenario: Storage unavailable
- **WHEN** browser storage cannot be read or written
- **THEN** the sheet still works and is simply shown again on the next visit; no error is shown

#### Scenario: Per user
- **WHEN** another user signs in on the same browser
- **THEN** that user sees the welcome on their own first visit

### Requirement: The key feature shows the key state and leads to Settings
The first feature SHALL say that the assistant runs on the user's own OpenAI key, billed to their
OpenAI account and stored encrypted, followed by the state in words: "Key stored." (in the `ok`
colour) or "No key yet.". While no key is stored, an "Add your key in Settings" action under
Continue SHALL close the welcome and open the Settings drawer. The welcome SHALL never contain a
key input or any part of a key.

#### Scenario: No key
- **WHEN** the user has no key stored
- **THEN** the feature reads "No key yet." and "Add your key in Settings" opens the Settings drawer

#### Scenario: Key stored
- **WHEN** the user's key is stored
- **THEN** the feature reads "Key stored." and no Settings action is shown

### Requirement: The ask feature offers one example
The second feature SHALL offer the first configured example prompt (the client configuration's
`suggestions`) as a one-tap "Try “…” →" action. Choosing it SHALL close the welcome and send that
prompt as the user's message. While no key is stored or a reply is running it SHALL be disabled
and say why (tooltip and `aria-description`). Without configured suggestions no example is shown.

#### Scenario: Pick the example
- **WHEN** a user with a stored key chooses the example
- **THEN** the welcome closes and that prompt is sent in the chat

#### Scenario: No key yet
- **WHEN** no key is stored
- **THEN** the example is disabled and says a key is needed first

### Requirement: The results feature explains where the results appear
The third feature SHALL name the overview, the map and the downloadable report, and state that
results are screening level, not a regulatory determination.

#### Scenario: Results explained
- **WHEN** the welcome is shown
- **THEN** it names the overview, the map and the report, and says results are screening level

### Requirement: Reopen from the rail
The navigation rail SHALL have a "Welcome" item (Lucide icon, labelled when collapsed) that opens
the welcome sheet at any time, whatever was dismissed before.

#### Scenario: Reopen
- **WHEN** a user who dismissed the welcome chooses Welcome in the rail
- **THEN** the welcome sheet opens with the current key state
