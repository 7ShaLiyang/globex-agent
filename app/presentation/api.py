import asyncio
import contextlib
import hashlib
import json
import secrets
import time
import uuid
from contextlib import asynccontextmanager
from typing import Annotated,Literal
from fastapi import FastAPI,Depends,Header,HTTPException,WebSocket,WebSocketDisconnect,Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel,Field,ConfigDict,ValidationError
from app.composition import Container
from app.domain.models import ShoppingContext,BusinessError

class MessageInput(BaseModel):
    text: str=Field(min_length=1,max_length=4000)
    request_id: str=Field(min_length=8,max_length=100)
class ActionInput(BaseModel):
    model_config=ConfigDict(extra='forbid')
    action: Literal['cart_set','order_propose','preference_propose','confirm','reject']
    args: dict=Field(default_factory=dict)
    request_id: str=Field(min_length=8,max_length=100)

class CartArgs(BaseModel):
    product_id: str = Field(pattern=r'^p[0-9]{2}$')
    quantity: int = Field(strict=True, ge=0, le=20)
class QuoteArgs(BaseModel):
    destination: Literal['US','CN','DE']='US'
    currency: Literal['USD','CNY','EUR']='USD'
class OrderArgs(BaseModel):
    order_id: uuid.UUID
class ConfirmationArgs(BaseModel):
    proposal_id: uuid.UUID
class PreferenceArgs(BaseModel):
    key: Literal['budget','brand','category','currency','destination','style']
    value: str=Field(min_length=1,max_length=200)

def create_app(settings=None):
    c=Container(settings)
    @asynccontextmanager
    async def lifespan(app):
        await c.start()
        task=asyncio.create_task(c.jobs.loop()) if c.settings.inline_worker else None
        yield
        if task:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError): await task
        await c.close()
    app=FastAPI(title='Globex Agent',version='1.0.0',lifespan=lifespan)
    app.state.container=c
    origins=c.settings.allowed_origins.split(',')
    app.add_middleware(CORSMiddleware,allow_origins=origins,allow_methods=['GET','POST'],allow_headers=['Authorization','Content-Type'])
    @app.exception_handler(BusinessError)
    async def business_error(_,exc): return JSONResponse(status_code=409,content={'detail':str(exc)})
    async def resolve(token):
        if not token: raise HTTPException(401,'需要访问凭证')
        async with c.db.transaction() as u:
            identity=await u.get('identities',hashlib.sha256(token.encode()).hexdigest(),'*')
        if not identity or identity['expires_at']<time.time(): raise HTTPException(401,'凭证已过期，请重新进入')
        return identity['buyer_id']
    async def auth(authorization: Annotated[str|None,Header()]=None):
        return await resolve(authorization[7:] if authorization and authorization.startswith('Bearer ') else '')
    async def session_context(buyer,id):
        async with c.db.transaction() as u:
            session=await u.get('sessions',id,buyer)
        if not session: raise HTTPException(404,'会话不存在')
        return ShoppingContext(buyer,id,'ui')
    @app.get('/api/health')
    async def health(): return {'status':'ok','mode':c.settings.app_mode,'model':c.settings.llm_model if c.settings.app_mode=='llm' else None}
    @app.post('/api/guest')
    async def guest():
        token=secrets.token_urlsafe(32);buyer=str(uuid.uuid4())
        async with c.db.transaction() as u:
            await u.put('identities',hashlib.sha256(token.encode()).hexdigest(),'*',{'buyer_id':buyer,'expires_at':time.time()+30*86400})
        return {'token':token}
    @app.get('/api/sessions')
    async def sessions(buyer=Depends(auth)):
        async with c.db.transaction() as u: rows=await u.list('sessions',buyer)
        return [{'id':r['id'],'title':r['title']} for r in rows]
    @app.post('/api/sessions')
    async def new_session(buyer=Depends(auth)):
        id=str(uuid.uuid4());row={'id':id,'title':'新的购物旅程','state':None}
        async with c.db.transaction() as u: await u.put('sessions',id,buyer,row)
        return {'id':id,'title':row['title']}
    @app.delete('/api/sessions/{id}')
    async def delete_session(id:str,buyer=Depends(auth)):
        await session_context(buyer,id)
        try:
            deleted=await c.db.delete_session(buyer,id)
        except RuntimeError as exc:
            raise HTTPException(409,str(exc)) from exc
        return {'deleted':deleted,'id':id}
    @app.get('/api/products')
    async def products(q: str=Query('',max_length=2000),buyer=Depends(auth)):
        return await c.search.search(q) if q else {'products':await c.search.products(),'mode':'catalog'}
    @app.get('/api/sessions/{id}/state')
    async def snapshot(id:str,buyer=Depends(auth)):
        return await c.commerce.snapshot(await session_context(buyer,id))
    @app.get('/api/sessions/{id}/events')
    async def events(id:str,after:int=Query(0,ge=0),buyer=Depends(auth)):
        await session_context(buyer,id)
        return await c.db.events(buyer,id,after)
    @app.post('/api/sessions/{id}/messages',status_code=202)
    async def message(id:str,body:MessageInput,buyer=Depends(auth)):
        await session_context(buyer,id)
        if not body.text.strip(): raise HTTPException(422,'消息不能为空')
        return await c.jobs.submit(buyer,id,body.text,body.request_id)
    @app.get('/api/jobs/{id}')
    async def job(id:str,buyer=Depends(auth)):
        result=await c.jobs.get(buyer,id)
        if not result: raise HTTPException(404,'任务不存在')
        return result
    @app.post('/api/sessions/{id}/actions')
    async def action(id:str,body:ActionInput,buyer=Depends(auth)):
        ctx=await session_context(buyer,id)
        permitted={'cart_set':{'product_id','quantity'},'order_propose':{'destination','currency'},
               'preference_propose':{'key','value'},'confirm':{'proposal_id'},'reject':{'proposal_id'}}
        if set(body.args)-permitted[body.action]: raise HTTPException(422,'操作包含未知字段')
        schemas={'cart_set':CartArgs,'order_propose':QuoteArgs,
                 'preference_propose':PreferenceArgs,'confirm':ConfirmationArgs,'reject':ConfirmationArgs}
        try: body.args=schemas[body.action].model_validate(body.args).model_dump(mode='json')
        except ValidationError as e: raise HTTPException(422,'操作参数格式错误') from e
        mirror_key='idem:'+hashlib.sha256((buyer+body.request_id).encode()).hexdigest()
        digest=hashlib.sha256(json.dumps([body.action,body.args],sort_keys=True,ensure_ascii=False).encode()).hexdigest()
        cached=await c.cache.get(mirror_key)
        if cached:
            if cached.get('digest')!=digest: raise BusinessError('同一幂等键不能用于不同请求')
            return cached['result']
        try: result=await c.commerce.perform(ctx,body.action,body.args,'ui:'+body.request_id)
        except (KeyError,TypeError) as e: raise HTTPException(422,'操作参数不完整或格式错误') from e
        await c.cache.set(mirror_key,{'digest':digest,'result':result},86400)
        return result
    @app.websocket('/api/ws/{id}')
    async def socket(ws:WebSocket,id:str):
        origin=ws.headers.get('origin')
        if origin and origin not in origins: await ws.close(code=1008);return
        await ws.accept()
        pub=None
        try:
            # Token is sent in the first frame, never in URL/access logs.
            hello=await asyncio.wait_for(ws.receive_json(),timeout=10)
            buyer=await resolve(hello.get('token',''));await session_context(buyer,id)
            after=max(0,int(hello.get('after',0)))
            if c.cache.redis:
                try:
                    pub=c.cache.redis.pubsub();await pub.subscribe('globex:events:'+id)
                except Exception:
                    if pub: await pub.aclose()
                    pub=None
            while True:
                rows=await c.db.events(buyer,id,after)
                for event in rows:
                    await ws.send_json(event);after=event['seq']
                if pub:
                    try: await pub.get_message(ignore_subscribe_messages=True,timeout=.4)
                    except Exception: await pub.aclose();pub=None
                else: await asyncio.sleep(.4)
                if not rows: await ws.send_json({'type':'heartbeat','seq':after})
        except (WebSocketDisconnect,RuntimeError): pass
        except (HTTPException,ValueError,TypeError,asyncio.TimeoutError):
            with contextlib.suppress(RuntimeError): await ws.close(code=1008)
        finally:
            if pub: await pub.aclose()
    return app

app=create_app()
