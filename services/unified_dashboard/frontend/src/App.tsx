import React from 'react'
import { BrowserRouter as Router, Routes, Route, Link } from 'react-router-dom'
import Home from './pages/Home'

function App() {
  return (
    <Router>
      <div className="min-h-screen bg-bg-page">
        {/* Header/Navigation */}
        <header className="bg-bg-card shadow-sm border-b border-border">
          <div className="container mx-auto px-6 py-4">
            <div className="flex items-center justify-between">
              <div className="flex items-center space-x-8">
                <h1 className="text-2xl font-bold text-text-primary">
                  NBA Stats Dashboard
                </h1>
                <nav className="flex space-x-6">
                  <Link
                    to="/"
                    className="text-text-secondary hover:text-text-primary font-medium"
                  >
                    Home
                  </Link>
                  <Link
                    to="/pipeline"
                    className="text-text-secondary hover:text-text-primary font-medium"
                  >
                    Pipeline
                  </Link>
                  <Link
                    to="/predictions"
                    className="text-text-secondary hover:text-text-primary font-medium"
                  >
                    Predictions
                  </Link>
                  <Link
                    to="/data-quality"
                    className="text-text-secondary hover:text-text-primary font-medium"
                  >
                    Data Quality
                  </Link>
                </nav>
              </div>
              <div className="text-text-tertiary text-sm">
                Auto-refresh: 60s
              </div>
            </div>
          </div>
        </header>

        {/* Main Content */}
        <main className="container mx-auto px-6 py-8">
          <Routes>
            <Route path="/" element={<Home />} />
            <Route path="/pipeline" element={<ComingSoon page="Pipeline Health" />} />
            <Route path="/predictions" element={<ComingSoon page="Prediction Quality" />} />
            <Route path="/data-quality" element={<ComingSoon page="Data Quality" />} />
          </Routes>
        </main>

        {/* Footer */}
        <footer className="mt-12 py-6 text-center text-text-tertiary text-sm">
          NBA Stats Unified Dashboard v1.0.0 | Last updated: {new Date().toLocaleString()}
        </footer>
      </div>
    </Router>
  )
}

function ComingSoon({ page }: { page: string }) {
  return (
    <div className="bg-bg-card rounded-card shadow-card p-12 text-center">
      <h2 className="text-2xl font-bold text-text-primary mb-4">{page}</h2>
      <p className="text-text-secondary">Coming soon in Phase 2...</p>
    </div>
  )
}

export default App
