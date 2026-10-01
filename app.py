from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from pathlib import Path
import sqlite3, json, re, os, uuid, httpx
import fitz

BASE=Path(__file__).parent
DATA=BASE/'data'; UPLOADS=BASE/'uploads'
DATA.mkdir(exist_ok=True); UPLOADS.mkdir(exist_ok=True)
DB=DATA/'recallai.db'

app=FastAPI(title='RecallAI MVP')
app.mount('/static', StaticFiles(directory=BASE/'static'), name='static')

def db():
    c=sqlite3.connect(DB)
    c.row_factory=sqlite3.Row
    c.execute('''CREATE TABLE IF NOT EXISTS documents(id TEXT PRIMARY KEY,name TEXT,text TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS decisions(id TEXT PRIMARY KEY,document_id TEXT,title TEXT,reason TEXT,alternatives TEXT,evidence TEXT,date TEXT)''')
    c.commit(); return c

def extract_pdf(path):
    doc=fitz.open(path); return '\n'.join(p.get_text() for p in doc)

def sentences(text):
    return [s.strip() for s in re.split(r'(?<=[.!?])\s+|\n+', text) if len(s.strip())>20]

def heuristic_extract(text):
    ss=sentences(text); out=[]
    patterns=[r'\bwe (?:decided|chose|selected|agreed)\s+(?:to\s+)?(.+?)(?:\.|$)',
              r'\bdecision\s*:\s*(.+?)(?:\.|$)',
              r'\bselected\s*:\s*(.+?)(?:\.|$)']
    for s in ss:
        for p in patterns:
            m=re.search(p,s,re.I)
            if m:
                title=m.group(1).strip().rstrip('.')
                reason=''
                rm=re.search(r'\b(?:because|since|as)\s+(.+)',s,re.I)
                if rm: reason=rm.group(1).strip().rstrip('.')
                out.append({'title':title[:180], 'reason':reason[:300], 'alternatives':'', 'evidence':s[:500], 'date':''})
                break
    # Also detect explicit reason/alternative statements and attach them to nearby decisions.
    for d in out:
        if not d['reason']:
            for s in ss:
                if re.search(r'\b(?:because|reason|requirement|needed)\b',s,re.I):
                    d['reason']=s[:300]; break
        alts=[s for s in ss if re.search(r'\b(?:considered|alternative|instead of|rejected)\b',s,re.I)]
        if alts: d['alternatives']=' '.join(alts[:2])[:500]
    return out

async def ollama_extract(text):
    prompt=f'''Extract decisions from this project material. Return ONLY valid JSON array. Each item keys: title, reason, alternatives, evidence, date. Do not invent facts. If no decisions, return [].\n\n{text[:12000]}'''
    try:
        async with httpx.AsyncClient(timeout=90) as client:
            r=await client.post(os.getenv('OLLAMA_URL','http://localhost:11434')+'/api/generate',json={'model':os.getenv('OLLAMA_MODEL','qwen2.5:3b'),'prompt':prompt,'stream':False,'format':'json'})
            r.raise_for_status(); raw=r.json().get('response','[]')
            data=json.loads(raw)
            return data if isinstance(data,list) else []
    except Exception:
        return []

async def process_document(doc_id,name,text):
    decisions=await ollama_extract(text)
    if not decisions: decisions=heuristic_extract(text)
    c=db();
    for d in decisions:
        c.execute('INSERT INTO decisions VALUES (?,?,?,?,?,?,?)',(str(uuid.uuid4()),doc_id,d.get('title','Decision'),d.get('reason',''),d.get('alternatives',''),d.get('evidence',''),d.get('date','')))
    c.commit(); c.close(); return len(decisions)

@app.get('/')
def home(): return FileResponse(BASE/'static/index.html')

@app.post('/api/upload')
async def upload(file:UploadFile=File(...)):
    if not file.filename.lower().endswith(('.pdf','.txt','.md')): raise HTTPException(400,'Upload PDF, TXT, or Markdown.')
    content=await file.read(); path=UPLOADS/(str(uuid.uuid4())+'_'+file.filename.replace('/','_')); path.write_bytes(content)
    text=extract_pdf(path) if file.filename.lower().endswith('.pdf') else content.decode('utf-8','ignore')
    doc_id=str(uuid.uuid4()); c=db(); c.execute('INSERT INTO documents VALUES (?,?,?)',(doc_id,file.filename,text)); c.commit(); c.close()
    count=await process_document(doc_id,file.filename,text)
    return {'id':doc_id,'name':file.filename,'decisions':count,'mode':'ollama' if os.getenv('OLLAMA_URL') or Path('/usr/bin/ollama').exists() else 'fallback'}

@app.get('/api/decisions')
def decisions():
    c=db(); rows=[dict(r) for r in c.execute('SELECT * FROM decisions ORDER BY rowid DESC')]; c.close(); return rows

class Ask(BaseModel): question:str

@app.post('/api/ask')
async def ask(body:Ask):
    q=body.question.strip(); c=db(); rows=[dict(r) for r in c.execute('SELECT * FROM decisions')]; c.close()
    if not q: raise HTTPException(400,'Question required.')
    terms=set(re.findall(r'\w+',q.lower())); ranked=[]
    for d in rows:
        blob=' '.join(str(d.get(k,'')) for k in ['title','reason','alternatives','evidence']).lower()
        score=sum(1 for t in terms if len(t)>2 and t in blob)
        ranked.append((score,d))
    ranked.sort(key=lambda x:x[0],reverse=True); hits=[d for s,d in ranked[:3] if s>0]
    if not hits and rows: hits=rows[:3]
    if not hits: return {'answer':'I do not have enough project memory to answer that yet. Upload meeting notes or project documents first.','sources':[]}
    context='\n'.join([f"Decision: {d['title']}\nReason: {d['reason']}\nAlternatives: {d['alternatives']}\nEvidence: {d['evidence']}" for d in hits])
    prompt=f'''Answer the user's question using ONLY the supplied project memory. Do not invent facts. Keep it concise. Mention uncertainty if evidence is insufficient.\nQuestion: {q}\nMemory:\n{context}'''
    answer='\n\n'.join([f"{d['title']}: {d['reason'] or d['evidence']}" for d in hits])
    try:
        async with httpx.AsyncClient(timeout=60) as client:
            r=await client.post(os.getenv('OLLAMA_URL','http://localhost:11434')+'/api/generate',json={'model':os.getenv('OLLAMA_MODEL','qwen2.5:3b'),'prompt':prompt,'stream':False})
            r.raise_for_status(); answer=r.json().get('response',answer)
    except Exception: pass
    return {'answer':answer,'sources':[{'title':d['title'],'evidence':d['evidence']} for d in hits]}

@app.get('/api/health')
def health(): return {'status':'ok','product':'RecallAI','version':'MVP 1.0'}

db()
