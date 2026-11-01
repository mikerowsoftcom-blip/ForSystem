import os, json, sqlite3, re, math, requests
from collections import Counter
from flask import Flask, request, jsonify, render_template_string
from flask_cors import CORS

app = Flask(__name__)
CORS(app)  # Allow the standalone HTML frontend to call this API.
DB_PATH = os.getenv('DB_PATH', 'ali_memory.db')
# Hosted inference through Groq (OpenAI-independent). Set GROQ_API_KEY in Render.
GROQ_API_KEY = os.getenv('GROQ_API_KEY', '').strip()
GROQ_URL = 'https://api.groq.com/openai/v1/chat/completions'
LLM_MODEL = os.getenv('LLM_MODEL', 'llama-3.3-70b-versatile')

# Lightweight local semantic associations; no sentence_transformers/numpy required.
ASSOCIATIONS = {
    'problem':['challenge','issue','obstacle','difficulty'], 'goal':['target','desired','objective','aim'],
    'plan':['strategy','steps','approach','method'], 'learn':['experience','memory','practice','feedback'],
    'failure':['mistake','error','risk','loss'], 'success':['solution','result','improvement','win'],
    'cause':['reason','source','because','driver'], 'effect':['result','consequence','outcome'],
    'repair':['fix','restore','recover','improve'], 'build':['create','construct','develop','make'],
    'adapt':['change','adjust','modify','flex'], 'conflict':['disagreement','tension','competition'],
    'resource':['tool','asset','support','material'], 'time':['deadline','duration','schedule','urgency']
}

def init_db():
    with sqlite3.connect(DB_PATH) as con:
        con.execute('''CREATE TABLE IF NOT EXISTS experiences (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            problem TEXT, logical_statement TEXT, abstract_pattern TEXT,
            analogy TEXT, solution TEXT, outcome TEXT, embedding TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
init_db()

def tokenize(text):
    return re.findall(r"[a-zA-Z0-9']+", (text or '').lower())

def embed(text):
    tokens = tokenize(text)
    counts = Counter(tokens)
    for token in tokens:
        for key, related in ASSOCIATIONS.items():
            if token == key:
                counts.update(related)
            for r in related:
                if token == r:
                    counts[key] += 1
    return dict(counts)

def cosine(a, b):
    common = set(a) & set(b)
    dot = sum(a[k]*b[k] for k in common)
    na = math.sqrt(sum(v*v for v in a.values()))
    nb = math.sqrt(sum(v*v for v in b.values()))
    return dot/(na*nb) if na and nb else 0.0

def retrieve_memories(problem, limit=3):
    query = embed(problem)
    with sqlite3.connect(DB_PATH) as con:
        rows = con.execute('SELECT problem, logical_statement, abstract_pattern, analogy, solution, outcome, embedding FROM experiences').fetchall()
    scored=[]
    for row in rows:
        try: vec=json.loads(row[6])
        except Exception: vec={}
        scored.append((cosine(query, vec), row[:6]))
    scored.sort(key=lambda x:x[0], reverse=True)
    return [r for score,r in scored[:limit] if score>0]

def call_llm(messages):
    if not GROQ_API_KEY:
        raise RuntimeError('GROQ_API_KEY is missing. Add your Groq API key in Render → Environment.')

    # Try configured model first, then fallback candidates. Groq availability changes,
    # so the list is environment-configurable rather than hard-coded as guaranteed.
    configured = os.getenv("LLM_MODEL", LLM_MODEL).strip()
    fallback_csv = os.getenv(
        "LLM_FALLBACK_MODELS",
        "llama-3.1-8b-instant,openai/gpt-oss-20b,qwen/qwen3-32b"
    )
    models = []
    for model in [configured] + [m.strip() for m in fallback_csv.split(",")]:
        if model and model not in models:
            models.append(model)

    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json"
    }
    errors = []
    for model in models:
        payload = {
            "model": model,
            "messages": messages,
            "temperature": 0.3,
            "stream": False
        }
        try:
            response = requests.post(GROQ_URL, json=payload, headers=headers, timeout=120)
            if response.ok:
                body = response.json()
                content = body.get("choices", [{}])[0].get("message", {}).get("content")
                if content:
                    return content
                errors.append(f"{model}: empty response")
                continue

            # Retry another model only for model availability/name errors.
            try:
                err = response.json().get("error", {})
                code = str(err.get("code", ""))
                message = str(err.get("message", response.text[:400]))
            except Exception:
                code, message = "", response.text[:400]

            if response.status_code in (400, 404) and (
                "model_not_found" in code.lower()
                or "does not exist" in message.lower()
                or "do not have access" in message.lower()
                or "model" in message.lower()
            ):
                errors.append(f"{model}: unavailable ({response.status_code})")
                continue

            response.raise_for_status()
            errors.append(f"{model}: HTTP {response.status_code} {message}")
            break

        except requests.RequestException as exc:
            errors.append(f"{model}: connection error: {exc}")
            break

    raise RuntimeError(
        "Groq inference failed for all attempted models: "
        + "; ".join(errors)
        + ". In Render Environment, set LLM_MODEL to a model currently listed "
          "in your Groq console, or edit LLM_FALLBACK_MODELS."
    )

def parse_json_or_text(text):
    text=text.strip()
    match=re.search(r'\{.*\}', text, re.S)
    if match:
        try: return json.loads(match.group(0))
        except json.JSONDecodeError: pass
    return {'response':text}

def ali_think(problem, desired_state='solve the problem'):
    memories=retrieve_memories(problem)
    memory_text=json.dumps(memories, ensure_ascii=False) if memories else 'No relevant past experiences stored yet.'
    prompt=f'''You are A.L.I. (Analogical Logic Intelligence), an experimental reasoning assistant.
Analyze the current problem by connecting it to useful prior patterns and reasoning logically.
Return valid JSON with keys: logical_statement, abstract_pattern, analogy, solution, actions (array of short sequential actions), assumptions.
Problem: {problem}
Desired state: {desired_state}
Relevant stored experiences: {memory_text}
Keep actions concrete and safe. Do not claim certainty when information is missing.'''
    raw=call_llm([{'role':'system','content':'You are A.L.I. Return only valid JSON.'},{'role':'user','content':prompt}])
    result=parse_json_or_text(raw)
    if 'response' in result:
        result.update({'logical_statement':'','abstract_pattern':'','analogy':'','solution':raw,'actions':[],'assumptions':[]})
    save_experience(problem, result)
    return result

def save_experience(problem, result, outcome='pending'):
    logical=result.get('logical_statement','')
    pattern=result.get('abstract_pattern','')
    analogy=result.get('analogy','')
    solution=result.get('solution','')
    vec=json.dumps(embed(problem+' '+logical+' '+pattern))
    with sqlite3.connect(DB_PATH) as con:
        con.execute('INSERT INTO experiences(problem,logical_statement,abstract_pattern,analogy,solution,outcome,embedding) VALUES(?,?,?,?,?,?,?)',
                   (problem,logical,pattern,analogy,solution,outcome,vec))

HTML='''<!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1"><title>A.L.I.</title><style>body{font:16px system-ui;max-width:760px;margin:30px auto;padding:0 16px;background:#10151d;color:#eaf0f8}textarea,input{width:100%;box-sizing:border-box;padding:12px;margin:8px 0;background:#202936;color:white;border:1px solid #526174;border-radius:8px}button{padding:12px 18px;background:#7dd3fc;border:0;border-radius:8px;font-weight:bold}pre{white-space:pre-wrap;background:#202936;padding:14px;border-radius:8px}</style></head><body><h1>A.L.I.</h1><p>Analogical Logic Intelligence — reason by patterns, analogy, and actions.</p><form id="f"><label>Current problem</label><textarea id="problem" rows="5" required placeholder="Describe the problem..."></textarea><label>Desired state</label><input id="goal" value="solve the problem"><button>Think</button></form><h2>Result</h2><pre id="result">Your analysis will appear here.</pre><script>document.getElementById('f').onsubmit=async e=>{e.preventDefault();let r=document.getElementById('result');r.textContent='Thinking…';try{let x=await fetch('/think',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({problem:document.getElementById('problem').value,desired_state:document.getElementById('goal').value})});let j=await x.json();r.textContent=JSON.stringify(j,null,2)}catch(err){r.textContent=String(err)}};</script></body></html>'''

@app.get('/')
def home(): return render_template_string(HTML)

@app.post('/think')


# Friendly Idea Help Bot chat endpoint. It receives only user-entered text;
# it does not query or access the website's ideas database.
@app.route('/v1/chat/completions', methods=['POST'])
def idea_help_chat():
    payload = request.get_json(silent=True) or {}
    messages = payload.get('messages') or []
    user_message = next((m.get('content','') for m in reversed(messages)
                        if m.get('role') == 'user'), '')
    if not isinstance(user_message, str) or not user_message.strip():
        return jsonify({'error':'Please enter a message.'}), 400

    system_prompt = (
        "You are Idea Help Bot, a friendly, natural, encouraging creativity mentor "
        "for a school innovation website. Discuss AI, Atal Tinkering Labs (ATL), "
        "INSPIRE-MANAK, science, engineering, robotics, innovation, ideation, "
        "prototyping, and entrepreneurship. PRIVACY: You have NO access to this "
        "website's ideas database, submitted ideas, private/public ideas, or student "
        "project records. Evaluate only the idea or text the user explicitly shares. "
        "Respond directly and conversationally. Never narrate your internal process "
        "or say 'The user has asked hello, I must reply', 'User wants...', or similar. "
        "Do not expose chain-of-thought. Greet normally. For ideas, give constructive "
        "feedback on creativity, innovativeness, potential impact, feasibility, and "
        "possible improvements. Be a supportive mentor, not a judge. Never claim "
        "absolute originality. If asked about current facts or existing inventions, "
        "be honest if web research is unavailable."
    )
    groq_messages = [{'role':'system','content':system_prompt},
                     {'role':'user','content':user_message}]
    result = call_llm(groq_messages)
    if isinstance(result, tuple):
        # Some implementations return (content, model); normalize safely.
        answer = result[0]
    else:
        answer = result
    if isinstance(answer, dict):
        answer = answer.get('content') or answer.get('message') or str(answer)
    return jsonify({'choices':[{'message':{'role':'assistant','content':str(answer)}}]})

def think():
    data=request.get_json(silent=True) or {}
    problem=str(data.get('problem','')).strip()
    goal=str(data.get('desired_state','solve the problem')).strip()
    if not problem: return jsonify({'error':'Please enter a problem.'}),400
    try: return jsonify(ali_think(problem,goal))
    except RuntimeError as e: return jsonify({'error':str(e)}),503
    except Exception as e: return jsonify({'error':f'Unexpected error: {e}'}),500

@app.get('/health')
def health(): return jsonify({'status':'ok','model':LLM_MODEL,'ollama_url_configured':bool(OLLAMA_URL)})

if __name__=='__main__':
    app.run(host='0.0.0.0',port=int(os.getenv('PORT','5000')))
