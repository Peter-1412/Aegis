from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    service_name: str = "rca-service"

    loki_base_url: str = "http://loki.monitoring.svc.cluster.local:3100"
    loki_tenant_id: str | None = None
    loki_service_label_key: str = "app"
    loki_selector_template: str = '{{{label_key}="{service}"}}'
    prometheus_base_url: str = "http://prometheus.monitoring.svc.cluster.local:9090"
    jaeger_base_url: str | None = "http://jaeger.monitoring.svc.cluster.local:16686"

    request_timeout_s: float = 60.0
    per_service_log_limit: int = 200
    max_total_evidence_lines: int = 200

    llm_model: str = "ep-20260207075658-4d5bg"
    ark_api_key: str | None = None
    ark_base_url: str = "https://ark.cn-beijing.volces.com/api/v3"

    feishu_app_id: str | None = None
    feishu_app_secret: str | None = None
    feishu_verification_token: str | None = None
    feishu_default_chat_id: str | None = None


settings = Settings()
