package com.rayneo.moasm_vui.navigation

import android.content.ActivityNotFoundException
import android.content.Context
import android.content.Intent
import android.net.Uri
import android.util.Log

/**
 * Intent 导航执行器：通过 Android Intent 拉起高德地图 App。
 *
 * 无需额外 SDK，只要手机安装了高德地图 App 即可使用。
 *
 * 支持的指令：
 * - cmd=4（设置终点/开始导航）：拉起高德地图导航页面
 * - cmd=2（停止导航）：Intent 方式无法远程停止，返回提示
 *
 * 注意：Android 11+ 需要在 AndroidManifest.xml 的 queries 中声明
 *       androidamap scheme 和 com.autonavi.minimap 包名，否则无法拉起。
 */
class IntentNavigationExecutor(private val context: Context) : NavigationExecutor {

    companion object {
        private const val TAG = "IntentNavExecutor"
        private const val AMAP_PACKAGE = "com.autonavi.minimap"
        private const val AMAP_NAVI_SCHEME = "androidamap://navi"
    }

    override fun execute(
        cmd: Int,
        requestId: Int,
        data: Map<String, Any?>,
        amapExecuteJson: String?
    ): String {
        return when (cmd) {
            4 -> startNavigation(data)
            2 -> stopNavigation()
            else -> {
                Log.w(TAG, "Intent 方式不支持 cmd=$cmd，建议集成 AmapLinkClient SDK")
                "unsupported: cmd=$cmd (Intent 方式仅支持 cmd=4 开始导航)"
            }
        }
    }

    /**
     * 开始导航：通过 Intent 拉起高德地图 App。
     *
     * URL Scheme: androidamap://navi?sourceApplication=xxx&poiname=xxx&lat=xxx&lon=xxx&dev=0&style=2
     *
     * dev=0 表示 GCJ-02 坐标（高德坐标，服务端返回的就是 GCJ-02）
     * style=2 表示距离优先
     */
    private fun startNavigation(data: Map<String, Any?>): String {
        val name = (data["name"] as? String) ?: "目的地"
        val lon = (data["lon"] as? Number)?.toDouble()
        val lat = (data["lat"] as? Number)?.toDouble()

        if (lon == null || lat == null) {
            Log.e(TAG, "缺少经纬度参数: lon=$lon, lat=$lat")
            return "error: 缺少经纬度参数"
        }

        // 检查高德地图是否已安装
        if (!isAppInstalled()) {
            Log.e(TAG, "未安装高德地图 App")
            return "error: 未安装高德地图 App，请先安装"
        }

        return try {
            val uri = Uri.parse(AMAP_NAVI_SCHEME).buildUpon()
                .appendQueryParameter("sourceApplication", "moasm_vui")
                .appendQueryParameter("poiname", name)
                .appendQueryParameter("lat", lat.toString())
                .appendQueryParameter("lon", lon.toString())
                .appendQueryParameter("dev", "0") // 0=GCJ-02（高德坐标）
                .appendQueryParameter("style", "2") // 2=距离优先
                .build()

            val intent = Intent(Intent.ACTION_VIEW, uri)
            intent.setPackage(AMAP_PACKAGE)
            intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)

            Log.d(TAG, "拉起高德地图导航: $uri")
            context.startActivity(intent)

            "started: $name"
        } catch (e: ActivityNotFoundException) {
            Log.e(TAG, "高德地图导航 Activity 不存在", e)
            "error: 无法启动高德地图导航（ActivityNotFoundException）"
        } catch (e: Exception) {
            Log.e(TAG, "拉起导航异常", e)
            "error: ${e.message}"
        }
    }

    /**
     * 停止导航：Intent 方式无法远程停止高德地图的导航。
     *
     * 需要集成 AmapLinkClient SDK 后使用 cmd=2 远程停止。
     */
    private fun stopNavigation(): String {
        Log.d(TAG, "Intent 方式无法远程停止导航，需用户手动停止或集成 AmapLinkClient SDK")
        return "stop_requested: Intent 方式无法远程停止，请在高德地图中手动停止；或集成 AmapLinkClient SDK 实现远程停止"
    }

    /** 检查高德地图 App 是否已安装。 */
    private fun isAppInstalled(): Boolean {
        return try {
            context.packageManager.getPackageInfo(AMAP_PACKAGE, 0)
            true
        } catch (e: Exception) {
            false
        }
    }

    override fun release() {
        // Intent 方式无需释放资源
    }
}
