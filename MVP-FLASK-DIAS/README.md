# MVP-FLASK-DIAS

Clean Flask port of the DaiS MVP with the same chat UI and RAG behavior.

## What Is Included

- Flask API endpoints: `/`, `/health`, `/ingest`, `/chat`, `/ask`, `/find`
- Ollama + Qdrant integration
- Same UI controls from the FastAPI MVP (Top K, strictness, score threshold, answer style)
- Citation-friendly evidence cards

## Run

From this directory:

```powershell
docker compose up --build -d
```

Open: `http://localhost:8081/`

## Notes

- Docs are mounted from `../docs`.
- If you change embedding model, run ingest again.
- This project is intentionally separate from your FastAPI MVP so demos stay stable.
