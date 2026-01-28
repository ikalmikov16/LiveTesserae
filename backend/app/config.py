from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # Database
    database_url: str = "postgresql://tesserae:tesserae_local@localhost:5433/tesserae"

    # Server
    host: str = "0.0.0.0"
    port: int = 8000
    debug: bool = True
    log_level: str = "INFO"  # DEBUG, INFO, WARNING, ERROR

    # Mosaic configuration
    grid_width: int = 1000
    grid_height: int = 1000
    tile_size: int = 32
    chunk_size: int = 100  # 100x100 tiles per chunk

    # Storage (local for MVP, S3 later)
    storage_path: str = "storage"
    tiles_path: str = "storage/tiles"
    chunks_path: str = "storage/chunks"

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()
