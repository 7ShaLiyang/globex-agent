import httpx
import pytest
from qdrant_client import AsyncQdrantClient
from agentscope.rag import TextParser,ApproxTokenChunker,KnowledgeBase,QdrantStore
from agentscope.embedding import EmbeddingModelBase,EmbeddingResponse
from app.composition import Container
from app.infrastructure.catalog import PRODUCTS
from app.infrastructure.settings import Settings

async def test_vector_reranker_and_downgrade(tmp_path):
    c=Container(Settings(database_url=f'sqlite+aiosqlite:///{tmp_path}/search.db',app_mode='demo',redis_url='',qdrant_url='',reranker_url='http://rerank.test'))
    await c.start()
    c.search.q=AsyncQdrantClient(':memory:')
    async def embed(_): return [1.,0.,0.]
    c.search.embed=embed
    await c.search.http.aclose()
    c.search.http=httpx.AsyncClient(transport=httpx.MockTransport(lambda r:httpx.Response(200,json={'results':[{'index':0,'relevance_score':1}]})))
    try:
        await c.search.index();await c.search.index()
        assert (await c.search.q.count(c.search.collection)).count==len(PRODUCTS)
        assert (await c.search.search('耳机'))['mode']=='embedding+rerank'
        await c.search.http.aclose()
        c.search.http=httpx.AsyncClient(transport=httpx.MockTransport(lambda r:httpx.Response(503)))
        result=await c.search.search('耳机');assert result['mode']=='embedding_only';assert result['warnings']
        async def failed(_): raise RuntimeError('offline')
        c.search.embed=failed
        assert (await c.search.search('耳机'))['mode']=='keyword_2gram'
    finally: await c.close()

async def test_markdown_parser_and_chunker():
    sections=await TextParser().parse(file='# 耳机\n通勤选择降噪耳机。'.encode(),filename='audio.md')
    chunks=await ApproxTokenChunker(chunk_size=350,overlap=40).chunk(sections)
    assert chunks and chunks[0].source=='audio.md'
    assert '耳机' in chunks[0].content.text

async def test_real_knowledgebase_embedding_and_qdrant(monkeypatch):
    import json,threading
    from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
    import app.infrastructure.knowledge as knowledge
    from app.infrastructure.cache import Cache
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args): pass
        def do_POST(self):
            body=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            inputs=body['input'];count=len(inputs) if isinstance(inputs,list) else 1
            result={'object':'list','data':[{'object':'embedding','embedding':[1.,0.,0.],'index':i} for i in range(count)],'model':'fake','usage':{'prompt_tokens':1,'total_tokens':1}}
            raw=json.dumps(result).encode();self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    store=QdrantStore(location=':memory:')
    monkeypatch.setattr(knowledge,'QdrantStore',lambda **kwargs:store)
    s=Settings(embedding_base_url=f'http://127.0.0.1:{server.server_port}/v1',embedding_api_key='local',embedding_model='fake',qdrant_url='http://test')
    try:
        kb=await knowledge.build_kb(s,Cache(''))
        assert kb.embedding_model.dimensions==3
        sections=await TextParser().parse(file=b'# Headphones\nTravel noise cancelling.',filename='audio.md')
        chunks=await ApproxTokenChunker(chunk_size=350,overlap=40).chunk(sections)
        async with store:
            await kb.insert_document(chunks,document_id='audio.md')
            await kb.insert_document(chunks,document_id='audio.md')
            results=await kb.search(['headphones'],top_k=3)
            assert len(results)==1
            assert results[0].document_id=='audio.md'
    finally: server.shutdown();server.server_close();thread.join()
