rca-service/
├── app/
│   ├── interface/          # Interface层（接收用户请求）
│   │   └── api.py          # FastAPI接口，处理HTTP请求（无CLI，聚焦服务化）
│   ├── agent/              # Agent层（核心决策逻辑）
│   │   └── rca_agent.py    # RCA（根因分析）核心Agent，整合工具/记忆/提示词
│   ├── tools/              # Tool层（外部工具调用封装）
│   │   ├── prometheus_tool.py # 调用Prometheus API查询监控指标
│   │   ├── loki_tool.py    # 调用Loki API查询日志
│   │   └── jaeger_tool.py  # 调用Jaeger API查询链路追踪数据
│   ├── memory/             # Memory层（短时记忆管理）
│   │   └── short_term_memory.py # 封装Agent短时记忆（对话/查询上下文）
│   ├── prompt/             # Prompt层（提示词模板）
│   │   └── rca_prompts.py  # RCA根因分析专用提示词模板
│   └── data/               # Data层（暂空，预留知识库/数据库操作）
├── config/                 # 配置文件目录
│   ├── config.yaml/config.py# 主配置文件（API密钥、Prometheus/Loki/Jaeger地址等）
│   └── .env.example        # 环境变量示例（敏感配置，如API_KEY，实际使用.env并加入.gitignore）
├── requirements.txt        # 项目依赖清单
├── main.py                 # 项目启动入口（启动FastAPI服务、初始化Agent等）