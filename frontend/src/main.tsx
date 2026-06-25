import React from 'react'
import ReactDOM from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import App from './App'
import { ToastProvider } from './components/ui/toast'
import { AppDataProvider } from './store/AppDataContext'
import { CostingsProvider } from './store/CostingsContext'
import { MaterialsProvider } from './store/MaterialsContext'
import { PlanningProvider } from './store/PlanningContext'
// WO v4.36b.4 — self-hosted Inter. Was loaded from Google Fonts via a <link> in index.html, which the
// strict CSP (style-src/font-src 'self') blocked → the app silently fell back to system-ui, and
// html2canvas spammed CSP errors re-cloning the link. @fontsource bundles the woff2 so Vite serves it
// same-origin under font-src 'self'. Family is 'Inter' (matches index.css + tailwind).
// LATIN + LATIN-EXT ONLY (en-ZA + Afrikaans): @fontsource's default `<weight>.css` pulls all 7 unicode
// subsets (cyrillic/greek/vietnamese/…) = 28 @font-face rules. The v4.38 feedback widget's html2canvas
// FETCHES + inlines every @font-face on each screenshot capture, and 28 same-origin fetches timed out
// its journey on CI ubuntu (the old Google-Fonts link was CSP-blocked → 0 fetches → fast). The 2 subsets
// we actually render keep that to 8. Weights 400/500/600/700 match the old css2 request.
import '@fontsource/inter/latin-400.css'
import '@fontsource/inter/latin-ext-400.css'
import '@fontsource/inter/latin-500.css'
import '@fontsource/inter/latin-ext-500.css'
import '@fontsource/inter/latin-600.css'
import '@fontsource/inter/latin-ext-600.css'
import '@fontsource/inter/latin-700.css'
import '@fontsource/inter/latin-ext-700.css'
import './index.css'

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <BrowserRouter basename={import.meta.env.BASE_URL.replace(/\/$/, '')}>
      <ToastProvider>
        <AppDataProvider>
          <CostingsProvider>
            <MaterialsProvider>
              <PlanningProvider>
                <App />
              </PlanningProvider>
            </MaterialsProvider>
          </CostingsProvider>
        </AppDataProvider>
      </ToastProvider>
    </BrowserRouter>
  </React.StrictMode>,
)
