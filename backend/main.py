"""
Bus Factor Tracker — FastAPI backend (Phase 5 + repo management)

Serves data that was already collected and computed by sync_mysql.py.
Most endpoints here only read from MySQL, which is why they respond in
milliseconds rather than the 10-15 seconds the sync script takes per repo.
See the note in the project README about why these two pieces are
deliberately separate.

The exception is POST /api/repos (adding a new repo to track), which calls
GitHub directly and DOES take 10-15 seconds — same cost as one repo in the
sync script, because it reuses that exact same sync_repo() function rather
than duplicating the logic.

Run:
    uvicorn main:app --reload --port 8000

Then visit http://localhost:8000/docs for interactive API docs (FastAPI
generates this automatically from the code below — nothing extra needed).
"""

import os
import sys
from pathlib import Path
from typing import Optional

import requests as gh_requests
from dotenv import load_dotenv
from fastapi import FastAPI, Depends, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from mysql.connector import MySQLConnection

from db import get_connection
from health_score import calculate_project_health

# Load .env from the backend folder first, then fall back to the project
# root's .env — this way GITHUB_TOKEN only has to exist in one place if
# you're already using it for the sync script.
load_dotenv(Path(__file__).parent / ".env")
load_dotenv(Path(__file__).parent.parent / ".env")

GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN")
REPOS_FILE = Path(__file__).parent.parent / "repos.txt"

# Reuse the exact same sync_repo() function the sync script uses, instead of
# duplicating GitHub-fetching/upsert logic here. This is the same reasoning
# as everything else in this project: one source of truth for how a repo
# gets synced, whether that's triggered by the batch script or by a user
# clicking "add" in the UI.
sys.path.append(str(Path(__file__).parent.parent / "scripts"))
from sync_mysql import sync_repo  # noqa: E402

app = FastAPI(
    title="Bus Factor Tracker API",
    description="Tracks bus factor / maintainer burnout risk across open-source repositories.",
    version="1.0.0",
)

# Allow the React dev server (Phase 6) to call this API from the browser.
# Vite's default port is 5173, Create React App's is 3000 — both included
# so it works regardless of which you end up using.
CORS_ORIGINS = [
    origin.strip() for origin in os.environ.get(
        "CORS_ORIGINS", "http://localhost:5173,http://localhost:3000"
    ).split(",") if origin.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["*"],
)




# ---------------------------------------------------------------------------
# Response models — these double as API documentation (visible in /docs)
# and give the frontend a predictable, typed shape to build against.
# ---------------------------------------------------------------------------

class RepoSummary(BaseModel):
    repo_id: int
    owner: str
    name: str
    primary_language: Optional[str]
    stars: int
    is_archived: bool
    bus_factor: Optional[int]
    top_contributor_pct: Optional[float]
    active_contributor_count: Optional[int]
    median_issue_response_hours: Optional[float]
    risk_level: Optional[str]
    computed_at: Optional[str]


class GitHubSearchResult(BaseModel):
    owner: str
    name: str
    full_name: str
    description: Optional[str]
    stars: int
    language: Optional[str]


class AddRepoRequest(BaseModel):
    owner: str
    name: str


class ContributorBreakdown(BaseModel):
    github_username: str
    total_commits: int
    additions: int
    deletions: int
    commit_share_pct: float


class RepoDetail(RepoSummary):
    forks: int
    created_at: Optional[str]
    contributors: list[ContributorBreakdown]


class SnapshotPoint(BaseModel):
    computed_at: str
    bus_factor: int
    top_contributor_pct: Optional[float]
    risk_level: str


class DashboardSummary(BaseModel):
    total_repos_tracked: int
    critical_count: int
    high_count: int
    medium_count: int
    healthy_count: int


# ---------------------------------------------------------------------------
# Shared query fragment: repo + its MOST RECENT snapshot.
# Uses a correlated subquery to grab each repo's latest computed_at — the
# straightforward way to do "latest row per group" without window functions
# cluttering every endpoint that needs this same join.
# ---------------------------------------------------------------------------

LATEST_SNAPSHOT_JOIN = """
    FROM repository r
    LEFT JOIN bus_factor_snapshot s
        ON s.repo_id = r.repo_id
        AND s.computed_at = (
            SELECT MAX(s2.computed_at)
            FROM bus_factor_snapshot s2
            WHERE s2.repo_id = r.repo_id
        )
"""


@app.get("/api/repos", response_model=list[RepoSummary])
def list_repos(
    risk: Optional[str] = Query(None, description="Filter by risk level: Critical, High, Medium, Healthy"),
    sort: str = Query("risk", description="Sort by: risk (worst first), stars, name"),
    conn: MySQLConnection = Depends(get_connection),
):
    """
    Risk-ranked list of all tracked repos with their latest snapshot.
    This is the main dashboard endpoint — powers the repo list / table view.
    """
    cur = conn.cursor(dictionary=True)

    where_clause = ""
    params = []
    if risk:
        where_clause = "WHERE s.risk_level = %s"
        params.append(risk)

    order_clause = {
        "risk": "FIELD(s.risk_level, 'Critical', 'High', 'Medium', 'Healthy'), s.bus_factor ASC",
        "stars": "r.stars DESC",
        "name": "r.owner ASC, r.name ASC",
    }.get(sort, "FIELD(s.risk_level, 'Critical', 'High', 'Medium', 'Healthy')")

    cur.execute(
        f"""
        SELECT
            r.repo_id, r.owner, r.name, r.primary_language, r.stars, r.is_archived,
            s.bus_factor, s.top_contributor_pct, s.active_contributor_count,
            s.median_issue_response_hours, s.risk_level, s.computed_at
        {LATEST_SNAPSHOT_JOIN}
        {where_clause}
        ORDER BY {order_clause}
        """,
        params,
    )
    rows = cur.fetchall()
    cur.close()

    # Convert non-JSON-serializable types (datetime, Decimal) to plain types.
    for row in rows:
        if row["computed_at"] is not None:
            row["computed_at"] = row["computed_at"].isoformat()
        if row["top_contributor_pct"] is not None:
            row["top_contributor_pct"] = float(row["top_contributor_pct"])
        if row["median_issue_response_hours"] is not None:
            row["median_issue_response_hours"] = float(row["median_issue_response_hours"])

    return rows


@app.get("/api/repos/{owner}/{name}", response_model=RepoDetail)
def get_repo_detail(owner: str, name: str, conn: MySQLConnection = Depends(get_connection)):
    """
    Full detail view for a single repo: metadata, latest snapshot, and its
    contributor breakdown (for the "who actually did the work" view).
    """
    cur = conn.cursor(dictionary=True)

    cur.execute(
        f"""
        SELECT
            r.repo_id, r.owner, r.name, r.primary_language, r.stars, r.forks,
            r.created_at, r.is_archived,
            s.bus_factor, s.top_contributor_pct, s.active_contributor_count,
            s.median_issue_response_hours, s.risk_level, s.computed_at
        {LATEST_SNAPSHOT_JOIN}
        WHERE r.owner = %s AND r.name = %s
        """,
        (owner, name),
    )
    repo = cur.fetchone()
    if repo is None:
        cur.close()
        raise HTTPException(status_code=404, detail=f"Repo {owner}/{name} not found — has it been synced yet?")

    cur.execute(
        """
        SELECT
            c.github_username,
            rc.total_commits,
            rc.additions,
            rc.deletions,
            ROUND(100 * rc.total_commits / NULLIF((
                SELECT SUM(rc2.total_commits) FROM repo_contributor rc2 WHERE rc2.repo_id = rc.repo_id
            ), 0), 1) AS commit_share_pct
        FROM repo_contributor rc
        JOIN contributor c ON c.contributor_id = rc.contributor_id
        WHERE rc.repo_id = %s
        ORDER BY rc.total_commits DESC
        """,
        (repo["repo_id"],),
    )
    contributors = cur.fetchall()
    cur.close()

    for c in contributors:
        c["commit_share_pct"] = float(c["commit_share_pct"]) if c["commit_share_pct"] is not None else 0.0

    if repo["computed_at"] is not None:
        repo["computed_at"] = repo["computed_at"].isoformat()
    if repo["created_at"] is not None:
        repo["created_at"] = repo["created_at"].isoformat()
    if repo["top_contributor_pct"] is not None:
        repo["top_contributor_pct"] = float(repo["top_contributor_pct"])
    if repo["median_issue_response_hours"] is not None:
        repo["median_issue_response_hours"] = float(repo["median_issue_response_hours"])

    repo["contributors"] = contributors
    return repo


@app.get("/api/repos/{owner}/{name}/health")
def get_project_health(owner: str, name: str, conn: MySQLConnection = Depends(get_connection)):
    """Explainable, deterministic 0-100 observable maintenance-risk indicator."""
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute(
            "SELECT repo_id, last_pushed_at FROM repository WHERE owner = %s AND name = %s",
            (owner, name),
        )
        repo = cur.fetchone()
        if repo is None:
            raise HTTPException(status_code=404, detail=f"Repo {owner}/{name} not found")

        cur.execute(
            """
            SELECT COUNT(*) AS contributor_count, SUM(total_commits) AS total_commits,
                   MAX(total_commits) AS top_commits
            FROM repo_contributor WHERE repo_id = %s AND total_commits > 0
            """,
            (repo["repo_id"],),
        )
        contributor = cur.fetchone() or {}
        total_commits = int(contributor.get("total_commits") or 0)
        top_commits = int(contributor.get("top_commits") or 0)
        top_pct = round(100 * top_commits / total_commits, 1) if total_commits else None

        cur.execute(
            """
            SELECT COUNT(*) AS tracked_issue_count,
                   SUM(CASE WHEN state = 'open' THEN 1 ELSE 0 END) AS open_issue_count
            FROM issue WHERE repo_id = %s
            """,
            (repo["repo_id"],),
        )
        issues = cur.fetchone() or {}
        cur.execute(
            "SELECT MAX(published_at) AS latest_release_at FROM repo_release WHERE repo_id = %s",
            (repo["repo_id"],),
        )
        release = cur.fetchone() or {}
        result = calculate_project_health({
            "top_contributor_pct": top_pct,
            "contributor_count": int(contributor.get("contributor_count") or 0),
            "last_pushed_at": repo.get("last_pushed_at"),
            "open_issue_count": int(issues["open_issue_count"] or 0) if issues.get("tracked_issue_count") else None,
            "tracked_issue_count": int(issues["tracked_issue_count"] or 0),
            "latest_release_at": release.get("latest_release_at"),
        })
        result["repository"] = f"{owner}/{name}"
        result["data_notes"] = [
            "Contributor statistics come from GitHub's aggregated contributor endpoint and may cover its available statistics window.",
            "Issue counts reflect issue records stored by the bounded/incremental sync pipeline, not necessarily every issue in the repository.",
            "Release recency uses the latest release record collected by the sync pipeline.",
            "Repository push time is a maintenance-activity proxy; it does not prove that issues are being handled.",
        ]
        return result
    finally:
        cur.close()


@app.get("/api/repos/{owner}/{name}/dependency-map")
def get_contributor_dependency_map(owner: str, name: str, conn: MySQLConnection = Depends(get_connection)):
    """Return a graph of contributors connected to sampled top-level modules."""
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute(
            "SELECT repo_id FROM repository WHERE owner = %s AND name = %s",
            (owner, name),
        )
        repo = cur.fetchone()
        if repo is None:
            raise HTTPException(status_code=404, detail=f"Repo {owner}/{name} not found")

        cur.execute(
            """
            SELECT c.github_username, rc.total_commits
            FROM repo_contributor rc
            JOIN contributor c ON c.contributor_id = rc.contributor_id
            WHERE rc.repo_id = %s AND rc.total_commits > 0
            ORDER BY rc.total_commits DESC, c.github_username ASC
            """,
            (repo["repo_id"],),
        )
        contributor_rows = cur.fetchall()
        total_commits = sum(int(row["total_commits"] or 0) for row in contributor_rows)
        contributor_nodes = []
        for rank, row in enumerate(contributor_rows, start=1):
            commits = int(row["total_commits"] or 0)
            contributor_nodes.append({
                "id": f"contributor:{row['github_username']}",
                "kind": "contributor",
                "label": row["github_username"],
                "rank": rank,
                "commits": commits,
                "activity_pct": round(100 * commits / total_commits, 1) if total_commits else 0,
            })

        cur.execute(
            """
            SELECT mo.file_path, mo.commit_count, mo.additions, mo.deletions, mo.sampled_at,
                   c.github_username
            FROM module_ownership mo
            JOIN contributor c ON c.contributor_id = mo.contributor_id
            WHERE mo.repo_id = %s
            ORDER BY mo.file_path, mo.commit_count DESC, c.github_username
            """,
            (repo["repo_id"],),
        )
        ownership_rows = cur.fetchall()
        cur.close()
        cur = None

        modules = {}
        links = {}
        sample_times = []
        for row in ownership_rows:
            path = row["file_path"]
            module_name = path.split("/", 1)[0] if "/" in path else "(root files)"
            module_id = f"module:{module_name}"
            module = modules.setdefault(module_id, {
                "id": module_id, "kind": "module", "label": module_name,
                "files": set(), "by_contributor": {}, "sampled_commits": 0,
                "additions": 0, "deletions": 0,
            })
            module["files"].add(path)
            login = row["github_username"]
            count = int(row["commit_count"] or 0)
            module["by_contributor"][login] = module["by_contributor"].get(login, 0) + count
            module["sampled_commits"] += count
            module["additions"] += int(row["additions"] or 0)
            module["deletions"] += int(row["deletions"] or 0)
            link_key = (login, module_id)
            links[link_key] = links.get(link_key, 0) + count
            if row.get("sampled_at"):
                sample_times.append(row["sampled_at"])

        module_nodes = []
        for module in modules.values():
            distribution = module.pop("by_contributor")
            ordered = sorted(distribution.items(), key=lambda item: (-item[1], item[0]))
            total = sum(distribution.values())
            top_login, top_count = ordered[0] if ordered else (None, 0)
            top_pct = round(100 * top_count / total, 1) if total else 0
            module_nodes.append({
                **module,
                "files": sorted(module["files"]),
                "file_count": len(module["files"]),
                "contributor_count": len(distribution),
                "top_contributor": top_login,
                "top_contributor_pct": top_pct,
                "bottleneck": bool(total and (len(distribution) == 1 or top_pct >= 80)),
            })

        module_nodes.sort(key=lambda item: (-item["sampled_commits"], item["label"]))
        graph_links = [{
            "source": f"contributor:{login}", "target": module_id,
            "commit_count": count,
        } for (login, module_id), count in sorted(links.items())]
        return {
            "repository": f"{owner}/{name}",
            "nodes": contributor_nodes + module_nodes,
            "links": graph_links,
            "contributors": contributor_nodes,
            "modules": module_nodes,
            "sampled_at": max(sample_times).isoformat() if sample_times else None,
            "sample": {
                "source": "GitHub commit detail files from up to 12 recent commits at last successful sync",
                "complete_history": False,
                "commit_details_sampled": len({(row["file_path"], row["github_username"]) for row in ownership_rows}),
                "note": "Ownership is an observed recent sample, not complete git blame. No graph is fabricated when sample data is unavailable.",
            },
        }
    finally:
        if cur is not None:
            cur.close()


@app.get("/api/repos/{owner}/{name}/trend", response_model=list[SnapshotPoint])
def get_repo_trend(owner: str, name: str, conn: MySQLConnection = Depends(get_connection)):
    """
    Full snapshot history for one repo — powers the "bus factor over time"
    trend chart. Only meaningful once sync_mysql.py has been run more than
    once for this repo (each run adds one snapshot row).
    """
    cur = conn.cursor(dictionary=True)
    cur.execute(
        """
        SELECT s.computed_at, s.bus_factor, s.top_contributor_pct, s.risk_level
        FROM bus_factor_snapshot s
        JOIN repository r ON r.repo_id = s.repo_id
        WHERE r.owner = %s AND r.name = %s
        ORDER BY s.computed_at ASC
        """,
        (owner, name),
    )
    rows = cur.fetchall()
    cur.close()

    if not rows:
        raise HTTPException(status_code=404, detail=f"No snapshot history for {owner}/{name} yet")

    for row in rows:
        row["computed_at"] = row["computed_at"].isoformat()
        if row["top_contributor_pct"] is not None:
            row["top_contributor_pct"] = float(row["top_contributor_pct"])

    return rows


@app.get("/api/stats/summary", response_model=DashboardSummary)
def get_dashboard_summary(conn: MySQLConnection = Depends(get_connection)):
    """
    Aggregate counts for a dashboard header — e.g. "12 Critical, 8 High,
    20 Medium, 40 Healthy out of 80 repos tracked".
    """
    cur = conn.cursor(dictionary=True)
    cur.execute(
        f"""
        SELECT
            COUNT(*) AS total_repos_tracked,
            SUM(CASE WHEN s.risk_level = 'Critical' THEN 1 ELSE 0 END) AS critical_count,
            SUM(CASE WHEN s.risk_level = 'High' THEN 1 ELSE 0 END) AS high_count,
            SUM(CASE WHEN s.risk_level = 'Medium' THEN 1 ELSE 0 END) AS medium_count,
            SUM(CASE WHEN s.risk_level = 'Healthy' THEN 1 ELSE 0 END) AS healthy_count
        {LATEST_SNAPSHOT_JOIN}
        """
    )
    row = cur.fetchone()
    cur.close()

    # SUM() over zero matching rows returns NULL, not 0 — normalize that.
    for key in ("critical_count", "high_count", "medium_count", "healthy_count"):
        row[key] = int(row[key]) if row[key] is not None else 0

    return row


# ---------------------------------------------------------------------------
# repos.txt helpers — keep the tracked-repo file in sync with the database
# whenever a repo is added or removed through the UI, so re-running the
# batch sync script later still operates on the same repo list.
# ---------------------------------------------------------------------------

def _append_to_repos_file(owner: str, name: str):
    entry = f"{owner}/{name}"
    existing_lines = []
    if REPOS_FILE.exists():
        existing_lines = [line.strip() for line in REPOS_FILE.read_text().splitlines()]
    if entry not in existing_lines:
        with open(REPOS_FILE, "a") as f:
            f.write(f"\n{entry}\n")


def _remove_from_repos_file(owner: str, name: str):
    entry = f"{owner}/{name}"
    if not REPOS_FILE.exists():
        return
    lines = REPOS_FILE.read_text().splitlines()
    kept_lines = [line for line in lines if line.strip() != entry]
    REPOS_FILE.write_text("\n".join(kept_lines) + "\n")


# ---------------------------------------------------------------------------
# Repo management: search GitHub, add a new repo to track, remove one.
# ---------------------------------------------------------------------------

@app.get("/api/github/search", response_model=list[GitHubSearchResult])
def search_github_repos(q: str = Query(..., min_length=2)):
    """
    Server-side proxy to GitHub's repository search — powers the
    autocomplete suggestions in the "add repo" UI. Kept server-side so the
    GitHub token never has to be exposed to the browser.
    """
    if not GITHUB_TOKEN:
        raise HTTPException(status_code=500, detail="GITHUB_TOKEN is not configured on the backend")

    resp = gh_requests.get(
        "https://api.github.com/search/repositories",
        params={"q": q, "per_page": 8, "sort": "stars", "order": "desc"},
        headers={"Authorization": f"Bearer {GITHUB_TOKEN}", "Accept": "application/vnd.github+json"},
    )
    if resp.status_code == 403:
        raise HTTPException(status_code=429, detail="GitHub API rate limit hit — try again shortly")
    resp.raise_for_status()

    items = resp.json().get("items", [])
    return [
        {
            "owner": item["owner"]["login"],
            "name": item["name"],
            "full_name": item["full_name"],
            "description": item.get("description"),
            "stars": item["stargazers_count"],
            "language": item.get("language"),
        }
        for item in items
    ]


@app.post("/api/repos", response_model=RepoSummary)
def add_repo(payload: AddRepoRequest, conn: MySQLConnection = Depends(get_connection)):
    """
    Add a new repo to track. This calls the SAME sync_repo() function the
    batch sync script uses — same GitHub calls, same transaction, same bus
    factor computation — so takes the same 10-15 seconds a single repo takes
    during a normal sync run. The frontend should show a loading state for
    this, not treat it like the other (instant) endpoints.
    """
    owner, name = payload.owner.strip(), payload.name.strip()
    if not owner or not name:
        raise HTTPException(status_code=400, detail="owner and name are required")

    try:
        sync_repo(conn, owner, name)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Could not sync {owner}/{name}: {e}")

    _append_to_repos_file(owner, name)

    cur = conn.cursor(dictionary=True)
    cur.execute(
        f"""
        SELECT
            r.repo_id, r.owner, r.name, r.primary_language, r.stars, r.is_archived,
            s.bus_factor, s.top_contributor_pct, s.active_contributor_count,
            s.median_issue_response_hours, s.risk_level, s.computed_at
        {LATEST_SNAPSHOT_JOIN}
        WHERE r.owner = %s AND r.name = %s
        """,
        (owner, name),
    )
    row = cur.fetchone()
    cur.close()

    if row["computed_at"] is not None:
        row["computed_at"] = row["computed_at"].isoformat()
    if row["top_contributor_pct"] is not None:
        row["top_contributor_pct"] = float(row["top_contributor_pct"])
    if row["median_issue_response_hours"] is not None:
        row["median_issue_response_hours"] = float(row["median_issue_response_hours"])

    return row


@app.delete("/api/repos/{owner}/{name}")
def remove_repo(owner: str, name: str, conn: MySQLConnection = Depends(get_connection)):
    """
    Stop tracking a repo. Deleting the repository row cascades (via the
    ON DELETE CASCADE foreign keys in the schema) to remove its contributors,
    issues, PRs, releases, and snapshot history in the same operation —
    no separate cleanup queries needed.
    """
    cur = conn.cursor()
    cur.execute("SELECT repo_id FROM repository WHERE owner = %s AND name = %s", (owner, name))
    row = cur.fetchone()
    if row is None:
        cur.close()
        raise HTTPException(status_code=404, detail=f"{owner}/{name} is not currently tracked")

    cur.execute("DELETE FROM repository WHERE repo_id = %s", (row[0],))
    conn.commit()
    cur.close()

    _remove_from_repos_file(owner, name)
    return {"status": "removed", "owner": owner, "name": name}


@app.get("/")
def root():
    return {"message": "Bus Factor Tracker API — see /docs for available endpoints"}
