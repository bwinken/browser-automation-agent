from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    mongodb_url: str = "mongodb://localhost:27017"
    db_name: str = "baas"
    openai_api_key: str = ""
    secret_key: str = "changeme-in-production"
    openai_model: str = "gpt-4o"
    max_concurrent_browsers: int = 2
    max_agent_iterations: int = 20
    demo_api_key: str = ""
    twocaptcha_api_key: str = ""
    admin_username: str = ""
    admin_password: str = ""
    initial_invite_codes: int = 3
    download_dir: str = "downloads"
    headless: bool = True
    dev_mode: bool = False
    log_level: str = "INFO"

    class Config:
        env_file = ".env"


settings = Settings()
