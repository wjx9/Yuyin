# 高德 AmapLinkClient Android 集成指南

> **版本**：1.0  
> **日期**：2026-09-01  
> **适用**：雷鸟语音助手 Android 手机端  
> **功能**：通过 AmapLinkClient 与高德地图 App IPC 通信，执行真正的导航

---

## 一、架构总览

```
用户语音 → 手机端ASR → POST /chat → 服务端导航对话引擎
                                              ↓
                          返回 ChatResponse { text, data.nav_command }
                                              ↓
                          手机端解析 data.nav_command.amap_execute_json
                                              ↓
                          amapLinkClient.execute(jsonStr)  ← IPC
                                              ↓
                          高德地图 App 执行真正导航（启动/停止/切换路线）
                                              ↓
                          导航数据回调 → AmapLinkDataListener → 推送眼镜HUD
```

**职责划分**：
- **服务端**：对话编排、意图识别、POI搜索、多轮状态管理、生成 NavCommand
- **手机端**：AmapLinkClient 连接管理、执行 NavCommand、接收导航数据回调、推送眼镜
- **高德地图 App**：真正的导航执行（路线规划、语音播报、地图渲染）

---

## 二、环境配置

### 2.1 添加依赖

```gradle
// build.gradle (Module level)
dependencies {
    // 高德 AmapLinkClient SDK（需向高德获取 AAR 或 Maven 坐标）
    implementation 'com.amap.api:amap-link-client:1.0.0'
}
```

### 2.2 AndroidManifest.xml 配置

```xml
<!-- 配置接收高德地图回调的 Activity（URL Scheme） -->
<activity
    android:name=".nav.AmapLinkCallbackActivity"
    android:exported="true"
    android:launchMode="singleTask">
    <intent-filter>
        <action android:name="android.intent.action.VIEW" />
        <category android:name="android.intent.category.DEFAULT" />
        <category android:name="android.intent.category.BROWSABLE" />
        <!-- host 必须填写你的高德 API Key -->
        <data
            android:scheme="amapuri"
            android:host="YOUR_AMAP_API_KEY" />
    </intent-filter>
</activity>
```

### 2.3 校验 URL Scheme

```bash
adb shell am start \
  -a android.intent.action.VIEW \
  -c android.intent.category.BROWSABLE \
  -c android.intent.category.DEFAULT \
  -f 0x10000000 \
  -d "amapuri://YOUR_AMAP_API_KEY" \
  com.rayneo.vui
```

---

## 三、核心代码实现

### 3.1 AmapLinkManager（单例，连接管理）

```java
package com.rayneo.vui.nav;

import android.content.Context;
import android.util.Log;

import com.amap.api.link.AmapLinkClient;
import com.amap.api.link.ConnectionListener;
import com.amap.api.link.AmapLinkDataListener;

import org.json.JSONObject;

/**
 * 高德 AmapLinkClient 管理器（单例）。
 *
 * 职责：
 * 1. 初始化、连接、断开 AmapLinkClient
 * 2. 执行服务端下发的 NavCommand
 * 3. 注册导航数据回调，推送到眼镜端
 */
public class AmapLinkManager {

    private static final String TAG = "AmapLinkManager";
    private static volatile AmapLinkManager instance;

    private AmapLinkClient client;
    private final Context appContext;
    private final String apiKey;
    private boolean connected = false;
    private NavDataCallback navDataCallback;

    private AmapLinkManager(Context context, String apiKey) {
        this.appContext = context.getApplicationContext();
        this.apiKey = apiKey;
    }

    public static AmapLinkManager getInstance(Context context, String apiKey) {
        if (instance == null) {
            synchronized (AmapLinkManager.class) {
                if (instance == null) {
                    instance = new AmapLinkManager(context, apiKey);
                }
            }
        }
        return instance;
    }

    /**
     * 初始化并连接高德地图服务。
     * 建议在 Application.onCreate() 中调用。
     */
    public void connect() {
        if (client != null && connected) {
            Log.d(TAG, "已连接，跳过");
            return;
        }

        client = new AmapLinkClient(appContext, apiKey);

        // 配置自动重连
        client.setReconnectConfig(true, 5, 2);

        // 设置连接监听器
        client.setConnectionListener(new ConnectionListener() {
            @Override
            public void onConnected() {
                connected = true;
                Log.d(TAG, "高德地图服务连接成功");
                // 连接成功后注册数据监听器
                registerDataListener();
            }

            @Override
            public void onConnectionFailed(int errorCode, String message) {
                connected = false;
                Log.e(TAG, "连接失败: " + errorCode + ", " + message);
            }

            @Override
            public void onDisconnected() {
                connected = false;
                Log.d(TAG, "高德地图服务断开");
            }
        });

        // 发起连接
        boolean started = client.connect();
        Log.d(TAG, "连接请求已发出: " + started);
    }

    /**
     * 注册导航数据监听器。
     * 连接成功后调用，接收高德地图 App 的导航数据回调。
     */
    private void registerDataListener() {
        if (client == null) return;

        boolean ok = client.registerDataListener(new AmapLinkDataListener() {
            @Override
            public void onDataReceived(JSONObject data, int transportType) {
                Log.d(TAG, "收到导航数据: " + data.toString());
                // 解析导航数据，推送到眼镜端 HUD
                if (navDataCallback != null) {
                    navDataCallback.onNavData(data);
                }
            }

            @Override
            public void onError(int errorCode, String errorMessage) {
                Log.e(TAG, "导航数据错误: " + errorCode + ", " + errorMessage);
            }
        });

        Log.d(TAG, "数据监听器注册: " + ok);
    }

    /**
     * 执行导航控制指令。
     *
     * @param amapExecuteJson 服务端 data.nav_command.amap_execute_json 字段的值
     * @return 执行结果 JSON 字符串
     */
    public String executeCommand(String amapExecuteJson) {
        if (client == null || !connected) {
            Log.e(TAG, "未连接高德地图服务，无法执行指令");
            return "{\"status\":\"error\",\"errorCode\":101,\"message\":\"服务未连接\"}";
        }

        try {
            Log.d(TAG, "执行导航指令: " + amapExecuteJson);
            String result = client.execute(amapExecuteJson);
            Log.d(TAG, "执行结果: " + result);
            return result;
        } catch (Exception e) {
            Log.e(TAG, "执行导航指令异常", e);
            return "{\"status\":\"error\",\"message\":\"" + e.getMessage() + "\"}";
        }
    }

    /**
     * 断开连接。
     * 建议在 Application.onTerminate() 或不再需要导航时调用。
     */
    public void disconnect() {
        if (client != null) {
            client.disconnect();
            client = null;
            connected = false;
            Log.d(TAG, "已断开高德地图服务");
        }
    }

    public boolean isConnected() {
        return connected;
    }

    public void setNavDataCallback(NavDataCallback callback) {
        this.navDataCallback = callback;
    }

    /**
     * 导航数据回调接口。
     * 实现此接口将导航数据推送到眼镜端 HUD。
     */
    public interface NavDataCallback {
        void onNavData(JSONObject data);
    }
}
```

### 3.2 NavCommandExecutor（解析服务端响应，执行指令）

```java
package com.rayneo.vui.nav;

import android.util.Log;

import org.json.JSONObject;

/**
 * 导航指令执行器。
 *
 * 解析服务端 ChatResponse.data 中的 nav_command，
 * 调用 AmapLinkManager.executeCommand() 执行真正的导航控制。
 */
public class NavCommandExecutor {

    private static final String TAG = "NavCommandExecutor";

    /**
     * 处理服务端响应，如果包含 nav_command 则执行。
     *
     * @param responseJson 服务端返回的完整 ChatResponse JSON
     * @return true=已执行导航指令, false=无导航指令
     */
    public static boolean handleResponse(String responseJson) {
        try {
            JSONObject response = new JSONObject(responseJson);
            JSONObject data = response.optJSONObject("data");
            if (data == null) return false;

            JSONObject navCommand = data.optJSONObject("nav_command");
            if (navCommand == null) return false;

            // 获取 AmapLinkClient.execute() 可直接传入的 JSON
            String amapExecuteJson = navCommand.optString("amap_execute_json");
            int cmd = navCommand.optInt("cmd");
            String description = navCommand.optString("description");

            Log.d(TAG, "收到导航指令: cmd=" + cmd + ", desc=" + description);
            Log.d(TAG, "amap_execute_json: " + amapExecuteJson);

            if (amapExecuteJson.isEmpty()) {
                Log.w(TAG, "amap_execute_json 为空，跳过");
                return false;
            }

            // 执行指令
            String result = AmapLinkManager.getInstance(null, null)
                    .executeCommand(amapExecuteJson);

            Log.d(TAG, "指令执行结果: " + result);
            return true;

        } catch (Exception e) {
            Log.e(TAG, "处理导航指令异常", e);
            return false;
        }
    }

    /**
     * 便捷方法：直接传入 data JSONObject 处理。
     */
    public static boolean handleData(JSONObject data) {
        if (data == null) return false;
        return handleResponse(data.toString());
    }
}
```

### 3.3 在 Application 中初始化

```java
package com.rayneo.vui;

import android.app.Application;
import android.util.Log;

import com.rayneo.vui.nav.AmapLinkManager;

public class VuiApplication extends Application {

    private static final String TAG = "VuiApplication";
    private static final String AMAP_API_KEY = "YOUR_AMAP_API_KEY"; // 从安全配置读取

    @Override
    public void onCreate() {
        super.onCreate();

        // 初始化高德 AmapLinkClient（异步连接，不阻塞启动）
        try {
            AmapLinkManager.getInstance(this, AMAP_API_KEY).connect();
            Log.d(TAG, "AmapLinkClient 初始化完成");
        } catch (Exception e) {
            Log.e(TAG, "AmapLinkClient 初始化失败", e);
        }

        // 设置导航数据回调，推送到眼镜端 HUD
        AmapLinkManager.getInstance(this, AMAP_API_KEY)
                .setNavDataCallback(data -> {
                    Log.d(TAG, "导航数据回调，推送到眼镜: " + data.toString());
                    // TODO: 通过蓝牙/USB 通道推送到眼镜端 HUD
                    // GlassHudManager.getInstance().pushNavData(data);
                });
    }

    @Override
    public void onTerminate() {
        super.onTerminate();
        AmapLinkManager.getInstance(this, AMAP_API_KEY).disconnect();
    }
}
```

### 3.4 在网络请求回调中集成

```java
// 在你的语音助手网络请求回调中
private void onChatResponse(String responseJson) {
    try {
        JSONObject response = new JSONObject(responseJson);

        // 1. TTS 朗读回复文本
        String text = response.optString("text");
        ttsManager.speak(text);

        // 2. 执行导航控制指令（如果有）
        //    服务端在开始导航/结束导航时会下发 nav_command
        NavCommandExecutor.handleResponse(responseJson);

        // 3. 更新 UI（POI 列表、导航状态等）
        updateUi(response);

    } catch (Exception e) {
        Log.e(TAG, "处理响应异常", e);
    }
}
```

---

## 四、服务端下发的 NavCommand 协议

服务端在 `ChatResponse.data.nav_command` 中下发导航控制指令：

```json
{
  "text": "好的，已为你导航到大新地铁站。",
  "intent": "navigation.navigating",
  "data": {
    "nav_state": "navigating",
    "controller": "amap_agent",
    "is_in_navigation": true,
    "selected_poi": {
      "name": "大新地铁站",
      "address": "深圳市南山区",
      "location": "113.93,22.57"
    },
    "nav_command": {
      "cmd": 4,
      "requestId": 1788232827172,
      "data": {
        "name": "大新地铁站",
        "lon": 113.93,
        "lat": 22.57
      },
      "description": "设置终点并启动导航: 大新地铁站",
      "amap_execute_json": "{\"cmd\":4,\"requestId\":1788232827172,\"data\":{\"name\":\"大新地铁站\",\"lon\":113.93,\"lat\":22.57}}"
    }
  }
}
```

**手机端只需取 `data.nav_command.amap_execute_json`，传给 `AmapLinkClient.execute()` 即可。**

### 指令码对照表

| cmd | 指令 | 触发场景 | data 参数 |
|-----|------|---------|-----------|
| 4 | 设置/变更终点 | 用户选择POI后开始导航 | `lon, lat, name, poiid` |
| 2 | 停止导航 | 用户说"结束导航"/"取消导航" | 无 |
| 1 | 切换路线 | 用户选择备选路线 | `pathID` |
| 6 | 切换播报方式 | 用户说"静音"/"详细播报" | `mode` 或 `value` |

---

## 五、导航数据回调处理

通过 `AmapLinkDataListener.onDataReceived()` 接收高德地图 App 的导航数据：

```java
client.registerDataListener(new AmapLinkDataListener() {
    @Override
    public void onDataReceived(JSONObject data, int transportType) {
        // data 格式示例：
        // {
        //   "datas": "[{\"type\":1,\"data\":\"...\"}]"
        // }
        //
        // type 对应 AMapNaviDataType（导航信息类型）
        // data 是具体的导航数据（转向、距离、车道、路况等）

        try {
            String datasStr = data.optString("datas");
            JSONArray datas = new JSONArray(datasStr);

            for (int i = 0; i < datas.length(); i++) {
                JSONObject item = datas.getJSONObject(i);
                int type = item.optInt("type");
                String navData = item.optString("data");

                // 根据 type 解析不同类型的导航数据
                handleNavDataType(type, navData);
            }
        } catch (Exception e) {
            Log.e(TAG, "解析导航数据异常", e);
        }
    }

    @Override
    public void onError(int errorCode, String errorMessage) {
        Log.e(TAG, "导航数据错误: " + errorCode + ", " + errorMessage);
    }
});
```

**推送到眼镜端 HUD**：解析后的导航数据（下一步转向、剩余距离、预计时间等）通过蓝牙/USB 通道推送到眼镜端渲染。

---

## 六、错误处理

### 6.1 连接错误

| 错误码 | 常量 | 处理建议 |
|--------|------|---------|
| 100 | SERVICE_NOT_INSTALLED | 提示用户安装/更新高德地图 App |
| 101 | SERVICE_NOT_CONNECTED | 重试连接，检查高德地图 App 是否在运行 |
| 102 | SERVICE_UNAVAILABLE | 稍后重试 |
| 103 | CONNECTION_RETRIES_EXCEEDED | 提示用户手动打开高德地图 App |

### 6.2 认证错误

| 错误码 | 常量 | 处理建议 |
|--------|------|---------|
| 204 | API_KEY_INVALID | 检查 API Key 配置 |
| 205 | PERMISSION_DENIED | 检查高德开放平台权限配置 |
| 206 | AUTHENTICATION_FAILED | 重新发起授权 |

### 6.3 执行结果检查

```java
String result = client.execute(amapExecuteJson);
JSONObject resultJson = new JSONObject(result);
if ("error".equals(resultJson.optString("status"))) {
    int errorCode = resultJson.optInt("errorCode");
    String message = resultJson.optString("message");
    Log.e(TAG, "导航指令执行失败: " + errorCode + ", " + message);
    // 根据错误码处理：提示用户、重试、降级等
}
```

---

## 七、最佳实践

1. **Application 初始化**：在 `Application.onCreate()` 中调用 `AmapLinkManager.connect()`，异步连接不阻塞启动
2. **自动重连**：配置 `setReconnectConfig(true, 5, 2)`，网络波动时自动恢复
3. **指令幂等**：服务端生成的 `requestId` 基于时间戳，手机端可用于去重和回调关联
4. **导航状态同步**：服务端维护本地导航状态，手机端执行结果可通过后续请求回传修正
5. **API Key 安全**：不要硬编码在代码中，通过服务端下发或加密存储
6. **生命周期管理**：在 `Application.onTerminate()` 中调用 `disconnect()` 释放资源
7. **眼镜推送**：导航数据回调中解析关键信息（转向、距离、时间），精简后推送到眼镜 HUD

---

## 八、验证清单

- [ ] AmapLinkClient 初始化成功，`onConnected()` 回调触发
- [ ] 服务端下发 `cmd=4` 指令，高德地图 App 自动开始导航
- [ ] 服务端下发 `cmd=2` 指令，高德地图 App 结束导航
- [ ] 导航数据回调 `onDataReceived()` 能收到导航信息
- [ ] 导航数据能推送到眼镜端 HUD 显示
- [ ] 断开高德地图 App 后，自动重连机制生效
- [ ] 未安装高德地图 App 时，有友好的错误提示
