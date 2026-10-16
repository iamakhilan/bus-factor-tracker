"""Deterministic, explainable project maintenance-risk scoring.

The score describes observable repository signals, not project failure or
individual maintainer burnout. Missing signals are excluded and remaining
weights are renormalized; callers receive coverage metadata.
"""
from datetime import date, datetime, timezone

WEIGHTS = {
    "concentration": 30,
    "activity": 25,
    "unresolved_issues": 15,
    "release_recency": 15,
    "contribution_diversity": 15,
}


def _as_datetime(value):
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day, tzinfo=timezone.utc)
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
        except ValueError:
            return None
    return None


def _days_since(value, now):
    dt = _as_datetime(value)
    if dt is None:
        return None
    return max(0, (now - dt).days)


def _activity_score(days):
    if days is None:
        return None
    if days <= 7:
        return 100
    if days <= 30:
        return 85
    if days <= 90:
        return 65
    if days <= 180:
        return 40
    if days <= 365:
        return 20
    return 0


def _release_score(days):
    if days is None:
        return None
    if days <= 30:
        return 100
    if days <= 90:
        return 85
    if days <= 180:
        return 65
    if days <= 365:
        return 40
    return 15


def _issue_score(open_count, total_count):
    if open_count is None or total_count is None or total_count <= 0:
        return None
    open_share = min(1.0, max(0.0, open_count / total_count))
    backlog_penalty = min(25.0, max(0, open_count) * 0.25)
    return round(max(0.0, min(100.0, 100 * (1 - open_share) - backlog_penalty)), 1)


def _diversity_score(contributor_count):
    if contributor_count is None or contributor_count <= 0:
        return None
    if contributor_count == 1:
        return 20
    if contributor_count == 2:
        return 40
    if contributor_count <= 4:
        return 60
    if contributor_count <= 9:
        return 80
    return 100


def calculate_project_health(data, now=None):
    """Return a deterministic 0-100 score and auditable factor breakdown."""
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)

    factors = []
    top_pct = data.get("top_contributor_pct")
    contributor_count = data.get("contributor_count")
    if top_pct is not None:
        top_pct = max(0.0, min(100.0, float(top_pct)))
        factors.append({
            "key": "concentration", "label": "Contributor concentration",
            "weight": WEIGHTS["concentration"], "score": round(100 - top_pct, 1),
            "evidence": f"Top contributor accounts for {top_pct:.1f}% of recorded commits.",
        })

    pushed_days = _days_since(data.get("last_pushed_at"), now)
    if pushed_days is not None:
        factors.append({
            "key": "activity", "label": "Maintenance activity",
            "weight": WEIGHTS["activity"], "score": _activity_score(pushed_days),
            "evidence": f"Last repository push was {pushed_days} day(s) ago.",
        })

    issue_score = _issue_score(data.get("open_issue_count"), data.get("tracked_issue_count"))
    if issue_score is not None:
        factors.append({
            "key": "unresolved_issues", "label": "Unresolved issue load",
            "weight": WEIGHTS["unresolved_issues"], "score": issue_score,
            "evidence": (
                f"{int(data['open_issue_count'])} open of "
                f"{int(data['tracked_issue_count'])} stored issue record(s); "
                "issue coverage is limited to records collected by the sync pipeline."
            ),
        })

    release_days = _days_since(data.get("latest_release_at"), now)
    if release_days is not None:
        factors.append({
            "key": "release_recency", "label": "Release recency",
            "weight": WEIGHTS["release_recency"], "score": _release_score(release_days),
            "evidence": f"Latest recorded release was {release_days} day(s) ago.",
        })

    diversity_score = _diversity_score(contributor_count)
    if diversity_score is not None:
        factors.append({
            "key": "contribution_diversity", "label": "Contribution diversity",
            "weight": WEIGHTS["contribution_diversity"], "score": diversity_score,
            "evidence": f"{int(contributor_count)} contributor(s) with recorded commit activity.",
        })

    available_weight = sum(f["weight"] for f in factors)
    if available_weight:
        score = round(sum(f["score"] * f["weight"] for f in factors) / available_weight)
        for factor in factors:
            factor["effective_weight_pct"] = round(100 * factor["weight"] / available_weight, 1)
            factor["weighted_points"] = round(factor["score"] * factor["weight"] / available_weight, 1)
    else:
        score = None

    return {
        "score": score,
        "label": (
            "Strong signals" if score is not None and score >= 80 else
            "Generally healthy" if score is not None and score >= 60 else
            "Elevated maintenance risk" if score is not None and score >= 40 else
            "High maintenance risk" if score is not None else
            "Insufficient data"
        ),
        "factors": factors,
        "configured_weights": WEIGHTS.copy(),
        "available_weight_pct": round(100 * available_weight / sum(WEIGHTS.values()), 1),
        "coverage": f"{len(factors)} of {len(WEIGHTS)} factors available",
        "methodology": (
            "Deterministic indicator of observable repository maintenance signals. "
            "Missing factors are omitted and remaining weights are renormalized. "
            "It is not a prediction of project failure or personal burnout."
        ),
    }
