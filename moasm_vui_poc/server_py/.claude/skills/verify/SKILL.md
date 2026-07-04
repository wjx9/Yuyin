---
name: verify
description: 端到端验证 server_py 路由/技能改动：起 HTTP 服务，打 /chat，看 debug 日志里的意图与槽位。
---

# server_py 验证手册

## 起服务（cwd = server_py，.env 自动加载）

```powershell
$env:PYTHONIOENCODING='utf-8'; python serve.py --port 8010 --debug *> "$env:TEMP\vui_serve.log"
# 后台运行；就绪判据：Test-NetConnection 127.0.0.1 -Port 8010
```

## 打 /chat

```powershell
$body = @{query="来3条美国的新闻"; session_id="verify-1"; location="113.93,22.53"} | ConvertTo-Json
Invoke-RestMethod -Uri http://127.0.0.1:8010/chat -Method Post `
  -Body ([System.Text.Encoding]::UTF8.GetBytes($body)) -ContentType 'application/json'
# 注意：中文必须走 UTF8 字节体，直接传 $body 字符串会乱码
```

响应：`{text, intent, session_id, data?}`。platform 字段可传 "mobile" 验证 PC-only 能力屏蔽。

## 看路由决策（核心证据）

```powershell
Get-Content "$env:TEMP\vui_serve.log" -Encoding UTF8 |
  Select-String 'Gemini 分类|路由 ->|新闻搜索:'
# [DEBUG] routing.classifier: Gemini 分类: intent='tencent_news_search' slots={'keyword': '美国', 'limit': 3} ...
# [INFO] routing.dispatcher: 路由 -> 技能 'tencent_news_search' (...)，槽位 {...}，分类耗时 NNNms
```

## 常用验证语料

| query | 期望 intent | 期望槽位 |
|---|---|---|
| 来3条美国的新闻 | tencent_news_search | keyword=美国, limit=3 |
| 有什么大新闻 | tencent_hot_news | （空） |
| 深圳明天下雨吗 | tencent_weather | city=深圳 |
| 附近的咖啡（带 location） | amap | keywords=咖啡 |
| 放一首晴天 | music_play | （未登录时回登录提示，路由仍可验证） |
| 今天心情不错聊聊天吧 | chitchat | （空） |

## 坑

- 各能力按 env key 有无注册（TENCENT_NEWS_API_KEY / AMAP_KEY / MUSIC163_*），缺 key 时对应 intent 不存在。
- 首个请求含 TLS 预热，分类耗时偏高（~3s）；看稳态取第 2 个请求之后（~0.9–1.2s）。
- 收尾记得停进程：按命令行匹配 `serve.py --port 8010` 的 python 进程 Stop-Process。
