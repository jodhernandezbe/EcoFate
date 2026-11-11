// Names the features use, re-exported from the generated contract (src/types/api.ts).
export type {
  AssistantMessage,
  ChatRequest,
  ConfirmationAnswers,
  ConfirmationPrompt,
  ConfirmationRequested,
  EntryAnswer,
  MissingValue,
  ClientConfig,
  Chemical,
  Dose,
  ErrorEvent,
  Extreme,
  Extremum,
  Facility,
  GuardrailPivotResponse,
  LayoutConfig,
  KeysStatusResponse,
  QuotaExhausted,
  QuotaStatus,
  KeyStatusResponse,
  KeyUpdatePayload,
  Meteorology,
  OccupationalExposure,
  OperationalProfile,
  ReadAcross,
  Receptors,
  RunningTurn,
  RiskSummary,
  ScenarioDriver,
  ScenarioFactor,
  ScenarioReceptor,
  ScopeDecision,
  Screening,
  SessionDetailResponse,
  SessionStep,
  SessionsResponse,
  SessionSummary,
  SessionTurn,
  SignInResponse,
  StreamEventSchema as StreamEvent,
  ThreadMessage,
  ThreadSnapshot,
  Token,
  Stack,
  ToolStatus,
  TurnFinished,
  TurnInterrupted,
  TurnInterruption,
  TurnStarted,
  TurnStatus,
  UserInfo,
  Usage,
  UsageTotals,
  VentilationTier,
  WorkerExtremum,
  WorkerRiskSummary,
  WorkspaceState,
  WorkspaceUpdate,
  WorstCaseScenario,
} from "./api";

import type { Extremum, KeysStatusResponse, OccupationalExposure } from "./api";

/** The data services an installation may provide (their keys belong to the operator). */
export type ServiceName = keyof KeysStatusResponse["services"];

/** Tier of the worker screening: how the 8-hour average, hazard quotient and cancer risk compare. */
export type OccupationalTier = NonNullable<OccupationalExposure["risk_tier"]>;

/** Risk position against the thresholds of concern. */
export type Status = Extremum["status"];
