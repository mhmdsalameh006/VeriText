"""Local source matching: hashed word-shingles for retrieval + exact contiguous runs.

Similarity = union of submitted word positions matched against indexed sources.
A match is not a finding of academic misconduct; quotes and citations may match.
"""
import hashlib
import re
from collections import Counter, defaultdict

WORD = re.compile(r"[^\W_]+(?:['’-][^\W_]+)*", re.UNICODE)
K = 7
WINDOW = 6


def tokenize(text):
    return [(m.group(0).casefold().replace('’', "'"), m.start(), m.end()) for m in WORD.finditer(text)]


def hashes(words):
    """Stable shingle hashes with indices. Cryptographic hashes avoid random Python seeds."""
    return [(hashlib.blake2b('\x1f'.join(words[i:i+K]).encode(), digest_size=10).hexdigest(), i)
            for i in range(max(0, len(words) - K + 1))]


def fingerprint_set(text):
    """Index every seven-word shingle so short copied passages are not discarded."""
    tokens = tokenize(text)
    return {digest for digest, _ in hashes([x[0] for x in tokens])}


def candidate_sources(db, submitted_text, limit=15):
    fprints = list(fingerprint_set(submitted_text))
    if not fprints:
        return []
    counts = Counter()
    for start in range(0, len(fprints), 350):
        values = fprints[start:start+350]
        placeholders = ','.join('?' for _ in values)
        rows = db.execute(f'''SELECT f.source_id, count(*) AS n
            FROM fingerprints f JOIN sources s ON s.id=f.source_id
            WHERE s.active=1 AND f.hash IN ({placeholders})
            GROUP BY f.source_id''', values).fetchall()
        counts.update({r['source_id']: r['n'] for r in rows})
    if not counts:
        return []
    ids = [id_ for id_, _ in counts.most_common(limit)]
    rows = db.execute('SELECT id,title,source_url,text FROM sources WHERE id IN ('+
                      ','.join('?' for _ in ids)+')', ids).fetchall()
    by_id = {r['id']: dict(r) for r in rows}
    return [by_id[i] for i in ids if i in by_id]


def matching_runs(submitted_tokens, source_tokens):
    sw = [t[0] for t in submitted_tokens]
    rw = [t[0] for t in source_tokens]
    index = defaultdict(list)
    for h, j in hashes(rw):
        if len(index[h]) < 40:
            index[h].append(j)
    covered = set()
    runs = []
    for h, i in hashes(sw):
        if all(k in covered for k in range(i, i + K)):
            continue
        best = None
        for j in index.get(h, []):
            if sw[i:i+K] != rw[j:j+K]:
                continue
            si, rj = i, j
            while si > 0 and rj > 0 and sw[si-1] == rw[rj-1]:
                si -= 1
                rj -= 1
            ei, ej = i+K, j+K
            while ei < len(sw) and ej < len(rw) and sw[ei] == rw[ej]:
                ei += 1
                ej += 1
            if best is None or ei-si > best[1]-best[0]:
                best = (si, ei, rj, ej)
        if best:
            a, b, c, d = best
            if sum(k not in covered for k in range(a, b)) >= K:
                runs.append(best)
                covered.update(range(a,b))
    return runs


def analyze_similarity(db, text):
    tokens = tokenize(text)
    n = len(tokens)
    sources_total = db.execute('SELECT count(*) FROM sources WHERE active=1').fetchone()[0]
    if not sources_total:
        return {'status': 'no_sources', 'similarity_percent': None, 'sources_checked': 0,
                'word_count': n, 'matched_words': 0, 'sources': [], 'overlaps': []}
    candidates = candidate_sources(db, text)
    runs = []
    per_source = []
    for source in candidates:
        source_tokens = tokenize(source['text'])
        current = matching_runs(tokens, source_tokens)
        if not current:
            continue
        unique_words = len(set(k for a,b,_,_ in current for k in range(a,b)))
        per_source.append({'id': source['id'], 'title': source['title'],
                           'source_url': source['source_url'], 'matched_words': unique_words,
                           'percent_of_submission': round(100*unique_words/max(n,1),1),
                           'match_count': len(current)})
        for a,b,c,d in current:
            runs.append({'start': tokens[a][1], 'end': tokens[b-1][2],
                         'start_word': a, 'end_word': b, 'matched_words': b-a,
                         'source_id': source['id'], 'source_title': source['title'],
                         'source_excerpt': source['text'][source_tokens[c][1]:source_tokens[d-1][2]][:260]})
    # Assign each submitted word to at most one source. Never sum source percentages.
    selected = []
    occupied = set()
    for run in sorted(runs, key=lambda r: r['matched_words'], reverse=True):
        free = [k for k in range(run['start_word'], run['end_word']) if k not in occupied]
        if len(free) < K:
            continue
        occupied.update(free)
        selected.append(run)
    selected.sort(key=lambda x: x['start'])
    per_source.sort(key=lambda x: x['matched_words'], reverse=True)
    # Dedupe highlighting spans for overlapping ranges.
    highlights = []
    cursor = 0
    for run in selected:
        a = max(cursor, run['start'])
        if run['end'] > a:
            highlights.append({'start': a, 'end': run['end'],
                               'source_id': run['source_id'], 'source_title': run['source_title'],
                               'matched_words': run['matched_words'],
                               'source_excerpt': run['source_excerpt']})
            cursor = run['end']
    return {'status': 'complete', 'similarity_percent': round(100*len(occupied)/max(n,1),1),
            'sources_checked': sources_total, 'word_count': n,
            'matched_words': len(occupied), 'sources': per_source, 'overlaps': highlights}
