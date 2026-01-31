import React, { useEffect, useState } from 'react'
import axios from 'axios'

interface HealthScore {
  overall_score: number
  status: string
  breakdown: {
    [key: string]: {
      score: number
      weight: number
      status: string
    }
  }
}

interface Alert {
  severity: string
  type: string
  message: string
  details: any
  action: string
  timestamp: string
}

interface Summary {
  total_predictions: number
  games_with_predictions: number
  total_games: number
  coverage_pct: number
  total_graded: number
  correct_predictions: number
  accuracy_pct: number
  week_avg_accuracy: number
  accuracy_vs_week_avg: number
}

interface PipelinePhase {
  phase: number
  name: string
  status: string
  processors: {
    total: number
    successful: number
    failed: number
  }
}

interface HomeData {
  timestamp: string
  health: HealthScore
  alerts: Alert[]
  summary: Summary
  pipeline_flow: {
    phases: PipelinePhase[]
  }
  quick_actions: any[]
}

export default function Home() {
  const [data, setData] = useState<HomeData | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [lastRefresh, setLastRefresh] = useState<Date>(new Date())

  const fetchData = async () => {
    try {
      setLoading(true)
      // Call backend directly instead of relying on proxy
      const apiUrl = process.env.REACT_APP_API_URL || 'http://localhost:8080'
      const response = await axios.get(`${apiUrl}/api/home`)
      setData(response.data)
      setLastRefresh(new Date())
      setError(null)
    } catch (err: any) {
      setError(err.message || 'Failed to fetch data')
      console.error('Error fetching home data:', err)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    fetchData()
    const interval = setInterval(fetchData, 60000) // Refresh every 60 seconds
    return () => clearInterval(interval)
  }, [])

  if (loading && !data) {
    return (
      <div className="text-center py-12">
        <div className="text-text-secondary">Loading dashboard...</div>
      </div>
    )
  }

  if (error && !data) {
    return (
      <div className="bg-red-50 border border-red-critical rounded-card p-6">
        <h3 className="text-red-critical font-bold mb-2">Error Loading Dashboard</h3>
        <p className="text-text-secondary">{error}</p>
        <button
          onClick={fetchData}
          className="mt-4 px-4 py-2 bg-red-critical text-white rounded hover:bg-red-600"
        >
          Retry
        </button>
      </div>
    )
  }

  if (!data) return null

  return (
    <div className="space-y-6">
      {/* System Health Score */}
      <HealthScoreCard health={data.health} />

      {/* Critical Alerts */}
      {data.alerts && data.alerts.length > 0 && (
        <AlertsSection alerts={data.alerts} />
      )}

      {/* Today's Summary */}
      <TodaysSummary summary={data.summary} />

      {/* Pipeline Flow */}
      <PipelineFlow phases={data.pipeline_flow.phases} />

      {/* Quick Actions */}
      {data.quick_actions && data.quick_actions.length > 0 && (
        <QuickActions actions={data.quick_actions} />
      )}

      {/* Last Refresh */}
      <div className="text-center text-text-tertiary text-sm">
        Last refresh: {lastRefresh.toLocaleTimeString()} | Next refresh in 60s
      </div>
    </div>
  )
}

function HealthScoreCard({ health }: { health: HealthScore }) {
  const statusColor = {
    healthy: 'text-green-healthy',
    warning: 'text-yellow-warning',
    critical: 'text-red-critical'
  }[health.status] || 'text-text-secondary'

  const statusBg = {
    healthy: 'bg-green-50',
    warning: 'bg-yellow-50',
    critical: 'bg-red-50'
  }[health.status] || 'bg-gray-50'

  return (
    <div className={`${statusBg} border-2 ${statusColor.replace('text-', 'border-')} rounded-card p-6`}>
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-2xl font-bold text-text-primary">System Health</h2>
        <div className="text-right">
          <div className="text-5xl font-bold ${statusColor}">{Math.round(health.overall_score)}</div>
          <div className="text-text-secondary text-sm">/ 100</div>
        </div>
      </div>
      <div className="mb-4">
        <span className={`${statusColor} font-semibold text-lg uppercase`}>
          {health.status}
        </span>
      </div>

      {/* Dimension Breakdown */}
      <div className="grid grid-cols-2 md:grid-cols-5 gap-4 mt-6">
        {Object.entries(health.breakdown).map(([key, value]) => (
          <DimensionCard key={key} name={key} data={value} />
        ))}
      </div>
    </div>
  )
}

function DimensionCard({ name, data }: { name: string; data: any }) {
  const displayName = name.replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase())
  const statusEmoji = {
    healthy: '✅',
    warning: '🟡',
    critical: '🔴'
  }[data.status] || '⚪'

  return (
    <div className="bg-bg-card rounded p-3 shadow-sm">
      <div className="text-text-tertiary text-xs mb-1">{displayName}</div>
      <div className="text-2xl font-bold text-text-primary">{Math.round(data.score)}</div>
      <div className="text-sm">{statusEmoji}</div>
    </div>
  )
}

function AlertsSection({ alerts }: { alerts: Alert[] }) {
  return (
    <div className="bg-bg-card rounded-card shadow-card p-6">
      <h2 className="text-xl font-bold text-text-primary mb-4">
        Critical Alerts ({alerts.length})
      </h2>
      <div className="space-y-3">
        {alerts.map((alert, index) => (
          <AlertCard key={index} alert={alert} />
        ))}
      </div>
    </div>
  )
}

function AlertCard({ alert }: { alert: Alert }) {
  const severityConfig = {
    critical: { bg: 'bg-red-50', text: 'text-red-critical', icon: '🔴' },
    warning: { bg: 'bg-yellow-50', text: 'text-yellow-warning', icon: '🟡' },
    info: { bg: 'bg-blue-50', text: 'text-blue-500', icon: '🔵' }
  }[alert.severity] || { bg: 'bg-gray-50', text: 'text-text-secondary', icon: '⚪' }

  return (
    <div className={`${severityConfig.bg} border ${severityConfig.text.replace('text-', 'border-')} rounded p-4`}>
      <div className="flex items-start justify-between">
        <div className="flex-1">
          <div className="flex items-center gap-2 mb-1">
            <span>{severityConfig.icon}</span>
            <span className={`${severityConfig.text} font-semibold`}>{alert.message}</span>
          </div>
          {alert.details && (
            <div className="text-text-secondary text-sm ml-6">
              {typeof alert.details === 'string' ? alert.details : JSON.stringify(alert.details)}
            </div>
          )}
        </div>
        <button className="ml-4 px-3 py-1 bg-bg-card text-text-primary text-sm rounded hover:bg-gray-100">
          {alert.action}
        </button>
      </div>
    </div>
  )
}

function TodaysSummary({ summary }: { summary: Summary }) {
  return (
    <div className="bg-bg-card rounded-card shadow-card p-6">
      <h2 className="text-xl font-bold text-text-primary mb-4">Today's Summary</h2>
      <div className="grid grid-cols-2 md:grid-cols-4 gap-6">
        <MetricCard
          label="Games Processed"
          value={`${summary.games_with_predictions}/${summary.total_games}`}
          status={summary.coverage_pct >= 95 ? 'good' : 'warning'}
        />
        <MetricCard
          label="Predictions Made"
          value={summary.total_predictions.toString()}
          subtitle={`${summary.coverage_pct.toFixed(1)}% coverage`}
        />
        <MetricCard
          label="Predictions Graded"
          value={`${summary.total_graded}`}
          subtitle={`${summary.correct_predictions} correct`}
        />
        <MetricCard
          label="Avg Accuracy"
          value={`${summary.accuracy_pct.toFixed(1)}%`}
          subtitle={`${summary.accuracy_vs_week_avg > 0 ? '↑' : '↓'} ${Math.abs(summary.accuracy_vs_week_avg).toFixed(1)}% vs 7-day avg`}
          status={summary.accuracy_pct >= 56 ? 'good' : summary.accuracy_pct >= 52.4 ? 'warning' : 'bad'}
        />
      </div>
    </div>
  )
}

function MetricCard({ label, value, subtitle, status }: { label: string; value: string; subtitle?: string; status?: string }) {
  const statusEmoji = {
    good: '✅',
    warning: '🟡',
    bad: '🔴'
  }[status || ''] || ''

  return (
    <div>
      <div className="text-text-tertiary text-sm mb-1">{label}</div>
      <div className="text-2xl font-bold text-text-primary flex items-center gap-2">
        {value} {statusEmoji}
      </div>
      {subtitle && <div className="text-text-secondary text-sm mt-1">{subtitle}</div>}
    </div>
  )
}

function PipelineFlow({ phases }: { phases: PipelinePhase[] }) {
  return (
    <div className="bg-bg-card rounded-card shadow-card p-6">
      <h2 className="text-xl font-bold text-text-primary mb-4">Pipeline Flow</h2>
      <div className="flex items-center justify-between gap-2">
        {phases.map((phase, index) => (
          <React.Fragment key={phase.phase}>
            <PhaseCard phase={phase} />
            {index < phases.length - 1 && (
              <div className="text-text-tertiary text-2xl">→</div>
            )}
          </React.Fragment>
        ))}
      </div>
    </div>
  )
}

function PhaseCard({ phase }: { phase: PipelinePhase }) {
  const statusConfig = {
    complete: { bg: 'bg-green-50', text: 'text-green-healthy', icon: '✅' },
    partial: { bg: 'bg-yellow-50', text: 'text-yellow-warning', icon: '🟡' },
    failed: { bg: 'bg-red-50', text: 'text-red-critical', icon: '🔴' },
    unknown: { bg: 'bg-gray-50', text: 'text-text-tertiary', icon: '⚪' }
  }[phase.status] || { bg: 'bg-gray-50', text: 'text-text-secondary', icon: '⚪' }

  return (
    <div className={`${statusConfig.bg} rounded p-3 flex-1 text-center`}>
      <div className="text-2xl mb-1">{statusConfig.icon}</div>
      <div className={`${statusConfig.text} font-semibold mb-1`}>Phase {phase.phase}</div>
      <div className="text-text-secondary text-sm">
        {phase.processors.successful}/{phase.processors.total}
      </div>
    </div>
  )
}

function QuickActions({ actions }: { actions: any[] }) {
  return (
    <div className="bg-bg-card rounded-card shadow-card p-6">
      <h2 className="text-xl font-bold text-text-primary mb-4">Quick Actions</h2>
      <div className="flex gap-3">
        {actions.map((action) => (
          <button
            key={action.id}
            disabled={!action.enabled}
            className="px-4 py-2 bg-blue-500 text-white rounded hover:bg-blue-600 disabled:bg-gray-300 disabled:cursor-not-allowed"
          >
            {action.label}
          </button>
        ))}
      </div>
    </div>
  )
}
