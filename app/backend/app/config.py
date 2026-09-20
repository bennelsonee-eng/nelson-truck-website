from pydantic_settings import BaseSettings, SettingsConfigDict
from functools import lru_cache


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- App ---
    app_name: str = "Nelson Truck Equipment"
    debug: bool = True
    environment: str = "development"

    # --- Database ---
    # Co-hosted with the Titan site on the same Postgres container (port 5433),
    # separate database (nelson_web).
    database_url: str = "postgresql+asyncpg://postgres:titan2026@localhost:5433/nelson_web"

    # --- Issue Recorder transcription (faster-whisper, CPU) ---
    # The browser's live transcript is unreliable, so we transcribe the recorded
    # .webm server-side. base.en is a good speed/accuracy balance on the box's
    # CPU; bump to small.en for accuracy if needed.
    transcription_enabled: bool = True
    transcription_model: str = "base.en"        # tiny.en | base.en | small.en | medium.en
    transcription_compute_type: str = "int8"    # int8 (fast, CPU) | int8_float32 | float32
    transcription_cache_dir: str = ""           # HF model cache dir; "" = library default

    # --- Auth / JWT ---
    jwt_secret_key: str = "change-me-in-production-use-openssl-rand-hex-32"
    jwt_algorithm: str = "HS256"
    jwt_expire_hours: int = 24
    require_auth: bool = True

    # --- Search (Typesense) ---
    typesense_host: str = "localhost"
    typesense_port: int = 8108
    typesense_protocol: str = "http"
    typesense_api_key: str = "nelson_search_dev_key"
    # Collection name — lets the Nelson site share a Typesense instance with the
    # Titan site (which uses "products") without clobbering its index.
    typesense_collection: str = "nelson_products"

    # --- Source data sync (Titan MySQL) ---
    titan_mysql_host: str = ""
    titan_mysql_port: int = 3306
    titan_mysql_user: str = ""
    titan_mysql_pass: str = ""
    titan_mysql_db: str = ""
    titan_inventory_sync_minutes: int = 15
    titan_pricing_sync_hour: int = 1  # 1am PST nightly bulk

    # Read-only PHP bridge for the Titan MySQL (lives on TigerTech web root).
    # Used by customer_sync.py — the bridge supports SHOW/SELECT/DESCRIBE only
    # and is hardened with a shared-secret token (see app/scripts/dump_titan_tables.php).
    titan_bridge_url: str = "https://nelsontruck.com.customers.tigertech.net/dump_titan_tables.php"
    titan_bridge_token: str = "ttn-x8e2-9qa1-y3h7-r5b6-mc4f-2026-rebuild"

    # --- FACS / IMS315 order push ---
    facs_ftp_host: str = ""
    facs_ftp_port: int = 21
    facs_ftp_user: str = ""
    facs_ftp_pass: str = ""
    facs_dropbox_path: str = "/nelson_orders"
    facs_pickup_lag_alert_minutes: int = 30

    # --- Authorize.net ---
    authnet_api_login_id: str = ""
    authnet_transaction_key: str = ""
    authnet_public_client_key: str = ""
    authnet_environment: str = "sandbox"  # sandbox or production

    # --- Email ---
    email_provider: str = "postmark"  # postmark / sendgrid / mailchimp / smtp / maildev / console
    email_api_key: str = ""
    email_from: str = "sales@nelsontruck.com"
    # SMTP-auth backend (used when email_provider=smtp).  Currently TigerTech
    # for winterwatch@titantruck.com:
    #   smtp_host=mail.tigertech.net  smtp_port=587  smtp_user=winterwatch@titantruck.com
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""

    # --- Cloudflare ---
    cloudflare_api_token: str = ""
    cloudflare_zone_id: str = ""

    # --- Cloudflare Access (Zero Trust login gate for the preview site) ---
    # The preview site (titantruckequipment.com) sits behind Cloudflare Access.
    # Cloudflare injects a signed `Cf-Access-Jwt-Assertion` header on every request
    # that reaches the origin through the tunnel; we validate it to learn the
    # authenticated tester's email.
    #   - cf_access_team_domain: the <team>.cloudflareaccess.com host (issuer).
    #   - cf_access_aud: the Application Audience (AUD) tag from the Access app.
    # When cf_access_aud is blank, ALL Cloudflare-Access logic no-ops, so local
    # dev and the Tailscale-only path are completely unaffected.
    cf_access_team_domain: str = "nelson-preview-team.cloudflareaccess.com"
    cf_access_aud: str = ""
    # Comma-separated emails that get a passwordless ADMIN session when they
    # arrive with a verified Cloudflare Access identity (email OTP). The first
    # time such an email hits POST /api/auth/cf-login we just-in-time provision
    # an ADMIN app user for them and issue the normal app JWT — so Cloudflare's
    # OTP is the only credential they ever type. Double-gated: the email must
    # ALSO be allowed by the Cloudflare Access policy to reach the origin.
    cf_admin_emails: str = ""

    # --- PACE / AAM Group catalog ---
    pace_api_base: str = ""
    pace_member_code: str = ""
    pace_api_key: str = ""

    # --- Anthropic (Phase 2) ---
    anthropic_api_key: str = ""

    # --- Public URL ---
    public_url: str = "http://localhost:5173"

    # --- Canonical host for SEO (single source of truth) ---
    # Every absolute URL emitted for search engines — canonical tags, sitemap
    # URLs, OG `url`, and the robots.txt `Sitemap:` directive — is built from
    # this ONE value.  Set it to the domain that will actually be indexed.
    #
    # IMPORTANT (domain strategy): we BUILD on the pre-launch preview host
    # `nelsontruckequipment.com` (behind Cloudflare Access, so crawlers can't
    # reach it), but at launch this site takes over the real domain
    # `nelsontruck.com` — which is the host Google indexes.  So canonical output
    # must point at nelsontruck.com even now.  No trailing slash.
    #   - www vs apex: defaulting to apex; add a www->apex 301 at launch.
    #   - Override per-env in .env if needed (e.g. a full staging test).
    #   - NOTE: nelsontruck.com currently hosts the legacy TigerTech site that
    #     also serves the shared MySQL bridge (see titan_bridge_url). The launch
    #     cutover must keep that bridge host reachable for BOTH sites.
    canonical_base_url: str = "https://nelsontruck.com"

    # --- Issue recorder -------------------------------------------------
    # Where "a new issue was filed" alerts go. Nelson and Titan run entirely
    # separate reporting stacks (separate databases, separate inboxes), so this
    # deliberately does NOT share Titan's address. Override in .env per env.
    error_report_alert_email: str = "admin@nelsontruck.com"

    # --- Anonymous-retail customer sentinel for FACS (per addendum 003) ---
    facs_anonymous_retail_customer_id: str = "106415"


@lru_cache
def get_settings() -> Settings:
    return Settings()
