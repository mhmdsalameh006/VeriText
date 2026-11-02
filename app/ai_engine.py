"""Research-oriented, opt-in supervised detector + non-evidentiary writing statistics.

No pretrained model or model-identity attribution is claimed. Classifier is trained only
on labeled records supplied by an authorized administrator, validated out of sample.
"""
import csv
import hashlib
import io
import json
import math
import re
from collections import Counter
from statistics import mean, pstdev

from .config import MODEL_FILE, MODEL_METADATA
from .similarity import tokenize

SENTENCE = re.compile(r'[^.!?\n]+(?:[.!?]+|$)', re.UNICODE)
FORMULAIC = [
    'in conclusion', 'it is important to note', 'in today\'s world',
    'on the other hand', 'furthermore', 'moreover', 'it is worth noting',
    'in the realm of', 'plays a crucial role', 'in summary', 'delve into',
    'a wide range of', 'in the ever-evolving', 'as a result',
]


def style_indicators(text):
    words = [t[0] for t in tokenize(text)]
    total = len(words)
    lengths = [len(tokenize(m.group(0))) for m in SENTENCE.finditer(text) if len(tokenize(m.group(0))) >= 3]
    lengths = lengths[:2000]
    avg = round(mean(lengths), 1) if lengths else 0
    cv = round(pstdev(lengths) / mean(lengths), 2) if len(lengths) > 2 and mean(lengths) else None
    counts = Counter(words)
    lexical = round(len(counts) / max(total, 1), 3)
    lower = text.casefold()
    formulaic_count = sum(lower.count(p) for p in FORMULAIC)
    repeated = sum(v-1 for _,v in Counter(tuple(words[i:i+4]) for i in range(max(0,total-3))).items() if v > 1)
    indicators = [
        {'label': 'Sentence length variation', 'value': cv, 'unit': 'coefficient of variation',
         'interpretation': 'Lower variation can occur in formal writing of any origin.'},
        {'label': 'Vocabulary diversity', 'value': lexical, 'unit': 'type-token ratio',
         'interpretation': 'This metric changes with text length and genre.'},
        {'label': 'Formulaic expressions', 'value': formulaic_count, 'unit': 'occurrences',
         'interpretation': 'Common academic phrases are not evidence of AI use.'},
        {'label': 'Repeated 4-word sequences', 'value': repeated, 'unit': 'repetitions',
         'interpretation': 'Repeated terminology may be appropriate within technical papers.'},
    ]
    return {'word_count': total, 'sentence_count': len(lengths),
            'average_sentence_words': avg, 'indicators': indicators,
            'note': 'Descriptive writing statistics only. These do not determine authorship.'}


def metadata():
    if not MODEL_FILE.exists() or not MODEL_METADATA.exists():
        return {'available': False, 'status': 'untrained', 'message': 'No validated AI writing classifier installed.'}
    try:
        meta = json.loads(MODEL_METADATA.read_text(encoding='utf-8'))
        return {'available': True, 'status': 'trained', **meta}
    except (OSError, ValueError):
        return {'available': False, 'status': 'unavailable', 'message': 'Model metadata could not be read.'}


def analyze_ai(text):
    import joblib
    summary = style_indicators(text)
    info = metadata()
    if summary['word_count'] < 120:
        return {'status': 'insufficient_text', 'probability': None, 'classification': 'Not assessed',
                'explanation': 'At least 120 words are required for an AI classifier assessment.',
                'style': summary, 'model': info}
    if not info['available']:
        return {'status': 'untrained', 'probability': None, 'classification': 'Not assessed',
                'explanation': 'A validated, labeled model is required. Writing statistics cannot identify AI authorship.',
                'style': summary, 'model': info}
    try:
        model = joblib.load(MODEL_FILE)
        probability = float(model.predict_proba([text])[0][1])
    except Exception:
        return {'status': 'model_error', 'probability': None, 'classification': 'Not assessed',
                'explanation': 'The installed classifier could not process this text.',
                'style': summary, 'model': info}
    threshold = float(info.get('threshold', 1.0))
    label = 'Review suggested' if probability >= threshold else 'No signal above review threshold'
    return {'status': 'assessed', 'probability': round(probability * 100, 1),
            'classification': label, 'threshold': round(threshold * 100, 1),
            'explanation': 'Statistical classification relative to the uploaded training set, not proof of origin or a model identity.',
            'style': summary, 'model': info}


def train_csv(data: bytes):
    """Separate train/tune/test. Tune review threshold at <=1% observed FPR.

    Nonrepresentative training data means nonrepresentative results; surface test metrics.
    """
    import joblib
    import numpy as np
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.linear_model import LogisticRegression
    from sklearn.metrics import accuracy_score, confusion_matrix, precision_score, recall_score, roc_auc_score
    from sklearn.model_selection import train_test_split
    from sklearn.pipeline import Pipeline
    from datetime import datetime, timezone

    if len(data) > 8*1024*1024:
        raise ValueError('Training CSV exceeds 8 MB.')
    try:
        source = io.StringIO(data.decode('utf-8-sig'))
        reader = csv.DictReader(source)
        if not reader.fieldnames or not {'text','label'}.issubset(set(reader.fieldnames)):
            raise ValueError('CSV columns must include text,label. Optional: generator,domain.')
        records = []
        seen = set()
        for row in reader:
            raw = (row.get('text') or '').strip()
            label = (row.get('label') or '').strip().lower()
            mapping = {'ai':1, '1':1, 'machine':1, 'human':0, '0':0}
            if label not in mapping or len(raw.split()) < 50:
                continue
            key = hashlib.sha256(re.sub(r'\s+', ' ',raw.casefold()).encode()).hexdigest()
            if key not in seen:
                seen.add(key)
                records.append((raw,mapping[label]))
        n0 = sum(r[1]==0 for r in records)
        n1 = sum(r[1]==1 for r in records)
        if min(n0,n1) < 50:
            raise ValueError('Need at least 50 distinct documents of 50+ words for EACH class: human and ai.')
        xs = [r[0] for r in records]
        ys = [r[1] for r in records]
        train_x, remainder_x, train_y, remainder_y = train_test_split(xs,ys,test_size=.4, random_state=42,stratify=ys)
        tune_x, test_x, tune_y, test_y = train_test_split(remainder_x,remainder_y,test_size=.5,random_state=43,stratify=remainder_y)
        model = Pipeline([
            ('tfidf', TfidfVectorizer(analyzer='char', ngram_range=(3,5), min_df=2,
                                      sublinear_tf=True, max_features=35000)),
            ('clf', LogisticRegression(C=1.0, class_weight='balanced',max_iter=1500,random_state=42))
        ])
        model.fit(train_x, train_y)
        tune_p = model.predict_proba(tune_x)[:,1]
        # Chosen on tuning only, with at least 0.85 required to reduce spurious flags.
        negatives = np.array([p for p,y in zip(tune_p,tune_y) if y == 0])
        threshold = float(max(.85, np.max(negatives)+1e-8)) if len(negatives) else 1.0
        threshold = min(1.0, threshold)
        test_p = model.predict_proba(test_x)[:,1]
        predicted = [int(p>=threshold) for p in test_p]
        tn, fp, fn, tp = confusion_matrix(test_y,predicted,labels=[0,1]).ravel()
        meta = {
            'trained_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
            'training_documents': len(train_x), 'tuning_documents': len(tune_x),
            'test_documents': len(test_x), 'dataset_human': n0, 'dataset_ai': n1,
            'threshold': round(threshold,5),
            'test_accuracy': round(float(accuracy_score(test_y,predicted)),3),
            'test_precision': round(float(precision_score(test_y,predicted,zero_division=0)),3),
            'test_recall': round(float(recall_score(test_y,predicted,zero_division=0)),3),
            'test_false_positive_rate': round(float(fp/max(tn+fp,1)),3),
            'test_roc_auc': round(float(roc_auc_score(test_y,test_p)),3),
            'validation_scope': 'Held-out samples from this dataset only; not tested on every language, model, or paraphrase style.',
        }
        # Write model + metadata in a predictable owner-controlled directory.
        temp_model = MODEL_FILE.with_suffix('.joblib.tmp')
        temp_meta = MODEL_METADATA.with_suffix('.json.tmp')
        joblib.dump(model,temp_model)
        temp_meta.write_text(json.dumps(meta,indent=2),encoding='utf-8')
        temp_model.replace(MODEL_FILE)
        temp_meta.replace(MODEL_METADATA)
        return {'available': True,'status':'trained', **meta}
    except (UnicodeError, csv.Error) as exc:
        raise ValueError('Invalid UTF-8 CSV content.') from exc
