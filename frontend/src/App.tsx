import { Routes, Route, Navigate } from 'react-router-dom'
import { Layout } from './components/layout/Layout'
import { Configurator } from './screens/Configurator/Configurator'
import { PlanningBoard } from './screens/Planning/PlanningBoard'
import { VacuumTablet } from './screens/ShopFloorTablet/VacuumTablet'
import { KanbanTV } from './screens/KanbanTV/KanbanTV'
import { ProductionDashboard } from './screens/Production/ProductionDashboard'
import { ManagementDashboard } from './screens/Management/ManagementDashboard'
import { QcFinalCheck } from './screens/QC/QcFinalCheck'
import { CostingsDashboard } from './screens/Costings/CostingsDashboard'
import { CostingDetail } from './screens/Costings/CostingDetail'
import { LiveCalculator } from './screens/Costings/LiveCalculator'
import { MaterialsDashboard } from './screens/Materials/MaterialsDashboard'
import { POSuggestionQueue } from './screens/Materials/POSuggestionQueue'
import { StoresReconciliation } from './screens/Materials/StoresReconciliation'
import { ChassisList } from './screens/Chassis/ChassisList'
import { ChassisDetail } from './screens/Chassis/ChassisDetail'
import { AdminModule } from './screens/Admin/AdminModule'
import { PrejobSignoffPage } from './screens/Prejob/PrejobSignoffPage'

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<Navigate to="/production" replace />} />
      {/* Costings (Addendum v1.2.1) — Configurator split into dashboard + wizard */}
      <Route path="/costings" element={<Layout><CostingsDashboard /></Layout>} />
      {/* + New Costing now embeds the REAL calculator at localhost:8000/calculator */}
      <Route path="/costings/new" element={<Layout><LiveCalculator /></Layout>} />
      {/* Original mocked wizard preserved for offline demos (rep-grouped customer page, fan-out modal) */}
      <Route path="/costings/new-mock" element={<Layout><Configurator /></Layout>} />
      <Route path="/costings/:quote" element={<Layout><CostingDetail /></Layout>} />
      {/* Legacy redirect — old /configurator path */}
      <Route path="/configurator" element={<Navigate to="/costings/new" replace />} />
      <Route path="/planning" element={<Layout><PlanningBoard /></Layout>} />
      {/* Work Order v4.11 — Materials, Buying & Stores. Weekly Forecast is a tab
          inside the dashboard at /materials?tab=forecast (not a separate route). */}
      <Route path="/materials" element={<Layout><MaterialsDashboard /></Layout>} />
      <Route path="/materials/suggestions" element={<Layout><POSuggestionQueue /></Layout>} />
      <Route path="/stores/reconciliation" element={<Layout><StoresReconciliation /></Layout>} />
      {/* WO v4.28 — Chassis lifecycle module */}
      <Route path="/chassis" element={<Layout><ChassisList /></Layout>} />
      <Route path="/chassis/:id" element={<Layout><ChassisDetail /></Layout>} />
      <Route path="/tablet/vacuum" element={<Layout><VacuumTablet /></Layout>} />
      <Route path="/kanban/pre-assy" element={<Layout dark><KanbanTV /></Layout>} />
      <Route path="/production" element={<Layout><ProductionDashboard /></Layout>} />
      <Route path="/management" element={<Layout><ManagementDashboard /></Layout>} />
      <Route path="/qc" element={<Layout><QcFinalCheck /></Layout>} />
      {/* WO v4.33 §3.5 — Pre-Job Card check sign-off pages (deep-linkable from the email) */}
      <Route path="/prejob/:id/signoff/:role" element={<Layout><PrejobSignoffPage /></Layout>} />
      {/* WO v4.25 read-only inspector → WO v4.26 full admin CRUD module (admin-gated) */}
      <Route path="/admin" element={<Navigate to="/admin/spec-options" replace />} />
      <Route path="/admin/:resource" element={<Layout><AdminModule /></Layout>} />
      <Route path="*" element={<Navigate to="/production" replace />} />
    </Routes>
  )
}
