import json
from agentscope.state import AgentState
from agentscope.tool import ToolChunk
from agentscope.message import TextBlock
from app.infrastructure.agentscope_runtime import capped_summary,AgentScopeRuntime
from app.infrastructure.settings import Settings
from app.domain.models import ShoppingContext

def test_summary_budget(): assert len(capped_summary('你好'*1000).encode())<=500

def test_sdk_tool_schema():
    runtime=AgentScopeRuntime(None,None,Settings(llm_api_key='test'))
    tools=runtime.build_tools(ShoppingContext('a','s','j'),'main')
    names=[t.name for t in tools]
    assert {'TaskCreate','TaskGet','TaskUpdate','TaskList','task_dispatch','remember_preference_tool'}<=set(names)
    for t in tools:
        assert 'buyer_id' not in json.dumps(t.input_schema)
        assert 'confirm'!=t.name
    state=AgentState(session_id='test')
    assert AgentState.model_validate(state.model_dump(mode='json')).session_id=='test'
    assert ToolChunk(content=[TextBlock(text='ok')]).content[0].text=='ok'
