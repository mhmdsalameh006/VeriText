import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def load_env():
    path = ROOT / '.env'
    if path.exists():
        for line in path.read_text(encoding='utf-8').splitlines():
            line = line.strip()
            if not line or line.startswith('#') or '=' not in line:
                continue
            k, v = line.split('=', 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


load_env()
DATA_DIR = Path(os.getenv('DATA_DIR', str(ROOT / 'data'))).resolve()
DATA_DIR.mkdir(parents=True, exist_ok=True)
DATABASE = DATA_DIR / 'veritext.db'
MODEL_FILE = DATA_DIR / 'ai_model.joblib'
MODEL_METADATA = DATA_DIR / 'ai_model_metadata.json'
APP_SECRET = os.getenv('APP_SECRET', '')
COOKIE_SECURE = os.getenv('COOKIE_SECURE', 'false').lower() == 'true'
TRUSTED_ORIGINS = [x.strip() for x in os.getenv('TRUSTED_ORIGINS','http://localhost:8000,http://127.0.0.1:8000').split(',') if x.strip()]
MAX_UPLOAD_BYTES = 12 * 1024 * 1024
MAX_TEXT_CHARS = 180_000
