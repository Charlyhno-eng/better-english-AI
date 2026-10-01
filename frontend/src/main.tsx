import React from 'react';
import ReactDOM from 'react-dom/client';
import { BrowserRouter, Route, Routes } from 'react-router';
import { HomePage } from './pages/HomePage';
import { PronunciationPage } from './pages/PronunciationPage';
import { WritingPage } from './pages/WritingPage';
import { SetupPage } from './pages/SetupPage';
import './styles.css';

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <div className="ambient-background" aria-hidden="true"><span /><span /><span /></div>
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<HomePage />} />
        <Route path="/setup" element={<SetupPage />} />
        <Route path="/writing" element={<WritingPage />} />
        <Route path="/pronunciation" element={<PronunciationPage />} />
        <Route path="*" element={<main><h1>Page not found</h1><a href="/">Go home</a></main>} />
      </Routes>
    </BrowserRouter>
  </React.StrictMode>,
);
