# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Architecture

Log Intelligence is a microservice system for AI-powered log analysis:

```
Frontend (React/Vite :5173)
    → POST /analyze (JWT in Authorization header) →
AI Service (Python/Flask :5000)
    → GET /api/logs/search (forwards JWT) →
Backend (Spring Boot :8080)
    ↔ Kafka (:9092) ↔ Elasticsearch (:9200)
    ↔ MongoDB (:27017)   (user accounts only)
```

**Data flow**: All logs come from the `log-collectors` service — it tails real sources (files, Windows events, nginx/apache access logs, GitHub Actions, MariaDB/Postgres, Docker containers) and pushes `LogEntry` JSON to the Kafka `app-logs` topic. The backend's `LogConsumerService` indexes everything to Elasticsearch. The backend ALSO uses MongoDB for the `users` collection (auth/RBAC); logs themselves are not in Mongo. The Python AI service receives a natural language query plus a `source` category (e.g. `"system"`, `"docker"`) from the frontend, parses the query into structured filters (LLM + keyword-based level fallback), maps `source` to service-name prefixes via `SOURCE_SERVICE_MAP`, forwards the user's JWT to the backend, fetches matching logs, generates embeddings, clusters them via K-Means, then returns a root cause summary.

> **There is no `LogProducerService`** — the backend does not generate synthetic logs. If `log-collectors` isn't running, Elasticsearch will only contain historical data and the dashboard will look empty.

## Starting the System

**Shortcut**: run each of these in its own PowerShell window from the repo root, in order:

```powershell
scripts\start-infra.ps1        # Terminal 1: docker (Kafka, ZK, ES, Kibana, Mongo)
scripts\start-backend.ps1      # Terminal 2: Spring Boot — builds JAR on first run
scripts\start-ai.ps1           # Terminal 3: Python AI service
scripts\start-frontend.ps1     # Terminal 4: Vite dev server
scripts\start-collectors.ps1   # Terminal 5: log-collectors (required)
```

Each script encapsulates the env-var loading, the `java -jar` workaround, and the venv handling. If you get a "running scripts is disabled" error, run once: `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`.

---

`docker-compose.yml` defines 9 services (infra + 4 app services + log-collectors), but only `log-collectors/Dockerfile` exists — the backend / ai-service / frontend Dockerfiles are missing, so `docker compose up -d` for the whole stack will fail. **Use hybrid mode**: infra in Docker, app services on the host.

Start in this order:

```bash
# 1. Infrastructure (Zookeeper, Kafka, Elasticsearch, Kibana, MongoDB)
docker compose up -d zookeeper kafka elasticsearch kibana mongodb

# 2. Backend (wait until mongo + es + kafka all show "(healthy)")
#    On Java 25, `mvn spring-boot:run` currently crashes with
#    NoClassDefFoundError: PasswordEncoder (Lombok 1.18.44 + Java 25 bug).
#    Build a fat JAR and run it directly:
cd backend && mvn package -DskipTests
SPRING_DATA_MONGODB_URI="mongodb://$MONGO_USER:$MONGO_PASS@127.0.0.1:27017/log-intelligence?authSource=admin" \
JWT_SECRET="$JWT_SECRET" \
java -jar target/backend-0.0.1-SNAPSHOT.jar

# 3. AI Service — set PYTHONIOENCODING=utf-8 on Windows or the 🚀 print crashes it
cd ai-service && source venv/Scripts/activate   # Linux/Mac: venv/bin/activate
PYTHONIOENCODING=utf-8 python app.py

# 4. Frontend
cd frontend && npm run dev

# 5. Log Collectors — REQUIRED, not optional. Without this, no new logs flow.
cd log-collectors && source venv/Scripts/activate
python main.py                          # start all enabled collectors
python main.py --collector file_watcher # start only one collector
```

Access the UI at `http://localhost:5173`. First-time users must register at the signup screen — accounts are stored in MongoDB.

## Service Commands

### Frontend (`/frontend`)
```bash
npm install          # install deps
npm run dev          # dev server with hot reload
npm run build        # production bundle → dist/
npm run preview      # preview production build
```

### AI Service (`/ai-service`)
```bash
python -m venv venv
pip install -r requirements.txt
python app.py        # or: flask run --port 5000
```

### Backend (`/backend`)
```bash
mvn spring-boot:run          # run dev server
mvn test                     # run unit tests
mvn package -DskipTests      # fast build, skip tests
mvn clean install            # full build + test + package
java -jar target/backend-0.0.1-SNAPSHOT.jar  # run packaged JAR
```

## Configuration

### Repo root — `.env` (required, gitignored)
Used by both `docker-compose.yml` and the backend (when started on the host). Generate fresh values; **the mongo-data volume bakes in MONGO_PASS on first init — changing it later means resetting the volume or doing a `db.changeUserPassword` reset**.
```
MONGO_USER=logadmin
MONGO_PASS=<strong random>     # python -c "import secrets; print(secrets.token_urlsafe(24))"
JWT_SECRET=<>= 64 chars>       # python -c "import secrets; print(secrets.token_urlsafe(64))"
GROQ_API_KEY=gsk_...
CORS_ORIGINS=http://localhost
GITHUB_TOKEN=...               # optional, for github_actions collector
```

### Backend — `backend/src/main/resources/application.properties`
Key settings: `server.port=8080`, `spring.kafka.bootstrap-servers=localhost:9092`, `elasticsearch.host=localhost`, `elasticsearch.port=9200`, `spring.data.mongodb.uri=mongodb://127.0.0.1:27017/log-intelligence` (default, no auth — **override `SPRING_DATA_MONGODB_URI` env var when running on host because the docker mongo container requires auth**).

### AI Service — `ai-service/.env`
```
OPENAI_API_KEY=sk-proj-...
GROQ_API_KEY=gsk_...
SPRING_BACKEND_URL=http://localhost:8080
FLASK_PORT=5000
```

### Frontend — `frontend/.env`
```
VITE_AI_SERVICE_URL=http://localhost:5000
```

### Log Collectors (`/log-collectors`)
```bash
pip install -r requirements.txt
python main.py                           # start all enabled collectors
python main.py --collector file_watcher  # start only file watcher
python main.py --collector docker        # start only docker collector
```
Configure collectors in `log-collectors/config.yaml` — each has an `enabled` flag. Secrets (GitHub tokens, DB passwords) go in `log-collectors/.env`.

## Key Code Locations

| Concern | File |
|---------|------|
| AI pipeline entry point | `ai-service/app.py` (POST `/analyze`) |
| Query parsing (NLP → filters) | `ai-service/query_parser.py` |
| Log embeddings | `ai-service/embeddings.py` |
| K-Means clustering | `ai-service/clustering.py` |
| Root cause summarization | `ai-service/summarizer.py` |
| Auth + JWT + RBAC | `backend/src/main/java/com/logintel/auth/*` |
| Spring Security config | `backend/src/main/java/com/logintel/config/SecurityConfig.java` |
| Kafka → Elasticsearch indexing | `backend/.../LogConsumerService.java` |
| Elasticsearch query builder | `backend/.../LogSearchService.java` |
| REST search API | `backend/.../LogSearchController.java` (GET `/api/logs/search`) |
| Log data model | `backend/.../LogEntry.java` |
| Frontend API client | `frontend/src/logApi.js` |
| Log collector base class | `log-collectors/base_collector.py` |
| Collector entry point | `log-collectors/main.py` |
| Collector config | `log-collectors/config.yaml` |
| File watcher collector | `log-collectors/collectors/file_watcher.py` |
| Windows event collector | `log-collectors/collectors/windows_event.py` |
| Web server log collector | `log-collectors/collectors/web_server.py` |
| GitHub Actions collector | `log-collectors/collectors/github_actions.py` |
| Database log collector | `log-collectors/collectors/database.py` |
| Docker log collector | `log-collectors/collectors/docker_logs.py` |
| Access log parser (CLF) | `log-collectors/parsers/common_log_format.py` |

## Backend REST API

All `/api/logs/**` endpoints (except `/health`) require a JWT in `Authorization: Bearer <token>`. The AI service must forward the caller's Authorization header — without it the backend returns 403 and the dashboard silently shows "No logs found".

`GET /api/logs/search` accepts query params: `level`, `service`, `servicePatterns` (comma-separated prefix list — used for source-category scoping), `keyword`, `hoursAgo`. Returns up to 200 `LogEntry` records sorted newest-first. Each `LogEntry` has: `id`, `service`, `level`, `message`, `timestamp`, `host`, `traceId`. RBAC is enforced in `LogSearchService` — the role from the JWT restricts which service prefixes can be queried.

`GET /api/logs/services` returns `{"services": [...]}` filtered by the caller's role. Used by the AI service for dynamic service discovery.

`POST /api/auth/register`, `POST /api/auth/login`, `GET /api/auth/me`, `GET /api/auth/roles` — public auth endpoints. Users are stored in MongoDB `users` collection with BCrypt-hashed passwords.

## AI Service Pipeline

POST `/analyze` with `{"query": "show payment service errors in last 6 hours", "source": "system"}` and an `Authorization: Bearer <jwt>` header:
1. **Forward the caller's `Authorization` header to the backend.** Without it, backend → 403 → empty result.
2. `query_parser.py` → LLM → `{level, service, hoursAgo, keyword, intent}`
3. **Keyword-based level fallback**: if the LLM left `level=None` but the query contains "error"/"errors"/"failure"/"exception", coerce `level="ERROR"`. Same for "warn"/"warning" → `WARN`. The LLM often misses these.
4. Map `source` → `servicePatterns` via `SOURCE_SERVICE_MAP` (e.g. `"system"` → `["windows-event"]`). Forwarded to backend as comma-separated prefixes so each category page only shows its own collector's logs.
5. Fetch logs from backend REST API
6. `embeddings.py` on error/warning logs
7. `clustering.py` → K-Means clusters by semantic similarity
8. `summarizer.py` → root cause summary
9. Return clusters + summary to frontend

## Log Collectors

Six Python-based collectors in `log-collectors/` push real logs to the same Kafka `app-logs` topic. Each inherits from `BaseCollector` which handles Kafka producing and LogEntry JSON formatting.

| Collector | Source | Service Name | Level Mapping |
|-----------|--------|--------------|---------------|
| File Watcher | Tails log files via `watchdog` | Configurable | DEBUG/TRACE→INFO, WARNING→WARN, CRITICAL/FATAL→ERROR |
| Windows Event | Polls Event Viewer via `pywin32` | `windows-event-{type}` | EventType mapping |
| Web Server | Tails nginx/apache access logs | `nginx` / `apache` | HTTP 2xx/3xx→INFO, 4xx→WARN, 5xx→ERROR |
| GitHub Actions | Polls GitHub API | `github-actions-{repo}` | success→INFO, cancelled→WARN, failure→ERROR |
| Database | Tails MySQL/PostgreSQL logs | `mysql` / `postgresql` | Parsed from log level prefix |
| Docker | Streams via Docker SDK | `docker-{container}` | Extracted from log line content |

All collectors are configured in `log-collectors/config.yaml` with individual `enabled` flags. The AI service's `query_parser.py` dynamically fetches the service list from `GET /api/logs/services` every 5 minutes.

## Gotchas

Things that have caused multi-hour debugging in this repo — check these first when something is off.

- **`mvn spring-boot:run` crashes on Java 25** with `NoClassDefFoundError: PasswordEncoder`. Lombok 1.18.44 emits bytecode that breaks under Java 25's reflective class loading. Workaround: `mvn package -DskipTests && java -jar target/backend-0.0.1-SNAPSHOT.jar`. The packaged JAR runs fine. Long-term fix: bump Lombok or use Java 21.
- **`docker compose up -d` (full stack) fails**: only `log-collectors/Dockerfile` exists; the backend/ai-service/frontend Dockerfiles are missing. Use hybrid mode (see "Starting the System") until the missing Dockerfiles are added.
- **MongoDB credential mismatch after changing `.env`**: Mongo only reads `MONGO_INITDB_ROOT_*` on first volume init. Changing `MONGO_PASS` later leaves the volume's stored hash unchanged and every connection fails with `SCRAM authentication failed, storedKey mismatch`. Either change `.env` back to the original password, do `db.changeUserPassword()` via `--noauth`, or wipe `log-intelligence_mongo-data` volume (loses all user accounts).
- **Dashboard shows "No logs found" for every query**: the AI service must (a) forward the caller's `Authorization` header to backend, (b) honor the `source` field on the request to scope by service-name prefix, and (c) honor the `timeRange` field from the UI dropdown — it must override the LLM-extracted `hoursAgo` because the dropdown is an explicit user control. All three behaviors are easy to drop during refactors — see `ai-service/app.py:analyze` and `SOURCE_SERVICE_MAP`.
- **LLM query parser misses level keywords**: queries like "show errors in last 24 hours" come back with `level=None` from the parser. Keep the keyword-based level fallback in `analyze()` — without it the user sees INFO logs instead of zero ERROR logs.
- **AI service crashes on startup with `UnicodeEncodeError: '\U0001f680'`** (the `🚀` print at the bottom of `app.py`) on Windows. Run with `PYTHONIOENCODING=utf-8`.
- **`logs/nginx-frontend/access.log` stays empty**: that path is only written when the frontend runs in the dockerized nginx container, not when run via `npm run dev`. The `nginx` collector will sit idle in hybrid mode — expected.
- **Empty dashboard after a fresh start**: `log-collectors` is REQUIRED, not optional. There is no `LogProducerService` despite earlier docs claiming otherwise. If collectors aren't running, ES will only contain whatever was indexed in previous sessions.
