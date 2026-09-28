"""Explicit deterministic demo. It never pretends to invoke an LLM."""
from app.application.tools.registry import BusinessTools
class DemoRuntime:
    def __init__(self,commerce,db): self.commerce,self.db=commerce,db
    async def run(self,ctx,text,state=None):
        tools=BusinessTools(self.commerce,ctx)
        if '记住' in text:
            value=text.split('记住',1)[1].strip() or text
            result=await tools.call('preference_propose',{'key':'style','value':value[:200]})
            reply='我整理了一条偏好候选，请在右侧确认后保存。'
        else:
            result=await self.commerce.search_port.web_to_knowledge(text)
            if result.get('available'):
                sources=result.get('sources',[])
                reply='联网搜索到以下商品资料：\n'+'\n'.join(f"• {x.get('title','未命名商品')}\n  {x.get('url','')}" for x in sources)
            else:
                reply='当前是演示模式，尚未配置联网商品搜索。请配置 LLM_API_KEY 和 WEB_SEARCH_URL 后重启服务。'
        if result.get('error'): reply=result['error']
        await self.db.emit(ctx,'tool_result',{'tool':'demo','result':result})
        return reply,{'mode':'demo','turns':(state or {}).get('turns',0)+1}
