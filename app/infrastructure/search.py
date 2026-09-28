import hashlib
import json
import logging
import math
import re
import uuid
from pathlib import Path
import httpx
from qdrant_client import AsyncQdrantClient, models
from app.infrastructure.cache import cache_key
log=logging.getLogger(__name__)

def grams(text):
    text=re.sub(r'\s+','',text.lower())
    return {text[i:i+2] for i in range(max(len(text)-1,0))} or {text}

def rewrite(query):
    synonyms={'headphones':'耳机','earbuds':'耳机','backpack':'背包','charger':'充电器','bottle':'保温杯','watch':'手表',
              'suitcase':'行李箱 拉杆箱','luggage':'行李箱 拉杆箱','carry-on':'登机箱','carryon':'登机箱',
              'noise cancelling':'降噪','wireless':'无线 蓝牙'}
    q=query.strip().lower()
    return q+' '+' '.join(v for k,v in synonyms.items() if k in q)

class Search:
    def __init__(self,db,cache,settings):
        self.db,self.cache,self.s=db,cache,settings
        self.http=httpx.AsyncClient(timeout=15)
        self.q=AsyncQdrantClient(url=settings.qdrant_url,timeout=5) if settings.qdrant_url else None
        self.collection='catalog_'+cache_key(settings.embedding_base_url+settings.embedding_model)[:12]
    async def products(self):
        async with self.db.transaction() as u: return await u.list('products','*')
    async def embed(self,text):
        if not self.s.embedding_api_key: raise RuntimeError('Embedding not configured')
        key='emb:'+cache_key(self.s.embedding_base_url+self.s.embedding_model+text)
        cached=await self.cache.get(key)
        if cached: return cached
        r=await self.http.post(self.s.embedding_base_url.rstrip('/')+'/embeddings',
            headers={'Authorization':'Bearer '+self.s.embedding_api_key},json={'model':self.s.embedding_model,'input':text})
        r.raise_for_status();v=r.json()['data'][0]['embedding']
        if not v or not all(isinstance(x,(int,float)) and math.isfinite(x) for x in v): raise ValueError('invalid embedding')
        await self.cache.set(key,v,86400);return v
    async def index(self):
        if not self.q: raise RuntimeError('Qdrant not configured')
        products=await self.products();points=[]
        for p in products:
            v=await self.embed(p['title']+' '+p['tags']+' '+p.get('description',''))
            points.append(models.PointStruct(id=str(uuid.uuid5(uuid.NAMESPACE_URL,p['id'])),vector=v,payload={'product_id':p['id']}))
        if not await self.q.collection_exists(self.collection):
            await self.q.create_collection(self.collection,vectors_config=models.VectorParams(size=len(points[0].vector),distance=models.Distance.COSINE))
        await self.q.upsert(self.collection,points,wait=True)
        return {'indexed':len(points),'collection':self.collection}
    async def search(self,query,limit=6,category=None,max_price=None):
        if not query.strip() or len(query)>2000: return {'products':[],'mode':'keyword_2gram','warnings':['查询不能为空或超过 2000 字符']}
        limit=max(1,min(int(limit),12));q=rewrite(query);products=await self.products()
        if category:
            products=[p for p in products if p.get('category')==category]
        if max_price is not None:
            products=[p for p in products if float(p['price'])<=float(max_price)]
        byid={p['id']:p for p in products}
        warnings=[];mode='keyword_2gram';hits=[]
        try:
            if not self.q: raise RuntimeError('Qdrant 未配置')
            v=await self.embed(q)
            revision=cache_key(json.dumps([(p['id'],p['title'],p['tags']) for p in products],ensure_ascii=False))[:12]
            scope=self.collection+':'+revision
            ids=await self.cache.semantic_get(scope,v)
            if ids is None:
                response=await self.q.query_points(self.collection,query=v,limit=20)
                ids=[p.payload['product_id'] for p in response.points if p.score>=.15]
                await self.cache.semantic_set(scope,v,ids)
            hits=[byid[i] for i in ids if i in byid];mode='embedding_only'
            if hits and self.s.reranker_url:
                try:
                    r=await self.http.post(self.s.reranker_url,headers={'Authorization':'Bearer '+self.s.reranker_api_key},
                        json={'model':self.s.reranker_model,'query':q,'documents':[p['title']+' '+p['tags'] for p in hits],'top_n':limit})
                    r.raise_for_status(); ranks=r.json()['results']
                    indices=[int(x['index']) for x in ranks]
                    if not indices or len(set(indices))!=len(indices) or any(i<0 or i>=len(hits) for i in indices): raise ValueError('invalid ranking')
                    hits=[hits[i] for i in indices];mode='embedding+rerank'
                except Exception:
                    warnings.append('重排服务不可用，已使用向量召回排序')
        except Exception as e:
            log.info('vector search degraded: %s',type(e).__name__)
            warnings.append('向量检索不可用，已使用关键词检索')
        if not hits:
            g=grams(q)
            scored=[(len(g & grams(p['title']+' '+p['tags'])),p) for p in products]
            hits=[p for score,p in sorted(scored,key=lambda x:x[0],reverse=True) if score>0]
            mode='keyword_2gram'
        result={'products':hits[:limit],'mode':mode,'rewritten_query':q,'warnings':warnings,
            'filters':{'category':category,'max_price':max_price}}
        if not hits and any(x in q for x in ['关税','政策','customs','tariff']): result['web']=await self.web(query)
        return result
    async def knowledge(self,query):
        try:
            from app.infrastructure.knowledge import build_kb
            kb=await build_kb(self.s,self.cache)
            async with kb.vector_store:
                matches=await kb.search([query],top_k=4)
            return {'mode':'agentscope_knowledgebase','sources':[x.model_dump(mode='json') for x in matches]}
        except Exception:
            docs=[];g=grams(query)
            for path in sorted(Path('knowledge').glob('*.md')):
                text=path.read_text();score=len(g & grams(text))
                if score: docs.append((score,{'source':path.name,'text':text[:1800]}))
            return {'mode':'keyword_2gram','sources':[p for _,p in sorted(docs,key=lambda x:-x[0])[:3]],'notice':'本地教学知识，不代表最新政策'}
    async def web(self,query):
        if not self.s.web_search_api_key:
            return {'available':False,'sources':[],'notice':'未配置实时网页检索 API Key，无法获取实时商品'}
        try:
            domains=[x.strip() for x in self.s.web_search_domains.split(',') if x.strip()]
            if self.s.web_search_provider=='tavily':
                payload={'api_key':self.s.web_search_api_key,'query':query,'search_depth':'advanced',
                         'max_results':5,'include_answer':False,'include_domains':domains}
                headers={}
            else:
                payload={'query':query,'limit':5}
                headers={'Authorization':'Bearer '+self.s.web_search_api_key}
            r=await self.http.post(self.s.web_search_url,headers=headers,json=payload)
            r.raise_for_status();data=r.json()
            sources=[]
            for item in data.get('results',[])[:5]:
                sources.append({'title':item.get('title','未命名商品'),'url':item.get('url',''),
                                'snippet':item.get('content',item.get('snippet','')),
                                'score':item.get('score')})
            return {'available':True,'provider':self.s.web_search_provider,'sources':sources}
        except Exception: return {'available':False,'sources':[],'notice':'网页检索暂不可用'}
    async def web_to_knowledge(self,query):
        result=await self.web(query)
        if not result.get('available'):
            return result
        from app.infrastructure.knowledge import ingest_text
        sources=result.get('sources',[])
        text='\n\n'.join(f"# {item.get('title','网页资料')}\n来源：{item.get('url','')}\n{item.get('snippet','')}" for item in sources)
        if not text:
            return {**result,'indexed_chunks':0}
        try:
            chunks=await ingest_text(self.s,self.cache,'web-'+cache_key(query)[:16]+'.md',text,{'source':'web','query':query})
            return {**result,'indexed_chunks':chunks}
        except Exception:
            return {**result,'indexed_chunks':0,'notice':'已获取网页结果，但本地知识库写入失败'}
    async def close(self):
        await self.http.aclose()
        if self.q: await self.q.close()
