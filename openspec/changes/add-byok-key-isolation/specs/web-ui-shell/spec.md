## MODIFIED Requirements

### Requirement: Settings drawer for the API keys
Choosing Settings in the navigation rail SHALL open a bottom drawer over the workspace. The drawer
SHALL keep the workspace and the chat mounted, can be resized and maximized, closes with
Escape or its close control, and keeps focus inside it while open, returning focus on close. The
drawer SHALL hold collapsible sections: an Assistant section for the user's OpenAI key and a
read-only Data services section. The OpenAI key SHALL have a label with an info tooltip stating
that it runs the assistant and is billed to the user's own OpenAI account, a password-type input
that can be cleared, a status reading "Key stored encrypted for your account" or "No key
configured" (never any part of the key), and "Clear key", "Reset" and "Save" actions. Save SHALL
be disabled while the input is blank or a request is running. The outcome of a save or clear
SHALL be shown in an inline success or error message in the section. Inputs SHALL be cleared
after saving and by Reset, and no key SHALL be written to browser storage, the URL or logs. The
Data services section SHALL list the Census service (counts the people around a facility) and
the CompTox service (looks up chemical properties and toxicity), each with "Provided by this
installation" or "Not available on this installation" and, when unavailable, which lookups will
be missing; it SHALL have no input for any key. When the OpenAI key is not configured, the chat
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

#### Scenario: Data services are read-only
- **WHEN** the drawer is open
- **THEN** the Data services section shows each service's availability and contains no input or save action

#### Scenario: Optional keys missing
- **WHEN** the installation has no Census key
- **THEN** the Census entry says it is not available on this installation and which lookups will be missing

#### Scenario: No browser storage
- **WHEN** a key has been saved
- **THEN** `localStorage` and `sessionStorage` contain no key material
