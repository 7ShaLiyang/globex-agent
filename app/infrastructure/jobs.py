import asyncio
import contextlib
import json
import logging
import time
import uuid
from sqlalchemy import text
from app.domain.models import ShoppingContext, BusinessError
log=logging.getLogger(__name__)

class Jobs:
    def __init__(self,db,cache,agent,settings):
        self.db,self.cache,self.agent,self.s=db,cache,agent,settings
        self.worker_id=str(uuid.uuid4());self.group_ready=False
    async def submit(self,buyer,session,message,key):
        async with self.db.transaction() as u:
            if not await u.get('sessions',session,buyer): raise BusinessError('会话不存在')
            prior=(await u.conn.execute(text('SELECT id,input FROM jobs WHERE buyer=:b AND session=:s AND request_key=:k'),dict(b=buyer,s=session,k=key))).mappings().first()
            if prior:
                if prior['input']!=message: raise BusinessError('幂等键已经用于其他消息')
                return {'id':prior['id']}
            count=(await u.conn.execute(text("SELECT count(*) FROM jobs WHERE buyer=:b AND status IN ('queued','running')"),dict(b=buyer))).scalar()
            if count>=10: raise BusinessError('待处理任务过多，请稍后再试')
            job=str(uuid.uuid4());now=time.time()
            await u.conn.execute(text("INSERT INTO jobs(id,buyer,session,input,status,created,request_key) VALUES(:i,:b,:s,:m,'queued',:t,:k)"),dict(i=job,b=buyer,s=session,m=message,t=now,k=key))
            await u.event(ShoppingContext(buyer,session,job),'user_message',{'text':message})
        # SQLite job row is a durable outbox; loss of this Redis notification is safe.
        if self.cache.redis:
            try: await self.cache.redis.xadd('globex:jobs',{'id':job},maxlen=10000,approximate=True)
            except Exception: log.info('Redis unavailable; durable outbox will be scanned')
        return {'id':job}
    async def claim(self,preferred=None):
        async with self.db.transaction() as u:
            now=time.time()
            # Reclaim timed-out leases. Heartbeats + a fence prevent stale completions.
            await u.conn.execute(text("UPDATE jobs SET status='queued',worker='' WHERE status='running' AND lease<:t"),{'t':now})
            # Preserve FIFO per session. Different sessions may run on different workers.
            sql="""SELECT j.* FROM jobs j WHERE j.status='queued'
                AND NOT EXISTS(SELECT 1 FROM jobs r WHERE r.session=j.session AND r.status='running')
                AND NOT EXISTS(SELECT 1 FROM jobs q WHERE q.session=j.session AND q.status='queued' AND (q.created<j.created OR (q.created=j.created AND q.rowid<j.rowid)))
                ORDER BY CASE WHEN j.id=:p THEN 0 ELSE 1 END,j.created LIMIT 1"""
            row=(await u.conn.execute(text(sql),{'p':preferred or ''})).mappings().first()
            if not row: return None
            row=dict(row)
            await u.conn.execute(text("UPDATE jobs SET status='running',worker=:w,lease=:l,attempts=attempts+1 WHERE id=:i"),dict(w=self.worker_id,l=now+60,i=row['id']))
            row['attempts']+=1
            await u.event(ShoppingContext(row['buyer'],row['session'],row['id']),'job_started',{'attempt':row['attempts']})
            return row
    async def heartbeat(self,id):
        while True:
            await asyncio.sleep(15)
            async with self.db.transaction() as u:
                result=await u.conn.execute(text("UPDATE jobs SET lease=:l WHERE id=:i AND worker=:w AND status='running'"),dict(l=time.time()+60,i=id,w=self.worker_id))
                if not result.rowcount: return
    async def finish(self,row,answer,state,error=None):
        ctx=ShoppingContext(row['buyer'],row['session'],row['id'])
        async with self.db.transaction() as u:
            result=await u.conn.execute(text("UPDATE jobs SET status=:s,result=:r,error=:e,lease=0 WHERE id=:i AND worker=:w AND status='running'"),
                dict(s='failed' if error else 'done',r=answer,e=error,i=row['id'],w=self.worker_id))
            if not result.rowcount: return
            session=await u.get('sessions',row['session'],row['buyer'])
            if not error:
                session['state']=state;await u.put('sessions',row['session'],row['buyer'],session)
                await u.event(ctx,'assistant_message',{'text':answer})
            await u.event(ctx,'job_finished',{'status':'failed' if error else 'done','error':error})
        if self.cache.redis:
            try: await self.cache.redis.publish('globex:events:'+row['session'],row['id'])
            except Exception: pass
    async def execute(self,row):
        heartbeat=asyncio.create_task(self.heartbeat(row['id']))
        try:
            if row['attempts']>3: raise RuntimeError('任务恢复次数超过上限')
            async with self.db.transaction() as u: session=await u.get('sessions',row['session'],row['buyer'])
            ctx=ShoppingContext(row['buyer'],row['session'],row['id'],self.worker_id)
            answer,state=await asyncio.wait_for(self.agent.run(ctx,row['input'],session.get('state')),timeout=self.s.job_timeout)
            await self.finish(row,answer,state)
        except asyncio.CancelledError: raise
        except Exception as e:
            # Do not send upstream exceptions containing credentials or HTTP headers to clients.
            log.error('job %s failed: %s',row['id'],type(e).__name__)
            await self.finish(row,None,None,'请求执行失败或超时，请检查模型配置和服务日志后重试。已确认的业务操作不会回滚。')
        finally:
            heartbeat.cancel()
            with contextlib.suppress(asyncio.CancelledError): await heartbeat
    async def stream_hint(self):
        r=self.cache.redis
        if not r: return None,None
        try:
            if not self.group_ready:
                try: await r.xgroup_create('globex:jobs','workers',id='0',mkstream=True)
                except Exception as e:
                    if 'BUSYGROUP' not in str(e): raise
                self.group_ready=True
            recovered=await r.xautoclaim('globex:jobs','workers',self.worker_id,min_idle_time=70000,start_id='0-0',count=1)
            items=recovered[1]
            if not items:
                stream=await r.xreadgroup('workers',self.worker_id,{'globex:jobs':'>'},count=1,block=400)
                items=stream[0][1] if stream else []
            if items: return items[0][0],items[0][1]['id']
        except Exception: self.group_ready=False
        return None,None
    async def loop(self):
        while True:
            try:
                stream_id,hint=await self.stream_hint()
                row=await self.claim(hint)
                if row: await self.execute(row)
                if stream_id and self.cache.redis:
                    # Acknowledgment only removes the notification. SQLite remains authoritative.
                    await self.cache.redis.xack('globex:jobs','workers',stream_id)
                if not row: await asyncio.sleep(.5)
            except asyncio.CancelledError: raise
            except Exception as e:
                log.error('worker loop: %s',type(e).__name__);await asyncio.sleep(1)
    async def get(self,buyer,id):
        async with self.db.engine.connect() as c:
            row=(await c.execute(text('SELECT id,session,status,result,error FROM jobs WHERE buyer=:b AND id=:i'),dict(b=buyer,i=id))).mappings().first()
            return dict(row) if row else None
