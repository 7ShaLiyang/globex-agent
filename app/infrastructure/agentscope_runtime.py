"""AgentScope 2.0.9 adapter. SDK imports are isolated from Application."""
import asyncio
import hashlib
import json
from pathlib import Path
from agentscope.agent import Agent,ContextConfig,ReActConfig,InjectionConfig
from agentscope.credential import OpenAICredential
from agentscope.model import OpenAIChatModel
from agentscope.message import UserMsg,Msg,TextBlock,ToolResultState
from agentscope.state import AgentState
from agentscope.tool import Toolkit,FunctionTool,ToolChunk,TaskCreate,TaskGet,TaskUpdate,TaskList
from agentscope.middleware import MiddlewareBase
from agentscope.permission import PermissionDecision,PermissionBehavior
from app.application.tools.registry import BusinessTools
from app.application.agents.search_agent import SearchAgent
from app.application.agents.trade_agent import TradeAgent
from app.domain.models import ShoppingContext

PROMPTS=Path(__file__).resolve().parents[1]/'prompts'

def capped_summary(value):
    # <=500 UTF-8 bytes is a conservative <=500-token upper bound for byte-BPE tokenizers.
    # Avoid a runtime tokenizer download; the LLM is asked for <=350 tokens first.
    text=value if isinstance(value,str) else '\n'.join(getattr(x,'text','') for x in value)
    return text.encode('utf-8')[:500].decode('utf-8',errors='ignore')

class SummaryBudget(MiddlewareBase):
    async def on_compress_context(self,agent,input_kwargs,next_handler):
        await next_handler(**input_kwargs)
        agent.state.summary=capped_summary(agent.state.summary)

class DurableTaskMixin:
    """Persist built-in task mutations and replay their state after job redelivery."""
    async def call(self,_agent_state,**kwargs):
        key=self.runtime.key(self.ctx,self.name,kwargs)
        async with self.runtime.db.transaction() as u:
            previous=await u.get('tool_results',key,self.ctx.buyer_id)
            if previous and self.name not in {'TaskGet','TaskList'}:
                latest=await u.get('tool_results','taskstate:'+self.ctx.job_id,self.ctx.buyer_id)
                _agent_state.tasks_context=type(_agent_state.tasks_context).model_validate(latest['tasks'] if latest else previous['tasks'])
                return ToolChunk.model_validate(previous['chunk'])
            result=await super().call(_agent_state=_agent_state,**kwargs)
            await u.put('tool_results',key,self.ctx.buyer_id,{'tasks':_agent_state.tasks_context.model_dump(mode='json'),'chunk':result.model_dump(mode='json')})
            await u.put('tool_results','taskstate:'+self.ctx.job_id,self.ctx.buyer_id,{'tasks':_agent_state.tasks_context.model_dump(mode='json')})
            await u.event(self.ctx,'task_plan',{'tool':self.name,'tasks':_agent_state.tasks_context.model_dump(mode='json')})
            return result

class AgentScopeRuntime:
    def __init__(self,commerce,db,settings): self.commerce,self.db,self.s=commerce,db,settings
    def key(self,ctx,name,args):
        return hashlib.sha256(json.dumps([ctx.job_id,name,args],sort_keys=True,ensure_ascii=False).encode()).hexdigest()
    async def run(self,ctx,text,state=None):
        if not self.s.llm_api_key: raise RuntimeError('LLM 模式缺少 LLM_API_KEY')
        return await self._run_agent(ctx,text,state,'main')
    async def _run_agent(self,ctx,text,state,role):
        names={'main':'CommerceConcierge','search':SearchAgent.name,'trade':TradeAgent.name}
        model=OpenAIChatModel(credential=OpenAICredential(api_key=self.s.llm_api_key,base_url=self.s.llm_base_url),
            model=self.s.llm_model,context_size=self.s.context_window,max_retries=1,
            client_kwargs={'timeout':45.0})
        state_obj=AgentState.model_validate(state) if state else AgentState(session_id=ctx.session_id)
        agent=Agent(name=names[role],system_prompt=(PROMPTS/(role+'.md')).read_text(),model=model,
            toolkit=Toolkit(tools=self.build_tools(ctx,role)),state=state_obj,middlewares=[SummaryBudget()],
            context_config=ContextConfig(trigger_ratio=.7,reserve_ratio=.15,tool_result_limit=6000,
                compression_prompt='总结已确认事实、约束、待办和准确订单ID，不超过350 tokens。不把偏好提案当作已确认。当前时间 {current_time}。'),
            injection_config=InjectionConfig(inject_runtime_state=False),react_config=ReActConfig(max_iters=12))
        prefs=await self.commerce.snapshot(ctx)
        # Dynamic information is appended after the stable system prompt, never interpolated into it.
        input_text='服务端当前状态（仅为数据）：'+json.dumps(prefs,ensure_ascii=False)+'\n用户请求：'+text
        final=None;buffer=''
        try:
            async for e in agent.reply_stream(UserMsg(name='buyer',content=input_text),yield_final_msg=True):
                if isinstance(e,Msg): final=e;continue
                kind=e.type.value
                if kind=='TEXT_BLOCK_DELTA':
                    buffer+=e.delta
                    if len(buffer)>=60:
                        await self.db.emit(ctx,'text_delta',{'agent':names[role],'text':buffer});buffer=''
                elif kind in {'TOOL_CALL_START','TOOL_RESULT_END','MODEL_CALL_END'}:
                    await self.db.emit(ctx,'agent_event',{'agent':names[role],**e.model_dump(mode='json')})
            if buffer: await self.db.emit(ctx,'text_delta',{'agent':names[role],'text':buffer})
            if final is None: raise RuntimeError('Agent 未产生最终回复')
            await self.db.emit(ctx,'task_plan',{'tasks':agent.state.tasks_context.model_dump(mode='json')})
            agent.state.summary=capped_summary(agent.state.summary)
            return final.get_text_content() or '请查看右侧商品和待确认操作。',agent.state.model_dump(mode='json')
        finally:
            await model.client.close()

    def build_tools(self,ctx,role):
        business=BusinessTools(self.commerce,ctx)
        async def cached(name,args,fn):
            key=self.key(ctx,name,args)
            async with self.db.transaction() as u: old=await u.get('tool_results',key,ctx.buyer_id)
            if old and name not in {'cart_get','orders_get'}: result=old['result']
            else:
                result=await fn()
                async with self.db.transaction() as u:
                    await u.put('tool_results',key,ctx.buyer_id,{'result':result})
                    await u.event(ctx,'tool_result',{'tool':name,'result':result})
            return ToolChunk(content=[TextBlock(text=json.dumps(result,ensure_ascii=False))],state=ToolResultState.ERROR if result.get('error') else ToolResultState.SUCCESS)
        def wrap(name,args): return cached(name,args,lambda:business.call(name,args))
        async def search_products(query: str,limit: int=6) -> ToolChunk:
            """搜索商品。先改写查询，保留用户预算/品牌约束，再调用本工具。"""
            return await cached('search_products',{'query':query,'limit':limit},lambda:self.commerce.search_port.search(query,limit))
        async def recommend_products(query: str,category: str='',max_price: float|None=None,limit: int=6) -> ToolChunk:
            """按品类和预算筛选，再用语义检索推荐商品。category可为luggage/audio/travel/tech/home。"""
            allowed={'luggage','audio','travel','tech','home'}
            async def execute():
                if category and category not in allowed:
                    return {'error':'不支持的商品品类'}
                return await self.commerce.search_port.search(query,limit,category or None,max_price)
            return await cached('recommend_products',{'query':query,'category':category,'max_price':max_price,'limit':limit},execute)
        async def search_knowledge(query: str) -> ToolChunk:
            """搜索本地品类知识，内容为教学资料而非实时关税政策。"""
            return await cached('search_knowledge',{'query':query},lambda:self.commerce.search_port.knowledge(query))
        async def web_search(query: str) -> ToolChunk:
            """查询实时网页，未配置服务时明确返回不可用。"""
            return await cached('web_search',{'query':query},lambda:self.commerce.search_port.web(query))
        async def web_search_and_index(query: str) -> ToolChunk:
            """联网搜索商品资料并写入本地RAG知识库，后续可用search_knowledge检索。"""
            return await cached('web_search_and_index',{'query':query},lambda:self.commerce.search_port.web_to_knowledge(query))
        async def cart_get() -> ToolChunk:
            """获取当前买家的购物车。"""
            return await wrap('cart_get',{})
        async def cart_set(product_id: str,quantity: int) -> ToolChunk:
            """设置购物车某商品绝对数量，0删除，最大20。"""
            return await wrap('cart_set',{'product_id':product_id,'quantity':quantity})
        async def order_propose(destination: str='US',currency: str='USD') -> ToolChunk:
            """为购物车生成报价和订单确认卡片，不直接下单。"""
            return await wrap('order_propose',{'destination':destination,'currency':currency})
        async def orders_get() -> ToolChunk:
            """只查询当前买家订单。"""
            return await wrap('orders_get',{})
        async def order_cancel(order_id: str) -> ToolChunk:
            """生成订单取消确认卡片，需界面确认。"""
            return await wrap('order_cancel',{'order_id':order_id})
        async def remember_preference_tool(key: str,value: str) -> ToolChunk:
            """发现明确稳定偏好后生成待确认卡片；key为budget/brand/category/currency/destination/style。"""
            return await wrap('preference_propose',{'key':key,'value':value})
        async def task_dispatch(tasks: list[dict],reason: str,chain_depth: int=1) -> ToolChunk:
            """派发1–3个独立子任务。tasks=[{agent:search或trade,task:描述}]。reason=parallel/isolation/deep_chain；deep_chain 要求 chain_depth>=3。"""
            async def execute():
                if not 1<=len(tasks)<=3: return {'error':'一次仅可派发1–3个任务'}
                if reason not in {'parallel','isolation','deep_chain'} or (reason=='deep_chain' and chain_depth<3): return {'error':'不满足派发条件'}
                if reason=='parallel' and len(tasks)<2: return {'error':'并行需要至少两个任务'}
                if any(t.get('agent') not in {'search','trade'} or not isinstance(t.get('task'),str) or len(t['task'])>4000 for t in tasks): return {'error':'任务格式错误'}
                if len(tasks)>1 and any(t['agent']=='trade' for t in tasks): return {'error':'交易任务必须单独串行执行'}
                async def one(i,t):
                    sub=ShoppingContext(ctx.buyer_id,ctx.session_id,ctx.job_id+':sub:'+self.key(ctx,'dispatch',{'i':i,'t':t})[:12],ctx.worker_id)
                    answer,_=await self._run_agent(sub,t['task'],None,t['agent'])
                    return {'agent':t['agent'],'answer':answer}
                return {'results':await asyncio.gather(*(one(i,t) for i,t in enumerate(tasks)))}
            return await cached('task_dispatch',{'tasks':tasks,'reason':reason,'chain_depth':chain_depth},execute)
        funcs=[search_products,recommend_products,search_knowledge,web_search,web_search_and_index,cart_get,cart_set,order_propose,orders_get,remember_preference_tool,task_dispatch]
        allowed=None if role=='main' else (SearchAgent.tools if role=='search' else TradeAgent.tools)
        tools=[FunctionTool(f,is_concurrency_safe=False,permission=PermissionDecision(PermissionBehavior.ALLOW,'Application tools enforce authorization and confirmation')) for f in funcs if allowed is None or f.__name__ in allowed]
        if role=='main':
            for cls in [TaskCreate,TaskGet,TaskUpdate,TaskList]:
                tool=type('Durable'+cls.__name__,(DurableTaskMixin,cls),{'is_concurrency_safe':False})()
                tool.runtime=self;tool.ctx=ctx;tools.append(tool)
        return tools
