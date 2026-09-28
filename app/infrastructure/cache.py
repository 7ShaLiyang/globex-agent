import hashlib
import json
import math
import logging
from redis.asyncio import Redis
log=logging.getLogger(__name__)

class Cache:
    def __init__(self,url): self.redis=Redis.from_url(url,decode_responses=True,socket_connect_timeout=2,socket_timeout=3) if url else None
    async def get(self,key):
        if self.redis:
            try:
                value=await self.redis.get('globex:'+key)
                return json.loads(value) if value else None
            except Exception: log.debug('Redis cache unavailable')
        return None
    async def set(self,key,value,ttl=300):
        if self.redis:
            try: await self.redis.set('globex:'+key,json.dumps(value,ensure_ascii=False),ex=ttl)
            except Exception: log.debug('Redis cache write unavailable')
    async def semantic_get(self,scope,vector):
        # Cache candidate IDs only: never cache buyer state, orders or generated answers.
        if not self.redis: return None
        try:
            for raw in await self.redis.lrange('globex:semantic:'+scope,0,49):
                p=json.loads(raw); v=p['v']
                if len(v)!=len(vector): continue
                dot=sum(x*y for x,y in zip(v,vector));norm=math.sqrt(sum(x*x for x in v)*sum(x*x for x in vector))
                if norm and dot/norm>=.997: return p['ids']
        except Exception: log.debug('semantic cache unavailable')
        return None
    async def semantic_set(self,scope,vector,ids):
        if self.redis:
            try:
                key='globex:semantic:'+scope
                async with self.redis.pipeline(transaction=True) as p:
                    p.lpush(key,json.dumps({'v':vector,'ids':ids}));p.ltrim(key,0,49);p.expire(key,120);await p.execute()
            except Exception: log.debug('semantic cache write unavailable')
    async def notify(self,ctx):
        if self.redis:
            try: await self.redis.publish('globex:events:'+ctx.session_id,ctx.job_id)
            except Exception: log.debug('event notification unavailable')
    async def close(self):
        if self.redis: await self.redis.aclose()

def cache_key(value): return hashlib.sha256(value.encode()).hexdigest()
