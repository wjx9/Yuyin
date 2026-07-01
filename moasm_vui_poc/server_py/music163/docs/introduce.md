8.8 网易云音乐

- 官方文档
skill：
	https://www.npmjs.com/package/@music163/ncm-cli
	https://github.com/NetEase/skills
	https://github.com/NetEase/skills/blob/master/netease-music-cli/SKILL.md

- 调用说明
	1. 在网易云音乐开放平台（https://music.163.com/st/developer/），通过个人/企业（需完成实名认证）登录，可获得技能调用的鉴权凭证（appid和privateKey）；
	2. 在本地agent中集成skill，并使用个人id和私钥作为身份凭证；
	3. 在agent中通过“我想听方大同的歌”等指令可触发，用户授权流程在skill交互过程中完成，返回二维码或链接进行OAuth登录，核心流程为授权登录-搜歌点歌-播放控制，在线播放目前支持mac和windows，依赖本地的mpv播放器组件；
	4. 个人使用观感，所谓的在线点播依赖本地环境，本地mpv自动安装和唤起流程繁琐，且容易出现失败，对于大众用户使用门槛较高，噱头大于实际体验；

- 接入提示:
  从本质上网易云音乐skill是2个能力的杂合:  1, 告诉(注册skill)到大模型, 当大模型知道自己是可以搜索和播放音乐的; 2, 实际执行搜索,播放音乐;
  对于demo而言, 在pc上将其集成到基于大模型的语音助手 这很容易. 但是对于实际商用client-server架构的语音助手来说, 当前skill不可能注册到client(android/ios). 
  其能力1+2看上去需要分两端步数: part1放在云端,而part2在客户端. part2有两种实现: 1, 跳转网易云音乐, 2,嵌入语音助手客户端. 
  先尝试实现纯pc步数 跑通流程. 然后再看cs架构,跳转网易云音乐app,最后是嵌入我们自己的语音助手客户端. 
  
- 目前我们却道到的一些约束(但不一定正确), 并按照这个做规划的:
 网易云 skills 平台纯 CLI(PC/mpv)，无任何移动端 SDK，所以 手机端语音助手app(client_flutter) 内嵌入播放走不通, 只能跳转网易云音乐app/web.

---

- 关键澄清：**存在两套互不相通的"播放目标"，别混为一谈**

  代码里网易云能力其实是全套的（见 `music163/service.py`）：搜歌+点歌(`music_play`)、以及暂停/继续/停止/上一首/下一首/音量(`music_control`)。但要分清这些控制作用在**谁身上**：

  ```
  播放目标 A ── 服务端本机 mpv
     · music_play  → ncm-cli play  → 服务端那台 PC 的 mpv 出声
     · music_control(暂停/切歌/音量) → ncm-cli pause/next/... → 只作用于这路 mpv

  播放目标 B ── 手机上的网易云 app
     · music_play  → 服务端在 /chat 的 data 里回传 orpheus:// 深链
                   → 手机拉起网易云 app，歌在**手机上**放
     · 想控制它？没有能力 —— 见下
  ```

  由此推出一个必须点破的矛盾：`music_control` 控的是**播放目标 A（服务端 mpv）**，而手机端听到的声音来自**播放目标 B（手机上的网易云 app）**。手机用户说"暂停"，请求打到服务端，`ncm-cli pause` 停的是 PC 上那路 mpv，手机 app 纹丝不动。**在手机链路里，`music_control` 是悬空的、控制不到用户实际在听的那路声音。**

- 为什么深链模式下"控制"注定走不通（不是没实现，是从根上堵死）
  `orpheus://song/{id}` 是 fire-and-forget 的"打开/播放某目标"启动意图，**不是控制通道**——它能拉起播放，但没有 暂停/切歌/调音量 对应的 scheme，更没法反过来操控一个已在前台运行的第三方 app。要真正控制手机上的网易云 app，只有：① 网易云移动端 SDK（平台没有）；② `MediaController`/媒体会话（那是网易云 app 自己的 session，助手要接管得申请 `NotificationListener` 去读它的通知媒体控件，属 hack、随版本易碎）；③ 系统媒体键（同样跨不过 app 边界）。当前约束下全不可行。

- 因此的工程处置：`music_control` 标记为 **PC-only 能力**，按发起端(platform)屏蔽
  - 机制：请求带 `platform` 字段（`pc` / `mobile`），`Handler.pc_only=True` 的能力对 `mobile` 隐藏——既不进 `/health` 能力清单，分类器也不会路由到它（`Dispatcher` 按 platform 过滤可见能力，见 `routing/dispatcher.py`）。
  - 各端表现：

    | 客户端 | platform | 能否看到/用到 `music_control` | 说明 |
    |--------|----------|------|------|
    | `chat_app.py`(进程内 dispatcher) | pc(默认) | ✅ | 就在 PC 本机，控的就是本机 mpv，天然成立 |
    | `client_py`(HTTP) | pc(默认，不带字段) | ✅ | PC 侧客户端，同上 |
    | `client_flutter`(HTTP) | **mobile**(显式声明) | ❌ | 播放在手机上，控制不到，故从能力清单与路由里彻底移除，避免"看得到却没用"的误导 |

  - 手机端仍保留 `music_play`（点歌）：它就是给手机用深链拉起网易云 app 的正路。手机上要暂停/切歌，只能引导用户去网易云 app 自身界面/通知栏操作，助手这层给不了。
 