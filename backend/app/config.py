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
    #
    # Per IP, which carrier CGNAT makes coarser than it looks: a large number of
    # phone users can share one public address. Left at 10/s anyway, because a
    # save costs a chunk render (~291 ms, serialised by render_semaphore) so
    # sustained global capacity is only ~3.4 saves/sec — one IP at this limit
    # already exceeds it, and raising the number would buy flooding room rather
    # than headroom for real users, who save on the order of once per 30 s each.
    # If CGNAT does start biting, the fix is a per-session limit (the client
    # already sends X-Session-Id) with this left as the abuse backstop.
    rate_limit_tile_save: int = 10  # max saves per window per IP
    rate_limit_window_seconds: int = 1  # sliding window duration

    # WebSocket limits
    ws_max_connections: int = 1000  # global cap
    # Per-IP cap, set to 10% of the global cap. This was 10, which is generous
    # on desktop and wrong on mobile: carrier CGNAT puts large numbers of phone
    # users behind a single public IP, so the eleventh phone user on a carrier
    # silently never went live while their page loaded perfectly. Sized against
    # the global cap rather than memory — the global cap is what bounds memory —
    # so one abusive source can still take at most a tenth of capacity.
    ws_max_connections_per_ip: int = 100
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
