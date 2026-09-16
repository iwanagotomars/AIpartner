# AIpartner 零基础环境配置教程

这篇教程面向没有安装过 Python、没有使用过命令行的用户。我们将从安装 Miniconda 开始，依次完成项目下载、环境配置、模型下载和 API 设置，最后通过双击文件启动 AIpartner。

**本文以 Windows 11、普通 Intel / AMD 处理器的 64 位电脑为例。**命令统一在 **Anaconda Prompt** 中执行。

## 一、开始前先确认这些事情

AIpartner 的角色对话由 在线 的大模型 API 生成，角色记忆和语音合成使用 本地 模型。因此，安装完成后仍需要联网，并配置自己的大模型 API Key。

先决定自己想使用哪种模式：

| 使用方式 | 需要准备什么 |
|---|---|
| 文本模式：像微信一样进行文字聊天 | 可以没有 NVIDIA 显卡；仍需下载本地embedding模型并配置大模型 API |
| 旮旯模式：显示立绘并生成角色配音，Galgame式的交互体验 | 建议 NVIDIA RTX 3060 或更高型号，至少 6 GB 显存，建议 8 GB 及以上；还需语音模型和角色语音素材 |

建议准备至少 16 GB 内存，并为环境、项目和模型预留 **15 GB 以上可用磁盘空间**。这是便于安装和后续使用的余量，不代表项目会立即占满这些空间。Miniconda 环境和下载缓存也会占用安装盘空间，不能只检查项目所在盘。

完整模型下载预计约 3 GB，另外还需要下载 PyTorch 和其他依赖。首次配置建议使用稳定网络。

## 二、安装 Miniconda

### 1. 下载安装包

Miniconda 用来给 AIpartner 建立独立的 Python 环境。

打开 [Download Success | Anaconda](https://www.anaconda.com/download/success?reg=skipped)，选择 Windows 64-Bit Graphical Installer 进行下载。

![miniconda](../images/miniconda.png)

如果官网下载较慢，可以打开[清华大学 Miniconda 镜像目录](https://mirrors.tuna.tsinghua.edu.cn/anaconda/miniconda/)，使用浏览器的 `Ctrl+F` 查找下面的文件名并下载：

```text
Miniconda3-latest-Windows-x86_64.exe
```

### 2. 运行安装程序

双击下载的安装包，**一路默认即可。**

**默认安装对本项目的一键启动最方便。** 当前脚本会自动查找用户目录下的 `miniconda3` 等常见位置。如果改装到其他位置，后面可能需要在启动脚本中指定 Conda 路径，处理方法见文末。

### 3. 打开 Anaconda Prompt

打开 Windows 开始菜单，搜索 `Anaconda Prompt`，打开出现的对应程序。

Windows 11 系统的话一般来说可以直接按 Win 键，以下图标即为 `Anaconda Prompt`

<img src="../images/anaconda%20prompt.png" alt="anaconda prompt" style="zoom:60%;" />

打开 `Anaconda Prompt`出现命令行窗口后，输入下面的命令并按回车：

```bat
conda --version
```

如果出现类似 `conda 26.x.x` 的版本信息，说明 Conda 已经可以使用。版本数字与示例不同没有关系。

接下来所有安装命令都在这个窗口输入。

- **每次复制一条命令，按回车，等它执行完再输入下一条。** 

- 只复制代码框内的命令，不要复制示例输出中的 `(base)`、`(aipartner)` 或路径提示符。
- 不要先输入 `python` 进入带有 `>>>` 的交互界面；如果已经进入，输入 `exit()` 并回车即可退出。

## 三、下载并解压 AIpartner

> 微微吐槽一下：能看到这个教程，项目应该已经下载好了吧

### 1. 下载项目压缩包

打开 [AIpartner 的 GitHub 页面](https://github.com/iwanagotomars/AIpartner)，点击 **Code → Download ZIP**。

本教程使用压缩包下载，不需要安装 Git。

### 2. 解压到固定位置

下载完成后，右键点击 ZIP 文件，选择“全部解压缩”。不要直接在压缩包里双击启动文件。

为了方便演示，本文使用以下项目路径：

```text
D:\AIpartner
```

你也可以放在自己有写入权限、空间充足的其他文件夹。**后续命令中的项目路径都要换成你自己的路径。** 建议使用简单的英文路径，避免放在需要管理员权限的系统目录中。

**解压后的文件夹可能叫 `AIpartner-main`，需要重命名为 `AIpartner`。**打开后应能直接看到：

```text
AIpartner
├─ characters
├─ frontend
├─ utils
├─ 使用指南
├─ main.py
├─ requirements.txt
└─ start_aipartner.bat
```

最终看到的项目界面应该是这样的：

![项目目录](../images/项目目录.png)

### 3. 在命令行中进入项目文件夹

回到 Anaconda Prompt，执行：

```bat
cd /d "D:\AIpartner"
```

如果你的项目在其他位置，请替换双引号内的内容。

切换成功后，命令行每行的前缀应该是：

```bash
(base) D:\AIpartner>
```

## 四、创建 AIpartner 专用环境

在刚才的 Anaconda Prompt 中执行：

```bat
conda create -n aipartner python=3.13 -y
```

这条命令会创建一个名为 `aipartner` 的环境，并安装 Python 3.13。项目当前说明使用 Python 3.13，Miniconda 安装器自带的 Python 版本不需要与它相同。

**请保持环境名为 `aipartner`，不要随意改名。**

创建过程需要联网，请等待下载和安装完成。如果 Conda 提示需要阅读并接受软件源的服务条款，按终端提供的指引查看、决定是否接受，完成后重新执行创建命令。如果出现网络错误或条款未处理，不能直接认为环境已经创建成功。

随后激活环境：

```bat
conda activate aipartner
```

提示符最前面应从 `(base)` 变为 `(aipartner)`。命令行每行的前缀应该是：

```bash
(aipartner) D:\AIpartner>
```

再检查 Python 版本：

```bat
python --version
```

正常应显示 `Python 3.13.x`，最后一位小版本号可以不同，此处你应该看到

![python版本](../images/python版本.png)

升级用于安装依赖的 pip：

```bat
python -m pip install --upgrade pip
```

如果下载很慢，可改用以下命令，通过[清华 PyPI 镜像](https://mirrors.tuna.tsinghua.edu.cn/help/pypi/)完成这一步：

```bat
python -m pip install --upgrade pip -i https://pypi.tuna.tsinghua.edu.cn/simple
```

> 如果中途关闭了窗口，重新打开 Anaconda Prompt 后
>
> - 先执行 `conda activate aipartner`
> - 再执行 `cd /d "D:\AIpartner"`。
> - 不需要重新创建环境，也不需要从头安装。

## 五、安装 PyTorch，并检查显卡能否使用

PyTorch 是本地模型运行所需的基础组件。请先安装它，再安装项目的其他依赖。

### 1. 有 NVIDIA 显卡，希望使用配音

#### 确定CUDA版本

先在 Anaconda Prompt 执行：

```bat
nvidia-smi
```

正常会显示 NVIDIA 显卡、驱动版本等信息。

![nvidiasmi](../images/nvidiasmi.png)

如果找不到命令或提示驱动错误，先通过电脑厂商提供的驱动工具或 [NVIDIA 官方驱动页面](https://www.nvidia.com/Download/index.aspx)安装适合显卡的驱动，重启电脑，再检查。

#### 安装Pytorch

打开 [PyTorch 官方安装页](https://pytorch.org/get-started/locally/)，在安装选项中选择：

| 选项 | 选择内容 |
|---|---|
| PyTorch Build | Stable，稳定版 |
| Your OS | Windows |
| Package | Pip |
| Language | Python |
| Compute Platform | 你的显卡驱动支持的 CUDA 选项 |

复制网页生成的安装命令，到带有 `(aipartner)` 的 Anaconda Prompt 中执行。

<img src="../images/Pytorch安装指令.png" alt="Pytorch安装指令" style="zoom:60%;" />

#### 如何选择和自己CUDA版本对应的Pytorch

1. 如果Pytorch下载界面里有和你CUDA版本对应的Pytorch，下载对应的即可。

   - 按照“3. 验证安装结果”中的方式进行验证，观察CUDA是否可用。如果可用，那么可以转到第六节，安装其他项目依赖。
   - 不可用的话，按照接下来的第2点进行处理。

2. 如果没有，那么：

   先尝试下载最新CUDA版本的Pytorch，按照“3. 验证安装结果”中的方式进行验证，观察CUDA是否可用。

   - 如果可用，那么可以转到第六节，安装其他项目依赖。
   - 如果不可用
     - 不建议：删除当前Pytorch、花力气寻找适合自己CUDA版本的Pytorch。
     - 建议：升级CUDA。傻瓜般升级方法为，进入[下载面向游戏玩家和创作者的 NVIDIA App | NVIDIA](https://www.nvidia.cn/software/nvidia-app/) 界面，直接下载这个应用程序，按照里面的提示，把驱动都更新一遍。CUDA会更新到最新的版本，目前来看，会适配最新版的Pytorch。

### 2. 没有 NVIDIA 显卡，只使用文本模式

同样打开 [PyTorch 官方安装页](https://pytorch.org/get-started/locally/)，选择 Windows、Pip、Python，并将 Compute Platform 选为 **CPU**。在 `(aipartner)` 环境中执行网页生成的命令。

当前项目的 GPU 配音实现使用 NVIDIA CUDA。AMD 或 Intel 显卡不能直接按照本文的 CUDA 路线开启配音。

### 3. 验证安装结果

安装完成后执行：

```bat
python -c "import torch; print('PyTorch:', torch.__version__); print('CUDA available:', torch.cuda.is_available()); print('GPU:', torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'Unavailable')"
```

使用 NVIDIA 显卡的理想结果类似：

```text
PyTorch: 你实际安装的版本
CUDA available: True
GPU: NVIDIA GeForce RTX 3060 Laptop GPU
```

显卡名称不同没有关系，关键是 `CUDA available: True`。

- 如果安装的是 CPU 版，显示 `False` 和 `Unavailable` 属于预期结果，可以继续配置文本模式。
- 如果原本打算使用 GPU，却显示 `False`，请先检查驱动和安装命令是否选择了 CUDA 版；在解决前只能使用文本模式。

## 六、安装项目依赖

确认窗口前面仍显示 `(aipartner)`，并且当前目录是项目根目录，然后执行：

```bat
python -m pip install -r requirements.txt
```

这条命令会按照项目清单安装其他软件包。下载和安装过程可能持续较长时间，等命令执行完再继续。

如果中国大陆网络下下载较慢，可以使用以下替代命令：

```bat
python -m pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
```

两条命令选一条成功执行即可。镜像参数仅影响本次命令，不会永久修改你的 pip 设置；前面安装 CUDA 版 PyTorch 时，仍应保留 PyTorch 官网给出的专用下载地址。

如果出现 `No matching distribution found`，先确认 Python 是 3.13、电脑是 Windows x86_64，再尝试不带镜像参数的原始命令。仍然失败时，保留报错信息，不要随意删除依赖的版本号。

安装完成后，执行：

```bat
python -m pip check
```

理想结果为：

```text
No broken requirements found.
```

## 七、下载本地模型

### 1. 确认下载位置

下载模型前，再执行一次：

```bat
cd /d "D:\AIpartner"
```

以下命令里的 `weights` 是相对于当前文件夹的路径。**在错误的目录执行命令，模型就会下载到错误的位置。**

项目使用两个本地模型：

| 模型 | 用途 | 首次下载预计流量 |
|---|---|---|
| BAAI/bge-base-zh-v1.5 | 保存和检索角色记忆，文本模式也需要 | 约 410 MB |
| Qwen/Qwen3-TTS-12Hz-0.6B-Base | 生成角色配音 | 约 2.52 GB，包含 speech_tokenizer |

只准备使用文本模式时，可以先下载记忆模型；希望完成配音配置时，两个模型都下载。

### 2. 使用 ModelScope 下载

本教程使用国内可访问的 ModelScope 魔搭社区。先安装下载工具：

```bat
python -m pip install -U modelscope -i https://pypi.tuna.tsinghua.edu.cn/simple
```

下载记忆embedding模型：

```bat
modelscope download --model BAAI/bge-base-zh-v1.5 --local_dir .\weights\bge-base-zh-v1.5
```

准备使用配音的用户，再下载语音模型：

```bat
modelscope download --model Qwen/Qwen3-TTS-12Hz-0.6B-Base --local_dir .\weights\Qwen3-TTS-12Hz-0.6B-Base
```

等待所有文件下载完成、命令行提示符重新出现。下载中断后，可以先重新执行同一条命令，让工具检查并复用已有文件；不要一看到下载失败就删除整个目录。

### 3. 检查文件有没有放对位置

在文件资源管理器中打开项目的 `weights` 文件夹。完整配置的关键结构应类似：

```text
AIpartner
└─ weights
   ├─ bge-base-zh-v1.5
   │  ├─ config.json
   │  ├─ pytorch_model.bin
   │  └─ 1_Pooling
   │     └─ config.json
   └─ Qwen3-TTS-12Hz-0.6B-Base
      ├─ config.json
      ├─ model.safetensors
      └─ speech_tokenizer
         └─ model.safetensors
```

这不是完整文件清单，下载工具保存的其他配置文件也应保留。不要只下载图中列出的几个文件。

正确路径示例：

```text
D:\AIpartner\weights\bge-base-zh-v1.5\config.json
```

下面这种多套一层同名文件夹的路径是错误的：

```text
D:\AIpartner\weights\bge-base-zh-v1.5\bge-base-zh-v1.5\config.json
```

安装成功后，两个模型的路径和文件内容如下所示：

<img src="../images/bge.png" alt="bge" style="zoom:60%;" />

<img src="../images/qwen3tts.png" alt="qwen3tts" style="zoom:60%;" />

## 八、申请并配置大模型 API

### 1. 申请 DeepSeek API Key

本教程以项目开发过程中测试过的 DeepSeek API 服务为例。其他大模型服务尚未由项目验证，首次安装建议先按这一条路线完成。

1. 打开 [DeepSeek 开放平台](https://platform.deepseek.com/)，注册或登录账号。
2. 按页面要求完成验证，在 API Keys 页面创建一个密钥，名称可填写 `AIpartner`。
3. 保存生成的完整 API Key。
4. 检查账户余额和可用额度。API 调用按平台规则计费，网页版可以免费聊天并不代表 API 免费；具体以平台当前的用量和价格说明为准。

API Key 可以理解为程序访问你账户的凭证，不要轻易给别人。

![DPSKAPI](../images/DPSKAPI.png)

### 2. 显示文件扩展名

打开项目文件夹，在 Windows 11 文件资源管理器中选择“查看 → 显示 → 文件扩展名”。

<img src="../images/文件扩展名.png" alt="文件扩展名" style="zoom:60%;" />

### 3. 创建 .env

在项目文件夹下新建文本文件，命名改为`.env`。**注意，不能叫 `.env.txt`。**

<img src="../images/env文件.png" alt="env文件" style="zoom:60%;" />

首次配置可以填写下面的内容；已有其他配置时只更新对应字段，不要重复添加同名字段：

```dotenv
LLM_API_KEY="把这里替换成你申请的完整API Key"
LLM_MODEL_ID="deepseek-flash"
LLM_BASE_URL="https://api.deepseek.com"

# 可选：图片识别；暂时不用时保持为空
LLM_VISION_API_KEY=""
LLM_VISION_MODEL_ID=""
LLM_VISION_BASE_URL=""

# 网络搜索：暂时不用时保持为空
ZHIPU_API_KEY=""
BAIDU_API_KEY=""
```

将 `LLM_API_KEY` 引号内的文字替换为自己的真实密钥。保留英文半角双引号，不要粘贴多余空格，也不要将 API Key 换成账号密码。视觉模型和搜索 API 都是可选功能，第一次安装时可以先保持为空。

上面的模型 ID 和地址参考 [DeepSeek 官方接入文档](https://api-docs.deepseek.com/zh-cn/)，核对日期为 2026 年 9 月 16 日。服务商可能调整可用模型；若提示模型不存在，请核对官方当前说明。

搜索 API 属于可选功能。第一次安装可以让 `ZHIPU_API_KEY` 和 `BAIDU_API_KEY` 保持为空，先完成正常聊天。需要联网搜索时，再阅读项目 `使用指南` 文件夹中的《如何申请API.md》。

### 4. 检查配置与接口

先确认程序能够读到三项必填配置：

```bat
python -c "import os; from dotenv import load_dotenv; load_dotenv(); print({k: bool(os.getenv(k)) for k in ('LLM_API_KEY','LLM_MODEL_ID','LLM_BASE_URL')})"
```

理想结果为：

```text
{'LLM_API_KEY': True, 'LLM_MODEL_ID': True, 'LLM_BASE_URL': True}
```

这一步只检查是否填了内容，不会打印密钥，也不能证明密钥有效。

接着测试一次真实 API 调用。这一步会产生一次 API 请求，可能消耗少量额度：

```bat
python -c "from utils.llm import get_llm; r=get_llm().invoke('只回复OK'); print(r.content)"
```

如果返回 `OK` 或其他正常文字，说明基础接口已经连通。如果报错，先检查密钥、模型 ID、API 地址、账户余额和网络。

![API连接测试](../images/API连接测试.png)

### 5. 可选：启用图片识别

基础文字聊天正常后，如果希望在聊天中上传图片，还需要向支持视觉模型的服务商申请 API，并确认模型同时支持图片输入、工具调用和 OpenAI 风格的 Chat Completions 接口。

将服务商提供的信息填写到 `.env`：

```dotenv
LLM_VISION_API_KEY="视觉模型的 API Key"
LLM_VISION_MODEL_ID="视觉模型 ID"
LLM_VISION_BASE_URL="视觉模型 API 地址"
```

三项必须同时填写，不能只填写其中一部分。保存后完整停止并重新启动 AIpartner；默认角色配置已设置 `vision = true`，配置有效时，聊天输入框左侧会出现可用的图片入口。不配置视觉模型不会影响文字聊天。

目前支持 JPG、JPEG 和 PNG，一次最多上传 3 张，单张不超过 10 MiB。图片及本轮相关文字会发送给所配置的视觉模型服务商，请勿上传不希望交由第三方处理的敏感内容。更详细的配置和角色开关说明见《如何申请API.md》和《如何创建新角色.md》。

**目前DeepSeek V4.1 Flash支持图片识别**，因此可以直接写成如下格式：

```text
LLM_API_KEY="把这里替换成你申请的完整API Key"
LLM_MODEL_ID="deepseek-flash"
LLM_BASE_URL="https://api.deepseek.com"

# 图片识别
LLM_VISION_API_KEY="把这里替换成你申请的完整API Key，和 LLM_API_KEY 一样即可"
LLM_VISION_MODEL_ID="deepseek-flash"
LLM_VISION_BASE_URL="https://api.deepseek.com"

# 网络搜索：暂时不用时保持为空
ZHIPU_API_KEY=""
BAIDU_API_KEY=""
```

## 九、一键启动 AIpartner

### 1. 双击启动文件

打开项目根目录，双击：

```text
start_aipartner.bat
```

正常情况下，脚本会检查 `aipartner` 环境，打开一个标题为 **AIpartner Server** 的服务窗口，等待服务就绪，然后自动打开浏览器。

浏览器地址应为：

```text
http://127.0.0.1:8000
```

这是本机运行的网页地址，可以直接复制到浏览器地址栏访问。项目启动时终端会输出信息，第一次加载可能比较慢，请先观察服务窗口。

### 2. 先完成一次文本聊天

在网页中选择项目自带的角色，进入文本模式，发送一句：

```text
你好啊
```

等待角色正常回复。能打开首页只说明网页服务启动成功；**能够进入角色并收到实际回复，才说明基本聊天配置已经通过验证。**

如果收到“抱歉，我的大脑刚刚走神了，能再说一遍吗？”，请查看服务窗口中的 `[agent_node, 大模型调用出错]`。这句是程序的异常提示，应根据后面的具体错误排查。

### 3. 再测试旮旯模式

如果已经确认 CUDA 可用、下载了语音模型，再进入旮旯模式发送一条消息。

第一次生成配音需要加载模型，因此相对较慢，后续对话中语音合成会快很多。

看到立绘、收到文字并听到配音，说明这条功能链路已经跑通。

如果有文字但没有声音，先查看浏览器和系统音量，再查看服务窗口中的语音模型加载或合成错误。

### 4. 以后怎样打开和关闭

以后使用时，直接双击 `start_aipartner.bat` 即可，不需要重新安装环境或下载模型。

聊天期间保持 **AIpartner Server** 窗口开启，可以最小化。只关闭浏览器不会自动关闭后台服务。

结束使用时，先等待当前回复、配音和记忆整理完成，再切换到服务窗口按 `Ctrl+C`。如果命令行询问是否终止批处理，按提示输入 `Y` 并回车。（如果嫌麻烦的话，确保所有的角色对话已经结束后，直接把窗口叉了就行，一般不影响后续使用。）

想从桌面启动，可以给 `start_aipartner.bat` 创建桌面快捷方式。**创建的是快捷方式，不要把 BAT 文件从项目文件夹移走**，因为它需要通过自身位置查找项目。

## 十、一键启动失败时怎么办

### 1. 提示 Conda was not found

这表示启动脚本找不到 Miniconda，常见于自定义安装目录。

用记事本打开`start_aipartner.bat`

在文件开头部分找到下面这一行：

```bat
set "CONDA_EXE="
```

将它替换为实际 Conda 程序路径，例如：

```bat
set "CONDA_EXE=D:\miniconda3\Scripts\conda.exe"
```

先在文件资源管理器中确认该文件存在。保存后重新双击脚本。

### 2. 手动启动

请手动启动，先确认没有另一个 AIpartner 服务正在运行，再在 Anaconda Prompt 中逐条执行：

```bat
conda activate aipartner
cd /d "D:\AIpartner"
python -m uvicorn main:app --host 127.0.0.1 --port 8000
```

成功后打开：

```text
http://127.0.0.1:8000
```

手动启动成功时也要保持这个命令行窗口开启。

如果再失败，请按照窗口中的输出信息进行针对性解决。

### 3. 常见错误对照

| 看到的现象或关键词 | 先检查哪里 |
|---|---|
| `conda` 不是内部或外部命令 | 是否打开了 Miniconda 安装后的 Anaconda Prompt |
| 找不到 `requirements.txt` 或 `main.py` | 是否进入直接包含这些文件的项目根目录 |
| `ModuleNotFoundError` | 是否激活了 aipartner，依赖安装是否中途失败 |
| `CUDA available: False` | 是否有 NVIDIA 显卡、驱动是否正常、是否装成了 CPU 版 PyTorch |
| 角色初始化失败，提示本地模型或配置文件缺失 | weights 的目录层级和模型下载是否完整 |
| `401`、`invalid api key` | 大模型 API Key 是否完整有效 |
| 余额不足、额度不足 | 大模型服务平台的账户状态 |
| `model not found` | 模型 ID 和 API 地址 |
| `timeout`、`connection` | 网络连接和服务商接口状态 |
| `CUDA out of memory` | 关闭其他占用显存的应用，或先使用文本模式 |
| 端口占用、`WinError 10048` | 是否已经启动过服务；先尝试访问本机网页 |

**修改 `.env` 后，需要完整停止并重新启动服务，单纯刷新网页不会重新加载配置。**

### 4. 被Windows安全中心阻止

Windows安全中心可能会阻止一键启动脚本调用python环境等操作，这时候可以：

1. 将`start_aipartner.bat`用记事本打开；
2. 随便找一个空行，打一个空格，再删除空格；
3. 保存文件，关闭文件。

这时候一般来说，Windows安全中心就不会再阻止了。

## 十一、完成检查

完成以下项目后，就可以正常使用了：

- [ ] Miniconda 已安装，`conda --version` 能输出版本。
- [ ] 已创建 `aipartner` 环境。
- [ ] PyTorch 和项目依赖安装成功。
- [ ] 记忆模型已下载到正确目录。
- [ ] `.env` 的三项大模型配置已填写，接口测试能返回文字。
- [ ] 双击 `start_aipartner.bat` 后能打开网页，并完成一次文本聊天。
- [ ] 如需图片识别：三项视觉模型配置已填写，聊天输入框能选择图片并得到正常回复。
- [ ] 如需配音：CUDA 可用，语音模型和角色素材齐全，已实际听到角色配音。

角色制作不属于首次环境安装的必需步骤。先使用自带角色确认程序可用，再阅读项目 `使用指南` 文件夹中的《如何创建新角色.md》，制作自己的角色。
