# VeriText — Academic Integrity Workspace

VeriText is a local-first web application that compares submissions with an indexed reference library, highlights exactly matching passages, manages users, records review history, exports PDF reports and optionally trains a statistical AI-writing classifier from verified labeled data.

**This is a functional v1 platform, not a validated Turnitin replacement.** No AI detector can prove who authored a passage or recognize all AI models. This system does not have access to Turnitin's corpus, scholarly publisher databases, or the full public web. Its similarity percentage covers only the sources you index.

## What is implemented

| Feature | Status |
| --- | --- |
| Web dashboard and user interface | Working |
| TXT, MD, DOCX, text-based PDF ingestion | Working |
| Seven-word fingerprint retrieval and contiguous-passage highlighting | Working |
| Reference upload, search index, deletion | Working |
| PDF export with source evidence and AI assessment context | Working |
| Administrator, analyst, viewer access control | Working |
| Argon2-hashed passwords, signed HttpOnly sessions, CSRF tokens, login throttling, audit log | Working |
| Optional custom classifier, train/tune/test split, visible evaluation metrics | Working |
| Descriptive text statistics when no classifier is installed | Working |
| Complete internet-wide plagiarism searching | Not included; requires search/corpus licensing |
| Semantic paraphrase, translated text and OCR-based plagiarism detection | Not included |
| Universal or guaranteed-accuracy AI origin detection | Not technically possible |
| Learning management system integration, SSO, horizontal scaling | Not included |

## Prerequisites

- Python 3.11, 3.12 or 3.13
- Windows 10/11, Windows Server, Linux, or macOS
- 2 GB free RAM recommended for small datasets, more for larger model training

## Windows installation

Open PowerShell or Command Prompt in the extracted directory. For a guided installation, run `setup_windows.bat`, then `launch_windows.bat`. The manual commands are below.

```powershell
py -m venv .venv
.venv\Scripts\activate
python -m pip install --upgrade pip
pip install -r requirements.txt
copy .env.example .env
```

Edit `.env` to set a secret. Generate one with:

```powershell
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

Put this value in `.env` as `APP_SECRET=<your-value>`. The app also creates a persistent secret automatically when running locally without `.env`.

Create your first administrator:

```powershell
python -m app.cli create-admin --email admin@example.edu --name "Platform Administrator"
```

The terminal prompts for a password of at least 12 characters. **No default account exists.**

Run the application:

```powershell
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Open http://127.0.0.1:8000 and log in with your administrator account.

## Linux installation

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# Edit APP_SECRET and TRUSTED_ORIGINS in .env
python -m app.cli create-admin --email admin@example.edu
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

For LAN access, use `--host 0.0.0.0` behind a network firewall. For Internet deployment, use HTTPS and a reverse proxy. See `DEPLOYMENT.md`.

## How to use

1. Sign in as administrator.
2. Choose **Source library**, then index reference papers (PDF, DOCX, TXT or MD) or paste text. An optional URL is metadata only; the app does not fetch website contents.
3. Choose **New analysis**, upload a paper or paste its text, then run analysis.
4. Open the saved report to inspect highlighted wording and source attribution. Download the PDF.
5. Under **AI model lab**, upload verified CSV examples of human and AI writing to train the optional classifier.
6. Under **Team & access**, add analysts (can scan) or viewers (read-only).

## AI classifier training

Upload a UTF-8 CSV containing `text,label`:

```csv
text,label
"An independently verified human-written passage containing at least 50 words...",human
"An independently verified AI-generated passage containing at least 50 words...",ai
```

At least 50 unique documents per class are required to run the pipeline. **This minimum is for functionality, not for scientific adequacy.** For research deployment, use thousands of provenance-verified texts from multiple genres, human populations, languages, and AI model families, with independent held-out evaluation against *entirely unseen models and writing populations*.

The model uses character 3–5-gram TF-IDF with logistic regression. It creates 60% training, 20% threshold-tuning and 20% held-out evaluation partitions. The high review threshold is tuned to avoid false positives on tuning samples. It reports measured test accuracy, false positive rate, recall and ROC AUC. These are **not universal accuracy claims**. A random document split can inflate results if related prompts or authors occur in multiple partitions.

For texts below 120 words, AI classification is withheld. If no classifier is trained, the platform gives descriptive style indicators but **no fake AI probability**. The application cannot identify which named model produced the text.

## What similarity means

Similarity is the percentage of submitted words covered by seven-or-more-word contiguous matches against indexed references. It is **not** a plagiarism probability. Proper quotations, common technical language, citations and reused methods can match. The reference retrieval uses exact shingle overlap, not semantic paraphrase search. The matcher examines up to 15 highest-overlap candidate documents for detailed spans; this is suitable for a modest local corpus, not a global-scale academic index. If no source is indexed, the system says *Not assessed*, not 0%.

The tool stores extracted document text in `data/veritext.db`, including source text and previous submissions. Limit access and back up this database per institutional requirements.

## API documentation

With the app running, visit http://127.0.0.1:8000/api/docs for OpenAPI documentation.

Main routes:

- `POST /api/auth/login`
- `GET /api/dashboard`
- `POST /api/scans` (multipart form; `title`, `text` or `file`)
- `GET /api/scans`, `GET /api/scans/{id}`
- `GET /api/scans/{id}/report.pdf`
- `POST /api/sources`, `GET /api/sources`, `DELETE /api/sources/{id}`
- `GET /api/model`, `POST /api/model/train`
- `GET /api/users`, `POST /api/users`, `PATCH /api/users/{id}/active?active=false`
- `GET /api/audit`

Authentication uses a signed session cookie. Mutating requests require the CSRF token from `/api/me` in the `X-CSRF-Token` header, except login. Browser UI handles this automatically.

## Tests

```bash
pip install pytest httpx
python -m pytest -q
```

## Architecture

```
Browser UI (HTML/CSS/JavaScript)
          |
FastAPI REST API ── signed session / Argon2 / RBAC / CSRF
          |
   +------+----------+--------------------+
   |                 |                    |
SQLite (users,    Fingerprint          Optional supervised
scans, sources,   index + text          AI classifier training
reports, audit)   overlap matcher       (scikit-learn)
          |
     PDF report generation
```

### Limits before institutional production

This v1 is suitable for development or a controlled pilot with a modest corpus. Before real university-wide deployment, add SSO/OIDC, multi-tenancy, document retention and deletion policies, encrypted storage/backups, API rate limits, antivirus and file sandboxing, job queues, observability, security testing, PostgreSQL + large-scale distributed retrieval, content licenses, bias audits, and independent evaluation. Never discipline students based only on the classifier output.

## License and reuse

Application source generated for this project; adapt and validate it for your institution. Third-party packages are governed by their own licenses.
