from pydantic_settings import BaseSettings, SettingsConfigDict
class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file='.env', extra='ignore')
    database_url: str = 'sqlite+aiosqlite:///./data/globex.db'
    redis_url: str = ''
    qdrant_url: str = ''
    app_mode: str = 'demo'
    inline_worker: bool = True
    llm_base_url: str = 'https://api.deepseek.com/v1'
    llm_api_key: str = ''
    llm_model: str = 'deepseek-chat'
    embedding_base_url: str = 'https://dashscope.aliyuncs.com/compatible-mode/v1'
    embedding_api_key: str = ''
    embedding_model: str = 'text-embedding-v4'
    reranker_url: str = ''
    reranker_api_key: str = ''
    reranker_model: str = 'rerank'
    web_search_provider: str = 'tavily'
    web_search_url: str = 'https://api.tavily.com/search'
    web_search_api_key: str = ''
    web_search_domains: str = 'jd.com,taobao.com,tmall.com'
    allowed_origins: str = 'http://localhost:5173,http://localhost:8080,http://127.0.0.1:5173,http://127.0.0.1:8080'
    context_window: int = 16000
    job_timeout: int = 180
