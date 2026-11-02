import io
import json
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import db
from app.main import app
from app.security import ph
from app.similarity import tokenize, fingerprint_set, matching_runs
from app.parser import extract

REFERENCE = ('Machine learning systems use numerical optimization and probabilistic modeling '
             'to learn relationships from observed data across academic research domains. '
             'The model parameters are updated through repeated gradient calculations '
             'under a specified objective function. ')*7


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(db,'DATABASE',tmp_path/'test.db')
    import app.ai_engine as ai_engine
    monkeypatch.setattr(ai_engine,'MODEL_FILE',tmp_path/'model.joblib')
    monkeypatch.setattr(ai_engine,'MODEL_METADATA',tmp_path/'metadata.json')
    with TestClient(app) as c:
        uid=str(uuid.uuid4())
        with db.connect() as con:
            con.execute('INSERT INTO users(id,email,name,password_hash,role,created_at) VALUES(?,?,?,?,?,?)',
                        (uid,'admin@example.org','Site Administrator',ph.hash('Strong-Password-12345'),'admin',db.now()))
        yield c


def sign_in(client):
    d=client.post('/api/auth/login',json={'email':'admin@example.org','password':'Strong-Password-12345'})
    assert d.status_code==200,d.text
    return {'X-CSRF-Token':d.json()['csrf']}


def test_sign_in_protected_and_csrf(client):
    assert client.get('/api/dashboard').status_code==401
    assert client.post('/api/auth/login',json={'email':'admin@example.org','password':'incorrect'}).status_code==401
    headers=sign_in(client)
    assert client.get('/api/me').status_code==200
    assert client.post('/api/sources',data={'title':'X','text':REFERENCE}).status_code==403
    assert client.post('/api/sources',data={'title':'X','text':REFERENCE},headers=headers).status_code==200
    assert client.post('/api/auth/logout',headers=headers).status_code==200
    assert client.get('/api/me').status_code==401


def test_similarity_scan_report_and_delete(client):
    headers=sign_in(client)
    r=client.post('/api/sources',headers=headers,data={'title':'Learning fundamentals','text':REFERENCE})
    assert r.status_code==200,r.text
    source_id=r.json()['id']
    s=client.post('/api/scans',headers=headers,data={'title':'Sample Research','text':REFERENCE})
    assert s.status_code==200,s.text
    result=s.json()
    similarity=result['result']['similarity']
    assert similarity['similarity_percent']==100.0
    assert similarity['matched_words']==len(tokenize(REFERENCE))
    assert similarity['sources'][0]['title']=='Learning fundamentals'
    assert similarity['overlaps']
    assert result['result']['ai']['status']=='untrained'
    assert result['result']['ai']['probability'] is None
    pdf=client.get('/api/scans/'+result['id']+'/report.pdf')
    assert pdf.status_code==200
    assert pdf.content[:4]==b'%PDF'
    assert client.delete('/api/sources/'+source_id,headers=headers).status_code==200
    assert client.get('/api/sources').json()['items']==[]
    later=client.post('/api/scans',headers=headers,data={'title':'Again','text':REFERENCE})
    assert later.json()['result']['similarity']['similarity_percent'] is None
    assert later.json()['result']['similarity']['status']=='no_sources'


def test_no_unmatched_source_and_file_upload(client):
    headers=sign_in(client)
    reference='The river measurement group built simple sensors for groundwater analysis. '*9
    client.post('/api/sources',headers=headers,data={'title':'Hydrology','text':reference})
    content='Unrelated ideas about literary manuscripts and forgotten archives were presented. '*9
    s=client.post('/api/scans',headers=headers,data={'title':'Different Text'},
                  files={'file':('test.txt',content.encode('utf-8'),'text/plain')})
    assert s.status_code==200,s.text
    assert s.json()['result']['similarity']['similarity_percent']==0.0
    assert s.json()['result']['similarity']['sources']==[]
    invalid=client.post('/api/scans',headers=headers,data={'title':'X'},files={'file':('file.exe',b'hello','application/octet-stream')})
    assert invalid.status_code==415


def test_roles_and_user_creation(client):
    headers=sign_in(client)
    p={'email':'viewer@example.org','name':'Read Only','password':'AnotherPassword123','role':'viewer'}
    created=client.post('/api/users',json=p,headers=headers)
    assert created.status_code==200
    viewer=TestClient(app)
    login=viewer.post('/api/auth/login',json={'email':p['email'],'password':p['password']})
    assert login.status_code==200
    vheaders={'X-CSRF-Token':login.json()['csrf']}
    assert viewer.get('/api/scans').status_code==200
    assert viewer.post('/api/scans',data={'title':'X','text':REFERENCE},headers=vheaders).status_code==403
    assert viewer.get('/api/users').status_code==403
    assert client.patch('/api/users/'+created.json()['id']+'/active?active=false',headers=headers).status_code==200
    assert viewer.get('/api/scans').status_code==401
    assert client.patch('/api/users/'+client.get('/api/me').json()['user']['id']+'/active?active=false',headers=headers).status_code==422
    viewer.close()


def test_train_validated_model(client):
    import csv
    headers=sign_in(client)
    output=io.StringIO()
    writer=csv.DictWriter(output,fieldnames=['text','label'])
    writer.writeheader()
    for k in range(52):
        human=('Yesterday I visited our campus archive, asked the librarian for help, and '
               'wrote down the names of several books I wanted to read before Monday. '
               'Then I walked to the bus stop and met my cousin. ')*3+f' Diary entry number {k}.'
        ai=('This investigation encompasses a comprehensive analytical framework wherein '
            'diverse methodological considerations and systematic evaluations elucidate '
            'multifaceted dimensions of the proposed conceptual research paradigm. '
            'Furthermore the proposed approach facilitates a structured exploration of the subject. ')*3+f' Version {k}.'
        writer.writerow({'text':human,'label':'human'})
        writer.writerow({'text':ai,'label':'ai'})
    r=client.post('/api/model/train',headers=headers,files={'file':('labels.csv',output.getvalue().encode(),'text/csv')})
    assert r.status_code==200,r.text
    assert r.json()['test_documents']>0
    assert 0<=r.json()['test_false_positive_rate']<=1
    assert client.get('/api/model').json()['available'] is True
    ai_result=client.post('/api/scans',headers=headers,data={'title':'AI Test','text':REFERENCE})
    assert ai_result.json()['result']['ai']['status']=='assessed'
    assert isinstance(ai_result.json()['result']['ai']['probability'],float)


def test_token_matching_unicode_and_overlap():
    text='Mathematical optimization across engineering studies requires careful measurement of learning outcomes.'
    assert fingerprint_set(text)
    runs=matching_runs(tokenize(text),tokenize(text))
    assert len(runs)>=1
    assert any(r[1]-r[0]>=7 for r in runs)
    assert tokenize("It's the model’s data")[:1][0][0]=="it's"


def test_login_throttle_persists_failures(client):
    for _ in range(10):
        r=client.post('/api/auth/login',json={'email':'admin@example.org','password':'wrong'})
        assert r.status_code==401
    r=client.post('/api/auth/login',json={'email':'admin@example.org','password':'Strong-Password-12345'})
    assert r.status_code==429
    with db.connect() as con:
        assert con.execute('SELECT count(*) FROM audit WHERE action="login_failed"').fetchone()[0]==10
