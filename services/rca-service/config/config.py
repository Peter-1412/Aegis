from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    service_name: str = "ops-service"

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
    ollama_qwen_model: str = "qwen2.5:32b"
    ollama_glm_model: str = "glm-4.7-flash:latest"
    ollama_deepseek_model: str = "deepseek-r1:32b"
    ollama_disable_thinking: bool = True
    ollama_num_predict: int = 8192
    ollama_temperature: float = 0.01
    ollama_top_p: float = 0.1

    doubao_base_url: str = "https://ark.cn-beijing.volces.com/api/v3"
    doubao_api_key: str | None = None
    doubao_model: str = "ep-20260207075658-4d5bg"
    doubao_temperature: float = 0.7
    doubao_max_tokens: int = 4096
    doubao_thinking_enabled: bool = True
    doubao_thinking_effort: str = "high"

    default_model: str = "doubao"

    agent_max_iterations: int = 50
    agent_max_execution_time_s: float = 600.0

    feishu_app_id: str | None = None
    feishu_app_secret: str | None = None
    feishu_verification_token: str | None = None
    feishu_default_chat_id: str | None = None


settings = Settings()
