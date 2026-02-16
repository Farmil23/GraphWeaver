from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    PROJECT_NAME: str = "GraphWeaver"
    NEO4J_URI: str = "bolt://localhost:7687"
    NEO4J_USER: str = "neo4j"
    NEO4J_PASSWORD: str 
    GROQ_API_KEY: str 
    
    LOG_LEVEL: str = "INFO"

    class Config:
        env_file = ".env"

settings = Settings()