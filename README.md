# AIpartner

AIpartner 是一个通过网页 GUI 使用的本地 AI 聊天伙伴项目。你只需在 `characters/` 下添加一个角色文件夹并编写角色设定，就能创建新的聊天角色。通过添加角色立绘和参考语音，你可以实现Galgame式的角色对话。**创建角色无需任何训练或微调模型**。

项目支持同时打开多个角色的对话窗口，但为了避免显存争用和生成状态冲突，**同一时间只能由一个角色生成回复**。

本项目需要配置大模型API来实现与角色的对话，语音合成和记忆存储则基于本地模型。

## 版本更新

### V0.2

- 新增图片识别：可以和AI伙伴分享你拍的照片了。
- 调整角色配置结构：角色名称和场景模式移至 `[character]`，主题、收藏和分组移至 `[frontend]`。

从旧版本升级时：

1. 建议先备份 `characters/`下所有的角色文件夹，再通过 `git pull` 或重新下载项目更新代码。
2. **必须使用新版本的 `characters/character_config.default.toml`**。
3. 角色个人文件无需任何改动，角色自身旧格式的 `character_config.toml` 会在加载时自动迁移。
4. 在 `aipartner` 环境中重新执行 `python -m pip install -r requirements.txt`，安装本次新增依赖。
5. 如需图片识别，在 `.env` 中补充三项 `LLM_VISION_*` 配置；不配置仍可正常进行聊天。详见 [配置大模型 API](#配置大模型 API)。

## 效果展示

### 旮旯模式

该模式类似于Galgame，角色回复会带有合适的立绘和语音。

![DS鲸鱼娘-对话展示](images/DS鲸鱼娘-对话展示.png)

![爱莉希雅-对话展示](images/爱莉希雅-对话展示.png)

![艾妮斯-对话展示](images/艾妮斯-对话展示.png)

### 文本模式

该模式类似于微信聊天，角色回复只有文本。

![DS鲸鱼娘-对话展示-文本模式1](images/DS鲸鱼娘-对话展示-文本模式1.png)

![DS鲸鱼娘-对话展示-文本模式2](images/DS鲸鱼娘-对话展示-文本模式2.png)

## 功能特性

- **零训练创建角色**：添加角色文件夹和 `character_setting.txt` 即可开始文字对话。
- **网页聊天界面**：通过浏览器选择、收藏和管理不同角色。
- **两种对话表现形式**：
  - **旮旯模式（Galgame mode）**：根据回复内容切换角色立绘，并使用参考音频进行语音克隆与配音。
  - **文本模式（Text mode）**：类似即时通讯软件，仅显示文字和头像。
- **多角色管理**：可同时打开多个角色窗口，并为角色设置分组、收藏状态和独立主题。
- **角色长期记忆**：使用 ChromaDB 和本地 BGE 嵌入模型保存、检索对话记忆。
- **背景故事导入**：可将结构化背景资料导入角色的独立记忆库。
- **实时与沙盒场景**：实时模式可感知现实时间并按需联网搜索；沙盒模式适合架空世界或沉浸式角色扮演。
- **可选图片识别**：配置独立的视觉模型 API 后，可在聊天中一次上传最多 3 张图片，并在对话历史中查看图片及识别结果。
- **可选语音翻译**：可保留中文对话文本，同时将送入 TTS 的台词翻译成日语等目标语言。

## 角色资源

本项目中默认只带有DS鲸鱼娘一个角色资源，如需其他角色可以阅读 [`使用指南/如何创建新角色.md`](使用指南/如何创建新角色.md)，来自行制作。

本项目还提供游戏 "崩坏3" 和 "灵魂潮汐" 中的少量角色资源，可以通过以下链接下载：

百度网盘链接如下：

```text
通过网盘分享的文件：AIpartner-characters
链接: https://pan.baidu.com/s/1Wj7ZpOsLxWqxyLHnlKoSgA?pwd=w33j 提取码: w33j
```

Google Drive链接如下：

```text
https://drive.google.com/drive/folders/1YIx_e_RIkIebGMU-f9g-82Mb0e146t50?usp=sharing
```

> 下载角色资源后，请将角色文件夹直接放置在项目的characters文件夹下。
>
> 比如下载了 `Elysia` 和 `Ennis` 两个角色，那么正确的格式如下：
>
> ```text
> characters/
> ├─ character_config.default.toml
> ├─ DSChan
> ├─ Elysia
> └─ Ennis
> ```
>
> 以下格式是错误的，会导致 `崩坏3` 和 `灵魂潮汐` 被视为两个角色：
>
> ```text
> characters/
> ├─ character_config.default.toml
> ├─ DSChan
> ├─ 崩坏3
> |  └─ Elysia
> └─ 灵魂潮汐
>    └─ Ennis
> ```

## 项目结构

| 文件夹或文件 | 作用 |
|---|---|
| `characters/` | 存放角色设定、配置、图片、参考语音和背景故事，以及运行后生成的角色记忆。创建新角色时，在此添加角色文件夹。 |
| `frontend/` | 网页前端，包含角色选择、文本聊天和旮旯模式所需的页面、样式、交互脚本及默认图片资源。 |
| `images/` | 存放 README 等说明文档使用的项目效果截图。 |
| `utils/` | 后端功能模块，负责大模型调用、角色管理、记忆检索、联网搜索、语音合成和翻译等。 |
| `wavs/` | 运行时生成的语音文件输出目录，供网页播放角色配音。 |
| `weights/` | 存放本地语音合成模型和文本嵌入模型权重，需要按下文说明另行下载。 |
| `使用指南/` | 存放角色创建、API 申请等操作指南，以及整理角色资料时使用的提示词。 |
| `.env` | 本地配置文件，用于填写对话模型、视觉模型和搜索服务的 API 密钥、模型名称及接口地址。不要将含真实密钥的文件上传到 GitHub。 |
| `.gitignore` | Git 忽略规则，排除模型权重、运行时生成的语音、缓存和虚拟环境等无需提交的文件。 |
| `chatGUI.py` | 角色对话核心，组织大模型交互、工具调用、记忆处理及角色运行状态。 |
| `import_backstory.py` | 背景故事导入脚本，将指定角色的背景资料写入对应场景模式的记忆库。 |
| `main.py` | FastAPI 服务入口，提供网页访问、聊天接口、角色管理及语音播放等后端服务。 |
| `README.md` | 项目说明，包含功能介绍、环境安装、模型下载、配置和启动方法。 |
| `requirements.txt` | Python 依赖清单；先安装适配本机的 torch，再通过此文件安装其他依赖。 |
| `start_aipartner.bat` | Windows 一键启动脚本，使用 `aipartner` Conda 环境启动项目，并自动打开网页。 |

## 运行方式概览

AIpartner 本身不包含本地聊天大模型。对话文本由你在 `.env` 中配置的 **OpenAI 兼容 API** 生成；本地模型用于以下功能：

| 模型 | 用途 | 项目内固定目录 |
|---|---|---|
| `Qwen/Qwen3-TTS-12Hz-0.6B-Base` | 旮旯模式的语音克隆与合成 | `weights/Qwen3-TTS-12Hz-0.6B-Base/` |
| `BAAI/bge-base-zh-v1.5` | 角色记忆和背景故事的向量检索 | `weights/bge-base-zh-v1.5/` |

## 环境要求

目前已验证的环境：

- Windows 11
- Conda 环境名：`aipartner`
- Python 3.13.14
- PyTorch 2.13.0 + CUDA 13.2 构建（`torch==2.13.0+cu132`）
- NVIDIA GeForce RTX 3060 Laptop GPU，6 GB 显存

硬件建议：

| 使用方式 | 建议配置 |
|---|---|
| 仅文本模式 | 可不使用独立显卡；本地嵌入模型可在 CPU 上运行，但初始化和检索速度会较慢 |
| 旮旯模式 | NVIDIA RTX 3060 或更高型号，至少 6 GB 显存，建议 8 GB 及以上 |
| 内存 | 建议 16 GB 及以上 |
| 磁盘 | 建议为项目、Python 环境、模型权重及安装缓存合计预留 10–15 GB 可用空间；两个模型权重合计约 2.9 GB，运行时还会产生语音和记忆数据，长期使用需额外预留空间 |

> [!IMPORTANT]
> 当前语音实现要求 CUDA 可用，并以 BF16 在 NVIDIA GPU 上运行。没有可用的 NVIDIA GPU、模型权重或完整参考语音时，角色仍可使用文本模式。

## 安装

如果你没有任何项目安装和环境配置经验：

- 可以参考 [`使用指南/AIpartner零基础环境配置教程.md`](使用指南/AIpartner零基础环境配置教程.md) 来配置项目所需环境。
- 更推荐使用当前的大模型工具（如Codex、Claude Code、国内的Workbuddy或者百度搭子）来帮你安装。

以下命令以 Windows PowerShell 为例。Linux 用户可以使用相同的 Conda 与 Python 命令，但目前主要在 Windows 环境验证。

### 1. 获取项目

在终端执行以下命令获取项目。也可以在 [GitHub 仓库页面](https://github.com/iwanagotomars/AIpartner)选择 **Code → Download ZIP**，解压后进入项目根目录。

```powershell
git clone "https://github.com/iwanagotomars/AIpartner.git"
cd "AIpartner"
```

如果尚未安装 Conda，可先安装 [Miniconda](https://www.anaconda.com/docs/getting-started/miniconda/main)。

### 2. 创建已验证的 Conda 环境

```powershell
conda create -n aipartner python=3.13 -y
conda activate aipartner
python -m pip install --upgrade pip
```

### 3. 安装 PyTorch 和项目依赖

先进入项目根目录（将下方路径替换为自己的实际路径），并激活环境：

```powershell
cd "yourPath\AIpartner"
conda activate aipartner
```

接着**单独安装适配本机的 torch**：前往 [PyTorch 官方安装页](https://pytorch.org/get-started/locally/)，根据操作系统、Python 和显卡驱动支持的 CUDA 版本选择安装方式，将生成的安装命令在当前终端执行。建议同时安装配套的 `torchaudio`；使用旮旯模式需选择 CUDA 版，而不是 CPU 版。

安装 torch 后，先运行以下命令检查 GPU 是否可用：

```powershell
python -c "import torch; print('CUDA available:', torch.cuda.is_available()); print('GPU:', torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'Unavailable')"
```

理想情况下，输出 `CUDA available: True`，并显示你的 NVIDIA 显卡名称。如果输出 `CUDA available: False`，表示当前 torch 无法使用 CUDA GPU，此时只能使用文本模式交互，无法使用依赖 GPU 语音合成的旮旯模式。

确认 GPU 可用后（或确定只使用文本模式），最后安装其余项目依赖：

```powershell
python -m pip install -r requirements.txt
```

## 下载模型权重

两个模型都必须放到指定目录；代码默认只从本地读取，不会在运行时自动下载。

首次完整下载、无本地缓存时，每个模型预计消耗的流量为：

- [Qwen3-TTS-12Hz-0.6B-Base](https://huggingface.co/Qwen/Qwen3-TTS-12Hz-0.6B-Base/tree/main)：约 **2.52 GB**，已包含 `speech_tokenizer`。
- [bge-base-zh-v1.5](https://huggingface.co/BAAI/bge-base-zh-v1.5/tree/main)：约 **410 MB**（0.41 GB）。

合计约 **3 GB**，不包含 PyTorch 和其他依赖的下载流量。实际流量会随模型更新、缓存命中和失败重试而变化。下面两种下载方式任选一种即可，无需重复下载。

### 中国大陆推荐：从 ModelScope 下载

[ModelScope 魔搭社区](https://modelscope.cn/) 通常在中国大陆访问更稳定。

```powershell
conda activate aipartner
pip install -U modelscope

modelscope download --model Qwen/Qwen3-TTS-12Hz-0.6B-Base --local_dir .\weights\Qwen3-TTS-12Hz-0.6B-Base
modelscope download --model BAAI/bge-base-zh-v1.5 --local_dir .\weights\bge-base-zh-v1.5
```

模型页面：

- [Qwen3-TTS-12Hz-0.6B-Base（ModelScope）](https://modelscope.cn/models/Qwen/Qwen3-TTS-12Hz-0.6B-Base)
- [bge-base-zh-v1.5（ModelScope）](https://modelscope.cn/models/BAAI/bge-base-zh-v1.5)

### 其他地区：从 Hugging Face 下载

```powershell
conda activate aipartner
# hf 命令已由 requirements.txt 中的 huggingface-hub 提供，无需升级。

hf download Qwen/Qwen3-TTS-12Hz-0.6B-Base --local-dir .\weights\Qwen3-TTS-12Hz-0.6B-Base
hf download BAAI/bge-base-zh-v1.5 --local-dir .\weights\bge-base-zh-v1.5
```

模型页面：

- [Qwen3-TTS-12Hz-0.6B-Base（Hugging Face）](https://huggingface.co/Qwen/Qwen3-TTS-12Hz-0.6B-Base)
- [bge-base-zh-v1.5（Hugging Face）](https://huggingface.co/BAAI/bge-base-zh-v1.5)

下载完成后的关键目录应类似：

```text
weights/
├─ Qwen3-TTS-12Hz-0.6B-Base/
│  ├─ config.json
│  ├─ model.safetensors
│  └─ speech_tokenizer/
│     └─ model.safetensors
└─ bge-base-zh-v1.5/
   ├─ config.json
   ├─ pytorch_model.bin
   └─ 1_Pooling/
      └─ config.json
```

不要额外套一层同名目录。例如下面这种路径是错误的：

```text
weights/Qwen3-TTS-12Hz-0.6B-Base/Qwen3-TTS-12Hz-0.6B-Base/model.safetensors
```

## 配置大模型 API

在项目根目录创建 `.env`文件。最小配置如下：

```dotenv
# 必填：支持 OpenAI Chat Completions 协议的大模型服务
LLM_API_KEY="你的 API Key"
LLM_MODEL_ID="你的模型 ID"
LLM_BASE_URL="https://你的服务商地址/v1"

# 可选：图片识别；三项需要同时填写
LLM_VISION_API_KEY=""
LLM_VISION_MODEL_ID=""
LLM_VISION_BASE_URL=""

# 可选：实时模式的联网搜索，二选一或同时配置
ZHIPU_API_KEY=""
BAIDU_API_KEY=""

# 可选：智谱搜索参数；不填写时使用项目默认值
# ZHIPU_SEARCH_MODEL="glm-4.7-flashx"
# ZHIPU_SEARCH_ENGINE="search_pro"
```

注意：

- `LLM_API_KEY`、`LLM_MODEL_ID` 和 `LLM_BASE_URL` 是正常对话所必需的。
- 模型接口需要兼容本项目使用的 OpenAI 风格调用和 `thinking` 扩展参数；不同服务商的模型名、Base URL 和兼容程度可能不同，请以服务商文档为准。
- `LLM_VISION_API_KEY`、`LLM_VISION_MODEL_ID` 和 `LLM_VISION_BASE_URL` 用于有图片输入时的回复，三项必须同时填写；视觉模型需要支持图片输入、工具调用及本项目使用的 OpenAI 风格接口。不配置时仍可正常进行聊天。
- `ZHIPU_API_KEY` 与 `BAIDU_API_KEY` 仅用于实时场景下的联网搜索；不使用搜索时可以留空。

关于API的申请和详细使用方式，请参考 [`使用指南/如何申请API.md`](使用指南/如何申请API.md)

### 图片识别（可选）

默认角色配置中的 `[vision]` 已设置 `vision = true`。同时填写 [配置大模型 API](#配置大模型 API) 三项视觉模型配置后，聊天输入框左侧会提供图片入口；如需为某个角色关闭该功能，可在该角色的 `character_config.toml` 中添加：

```toml
[vision]
vision = false
```

目前支持 JPG、JPEG 和 PNG，一次最多上传 3 张，单张不超过 10 MiB，也可以只发送图片。

用于模型调用的临时图片会在处理后删除；对话历史会在角色当前记忆目录的 `chat_history/images` 中保存转换后的 JPEG 副本，并随历史记录展示。

图片及相关文字会发送给你配置的视觉模型服务商，请不要上传不希望交由该服务处理的敏感内容。

## 启动项目

### 推荐：一键启动（Windows）

完成环境安装、模型下载和 API 配置后，双击项目根目录下的脚本 `start_aipartner.bat`。脚本会自行启动项目，并在服务就绪后自动打开网页。

使用期间请保持 `AIpartner Server` 窗口开启。如果一键启动失败，再按下面的方式手动启动。

### 备用：命令行启动

在已配置 Conda 的终端中进入项目根目录（请替换为自己的实际路径），然后运行：

```powershell
cd "yourPath\AIpartner"
conda activate aipartner
python -m uvicorn main:app --host 127.0.0.1 --port 8000
```

服务启动成功后，在浏览器打开：

```text
http://127.0.0.1:8000
```

无论使用哪种启动方式，停止服务时请在运行服务的终端窗口中按 `Ctrl+C`。

## 创建自己的角色

最小可用角色只需要一个非空的 UTF-8 文本文件：

```text
characters/
└─ MyCharacter/
   └─ character_setting.txt
```

`character_setting.txt` 中建议包含角色身份、背景、性格、语言风格、与 User 的关系以及回复要求。添加或修改角色后需要重启服务。

完整角色可以包含：

```text
characters/MyCharacter/
├─ character_setting.txt          # 必需：完整角色设定
├─ character_config.toml          # 可选：名称、场景、主题、记忆等配置
├─ profile.png                    # 可选：角色头像
├─ portraits/                     # 可选：旮旯模式立绘
│  ├─ default.png
│  ├─ happy.png
│  └─ description.txt
├─ ref_audios/                    # 可选：语音克隆参考音频
│  ├─ default.wav
│  ├─ default.txt
│  └─ description.txt
├─ frontend_imgs/                 # 可选：角色专属背景和用户头像
└─ backstory/                     # 可选：结构化背景故事
```

详细格式、立绘说明、参考语音要求和背景故事模板请阅读 [`使用指南/如何创建新角色.md`](使用指南/如何创建新角色.md)。

### 旮旯模式资源要求

- `portraits/` 中建议至少提供 `default.png`，并在 `description.txt` 中说明各立绘的适用情绪或动作。
- `ref_audios/` 中每个 WAV/MP3 都必须有一个同名 TXT；TXT 内容必须与音频中实际说出的文字一致。
- 参考音频建议使用清晰、单人、无背景音乐且无明显混响的录音。
- GPU、权重、立绘或参考语音不可用时，可以继续使用文本模式。

### 导入角色背景故事

先关闭正在运行的聊天服务，然后执行：

```powershell
conda activate aipartner
python import_backstory.py MyCharacter --scene-mode realtime
```

沙盒场景使用：

```powershell
python import_backstory.py MyCharacter --scene-mode sandbox
```

导入会替换该角色、该场景模式下旧的背景故事记录，但不会删除正常对话产生的记忆。四类背景文件的具体格式见角色创建指南。

## 常见问题

### 一键启动被Windows安全中心阻止

Windows安全中心可能会阻止一键启动脚本调用python环境等操作，这时候可以：

1. 将`start_aipartner.bat`用记事本打开；
2. 随便找一个空行，打一个空格，再删除空格；
3. 保存文件，关闭文件。

这时候一般来说，Windows安全中心就不会再阻止了。

### 角色可以出现，但打开后初始化失败

优先检查终端错误，常见原因包括：

- `character_setting.txt` 不存在、为空或不是 UTF-8 编码；
- `character_config.toml` 格式错误；
- 模型权重目录多套了一层或下载不完整；
- 旮旯模式缺少默认立绘、参考音频或同名参考文本；
- `.env` 中的大模型 API 地址、模型 ID 或密钥不可用。

### `torch.cuda.is_available()` 返回 `False`

请确认使用的是 NVIDIA 显卡、驱动工作正常，并且安装了 CUDA 版 PyTorch，而不是 CPU 版。可以重新执行本文的 PyTorch 安装命令，或根据 PyTorch 官方安装页选择适合本机的构建。

### 显存不足

关闭其他占用 GPU 的应用并重启服务。仍然不足时请使用文本模式，或换用显存更大的 NVIDIA 显卡。不要同时启动多个 AIpartner 后端实例加载 TTS 权重。

### 为什么多个窗口不能同时回复

这是当前设计：可以同时打开多个角色窗口，但后端使用全局生成协调机制，同一时刻只允许一个角色执行回复、语音生成和记忆整理。

## 依赖模型与致谢

- [Qwen3-TTS](https://github.com/QwenLM/Qwen3-TTS) 和 [faster-qwen3-tts](https://github.com/andimarafioti/faster-qwen3-tts)：用于语音克隆与合成；
- [BGE / FlagEmbedding](https://github.com/FlagOpen/FlagEmbedding)：用于中文文本嵌入和记忆检索；
- [FastAPI](https://fastapi.tiangolo.com/)、[LangGraph](https://github.com/langchain-ai/langgraph)、[ChromaDB](https://github.com/chroma-core/chroma) 等开源项目为本项目提供了基础能力；
- [ZipZipPipe](https://space.bilibili.com/4168597/dynamic)：创造了广为接受的DeepSeek鲸鱼娘形象。

使用前请分别阅读并遵守各依赖、模型权重和第三方 API 的许可证及服务条款。

## 使用声明

本项目仅供个人学习、娱乐使用，请勿用于商业用途。
