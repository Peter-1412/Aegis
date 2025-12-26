from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    service_name: str = "chatops-service"

    loki_base_url: str = "http://loki-loki-distributed-query-frontend.observability:3100"
    loki_tenant_id: str | None = None
    loki_service_label_key: str = "app"
    loki_selector_template: str = '{{{label_key}="{service}"}}'

    request_timeout_s: float = 60.0
    max_log_lines: int = 500

    llm_model: str = "doubao-seed-1-6-251015"
    ark_api_key: str | None = None
    ark_base_url: str = "https://ark.cn-beijing.volces.com/api/v3"


settings = Settings()
