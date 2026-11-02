import secrets
from fastapi import HTTPException, Request
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, VerificationError
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
from .config import APP_SECRET, DATA_DIR, TRUSTED_ORIGINS, COOKIE_SECURE
from .db import connect

ph = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=2)


def secret_key():
    # Stable local fallback survives restarts. Production: use APP_SECRET environment variable.
    if APP_SECRET and APP_SECRET != 'REPLACE_WITH_A_UNIQUE_RANDOM_SECRET':
        return APP_SECRET
    path = DATA_DIR / '.session_secret'
    if not path.exists():
        path.write_text(secrets.token_urlsafe(48),encoding='utf-8')
        try: path.chmod(0o600)
        except OSError: pass
    return path.read_text(encoding='utf-8')


serializer = URLSafeTimedSerializer(secret_key(), salt='veritext-session-v1')


def new_session(response, user_id):
    csrf = secrets.token_urlsafe(24)
    value = serializer.dumps({'uid': user_id,'csrf': csrf})
    response.set_cookie('vt_session',value,httponly=True,secure=COOKIE_SECURE,
                        samesite='lax',max_age=8*3600,path='/')
    return csrf


def verify_password(stored, incoming):
    try:
        return ph.verify(stored,incoming)
    except (VerifyMismatchError,VerificationError):
        return False


def current_user(request: Request):
    cookie = request.cookies.get('vt_session','')
    try:
        session = serializer.loads(cookie,max_age=8*3600)
    except (BadSignature,SignatureExpired):
        raise HTTPException(401,'Sign in required')
    with connect() as db:
        row = db.execute('SELECT id,email,name,role,active FROM users WHERE id=?',
                         (session.get('uid'),)).fetchone()
    if not row or not row['active']:
        raise HTTPException(401,'Account is disabled or unavailable')
    if request.method not in ('GET','HEAD','OPTIONS'):
        if request.headers.get('x-csrf-token') != session.get('csrf'):
            raise HTTPException(403,'Invalid or missing CSRF token')
    return dict(row)


def role(user, *roles):
    if user['role'] not in roles:
        raise HTTPException(403,'Insufficient permission')


def origin_guard(request: Request):
    if request.method in ('POST','PATCH','DELETE','PUT'):
        origin = request.headers.get('origin')
        if origin and origin.rstrip('/') not in TRUSTED_ORIGINS:
            raise HTTPException(403,'Origin not allowed')
