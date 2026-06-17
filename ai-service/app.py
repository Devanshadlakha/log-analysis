"""
app.py
──────
Flask entry point — defines all API routes for the AI service.

Routes:
  POST /analyze     ← main endpoint React calls with NL query
  GET  /health      ← health check
"""

import os
import requests
from flask import Flask, request, jsonify
from flask_cors import CORS
from dotenv import load_dotenv

from query_parser import parse_query
from embeddings import get_embeddings
from clustering import cluster_logs
from summarizer import generate_summary

# Load environment variables from .env file
load_dotenv()

app = Flask(__name__)

# Allow React frontend (port 5173) to call this API
CORS(app, origins=["http://localhost:5173", "http://localhost:3000"])

# Spring Boot backend URL
SPRING_BACKEND_URL = os.getenv("SPRING_BACKEND_URL", "http://localhost:8080")

# Maps frontend source categories to collector service-name prefixes.
# When the UI is on a category page (e.g. "System Logs"), it sends source="system"
# and we scope the backend search to logs whose service.keyword starts with one
# of these prefixes. Passed to the backend as servicePatterns=...,...
SOURCE_SERVICE_MAP = {
    "system":    ["windows-event"],
    "file":      ["test-app", "file-"],
    "database":  ["mariadb", "mysql", "postgresql"],
    "docker":    ["docker"],
    "github":    ["github-actions"],
    "webserver": ["nginx", "apache"],
}


# ─────────────────────────────────────────────────────────────
# POST /analyze
# Main endpoint — takes natural language query, returns everything
# ─────────────────────────────────────────────────────────────
@app.route("/analyze", methods=["POST"])
def analyze():
    """
    Full pipeline:
    1. Parse natural language query → structured filters
    2. Fetch logs from Spring Boot using those filters (scoped to source category)
    3. Generate embeddings for log messages
    4. Cluster logs by similarity
    5. Generate root cause summary
    6. Return everything to frontend
    """
    data = request.get_json()

    if not data or "query" not in data:
        return jsonify({"error": "Missing 'query' field in request body"}), 400

    # Forward the user's JWT so backend can enforce RBAC
    auth_header = request.headers.get("Authorization", "")

    natural_query = data["query"]
    source = data.get("source")  # e.g. "system", "docker", "github"
    time_range = data.get("timeRange")  # explicit UI dropdown (hours, as string)
    print(f"\n[analyze] Received query: {natural_query} (source={source}, timeRange={time_range})")

    # ── Step 1: Parse NL query into structured filters ────────
    filters = parse_query(natural_query)

    # Keyword-based level fallback — the LLM parser sometimes misses an
    # obvious level keyword, so detect it here. Without this, a query like
    # "show errors in last 24 hours" returns INFO logs because the LLM left
    # level=None.
    if not filters.get("level"):
        q_lower = natural_query.lower()
        if any(w in q_lower for w in ["error", "errors", "failure", "failures", "failed", "exception"]):
            filters["level"] = "ERROR"
        elif any(w in q_lower for w in ["warn", "warns", "warning", "warnings"]):
            filters["level"] = "WARN"

    # The UI dropdown is an explicit control — it must win over whatever the
    # LLM guessed from the query text. Otherwise a query like "show errors in
    # last 24 hours" beats the user's "Last 15 Minutes" dropdown selection.
    if time_range is not None:
        try:
            filters["hoursAgo"] = float(time_range)
        except (TypeError, ValueError):
            pass

    print(f"[analyze] Parsed filters: {filters}")

    # ── Step 2: Fetch logs from Spring Boot ───────────────────
    logs = fetch_logs_from_backend(filters, auth_header, source)
    print(f"[analyze] Fetched {len(logs)} logs from backend")

    if not logs:
        return jsonify({
            "filters": filters,
            "logs": [],
            "clusters": [],
            "summary": "No logs found matching your query. Try adjusting the time range or filters.",
            "total": 0
        })

    # ── Step 3: Generate embeddings (only for ERROR/WARN logs) ─
    # Embedding all logs would be expensive — focus on errors
    error_logs = [l for l in logs if l.get("level") in ["ERROR", "WARN"]]
    logs_to_embed = error_logs if error_logs else logs[:50]

    clusters = []
    if len(logs_to_embed) >= 2:  # need at least 2 logs to cluster
        messages = [log.get("message", "") for log in logs_to_embed]
        embeddings = get_embeddings(messages)

        # ── Step 4: Cluster logs ───────────────────────────────
        if len(embeddings) > 0:
            clusters = cluster_logs(logs_to_embed, embeddings)
            print(f"[analyze] Created {len(clusters)} clusters")

    # ── Step 5: Generate root cause summary ───────────────────
    summary = generate_summary(logs)
    print(f"[analyze] Summary generated")

    # ── Step 6: Build frequency data for chart ────────────────
    frequency_data = build_frequency_data(logs)

    return jsonify({
        "filters": filters,
        "logs": logs,
        "clusters": clusters,
        "summary": summary,
        "total": len(logs),
        "frequency": frequency_data
    })


# ─────────────────────────────────────────────────────────────
# GET /health
# ─────────────────────────────────────────────────────────────
@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "UP", "service": "log-intelligence-ai"})


# ─────────────────────────────────────────────────────────────
# Helper functions
# ─────────────────────────────────────────────────────────────

def fetch_logs_from_backend(filters: dict, auth_header: str = "", source: str = None) -> list:
    """
    Calls the Spring Boot Search API with structured filters.
    Forwards the user's JWT (auth_header) so backend RBAC applies.
    If `source` is one of SOURCE_SERVICE_MAP, scopes the query to those
    service-name prefixes via the backend's servicePatterns param.
    Returns a list of log dicts.
    """
    params = {}

    if filters.get("level"):
        params["level"] = filters["level"]
    if filters.get("service"):
        params["service"] = filters["service"]
    if filters.get("keyword"):
        params["keyword"] = filters["keyword"]
    if filters.get("hoursAgo"):
        params["hoursAgo"] = filters["hoursAgo"]

    # Scope by source-category page (System Logs, Docker Logs, etc.)
    # Don't override an explicit service= filter the LLM extracted.
    if source and source in SOURCE_SERVICE_MAP and "service" not in params:
        params["servicePatterns"] = ",".join(SOURCE_SERVICE_MAP[source])

    headers = {}
    if auth_header:
        headers["Authorization"] = auth_header

    try:
        response = requests.get(
            f"{SPRING_BACKEND_URL}/api/logs/search",
            params=params,
            headers=headers,
            timeout=10  # don't wait more than 10 seconds
        )
        response.raise_for_status()
        data = response.json()
        return data.get("logs", [])

    except requests.exceptions.ConnectionError:
        print("[fetch_logs] Cannot connect to Spring Boot backend")
        return []
    except requests.exceptions.Timeout:
        print("[fetch_logs] Spring Boot backend timed out")
        return []
    except Exception as e:
        print(f"[fetch_logs] Error: {e}")
        return []


def build_frequency_data(logs: list) -> list:
    """
    Builds hourly frequency data for the error chart.
    Groups error/warn logs by hour for the last 24 hours.

    Returns list of dicts: [{ "hour": "14:00", "errors": 5, "warnings": 2 }, ...]
    """
    from collections import defaultdict
    from datetime import datetime, timezone

    hourly = defaultdict(lambda: {"errors": 0, "warnings": 0})

    for log in logs:
        level = log.get("level", "")
        if level not in ["ERROR", "WARN"]:
            continue

        timestamp_str = log.get("timestamp", "")
        if not timestamp_str:
            continue

        try:
            # Parse ISO timestamp
            if timestamp_str.endswith("Z"):
                timestamp_str = timestamp_str[:-1] + "+00:00"
            dt = datetime.fromisoformat(timestamp_str)
            hour_key = dt.strftime("%H:00")

            if level == "ERROR":
                hourly[hour_key]["errors"] += 1
            elif level == "WARN":
                hourly[hour_key]["warnings"] += 1

        except Exception:
            continue

    # Convert to sorted list
    result = [
        {"hour": hour, "errors": counts["errors"], "warnings": counts["warnings"]}
        for hour, counts in sorted(hourly.items())
    ]

    return result


# ─────────────────────────────────────────────────────────────
if __name__ == "__main__":
    port = int(os.getenv("FLASK_PORT", 5000))
    print(f"\nAI Service running on http://localhost:{port}\n")
    app.run(debug=True, port=port)