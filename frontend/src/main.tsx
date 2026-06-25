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
// same-origin under font-src 'self'. Weights match the old css2 request (400/500/600/700); family is 'Inter'.
import '@fontsource/inter/400.css'
import '@fontsource/inter/500.css'
import '@fontsource/inter/600.css'
import '@fontsource/inter/700.css'
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
