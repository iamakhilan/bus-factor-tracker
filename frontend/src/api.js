// Thin wrapper around the FastAPI backend (Phase 5). No caching, no state
// management library — the dashboard is small enough that plain fetch +
// React state is the right amount of complexity, not less.

const API_ROOT = (import.meta.env.VITE_API_URL || 'http://localhost:8000').replace(/\\/$/, '')

async function getJSON(path, options = {}) {
  const res = await fetch(`${API_ROOT}${path}`, options)
  if (!res.ok) {
    const body = await res.json().catch(() => ({}))
    throw new Error(body.detail || `Request failed: ${res.status}`)
  }
  return res.json()
}

export function fetchRepos({ risk, sort } = {}) {
  const params = new URLSearchParams()
  if (risk) params.set('risk', risk)
  if (sort) params.set('sort', sort)
  const qs = params.toString()
  return getJSON(`/api/repos${qs ? `?${qs}` : ''}`)
}

export function fetchRepoDetail(owner, name) {
  return getJSON(`/api/repos/${owner}/${name}`)
}

export function fetchRepoTrend(owner, name) {
  return getJSON(`/api/repos/${owner}/${name}/trend`)
}

export function fetchSummary() {
  return getJSON('/api/stats/summary')
}

export function searchGithub(query, options = {}) {
  return getJSON(`/api/github/search?q=${encodeURIComponent(query)}`, options)
}

export function fetchProjectHealth(owner, name) {
  return getJSON(`/api/repos/${encodeURIComponent(owner)}/${encodeURIComponent(name)}/health`)
}

export function fetchDependencyMap(owner, name) {
  return getJSON(`/api/repos/${encodeURIComponent(owner)}/${encodeURIComponent(name)}/dependency-map`)
}

export async function addRepo(owner, name) {
  const res = await fetch(`${API_ROOT}/api/repos`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ owner, name }),
  })
  if (!res.ok) {
    const body = await res.json().catch(() => ({}))
    throw new Error(body.detail || `Request failed: ${res.status}`)
  }
  return res.json()
}

export async function removeRepo(owner, name) {
  const res = await fetch(`${API_ROOT}/api/repos/${owner}/${name}`, { method: 'DELETE' })
  if (!res.ok) {
    const body = await res.json().catch(() => ({}))
    throw new Error(body.detail || `Request failed: ${res.status}`)
  }
  return res.json()
}
