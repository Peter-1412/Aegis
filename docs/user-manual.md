# 运维使用手册：Aegis Ops Agent（飞书版）/ User Manual: Aegis Ops Agent (Feishu Version)

## 1. 面向读者 / Target Audience

本手册面向一线 SRE / 运维工程师，假设你：

- 已经有一个已经运行的 Kubernetes 集群；
- 已经部署了 Prometheus、Loki、Jaeger、Grafana、Promtail 等观测组件；
- 已经配置好飞书机器人，并将其拉入运维告警群。

你不需要深入理解 LangChain 或 LLM，只需要知道如何在飞书里"和机器人说话"即可。

## 2. 飞书侧体验 / Feishu Side Experience

### 2.1 告警通知 / 2.1 Alert Notification

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

这条消息仅是"告警汇总"，不包含运维分析结果。

### 2.2 触发运维分析 / 2.2 Triggering Ops Analysis

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

### 2.3 结果消息示例 / 2.3 Result Message Example

```text
【自动运维分析结果】
时间范围（CST）：2025-01-15T20:10:00+08:00 ~ 2025-01-15T20:25:00+08:00
故障描述：@AegisBot 帮我分析一下刚才 todo-service 的 5xx 和 CrashLoop 的根因

总结：本次故障主要由 todo-service 访问数据库超时导致，大量请求返回 5xx，并伴随 Pod 重启。

可能的根因候选：
1. todo-service 访问数据库出现大量连接超时和死锁，导致接口 5xx 和请求排队（服务：todo-service），概率≈0.78
2. worker-02 节点在同一时间段发生短暂 NotReady，可能影响到部分 Pod 调度（服务：kubelet），概率≈0.32

建议后续操作：
1. 在 Grafana 中进一步放大 todo-service 相关面板，确认是否存在资源瓶颈或连接池耗尽。
2. 检查 worker-02 节点的 kubelet 与系统日志，确认是否存在重启或资源异常。
```

一般情况下，你只需要从上往下看：

1. 先看"总结"是否和用户反馈一致；
2. 再看根因候选 1 是否有足够指标/日志证据；
3. 最后按"建议后续操作"一步步排查。

## 3. 常见提问模板 / 3. Common Question Templates

你可以参考以下模板与 Agent 对话：

- "@AegisBot 帮我看下刚才 502 的根因"
- "@AegisBot 帮我分析一下 todo-service 在 21:00–21:10 的超时问题"
- "@AegisBot 用户说下单接口经常报错，你看看最近半小时的可能原因"

尽量在描述中包含：

- 涉及的服务名（如 `todo-service`、`user-service` 等）；
- 大致时间范围（"刚才""昨晚 23 点""最近半小时"等）；
- 用户实际感知（502、超时、页面白屏等）。

## 4. 注意事项 / 4. Important Notes

1. Agent 始终是只读的：
   - 它不会重启服务、扩容、删数据，也不会调用任何危险接口；
   - 它只能给出"诊断"与"建议"，实际操作需要你自己执行。
2. 观测数据可能不完整：
   - 如果 Prometheus / Loki / Jaeger 没有采集到对应服务或指标，Agent 会在结果中说明"查询不到数据"；
   - 此时建议先检查监控采集配置。
3. LLM 有一定不确定性：
   - 尽管 Prompt 中进行了约束，但模型仍可能给出不完全准确的结论；
   - 请将 Agent 的结果视为"高质量建议"，而不是"绝对真相"，必要时结合自身经验判断。

## 5. 排错建议 / 5. Troubleshooting Guide

如果发现 Agent 返回结果异常或没有反应，可以按以下步骤排查：

1. 检查飞书长连接网关进程是否正常：
   - 运行 `app/interface/feishu_ws_client.py` 的长连接进程是否在运行；
   - `app_id`、`app_secret`、订阅的 `im.message.receive_v1` 是否配置正确。
2. 在 Kubernetes 中检查 ops-service 状态：

   ```bash
   kubectl -n aegis get pods
   kubectl -n aegis logs deploy/ops-service
   ```

3. 验证观测组件是否可访问：
   - 从 ops-service Pod 内执行 `curl` 到 Prometheus / Loki / Jaeger；
4. 如果是 LLM 相关错误，检查：
   - `DOUBAO_API_KEY` 是否配置正确；
   - 外网访问是否受限制。

## 6. 与其他工具的配合 / 6. Working with Other Tools

Aegis Ops Agent 不是用来替代 Grafana / Kibana / Jaeger UI，而是帮助你：

- 在飞书里快速得到一个"带证据的假设"；
- 然后再使用图形化工具进行深度分析与验证。

推荐工作流：

1. 先在飞书里触发一次运维分析，获取候选根因和关键证据；
2. 然后根据结果中的指标名和日志片段，在 Grafana 与 Loki 中做进一步 drill-down；
3. 对于重要故障，将最终结论同步到内部故障管理系统中。

---

# User Manual: Aegis Ops Agent (Feishu Version)

## 1. Target Audience

This manual is oriented towards frontline SRE / operations engineers, assuming you:

- Already have a running Kubernetes cluster;
- Already deployed observability components such as Prometheus, Loki, Jaeger;
- Already configured Feishu bot and added it to operations alert group.

You do not need to deeply understand LangChain or LLM, just need to know how to "talk to bot" in Feishu.

## 2. Feishu Side Experience

### 2.1 Alert Notification

When a cluster alert occurs, you will see a message similar to the following in the Feishu alert group:

```text
@all
【Kubernetes Cluster Alert Notification】
Alertmanager status: firing
Alert count: 2

1. [critical] KubernetesPodCrashLooping @ todo-service-7c9f7d44bb-p2x7b
   Summary: todo-service pod is restarting too frequently
2. [warning] KubernetesNodeNotReady @ worker-02
   Summary: Node worker-02 is not ready
```

This message is only an "alert summary", it does not contain Ops analysis results.

### 2.2 Triggering Ops Analysis

When you want to Agent to help you analyze, just @mention bot in the same group and describe to issue in natural language, for example:

```text
@AegisBot help me analyze of root cause of the 5xx and CrashLoop for todo-service just now
```

Or be more specific:

```text
@AegisBot help me check of root cause of 502 for todo-service around 20:15, users reported slow page load
```

The Agent will automatically:

- Use as last 15 minutes as the time window (you can also specify exact time range in the description);
- Query Prometheus metrics, Loki logs, and Jaeger traces;
- Reply with a structured result message in the same group.

### 2.3 Result Message Example

```text
【Ops Analysis Result】
Time Range (CST): 2025-01-15T20:10:00+08:00 ~ 2025-01-15T20:25:00+08:00
Issue Description: @AegisBot help me analyze of root cause of the 5xx and CrashLoop for todo-service just now

Summary: This incident was primarily caused by todo-service experiencing connection timeouts and deadlocks when accessing MySQL, resulting in massive 5xx errors and request queuing.

Possible Root Cause Candidates:
1. todo-service experienced massive connection timeouts and deadlocks when accessing MySQL, leading to 5xx errors and request queuing (Service: todo-service), Probability≈0.78
2. worker-02 node experienced brief NotReady during the same period, potentially affecting some Pod scheduling (Service: kubelet), Probability≈0.32

Suggested Follow-up Actions:
1. Further investigate todo-service database connection metrics and slow queries in Grafana to confirm connection pool exhaustion or lock waits.
2. Check worker-02 node's kubelet and system logs to confirm if there are restarts or resource anomalies.
```

Generally, you just need to read from top to bottom:

1. First check if = "Summary" matches your user feedback;
2. Then check if Root Cause Candidate 1 has sufficient metrics/log evidence;
3. Finally follow = "Suggested Follow-up Actions" step by step for troubleshooting.

## 3. Common Question Templates

You can refer to the following templates to converse with Agent:

- "@AegisBot help me check of root cause of the 502 just now"
- "@AegisBot help me analyze of timeout issue for todo-service between 21:00–21:10"
- "@AegisBot users reported frequent errors on = order placement interface, please check of possible causes in the last half hour"

Try to include in your description:

- The service name involved (such as `todo-service`, `user-service`, etc.);
- Approximate time range ("just now", "last night at 23:00", "last half hour", etc.);
- User's actual perception (502, timeout, blank page, etc.).

## 4. Important Notes

For operations engineers, assuming you:

- Already have a running Kubernetes cluster;
- Already deployed observability components such as Prometheus, Loki, Jaeger;
- Already configured Feishu bot and added it to operations alert group.

You do not need to deeply understand LangChain or LLM, just need to know how to "talk to bot" in Feishu.

1. Agent is always read-only:
   - It will not restart services, scale up, delete data, or call any dangerous interfaces;
   - It can only provide "diagnosis" and "suggestions", actual operations need to be executed by yourself.
2. Observability data may be incomplete:
   - If Prometheus / Loki / Jaeger have not collected corresponding service or metrics, Agent will state in the result "no data queried";
   - In this case, suggest checking = monitoring collection configuration first.
3. LLM has certain uncertainty:
   - Although constraints are set in the Prompt, model may still give不完全 accurate conclusions;
   - Please treat = Agent's result as a "high-quality suggestion", not "absolute truth", and combine with your own experience for judgment when necessary.

## 5. Troubleshooting Guide

If you find = Agent's return result abnormal or no response, you can troubleshoot according to the following steps:

1. Check if the Feishu long connection gateway process is running normally:
   - Check if the long connection process running `app/interface/feishu_ws_client.py` is running;
   - Check if `app_id`, `app_secret`, and the subscribed `im.message.receive_v1` are configured correctly.
2. Check ops-service status in Kubernetes:

   ```bash
   kubectl -n aegis get pods
   kubectl -n aegis logs deploy/ops-service
   ```

3. Verify if observability components are accessible:
   - Execute `curl` from within the ops-service Pod to Prometheus / Loki / Jaeger;
4. If it is an LLM-related error, check:
   - Check if `DOUBAO_API_KEY` is configured correctly;
   - Check if external network access is restricted.

## 6. Working with Other Tools

Aegis Ops Agent is not intended to replace Grafana / Kibana / Jaeger UI, but to help you:

- Quickly get a "hypothesis with evidence" in Feishu;
- Then use graphical tools for further deep analysis and verification based on the results.

Recommended workflow:

1. First trigger an Ops analysis in Feishu to get candidate root causes and key evidence;
2. Then use the metric names and log fragments in the results to do further drill-down in Grafana and Loki;
3. For important incidents, synchronize the final conclusion to the internal incident management system.
