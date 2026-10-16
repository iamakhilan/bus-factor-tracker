# 🚌 Bus Factor Tracker

> *"I can tell you which of your project''s dependencies are one person away from going unmaintained."*

A full-stack DBMS project that estimates **bus factor** and observable repository maintenance risk from live public GitHub data. Scores are risk indicators, not predictions of project failure or personal burnout.

Built for **SEM 5 — Database Management Systems**.

---

## What Is Bus Factor?

**Bus factor** = the smallest number of top contributors whose combined commits account for ≥50% of total recent activity.

A bus factor of **1** means a single person''s absence would kill the project (critical risk). A bus factor of **4+** means the project is healthy and distributed.

---

## Features

- 📊 **Risk Dashboard** — Risk-ranked list of all tracked repos (Critical / High / Medium / Healthy)
- 📈 **Trend Charts** — Bus factor over time for each repo
- 🕸️ **Contributor Dependency Map** — Interactive graph connecting ranked contributors to top-level code modules, with sampled file ownership and bottleneck indicators
- 💯 **Project Health Score** — Deterministic 0–100 score with configurable factor weights, per-factor evidence, missing-data coverage and scoring explanations
- 🔍 **GitHub Search** — Add any public repo to the tracker via live GitHub search
- 🗑️ **Repo Management** — Add/remove repos; `repos.txt` stays in sync automatically
- ⚡ **FastAPI Backend** — Auto-generated `/docs` (Swagger UI) with all endpoints
- 🛢️ **MySQL Database** — Fully normalized schema (3NF), window functions, ACID transactions

---

## Tech Stack

| Layer | Technology |
|---|---|
| Database | MySQL |
| Backend | Python + FastAPI |
| Sync Script | Python (`scripts/sync_mysql.py`) |
| Frontend | React + Recharts (Vite) |

---

## Project Structure

```
bus-factor-tracker/
├── backend/
│   ├── main.py          # FastAPI app and analytics endpoints
│   ├── health_score.py  # Pure, deterministic health score calculation
│   ├── db.py            # MySQL connection helper
│   └── requirements.txt
├── frontend/
│   ├── src/
│   │   ├── App.jsx
│   │   ├── api.js
│   │   ├── styles.css
│   │   └── components/
│   ├── index.html
│   └── package.json
├── scripts/
│   └── sync_mysql.py    # GitHub API → MySQL sync script
├── sql/
│   ├── schema_mysql.sql  # Full database schema
│   ├── queries_mysql.sql # Analytics queries
│   └── migrations/       # Existing-database migrations
├── tests/
│   └── test_health_score.py
├── repos.txt            # Curated list of repos to track
├── .env.example         # Environment variable template
└── requirements_mysql.txt
```

---

## Setup

### 1. Prerequisites

- Python 3.10+
- Node.js 18+
- MySQL 8.0+
- A [GitHub Personal Access Token](https://github.com/settings/tokens) (read-only, public repos)

### 2. Database

```sql
source sql/schema_mysql.sql
```

For an **existing** database created before the new analytics features, apply the migration once:

```bash
mysql -u root -p bus_factor_tracker < sql/migrations/001_health_and_module_ownership.sql
```

Do not run the migration on a fresh database that already uses the updated schema.

### 3. Environment Variables

```bash
cp .env.example .env
# Edit .env — fill in GITHUB_TOKEN, DB_HOST, DB_USER, DB_PASSWORD, and CORS_ORIGINS
```

### 4. Backend

```bash
cd backend
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
# Swagger UI → http://localhost:8000/docs
```

### 5. Sync Data

```bash
pip install -r requirements_mysql.txt
python scripts/sync_mysql.py
```

### 6. Frontend

```bash
cd frontend
npm install
npm run dev
# App → http://localhost:5173
```

For deployment, create `frontend/.env.local` (or set your hosting provider's build environment) with `VITE_API_URL=https://your-api.example.com`. Set backend `CORS_ORIGINS` to a comma-separated list of the exact frontend origins. Never put the GitHub token in frontend variables.

---

## Risk Scoring

| Risk Level | Criteria |
|---|---|
| 🔴 Critical | Bus factor = 1 |
| 🟠 High | Bus factor = 2 |
| 🟡 Medium | Bus factor 3–4 |
| 🟢 Healthy | Bus factor 5+ |

---

## Project Health Score methodology

The health score is a **deterministic indicator of observable repository maintenance signals**, not a prediction of project failure and not a measure of any person's burnout. The default weights are defined in `backend/health_score.py` and can be changed there.

| Factor | Weight | Score rule |
|---|---:|---|
| Contributor concentration | 30% | 100 minus the top contributor's percentage of recorded contributor commits |
| Maintenance activity | 25% | Days since GitHub's repository `pushed_at`: ≤7 days = 100; ≤30 = 85; ≤90 = 65; ≤180 = 40; ≤365 = 20; older = 0 |
| Unresolved issue load | 15% | 100 × (1 − open / recorded total), minus a capped backlog penalty of 0.25 points per open issue (maximum 25 points), clamped to 0–100 |
| Release recency | 15% | Days since latest recorded release: ≤30 days = 100; ≤90 = 85; ≤180 = 65; ≤365 = 40; older = 15 |
| Contribution diversity | 15% | Recorded contributors with commits: 1 = 20; 2 = 40; 3–4 = 60; 5–9 = 80; 10+ = 100 |

The final score is the weighted mean of available factor scores, rounded to the nearest integer. **Missing factors are omitted and the remaining weights are renormalized.** If no factor is available, the score is `null` rather than a fabricated zero. The API returns configured weight, effective weight, factor score, weighted contribution, evidence, and data coverage.

Important data limits:
- Contributor statistics use GitHub's aggregate contributor endpoint; the API does not provide a universal, exact trailing-12-month contribution window for every repository.
- Issue records are bounded/incremental in this project, so issue evidence describes records stored locally and may not represent the repository's complete backlog.
- Release recency is based on releases collected by the sync pipeline.
- Repository `pushed_at` is a recent-activity proxy; it does not prove that issues are being answered or releases are being shipped.
- The score does not currently treat archived status as a negative signal; archived projects may be intentionally complete.

## Contributor Dependency Map

During sync, the pipeline requests up to 12 recent commit details and records changed files and commit authors in `module_ownership`. The API groups paths by top-level directory (root-level files use a separate group) and exposes links weighted by sampled file-touch commits. Modules are flagged as potential bottlenecks when only one contributor appears in the sample or the top contributor accounts for at least 80% of sampled touches.

This is deliberately a **bounded recent sample**, not full Git history, full code ownership, or `git blame`. If GitHub cannot provide a sample, the previous sample is retained; the UI does not invent graph nodes. The sample uses additional GitHub API requests (up to 12 commit-detail requests per successful repository sync).

## Tests

Run deterministic scoring unit tests from the repository root:

```bash
python -m unittest discover -s tests
```

## API Endpoints

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/repos` | Risk-ranked repo list |
| `GET` | `/api/repos/{owner}/{name}` | Repo detail + contributor breakdown |
| `GET` | `/api/repos/{owner}/{name}/trend` | Bus factor history |
| `GET` | `/api/repos/{owner}/{name}/health` | Explainable 0–100 health score and factor evidence |
| `GET` | `/api/repos/{owner}/{name}/dependency-map` | Contributor-to-module graph and sampled ownership bottlenecks |
| `GET` | `/api/stats/summary` | Dashboard aggregate counts |
| `GET` | `/api/github/search?q=...` | Search GitHub repos |
| `POST` | `/api/repos` | Add a repo to track |
| `DELETE` | `/api/repos/{owner}/{name}` | Remove a repo |

---

## License

MIT
