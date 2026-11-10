import {
  Activity,
  CircleAlert,
  FileDown,
  LayoutDashboard,
  LoaderCircle,
  PanelLeftClose,
  PanelLeftOpen,
  Settings,
  Trash2,
  UserRound,
} from "lucide-react";
import type { ElementType } from "react";

import { BrandLogo, BrandMark } from "../ui/BrandLogo";

interface LeftNavRailProps {
  collapsed: boolean;
  /** Absent where the rail cannot expand (a narrow window): the toggle is then not shown. */
  onToggle?: (() => void) | undefined;
  /** The view on screen; its entry is marked as the current page. */
  view: "workspace" | "monitoring";
  /** Return to the workspace: leave fullscreen and close whatever is open over it. */
  onWorkspace: () => void;
  /** Show the Monitoring view: leave fullscreen and close whatever is open over the workspace. */
  onMonitoring: () => void;
  /** Ask to clear the workspace (the caller confirms first). */
  onClear: () => void;
  /** Why "Clear workspace" is unavailable now; null when it can be used. */
  clearBlocked: string | null;
  onReport: () => void;
  /** Why "Generate report" is unavailable now; null when it can be used. */
  reportBlocked: string | null;
  /** A report is being generated. */
  reporting: boolean;
  /** Why the last report failed; null when it did not. */
  reportError?: string | null | undefined;
  onOpenSettings: () => void;
  /** The signed-in user's email, shown on the Account entry. */
  email: string;
  /** Administrators see the Monitoring entry; nobody else does. */
  admin: boolean;
  /** Open the account sheet (sign out, password, delete). */
  onAccount: () => void;
}

interface ItemProps {
  icon: ElementType;
  label: string;
  collapsed: boolean;
  onClick?: (() => void) | undefined;
  page?: boolean | undefined;
  /** Why the entry is disabled; the entry is enabled when absent. */
  blocked?: string | null | undefined;
  busy?: boolean | undefined;
  badge?: string | undefined;
  tone?: "danger" | undefined;
}

/** One rail entry: icon and label when expanded, the icon alone (named and titled) when collapsed. */
function Item({ icon: Icon, label, collapsed, onClick, page, blocked, busy, badge, tone }: ItemProps) {
  const disabled = Boolean(blocked) || busy;
  const title = blocked ? `${label}: ${blocked}` : collapsed ? label : undefined;
  const Shown = busy ? LoaderCircle : Icon;
  return (
    <button
      type="button"
      aria-label={collapsed ? label : undefined}
      aria-description={blocked ?? undefined}
      title={title}
      aria-current={page ? "page" : undefined}
      aria-busy={busy || undefined}
      disabled={disabled}
      onClick={onClick}
      className={`spring relative flex h-9 w-full items-center gap-3 rounded-xl px-[11px] text-left text-sm transition hover:bg-hairline disabled:opacity-40 disabled:hover:bg-transparent ${
        page ? "bg-hairline font-semibold" : `text-fg2 ${tone === "danger" ? "hover:text-bad" : "hover:text-fg"}`
      }`}
    >
      {page ? <span aria-hidden="true" className="absolute inset-y-2 left-0 w-[3px] rounded-full bg-accent" /> : null}
      <Shown size={18} aria-hidden="true" className={`shrink-0 ${busy ? "motion-safe:animate-spin" : ""}`} />
      {collapsed ? null : <span className="min-w-0 flex-1 truncate">{label}</span>}
      {collapsed || !badge ? null : (
        <span className="shrink-0 rounded-full bg-hairline px-1.5 py-0.5 text-[11px] font-medium text-fg2">
          {badge}
        </span>
      )}
    </button>
  );
}

/** Why the last report failed: a line of text, or a titled icon on the collapsed rail. */
function ReportError({ text, collapsed }: { text: string; collapsed: boolean }) {
  if (!collapsed) {
    return (
      <p role="alert" className="px-3 text-xs text-bad">
        {text}
      </p>
    );
  }
  return (
    <p role="alert" title={text} className="grid h-6 place-items-center text-bad">
      <CircleAlert size={14} aria-hidden="true" />
      <span className="sr-only">{text}</span>
    </p>
  );
}

/**
 * The left rail: brand and toggle; Workspace, Clear workspace, Generate report, Monitoring
 * (administrators only); Account (with the email) and Settings.
 */
export function LeftNavRail({
  collapsed,
  onToggle,
  view,
  onWorkspace,
  onMonitoring,
  onClear,
  clearBlocked,
  onReport,
  reportBlocked,
  reporting,
  reportError,
  onOpenSettings,
  email,
  admin,
  onAccount,
}: LeftNavRailProps) {
  const Toggle = collapsed ? PanelLeftOpen : PanelLeftClose;
  return (
    <div className="flex h-full min-w-0 flex-col gap-1 overflow-hidden bg-surface p-2">
      <div className={`flex ${collapsed ? "flex-col items-center" : "items-center"} gap-1`}>
        {collapsed ? (
          <span role="img" aria-label="EcoFate" title="EcoFate" className="group grid size-9 place-items-center">
            <BrandMark size={32} />
          </span>
        ) : (
          <span className="min-w-0 flex-1 pl-0.5">
            <BrandLogo size={32} label="Exposure & Risk Studio" />
          </span>
        )}
        {onToggle ? (
          <button
            type="button"
            aria-label={collapsed ? "Expand navigation" : "Collapse navigation"}
            aria-expanded={!collapsed}
            onClick={onToggle}
            className="spring grid size-9 shrink-0 place-items-center rounded-xl text-fg2 transition hover:bg-hairline hover:text-fg"
          >
            <Toggle size={18} aria-hidden="true" />
          </button>
        ) : null}
      </div>
      <div className="mt-2 flex min-h-0 flex-1 flex-col gap-1">
        {collapsed ? (
          <h2 className="sr-only">Analysis area</h2>
        ) : (
          <h2 className="px-3 text-xs font-semibold uppercase tracking-wider text-fg2">Analysis area</h2>
        )}
        <Item
          icon={LayoutDashboard}
          label="Workspace"
          collapsed={collapsed}
          onClick={onWorkspace}
          page={view === "workspace"}
        />
        <Item
          icon={Trash2}
          label="Clear workspace"
          collapsed={collapsed}
          onClick={onClear}
          blocked={clearBlocked}
          tone="danger"
        />
        <Item
          icon={FileDown}
          label={reporting ? "Generating report…" : "Generate report"}
          collapsed={collapsed}
          onClick={onReport}
          blocked={reportBlocked}
          busy={reporting}
        />
        {reportError ? <ReportError text={reportError} collapsed={collapsed} /> : null}
        {admin ? (
          <Item
            icon={Activity}
            label="Monitoring"
            collapsed={collapsed}
            onClick={onMonitoring}
            page={view === "monitoring"}
          />
        ) : null}
      </div>
      <Item icon={UserRound} label="Account" collapsed={collapsed} onClick={onAccount} />
      {collapsed ? null : (
        <p title={email} className="truncate px-3 pb-1 text-xs text-fg2">
          {email}
        </p>
      )}
      <Item icon={Settings} label="Settings" collapsed={collapsed} onClick={onOpenSettings} />
    </div>
  );
}
