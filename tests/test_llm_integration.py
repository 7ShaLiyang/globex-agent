"""Real AgentScope loop, local fake OpenAI SSE: no paid model is called."""
import json
import threading
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import pytest
from agentscope.state import AgentState
from app.composition import Container
from app.domain.models import ShoppingContext
from app.infrastructure.settings import Settings
from app.infrastructure.agentscope_runtime import AgentScopeRuntime

@pytest.fixture
def fake_openai():
    calls=[]
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args): pass
        def do_POST(self):
            body=json.loads(self.rfile.read(int(self.headers['Content-Length'])));calls.append(body)
            self.send_response(200);self.send_header('Content-Type','text/event-stream');self.end_headers()
            has_tool=any(m.get('role')=='tool' for m in body['messages'])
            if not has_tool:
                delta={'role':'assistant','tool_calls':[{'index':0,'id':'call_search','type':'function','function':{'name':'search_products','arguments':'{"query":"降噪耳机","limit":3}'}}]}
                reason='tool_calls'
            else: delta={'role':'assistant','content':'推荐 Aero 轻量降噪耳机，价格 79 美元。'};reason='stop'
            for d,f in [(delta,None),({},reason)]:
                chunk={'id':'chat-test','object':'chat.completion.chunk','created':1,'model':'fake','choices':[{'index':0,'delta':d,'finish_reason':f}]}
                self.wfile.write(('data: '+json.dumps(chunk)+'\n\n').encode())
            self.wfile.write(b'data: [DONE]\n\n');self.wfile.flush()
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    yield f'http://127.0.0.1:{server.server_port}/v1',calls
    server.shutdown();server.server_close();thread.join()

async def test_real_agentscope_tool_loop_and_restore(tmp_path,fake_openai):
    url,calls=fake_openai
    c=Container(Settings(database_url=f'sqlite+aiosqlite:///{tmp_path}/llm.db',app_mode='llm',llm_base_url=url,llm_api_key='local-test',llm_model='fake',redis_url='',qdrant_url=''))
    await c.start()
    try:
        ctx=ShoppingContext('buyer','session','j1')
        answer,state=await c.agent.run(ctx,'找降噪耳机')
        assert 'Aero' in answer
        assert any(e['type']=='tool_result' for e in await c.db.events('buyer','session'))
        answer,state2=await c.agent.run(ShoppingContext('buyer','session','j2'),'再讲讲',state)
        assert len(state2['context'])>len(state['context'])
        assert calls[0]['messages'][0]==calls[-1]['messages'][0] # stable system prefix
        assert len(calls)>=3
    finally: await c.close()

async def test_builtin_task_idempotency_and_live_reads(tmp_path):
    c=Container(Settings(database_url=f'sqlite+aiosqlite:///{tmp_path}/tasks.db',app_mode='demo',redis_url='',qdrant_url=''))
    await c.start()
    try:
        runtime=AgentScopeRuntime(c.commerce,c.db,c.settings);ctx=ShoppingContext('b','s','j')
        tools={t.name:t for t in runtime.build_tools(ctx,'main')};state=AgentState(session_id='s')
        await tools['TaskCreate'].call(_agent_state=state,subject='Compare',description='Compare headphones')
        await tools['TaskCreate'].call(_agent_state=state,subject='Compare',description='Compare headphones')
        assert len(state.tasks_context.tasks)==1
        restored=AgentState(session_id='s')
        await tools['TaskCreate'].call(_agent_state=restored,subject='Compare',description='Compare headphones')
        assert len(restored.tasks_context.tasks)==1
        await c.commerce.perform(ctx,'cart_get',{},'read')
        await c.commerce.perform(ctx,'cart_set',{'product_id':'p01','quantity':1},'write')
        assert (await c.commerce.perform(ctx,'cart_get',{},'read'))['items']=={'p01':1}
    finally: await c.close()
