import os, json, sqlite3, re, math, requests
from collections import Counter
from flask import Flask, request, jsonify, render_template_string

app = Flask(__name__)
DB_PATH = os.getenv('DB_PATH', 'ali_memory.db')
OLLAMA_URL = os.getenv('OLLAMA_URL', 'http://localhost:11434/api/chat').rstrip('/')
LLM_MODEL = os.getenv('LLM_MODEL', 'qwen2.5:7b')

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
    payload={'model':LLM_MODEL,'messages':messages,'stream':False}
    try:
        response=requests.post(OLLAMA_URL, json=payload, timeout=120)
        response.raise_for_status()
        return response.json()['message']['content']
    except requests.RequestException as e:
        raise RuntimeError(f'LLM endpoint unavailable ({OLLAMA_URL}): {e}. Set OLLAMA_URL to a reachable Ollama-compatible /api/chat endpoint.')

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
