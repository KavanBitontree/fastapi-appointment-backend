from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    NEON_DB_URL: str
    FRONTEND_URL: str
    ENV: str = "development"
    CLOUD_NAME: str
    CLOUDINARY_API_KEY: str
    CLOUDINARY_API_SECRET: str

    class Config:
        env_file = ".env"

settings = Settings()
