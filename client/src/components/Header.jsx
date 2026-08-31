import { useTheme } from "../context/ThemeContext";

function SunIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <circle cx="12" cy="12" r="4" />
      <path d="M12 2v2.5" />
      <path d="M12 19.5V22" />
      <path d="M4.9 4.9 6.7 6.7" />
      <path d="M17.3 17.3 19.1 19.1" />
      <path d="M2 12h2.5" />
      <path d="M19.5 12H22" />
      <path d="M4.9 19.1 6.7 17.3" />
      <path d="M17.3 6.7 19.1 4.9" />
    </svg>
  );
}

function MoonIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M20.4 14.2a8.8 8.8 0 1 1-10.6-10.6 7.2 7.2 0 1 0 10.6 10.6Z" />
    </svg>
  );
}

function Header() {
  const { isDarkTheme, toggleTheme } = useTheme();
  const nextThemeLabel = isDarkTheme ? "light" : "dark";

  return (
    <header className="topbar">
      <div className="title-group">
        <p className="eyebrow">Accessibility Audit</p>
        <h1>Issues Dashboard</h1>
        <p className="subtitle">Aggregated view of issues detected by AX Tester agent</p>
      </div>
      <button
        type="button"
        className="theme-toggle"
        onClick={toggleTheme}
        aria-label={`Switch to ${nextThemeLabel} theme`}
        title={`Switch to ${nextThemeLabel} theme`}
      >
        {isDarkTheme ? <SunIcon /> : <MoonIcon />}
      </button>
    </header>
  );
}

export default Header;
