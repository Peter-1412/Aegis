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

    ollama_base_url: str = "http://192.169.223.108:11434"
    ollama_model: str = "qwen2.5:32b"
    ollama_disable_thinking: bool = True
    ollama_num_predict: int = 8192
    ollama_temperature: float = 0.01
    ollama_top_p: float = 0.95

    agent_max_iterations: int = 50
    agent_max_execution_time_s: float = 600.0

    feishu_app_id: str | None = None
    feishu_app_secret: str | None = None
    feishu_verification_token: str | None = None
    feishu_default_chat_id: str | None = None


settings = Settings()
