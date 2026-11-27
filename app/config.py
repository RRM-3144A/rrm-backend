from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://rrm:rrm@localhost:5432/rrm"
    cors_origins: str = "http://localhost:3000"
    google_client_id: str = ""
    allowed_email_domain: str = "student.usv.ro"
    jwt_secret: str = "dev-only-secret-change-me-in-production"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 480
    admin_emails: str = ""
    # Demo sign-in (POST /auth/demo) for presentations without a Google OAuth client.
    # Never enable it in production.
    demo_login: bool = False
    timezone: str = "Europe/Bucharest"
    frontend_url: str = "http://localhost:3000"
    # E-mail: with no SMTP host the messages are only written to the log (development).
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_use_tls: bool = True
    mail_from: str = "Research Resource Manager <rrm-noreply@usv.ro>"

    @property
    def admin_email_set(self) -> set[str]:
        return {email.strip().lower() for email in self.admin_emails.split(",") if email.strip()}

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


settings = Settings()
