import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import type { JSX } from 'react'
import { isAuthed } from './auth'
import LoginPage from './pages/LoginPage'
import DashboardPage from './pages/DashboardPage'
import RunPage from './pages/RunPage'

function Protected({ children }: { children: JSX.Element }): JSX.Element {
  return isAuthed() ? children : <Navigate to="/" replace />
}

export default function App(): JSX.Element {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<LoginPage />} />
        <Route
          path="/dashboard"
          element={
            <Protected>
              <DashboardPage />
            </Protected>
          }
        />
        <Route
          path="/run/:runId"
          element={
            <Protected>
              <RunPage />
            </Protected>
          }
        />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
  )
}
