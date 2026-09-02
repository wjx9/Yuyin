package com.rayneo.moasm_vui

import android.content.Intent
import android.util.Log
import com.rayneo.moasm_vui.navigation.AgentPocActivity
import com.rayneo.moasm_vui.navigation.AmapNaviViewActivity
import com.rayneo.moasm_vui.navigation.NavigationEventBus
import com.rayneo.moasm_vui.navigation.NavigationExecutor
import com.rayneo.moasm_vui.navigation.NaviFloatingPlatformView
import com.rayneo.moasm_vui.navigation.NaviFloatingViewFactory
import io.flutter.embedding.android.FlutterActivity
import io.flutter.embedding.engine.FlutterEngine
import io.flutter.embedding.engine.FlutterEngineCache
import io.flutter.plugin.common.EventChannel
import io.flutter.plugin.common.MethodChannel

/**
 * 主 Activity：注册导航相关的 MethodChannel 和 EventChannel。
 *
 * Channels:
 * - MethodChannel: com.rayneo.moasm_vui/navigation
 *   - executeNavCommand: 执行导航控制指令（兼容旧版 Intent 方式）
 *   - startNavigation: 开始导航（拉起高德原生导航界面 AMapNaviView）
 *   - stopNavigation: 停止导航
 *
 * - EventChannel: com.rayneo.moasm_vui/navigation_events
 *   - navi_info: 导航实时信息（转向、距离、时间等）
 *   - route_calc_success/failure: 路线计算结果
 *   - start_navi: 开始导航
 *   - arrived_destination: 到达目的地
 *   - navi_text: 导航播报文本
 */
class MainActivity : FlutterActivity() {

    companion object {
        private const val NAV_CHANNEL = "com.rayneo.moasm_vui/navigation"
        private const val NAV_EVENT_CHANNEL = "com.rayneo.moasm_vui/navigation_events"
        private const val AGENT_POC_CHANNEL = "com.rayneo.moasm_vui/agent_poc"
        private const val TAG = "NavChannel"
    }

    private var navigationExecutor: NavigationExecutor? = null

    override fun configureFlutterEngine(flutterEngine: FlutterEngine) {
        super.configureFlutterEngine(flutterEngine)

        val binaryMessenger = flutterEngine.dartExecutor.binaryMessenger

        // 缓存引擎：供原生导航页（AmapNaviViewActivity）唤起语音助手时发消息给 Flutter
        FlutterEngineCache.getInstance().put(AmapNaviViewActivity.ENGINE_ID, flutterEngine)

        // 注册悬浮导航 PlatformView（POC：AMapNaviView 嵌入 Flutter 悬浮面板）
        flutterEngine.platformViewsController.registry.registerViewFactory(
            NaviFloatingPlatformView.VIEW_TYPE,
            NaviFloatingViewFactory(this)
        )
        Log.d(TAG, "悬浮导航 PlatformView 已注册: ${NaviFloatingPlatformView.VIEW_TYPE}")

        // 导航事件通道：高德原生导航界面把实时事件推给 Flutter（眼镜 HUD / 失败回退）。
        // sink 写入 NavigationEventBus，由 AmapNaviViewActivity 推事件。
        EventChannel(binaryMessenger, NAV_EVENT_CHANNEL).setStreamHandler(object : EventChannel.StreamHandler {
            override fun onListen(arguments: Any?, events: EventChannel.EventSink?) {
                NavigationEventBus.sink = events
            }
            override fun onCancel(arguments: Any?) {
                NavigationEventBus.sink = null
            }
        })

        // 创建 Intent 回退执行器（用于 executeNavCommand 兼容旧版）
        navigationExecutor = NavigationExecutor.create(applicationContext)

        // 注册 MethodChannel
        MethodChannel(binaryMessenger, NAV_CHANNEL).setMethodCallHandler { call, result ->
            when (call.method) {
                "executeNavCommand" -> executeNavCommand(call.arguments, result)
                "startNavigation" -> startNavigation(call.arguments, result)
                "stopNavigation" -> stopNavigation(result)
                "setAssistantActive" -> setAssistantActive(call.arguments, result)
                "naviSpeechText" -> naviSpeechText(call.arguments, result)
                else -> result.notImplemented()
            }
        }

        Log.d(TAG, "导航 Channel 已注册")

        // 注册 Agent POC Channel
        MethodChannel(binaryMessenger, AGENT_POC_CHANNEL).setMethodCallHandler { call, result ->
            when (call.method) {
                "startAgentPoc" -> {
                    startActivity(Intent(this, AgentPocActivity::class.java))
                    result.success("started")
                }
                else -> result.notImplemented()
            }
        }
    }

    /**
     * 执行导航控制指令（兼容旧版 Intent 方式）。
     */
    private fun executeNavCommand(arguments: Any?, result: MethodChannel.Result) {
        try {
            val args = arguments as? Map<*, *>
                ?: run {
                    result.error("INVALID_ARGS", "arguments 不是 Map", null)
                    return
                }

            val cmd = (args["cmd"] as? Number)?.toInt()
                ?: run {
                    result.error("INVALID_CMD", "缺少 cmd 参数", null)
                    return
                }

            val requestId = (args["requestId"] as? Number)?.toInt() ?: 0
            val data = (args["data"] as? Map<*, *>)?.let {
                @Suppress("UNCHECKED_CAST")
                it as Map<String, Any?>
            } ?: emptyMap()
            val amapExecuteJson = args["amapExecuteJson"] as? String

            Log.d(TAG, "executeNavCommand: cmd=$cmd, data=$data")

            val executor = navigationExecutor
                ?: run {
                    result.error("NO_EXECUTOR", "导航执行器未初始化", null)
                    return
                }

            val executeResult = executor.execute(cmd, requestId, data, amapExecuteJson)
            if (executeResult.startsWith("error:")) {
                result.error("EXECUTE_FAILED", executeResult.removePrefix("error:").trim(), null)
            } else {
                result.success(executeResult)
            }
        } catch (e: Exception) {
            Log.e(TAG, "executeNavCommand exception", e)
            result.error("EXCEPTION", e.message, null)
        }
    }

    /**
     * 开始导航（高德导航自带界面 AMapNaviView）。
     *
     * 由 Flutter 端调用：拉起承载高德原生导航界面的 Activity；
     * 导航实时事件由 AmapNaviViewActivity 通过 NavigationEventBus 推回 Flutter。
     */
    private fun startNavigation(arguments: Any?, result: MethodChannel.Result) {
        try {
            val args = arguments as? Map<*, *>
                ?: run {
                    result.error("INVALID_ARGS", "arguments 不是 Map", null)
                    return
                }

            val lat = (args["lat"] as? Number)?.toDouble()
            val lon = (args["lon"] as? Number)?.toDouble()
            val poiName = args["poiName"] as? String
            val poiId = args["poiId"] as? String

            if (lat == null || lon == null) {
                result.error("INVALID_COORD", "缺少经纬度参数", null)
                return
            }

            Log.d(TAG, "startNavigation(高德原生导航UI): lat=$lat, lon=$lon, poiName=$poiName, poiId=$poiId")

            startActivity(AmapNaviViewActivity.launchIntent(applicationContext, lat, lon, poiName, poiId))
            result.success("started")
        } catch (e: Exception) {
            Log.e(TAG, "startNavigation exception", e)
            result.error("EXCEPTION", e.message, null)
        }
    }

    /**
     * 停止导航：弹出"是否结束本次导航"确认；确认后由导航页结束并返回。
     * 无导航页时直接返回 "stopped"。
     */
    private fun stopNavigation(result: MethodChannel.Result) {
        try {
            Log.d(TAG, "stopNavigation")
            val navi = AmapNaviViewActivity.current
            if (navi != null) {
                navi.confirmExitNavigation()
                result.success("confirming")
            } else {
                result.success("stopped")
            }
        } catch (e: Exception) {
            Log.e(TAG, "stopNavigation exception", e)
            result.error("EXCEPTION", e.message, null)
        }
    }

    /**
     * 设置语音助手激活状态：优先转发给悬浮导航 PlatformView，
     * 若无悬浮窗则转发给全屏导航 Activity。激活时让导航语音让位。
     */
    private fun setAssistantActive(arguments: Any?, result: MethodChannel.Result) {
        try {
            val active = arguments as? Boolean ?: false
            val floating = NaviFloatingPlatformView.current
            if (floating != null) {
                floating.setAssistantActive(active)
            } else {
                AmapNaviViewActivity.current?.setAssistantActive(active)
            }
            result.success(null)
        } catch (e: Exception) {
            Log.e(TAG, "setAssistantActive exception", e)
            result.error("EXCEPTION", e.message, null)
        }
    }

    /**
     * 导航页实时识别文字：由 Flutter 听写过程中回传，转发给原生导航页显示。
     * text 为空串时导航页隐藏显示。
     */
    private fun naviSpeechText(arguments: Any?, result: MethodChannel.Result) {
        try {
            val text = arguments as? String
            AmapNaviViewActivity.current?.showSpeechText(text)
            result.success(null)
        } catch (e: Exception) {
            Log.e(TAG, "naviSpeechText exception", e)
            result.error("EXCEPTION", e.message, null)
        }
    }

    override fun onDestroy() {
        navigationExecutor = null
        super.onDestroy()
    }
}
