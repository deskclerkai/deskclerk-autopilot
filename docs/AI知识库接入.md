# AI 知识库接入

> 适用系统：DeskClerk AI Autopilot
> 最后更新：2026-11-12

## 一、配置

| 配置 | 说明 |
|---|---|
| Base URL | 知识库服务的集成接口地址，例如 `https://your-host/api/v1/integrations` |
| API Key | 只存服务端；页面保存后只显示打码值 |
| Site ID | 一套知识库对应一个站点 |
| locale | 知识、提问与人设按语言隔离，推送和提问要用同一个 locale |

Key 可以写在应用里，也可以用服务端环境变量 `AICHAT_KEY` 提供。环境变量优先，页面不会再显示明文。

需要的权限范围通常是：问答 `chat:write`；推送知识 `knowledge:write`；同步状态 `sync_status:read`；问答历史 `conversations:read`；修改人设 `ai_assistant_config:write`。

## 二、一次问答的流程

1. 创建会话：`POST /sites/{siteId}/conversations`，带上 `channel=whatsapp`、`external_user_id`、`locale`、`timezone`。
2. 发送问题：`POST /sites/{siteId}/conversations/{id}/messages`，body 为 `{"content": "客户原话"}`。
3. 读取返回：
   - `aiMessage` 为空：没有自动回答，转人工；
   - `sources` 为空：没有知识依据，转人工或发固定兜底话术；
   - `sources[].score` 的最高分达到阈值：可以自动回复；
   - 返回里有 `escalation`：按转人工处理。

`score` 是相似度，不是准确率。阈值默认 0.70，可在 AI 助手页调整。

## 三、三种接待方式

| 模式 | 客户来信时发生什么 |
|---|---|
| 人工接待 | AI 不参与，会话进入人工队列 |
| AI 草稿 | AI 生成回答并存为草稿；人工点「采用并发送」才发出 |
| AI 全自动托管 | 命中知识且分数达标时直接回复；价格、合同、无依据、转人工信号都不自动发 |

每个会话还可以单独关掉 AI。草稿永远不自动发送。

## 四、安全边界

入口先做硬拦截，命中以下主题时不调用知识库：

- 价格、折扣、报价
- 交期承诺
- 合同、法律、索赔
- 投诉、退款、律师

拦截后统一转人工。知识库的“人设约束”是软约束，不能代替入口拦截。

另外两条硬规则：

- 24 小时客服窗口外只允许发已审核模板；
- 已退订客户不进入任何发送名单，也不参与自动回复。

## 五、超时与失败

- 单次问答可能长达 45 秒；Webhook 不能等，所以 AI 处理放在后台线程，先给 Meta 返回 200。
- 超过内部等待时间就转人工，不要换 Key 重发同一句。
- 网络错误、429、5xx 可以按退避重试，最多 3 次。
- 任何失败都要写 `ai_logs`，并保留转人工信号。

## 六、数据与日志

系统自己保存问答日志，因为外部知识库的导出通常经过打码，也不含引用来源：

| 字段 | 用途 |
|---|---|
| question / answer | 复盘回答质量 |
| sources | 判断有没有知识依据 |
| top_score | 判断置信度 |
| decision | auto / draft / handoff / blocked |
| escalation | 转人工原因 |
| latency_ms | 发现慢查询 |

知识库侧一般不做自动删除。不要把身份证号、完整手机号、家庭地址写进知识或提问；入口先脱敏。

## 七、换一家知识库

工作流不绑定某一家服务。只要对方提供同等能力的“建会话 → 提问 → 返回回答与来源”接口，改 Base URL、Site ID 和 Key 即可，业务代码不变。

如果对方协议不同，在 `app/main.py` 的 `ai_remote_ask()` 里做一层适配，保持返回结构一致：

```json
{
  "answer": "...",
  "sources": [{"title": "...", "score": 0.82}],
  "top_score": 0.82,
  "decision": "auto",
  "escalation": null,
  "latency_ms": 1200
}
```
