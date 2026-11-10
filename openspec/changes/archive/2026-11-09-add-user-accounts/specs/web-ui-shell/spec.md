## ADDED Requirements

### Requirement: Account screens before the workspace
When the server reports no signed-in user, the interface SHALL show the account screens
instead of the workspace: sign in, sign up, check your email, verify email, forgot password and
reset password, each reachable from the others by links. They SHALL use the design system's
tokens and existing controls, label every input, show a progress state while a request runs,
show the server's user-safe message on failure, and never say whether an email has an account
beyond what the server answered. A token from an emailed link SHALL be read from the URL
fragment, sent in a request body, and removed from the address bar. No password or token SHALL
be written to browser storage. Any 401 from the API during use SHALL return the interface to
sign in without a reload and without keeping the previous user's workspace on screen.

#### Scenario: First visit
- **WHEN** an anonymous person opens the app
- **THEN** the sign-in screen is shown with links to sign up and to recover a password, and the workspace is not rendered

#### Scenario: Reset link
- **WHEN** a person opens a reset link
- **THEN** the reset screen is shown, the token is no longer in the address bar, and submitting a new password sends the token in the request body

#### Scenario: Session expires mid-use
- **WHEN** an API call returns 401 while the workspace is open
- **THEN** the sign-in screen replaces the workspace and no previous thread data remains visible

#### Scenario: No credentials in storage
- **WHEN** a user has signed up, signed in and reset a password
- **THEN** `localStorage` and `sessionStorage` contain no password and no token

## MODIFIED Requirements

### Requirement: Navigation rail with workspace and monitoring views
The leftmost region SHALL be a navigation rail with two states: collapsed (an icon rail of about
60 px) and expanded (resizable within its configured limits, 200–320 px by default). A toggle
next to the brand mark at the top SHALL switch between them. In order, the rail SHALL show: at
the top, the brand mark and the toggle. Below them, the entries "Workspace", "Clear workspace",
"Generate report" and, for administrators only, "Monitoring". At the bottom, an Account entry
(showing the signed-in email, with "Sign out" and account management) and a Settings entry. For
a user without the `admin` role the "Monitoring" entry SHALL NOT be rendered. The rail SHALL NOT
list runs and SHALL NOT offer a "New analysis" action. The entry for the view on screen
("Workspace" or "Monitoring") SHALL be marked as the current page, in words for assistive
technology and not by colour alone. Activating "Workspace" SHALL show the workspace, leave
fullscreen and close the Settings drawer and any open dialog. Activating "Monitoring" SHALL
show the Monitoring view and close the Settings drawer and any open dialog. The workspace
panels and the chat stay mounted and keep their state. In the collapsed state every entry SHALL
show only its icon with an accessible name and a tooltip; a disabled entry's tooltip SHALL say
why it is disabled. Signing out SHALL end the session on the server and show the sign-in
screen.

#### Scenario: Collapse and expand
- **WHEN** the user activates the toggle on an expanded rail
- **THEN** the rail collapses to icons, the analysis area widens, and the map redraws at its new size

#### Scenario: Collapsed entries remain usable
- **WHEN** the rail is collapsed and the user focuses the Settings icon
- **THEN** it announces "Settings" and opens the settings drawer when activated

#### Scenario: Entries in order
- **WHEN** the rail is expanded for an administrator
- **THEN** it shows Workspace, Clear workspace, Generate report and Monitoring in that order, then Account and Settings at the bottom, and no run list

#### Scenario: Entries for a regular user
- **WHEN** the rail is expanded for a user without the `admin` role
- **THEN** it shows Workspace, Clear workspace and Generate report, then Account and Settings, and no Monitoring entry

#### Scenario: Return to the workspace
- **WHEN** the map is fullscreen and the Settings drawer is open, and the user activates "Workspace"
- **THEN** the drawer closes and the overview, map and chat are all visible again

#### Scenario: Open Monitoring
- **WHEN** an administrator activates "Monitoring"
- **THEN** the Monitoring view is shown, "Monitoring" is announced as the current page, and returning to "Workspace" shows the panels and chat as they were left

#### Scenario: Sign out
- **WHEN** the user chooses "Sign out" from the Account entry
- **THEN** the server session is deleted and the sign-in screen replaces the workspace
