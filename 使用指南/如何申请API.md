# 如何申请大模型 API

大模型 API 用于生成角色的对话回复，是 AIpartner 正常聊天的必需配置；后文的搜索 API 用于联网搜索，属于可选配置，不能代替大模型 API。

以下以 **DeepSeek 官方 API** 为例。本项目在开发过程中已测试 DeepSeek API 可用，**其他大模型 API 服务尚未测试**，即使声明兼容 OpenAI 格式，也需自行验证兼容性。

## 申请步骤（以 DeepSeek 为例）

1. 打开 [DeepSeek 开放平台](https://platform.deepseek.com/)，注册或登录账号，按页面提示完成所需验证。
2. 进入 [API Keys 页面](https://platform.deepseek.com/api_keys)，创建一个 API Key，并妥善保存。名称可填写 `AIpartner`。
3. 在平台检查可用余额，按需充值。API 按用量计费，具体以 [DeepSeek 模型与价格说明](https://api-docs.deepseek.com/zh-cn/quick_start/pricing/) 为准，不要将网页聊天的免费使用等同于 API 免费。
4. 在项目根目录的 `.env` 中填写或更新以下三项；保留文件中的其他配置：

```dotenv
LLM_API_KEY="这里填写 DeepSeek API Key"
LLM_MODEL_ID="deepseek-flash"
LLM_BASE_URL="https://api.deepseek.com"
```

`LLM_MODEL_ID` 请填写 [DeepSeek 官方接入文档](https://api-docs.deepseek.com/zh-cn/) 中当前可用的模型 ID，例如 `deepseek-flash`。模型名称可能更新，此处示例不表示所有 DeepSeek 模型均已通过本项目测试。`LLM_BASE_URL` 使用上面的 API 地址，不是网页版聊天地址。

保存后完整退出并重新启动 AIpartner，打开角色发送一条消息进行测试。如果调用失败，优先核对密钥、模型 ID、账户余额和终端错误信息。

**不要将真实 API Key 或 `.env` 上传到 GitHub，也不要在截图中暴露密钥。** 对话内容会发送给所配置的大模型服务商，请留意隐私。

以上 DeepSeek 申请与配置指引核对于 2026-09-16，实际开通流程及可用模型请以官方页面为准。

# 如何配置视觉模型 API（可选）

视觉模型 API 只用于识别聊天中附带的图片，不配置也不影响纯文字聊天。请在支持图片输入的模型服务商处注册账号、创建 API Key，并确认所选模型同时支持：

- 图片输入；
- 工具调用（Function Calling / Tool Calling）；
- OpenAI 风格的 Chat Completions 接口及本项目发送的 `thinking` 扩展参数。

然后在项目根目录的 `.env` 中填写：

```dotenv
LLM_VISION_API_KEY="这里填写视觉模型 API Key"
LLM_VISION_MODEL_ID="这里填写视觉模型 ID"
LLM_VISION_BASE_URL="这里填写视觉模型 API 地址"
```

三项必须同时填写。保存后完整停止并重新启动 AIpartner；若角色配置中的 `[vision]` 保持 `vision = true`，聊天输入框左侧应出现可用的图片入口。

当前 DeepSeek V4.1 Flash 支持图片理解和工具调用，因此使用 DeepSeek 时，可以复用正常对话的 API Key：

```dotenv
LLM_VISION_API_KEY="这里填写与 LLM_API_KEY 相同的 DeepSeek API Key"
LLM_VISION_MODEL_ID="deepseek-flash"
LLM_VISION_BASE_URL="https://api.deepseek.com"
```

视觉模型服务商会接收到上传的图片及本轮相关文字。请查看服务商的隐私与数据处理规则，不要上传身份证件、密钥截图或其他不希望交由第三方处理的敏感内容。

# 如何申请搜索 API

AIpartner 支持使用智谱或百度为角色提供联网搜索能力，**配置其中一家即可**。搜索只在角色的 `realtime` 场景模式下启用，`sandbox` 模式不使用联网搜索。

本部分核对日期：2026-08-31，控制台菜单、开通条件和免费额度可能调整，请以官方页面及个人账户显示为准。

## 一、百度：智能搜索生成

本项目使用的是百度“智能搜索生成（高性能版）”，接口路径为 `/v2/ai_search/web_summary`。截至上述日期，官方说明提供**每日 100 次免费额度**，超出部分支持按量后付费。不要将其与其他“百度搜索”接口的额度或计费方式混淆。详情见[高性能版接口说明](https://cloud.baidu.com/doc/qianfan-api/s/wmjqtqr7w)。

### 申请步骤

1. 打开[百度 AI 搜索控制台](https://console.bce.baidu.com/ai-search/home)，注册或登录百度智能云账号，按页面提示完成实名认证及服务开通。
2. 在控制台检查 AI 搜索的资源状态和免费额度，确认可以使用“智能搜索生成（高性能版）”。如页面要求开通后付费，请先阅读计费条款，再决定是否开启。
3. 进入左侧 **API Key** 页面，点击“创建 API Key”，填写名称，例如 `AIpartner`。按页面提示配置 AI 搜索所需权限；使用自定义授权时，仅授予必要权限。
4. 复制生成的完整 API Key，填写到项目根目录的 `.env`：

```dotenv
BAIDU_API_KEY="这里填写百度 API Key"
```

填写的是 **API Key 本身**，不是 Access Key / Secret Key，也不要手动加上 `Bearer ` 前缀；项目会自动处理请求头。控制台操作可参考[百度 API Key 官方指南](https://cloud.baidu.com/doc/BAIDU_AI_SEARCH/s/5mkmgi38d)。

> 每日 100 次指接口调用额度，不是 100 轮聊天。项目初始化时的连通性检查、重试和一次对话中的多次搜索都可能消耗额度。项目不会自动在第 100 次时停止调用；若开启后付费，请留意控制台用量和账单。

## 二、智谱：联网搜索

本项目通过智谱模型的“对话中的网络搜索”能力获取搜索结果并生成摘要，默认组合为 `glm-4.7-flashx` + `search_pro`，无需单独搭建搜索服务。功能说明见[智谱联网搜索文档](https://docs.bigmodel.cn/cn/guide/tools/web-search)。

### 申请步骤

1. 打开[智谱 BigModel 平台](https://bigmodel.cn/)，注册或登录，按平台提示完成所需认证。
2. 进入[API Key 管理页面](https://bigmodel.cn/apikey/platform)，创建并复制 API Key，建议命名为 `AIpartner`。
3. 在控制台确认所用模型及联网搜索能力可用，并检查账户余额或可用资源包。模型调用和搜索可能产生费用，具体查看[智谱产品价格](https://bigmodel.cn/pricing)，不要默认所有搜索都是免费的。
4. 将密钥填写到项目根目录的 `.env`：

```dotenv
ZHIPU_API_KEY="这里填写智谱 API Key"
```

通常无需修改其他配置。如需显式写出项目默认值，可添加：

```dotenv
ZHIPU_SEARCH_MODEL="glm-4.7-flashx"
ZHIPU_SEARCH_ENGINE="search_pro"
```

若平台提示默认模型不可用，请先核对账户权限及模型状态，再选择支持联网搜索的模型修改 `ZHIPU_SEARCH_MODEL`。

## 三、配置后如何使用

1. 保存 `.env`，完整退出并重新启动 AIpartner，仅刷新网页不会重新加载密钥。
2. 在角色的 `character_config.toml` 的 `[character]` 下设置：

   ```toml
   [character]
   scene_mode = "realtime"
   ```

3. 打开角色，尝试发送：“请联网搜索今天的科技新闻，并简要总结。”是否成功应结合终端的搜索初始化及调用日志判断，不要仅凭角色声称自己搜索过来判断。

当前程序在自动初始化搜索服务时**先尝试智谱，再尝试百度**。如果只想使用百度的免费额度，请仅配置百度，并将智谱密钥留空：

```dotenv
ZHIPU_API_KEY=""
BAIDU_API_KEY="这里填写百度 API Key"
```

搜索密钥不能代替正常聊天所需的 `LLM_API_KEY`。

## 四、常见问题与安全提醒

- **提示未配置密钥**：请检查`.env`是否配置了正确的API KEY，并重启服务。
- **认证失败或无权限**：检查密钥是否完整、是否已失效，以及账户是否完成认证和所需授权。
- **额度不足或限流**：在服务商控制台查看免费额度、余额和调用频率限制。
- **角色不搜索**：确认角色处于 `realtime` 模式，并查看终端是否成功初始化搜索服务。
- **保护密钥和隐私**：不要将真实 `.env`、密钥截图或含密钥的日志上传到 GitHub；搜索问题会发送给相应服务商，请勿输入不希望对外发送的敏感信息。

# 其他声明

本文档内容主要由大模型生成，仅供参考。
