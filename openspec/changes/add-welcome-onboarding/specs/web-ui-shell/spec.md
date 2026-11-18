## REMOVED Requirements

### Requirement: Settings drawer for the API keys
**Reason**: Its Data services section listed operator-only keys users cannot act on.
**Migration**: Replaced by "Settings drawer for the OpenAI key" below, identical except that section is gone.

## ADDED Requirements

### Requirement: Settings drawer for the OpenAI key
Choosing Settings in the navigation rail SHALL open a bottom drawer over the workspace. The drawer
SHALL keep the workspace and the chat mounted, can be resized and maximized, closes with
Escape or its close control, and keeps focus inside it while open, returning focus on close. The
drawer SHALL hold the Assistant section for the user's OpenAI key and nothing about the
operator's data services (Census, CompTox), which users never configure. The OpenAI key SHALL have a label with an info tooltip stating
that it runs the assistant and is billed to the user's own OpenAI account, a password-type input
that can be cleared, a status reading "Key stored encrypted for your account" or "No key
configured" (never any part of the key), and "Clear key", "Reset" and "Save" actions. Save SHALL
be disabled while the input is blank or a request is running. The outcome of a save or clear
SHALL be shown in an inline success or error message in the section. Inputs SHALL be cleared
after saving and by Reset, and no key SHALL be written to browser storage, the URL or logs. When the OpenAI key is not configured, the chat
input SHALL point the user to Settings and the Assistant section SHALL open expanded.

#### Scenario: Open from the rail
- **WHEN** the user activates Settings in the navigation rail
- **THEN** the drawer opens over the workspace and the map and chat stay as they were

#### Scenario: Save key
- **WHEN** the user enters their OpenAI key and saves
- **THEN** the section shows a success message and the stored state, showing no part of the key, and its input is empty

#### Scenario: Save fails
- **WHEN** the server rejects a key
- **THEN** the section shows an error message and the stored state is unchanged

#### Scenario: No data services section
- **WHEN** the drawer is open
- **THEN** it shows no Census or CompTox entry and no Data services section

#### Scenario: No browser storage
- **WHEN** a key has been saved
- **THEN** `localStorage` and `sessionStorage` contain no key material
