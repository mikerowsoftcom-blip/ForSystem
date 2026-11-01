# A.L.I. — Analogical Logic Intelligence (Render starter)

Flask web interface + SQLite experience memory + Ollama-compatible chat endpoint. No OpenAI API and no `sentence_transformers`/NumPy dependency.

## Important: configure an inference server
Render does **not** run Ollama automatically. Before `/think` can work, configure `OLLAMA_URL` in Render to a reachable Ollama-compatible endpoint ending in `/api/chat`, and ensure the selected model is available there. Do not expose a home computer's Ollama port publicly without authentication/TLS or a secure tunnel.

## Deploy
1. Put these files in a GitHub repository.
2. In Render, choose **New → Blueprint** and connect the repository (Render reads `render.yaml`), or create a Python web service manually.
3. Add `OLLAMA_URL` as a secret/environment variable, e.g. `https://YOUR-HOST/api/chat`.
4. Deploy. Open the service URL and submit a problem.
5. Check `/health` for service status.

## Local run
```bash
python -m pip install -r requirements.txt
# Set OLLAMA_URL to your reachable endpoint first
python app.py
```

## API
`POST /think` JSON:
```json
{"problem":"A project is behind schedule","desired_state":"deliver on time"}
```
`GET /health`

## Persistence
SQLite file storage on Render Free is ephemeral; memories may disappear after restart/redeploy. For durable memory, use Render Postgres or a persistent disk (where available) and adapt the database layer.


## CORS-enabled browser interface
This package includes `flask-cors` and enables CORS in `app.py`, allowing the
standalone A.L.I. HTML client to call `POST https://forsystem.onrender.com/think`.
After committing these files to the GitHub repository connected to Render,
trigger a redeploy. Check `/health` and then test `/think`.

Note: CORS only allows the browser request to reach Flask; inference still
requires a reachable Ollama-compatible endpoint configured in `OLLAMA_URL`.
