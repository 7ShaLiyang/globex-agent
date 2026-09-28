import json
import httpx
from pathlib import Path
from agentscope.rag import KnowledgeBase,QdrantStore,TextParser,ApproxTokenChunker
from agentscope.embedding import OpenAIEmbeddingModel, EmbeddingCacheBase
from agentscope.credential import OpenAICredential
from app.infrastructure.cache import cache_key

class RedisEmbeddingCache(EmbeddingCacheBase):
    def __init__(self,cache,scope): self.cache,self.scope=cache,scope
    def key(self,identifier): return 'kbemb:'+self.scope+':'+cache_key(json.dumps(identifier,sort_keys=True))
    async def store(self,embeddings,identifier,overwrite=False,**kwargs): await self.cache.set(self.key(identifier),embeddings,86400)
    async def retrieve(self,identifier): return await self.cache.get(self.key(identifier))
    async def remove(self,identifier):
        if self.cache.redis: await self.cache.redis.delete('globex:'+self.key(identifier))
    async def clear(self):
        if self.cache.redis:
            async for key in self.cache.redis.scan_iter(match='globex:kbemb:'+self.scope+':*'):
                await self.cache.redis.delete(key)

async def build_kb(s,cache):
    if not s.qdrant_url or not s.embedding_api_key: raise RuntimeError('KnowledgeBase 需要 Qdrant 和 embedding 配置')
    scope=cache_key(s.embedding_base_url+s.embedding_model)[:12]
    dimensions=await cache.get('embedding-dimension:'+scope)
    if dimensions is None:
        async with httpx.AsyncClient(timeout=15) as client:
            response=await client.post(s.embedding_base_url.rstrip('/')+'/embeddings',
                headers={'Authorization':'Bearer '+s.embedding_api_key},
                json={'model':s.embedding_model,'input':'dimension probe'})
            response.raise_for_status()
            dimensions=len(response.json()['data'][0]['embedding'])
        if dimensions<1: raise ValueError('Embedding returned empty vector')
        await cache.set('embedding-dimension:'+scope,dimensions,86400)
    model=OpenAIEmbeddingModel(credential=OpenAICredential(api_key=s.embedding_api_key,base_url=s.embedding_base_url),
        model=s.embedding_model,dimensions=dimensions,pass_dimensions=False,
        embedding_cache=RedisEmbeddingCache(cache,scope),max_retries=1)
    return KnowledgeBase(name='category-insights',description='品类洞察和跨境交易教学知识',embedding_model=model,
                         vector_store=QdrantStore(url=s.qdrant_url),collection='knowledge_'+scope)

async def ingest(s,cache):
    kb=await build_kb(s,cache);await kb.ensure_collection();count=0
    async with kb.vector_store:
        for path in sorted(Path('knowledge').glob('*.md')):
            sections=await TextParser().parse(file=path.read_bytes(),filename=path.name)
            chunks=await ApproxTokenChunker(chunk_size=350,overlap=40).chunk(sections)
            # Explicit replacement removes trailing chunks when a document shrinks.
            await kb.delete_document(path.name)
            await kb.insert_document(chunks,document_id=path.name,document_metadata={'source':path.name})
            count+=len(chunks)
    return {'chunks':count}

async def ingest_text(s,cache,document_id,text,metadata=None):
    """Index trusted text fetched by the web-search adapter into the local RAG store."""
    kb=await build_kb(s,cache);await kb.ensure_collection()
    sections=await TextParser().parse(file=text.encode('utf-8'),filename=document_id)
    chunks=await ApproxTokenChunker(chunk_size=350,overlap=40).chunk(sections)
    async with kb.vector_store:
        await kb.delete_document(document_id)
        await kb.insert_document(chunks,document_id=document_id,document_metadata=metadata or {'source':document_id})
    return len(chunks)
