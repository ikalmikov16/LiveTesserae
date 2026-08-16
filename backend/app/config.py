from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # Database
    database_url: str = "postgresql://tesserae:tesserae_local@localhost:5433/tesserae"
    db_pool_min: int = 5
    db_pool_max: int = 20
    db_command_timeout: float = 10.0  # seconds before a query is killed

    # Server
    host: str = "0.0.0.0"
    port: int = 8000
    debug: bool = True
    log_level: str = "INFO"  # DEBUG, INFO, WARNING, ERROR
    log_format: str = "text"  # "text" for dev, "json" for production

    # CORS: comma-separated allowed origins
    cors_origins: str = "http://localhost:5173"

    # Number of reverse proxies we control in front of this app, counted from
    # the app inward (ALB only = 1; CloudFront -> ALB = 2). Only the last N
    # X-Forwarded-For entries are written by our own infrastructure; anything
    # further left is client-supplied and must not be trusted. 0 = no proxy
    # (local dev), meaning the header is ignored entirely.
    trusted_proxy_hops: int = 0

    # Mosaic configuration
    grid_width: int = 1000
    grid_height: int = 1000
    tile_size: int = 32
    chunk_size: int = 100  # 100x100 tiles per chunk

    # How long the Level-0 overview rebuild waits to collect dirty chunks.
    # Every tile save used to re-encode the overview, capping the site at ~0.5
    # saves/sec; one rebuild per window makes that cost independent of the edit
    # rate, at the price of up to this much staleness at zoom level 0.
    overview_coalesce_seconds: float = 5.0

    # Storage mode: "local" or "s3"
    storage_mode: str = "local"

    # Local storage paths (used when storage_mode="local")
    storage_path: str = "storage"
    tiles_path: str = "storage/tiles"
    chunks_path: str = "storage/chunks"

    # Rate limiting
    rate_limit_tile_save: int = 10  # max saves per window per IP
    rate_limit_window_seconds: int = 1  # sliding window duration

    # WebSocket limits
    ws_max_connections: int = 1000  # global cap
    ws_max_connections_per_ip: int = 10  # per-IP cap
    ws_max_subscriptions: int = 50  # max chunks per connection
    ws_max_message_size: int = 4096  # max bytes for incoming WS messages

    # S3 configuration (used when storage_mode="s3")
    aws_s3_bucket: str = ""
    aws_region: str = "us-east-2"
    aws_access_key_id: str = ""  # Optional, uses default credential chain if empty
    aws_secret_access_key: str = ""  # Optional

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()
