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
  KeyStatusResponse,
  KeyUpdatePayload,
  Meteorology,
  OccupationalExposure,
  OperationalProfile,
  ReadAcross,
  Receptors,
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

/** The keys the interface stores: the model key and the two service keys the tools use. */
export type KeyName = keyof KeysStatusResponse;

/** Tier of the worker screening: how the 8-hour average, hazard quotient and cancer risk compare. */
export type OccupationalTier = NonNullable<OccupationalExposure["risk_tier"]>;

/** Risk position against the thresholds of concern. */
export type Status = Extremum["status"];
