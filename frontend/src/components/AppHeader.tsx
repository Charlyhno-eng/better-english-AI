import { Link, NavLink } from 'react-router';

export function AppHeader() {
  return <header className="app-header">
    <Link className="wordmark" to="/">
      <img className="wordmark-logo" src="/better-english-AI-logo.png" alt="" />
      <span className="wordmark-name">Better English <span>AI</span></span>
    </Link>
    <nav className="app-nav" aria-label="Main navigation">
      <NavLink to="/" end>Conversation</NavLink>
      <NavLink to="/writing">Writing practice</NavLink>
      <NavLink to="/pronunciation">Pronunciation practice</NavLink>
      <NavLink to="/setup">Setup</NavLink>
    </nav>
  </header>;
}
