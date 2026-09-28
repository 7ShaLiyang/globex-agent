"""No API credentials are needed for this compatibility check."""
from importlib.metadata import version
from agentscope.agent import Agent,ContextConfig,InjectionConfig
from agentscope.tool import FunctionTool,Toolkit,TaskCreate,TaskGet,TaskUpdate,TaskList
from agentscope.rag import KnowledgeBase
assert version('agentscope')=='2.0.9'
assert ContextConfig(trigger_ratio=.7).trigger_ratio==.7
print('AgentScope 2.0.9 interfaces OK')
