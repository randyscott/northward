import { useEffect } from "react";
import { NavLink, Outlet, useMatch, useNavigate } from "react-router-dom";

import { useProfile, useProfiles } from "../api/hooks";

const STORAGE_KEY = "northward.profile";

export function rememberedProfile(): string | null {
  try {
    return localStorage.getItem(STORAGE_KEY);
  } catch {
    return null;
  }
}

function remember(profile: string) {
  try {
    localStorage.setItem(STORAGE_KEY, profile);
  } catch {
    // private mode: nothing to remember
  }
}

/** The profile the page is about: the one in the URL, else the last one opened (the sidebar falls back to the
first profile). */
export function useCurrentProfile(): string | null {
  const match = useMatch("/profiles/:profile/*");
  return match?.params.profile ?? rememberedProfile();
}

function Link({ to, children, end }: { to: string; children: React.ReactNode; end?: boolean }) {
  return (
    <NavLink to={to} end={end} className={({ isActive }) => `nav-link${isActive ? " active" : ""}`}>
      {children}
    </NavLink>
  );
}

export function Layout() {
  const navigate = useNavigate();
  const profiles = useProfiles();
  const current = useCurrentProfile();
  const names = profiles.data?.map((p) => p.name) ?? [];
  const profile = current && names.includes(current) ? current : (names[0] ?? null);
  const detail = useProfile(profile ?? undefined);

  useEffect(() => {
    if (profile) remember(profile);
  }, [profile]);

  return (
    <div className="app">
      <nav className="sidebar" aria-label="Main">
        <a className="brand" href="/">
          <svg width="22" height="22" viewBox="0 0 32 32" aria-hidden>
            <rect width="32" height="32" rx="7" fill="var(--accent)" />
            <path d="M16 5 L21.5 22 L16 18.5 L10.5 22 Z" fill="white" />
          </svg>
          Northward
        </a>

        <label className="field" style={{ padding: "0 8px" }}>
          Profile
          <select
            aria-label="Profile"
            value={profile ?? ""}
            onChange={(event) => event.target.value && navigate(`/profiles/${event.target.value}`)}
          >
            {!profile && <option value="">Choose a profile…</option>}
            {names.map((name) => (
              <option key={name} value={name}>
                {name}
              </option>
            ))}
          </select>
        </label>

        {profile && (
          <div className="nav-section">
            <Link to={`/profiles/${profile}`} end>
              Overview
            </Link>
            <Link to={`/profiles/${profile}/balances`}>Balances</Link>
            <div className="nav-heading" style={{ marginTop: 12 }}>
              Scenarios
            </div>
            {detail.data?.scenarios.map((scenario) => (
              <Link key={scenario} to={`/profiles/${profile}/scenarios/${scenario}`}>
                {scenario}
              </Link>
            ))}
          </div>
        )}

        <div className="nav-section">
          <div className="nav-heading">Analysis</div>
          <Link to="/runs">Run history</Link>
          <Link to="/compare">Compare scenarios</Link>
        </div>

        <div className="nav-section">
          <div className="nav-heading">Setup</div>
          <Link to="/profiles" end>
            All profiles
          </Link>
          <Link to="/rules">Rules</Link>
        </div>
      </nav>
      <main className="main">
        <Outlet />
      </main>
    </div>
  );
}
