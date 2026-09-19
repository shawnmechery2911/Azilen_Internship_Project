import { useEffect, useState, type ReactNode } from "react";
import {
  Code2,
  Inbox,
  Layers3,
  Menu,
  Moon,
  Settings2,
  Sun,
  Zap,
} from "lucide-react";

const navItems = [
  ["Overview", Layers3],
  ["Exceptions", Inbox],
  ["Onboard", Code2],
] as const;

type Theme = "light" | "dark";

/** Light is the default; a previous choice wins over it. */
function storedTheme(): Theme {
  try {
    return localStorage.getItem("pipeline-theme") === "dark" ? "dark" : "light";
  } catch {
    return "light";
  }
}

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
  const [theme, setTheme] = useState<Theme>(storedTheme);
  useEffect(() => {
    document.documentElement.setAttribute("data-theme", theme);
    try {
      localStorage.setItem("pipeline-theme", theme);
    } catch {
      // a blocked storage write should never stop the theme applying
    }
  }, [theme]);
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
        <nav className="main-nav" aria-label="Primary navigation">
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
          <div className="topbar-actions">
            <button
              className="icon-button"
              onClick={() => setTheme(theme === "dark" ? "light" : "dark")}
              aria-label={
                theme === "dark" ? "Switch to light theme" : "Switch to dark theme"
              }
              title={theme === "dark" ? "Light theme" : "Dark theme"}
            >
              {theme === "dark" ? <Sun size={17} /> : <Moon size={17} />}
            </button>
            <div className={`env-chip ${apiUp ? "" : "env-down"}`}>
              <span className={apiUp ? "pulse-dot" : "pulse-dot dot-down"} />
              {apiUp ? "Live" : "Offline"}
            </div>
          </div>
        </header>
        {children}
      </main>
    </div>
  );
}
