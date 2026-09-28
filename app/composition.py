import logging
from app.infrastructure.settings import Settings
from app.infrastructure.database import Database
from app.infrastructure.cache import Cache
from app.infrastructure.search import Search
from app.infrastructure.catalog import seed
from app.infrastructure.jobs import Jobs
from app.application.usecases.commerce import Commerce
from app.application.agents.main_agent import MainAgent

log=logging.getLogger(__name__)

class Container:
    def __init__(self,settings=None):
        self.settings=settings or Settings()
        self.db=Database(self.settings.database_url);self.cache=Cache(self.settings.redis_url)
        self.db.notifier=self.cache.notify
        self.search=Search(self.db,self.cache,self.settings);self.commerce=Commerce(self.db,self.search)
        if self.settings.app_mode=='llm':
            if not self.settings.llm_api_key: raise ValueError('APP_MODE=llm 时必须配置 LLM_API_KEY')
            from app.infrastructure.agentscope_runtime import AgentScopeRuntime
            runtime=AgentScopeRuntime(self.commerce,self.db,self.settings)
        elif self.settings.app_mode=='demo':
            from app.infrastructure.demo_runtime import DemoRuntime
            runtime=DemoRuntime(self.commerce,self.db)
        else: raise ValueError('APP_MODE 必须为 demo 或 llm')
        self.agent=MainAgent(runtime);self.jobs=Jobs(self.db,self.cache,self.agent,self.settings)
    async def start(self):
        await self.db.init();await seed(self.db)
        if self.settings.qdrant_url and self.settings.embedding_api_key:
            try:
                await self.search.index()
            except Exception as exc:
                log.warning('catalog vector index unavailable: %s',type(exc).__name__)
    async def close(self):
        await self.search.close();await self.cache.close();await self.db.close()
