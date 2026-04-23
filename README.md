# Flask Documentation Starter (No Auth)

Restructured Flask app with:

- Application factory (`create_app`)
- Blueprint-based routing (`web`, `api`)
- Service layer for RAG/Ollama/Qdrant logic
- Vite + Tailwind frontend workspace

## Project Layout

```text
DockerAiRag/
  app.py
  dais_app/
    __init__.py
    config.py
    errors.py
    blueprints/
      api/routes.py
      web/routes.py
    services/rag.py
    templates/index.html
    static/dist/
  frontend/
    package.json
    vite.config.js
    tailwind.config.js
    postcss.config.js
    src/main.js
    src/main.css
```

## API Surface

All API routes are now namespaced under `/api`:

- `GET /api/health`
- `POST /api/setup-models`
- `GET /api/ingested-docs`
- `POST /api/ingest`
- `POST /api/chat`
- `POST /api/ask`
- `GET /api/find`

UI route:

- `GET /`

## Run With Docker (Backend + fallback static assets)

```powershell
docker compose up --build -d
```

Open: `http://localhost:8081/`

`docker compose build` now also runs the Vite/Tailwind production build in a Node stage and copies the compiled assets into `dais_app/static/dist`.

## Model Setup (Ollama)

On first run, you must have both models available in Ollama:

- Embedding model: `nomic-embed-text`
- Generation model: `dolphin3:latest` (or your configured `MODEL_NAME`)

Ways to set them up:

- In the UI, click **Setup Models**.
- API call: `POST /api/setup-models`

If a request hits a missing-model error, the backend now attempts a one-time automatic pull and retries.

## Run Frontend In Vite Dev Mode

1. Install frontend dependencies:

```powershell
cd frontend
npm install
```

2. Start Vite:

```powershell
npm run dev
```

3. Run Flask with Vite dev enabled:

```powershell
$env:FRONTEND_USE_VITE_DEV="true"
$env:VITE_DEV_SERVER="http://localhost:5173"
python app.py
```

## Build Frontend Assets

```powershell
cd frontend
npm run build
```

This writes built assets to `frontend/dist` (including Vite manifest).

## Environment Variables

- `OLLAMA_BASE_URL` (default: `http://ollama:11434`)
- `QDRANT_URL` (default: `http://qdrant:6333`)
- `MODEL_NAME` (default: `dolphin3:latest`)
- `EMBED_MODEL` (default: `nomic-embed-text`)
- `DOCS_PATH` (default: `/data/docs`)
- `COLLECTION_NAME` (default: `dais_docs_v3`)
- `FRONTEND_USE_VITE_DEV` (`true` or `false`)
- `VITE_DEV_SERVER` (default: `http://localhost:5173`)
