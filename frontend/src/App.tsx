import { useState } from "react";

import { LeftNavRail } from "./components/layout/LeftNavRail";
import { SplitWorkspace } from "./components/layout/SplitWorkspace";
import { ConfirmDialog } from "./components/ui/ConfirmDialog";
import { ChatDock } from "./features/chat/ChatDock";
import { ExposureChainTab, useFocusedFacility } from "./features/exposure-chain";
import { MapPanel } from "./features/map/MapPanel";
import { MonitoringView } from "./features/monitoring/MonitoringView";
import { OverviewPanel } from "./features/overview/OverviewPanel";
import { SettingsDrawer } from "./features/settings/SettingsDrawer";
import { useAgentStream } from "./hooks/useAgentStream";
import { useClientConfig } from "./hooks/useClientConfig";
import { useKeyStatus } from "./hooks/useKeyStatus";
import { useReportDownload } from "./hooks/useReportDownload";
import { useWorkspaceStore } from "./hooks/useWorkspaceStore";
import type { WorkspaceState } from "./types/workspace";

// Until the server sends its display settings the ribbon shows these many digits.
const DEFAULT_DIGITS = 2;
const DEFAULT_BREAKPOINT_PX = 900;
const REPLY_IN_PROGRESS = "a reply is in progress";
const ALREADY_EMPTY = "the workspace is already empty";
const NO_FINDINGS = "there are no findings yet";

/** A chemical result or a facility: what the server needs before it can write a report. */
const hasFindings = (state: WorkspaceState): boolean =>
  state.chemical.cas_number !== null || state.facilities.length > 0;

export function App() {
  const store = useWorkspaceStore();
  const chat = useAgentStream({
    onWorkspace: store.apply,
    onReplace: (state) => (state ? store.replace(state) : store.clear()),
  });
  const report = useReportDownload();
  const key = useKeyStatus();
  const config = useClientConfig();
  const focus = useFocusedFacility(store.workspace, store.epoch);
  const [settingsOpen, setSettingsOpen] = useState(false);
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
              setConfirmingClear(false);
              exitFullscreen();
            }}
            onMonitoring={() => {
              setView("monitoring");
              setSettingsOpen(false);
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
          />
        )}
        covering={view === "monitoring" ? <MonitoringView /> : undefined}
        overview={
          <OverviewPanel
            workspace={store.workspace}
            digits={digits}
            thresholds={config?.thresholds}
            workerThresholds={config?.worker_thresholds}
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
            notice={chat.notice}
            confirmation={chat.confirmation}
            onSend={(text) => void chat.send(text)}
            onClear={() => setConfirmingClear(true)}
            onAnswer={(answers, summary) => {
              if (chat.confirmation) void chat.answer(answers, summary, chat.confirmation);
            }}
            onResume={() => void chat.resume()}
            onOpenSettings={() => setSettingsOpen(true)}
            onCollapse={collapse}
          />
        )}
      />
      <SettingsDrawer
        open={settingsOpen}
        statuses={key.statuses}
        busy={key.busy}
        outcomes={key.outcomes}
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
