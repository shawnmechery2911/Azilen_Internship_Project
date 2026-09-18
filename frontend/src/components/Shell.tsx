import { useState, type ReactNode } from "react";
import {
  Code2,
  GitBranch,
  Inbox,
  Layers3,
  Menu,
  Settings2,
  Zap,
} from "lucide-react";

const navItems = [
  ["Overview", Layers3],
  ["Mappings", GitBranch],
  ["Exceptions", Inbox],
  ["Onboard", Code2],
] as const;

export function Shell({
  activeNav,
  onNavigate,
  children,
  apiUp = true,
}: {
  activeNav: string;
  onNavigate: (screen: string) => void;
  children: ReactNode;
  apiUp?: boolean;
}) {
  const [open, setOpen] = useState(false);
  return (
    <div className="app-shell">
      <aside className={`sidebar ${open ? "sidebar-open" : ""}`}>
        <div className="brand-lockup">
          <div className="brand-mark">
            <Zap size={17} fill="currentColor" />
          </div>
          <div>
            <strong>PIPELINE</strong>
            <span>mapping control</span>
          </div>
        </div>
        <div className="workspace-switcher">
          <div className="workspace-dot">P</div>
          <div>
            <span>Workspace</span>
            <strong>{window.location.host}</strong>
          </div>
        </div>
        <nav className="main-nav" aria-label="Primary navigation">
          <span className="nav-label">Monitor</span>
          {navItems.map(([label, Icon]) => (
            <button
              key={label}
              className={`nav-item ${activeNav === label ? "nav-active" : ""}`}
              onClick={() => {
                onNavigate(label);
                setOpen(false);
              }}
            >
              <Icon size={17} />
              <span>{label}</span>
            </button>
          ))}
          <span className="nav-label nav-label-spaced">Configure</span>
          <button
            className={`nav-item ${activeNav === "Validation" ? "nav-active" : ""}`}
            onClick={() => onNavigate("Validation")}
          >
            <Settings2 size={17} />
            <span>Validation</span>
          </button>
        </nav>
        <div className="sidebar-footer">
          <div className="health-line">
            <span className={apiUp ? "pulse-dot" : "pulse-dot dot-down"} />
            {apiUp ? "API reachable" : "API unreachable"}
          </div>
          <div className="user-card">
            <div className="avatar">SM</div>
            <div>
              <strong>Shawn Mechery</strong>
              <span>Administrator</span>
            </div>
          </div>
        </div>
      </aside>
      <main className="main-content">
        <header className="topbar">
          <button
            className="mobile-menu"
            onClick={() => setOpen(!open)}
            aria-label="Toggle navigation"
          >
            <Menu size={20} />
          </button>
          <div className="breadcrumbs">
            <span>Operations</span>
            <span>/</span>
            <strong>{activeNav}</strong>
          </div>
          <div className={`env-chip ${apiUp ? "" : "env-down"}`}>
            <span className={apiUp ? "pulse-dot" : "pulse-dot dot-down"} />
            {apiUp ? "Live" : "Offline"}
          </div>
        </header>
        {children}
      </main>
    </div>
  );
}
