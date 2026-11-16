import json, os, sqlite3
from contextlib import contextmanager
from pathlib import Path
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field
app=FastAPI(title='AgentHub Rules API',version='1.0.0')
@contextmanager
def conn():
    db=sqlite3.connect(os.getenv('DATABASE_PATH','app.db'));db.row_factory=sqlite3.Row
    try:yield db;db.commit()
    finally:db.close()
with conn() as db:db.executescript("""CREATE TABLE IF NOT EXISTS agents(id INTEGER PRIMARY KEY,name TEXT NOT NULL,description TEXT NOT NULL DEFAULT '',fallback TEXT NOT NULL,rules_json TEXT NOT NULL,created_at TEXT DEFAULT CURRENT_TIMESTAMP);CREATE TABLE IF NOT EXISTS executions(id INTEGER PRIMARY KEY,agent_id INTEGER NOT NULL,input_text TEXT NOT NULL,matched_keyword TEXT,output_text TEXT NOT NULL,created_at TEXT DEFAULT CURRENT_TIMESTAMP);""")
class Rule(BaseModel):
    keyword:str=Field(min_length=1)
    response:str=Field(min_length=1)
class Agent(BaseModel):
    name:str=Field(min_length=1)
    description:str=''
    fallback:str=Field(min_length=1)
    rules:list[Rule]=Field(min_length=1)
class Run(BaseModel):
    text:str=Field(min_length=1)
def get_agent(db,id):
    row=db.execute('SELECT * FROM agents WHERE id=?',(id,)).fetchone()
    if row is None:raise HTTPException(404,'Agent not found')
    return {**dict(row),'rules':json.loads(row['rules_json'])}
@app.get('/api/agents')
def agents():
    with conn() as db:return [get_agent(db,r['id']) for r in db.execute('SELECT id FROM agents ORDER BY id DESC').fetchall()]
@app.post('/api/agents',status_code=201)
def create_agent(agent:Agent):
    with conn() as db:
        c=db.execute('INSERT INTO agents(name,description,fallback,rules_json) VALUES(?,?,?,?)',(agent.name,agent.description,agent.fallback,json.dumps([r.model_dump() for r in agent.rules])))
        return get_agent(db,c.lastrowid)
@app.get('/api/agents/{id}')
def agent(id:int):
    with conn() as db:return get_agent(db,id)
@app.post('/api/agents/{id}/run')
def run(id:int,payload:Run):
    with conn() as db:
        a=get_agent(db,id);matched=next((r for r in a['rules'] if r['keyword'].lower() in payload.text.lower()),None)
        answer=matched['response'] if matched else a['fallback']
        c=db.execute('INSERT INTO executions(agent_id,input_text,matched_keyword,output_text) VALUES(?,?,?,?)',(id,payload.text,matched['keyword'] if matched else None,answer))
        return {'execution_id':c.lastrowid,'matched_keyword':matched['keyword'] if matched else None,'output':answer}
@app.get('/api/agents/{id}/runs')
def history(id:int):
    with conn() as db:
        get_agent(db,id)
        return [dict(r) for r in db.execute('SELECT * FROM executions WHERE agent_id=? ORDER BY id DESC LIMIT 100',(id,))]
@app.get('/',response_class=HTMLResponse)
def home():return Path(__file__).with_name('index.html').read_text(encoding='utf8')

@app.get('/api/health')
def health():
    return {'status':'ok'}
@app.get('/api/insights')
def insights():
    with conn() as db:
        return {'agents':db.execute('SELECT COUNT(*) FROM agents').fetchone()[0],'executions':db.execute('SELECT COUNT(*) FROM executions').fetchone()[0],'matched_executions':db.execute('SELECT COUNT(*) FROM executions WHERE matched_keyword IS NOT NULL').fetchone()[0]}

@app.middleware('http')
async def security_headers(request,call_next):
    response=await call_next(request)
    response.headers['X-Content-Type-Options']='nosniff'
    response.headers['Referrer-Policy']='no-referrer'
    response.headers['X-Frame-Options']='DENY'
    return response

# Local demos work without credentials. Production APIs require an explicit token.
import hmac
from fastapi.responses import JSONResponse

@app.middleware('http')
async def require_api_auth(request, call_next):
    path = request.url.path
    if path.startswith('/api/') and path != '/api/health':
        token = os.getenv('API_TOKEN')
        if os.getenv('APP_ENV') == 'production' or token:
            if not token:
                return JSONResponse({'error': 'API authentication must be configured in production'}, status_code=503)
            if not hmac.compare_digest(request.headers.get('x-api-token', ''), token):
                return JSONResponse({'error': 'Unauthorized'}, status_code=401)
    return await call_next(request)



@app.get('/api/export/agents.csv')
def export_agents_csv():
    """Download a read-only snapshot of the local demo dataset."""
    from fastapi.responses import Response
    from data_export import serialize_csv
    with conn() as connection:
        cursor = connection.execute("SELECT id,name,description,fallback,created_at FROM agents ORDER BY id")
        columns = [column[0] for column in cursor.description]
        content = serialize_csv(cursor.fetchall(), columns)
    return Response(content=content, media_type='text/csv; charset=utf-8',
                    headers={'Content-Disposition':'attachment; filename="agents.csv"',
                             'Cache-Control':'no-store'})
