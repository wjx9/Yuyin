# 高德 AmapLinkClient 集成指南

> 本文档说明如何在雷鸟语音助手 Android 端集成高德 AmapLinkClient SDK，实现真正的导航控制。

## 一、当前实现状态

### 1.1 双模式自动切换

手机端已实现**双模式自动切换**：

| 模式 | 实现方式 | 支持指令 | 依赖 |
|------|---------|---------|------|
| **AmapLink 模式** | 高德 AmapLinkClient SDK（IPC 通信） | cmd=1~7 全部指令 | 需集成 SDK + API Key |
| **Intent 模式**（默认） | Android Intent 拉起高德地图 | cmd=4（开始导航） | 仅需安装高德地图 App |

`NavigationExecutor.create()` 会通过反射自动检测 AmapLinkClient SDK 是否可用：
- SDK 已集成 → 使用 `AmapLinkNavigationExecutor`
- SDK 未集成 → 回退到 `IntentNavigationExecutor`

### 1.2 Intent 模式（当前可用，无需 SDK）

**已修复的关键问题**：AndroidManifest.xml 的 `<queries>` 中缺少 `androidamap` scheme 和 `com.autonavi.minimap` 包名，导致 Android 11+ 无法拉起高德地图。**现已修复。**

Intent 模式支持：
- ✅ cmd=4（设置终点/开始导航）：拉起高德地图 App 自动开始导航
- ❌ cmd=2（停止导航）：Intent 方式无法远程停止，需用户手动停止
- ❌ cmd=1/3/5/6/7：Intent 方式不支持

## 二、AmapLinkClient SDK 集成步骤

### 2.1 获取 SDK

1. 访问高德开放平台：https://lbs.amap.com/
2. 申请「Amap Link Service」SDK（联系高德商务获取 AAR 包）
3. 获取 API Key（在高德开放平台注册应用，包名 `com.rayneo.moasm.vui`）

### 2.2 添加依赖

1. 在 `android/app/` 下创建 `libs/` 目录
2. 将 `amap-link-client.aar` 放入 `android/app/libs/`
3. 修改 `android/app/build.gradle.kts`，取消依赖注释：

```kotlin
dependencies {
    implementation(files("libs/amap-link-client.aar"))
}
```

### 2.3 配置 API Key

1. 修改 `AmapLinkNavigationExecutor.kt` 中的 API_KEY：

```kotlin
// TODO: 集成 AmapLinkClient SDK 后，替换为你的高德 API Key
private const val API_KEY = "你的高德APIKey"
```

2. 修改 `AndroidManifest.xml` 中 amapuri intent-filter 的 host：

```xml
<intent-filter>
    <action android:name="android.intent.action.VIEW" />
    <category android:name="android.intent.category.DEFAULT" />
    <category android:name="android.intent.category.BROWSABLE" />
    <data
        android:scheme="amapuri"
        android:host="你的高德APIKey" />
</intent-filter>
```

### 2.4 验证配置

使用 adb 命令验证 URL Scheme 配置：

```bash
adb shell am start \
  -a android.intent.action.VIEW \
  -c android.intent.category.BROWSABLE \
  -c android.intent.category.DEFAULT \
  -f 0x10000000 \
  -d "amapuri://你的高德APIKey" \
  com.rayneo.moasm.vui
```

## 三、代码结构

### 3.1 文件清单

| 文件 | 说明 |
|------|------|
| `navigation/NavigationExecutor.kt` | 导航执行器接口 + 工厂方法（自动选择 AmapLink/Intent） |
| `navigation/IntentNavigationExecutor.kt` | Intent 方式实现（无需 SDK，默认回退） |
| `navigation/AmapLinkNavigationExecutor.kt` | AmapLinkClient 实现（反射调用，SDK 可用时自动启用） |
| `MainActivity.kt` | 注册 Platform Channel，调用 NavigationExecutor |

### 3.2 调用链路

```
Flutter 端 (chat_controller.dart)
  │
  ├─ 解析服务端返回的 data.nav_command
  └─ MethodChannel.invokeMethod("executeNavCommand", {cmd, requestId, data, amapExecuteJson})
        │
        ▼
Android 端 (MainActivity.kt)
  │
  ├─ NavigationExecutor.create(context)  // 反射检测 SDK，自动选择 AmapLink/Intent
  └─ executor.execute(cmd, requestId, data, amapExecuteJson)
        │
        ├─ AmapLink 模式：amapLinkClient.execute(amapExecuteJson)  // IPC 控制高德地图
        └─ Intent 模式：startActivity(androidamap://navi?...)      // 拉起高德地图
```

### 3.3 服务端下发的 nav_command 格式

```json
{
  "cmd": 4,
  "requestId": 1788233461020,
  "data": {
    "name": "大新地铁站",
    "lon": 113.915072,
    "lat": 22.532232,
    "poiid": "BV10249973"
  },
  "amap_execute_json": "{\"cmd\":4,\"requestId\":1788233461020,\"data\":{...}}"
}
```

手机端优先使用 `amap_execute_json`（服务端已构建好的完整 JSON），直接传给 `AmapLinkClient.execute()`。

## 四、测试步骤

### 4.1 Intent 模式测试（当前可用）

1. **重新构建 App**：
   ```bash
   cd client_flutter
   flutter run
   ```

2. **确保手机安装高德地图 App**

3. **测试导航流程**：
   - 说"导航到肯德基" → 应返回 POI 列表
   - 说"第一个" → 应自动拉起高德地图并开始导航
   - 说"结束导航" → 应提示停止（Intent 模式需手动在高德地图中停止）

4. **查看日志**：
   ```bash
   adb logcat | grep -E "NavChannel|NavExecutor|IntentNavExecutor"
   ```

### 4.2 AmapLink 模式测试（集成 SDK 后）

1. 按「二、集成步骤」完成 SDK 集成
2. 重新构建 App
3. 测试导航流程（同上）
4. 验证 cmd=2（结束导航）能否远程停止高德地图
5. 查看日志：
   ```bash
   adb logcat | grep -E "NavChannel|NavExecutor|AmapLinkNavExecutor"
   ```

## 五、指令码对照表

| cmd | 指令名称 | Intent 模式 | AmapLink 模式 | data 参数 |
|-----|---------|------------|--------------|-----------|
| 1 | 切换路线 | ❌ | ✅ | `{"pathID": "123"}` |
| 2 | 停止导航 | ❌ | ✅ | 无 |
| 3 | 添加途经点 | ❌ | ✅ | `{"lon","lat","name","poiid"}` |
| 4 | 设置/变更终点 | ✅ | ✅ | `{"lon","lat","name","poiid"}` |
| 5 | 查询导航信息 | ❌ | ✅ | 无 |
| 6 | 切换播报方式 | ❌ | ✅ | `{"mode": 2}` 或 `{"value": "1"}` |
| 7 | 刷新导航信息 | ❌ | ✅ | 无 |

## 六、常见问题

### Q1: Intent 模式下拉不起高德地图？

**原因**：Android 11+ 包可见性限制，需要在 AndroidManifest.xml 的 `<queries>` 中声明。

**解决**：确认 AndroidManifest.xml 中已添加：
```xml
<queries>
    <intent>
        <action android:name="android.intent.action.VIEW"/>
        <data android:scheme="androidamap"/>
    </intent>
    <package android:name="com.autonavi.minimap" />
</queries>
```

### Q2: AmapLinkClient 连接失败？

**排查步骤**：
1. 确认 API Key 正确（包名与高德开放平台注册一致）
2. 确认手机已安装高德地图 App 且版本支持 Amap Link Service
3. 查看错误码：
   - 100: 高德地图服务未安装或版本过低
   - 204: API Key 无效
   - 205: 权限不足
   - 206: 认证失败

### Q3: 如何确认当前使用的是哪种模式？

查看日志：
- `使用 AmapLinkNavigationExecutor（SDK 已集成）` → AmapLink 模式
- `AmapLinkClient SDK 不可用，回退到 IntentNavigationExecutor` → Intent 模式

### Q4: 导航数据回调如何处理？

AmapLinkClient 支持 `registerDataListener()` 接收导航数据回调（转向信息、距离、速度等）。当前版本未实现回调处理，后续可在 `AmapLinkNavigationExecutor` 中添加 `registerDataListener`，将导航数据通过 Platform Channel 回传给 Flutter，再推送到眼镜端 HUD。

## 七、后续优化方向

1. **导航数据回调**：实现 `AmapLinkDataListener`，将导航实时数据（转向、距离、速度）推送到眼镜端 HUD
2. **导航状态同步**：将高德地图的导航状态（开始/结束/偏航）同步到服务端导航状态机
3. **离线地图**：集成高德离线地图 SDK，支持无网络环境下的导航
4. **多模式导航**：支持驾车/步行/骑行/公交等多种导航模式切换
