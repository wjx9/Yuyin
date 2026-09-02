package com.rayneo.moasm_vui.navigation

import android.content.Context
import android.util.Log
import java.lang.reflect.Method

/**
 * 高德 AmapLinkClient 导航执行器：通过反射调用高德 AmapLinkClient SDK。
 *
 * 使用反射的原因：
 * - 无需集成 SDK 也能编译（SDK 不可用时自动回退到 Intent）
 * - 用户集成 AmapLinkClient SDK 后，反射自动找到类并启用
 * - NavigationExecutor.create() 会通过反射检测此类是否可用
 *
 * 集成 AmapLinkClient SDK 步骤：
 * 1. 从高德开放平台获取 AmapLinkClient AAR 包
 * 2. 将 AAR 放入 android/app/libs/ 目录
 * 3. 在 build.gradle.kts 中添加：
 *    implementation(files("libs/amap-link-client.aar"))
 * 4. 在 AndroidManifest.xml 中将 amapuri intent-filter 的 host 替换为你的 API Key
 * 5. 在下方 API_KEY 常量中填入你的高德 API Key
 *
 * 支持的指令（完整 AmapLinkClient 协议）：
 * - cmd=1 切换路线
 * - cmd=2 停止导航
 * - cmd=3 添加途经点
 * - cmd=4 设置/变更终点（开始导航）
 * - cmd=5 查询导航结构化信息
 * - cmd=6 切换播报方式
 * - cmd=7 触发导航关键信息刷新
 */
class AmapLinkNavigationExecutor(private val context: Context) : NavigationExecutor {

    companion object {
        private const val TAG = "AmapLinkNavExecutor"

        // TODO: 集成 AmapLinkClient SDK 后，替换为你的高德 API Key
        private const val API_KEY = "YOUR_AMAP_API_KEY"

        // AmapLinkClient 类名和方法名（用于反射）
        private const val CLASS_AMAP_LINK_CLIENT = "com.amap.api.link.AmapLinkClient"
        private const val METHOD_CONNECT = "connect"
        private const val METHOD_DISCONNECT = "disconnect"
        private const val METHOD_EXECUTE = "execute"
        private const val METHOD_SET_RECONNECT_CONFIG = "setReconnectConfig"
        private const val METHOD_IS_CONNECTED = "isConnected"
    }

    private var amapLinkClient: Any? = null
    private var executeMethod: Method? = null
    private var isInitialized = false

    init {
        initialize()
    }

    /**
     * 初始化 AmapLinkClient：
     * 1. 反射创建实例
     * 2. 配置自动重连
     * 3. 连接到高德地图服务
     */
    private fun initialize() {
        try {
            val clazz = Class.forName(CLASS_AMAP_LINK_CLIENT)
            Log.d(TAG, "找到 AmapLinkClient 类: $CLASS_AMAP_LINK_CLIENT")

            // 构造函数: AmapLinkClient(Context context, String apiKey)
            val constructor = clazz.getConstructor(Context::class.java, String::class.java)
            amapLinkClient = constructor.newInstance(context, API_KEY)
            Log.d(TAG, "AmapLinkClient 实例创建成功")

            // 配置自动重连: setReconnectConfig(boolean enabled, int maxAttempts, int delaySeconds)
            try {
                val setReconnectMethod = clazz.getMethod(
                    METHOD_SET_RECONNECT_CONFIG,
                    Boolean::class.javaPrimitiveType,
                    Int::class.javaPrimitiveType,
                    Int::class.javaPrimitiveType
                )
                setReconnectMethod.invoke(amapLinkClient, true, 5, 2)
                Log.d(TAG, "自动重连配置成功")
            } catch (e: Exception) {
                Log.w(TAG, "配置自动重连失败（不影响基本功能）: ${e.message}")
            }

            // 获取 execute 方法: String execute(String param)
            executeMethod = clazz.getMethod(METHOD_EXECUTE, String::class.java)
            Log.d(TAG, "execute 方法获取成功")

            // 连接到高德地图服务: boolean connect()
            try {
                val connectMethod = clazz.getMethod(METHOD_CONNECT)
                val result = connectMethod.invoke(amapLinkClient) as Boolean
                Log.d(TAG, "连接请求已发出: $result（连接结果通过 ConnectionListener 回调通知）")
            } catch (e: Exception) {
                Log.w(TAG, "调用 connect 失败: ${e.message}")
            }

            isInitialized = true
            Log.d(TAG, "AmapLinkNavigationExecutor 初始化完成")
        } catch (e: ClassNotFoundException) {
            Log.e(TAG, "AmapLinkClient 类不存在，请先集成 SDK: ${e.message}")
            throw RuntimeException("AmapLinkClient SDK 未集成", e)
        } catch (e: Exception) {
            Log.e(TAG, "AmapLinkClient 初始化失败", e)
            throw RuntimeException("AmapLinkClient 初始化失败", e)
        }
    }

    override fun execute(
        cmd: Int,
        requestId: Int,
        data: Map<String, Any?>,
        amapExecuteJson: String?
    ): String {
        if (!isInitialized || amapLinkClient == null || executeMethod == null) {
            return "error: AmapLinkClient 未初始化"
        }

        // 优先使用服务端下发的 amap_execute_json（已包含完整的 cmd/requestId/data）
        val jsonToExecute = amapExecuteJson ?: buildExecuteJson(cmd, requestId, data)
        Log.d(TAG, "执行导航指令: cmd=$cmd, json=$jsonToExecute")

        return try {
            val result = executeMethod!!.invoke(amapLinkClient, jsonToExecute) as String
            Log.d(TAG, "指令执行结果: $result")
            result
        } catch (e: Exception) {
            Log.e(TAG, "指令执行失败", e)
            "error: ${e.message}"
        }
    }

    /**
     * 构建 AmapLinkClient execute() 所需的 JSON。
     *
     * 格式: {"cmd": 4, "requestId": 123456, "data": {...}}
     */
    private fun buildExecuteJson(cmd: Int, requestId: Int, data: Map<String, Any?>): String {
        val dataJson = data.entries.joinToString(",") { (key, value) ->
            when (value) {
                is String -> "\"$key\":\"$value\""
                is Number -> "\"$key\":$value"
                is Boolean -> "\"$key\":$value"
                null -> "\"$key\":null"
                else -> "\"$key\":\"$value\""
            }
        }
        return "{\"cmd\":$cmd,\"requestId\":$requestId,\"data\":{$dataJson}}"
    }

    override fun release() {
        if (amapLinkClient != null) {
            try {
                val disconnectMethod = amapLinkClient!!.javaClass.getMethod(METHOD_DISCONNECT)
                disconnectMethod.invoke(amapLinkClient)
                Log.d(TAG, "AmapLinkClient 已断开连接")
            } catch (e: Exception) {
                Log.w(TAG, "断开连接失败: ${e.message}")
            }
            amapLinkClient = null
        }
        isInitialized = false
    }
}
