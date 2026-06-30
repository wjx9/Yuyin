# moasm_vui · 语音助手 Flutter 客户端（client-server 客户端）

> moasm_vui 是"把第三方能力接入下一代语音助手(VUI)"的 PoC；TripNow 只是接入的第一个第三方能力，并非项目名。

本目录是这套**多能力分流语音助手的手机端**：把 `server_py/chat_app.py` 的体验从"PC 终端打字"搬到"手机语音"，
业务"大脑"仍在服务端（`server_py/serve.py`），客户端只负责**采集语音 → 发请求 → 渲染/朗读回复**。

一条链路（与 `client_py` 等价，多了端侧语音 I/O）：

```
按麦克风 → 端侧 ASR(speech_to_text) 转文字 → POST /chat 给 serve.py
        → 收到 { text, intent } → 上屏气泡 + TTS(flutter_tts) 朗读
```

- applicationId / bundle id：`com.rayneo.moasm.vui`（Dart 包名 `moasm_vui`，包名不能含点，故用下划线）
- 目标平台：Android / iOS

## 一、先把服务端跑起来（PC）

在工程根目录：

```bash
python server_py/serve.py            # 监听 0.0.0.0:8000，同一 WiFi 下手机可访问
```

启动后控制台会打印**局域网地址**，例如 `http://192.168.1.5:8000` —— 手机要填的就是它。

## 二、跑客户端（用 FVM，工具链与 venusflutterapp 对齐）

本工程用 [FVM](https://fvm.app) 把 Flutter 锁定在 **3.41.9**（见 `.fvmrc`），与 `d:/code/rayneo/venusflutterapp` 一致。
首次在一台新机器上：

```bash
cd client_flutter
fvm install                # 按 .fvmrc 装好 3.41.9（已装则秒过）
fvm flutter pub get
fvm flutter test           # 跑单元测试（纯 Dart，无需设备/模拟器）
fvm flutter run            # 选中已连接的手机/模拟器
```

> 没装 fvm：`dart pub global activate fvm`。也可不经 fvm 直接用本机 Flutter 3.41.9：把上面命令的 `fvm flutter` 换成 `flutter` 即可。

### 工具链版本（与 venusflutterapp 对齐）

| 组件 | 版本 | 来源 |
|---|---|---|
| Flutter | 3.41.9 | `.fvmrc` |
| Dart | 3.11.5 | 随 Flutter 3.41.9 |
| Gradle | 8.14 | `android/gradle/wrapper/gradle-wrapper.properties` |
| Android Gradle Plugin | 8.11.1 | `android/settings.gradle.kts` |
| Kotlin | 2.2.20 | `android/settings.gradle.kts` |
| Java（compile/jvmTarget） | 17 | `android/app/build.gradle.kts` |

这些值是 Flutter 3.41.9 脚手架的默认，恰好与 venus 一致，未额外改动；差异仅 `minSdk`（本客户端取 24 以兼容更多手机，venus 因 AR 设备取 29）。

首次启动进入「设置」（右上角齿轮），填入**服务端地址**：

| 设备 | 填什么 |
|---|---|
| 真机（同一 WiFi） | serve.py 打印的局域网地址，如 `http://192.168.1.5:8000` |
| Android 模拟器 | `http://10.0.2.2:8000`（10.0.2.2 = 宿主机 localhost，已是默认值） |
| iOS 模拟器 | `http://127.0.0.1:8000` |

服务端若用 `--token` 开了鉴权，则在设置里同时填 **Bearer 鉴权密钥**。

## 三、用法

- **点麦克风**说话 → 自动识别 → 发送 → 语音播报回复；再点一次可手动停止聆听。
- 也可**直接打字**（底部输入框），等价于语音，便于无麦克风环境调试。
- 顶栏 ✨ 查看服务端**已启用能力**；🗑 清空对话；⚙ 设置（含「新建会话」可重置服务端多轮上下文）。

测试话术（对应 `server_py/run_cases.py` 的用例）：
> “深圳到北京怎么最舒服？” / “附近好吃的” / “看下深圳天气” / “看下今天的新闻top5” / “1+1等于几？”（再问“我刚才问你什么来着？”验证多轮记忆）

## 四、权限说明

- **Android**：`RECORD_AUDIO`（语音识别）、`INTERNET`；并开了 `usesCleartextTraffic`（局域网是明文 HTTP）。
- **iOS**：`NSMicrophoneUsageDescription` / `NSSpeechRecognitionUsageDescription`（语音）、
  `NSLocalNetworkUsageDescription`（iOS 14+ 访问局域网）、ATS 允许明文（试用期；上线走 HTTPS 后可收紧）。

> 注：iOS 真机需自有开发者签名；Android 直接 `flutter run` 即可。

## 五、代码结构（刻意与 server_py/server/ 分层对称，便于对照）

```
lib/
  main.dart                      入口：load 配置 + 初始化服务 + provider 注入
  src/
    config/app_config.dart       不可变配置值对象（server/token/location/session_id）
    data/
      models.dart                ChatTurn / ChatReply / HealthInfo
      chat_api.dart              唯一懂 HTTP 契约的地方（health / chat）
    services/
      speech_service.dart        端侧语音识别(ASR) 封装（speech_to_text）
      tts_service.dart           文字转语音(TTS) 封装（flutter_tts）
    state/
      settings_controller.dart   ChangeNotifier：持久化配置（shared_preferences）
      chat_controller.dart       ChangeNotifier：串起 ASR→/chat→TTS 的协调者
    ui/
      chat_page.dart             主界面：消息列表 + 听写草稿 + 输入 + 麦克风
      settings_page.dart         服务端地址 / 鉴权 / 位置 / 新建会话
      widgets/                   message_bubble.dart / mic_button.dart
```

Android 视角的类比：`ChangeNotifier` ≈ `ViewModel`+`LiveData`，`provider` ≈ `ViewModelProvider`/DI，
`ChatApi`/各 service ≈ Repository 层，UI 只监听状态重绘。换传输/换 UI 只动对应一层，互不牵连。
