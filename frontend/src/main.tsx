import React from 'react'
import ReactDOM from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import App from './App'
import { ToastProvider } from './components/ui/toast'
import { AppDataProvider } from './store/AppDataContext'
import { CostingsProvider } from './store/CostingsContext'
import { MaterialsProvider } from './store/MaterialsContext'
import './index.css'

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <BrowserRouter basename={import.meta.env.BASE_URL.replace(/\/$/, '')}>
      <ToastProvider>
        <AppDataProvider>
          <CostingsProvider>
            <MaterialsProvider>
              <App />
            </MaterialsProvider>
          </CostingsProvider>
        </AppDataProvider>
      </ToastProvider>
    </BrowserRouter>
  </React.StrictMode>,
)
