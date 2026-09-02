package com.rayneo.moasm_vui.navigation

import android.content.Context
import android.util.Log

/**
 * 导航执行器接口：抽象导航控制指令的执行。
 *
 * 有两种实现：
 * - IntentNavigationExecutor：通过 Android Intent 拉起高德地图 App（无需额外 SDK）
 * - AmapLinkNavigationExecutor：通过高德 AmapLinkClient SDK 与高德地图 IPC 通信（需集成 SDK）
 *
 * MainActivity 会优先使用 AmapLinkNavigationExecutor（如果 SDK 可用），失败时回退到 Intent。
 */
interface NavigationExecutor {

    companion object {
        private const val TAG = "NavExecutor"

        /**
         * 创建导航执行器：优先尝试 AmapLinkClient，失败则回退到 Intent。
         *
         * 通过反射检测 AmapLinkNavigationExecutor 是否可用（即 SDK 是否已集成）。
         */
        fun create(context: Context): NavigationExecutor {
            return try {
                // 反射检测 AmapLinkClient SDK 是否可用
                val clazz = Class.forName("com.rayneo.moasm_vui.navigation.AmapLinkNavigationExecutor")
                val constructor = clazz.getConstructor(Context::class.java)
                val executor = constructor.newInstance(context) as NavigationExecutor
                Log.d(TAG, "使用 AmapLinkNavigationExecutor（SDK 已集成）")
                executor
            } catch (e: Exception) {
                Log.d(TAG, "AmapLinkClient SDK 不可用，回退到 IntentNavigationExecutor: ${e.message}")
                IntentNavigationExecutor(context)
            }
        }
    }

    /** 执行导航控制指令。 */
    fun execute(cmd: Int, requestId: Int, data: Map<String, Any?>, amapExecuteJson: String?): String

    /** 释放资源。 */
    fun release()
}
