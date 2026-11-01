# A.L.I. — Render deployment

## 1. Deploy
Push this folder's contents to the GitHub repository connected to Render.
Render build command: `pip install -r requirements.txt`
Start command: `gunicorn app:app`

## 2. Configure hosted inference (required)
This version uses **Groq hosted inference** (not OpenAI and not local Ollama).
1. Create an API key in the Groq console: https://console.groq.com/keys
2. In Render → your service → **Environment**, add:
   - `GROQ_API_KEY` = your secret key (keep private)
   - `LLM_MODEL` = `llama-3.3-70b-versatile` (default; change only to a model currently available in your Groq account)
3. Save; Render redeploys.

## 3. Test
- `https://forsystem.onrender.com/health`
- Open `ALI_Live_Interface.html`, submit a problem and desired state.

## Notes
- CORS is enabled for the standalone HTML frontend.
- A.L.I.'s analogical memory and reasoning pipeline remain in Flask.
- SQLite on Render's ephemeral filesystem can reset on deploy/restart. For persistent memory, configure a Render persistent disk or PostgreSQL.
- Do not expose or share `GROQ_API_KEY`; use Render environment variables, never hard-code it into HTML or Git.


## Automatic Groq model fallback
The backend first tries `LLM_MODEL`, then the comma-separated models in
`LLM_FALLBACK_MODELS` when Groq returns a model-not-found / access error.
Default fallbacks: `llama-3.1-8b-instant,openai/gpt-oss-20b,qwen/qwen3-32b`.
These names are not guaranteed to be enabled for every account/region; verify
current model IDs in the Groq console. You can override `LLM_FALLBACK_MODELS`
in Render Environment.
