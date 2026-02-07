# 运维使用手册：Aegis RCA Agent（飞书版）

## 1. 面向读者

本手册面向一线 SRE / 运维工程师，假设你：

- 已经有一个运行中的 Kubernetes 集群；
- 已经部署了 Prometheus、Loki、Jaeger 等观测组件；
- 已经配置好飞书机器人，并将其拉入运维告警群。

你不需要深入理解 LangChain 或 LLM，只需要知道如何在飞书里“和机器人说话”即可。

## 2. 飞书侧体验

### 2.1 告警通知

当集群发生告警时，你会在飞书告警群看到类似消息：

```text
@所有人
【Kubernetes 集群告警通知】
Alertmanager status: firing
告警数量: 2

1. [critical] KubernetesPodCrashLooping @ todo-service-7c9f7d44bb-p2x7b
   概要: todo-service pod is restarting too frequently
2. [warning] KubernetesNodeNotReady @ worker-02
   概要: Node worker-02 is not ready
```

这条消息仅是“告警汇总”，不包含 RCA 结果。

### 2.2 触发 RCA 分析

当你想让 Agent 帮你分析时，只需在同一个群里 @ 机器人，并用自然语言描述问题，例如：

```text
@AegisBot 帮我分析一下刚才 todo-service 的 5xx 和 CrashLoop 的根因
```

或更具体一点：

```text
@AegisBot 帮我看下 20:15 左右 todo-service 502 的根因，用户反馈页面很慢
```

Agent 会自动：

- 使用最近 15 分钟作为时间窗口（也可以在描述里写明具体时间段）；
- 查询 Prometheus 指标、Loki 日志和 Jaeger 调用链；
- 在同一个群里回复一条结构化的结果消息。

### 2.3 结果消息示例

```text
【自动RCA分析结果】
时间范围（CST）：2025-01-15T20:10:00+08:00 ~ 2025-01-15T20:25:00+08:00
故障描述：@AegisBot 帮我分析一下刚才 todo-service 的 5xx 和 CrashLoop 的根因

总结：本次故障主要由 todo-service 访问数据库超时导致，大量请求返回 5xx，并伴随 Pod 重启。

可能的根因候选：
1. todo-service 访问 MySQL 出现连接超时和死锁，导致接口错误率陡增（服务：todo-service），概率≈0.78
2. worker-02 节点在同一时间段发生短暂 NotReady，可能影响到部分 Pod 调度（服务：kubelet），概率≈0.32

建议后续操作：
1. 在 Grafana 中查看 todo-service 的数据库连接指标和慢查询情况，确认是否存在连接池耗尽或锁等待。
2. 检查 worker-02 节点的 kubelet 与系统日志，确认是否存在重启或资源异常。
```

一般情况下，你只需要从上往下看：

1. 先看“总结”是否和用户反馈一致；
2. 再看根因候选 1 是否有足够指标/日志证据；
3. 最后按“建议后续操作”一步步排查。

## 3. 常见提问模板

你可以参考以下模板与 Agent 对话：

- “@AegisBot 帮我看下刚才 502 的根因”
- “@AegisBot 帮我分析一下 todo-service 在 21:00–21:10 的超时问题”
- “@AegisBot 用户说下单接口经常报错，你看看最近半小时的可能原因”

尽量在描述中包含：

- 涉及的服务名（如 `todo-service`、`user-service` 等）；
- 大致时间范围（“刚才”“昨晚 23 点”“最近半小时”等）；
- 用户实际感知（502、超时、页面白屏等）。

## 4. 注意事项

1. Agent 始终是只读的：
   - 它不会重启服务、扩容、删数据，也不会调用任何危险接口；
   - 它只能给出“诊断”与“建议”，实际操作需要你自己执行。
2. 观测数据可能不完整：
   - 如果 Prometheus / Loki / Jaeger 没有采集到对应服务或指标，Agent 会在结果中说明“查询不到数据”；
   - 此时建议先检查监控采集配置。
3. LLM 有一定不确定性：
   - 尽管 Prompt 中进行了约束，但模型仍可能给出不完全准确的结论；
   - 请将 Agent 的结果视为“高质量建议”，而不是“绝对真相”，必要时结合自身经验判断。

## 5. 排错建议

如果发现 Agent 返回结果异常或没有反应，可以按以下步骤排查：

1. 检查飞书长连接网关进程是否正常：
   - 运行 `app/interface/feishu_ws_client.py` 的长连接进程是否在运行；
   - `app_id`、`app_secret`、订阅的 `im.message.receive_v1` 是否配置正确。
2. 在 Kubernetes 中检查 rca-service 状态：

   ```bash
   kubectl -n aegis get pods
   kubectl -n aegis logs deploy/rca-service
   ```

3. 验证观测组件是否可访问：
   - 从 rca-service Pod 内执行 `curl` 到 Prometheus / Loki / Jaeger；
4. 如果是 LLM 相关错误，检查：
   - `ARK_API_KEY` 是否配置正确；
   - 外网访问是否受限制。

## 6. 与其他工具的配合

Aegis RCA Agent 不是用来替代 Grafana / Kibana / Jaeger UI，而是帮助你：

- 在飞书里快速得到一个“带证据的假设”；
- 然后再使用图形化工具进行深度分析与验证。

推荐工作流：

1. 先在飞书里触发一次 RCA 分析，获取候选根因和关键证据；
2. 再根据结果中的指标名和日志片段，在 Grafana 与 Loki 中做进一步 drill-down；
3. 对于重要故障，将最终结论同步到内部故障管理系统中。
