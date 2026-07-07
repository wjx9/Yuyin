# myChatGPT

`myChatGPT` 是一个放在当前仓库 `myChatGPT/` 路径下的 Python 桌面语音助手 App。目标是做一个类似网页版 ChatGPT、但界面布局接近 Claude Desktop 的本地 GUI：左侧保存历史对话，中间显示富文本聊天内容，底部支持多行输入、附件和截图粘贴，顶部可以配置云端大模型 Key 和工作文件夹。

这个项目不绑定某一家模型厂商。你可以配置 OpenAI、aitogit_openai、OpenAI-compatible、Gemini 或 Claude 的 Key；程序会把文本、附件、截图、本地文件上下文和多轮历史发送给对应云端模型。

## 当前功能

- GUI 桌面窗口，可自由缩放。
- 左侧历史会话列表，历史会话持久化保存，之后可以从任意历史对话继续聊。
- 顶部模型设置：`provider`、`model`、`base_url`、`api_key`，以及联网搜索开关。
- 支持 OpenAI Chat Completions、aitogit_openai Responses API、OpenAI-compatible `/chat/completions`、Gemini REST API、Anthropic Claude Messages API。
- 底部多行文本输入：`Enter` 发送，`Shift+Enter` 换行。
- 支持添加任意附件。文本类文件和 PDF 会被读取为上下文；图片会按多模态图片发送给支持视觉的模型。
- 支持截图粘贴：剪贴板里有截图时，在输入框按 `Ctrl+V` 会把截图加入待发送附件，发送时和文本一起提交。
- Markdown 富文本显示：标题、列表、引用、代码块、语法高亮、链接样式、`==高亮==`、Mermaid 代码块文本展示。
- 顶部可设置“工作文件夹”。启用后，用户消息中的本地路径会被解析并读取，作为上下文发给模型；相对路径会按工作文件夹解析。
- 代理模式：模型可以通过约定的 `tool_calls` JSON 块请求本地工具读取目录、读文件、搜索文本。勾选“允许写入/命令”后，还可以写文件和执行命令。
- 语音能力：`听写` 按钮使用 Windows `System.Speech` 做一次性语音识别；“自动朗读”使用 Windows SAPI 朗读助手回复。

## 项目结构

```text
myChatGPT/
  main.py                    # 程序入口
  requirements.txt           # pip 依赖
  run.ps1                    # 使用 .venv 运行
  build_exe.ps1              # 使用 PyInstaller 打包 exe
  README.md                  # 本说明
  mychatgpt/
    app.py                   # Tkinter GUI
    config.py                # 配置读写
    storage.py               # 会话和附件持久化
    llm_client.py            # OpenAI/Gemini/Claude REST 适配
    local_context.py         # 本地文件读取和工作目录工具
    markdown_view.py         # Markdown 富文本渲染
    voice.py                 # Windows 语音识别和朗读
```

运行后，配置和历史会话默认保存到：

```text
%APPDATA%\myChatGPT
```

## 直接用 Python 运行

推荐使用项目自己的 venv：

```powershell
cd D:\code\moasm_vui_poc\moasm_vui_poc\myChatGPT
.\run.ps1
```

`run.ps1` 会使用：

```text
myChatGPT\.venv\Scripts\python.exe
```

脚本会优先执行：

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

如果当前机器没有可用 pip 包索引，脚本会回退到通过 `.venv` 复用系统 Python 已安装依赖，并在启动前检查 `Pillow`、`Pygments`、`requests`、`PyMuPDF` 是否可导入。

也可以手动运行：

```powershell
cd D:\code\moasm_vui_poc\moasm_vui_poc\myChatGPT
py -3 -m venv --system-site-packages .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe main.py
```

如果你的 Python 环境创建 venv 时 `ensurepip` 被系统临时目录权限拦截，可以使用无 pip venv，并复用系统 site-packages：

```powershell
py -3 -m venv --without-pip --system-site-packages .venv
.\.venv\Scripts\python.exe main.py
```

## 第一次使用

1. 启动程序。
2. 顶部选择 `Provider`：`openai`、`aitogit_openai`、`openai-compatible`、`gemini` 或 `claude`。
3. 填写 `API Key`。
4. 按需要修改 `Model` 和 `Base URL`。
5. 点击“保存设置”。
6. 在底部输入问题，按 `Enter` 发送。

常用默认值：

```text
openai             model: gpt-4.1-mini              base_url: https://api.openai.com/v1
aitogit_openai     model: gpt-5.5                   base_url: https://api.aitogit.cc
openai-compatible  model: 自行填写兼容服务模型名       base_url: 你的兼容服务 /v1 地址
gemini             model: gemini-2.5-flash           base_url: https://generativelanguage.googleapis.com/v1beta
claude             model: claude-3-5-sonnet-latest   base_url: https://api.anthropic.com
```

API Key 会保存到本机 `%APPDATA%\myChatGPT\config.json`。这是本地明文配置文件，请不要把它提交到代码仓库或发给别人。

如果 API Key 输入框留空，程序会自动找 key。查找顺序是：进程环境变量、Windows 用户/系统环境变量注册表、当前目录或父目录 `.env` 文件。`aitogit_openai` 会依次尝试：`AITOGIT_OPENAI_API_KEY`、`AITOGIT_API_KEY`、`OPENAI_API_KEY`、`openai_api_key`。

## aitogit_openai 配置

选择 `aitogit_openai` 后会使用类似下面的配置：

```text
model_provider = "OpenAI"
model = "gpt-5.5"
base_url = "https://api.aitogit.cc"
wire_api = "responses"
requires_openai_auth = true
disable_response_storage = true
model_reasoning_effort = "xhigh"
```

程序实际请求为 `POST https://api.aitogit.cc/v1/responses`，认证头为 `Authorization: Bearer <key>`，并设置 `store: false`、`reasoning.effort: xhigh`。如果顶部勾选“联网搜索”，请求会附加 `tools: [{"type":"web_search"}]` 和 `tool_choice: "auto"`，让模型在股价、新闻、汇率、版本变化等问题上自行决定是否联网。

## 聊天和附件用法

- 多行输入：`Shift+Enter` 换行。
- 发送：`Enter`。
- 添加文件：点底部“附件”。
- 粘贴截图：先截图复制到剪贴板，然后在输入框按 `Ctrl+V`。
- 只发截图也可以：输入框可以为空，只要待发送附件里有截图或文件即可发送。
- 文本、代码、Markdown、JSON、YAML、CSV、日志等文本类文件会被读取为上下文。
- PDF 会用 PyMuPDF 提取文本。
- 图片附件会以多模态图片形式发送；请确认你选择的模型支持图片输入。

## 工作文件夹用法

顶部“工作文件夹”用于给某个对话绑定本地项目目录。设置后：

- 勾选“使用工作文件夹”时，聊天会带上当前工作目录信息。
- 你在消息中写本地路径，例如 `README.md`、`src/main.py`、`D:\project\file.txt`，程序会尝试读取并附加到上下文。
- 相对路径会按当前工作文件夹解析。
- 历史对话会保存它当时使用的工作文件夹，切回对话时会恢复。

示例问题：

```text
帮我总结 README.md 的内容
```

```text
请阅读 src/app.py，指出主要类和调用流程
```

## 代理模式用法

勾选“代理模式”后，系统提示会告诉模型可以请求本地工具。当前支持：

```text
list_dir(path)                 列目录
read_file(path)                读文件
search_text(pattern, path)     搜索文本
write_file(path, content)      写文件，需要勾选“允许写入/命令”
run_command(command, timeout)  执行命令，需要勾选“允许写入/命令”
```

默认情况下，未勾选“允许写入/命令”时，只能读目录、读文件和搜索文本。这样更适合代码阅读、总结、定位问题。

如果你要让它修改代码或运行测试，再勾选“允许写入/命令”。该能力会真实操作工作文件夹里的文件和命令，请只在你信任当前任务和模型输出时开启。

## 打包 exe

使用项目 venv 打包：

```powershell
cd D:\code\moasm_vui_poc\moasm_vui_poc\myChatGPT
.\build_exe.ps1
```

打包脚本会：

1. 准备 `myChatGPT\.venv`。
2. 安装或检查依赖。
3. 调用 PyInstaller。
4. 输出 Windows GUI 程序。

输出文件位于脚本打印的时间戳目录，例如：

```text
D:\code\moasm_vui_poc\moasm_vui_poc\myChatGPT\dist_20260706-213000\myChatGPT\myChatGPT.exe
```

使用时间戳目录是为了避开当前 Windows 环境中 Python 无法删除旧构建文件的问题。

运行 exe 后，配置和历史仍然保存在 `%APPDATA%\myChatGPT`。

## 依赖

```text
Pillow       读取剪贴板截图、保存图片附件
Pygments     代码块语法高亮
requests     调用云端模型 REST API
PyMuPDF      PDF 文本提取
PyInstaller  打包 exe
```

GUI 使用 Python 标准库 `tkinter`，因此不需要 PySide6/PyQt6。

## 注意事项

- OpenAI-compatible 服务必须兼容 `/chat/completions`。
- 图片输入取决于模型能力；不支持视觉的模型会返回 API 错误。
- Mermaid 当前以代码块形式美化展示，不内置浏览器渲染图形。
- 语音识别和朗读依赖 Windows `System.Speech`，不同系统语言环境下识别效果会不同。
- 本地文件读取和代理工具会访问你的工作文件夹；写入和命令执行需要单独勾选“允许写入/命令”。


## Windows 打包说明

当前开发环境不允许 PyInstaller 对 exe 执行 Windows resource update。因此打包脚本使用 PyInstaller console bootloader，并在 `main.py` 启动时立即隐藏控制台窗口，最终用户看到的是 GUI 应用。

如果看到旧包弹出“无法定位序数 380 / COMCTL32.dll”之类错误，请不要使用旧的 `dist_20260706-215356` 目录，重新执行 `build_exe.ps1`，或使用当前已验证的：

```text
D:\code\moasm_vui_poc\moasm_vui_poc\myChatGPT\dist_20260706-215911\myChatGPT\myChatGPT.exe
```




