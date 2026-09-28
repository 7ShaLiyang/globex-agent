import time
from fastapi.testclient import TestClient
from app.presentation.api import create_app
from app.infrastructure.settings import Settings

def test_complete_flow(tmp_path):
    app=create_app(Settings(database_url=f'sqlite+aiosqlite:///{tmp_path}/api.db',app_mode='demo',redis_url='',qdrant_url='',inline_worker=True))
    with TestClient(app) as client:
        assert client.get('/api/products').status_code==401
        token=client.post('/api/guest').json()['token'];client.headers['Authorization']='Bearer '+token
        sid=client.post('/api/sessions').json()['id']
        body={'text':'降噪耳机','request_id':'test-message-1'}
        job=client.post(f'/api/sessions/{sid}/messages',json=body).json()['id']
        assert client.post(f'/api/sessions/{sid}/messages',json=body).json()['id']==job
        for _ in range(80):
            state=client.get('/api/jobs/'+job).json()
            if state['status'] in ['done','failed']: break
            time.sleep(.05)
        assert state['status']=='done'
        assert '耳机' in state['result']
        events=client.get(f'/api/sessions/{sid}/events').json()
        assert len([e for e in events if e['type']=='user_message'])==1
        assert len([e for e in events if e['type']=='assistant_message'])==1
        with client.websocket_connect('/api/ws/'+sid) as ws:
            ws.send_json({'token':token,'after':0});assert ws.receive_json()['type']=='user_message'
        assert client.delete(f'/api/sessions/{sid}').json()['deleted'] is True
        assert client.get(f'/api/sessions/{sid}/events').status_code==404
        client.headers['Authorization']='Bearer '+client.post('/api/guest').json()['token']
        assert client.get(f'/api/sessions/{sid}/state').status_code==404
        assert client.get('/api/jobs/'+job).status_code==404
