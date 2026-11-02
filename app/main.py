"""VeriText API. Run: python -m uvicorn app.main:app --host 127.0.0.1 --port 8000"""
import json
import re
import uuid
import hashlib
import time
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlparse

from fastapi import FastAPI, Request, Response, HTTPException, Depends, File, Form, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .config import ROOT, MAX_UPLOAD_BYTES
from .db import init_db, connect, now, audit
from .security import current_user, new_session, verify_password, ph, role, origin_guard
from .parser import extract, validate_text
from .similarity import analyze_similarity, fingerprint_set, tokenize
from .ai_engine import analyze_ai, metadata, train_csv
from .pdf_report import make_report


@asynccontextmanager
async def lifespan(app):
    init_db()
    yield


app = FastAPI(title='VeriText Academic Integrity API', version='1.0.0',
              description='Evidence-led source similarity and an optional validated AI text classifier.',
              lifespan=lifespan, docs_url='/api/docs', redoc_url=None)
app.mount('/static', StaticFiles(directory=ROOT / 'app' / 'static'),name='static')


@app.middleware('http')
async def check_origin(request: Request, call_next):
    try:
        origin_guard(request)
    except HTTPException as exc:
        return Response(content=json.dumps({'detail':exc.detail}),status_code=exc.status_code,media_type='application/json')
    response = await call_next(request)
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['Referrer-Policy'] = 'no-referrer'
    response.headers['Content-Security-Policy'] = "default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; font-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
    response.headers['Cache-Control'] = 'no-store'
    return response


@app.get('/')
def home():
    return FileResponse(ROOT/'app'/'static'/'index.html')


@app.get('/api/health')
def health():
    return {'ok':True, 'service':'VeriText', 'version':'1.0.0'}


class Login(BaseModel):
    email: str = Field(min_length=3,max_length=255)
    password: str = Field(min_length=1,max_length=500)


@app.post('/api/auth/login')
def login(payload: Login, response: Response, request: Request):
    # Persistent per-IP throttling. Public deployments also need edge protection.
    ip = request.client.host if request.client else 'unknown'
    key = hashlib.sha256(ip.encode()).hexdigest()
    current = time.time()
    failed = False
    with connect() as db:
        attempt = db.execute('SELECT failures,window_start,block_until FROM login_limits WHERE key=?',(key,)).fetchone()
        if attempt and attempt['block_until'] > current:
            raise HTTPException(429,'Too many sign-in attempts. Try again later.',headers={'Retry-After':'900'})
        row = db.execute('SELECT * FROM users WHERE email=?',(payload.email.lower().strip(),)).fetchone()
        if not row or not row['active'] or not verify_password(row['password_hash'],payload.password):
            n = 1 if not attempt or current-attempt['window_start']>900 else attempt['failures']+1
            start = current if n==1 else attempt['window_start']
            block = current+900 if n>=10 else 0
            db.execute('''INSERT INTO login_limits(key,failures,window_start,block_until) VALUES(?,?,?,?)
                ON CONFLICT(key) DO UPDATE SET failures=excluded.failures,
                window_start=excluded.window_start,block_until=excluded.block_until''',(key,n,start,block))
            audit(db,None,'login_failed',details='Invalid credentials')
            failed = True
        else:
            db.execute('DELETE FROM login_limits WHERE key=?',(key,))
            csrf = new_session(response,row['id'])
            audit(db,row['id'],'login')
            user = {'id':row['id'],'name':row['name'],'email':row['email'],'role':row['role']}
    if failed:
        raise HTTPException(401,'Incorrect email or password')
    return {'csrf':csrf,'user':user}


@app.post('/api/auth/logout')
def logout(response: Response,user=Depends(current_user)):
    with connect() as db: audit(db,user['id'],'logout')
    response.delete_cookie('vt_session',path='/')
    return {'ok':True}


@app.get('/api/me')
def me(request: Request,user=Depends(current_user)):
    from .security import serializer
    session = serializer.loads(request.cookies['vt_session'],max_age=8*3600)
    return {'user':user,'csrf':session['csrf']}


@app.get('/api/dashboard')
def dashboard(user=Depends(current_user)):
    with connect() as db:
        scans = db.execute('SELECT count(*) FROM scans').fetchone()[0]
        sources = db.execute('SELECT count(*) FROM sources WHERE active=1').fetchone()[0]
        matched = db.execute('SELECT count(*) FROM scans WHERE similarity_score>0').fetchone()[0]
        latest = db.execute('''SELECT s.id,s.title,s.created_at,s.word_count,s.similarity_score,
                            s.ai_status,u.name AS author FROM scans s JOIN users u ON u.id=s.created_by
                            ORDER BY s.created_at DESC LIMIT 8''').fetchall()
        return {'scans':scans,'sources':sources,'with_matches':matched,
                'model': metadata(), 'recent':[dict(r) for r in latest]}


async def read_upload(file: UploadFile):
    data = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(413,'File exceeds 12 MB limit')
    return extract(data,file.filename or '')


@app.post('/api/scans')
async def create_scan(title: str = Form('Untitled submission'),text: str = Form(''),
                      file: UploadFile | None = File(None),user=Depends(current_user)):
    role(user,'admin','analyst')
    if not title.strip() or len(title) > 200:
        raise HTTPException(422,'Title must be between 1 and 200 characters')
    content = await read_upload(file) if file and file.filename else validate_text(text)
    with connect() as db:
        similarity = analyze_similarity(db,content)
        ai = analyze_ai(content)
        result = {'similarity':similarity,'ai':ai}
        scan_id = str(uuid.uuid4())
        db.execute('''INSERT INTO scans(id,title,text,created_by,created_at,word_count,similarity_score,ai_status,ai_probability,result_json)
                      VALUES(?,?,?,?,?,?,?,?,?,?)''',
                   (scan_id,title.strip(),content,user['id'],now(),similarity['word_count'],
                    similarity['similarity_percent'],ai['status'],ai['probability'],json.dumps(result)))
        audit(db,user['id'],'scan_created',scan_id,title.strip()[:150])
    return {'id':scan_id,'title':title.strip(),'text':content,'created_at':now(),'result':result}


@app.get('/api/scans')
def list_scans(limit: int=60,user=Depends(current_user)):
    limit = min(max(1,limit),200)
    with connect() as db:
        rows = db.execute('''SELECT s.id,s.title,s.created_at,s.word_count,s.similarity_score,
                      s.ai_status,s.ai_probability,u.name AS author FROM scans s JOIN users u ON u.id=s.created_by
                      ORDER BY s.created_at DESC LIMIT ?''',(limit,)).fetchall()
        return {'items':[dict(r) for r in rows]}


@app.get('/api/scans/{scan_id}')
def get_scan(scan_id: str,user=Depends(current_user)):
    with connect() as db:
        row = db.execute('SELECT * FROM scans WHERE id=?',(scan_id,)).fetchone()
        if not row: raise HTTPException(404,'Scan not found')
        return {'id':row['id'],'title':row['title'],'text':row['text'],
                'created_at':row['created_at'],'word_count':row['word_count'],
                'result':json.loads(row['result_json'])}


@app.get('/api/scans/{scan_id}/report.pdf')
def report(scan_id: str,user=Depends(current_user)):
    with connect() as db:
        row = db.execute('SELECT * FROM scans WHERE id=?',(scan_id,)).fetchone()
        if not row: raise HTTPException(404,'Scan not found')
        result = json.loads(row['result_json'])
        pdf = make_report(row,result)
        audit(db,user['id'],'report_exported',scan_id)
    safe = re.sub(r'[^A-Za-z0-9_-]+','-',row['title'])[:45].strip('-') or 'report'
    return StreamingResponse(iter([pdf]),media_type='application/pdf',
                headers={'Content-Disposition': f'attachment; filename="{safe}-integrity.pdf"'})


@app.get('/api/sources')
def list_sources(user=Depends(current_user)):
    with connect() as db:
        rows = db.execute('''SELECT s.id,s.title,s.source_url,s.word_count,s.created_at,u.name AS uploader
                      FROM sources s JOIN users u ON u.id=s.uploaded_by
                      WHERE s.active=1 ORDER BY s.created_at DESC''').fetchall()
    return {'items':[dict(r) for r in rows]}


@app.post('/api/sources')
async def add_source(title: str=Form(...), text: str=Form(''),source_url: str=Form(''),
                     file: UploadFile | None=File(None),user=Depends(current_user)):
    role(user,'admin')
    if not title.strip() or len(title)>200:
        raise HTTPException(422,'Title must be between 1 and 200 characters')
    if source_url:
        parsed = urlparse(source_url)
        if parsed.scheme not in ('https','http') or not parsed.netloc or len(source_url)>500:
            raise HTTPException(422,'Source URL must be a valid HTTP(S) address')
    content = await read_upload(file) if file and file.filename else validate_text(text)
    source_id = str(uuid.uuid4())
    fprints = fingerprint_set(content)
    with connect() as db:
        db.execute('INSERT INTO sources(id,title,source_url,text,word_count,uploaded_by,created_at) VALUES(?,?,?,?,?,?,?)',
                   (source_id,title.strip(),source_url.strip() or None,content,len(tokenize(content)),user['id'],now()))
        db.executemany('INSERT INTO fingerprints(source_id,hash) VALUES(?,?)',
                       ((source_id,f) for f in fprints))
        audit(db,user['id'],'source_added',source_id,title.strip()[:150])
    return {'id':source_id,'title':title.strip(),'word_count':len(tokenize(content)),
            'fingerprints':len(fprints)}


@app.delete('/api/sources/{source_id}')
def delete_source(source_id: str,user=Depends(current_user)):
    role(user,'admin')
    with connect() as db:
        row = db.execute('SELECT title FROM sources WHERE id=?',(source_id,)).fetchone()
        if not row: raise HTTPException(404,'Source not found')
        db.execute('DELETE FROM sources WHERE id=?',(source_id,))
        audit(db,user['id'],'source_removed',source_id,row['title'][:150])
    return {'ok':True}


@app.get('/api/model')
def model_info(user=Depends(current_user)):
    return metadata()


@app.post('/api/model/train')
async def train_model(file: UploadFile=File(...),user=Depends(current_user)):
    role(user,'admin')
    if not file.filename or not file.filename.lower().endswith('.csv'):
        raise HTTPException(415,'Upload a UTF-8 CSV training dataset')
    data = await file.read(8*1024*1024+1)
    try:
        result = train_csv(data)
    except ValueError as exc:
        raise HTTPException(422,str(exc)) from exc
    with connect() as db:
        audit(db,user['id'],'ai_model_trained',details=f"Human/AI examples: {result['dataset_human']}/{result['dataset_ai']}")
    return result


class NewUser(BaseModel):
    email: str = Field(min_length=5,max_length=255)
    name: str = Field(min_length=2,max_length=120)
    role: str = 'analyst'
    password: str = Field(min_length=12,max_length=128)


@app.get('/api/users')
def users(user=Depends(current_user)):
    role(user,'admin')
    with connect() as db:
        rows = db.execute('SELECT id,name,email,role,active,created_at FROM users ORDER BY created_at DESC').fetchall()
        return {'items':[dict(r) for r in rows]}


@app.post('/api/users')
def create_user(payload: NewUser,user=Depends(current_user)):
    role(user,'admin')
    if payload.role not in ('admin','analyst','viewer'):
        raise HTTPException(422,'Invalid role')
    email = payload.email.strip().lower()
    if not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+',email):
        raise HTTPException(422,'Invalid email address')
    uid = str(uuid.uuid4())
    with connect() as db:
        if db.execute('SELECT 1 FROM users WHERE email=?',(email,)).fetchone():
            raise HTTPException(409,'Email already exists')
        db.execute('INSERT INTO users(id,email,name,password_hash,role,created_at) VALUES(?,?,?,?,?,?)',
                   (uid,email,payload.name.strip(),ph.hash(payload.password),payload.role,now()))
        audit(db,user['id'],'user_created',uid,email+' / '+payload.role)
    return {'id':uid,'email':email,'name':payload.name.strip(),'role':payload.role}


@app.patch('/api/users/{user_id}/active')
def set_user_active(user_id: str, active: bool,user=Depends(current_user)):
    role(user,'admin')
    if user_id == user['id'] and not active:
        raise HTTPException(422,'You cannot disable your own account')
    with connect() as db:
        row = db.execute('SELECT id,role,active FROM users WHERE id=?',(user_id,)).fetchone()
        if not row: raise HTTPException(404,'User not found')
        if row['role']=='admin' and not active:
            active_admins = db.execute("SELECT count(*) FROM users WHERE active=1 AND role='admin'").fetchone()[0]
            if active_admins <= 1:
                raise HTTPException(422,'Cannot disable the final active administrator')
        db.execute('UPDATE users SET active=? WHERE id=?',(int(active),user_id))
        audit(db,user['id'],'user_status_changed',user_id,str(active))
    return {'ok':True,'active':active}


@app.get('/api/audit')
def audit_log(user=Depends(current_user)):
    role(user,'admin')
    with connect() as db:
        rows = db.execute('''SELECT a.at,a.action,a.object_id,a.details,coalesce(u.name,'System') AS actor
                    FROM audit a LEFT JOIN users u ON u.id=a.user_id
                    ORDER BY a.id DESC LIMIT 80''').fetchall()
        return {'items':[dict(r) for r in rows]}
