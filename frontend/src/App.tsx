import { useState } from "react";

import { LeftNavRail } from "./components/layout/LeftNavRail";
import { SplitWorkspace } from "./components/layout/SplitWorkspace";
import { ConfirmDialog } from "./components/ui/ConfirmDialog";
import { AccountDrawer, AccountScreens } from "./features/auth";
import { ChatDock } from "./features/chat/ChatDock";
import { ExposureChainTab, useFocusedFacility } from "./features/exposure-chain";
import { MapPanel } from "./features/map/MapPanel";
import { MonitoringView } from "./features/monitoring/MonitoringView";
import { OverviewPanel } from "./features/overview/OverviewPanel";
import { SettingsDrawer } from "./features/settings/SettingsDrawer";
import { useAgentStream } from "./hooks/useAgentStream";
import { useClientConfig } from "./hooks/useClientConfig";
import { useKeyStatus } from "./hooks/useKeyStatus";
import { useQuota } from "./hooks/useQuota";
import { useReportDownload } from "./hooks/useReportDownload";
import { useSession } from "./hooks/useSession";
import { useWorkspaceStore } from "./hooks/useWorkspaceStore";
import type { UserInfo, WorkspaceState } from "./types/workspace";

// Until the server sends its display settings the ribbon shows these many digits.
const DEFAULT_DIGITS = 2;
const DEFAULT_BREAKPOINT_PX = 900;
const REPLY_IN_PROGRESS = "a reply is in progress";
const ALREADY_EMPTY = "the workspace is already empty";
const NO_FINDINGS = "there are no findings yet";

/** A chemical result or a facility: what the server needs before it can write a report. */
const hasFindings = (state: WorkspaceState): boolean =>
  state.chemical.cas_number !== null || state.facilities.length > 0;

interface WorkspaceProps {
  user: UserInfo;
  onSignOut: () => void;
  /** The session ended on the server (signed out everywhere, or the account was deleted). */
  onGone: () => void;
}

/** The signed-in page. It is mounted only while someone is signed in, and per user. */
function Workspace({ user, onSignOut, onGone }: WorkspaceProps) {
  const store = useWorkspaceStore();
  const chat = useAgentStream({
    onWorkspace: store.apply,
    onReplace: (state) => (state ? store.replace(state) : store.clear()),
  });
  const quota = useQuota(chat.busy, chat.refusal);
  const report = useReportDownload();
  const key = useKeyStatus();
  const config = useClientConfig();
  const focus = useFocusedFacility(store.workspace, store.epoch);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [accountOpen, setAccountOpen] = useState(false);
  const [confirmingClear, setConfirmingClear] = useState(false);
  const [view, setView] = useState<"workspace" | "monitoring">("workspace");
  const digits = config?.significant_digits ?? DEFAULT_DIGITS;
  const findings = hasFindings(store.workspace);
  const empty = chat.messages.length === 0 && !findings;
  const clearBlocked = chat.busy ? REPLY_IN_PROGRESS : empty ? ALREADY_EMPTY : null;
  const reportBlocked = chat.busy ? REPLY_IN_PROGRESS : findings ? null : NO_FINDINGS;
  const clear = () => {
    setConfirmingClear(false);
    void chat.clearWorkspace().then((cleared) => {
      if (cleared) report.dismiss();
    });
  };

  return (
    <>
      <SplitWorkspace
        layout={config?.layout}
        narrowBreakpointPx={config?.narrow_breakpoint_px ?? DEFAULT_BREAKPOINT_PX}
        rail={({ collapsed, toggle, exitFullscreen }) => (
          <LeftNavRail
            collapsed={collapsed}
            onToggle={toggle}
            view={view}
            onWorkspace={() => {
              setView("workspace");
              setSettingsOpen(false);
              setAccountOpen(false);
              setConfirmingClear(false);
              exitFullscreen();
            }}
            onMonitoring={() => {
              setView("monitoring");
              setSettingsOpen(false);
              setAccountOpen(false);
              setConfirmingClear(false);
              exitFullscreen();
            }}
            onClear={() => setConfirmingClear(true)}
            clearBlocked={clearBlocked}
            onReport={() => void report.download(chat.threadId)}
            reportBlocked={reportBlocked}
            reporting={report.busy}
            reportError={report.error}
            onOpenSettings={() => setSettingsOpen(true)}
            email={user.email}
            admin={user.role === "admin"}
            onAccount={() => setAccountOpen(true)}
          />
        )}
        covering={view === "monitoring" && user.role === "admin" ? <MonitoringView /> : undefined}
        overview={
          <OverviewPanel
            workspace={store.workspace}
            digits={digits}
            bands={config?.bands}
            chain={<ExposureChainTab facility={focus.facility} workspace={store.workspace} digits={digits} onPick={focus.onPin} />}
          />
        }
        map={<MapPanel workspace={store.workspace} viewEpoch={store.epoch} digits={digits} map={config?.map} onPin={focus.onPin} />}
        chat={({ collapse }) => (
          <ChatDock
            messages={chat.messages}
            busy={chat.busy}
            hasKey={key.statuses?.openai.configured === true}
            model={config?.model}
            suggestions={config?.suggestions}
            usage={chat.usage}
            quota={quota}
            refusedText={chat.refusal?.text}
            notice={chat.notice}
            confirmation={chat.confirmation}
            onSend={(text) => void chat.send(text)}
            onClear={() => setConfirmingClear(true)}
            onAnswer={(answers, summary) => {
              if (chat.confirmation) void chat.answer(answers, summary, chat.confirmation);
            }}
            onResume={() => void chat.resume()}
            status={chat.status}
            stopping={chat.stopping}
            onStop={() => void chat.stop()}
            onOpenSettings={() => setSettingsOpen(true)}
            onCollapse={collapse}
          />
        )}
      />
      <AccountDrawer
        open={accountOpen}
        user={user}
        onClose={() => setAccountOpen(false)}
        onSignOut={onSignOut}
        onGone={onGone}
      />
      <SettingsDrawer
        open={settingsOpen}
        statuses={key.statuses}
        busy={key.busy}
        outcome={key.outcome}
        loadError={key.loadError}
        onSave={key.save}
        onClear={key.clear}
        onClose={() => setSettingsOpen(false)}
      />
      <ConfirmDialog
        open={confirmingClear && clearBlocked === null}
        title="Clear this workspace?"
        confirmLabel="Clear"
        destructive
        onConfirm={clear}
        onCancel={() => setConfirmingClear(false)}
      >
        <p>This discards the current analysis. It cannot be recovered.</p>
        <ul className="list-disc pl-5">
          <li>The conversation with the copilot</li>
          <li>Overview figures and risk charts</li>
          <li>Facilities and buffers on the map</li>
          <li>Session usage</li>
        </ul>
        <p>Generate a report first to keep the findings.</p>
      </ConfirmDialog>
    </>
  );
}

/**
 * Who is using the page decides what it shows: the account screens while nobody is signed in
 * (the workspace is not mounted, so nothing of a previous user can remain on screen), the
 * workspace once someone is, keyed by user.
 */
export function App() {
  const session = useSession();
  const { state } = session;
  if (state.status === "signed-in") {
    return <Workspace key={state.user.id} user={state.user} onSignOut={() => void session.signOut()} onGone={session.signedOut} />;
  }
  if (state.status === "signed-out") return <AccountScreens onSignedIn={session.signedIn} />;
  return (
    <main className="grid min-h-dvh place-items-center bg-bg p-4">
      {state.status === "loading" ? (
        <p role="status" className="text-sm text-fg2">Loading…</p>
      ) : (
        <div className="flex flex-col items-start gap-2">
          <p role="alert" className="text-sm text-bad">{state.message}</p>
          <button type="button" onClick={() => void session.retry()} className="spring rounded-lg bg-accent px-3 py-1.5 text-sm font-medium text-accent-fg">
            Retry
          </button>
        </div>
      )}
    </main>
  );
}
