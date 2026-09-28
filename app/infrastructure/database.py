import json
import time
from contextlib import asynccontextmanager
from pathlib import Path
from sqlalchemy import text, event
from sqlalchemy.ext.asyncio import create_async_engine

TABLES = {'products', 'orders', 'carts', 'preferences', 'confirmations', 'idempotency', 'sessions', 'identities', 'tool_results'}
def encode(data): return json.dumps(data, ensure_ascii=False, separators=(',', ':'))

class SqlUnitOfWork:
    def __init__(self, conn): self.conn = conn
    def table(self, kind):
        if kind not in TABLES: raise ValueError('Unknown table')
        return kind
    async def get(self, kind, id, owner):
        r = await self.conn.execute(text(f'SELECT data FROM {self.table(kind)} WHERE id=:id AND owner=:owner'), {'id': id, 'owner': owner})
        raw = r.scalar_one_or_none()
        return json.loads(raw) if raw else None
    async def put(self, kind, id, owner, data):
        await self.conn.execute(text(f'INSERT INTO {self.table(kind)}(id,owner,data) VALUES(:id,:owner,:data) ON CONFLICT(id,owner) DO UPDATE SET data=excluded.data'), {'id': id, 'owner': owner, 'data': encode(data)})
    async def list(self, kind, owner):
        r = await self.conn.execute(text(f'SELECT data FROM {self.table(kind)} WHERE owner=:owner ORDER BY rowid'), {'owner': owner})
        return [json.loads(row[0]) for row in r]
    async def event(self, ctx, type, data):
        if ctx.worker_id:
            root_job=ctx.job_id.split(':',1)[0]
            valid=(await self.conn.execute(text("SELECT 1 FROM jobs WHERE id=:i AND worker=:w AND status='running' AND lease>:t"),dict(i=root_job,w=ctx.worker_id,t=time.time()))).scalar()
            if not valid: raise RuntimeError('Worker lease lost; transaction rolled back')
        await self.conn.execute(text('INSERT INTO events(buyer,session,job,type,data,created) VALUES(:b,:s,:j,:t,:d,:c)'),
                               dict(b=ctx.buyer_id,s=ctx.session_id,j=ctx.job_id,t=type,d=encode(data),c=time.time()))

class Database:
    def __init__(self, url):
        self.notifier=None
        if url.startswith('sqlite+aiosqlite:///'):
            path=url.split('///',1)[1]
            if path != ':memory:': Path(path).parent.mkdir(parents=True,exist_ok=True)
        self.engine=create_async_engine(url, connect_args={'timeout': 30})
        @event.listens_for(self.engine.sync_engine, 'connect')
        def pragmas(conn, _):
            cur=conn.cursor();cur.execute('PRAGMA busy_timeout=30000');cur.execute('PRAGMA foreign_keys=ON');cur.close()
    async def init(self):
        async with self.engine.begin() as c:
            await c.execute(text('PRAGMA journal_mode=WAL'))
            for name in sorted(TABLES):
                await c.execute(text(f'CREATE TABLE IF NOT EXISTS {name}(id TEXT NOT NULL,owner TEXT NOT NULL,data TEXT NOT NULL,PRIMARY KEY(id,owner))'))
            await c.execute(text('CREATE TABLE IF NOT EXISTS events(seq INTEGER PRIMARY KEY AUTOINCREMENT,buyer TEXT,session TEXT,job TEXT,type TEXT,data TEXT,created REAL)'))
            await c.execute(text('CREATE INDEX IF NOT EXISTS event_session ON events(buyer,session,seq)'))
            await c.execute(text('CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY,buyer TEXT,session TEXT,input TEXT,status TEXT,created REAL,lease REAL DEFAULT 0,worker TEXT DEFAULT "",attempts INTEGER DEFAULT 0,result TEXT,error TEXT,request_key TEXT,UNIQUE(buyer,session,request_key))'))
            await c.execute(text('CREATE INDEX IF NOT EXISTS job_status ON jobs(status,lease,created)'))
    @asynccontextmanager
    async def transaction(self):
        async with self.engine.connect() as c:
            # Serialize SQLite writers across processes; never hold across a network call.
            await c.execute(text('BEGIN IMMEDIATE'))
            try:
                yield SqlUnitOfWork(c)
                await c.commit()
            except BaseException:
                await c.rollback(); raise
    async def events(self, buyer, session, after=0):
        async with self.engine.connect() as c:
            rows=await c.execute(text('SELECT * FROM events WHERE buyer=:b AND session=:s AND seq>:a ORDER BY seq LIMIT 300'),dict(b=buyer,s=session,a=after))
            return [{**dict(r), 'data':json.loads(r['data'])} for r in rows.mappings()]
    async def delete_session(self,buyer,session):
        async with self.transaction() as u:
            if not await u.get('sessions',session,buyer):
                return False
            running=(await u.conn.execute(text("SELECT count(*) FROM jobs WHERE buyer=:b AND session=:s AND status='running'"),dict(b=buyer,s=session))).scalar()
            if running:
                raise RuntimeError('会话正在处理请求，请稍后再删除')
            await u.conn.execute(text('DELETE FROM events WHERE buyer=:b AND session=:s'),dict(b=buyer,s=session))
            await u.conn.execute(text('DELETE FROM jobs WHERE buyer=:b AND session=:s'),dict(b=buyer,s=session))
            await u.conn.execute(text('DELETE FROM sessions WHERE owner=:b AND id=:s'),dict(b=buyer,s=session))
            return True
    async def emit(self,ctx,type,data):
        async with self.transaction() as u: await u.event(ctx,type,data)
        if self.notifier: await self.notifier(ctx)
    async def close(self): await self.engine.dispose()
