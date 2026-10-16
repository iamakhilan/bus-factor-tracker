import { useEffect, useMemo, useState } from 'react'
import { fetchDependencyMap } from '../api.js'

const WIDTH = 820
const LEFT_X = 185
const RIGHT_X = 625

export default function ContributorDependencyMap({ owner, name }) {
  const [data, setData] = useState(null)
  const [error, setError] = useState(null)
  const [loading, setLoading] = useState(true)
  const [selected, setSelected] = useState(null)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError(null)
    setSelected(null)
    fetchDependencyMap(owner, name)
      .then((value) => { if (!cancelled) setData(value) })
      .catch((e) => { if (!cancelled) setError(e.message) })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [owner, name])

  const contributors = useMemo(() => (data?.contributors || []).slice(0, 10), [data])
  const modules = useMemo(() => (data?.modules || []).slice(0, 10), [data])
  const height = Math.max(320, Math.max(contributors.length, modules.length) * 52 + 72)
  const contributorPositions = new Map(contributors.map((node, i) => [node.id, { x: LEFT_X, y: 42 + i * 52 }]))
  const modulePositions = new Map(modules.map((node, i) => [node.id, { x: RIGHT_X, y: 42 + i * 52 }]))
  const visibleLinks = (data?.links || []).filter((link) => contributorPositions.has(link.source) && modulePositions.has(link.target))
  const selectedNode = selected ? data?.nodes.find((node) => node.id === selected) : null

  return (
    <section className="panel dependency-panel">
      <div className="feature-heading">
        <div>
          <h2 className="section-title">Contributor dependency map</h2>
          <p className="feature-subtitle">Who contributes, which modules they touch, and where ownership is concentrated</p>
        </div>
        {data?.sampled_at && <span className="coverage-chip">Sampled {new Date(data.sampled_at).toLocaleDateString()}</span>}
      </div>
      {loading && <div className="state-message">Loading sampled contributor and file ownership data…</div>}
      {error && <div className="state-message error">{error}</div>}
      {!loading && !error && data && (modules.length === 0 ? (
        <div className="dependency-empty">
          <strong>No module ownership sample available yet.</strong>
          <p>Run a successful sync to collect file-level data from recent GitHub commits. The graph intentionally does not generate placeholder contributors or modules.</p>
        </div>
      ) : (
        <>
          <div className="dependency-legend">
            <span><i className="legend-dot contributor-dot" /> Contributors · ranked by recorded commits</span>
            <span><i className="legend-dot module-dot" /> Modules · top-level directories</span>
            <span><i className="legend-line" /> Line thickness reflects sampled commit count</span>
          </div>
          <div className="dependency-graph-wrap">
            <svg className="dependency-graph" viewBox={`0 0 ${WIDTH} ${height}`} role="img" aria-label="Interactive graph connecting contributors to code modules">
              <text x={LEFT_X} y="22" className="graph-column-label" textAnchor="middle">CONTRIBUTORS</text>
              <text x={RIGHT_X} y="22" className="graph-column-label" textAnchor="middle">MODULES</text>
              {visibleLinks.map((link) => {
                const a = contributorPositions.get(link.source)
                const b = modulePositions.get(link.target)
                const active = selected === link.source || selected === link.target
                return <line key={`${link.source}-${link.target}`} x1={a.x + 8} y1={a.y} x2={b.x - 8} y2={b.y}
                  className={`graph-link ${active ? 'is-active' : ''}`}
                  strokeWidth={Math.max(1, Math.min(6, 1 + Math.log2(link.commit_count + 1)))} opacity={selected && !active ? 0.12 : 0.55}>
                  <title>{link.commit_count} sampled commit(s)</title>
                </line>
              })}
              {contributors.map((node) => {
                const p = contributorPositions.get(node.id)
                return <g key={node.id} transform={`translate(${p.x},${p.y})`} className={`graph-node contributor-node ${selected === node.id ? 'is-selected' : ''}`}
                  role="button" tabIndex="0" aria-label={`${node.label}, rank ${node.rank}, ${node.activity_pct}% of recorded commits`}
                  onClick={() => setSelected(node.id)} onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') setSelected(node.id) }}>
                  <circle r="7" />
                  <text x="-15" y="-1" textAnchor="end" className="graph-node-title">{node.label.length > 22 ? node.label.slice(0, 20) + '…' : node.label}</text>
                  <text x="-15" y="14" textAnchor="end" className="graph-node-subtitle">#{node.rank} · {node.activity_pct}% activity</text>
                </g>
              })}
              {modules.map((node) => {
                const p = modulePositions.get(node.id)
                return <g key={node.id} transform={`translate(${p.x},${p.y})`} className={`graph-node module-node ${selected === node.id ? 'is-selected' : ''}`}
                  role="button" tabIndex="0" aria-label={`${node.label}, ${node.file_count} files, top owner ${node.top_contributor_pct}%`}
                  onClick={() => setSelected(node.id)} onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') setSelected(node.id) }}>
                  <rect x="-7" y="-7" width="14" height="14" rx="3" />
                  <text x="16" y="-1" className="graph-node-title">{node.label.length > 22 ? node.label.slice(0, 20) + '…' : node.label}</text>
                  <text x="16" y="14" className="graph-node-subtitle">{node.file_count} files · {node.top_contributor_pct}% top owner</text>
                </g>
              })}
            </svg>
          </div>
          <div className="dependency-insights">
            <div className="dependency-lists">
              <div>
                <h3>Contributor ranking</h3>
                {contributors.map((node) => <button key={node.id} className={`dependency-list-row ${selected === node.id ? 'is-selected' : ''}`} onClick={() => setSelected(node.id)}>
                  <span className="dependency-rank">#{node.rank}</span><span className="dependency-row-name">{node.label}</span><strong>{node.activity_pct}%</strong>
                </button>)}
              </div>
              <div>
                <h3>Ownership bottlenecks</h3>
                {modules.map((node) => <button key={node.id} className={`dependency-list-row ${selected === node.id ? 'is-selected' : ''}`} onClick={() => setSelected(node.id)}>
                  <span className={`bottleneck-indicator ${node.bottleneck ? 'is-risky' : ''}`} />
                  <span className="dependency-row-name">{node.label}</span><strong>{node.top_contributor_pct}%</strong>
                </button>)}
              </div>
            </div>
            {selectedNode && <div className="dependency-selection">
              <button className="dependency-clear" onClick={() => setSelected(null)}>Clear selection ×</button>
              <strong>{selectedNode.label}</strong>
              {selectedNode.kind === 'contributor'
                ? <p>Rank #{selectedNode.rank} · {selectedNode.commits.toLocaleString()} recorded commits · {selectedNode.activity_pct}% of recorded contributor commits.</p>
                : <><p>{selectedNode.file_count} file(s) · {selectedNode.contributor_count} contributor(s) · {selectedNode.sampled_commits} sampled file-touch commit(s).</p>
                  <p>{selectedNode.bottleneck ? 'Potential ownership bottleneck: one contributor or a top owner with at least 80% of sampled touches.' : 'No single-owner bottleneck detected in this sample.'} Top observed contributor: {selectedNode.top_contributor || 'unknown'} ({selectedNode.top_contributor_pct}%).</p>
                  <div className="dependency-file-list">{selectedNode.files.slice(0, 12).map((path) => <code key={path}>{path}</code>)}</div></>}
            </div>}
          </div>
          <p className="dependency-footnote">Sample method: up to 12 recent GitHub commits, with each commit's changed-file list. It is not complete Git history or git blame. Displayed contributors/modules are the top 10 in this sample; inspect the selected module for file-level details.</p>
        </>
      ))}
    </section>
  )
}
