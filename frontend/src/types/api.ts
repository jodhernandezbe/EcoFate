/* Generated from api/schemas/ by npm run gen:types. Do not edit. */

/**
 * Any one event of the stream (used to export the event union).
 *
 * This interface was referenced by `ApiContract`'s JSON-Schema
 * via the `definition` "StreamEventSchema".
 */
export type StreamEventSchema =
  | TurnStarted
  | TurnStatus
  | ScopeDecision
  | GuardrailPivotResponse
  | ToolStatus
  | WorkspaceUpdate
  | Token
  | AssistantMessage
  | TurnInterrupted
  | Usage
  | ErrorEvent
  | ConfirmationRequested
  | TurnFinished;

export interface ApiContract {
  AcceptedResponse: AcceptedResponse;
  ChangePasswordRequest: ChangePasswordRequest;
  ChatRequest: ChatRequest;
  ClientConfig: ClientConfig;
  DeleteAccountRequest: DeleteAccountRequest;
  EmailRequest: EmailRequest;
  KeyStatusResponse: KeyStatusResponse;
  KeyUpdatePayload: KeyUpdatePayload;
  KeysStatusResponse: KeysStatusResponse;
  QuotaExhausted: QuotaExhausted;
  QuotaStatus: QuotaStatus;
  ResetRequest: ResetRequest;
  SessionDetailResponse: SessionDetailResponse;
  SessionsResponse: SessionsResponse;
  SignInRequest: SignInRequest;
  SignInResponse: SignInResponse;
  SignUpRequest: SignUpRequest;
  StreamEventSchema: StreamEventSchema;
  ThreadSnapshot: ThreadSnapshot;
  TokenRequest: TokenRequest;
  UsageTotals: UsageTotals;
  UserInfo: UserInfo;
  WorkspaceState: WorkspaceState;
}
/**
 * The same answer whether or not the email has an account.
 *
 * This interface was referenced by `ApiContract`'s JSON-Schema
 * via the `definition` "AcceptedResponse".
 */
export interface AcceptedResponse {
  status: "accepted";
}
/**
 * ``POST /api/v1/account/password``.
 *
 * This interface was referenced by `ApiContract`'s JSON-Schema
 * via the `definition` "ChangePasswordRequest".
 */
export interface ChangePasswordRequest {
  current_password: string;
  new_password: string;
}
/**
 * Body of ``POST /api/v1/chat/stream``: a message, or answers to an open request.
 *
 * This interface was referenced by `ApiContract`'s JSON-Schema
 * via the `definition` "ChatRequest".
 */
export interface ChatRequest {
  answers?: ConfirmationAnswers | null;
  message?: string;
  thread_id: string;
}
/**
 * Answers to an open confirmation request: every entry, each answered once.
 *
 * This interface was referenced by `ApiContract`'s JSON-Schema
 * via the `definition` "ConfirmationAnswers".
 */
export interface ConfirmationAnswers {
  /**
   * @minItems 1
   * @maxItems 50
   */
  entries: [EntryAnswer, ...EntryAnswer[]];
  request_id: string;
}
/**
 * The user's answer to one missing value: a number in one of its units, or a decline.
 *
 * This interface was referenced by `ApiContract`'s JSON-Schema
 * via the `definition` "EntryAnswer".
 */
export interface EntryAnswer {
  decision: "supply" | "decline";
  entry_id: string;
  number?: number | null;
  unit?: string | null;
}
/**
 * Display settings the frontend needs (``GET /api/v1/settings/client``).
 *
 * This interface was referenced by `ApiContract`'s JSON-Schema
 * via the `definition` "ClientConfig".
 */
export interface ClientConfig {
  layout: LayoutConfig;
  map: MapConfig;
  /**
   * Chat model that drives the agent.
   */
  model: string;
  narrow_breakpoint_px: number;
  significant_digits: number;
  suggestions: string[];
  thresholds: Thresholds;
  worker_thresholds: WorkerThresholds;
}
/**
 * Workspace layout limits from the configuration.
 *
 * This interface was referenced by `ApiContract`'s JSON-Schema
 * via the `definition` "LayoutConfig".
 */
export interface LayoutConfig {
  chat: ChatLayout;
  overview: OverviewLayout;
  rail: RailLayout;
}
/**
 * Chat dock: default and maximum shares of the viewport width (0-1), minimum width in px.
 *
 * This interface was referenced by `ApiContract`'s JSON-Schema
 * via the `definition` "ChatLayout".
 */
export interface ChatLayout {
  default_share: number;
  max_share: number;
  min_px: number;
}
/**
 * Overview panel height as shares (0-1) of the analysis area.
 *
 * This interface was referenced by `ApiContract`'s JSON-Schema
 * via the `definition` "OverviewLayout".
 */
export interface OverviewLayout {
  default_share: number;
  max_share: number;
  min_share: number;
}
/**
 * Navigation rail widths in px: collapsed to icons, and the expanded default and limits.
 *
 * This interface was referenced by `ApiContract`'s JSON-Schema
 * via the `definition` "RailLayout".
 */
export interface RailLayout {
  collapsed_px: number;
  default_px: number;
  max_px: number;
  min_px: number;
}
/**
 * Basemap style URLs and the marker radii (px) for the smallest and largest emission rate.
 *
 * This interface was referenced by `ApiContract`'s JSON-Schema
 * via the `definition` "MapConfig".
 */
export interface MapConfig {
  dark_style: string;
  initial_view: InitialView;
  light_style: string;
  marker_max_px: number;
  marker_min_px: number;
}
/**
 * What the map shows before any facility.
 */
export interface InitialView {
  east: number;
  north: number;
  south: number;
  west: number;
}
/**
 * Status thresholds (unitless HQ and lifetime cancer risk).
 *
 * This interface was referenced by `ApiContract`'s JSON-Schema
 * via the `definition` "Thresholds".
 */
export interface Thresholds {
  cancer_lower: number;
  cancer_upper: number;
  hq_concern: number;
  hq_near_lower: number;
}
/**
 * Tier boundaries of the worker screening: above `*_exceedance` is "exceedance", above
 * `*_elevated` is "elevated" (unitless; cancer risk is a probability).
 *
 * This interface was referenced by `ApiContract`'s JSON-Schema
 * via the `definition` "WorkerThresholds".
 */
export interface WorkerThresholds {
  cancer_elevated: number;
  cancer_exceedance: number;
  hq_elevated: number;
  hq_exceedance: number;
  ratio_elevated: number;
  ratio_exceedance: number;
}
/**
 * ``POST /api/v1/account/delete``: the account's password confirms it.
 *
 * This interface was referenced by `ApiContract`'s JSON-Schema
 * via the `definition` "DeleteAccountRequest".
 */
export interface DeleteAccountRequest {
  password: string;
}
/**
 * ``POST /api/v1/auth/resend`` and ``/forgot``: the address to mail.
 *
 * This interface was referenced by `ApiContract`'s JSON-Schema
 * via the `definition` "EmailRequest".
 */
export interface EmailRequest {
  email: string;
}
/**
 * Whether a key is stored; never the key or any part of it.
 *
 * This interface was referenced by `ApiContract`'s JSON-Schema
 * via the `definition` "KeyStatusResponse".
 */
export interface KeyStatusResponse {
  configured: boolean;
}
/**
 * Body of ``POST /api/v1/settings/openai-key``; the key is never echoed or logged.
 *
 * This interface was referenced by `ApiContract`'s JSON-Schema
 * via the `definition` "KeyUpdatePayload".
 */
export interface KeyUpdatePayload {
  /**
   * The user's OpenAI API key; stored encrypted for their account only.
   */
  api_key: string;
}
/**
 * The user's OpenAI key status and the data services this installation provides.
 *
 * This interface was referenced by `ApiContract`'s JSON-Schema
 * via the `definition` "KeysStatusResponse".
 */
export interface KeysStatusResponse {
  openai: KeyStatusResponse;
  services: ServicesAvailability;
}
/**
 * The data services the operator may provide.
 *
 * This interface was referenced by `ApiContract`'s JSON-Schema
 * via the `definition` "ServicesAvailability".
 */
export interface ServicesAvailability {
  census: ServiceAvailability;
  comptox: ServiceAvailability;
}
/**
 * Whether a data service is provided by this installation (never its key).
 *
 * This interface was referenced by `ApiContract`'s JSON-Schema
 * via the `definition` "ServiceAvailability".
 */
export interface ServiceAvailability {
  available: boolean;
}
/**
 * The body of the 429 answer to a new turn over the quota.
 *
 * Attributes:
 *     detail: Fixed message from configuration.
 *     limit: Turns allowed per UTC day.
 *     resets_at: The next 00:00 UTC.
 *     correlation_id: Id to quote when asking about this refusal.
 *
 * This interface was referenced by `ApiContract`'s JSON-Schema
 * via the `definition` "QuotaExhausted".
 */
export interface QuotaExhausted {
  correlation_id: string;
  detail: string;
  limit: number;
  resets_at: string;
}
/**
 * The signed-in user's quota today.
 *
 * Attributes:
 *     applies: Whether the quota applies to this user (false when it is disabled or the user
 *         is an exempt administrator; the other figures are then absent).
 *     limit: Turns allowed per UTC day.
 *     used: Turns counted today.
 *     remaining: Turns left today.
 *     resets_at: The next 00:00 UTC (the figures start again then).
 *
 * This interface was referenced by `ApiContract`'s JSON-Schema
 * via the `definition` "QuotaStatus".
 */
export interface QuotaStatus {
  applies: boolean;
  limit: number | null;
  remaining: number | null;
  resets_at: string | null;
  used: number | null;
}
/**
 * ``POST /api/v1/auth/reset``: the token from the emailed link and the new password.
 *
 * This interface was referenced by `ApiContract`'s JSON-Schema
 * via the `definition` "ResetRequest".
 */
export interface ResetRequest {
  password: string;
  token: string;
}
/**
 * ``GET /api/v1/monitoring/sessions/{session_id}``: one session and its turns.
 *
 * This interface was referenced by `ApiContract`'s JSON-Schema
 * via the `definition` "SessionDetailResponse".
 */
export interface SessionDetailResponse {
  message: string | null;
  session: SessionSummary | null;
  state: "ok" | "not_configured" | "unavailable" | "unauthorized";
  turns: SessionTurn[];
}
/**
 * A session as listed: a web thread or one command-line run.
 *
 * Counts come from the trace's spans; tokens and cost are the sums of the turns' recorded
 * usage and are None when any turn did not record them. ``cost_status`` is the weakest status
 * of its turns (``unknown`` when one is missing). ``account`` is the email of the user who ran
 * it, looked up in the application database from the opaque user id on the spans; None when the
 * spans carry none (a command-line run) or the account no longer exists.
 *
 * This interface was referenced by `ApiContract`'s JSON-Schema
 * via the `definition` "SessionSummary".
 */
export interface SessionSummary {
  account: string | null;
  cached_input_tokens: number | null;
  cost_status: "estimate" | "lower_bound" | "unpriced" | "unknown";
  cost_usd: number | null;
  duration_ms: number | null;
  input_tokens: number | null;
  model: string | null;
  model_calls: number | null;
  outcome: "ok" | "error" | "unknown";
  output_tokens: number | null;
  question: string | null;
  session_id: string;
  started_at: string;
  tool_calls: number | null;
  turns: number;
}
/**
 * One turn (web) or run (command line) of a session, with its steps.
 *
 * ``trace_url`` opens the trace in Logfire; None when the project is unknown.
 *
 * This interface was referenced by `ApiContract`'s JSON-Schema
 * via the `definition` "SessionTurn".
 */
export interface SessionTurn {
  duration_ms: number | null;
  outcome: "ok" | "error" | "unknown";
  question: string | null;
  started_at: string;
  steps: SessionStep[];
  trace_id: string;
  trace_url: string | null;
}
/**
 * One model call or tool call of a turn, in start order.
 *
 * Attributes:
 *     kind: ``model`` or ``tool``.
 *     name: The model name, or the tool's step label.
 *     offset_ms: Start, in milliseconds after the turn started.
 *     duration_ms: How long it took.
 *     outcome: ``error`` when the call raised.
 *     input_tokens: Input tokens (model calls that reported usage).
 *     output_tokens: Output tokens (model calls that reported usage).
 *
 * This interface was referenced by `ApiContract`'s JSON-Schema
 * via the `definition` "SessionStep".
 */
export interface SessionStep {
  duration_ms: number | null;
  input_tokens: number | null;
  kind: "model" | "tool";
  name: string;
  offset_ms: number;
  outcome: "ok" | "error" | "unknown";
  output_tokens: number | null;
}
/**
 * ``GET /api/v1/monitoring/sessions``: recent sessions, newest first, or why there are none.
 *
 * ``message`` is a user-safe reason when ``state`` is not ``ok``.
 *
 * This interface was referenced by `ApiContract`'s JSON-Schema
 * via the `definition` "SessionsResponse".
 */
export interface SessionsResponse {
  message: string | null;
  sessions: SessionSummary[];
  state: "ok" | "not_configured" | "unavailable" | "unauthorized";
}
/**
 * ``POST /api/v1/auth/signin``.
 *
 * This interface was referenced by `ApiContract`'s JSON-Schema
 * via the `definition` "SignInRequest".
 */
export interface SignInRequest {
  email: string;
  password: string;
}
/**
 * ``signed_in`` (with the user; the session is the cookie) or ``verification_required``
 * (the password was right but the email is not verified; no session was made).
 *
 * This interface was referenced by `ApiContract`'s JSON-Schema
 * via the `definition` "SignInResponse".
 */
export interface SignInResponse {
  state: "signed_in" | "verification_required";
  user: UserInfo | null;
}
/**
 * The signed-in user: never a password hash or a token.
 *
 * This interface was referenced by `ApiContract`'s JSON-Schema
 * via the `definition` "UserInfo".
 */
export interface UserInfo {
  email: string;
  id: string;
  role: "user" | "admin";
  verified: boolean;
}
/**
 * ``POST /api/v1/auth/signup``.
 *
 * This interface was referenced by `ApiContract`'s JSON-Schema
 * via the `definition` "SignUpRequest".
 */
export interface SignUpRequest {
  email: string;
  password: string;
}
/**
 * This interface was referenced by `ApiContract`'s JSON-Schema
 * via the `definition` "TurnStarted".
 */
export interface TurnStarted {
  resumed: boolean;
  /**
   * Position of the event in its turn's stream: strictly increasing, not contiguous. Sent as the SSE event id; send the last one received as Last-Event-ID to reattach.
   */
  seq: number;
  thread_id: string;
  turn_id: string;
  type: "turn_started";
}
/**
 * What the turn is doing now, for the chat's status line: waiting for a worker (with about
 * how many turns ahead), running, thinking, or running a step (with its label).
 *
 * This interface was referenced by `ApiContract`'s JSON-Schema
 * via the `definition` "TurnStatus".
 */
export interface TurnStatus {
  label: string | null;
  phase: "queued" | "running" | "thinking" | "running_tool";
  position: number | null;
  /**
   * Position of the event in its turn's stream: strictly increasing, not contiguous. Sent as the SSE event id; send the last one received as Last-Event-ID to reattach.
   */
  seq: number;
  type: "turn_status";
}
/**
 * This interface was referenced by `ApiContract`'s JSON-Schema
 * via the `definition` "ScopeDecision".
 */
export interface ScopeDecision {
  in_scope: boolean;
  /**
   * Position of the event in its turn's stream: strictly increasing, not contiguous. Sent as the SSE event id; send the last one received as Last-Event-ID to reattach.
   */
  seq: number;
  type: "scope";
}
/**
 * The in-character redirect sent instead of running the agent on an off-topic turn.
 *
 * This interface was referenced by `ApiContract`'s JSON-Schema
 * via the `definition` "GuardrailPivotResponse".
 */
export interface GuardrailPivotResponse {
  /**
   * Position of the event in its turn's stream: strictly increasing, not contiguous. Sent as the SSE event id; send the last one received as Last-Event-ID to reattach.
   */
  seq: number;
  text: string;
  type: "guardrail_pivot";
}
/**
 * A tool step: ``started`` carries the label; ``finished`` adds the outcome.
 *
 * This interface was referenced by `ApiContract`'s JSON-Schema
 * via the `definition` "ToolStatus".
 */
export interface ToolStatus {
  call_id: string;
  label: string;
  phase: "started" | "finished";
  /**
   * Position of the event in its turn's stream: strictly increasing, not contiguous. Sent as the SSE event id; send the last one received as Last-Event-ID to reattach.
   */
  seq: number;
  status: ("ok" | "error") | null;
  tool_name: string;
  type: "tool_status";
}
/**
 * This interface was referenced by `ApiContract`'s JSON-Schema
 * via the `definition` "WorkspaceUpdate".
 */
export interface WorkspaceUpdate {
  /**
   * Position of the event in its turn's stream: strictly increasing, not contiguous. Sent as the SSE event id; send the last one received as Last-Event-ID to reattach.
   */
  seq: number;
  state: WorkspaceState;
  type: "workspace_update";
}
/**
 * The current workspace of one thread.
 *
 * Attributes:
 *     framing_version: Increases only when the set of placed facilities or buffers changes.
 *     bounds: Extent of the placed facilities and buffers; None when none is placed.
 *     facilities: One per FRS ID, in the order first reported.
 *     selected_frs_id: Facility whose receptors the ribbon shows (the highest risk, or the
 *         only one); None when no single facility stands out.
 *     chemical: The queried chemical and its provenance.
 *     risk: Highest risk values across the attributed facilities.
 *     worker_risk: Highest worker (occupational) values across the assessed facilities.
 *     scenario_drivers: For each pathway and quantity, the facility with the highest value.
 *     receptors: Receptors of the selected facility.
 *     meteorology: Meteorology of the selected facility, else the latest result.
 *     unattributed: Results not attached to any facility.
 *     warnings: Results left out (malformed, unattributable) and why.
 *
 * This interface was referenced by `ApiContract`'s JSON-Schema
 * via the `definition` "WorkspaceState".
 */
export interface WorkspaceState {
  bounds: BoundingBox | null;
  chemical: Chemical;
  facilities: Facility[];
  framing_version: number;
  meteorology: Meteorology | null;
  receptors: Receptors | null;
  risk: RiskSummary;
  scenario_drivers: ScenarioDriver[];
  selected_frs_id: string | null;
  unattributed: Unattributed[];
  warnings: string[];
  worker_risk: WorkerRiskSummary;
}
/**
 * Extent of the placed facilities and buffers, decimal degrees (WGS84).
 *
 * This interface was referenced by `ApiContract`'s JSON-Schema
 * via the `definition` "BoundingBox".
 */
export interface BoundingBox {
  east: number;
  north: number;
  south: number;
  west: number;
}
/**
 * The chemical as queried, with its properties and read-across provenance.
 *
 * Attributes:
 *     cas_number: CAS number as queried.
 *     name: The name the properties result gave (CompTox's preferred name); None when it
 *         gave none, and then the CAS number stands alone.
 *     molecular_weight_g_mol: Molecular weight, g/mol.
 *     vapor_pressure_mmhg: Vapor pressure, mmHg (its source is in ``sources``).
 *     density_g_cm3: Density, g/cm³.
 *     oel_twa_mg_m3: 8-hour occupational exposure limit, mg/m³ (source under ``oel_twa``).
 *     rfc_mg_m3: Inhalation reference concentration, mg/m³.
 *     iur_per_ug_m3: Inhalation unit risk, (µg/m³)⁻¹.
 *     sources: Field name -> source the value came from.
 *
 * This interface was referenced by `ApiContract`'s JSON-Schema
 * via the `definition` "Chemical".
 */
export interface Chemical {
  cas_number: string | null;
  density_g_cm3: number | null;
  iur_per_ug_m3: number | null;
  molecular_weight_g_mol: number | null;
  name: string | null;
  oel_twa_mg_m3: number | null;
  read_across: ReadAcross;
  rfc_mg_m3: number | null;
  sources: {
    [k: string]: string;
  };
  vapor_pressure_mmhg: number | null;
  warnings: string[];
}
/**
 * The read-across outcome for the queried chemical (surrogate values are scores 0-1).
 *
 * This interface was referenced by `ApiContract`'s JSON-Schema
 * via the `definition` "ReadAcross".
 */
export interface ReadAcross {
  cosine_similarity: number | null;
  hybrid_score: number | null;
  kind: "not_evaluated" | "direct_tri_match" | "tri_category_member" | "read_across" | "unresolved";
  surrogate_cas: string | null;
  surrogate_name: string | null;
  tanimoto_similarity: number | null;
  warnings: string[];
  within_applicability_domain: boolean | null;
}
/**
 * One facility of the emissions inventory with what the other tools reported about it.
 *
 * Attributes:
 *     doc_ctrl_num: TRI document control number (the inventory has no TRI facility ID).
 *     total_release: Annual quantity in ``release_unit``, as reported.
 *     emission_rate_g_s: Total release averaged over ``operating_hours_per_year``.
 *     operating_hours_source: Where those hours came from (industry survey or default); None
 *         when the record predates the field.
 *     fugitive_release_kg_per_year: TRI fugitive air release, kg/yr; None when TRI has none.
 *     exposure: The community (ambient fenceline) result.
 *     occupational_exposure: The worker screening; None when no assessment produced it.
 *     operational_profile: Schedule, life cycle stage, condition of use and CDR sector.
 *     scenarios: The worst-case scenarios of the facility, one per pathway and quantity that
 *         has a value.
 *     exposure_graph: How the worst-case exposure arises, source to endpoint, per pathway.
 *     naics_subsector: First three digits of the inventory's NAICS code (e.g. "325").
 *     naics_subsector_title: That subsector's title from the Census lists; None if unknown.
 *     conditions_of_use: TSCA conditions of use of the activities the facility reported to TRI.
 *     lifecycle_stages: The distinct TSCA life cycle stages of ``conditions_of_use``.
 *     conditions_note: Why ``conditions_of_use`` is empty; None when it is not.
 *     stack_source: Where the NEI stack lookup came from, when one was made for the facility.
 *     status: Worst-case risk status (from the screening value when screened out); None
 *         while no risk is computed.
 *     screening: How the batch assessment screened it; None when it did not.
 *     buffer: The receptor radius drawn as a circle around the facility, when receptors exist.
 *     sector: Schematic downwind sector (toward ``wind_toward_deg``, length the receptor radius);
 *         never a modelled plume footprint. Present with both receptors and meteorology.
 *
 * This interface was referenced by `ApiContract`'s JSON-Schema
 * via the `definition` "Facility".
 */
export interface Facility {
  address: string | null;
  buffer: Polygon | null;
  cas_number: string | null;
  city: string | null;
  conditions_note: string | null;
  conditions_of_use: ConditionOfUse[];
  county: string | null;
  doc_ctrl_num: string | null;
  emission_rate_g_s: number;
  exposure: ExposureRanges | null;
  exposure_graph: ExposureGraph | null;
  frs_id: string;
  fugitive_release_kg_per_year: number | null;
  fugitive_reporting_year: number | null;
  industry: Industry | null;
  latitude: number;
  lifecycle_stages: string[];
  longitude: number;
  medium: string;
  meteorology: Meteorology | null;
  naics_subsector: string | null;
  naics_subsector_title: string | null;
  name: string | null;
  occupational_exposure: OccupationalExposure | null;
  operating_hours_per_year: number;
  operating_hours_source: string | null;
  operational_profile: OperationalProfile | null;
  receptors: Receptors | null;
  release_unit: string;
  reporting_year: number;
  scenarios: WorstCaseScenario[];
  screening: Screening | null;
  sector: Polygon | null;
  stacks: Stack[];
  state: string | null;
  status: ("below" | "near" | "above") | null;
  total_release: number;
  zip_code: string | null;
}
/**
 * A GeoJSON polygon: one closed ring of ``[longitude, latitude]`` positions (WGS84).
 *
 * This interface was referenced by `ApiContract`'s JSON-Schema
 * via the `definition` "Polygon".
 */
export interface Polygon {
  coordinates: number[][][];
  type: "Polygon";
}
/**
 * One TSCA condition of use implied by a TRI activity the facility reported.
 *
 * This interface was referenced by `ApiContract`'s JSON-Schema
 * via the `definition` "ConditionOfUse".
 */
export interface ConditionOfUse {
  cou_category: string;
  lifecycle_stage: string;
  mapping_strength: string;
  tri_activity: string;
  tri_section: string;
}
/**
 * Ranges over the evaluated stacks of one facility; None when no stack has the quantity.
 *
 * This interface was referenced by `ApiContract`'s JSON-Schema
 * via the `definition` "ExposureRanges".
 */
export interface ExposureRanges {
  cancer_risk_representative: Extreme | null;
  cancer_risk_worst: Extreme | null;
  concentration_representative: Extreme | null;
  concentration_worst: Extreme | null;
  /**
   * Per age band, the highest worst-case dose over the stacks.
   */
  dose: Dose | null;
  hq_representative: Extreme | null;
  hq_worst: Extreme | null;
  stacks_evaluated: number;
  stacks_given: number;
  warnings: string[];
}
/**
 * The lowest and highest value of one quantity over a facility's stacks.
 *
 * This interface was referenced by `ApiContract`'s JSON-Schema
 * via the `definition` "Extreme".
 */
export interface Extreme {
  high: number;
  high_stack: number;
  low: number;
  low_stack: number;
}
/**
 * Inhalation average daily dose, mg/(kg·day), of the worst case, by age band of the residents.
 *
 * ``highest_band`` is the band with the largest dose (``highest_mg_kg_day``); ``by_band`` has
 * every band that has residents. Children get larger doses because they breathe more per kg.
 *
 * This interface was referenced by `ApiContract`'s JSON-Schema
 * via the `definition` "Dose".
 */
export interface Dose {
  by_band: {
    [k: string]: number;
  };
  highest_band: string | null;
  highest_mg_kg_day: number | null;
}
/**
 * The source facility, then each lane's steps, joined by labelled edges.
 *
 * This interface was referenced by `ApiContract`'s JSON-Schema
 * via the `definition` "ExposureGraph".
 */
export interface ExposureGraph {
  edges: GraphEdge[];
  lanes: GraphLane[];
  nodes: GraphNode[];
}
/**
 * A connection from one node to the next, with the quantity it carries when there is one.
 *
 * This interface was referenced by `ApiContract`'s JSON-Schema
 * via the `definition` "GraphEdge".
 */
export interface GraphEdge {
  id: string;
  lane: string;
  quantity: GraphQuantity | null;
  source: string;
  target: string;
}
/**
 * A number a tool reported, with its label and unit, or no number and why.
 *
 * This interface was referenced by `ApiContract`'s JSON-Schema
 * via the `definition` "GraphQuantity".
 */
export interface GraphQuantity {
  key: string;
  label: string;
  /**
   * Why ``value`` is absent.
   */
  reason: string | null;
  source: string | null;
  unit: string;
  value: number | null;
}
/**
 * One pathway (community outdoor air, worker indoor air), its status and if it is drawn.
 *
 * This interface was referenced by `ApiContract`'s JSON-Schema
 * via the `definition` "GraphLane".
 */
export interface GraphLane {
  available: boolean;
  id: string;
  label: string;
  reason: string | null;
  status: ("below" | "near" | "above") | null;
  status_label: string | null;
}
/**
 * One step of a lane, or the source facility shared by every lane.
 *
 * Attributes:
 *     lane: Lane id; None for the source facility.
 *     headline: Key of the quantity shown on the node, when it has one.
 *     status_label: The status in the lane's own words (the worker tier); None to use the default.
 *
 * This interface was referenced by `ApiContract`'s JSON-Schema
 * via the `definition` "GraphNode".
 */
export interface GraphNode {
  facts: GraphFact[];
  headline: string | null;
  id: string;
  kind: "source" | "release" | "pathway" | "route" | "receptor" | "endpoint";
  lane: string | null;
  quantities: GraphQuantity[];
  status: ("below" | "near" | "above") | null;
  status_label: string | null;
  title: string;
  warnings: string[];
}
/**
 * A text value a tool reported (a source, a class, a list), or none and why.
 *
 * This interface was referenced by `ApiContract`'s JSON-Schema
 * via the `definition` "GraphFact".
 */
export interface GraphFact {
  key: string;
  label: string;
  reason: string | null;
  text: string | null;
}
/**
 * Primary industry of the TRI submission; origin is reported, assigned or None.
 *
 * This interface was referenced by `ApiContract`'s JSON-Schema
 * via the `definition` "Industry".
 */
export interface Industry {
  code_origin: string | null;
  naics_code: string | null;
  naics_title: string | null;
  source: string | null;
}
/**
 * Annual representative conditions at a point: m/s, degrees clockwise from north, K.
 *
 * This interface was referenced by `ApiContract`'s JSON-Schema
 * via the `definition` "Meteorology".
 */
export interface Meteorology {
  ambient_temperature_k: number;
  facility_name: string | null;
  /**
   * Facility at that point, if one is.
   */
  frs_id: string | null;
  /**
   * Point the weather is for, decimal degrees.
   */
  latitude: number;
  /**
   * Point the weather is for, decimal degrees.
   */
  longitude: number;
  screening_default: boolean;
  source: string;
  stability_class: string;
  warnings: string[];
  /**
   * Direction the wind blows from.
   */
  wind_from_deg: number;
  wind_speed_m_s: number;
  /**
   * Downwind direction, ``(from + 180) % 360``.
   */
  wind_toward_deg: number;
}
/**
 * Worker screening of a facility: EPA ChemSTEER box model and RAGS Part F dosimetry.
 *
 * A screening that assumes generic ventilation, not an OSHA compliance determination.
 *
 * Attributes:
 *     fugitive_release_kg_per_year: TRI fugitive air release, kg/yr (year in
 *         ``fugitive_reporting_year``).
 *     operating_days_per_year: Days a year the plant runs, d/yr.
 *     hours_per_day: Hours a day it runs, h/day.
 *     oel_twa_mg_m3: The 8-hour occupational limit used, mg/m³, with ``oel_source``.
 *     rfc: Reference concentration used, mg/m³.
 *     iur: Inhalation unit risk used, (µg/m³)⁻¹.
 *     vapor_pressure_mmhg: Context only; never enters an equation. Its source is in
 *         ``vapor_pressure_source``.
 *     baseline: The baseline manufacturing ventilation tier.
 *     worst_case: The enclosed-zone tier.
 *     risk_tier: The baseline tier.
 *
 * This interface was referenced by `ApiContract`'s JSON-Schema
 * via the `definition` "OccupationalExposure".
 */
export interface OccupationalExposure {
  assumptions: string[];
  baseline: VentilationTier;
  fugitive_release_kg_per_year: number | null;
  fugitive_reporting_year: number | null;
  hours_per_day: number | null;
  iur: number | null;
  oel_source: string | null;
  oel_twa_mg_m3: number | null;
  operating_days_per_year: number | null;
  rfc: number | null;
  risk_tier: ("exceedance" | "elevated" | "acceptable") | null;
  vapor_pressure_mmhg: number | null;
  vapor_pressure_source: string | null;
  warnings: string[];
  worst_case: VentilationTier;
}
/**
 * The worker screening for one ventilation tier of the box model; None = not computed.
 *
 * Attributes:
 *     ventilation_m3_per_s: Room ventilation rate, m³/s.
 *     mixing_factor: Mixing factor k, unitless.
 *     workplace_concentration_mg_m3: Concentration while the plant runs, mg/m³.
 *     twa_mg_m3: 8-hour time-weighted average, mg/m³.
 *     oel_ratio: The average over the occupational limit (unitless); above 1 exceeds it.
 *     hq: Worker hazard quotient (unitless).
 *     cancer_risk: Worker lifetime excess cancer risk (unitless).
 *     risk_tier: "exceedance", "elevated" or "acceptable"; None when nothing could be compared.
 *
 * This interface was referenced by `ApiContract`'s JSON-Schema
 * via the `definition` "VentilationTier".
 */
export interface VentilationTier {
  cancer_risk: number | null;
  hq: number | null;
  label: string;
  mixing_factor: number;
  oel_ratio: number | null;
  risk_tier: ("exceedance" | "elevated" | "acceptable") | null;
  twa_mg_m3: number | null;
  ventilation_m3_per_s: number;
  workplace_concentration_mg_m3: number | null;
}
/**
 * How a facility operates and where it sits in the TSCA framework.
 *
 * Attributes:
 *     life_cycle_stage: TSCA stages of the activities the facility reported to TRI.
 *     cou_category: TSCA condition-of-use categories of those activities.
 *     cdr_sector: CDR industrial sector of its NAICS code; None when the table has none.
 *     days_per_week: Derived from the Census QPC hours per week and a configured working day.
 *     operating_days_per_year: Days a year, d/yr.
 *     hours_per_day: Hours a day, h/day.
 *     annual_operating_hours: Hours a year, h/yr (at most 8,760).
 *     schedule_source: Where the hours come from.
 *
 * This interface was referenced by `ApiContract`'s JSON-Schema
 * via the `definition` "OperationalProfile".
 */
export interface OperationalProfile {
  annual_operating_hours: number | null;
  cdr_sector: CdrSector | null;
  cou_category: string[];
  days_per_week: number | null;
  hours_per_day: number | null;
  life_cycle_stage: string[];
  naics_code: string | null;
  operating_days_per_year: number | null;
  schedule_source: string | null;
  warnings: string[];
}
/**
 * The TSCA CDR industrial sector of a NAICS code, with the table row that matched.
 *
 * This interface was referenced by `ApiContract`'s JSON-Schema
 * via the `definition` "CdrSector".
 */
export interface CdrSector {
  code: string;
  matched_naics_prefix: string;
  naics_edition: string;
  name: string;
}
/**
 * Residents within ``radius_km`` of a point; ``age_distribution`` is percent per band.
 *
 * This interface was referenced by `ApiContract`'s JSON-Schema
 * via the `definition` "Receptors".
 */
export interface Receptors {
  age_distribution: {
    [k: string]: number;
  };
  radius_km: number;
  screening_default: boolean;
  source: string;
  total_population: number;
  warnings: string[];
}
/**
 * The combination of factors behind the high-end value of one quantity on one pathway.
 *
 * A screening result, never a regulatory finding: ``tier`` is the level the assessment gave.
 *
 * Attributes:
 *     pathway_key: Which pathway produced it, e.g. ``community_inhalation``.
 *     pathway: Medium, route and receptor class, in words.
 *     quantity: ``hq``, ``cancer_risk`` or ``oel_ratio``.
 *     value: The high-end value, unitless.
 *     tier: The level the assessment gave the value; None when none was given.
 *     benchmark: The level of concern the value was compared with, unitless.
 *     receptors_note: Why there are no receptors, or what was left out.
 *
 * This interface was referenced by `ApiContract`'s JSON-Schema
 * via the `definition` "WorstCaseScenario".
 */
export interface WorstCaseScenario {
  benchmark: number | null;
  factors: ScenarioFactor[];
  notes: string[];
  pathway: string;
  pathway_key: string;
  quantity: string;
  quantity_label: string;
  receptors: ScenarioReceptor[];
  receptors_note: string | null;
  tier: string | null;
  value: number;
}
/**
 * One factor of a worst-case scenario: a value a tool returned, or why there is none.
 *
 * Attributes:
 *     group: source, release, conditions or receptor_model.
 *     value: A number or text a tool returned; None when none did (see ``reason``).
 *     unit: Unit of ``value``; empty when unitless or text.
 *     source: Where the value came from, when a tool said.
 *     reason: Why there is no value.
 *
 * This interface was referenced by `ApiContract`'s JSON-Schema
 * via the `definition` "ScenarioFactor".
 */
export interface ScenarioFactor {
  group: "source" | "release" | "conditions" | "receptor_model";
  key: string;
  label: string;
  reason: string | null;
  source: string | null;
  unit: string;
  value: number | string | null;
}
/**
 * A receptor of a worst-case scenario: a census tract, or the facility's workers.
 *
 * Attributes:
 *     residents: Persons in the tract (the tract's ACS estimate); None for workers.
 *     age_distribution: Age band -> percent of the tract; empty for workers.
 *     distance_m: Meters from the facility to the tract's internal point.
 *     bearing_deg: Degrees clockwise from north from the facility to that point.
 *     latitude: Decimal degrees of that point (the census service's internal point), for drawing.
 *     longitude: Decimal degrees of that point.
 *     concentration: Annual-average ug/m^3 the scenario gives at the tract (workers: the
 *         8-hour average, mg/m^3).
 *     fraction_of_maximum: That concentration over the scenario's maximum, unitless.
 *
 * This interface was referenced by `ApiContract`'s JSON-Schema
 * via the `definition` "ScenarioReceptor".
 */
export interface ScenarioReceptor {
  age_distribution: {
    [k: string]: number;
  };
  bearing_deg: number | null;
  concentration: number | null;
  distance_m: number | null;
  fraction_of_maximum: number | null;
  kind: "tract" | "workers";
  label: string;
  latitude: number | null;
  longitude: number | null;
  note: string | null;
  residents: number | null;
}
/**
 * How the batch assessment screened a facility.
 *
 * Attributes:
 *     outcome: Fully assessed; kept at its own-stack worst case only (no weather, residents
 *         or representative case); or screened out on the conservative bound (a generic
 *         short, cold stack) or on its own-stack worst case, below both thresholds; or not
 *         assessed, with the reason in ``reason``.
 *     bound_hq: The bound's hazard quotient (unitless), when computed.
 *     bound_cancer_risk: The bound's lifetime excess cancer risk (unitless), when computed.
 *     value_hq: The screening value compared with the threshold (the bound, or the own-stack
 *         worst case), unitless.
 *     value_cancer_risk: Likewise for the cancer risk.
 *     reason: Why the facility was screened out or not assessed, in words; None otherwise.
 *
 * This interface was referenced by `ApiContract`'s JSON-Schema
 * via the `definition` "Screening".
 */
export interface Screening {
  bound_cancer_risk: number | null;
  bound_hq: number | null;
  outcome: "full" | "worst_case_only" | "screened_out_at_bound" | "screened_out_with_own_stacks" | "not_assessed";
  reason: string | null;
  value_cancer_risk: number | null;
  value_hq: number | null;
}
/**
 * One release point with its provenance tier and, when computed, its results.
 *
 * Attributes:
 *     stack_number: 1-based position in the exposure call that evaluated it, else None.
 *     tier: 1 Empirical NEI, 2 PSTK by SCC, 3 EPA global default; None without a source.
 *     tier_label: ``Tier 1: Empirical NEI`` and so on.
 *     scc: SCC behind a PSTK stack, when reported.
 *     scc_description: Most specific process description of that SCC, from an SCC lookup
 *         in the same thread; None when no lookup returned it.
 *     scc_score: Match score (0-1) of that lookup.
 *
 * This interface was referenced by `ApiContract`'s JSON-Schema
 * via the `definition` "Stack".
 */
export interface Stack {
  diameter_m: number | null;
  dose: Dose | null;
  exit_temperature_k: number | null;
  exit_velocity_m_s: number | null;
  height_m: number | null;
  representative: Scenario | null;
  scc: string | null;
  scc_description: string | null;
  scc_score: number | null;
  source: string | null;
  stack_number: number | null;
  tier: (1 | 2 | 3) | null;
  tier_label: string | null;
  warnings: string[];
  worst_case: Scenario | null;
}
/**
 * Screening result for one set of weather: concentration µg/m³, HQ and cancer risk unitless.
 *
 * This interface was referenced by `ApiContract`'s JSON-Schema
 * via the `definition` "Scenario".
 */
export interface Scenario {
  cancer_risk: number | null;
  /**
   * Downwind distance of the maximum.
   */
  distance_m: number | null;
  hq: number | null;
  max_concentration_ug_m3: number | null;
}
/**
 * Highest worst-case and representative HQ and cancer risk; ``reason`` when none exists.
 *
 * This interface was referenced by `ApiContract`'s JSON-Schema
 * via the `definition` "RiskSummary".
 */
export interface RiskSummary {
  cancer_risk_representative: Extremum | null;
  cancer_risk_worst: Extremum | null;
  hq_representative: Extremum | null;
  hq_worst: Extremum | null;
  /**
   * Why no value yet, e.g. not computed.
   */
  reason: string | null;
}
/**
 * The highest value of one risk quantity over every attributed facility.
 *
 * Attributes:
 *     value: The value (HQ and cancer risk are unitless).
 *     frs_id: Facility whose stack gave it.
 *     facility_name: That facility's name, as reported.
 *     stack_number: The stack that gave it.
 *     status: Position against the configured thresholds of concern.
 *
 * This interface was referenced by `ApiContract`'s JSON-Schema
 * via the `definition` "Extremum".
 */
export interface Extremum {
  facility_name: string | null;
  frs_id: string;
  stack_number: number;
  status: "below" | "near" | "above";
  value: number;
}
/**
 * The assessed facility whose scenario has the highest value of a pathway's quantity.
 *
 * Attributes:
 *     stack_number: The stack behind the value (community pathways); None otherwise.
 *
 * This interface was referenced by `ApiContract`'s JSON-Schema
 * via the `definition` "ScenarioDriver".
 */
export interface ScenarioDriver {
  facility_name: string | null;
  frs_id: string;
  pathway_key: string;
  quantity: string;
  stack_number: number | null;
  value: number;
}
/**
 * A result that could not be tied to exactly one facility, and why.
 *
 * This interface was referenced by `ApiContract`'s JSON-Schema
 * via the `definition` "Unattributed".
 */
export interface Unattributed {
  reason: string;
  tool: string;
}
/**
 * The worker screening across facilities, for both ventilation tiers; ``reason`` if none.
 *
 * This interface was referenced by `ApiContract`'s JSON-Schema
 * via the `definition` "WorkerRiskSummary".
 */
export interface WorkerRiskSummary {
  baseline: WorkerTierSummary;
  /**
   * Why no value yet, e.g. not computed.
   */
  reason: string | null;
  worst_case: WorkerTierSummary;
}
/**
 * Highest limit ratio, hazard quotient and cancer risk of the workers for one tier.
 *
 * This interface was referenced by `ApiContract`'s JSON-Schema
 * via the `definition` "WorkerTierSummary".
 */
export interface WorkerTierSummary {
  cancer_risk: WorkerExtremum | null;
  hq: WorkerExtremum | null;
  oel_ratio: WorkerExtremum | null;
}
/**
 * The highest value of one worker quantity over the assessed facilities.
 *
 * ``risk_tier`` is the tier the tool gave that facility (baseline ventilation).
 *
 * This interface was referenced by `ApiContract`'s JSON-Schema
 * via the `definition` "WorkerExtremum".
 */
export interface WorkerExtremum {
  facility_name: string | null;
  frs_id: string;
  risk_tier: ("exceedance" | "elevated" | "acceptable") | null;
  value: number;
}
/**
 * This interface was referenced by `ApiContract`'s JSON-Schema
 * via the `definition` "Token".
 */
export interface Token {
  /**
   * Position of the event in its turn's stream: strictly increasing, not contiguous. Sent as the SSE event id; send the last one received as Last-Event-ID to reattach.
   */
  seq: number;
  text: string;
  type: "token";
}
/**
 * This interface was referenced by `ApiContract`'s JSON-Schema
 * via the `definition` "AssistantMessage".
 */
export interface AssistantMessage {
  /**
   * Position of the event in its turn's stream: strictly increasing, not contiguous. Sent as the SSE event id; send the last one received as Last-Event-ID to reattach.
   */
  seq: number;
  text: string;
  type: "assistant_message";
}
/**
 * The turn stopped for a reason the user can fix; it may be resumed where it stopped.
 *
 * This interface was referenced by `ApiContract`'s JSON-Schema
 * via the `definition` "TurnInterrupted".
 */
export interface TurnInterrupted {
  message: string;
  reason:
    | "out_of_credits"
    | "rate_limited"
    | "bad_key"
    | "provider_down"
    | "step_limit"
    | "worker_lost"
    | "cancelled"
    | "time_limit";
  resumable: boolean;
  /**
   * Position of the event in its turn's stream: strictly increasing, not contiguous. Sent as the SSE event id; send the last one received as Last-Event-ID to reattach.
   */
  seq: number;
  type: "turn_interrupted";
}
/**
 * This interface was referenced by `ApiContract`'s JSON-Schema
 * via the `definition` "Usage".
 */
export interface Usage {
  /**
   * Position of the event in its turn's stream: strictly increasing, not contiguous. Sent as the SSE event id; send the last one received as Last-Event-ID to reattach.
   */
  seq: number;
  session: UsageTotals;
  turn: UsageTotals;
  type: "usage";
}
/**
 * Token counts and estimated cost (USD) of a turn or a session.
 *
 * ``cost_status`` is ``estimate`` when every call was priced, ``lower_bound`` when some call
 * reported no usage, and ``unpriced`` (``cost_usd`` null) when the model has no price.
 *
 * This interface was referenced by `ApiContract`'s JSON-Schema
 * via the `definition` "UsageTotals".
 */
export interface UsageTotals {
  cached_input_tokens: number;
  calls: number;
  complete: boolean;
  cost_status: "estimate" | "lower_bound" | "unpriced";
  cost_usd: number | null;
  input_tokens: number;
  output_tokens: number;
  priced_on: string | null;
}
/**
 * A user-safe message and the id under which the details were logged.
 *
 * This interface was referenced by `ApiContract`'s JSON-Schema
 * via the `definition` "ErrorEvent".
 */
export interface ErrorEvent {
  correlation_id: string;
  message: string;
  /**
   * Position of the event in its turn's stream: strictly increasing, not contiguous. Sent as the SSE event id; send the last one received as Last-Event-ID to reattach.
   */
  seq: number;
  type: "error";
}
/**
 * The turn stopped to ask the user for missing values; the request stays open.
 *
 * This interface was referenced by `ApiContract`'s JSON-Schema
 * via the `definition` "ConfirmationRequested".
 */
export interface ConfirmationRequested {
  entries: MissingValue[];
  request_id: string;
  /**
   * Position of the event in its turn's stream: strictly increasing, not contiguous. Sent as the SSE event id; send the last one received as Last-Event-ID to reattach.
   */
  seq: number;
  type: "confirmation_request";
}
/**
 * One value the assessment needs and could not find, as the user is asked for it.
 *
 * This interface was referenced by `ApiContract`'s JSON-Schema
 * via the `definition` "MissingValue".
 */
export interface MissingValue {
  accepted_units: string[];
  entry_id: string;
  maximum: number;
  minimum: number;
  purpose: string;
  quantity: string;
  subject: string;
}
/**
 * This interface was referenced by `ApiContract`'s JSON-Schema
 * via the `definition` "TurnFinished".
 */
export interface TurnFinished {
  /**
   * Position of the event in its turn's stream: strictly increasing, not contiguous. Sent as the SSE event id; send the last one received as Last-Event-ID to reattach.
   */
  seq: number;
  type: "turn_finished";
}
/**
 * A held thread as of its last finished turn (``GET /api/v1/chat/threads/{id}``).
 *
 * This interface was referenced by `ApiContract`'s JSON-Schema
 * via the `definition` "ThreadSnapshot".
 */
export interface ThreadSnapshot {
  confirmation: ConfirmationPrompt | null;
  interrupted: TurnInterruption | null;
  messages: ThreadMessage[];
  running_turn: RunningTurn | null;
  thread_id: string;
  usage: UsageTotals;
  workspace: WorkspaceState;
}
/**
 * An open request for missing values: what the user is asked, not yet answered.
 *
 * This interface was referenced by `ApiContract`'s JSON-Schema
 * via the `definition` "ConfirmationPrompt".
 */
export interface ConfirmationPrompt {
  entries: MissingValue[];
  request_id: string;
}
/**
 * Why a turn stopped before its answer, whether it can be resumed, and what to do.
 *
 * This interface was referenced by `ApiContract`'s JSON-Schema
 * via the `definition` "TurnInterruption".
 */
export interface TurnInterruption {
  message: string;
  reason:
    | "out_of_credits"
    | "rate_limited"
    | "bad_key"
    | "provider_down"
    | "step_limit"
    | "worker_lost"
    | "cancelled"
    | "time_limit";
  resumable: boolean;
}
/**
 * One user or assistant message of a thread (text only, no tool calls or results).
 *
 * This interface was referenced by `ApiContract`'s JSON-Schema
 * via the `definition` "ThreadMessage".
 */
export interface ThreadMessage {
  role: "user" | "assistant";
  text: string;
}
/**
 * A queued or running turn of the thread, so a reloaded page can show it and reattach.
 *
 * This interface was referenced by `ApiContract`'s JSON-Schema
 * via the `definition` "RunningTurn".
 */
export interface RunningTurn {
  question: string | null;
  resumed: boolean;
  turn_id: string;
}
/**
 * ``POST /api/v1/auth/verify``: the token from the emailed link (sent in the body).
 *
 * This interface was referenced by `ApiContract`'s JSON-Schema
 * via the `definition` "TokenRequest".
 */
export interface TokenRequest {
  token: string;
}
/**
 * A box on the map, decimal degrees (WGS84, west negative).
 *
 * This interface was referenced by `ApiContract`'s JSON-Schema
 * via the `definition` "InitialView".
 */
export interface InitialView1 {
  east: number;
  north: number;
  south: number;
  west: number;
}
