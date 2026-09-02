package com.rayneo.moasm_vui.navigation

import android.app.Activity
import android.content.Context
import android.os.Bundle
import android.util.Log
import android.view.View
import android.view.ViewGroup
import android.widget.FrameLayout
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleObserver
import androidx.lifecycle.OnLifecycleEvent
import com.amap.api.navi.AMapNavi
import com.amap.api.navi.AMapNaviListener
import com.amap.api.navi.AMapNaviView
import com.amap.api.navi.AMapNaviViewListener
import com.amap.api.navi.AmapPageType
import com.amap.api.navi.enums.NaviType
import com.amap.api.navi.enums.PathPlanningStrategy
import com.amap.api.navi.model.AMapCalcRouteResult
import com.amap.api.navi.model.AMapLaneInfo
import com.amap.api.navi.model.AMapModelCross
import com.amap.api.navi.model.AMapNaviCameraInfo
import com.amap.api.navi.model.AMapNaviCross
import com.amap.api.navi.model.AMapNaviLocation
import com.amap.api.navi.model.AMapNaviRouteNotifyData
import com.amap.api.navi.model.AMapNaviTrafficFacilityInfo
import com.amap.api.navi.model.AMapServiceAreaInfo
import com.amap.api.navi.model.AimLessModeCongestionInfo
import com.amap.api.navi.model.AimLessModeStat
import com.amap.api.navi.model.NaviInfo
import com.amap.api.navi.model.NaviLatLng
import com.amap.api.navi.model.NaviPoi
import io.flutter.plugin.common.StandardMessageCodec
import io.flutter.plugin.platform.PlatformView
import io.flutter.plugin.platform.PlatformViewFactory

/**
 * 悬浮导航 PlatformView：把高德 AMapNaviView 嵌入 Flutter PlatformView，
 * 以可拖拽悬浮面板的形式叠加在聊天界面上，语音助手始终可见可用。
 *
 * POC 验证点：
 * 1. AMapNaviView（FrameLayout 子类）能否在非全屏容器中正常渲染；
 * 2. Hybrid Composition 模式下 SurfaceView 地图是否黑屏/闪烁；
 * 3. 小窗尺寸下导航 UI 元素是否可读。
 *
 * 生命周期：Flutter 端创建 AndroidView → create() → onCreate/onResume；
 * Flutter 端移除 → dispose() → onPause/onDestroy + stopNavi + 推送 navi_end。
 */
class NaviFloatingPlatformView(
    private val context: Context,
    activity: Activity?,
    creationParams: Map<String, Any?>?
) : PlatformView, AMapNaviViewListener, AMapNaviListener, LifecycleObserver {

    companion object {
        private const val TAG = "NaviFloatingView"
        const val VIEW_TYPE = "com.rayneo.moasm_vui/navi_floating_view"

        /** 当前活跃的悬浮导航视图（供 MainActivity 转发助手激活状态等）。 */
        @Volatile
        var current: NaviFloatingPlatformView? = null
    }

    private val naviView: AMapNaviView
    private var aMapNavi: AMapNavi? = null
    private val lat: Double
    private val lon: Double
    private val poiName: String?
    private val poiId: String?
    private var naviStarted = false

    init {
        lat = (creationParams?.get("lat") as? Number)?.toDouble() ?: 0.0
        lon = (creationParams?.get("lon") as? Number)?.toDouble() ?: 0.0
        poiName = creationParams?.get("poiName") as? String
        poiId = creationParams?.get("poiId") as? String

        Log.d(TAG, "init: lat=$lat, lon=$lon, poiName=$poiName, poiId=$poiId")

        callPrivacyCompliance(context)

        naviView = AMapNaviView(context)
        naviView.layoutParams = FrameLayout.LayoutParams(
            ViewGroup.LayoutParams.MATCH_PARENT,
            ViewGroup.LayoutParams.MATCH_PARENT
        )
        naviView.onCreate(null)
        naviView.setAMapNaviViewListener(this)

        // AMapNavi 是单例，用 applicationContext 获取
        aMapNavi = AMapNavi.getInstance(context.applicationContext)
        aMapNavi?.addAMapNaviListener(this)
        aMapNavi?.startGPS()

        current = this

        // 绑定 Activity 生命周期，实现 onResume/onPause 转发
        (activity as? androidx.lifecycle.LifecycleOwner)?.lifecycle?.addObserver(this)
    }

    override fun getView(): View = naviView

    /**
     * 语音助手激活状态：激活时静音导航播报，空闲时恢复。
     * 由 MainActivity 从 Flutter 端转发过来。
     */
    fun setAssistantActive(active: Boolean) {
        try {
            if (active) {
                aMapNavi?.stopSpeak()
            }
            aMapNavi?.setUseInnerVoice(!active)
        } catch (e: Exception) {
            Log.e(TAG, "setAssistantActive 失败", e)
        }
    }

    @OnLifecycleEvent(Lifecycle.Event.ON_RESUME)
    fun onActivityResume() {
        try {
            naviView.onResume()
        } catch (e: Exception) {
            Log.d(TAG, "onResume: ${e.message}")
        }
    }

    @OnLifecycleEvent(Lifecycle.Event.ON_PAUSE)
    fun onActivityPause() {
        try {
            naviView.onPause()
        } catch (e: Exception) {
            Log.d(TAG, "onPause: ${e.message}")
        }
    }

    /**
     * Flutter 端移除悬浮面板时调用：停止导航、释放资源、推送 navi_end。
     */
    override fun dispose() {
        Log.d(TAG, "dispose")
        current = null
        try {
            (context as? androidx.lifecycle.LifecycleOwner)?.lifecycle?.removeObserver(this)
        } catch (_: Exception) {}
        try { aMapNavi?.stopSpeak() } catch (e: Exception) { Log.d(TAG, "stopSpeak: ${e.message}") }
        try { aMapNavi?.stopNavi() } catch (e: Exception) { Log.d(TAG, "stopNavi: ${e.message}") }
        try { aMapNavi?.removeAMapNaviListener(this) } catch (e: Exception) { Log.d(TAG, "removeListener: ${e.message}") }
        try { naviView.onDestroy() } catch (e: Exception) { Log.d(TAG, "onDestroy: ${e.message}") }
        aMapNavi = null
        naviStarted = false
        // 通知 Flutter 导航已结束
        NavigationEventBus.push("navi_end", null)
    }

    // ==================== AMapNaviViewListener ====================

    /** 导航视图加载完成：开始算路。 */
    override fun onNaviViewLoaded() {
        Log.d(TAG, "onNaviViewLoaded")
        val navi = aMapNavi ?: return
        if (!poiId.isNullOrEmpty()) {
            navi.calculateDriveRoute(
                null,
                NaviPoi(poiName ?: "目的地", null, poiId),
                null,
                PathPlanningStrategy.DRIVING_MULTIPLE_ROUTES_DEFAULT
            )
            Log.d(TAG, "POI 算路: poiId=$poiId")
        } else {
            val end = ArrayList<NaviLatLng>().apply { add(NaviLatLng(lat, lon)) }
            navi.calculateDriveRoute(null, end, null, PathPlanningStrategy.DRIVING_MULTIPLE_ROUTES_DEFAULT)
            Log.d(TAG, "坐标算路: lat=$lat, lon=$lon")
        }
    }

    override fun onNaviSetting() {}
    override fun onNaviCancel() { /* 悬浮窗由 Flutter 关闭按钮控制，不弹确认 */ }
    override fun onNaviBackClick(): Boolean = true
    override fun onNaviMapMode(mode: Int) {}
    override fun onNaviTurnClick() {}
    override fun onNextRoadClick() {}
    override fun onScanViewButtonClick() {}
    override fun onLockMap(isLock: Boolean) {}
    override fun onMapTypeChanged(type: Int) {}
    override fun onNaviViewShowMode(mode: Int) {}
    override fun onStopSpeaking() {}
    override fun onViewTypeChanged(type: AmapPageType) {}
    override fun onAMapNaviViewExit() { /* 不处理，由 Flutter 关闭按钮控制 */ }
    override fun onStrategyChanged(strategy: Int) {}
    override fun onBroadcastModeChanged(mode: Int) {}
    override fun onDayAndNightModeChanged(mode: Int) {}
    override fun onScaleAutoChanged(isAuto: Boolean) {}
    override fun onListenToVoiceDuringCallChanged(change: Boolean) {}
    override fun onControlMusicVolumeModeChanged(mode: Int) {}
    override fun onEagleChanged(isEagle: Boolean) {}
    override fun onNaviRouteHighlightChange(routeId: Long, type: Int) {}

    // ==================== AMapNaviListener ====================

    override fun onInitNaviSuccess() {
        Log.d(TAG, "onInitNaviSuccess")
    }

    override fun onInitNaviFailure() {
        Log.e(TAG, "onInitNaviFailure")
        NavigationEventBus.push("error", mapOf("message" to "导航 SDK 初始化失败"))
    }

    override fun onCalculateRouteSuccess(routeIDs: IntArray?) {
        Log.d(TAG, "onCalculateRouteSuccess(IntArray)")
        NavigationEventBus.push("route_calc_success", null)
        startNaviIfNeeded()
    }

    override fun onCalculateRouteSuccess(routeResult: AMapCalcRouteResult?) {
        Log.d(TAG, "onCalculateRouteSuccess(AMapCalcRouteResult)")
        NavigationEventBus.push("route_calc_success", null)
        startNaviIfNeeded()
    }

    private fun startNaviIfNeeded() {
        if (naviStarted) return
        naviStarted = true
        try {
            aMapNavi?.startNavi(NaviType.GPS)
        } catch (e: Exception) {
            Log.e(TAG, "startNavi 失败", e)
            NavigationEventBus.push("error", mapOf("message" to "开始导航失败: ${e.message}"))
        }
    }

    override fun onCalculateRouteFailure(errorCode: Int) {
        Log.e(TAG, "onCalculateRouteFailure(Int): $errorCode")
        NavigationEventBus.push("route_calc_failure", mapOf("errorCode" to errorCode))
    }

    override fun onCalculateRouteFailure(routeResult: AMapCalcRouteResult?) {
        val errorCode = routeResult?.errorCode ?: -1
        Log.e(TAG, "onCalculateRouteFailure(AMapCalcRouteResult): $errorCode")
        NavigationEventBus.push("route_calc_failure", mapOf("errorCode" to errorCode))
    }

    override fun onStartNavi(type: Int) {
        Log.d(TAG, "onStartNavi: $type")
        NavigationEventBus.push("start_navi", mapOf("type" to type))
    }

    override fun onNaviInfoUpdate(naviInfo: NaviInfo?) {
        naviInfo ?: return
        NavigationEventBus.push("navi_info", parseNaviInfo(naviInfo))
    }

    override fun onGetNavigationText(type: Int, text: String?) {
        text ?: return
        NavigationEventBus.push("navi_text", mapOf("text" to text))
    }

    override fun onGetNavigationText(text: String?) {
        text ?: return
        NavigationEventBus.push("navi_text", mapOf("text" to text))
    }

    override fun onArriveDestination() {
        Log.d(TAG, "到达目的地")
        NavigationEventBus.push("arrive_destination", null)
    }

    override fun onEndEmulatorNavi() {}
    override fun onLocationChange(location: AMapNaviLocation?) {}
    override fun onReCalculateRouteForYaw() { Log.d(TAG, "偏航重算") }
    override fun onReCalculateRouteForTrafficJam() { Log.d(TAG, "拥堵重算") }
    override fun onArrivedWayPoint(wayPointIndex: Int) {}
    override fun onTrafficStatusUpdate() {}
    override fun onGpsOpenStatus(opened: Boolean) {}
    override fun updateCameraInfo(cameraInfos: Array<out AMapNaviCameraInfo>?) {}
    override fun updateIntervalCameraInfo(start: AMapNaviCameraInfo?, end: AMapNaviCameraInfo?, status: Int) {}
    override fun onServiceAreaUpdate(serviceAreaInfos: Array<out AMapServiceAreaInfo>?) {}
    override fun showCross(cross: AMapNaviCross?) {}
    override fun hideCross() {}
    override fun showModeCross(modelCross: AMapModelCross?) {}
    override fun hideModeCross() {}
    override fun showLaneInfo(laneInfos: Array<out AMapLaneInfo>?, laneInfoBg: ByteArray?, laneInfoSel: ByteArray?) {}
    override fun showLaneInfo(laneInfo: AMapLaneInfo?) {}
    override fun hideLaneInfo() {}
    override fun notifyParallelRoad(type: Int) {}
    override fun OnUpdateTrafficFacility(trafficFacilityInfos: Array<out AMapNaviTrafficFacilityInfo>?) {}
    override fun OnUpdateTrafficFacility(trafficFacilityInfo: AMapNaviTrafficFacilityInfo?) {}
    override fun updateAimlessModeStatistics(stat: AimLessModeStat?) {}
    override fun updateAimlessModeCongestionInfo(info: AimLessModeCongestionInfo?) {}
    override fun onPlayRing(type: Int) {}
    override fun onNaviRouteNotify(notifyData: AMapNaviRouteNotifyData?) {}
    override fun onGpsSignalWeak(weak: Boolean) {}

    // ==================== 工具 ====================

    private fun parseNaviInfo(naviInfo: NaviInfo): Map<String, Any?> {
        val info = mutableMapOf<String, Any?>()
        try {
            info["iconType"] = naviInfo.iconType
            info["curStepRetainDistance"] = naviInfo.curStepRetainDistance
            info["pathRetainDistance"] = naviInfo.pathRetainDistance
            info["pathRetainTime"] = naviInfo.pathRetainTime
            info["nextRoadName"] = naviInfo.nextRoadName
            info["currentRoadName"] = naviInfo.currentRoadName
            info["currentSpeed"] = naviInfo.currentSpeed
            info["curStep"] = naviInfo.curStep
        } catch (e: Exception) {
            Log.e(TAG, "解析 NaviInfo 失败", e)
        }
        return info
    }

    private fun callPrivacyCompliance(context: Context) {
        val classNames = listOf(
            "com.amap.api.maps.MapsInitializer",
            "com.amap.api.navi.NaviInitializer"
        )
        for (className in classNames) {
            try {
                val clazz = Class.forName(className)
                try {
                    clazz.getMethod(
                        "updatePrivacyShow",
                        Context::class.java,
                        Boolean::class.javaPrimitiveType,
                        Boolean::class.javaPrimitiveType
                    ).invoke(null, context, true, true)
                } catch (_: NoSuchMethodException) {}
                try {
                    clazz.getMethod(
                        "updatePrivacyAgree",
                        Context::class.java,
                        Boolean::class.javaPrimitiveType
                    ).invoke(null, context, true)
                } catch (_: NoSuchMethodException) {}
            } catch (_: ClassNotFoundException) {}
        }
    }
}

/**
 * 悬浮导航 PlatformView 工厂：由 MainActivity 注册，Flutter 端通过 viewType 创建。
 */
class NaviFloatingViewFactory(
    private val activity: Activity?
) : PlatformViewFactory(StandardMessageCodec.INSTANCE) {

    override fun create(context: Context, viewId: Int, args: Any?): PlatformView {
        val params = args as? Map<String, Any?>
        return NaviFloatingPlatformView(context, activity, params)
    }
}
