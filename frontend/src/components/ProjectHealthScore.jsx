import { useEffect, useState } from 'react'
import { fetchProjectHealth } from '../api.js'

const FACTOR_LABELS = {
  concentration: 'Contributor concentration',
  activity: 'Maintenance activity',
  unresolved_issues: 'Unresolved issue load',
  release_recency: 'Release recency',
  contribution_diversity: 'Contribution diversity',
}

function ScoreRing({ score }) {
  const safeScore = score == null ? 0 : Math.max(0, Math.min(100, score))
  const scoreColor = score == null ? 'var(--border)' : score >= 80 ? 'var(--risk-healthy)' : score >= 60 ? 'var(--risk-medium)' : score >= 40 ? 'var(--risk-high)' : 'var(--risk-critical)'
  return (
    <div className={`health-score-ring ${score == null ? 'is-empty' : ''}`}
      style={{ '--score-angle': `${safeScore * 3.6}deg`, '--score-color': scoreColor }} aria-label={score == null ? 'Score unavailable' : `Health score ${score} out of 100`}>
      <div className="health-score-ring-inner">
        <strong>{score == null ? '—' : score}</strong>
        <span>out of 100</span>
      </div>
    </div>
  )
}

export default function ProjectHealthScore({ owner, name }) {
  const [result, setResult] = useState(null)
  const [error, setError] = useState(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError(null)
    fetchProjectHealth(owner, name)
      .then((value) => { if (!cancelled) setResult(value) })
      .catch((e) => { if (!cancelled) setError(e.message) })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [owner, name])

  return (
    <section className="panel health-panel">
      <div className="feature-heading">
        <div>
          <h2 className="section-title">Project health score</h2>
          <p className="feature-subtitle">A transparent indicator of observable maintenance signals</p>
        </div>
        {result && <span className="coverage-chip">{result.coverage}</span>}
      </div>
      {loading && <div className="state-message">Calculating from stored repository data…</div>}
      {error && <div className="state-message error">{error}</div>}
      {!loading && !error && result && (
        <>
          <div className="health-score-overview">
            <ScoreRing score={result.score} />
            <div className="health-score-summary">
              <div className="health-score-label">{result.label}</div>
              <p>{result.score == null
                ? 'There is not enough stored data to calculate a score yet. Run a successful sync first.'
                : `Based on ${result.factors.length} available factors. ${result.available_weight_pct}% of configured weight is represented by observed data.`}</p>
              <div className="health-score-disclaimer">{result.methodology}</div>
            </div>
          </div>
          <div className="health-factor-list">
            {result.factors.map((factor) => (
              <article className="health-factor" key={factor.key}>
                <div className="health-factor-top">
                  <div>
                    <strong>{factor.label}</strong>
                    <span className="health-factor-weight">{factor.weight}% configured weight · {factor.effective_weight_pct}% effective</span>
                  </div>
                  <strong className="health-factor-score">{factor.score}/100</strong>
                </div>
                <div className="health-factor-track" aria-label={`${factor.label}: ${factor.score} out of 100`}>
                  <div className="health-factor-fill" style={{ width: `${factor.score}%` }} />
                </div>
                <p>{factor.evidence}</p>
                <span className="health-factor-impact">Weighted contribution: {factor.weighted_points} points</span>
              </article>
            ))}
          </div>
          <details className="health-methodology">
            <summary>Scoring weights & data limitations</summary>
            <ul>
              {Object.entries(result.configured_weights).map(([key, weight]) => (
                <li key={key}>{FACTOR_LABELS[key] || key}: {weight}%</li>
              ))}
            </ul>
            <p>Missing factors are excluded and remaining weights are renormalized. Issue counts represent stored records and may be incomplete because sync is bounded/incremental. A high score is not a guarantee of project health; a low score is not a prediction of failure or personal burnout.</p>
            {result.data_notes?.map((note) => <p key={note}>{note}</p>)}
          </details>
        </>
      )}
    </section>
  )
}
