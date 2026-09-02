package com.rayneo.moasm_vui.navigation

import android.content.Context
import android.util.Log
import com.amap.api.navi.AMapNavi
import com.amap.api.navi.AMapNaviListener
import com.amap.api.navi.enums.NaviType
import com.amap.api.navi.enums.PathPlanningStrategy
import com.amap.api.navi.model.AMapCalcRouteResult
import com.amap.api.navi.model.AMapLaneInfo
import com.amap.api.navi.model.AMapModelCross
import com.amap.api.navi.model.AMapNaviCameraInfo
import com.amap.api.navi.model.AMapNaviCross
import com.amap.api.navi.model.AMapNaviLocation
import com.amap.api.navi.model.AMapNaviTrafficFacilityInfo
import com.amap.api.navi.model.AMapNaviRouteNotifyData
import com.amap.api.navi.model.AMapServiceAreaInfo
import com.amap.api.navi.model.AimLessModeCongestionInfo
import com.amap.api.navi.model.AimLessModeStat
import com.amap.api.navi.model.NaviInfo
import com.amap.api.navi.model.NaviLatLng
import com.amap.api.navi.model.NaviPoi
import io.flutter.plugin.common.EventChannel
import io.flutter.plugin.common.MethodChannel

/**
 * 高德导航管理器：封装高德导航 SDK（AMapNavi），无 UI 模式。
 * 适配 V11.2.100 接口。
 */
class AmapNaviManager(
    private val context: Context,
    methodChannel: MethodChannel,
    private val eventChannel: EventChannel
) : AMapNaviListener {

    companion object {
        private const val TAG = "AmapNaviManager"
        const val EVENT_NAVI_INFO = "navi_info"
        const val EVENT_ROUTE_CALC_SUCCESS = "route_calc_success"
        const val EVENT_ROUTE_CALC_FAILURE = "route_calc_failure"
        const val EVENT_START_NAVI = "start_navi"
        const val EVENT_ARRIVE_DEST = "arrive_destination"
        const val EVENT_NAVI_TEXT = "navi_text"
        const val EVENT_ERROR = "error"
    }

    private var aMapNavi: AMapNavi? = null
    private var isNavigating = false
    private var eventSink: EventChannel.EventSink? = null
    private var initError: String? = null

    init {
        setupEventChannel()
        initializeSdk()
    }

    private fun setupEventChannel() {
        eventChannel.setStreamHandler(object : EventChannel.StreamHandler {
            override fun onListen(arguments: Any?, events: EventChannel.EventSink?) {
                eventSink = events
            }
            override fun onCancel(arguments: Any?) {
                eventSink = null
            }
        })
    }

    private fun initializeSdk() {
        try {
            // 高德 SDK V11.2+ 要求：调用任何接口前必须先设置隐私合规
            // 用反射调用，尝试 MapsInitializer 和 NaviInitializer
            callPrivacyCompliance(context.applicationContext)

            aMapNavi = AMapNavi.getInstance(context.applicationContext)
            aMapNavi?.addAMapNaviListener(this)
            // 启动 GPS 定位，确保计算路线时有起点
            aMapNavi?.startGPS()
            Log.d(TAG, "高德导航 SDK 初始化成功，GPS 已启动")
        } catch (e: Exception) {
            Log.e(TAG, "高德导航 SDK 初始化失败", e)
            initError = "${e.javaClass.simpleName}: ${e.message}"
        }
    }

    /**
     * 用反射调用高德隐私合规接口。
     * 尝试 MapsInitializer（地图SDK）和 NaviInitializer（导航SDK）。
     */
    private fun callPrivacyCompliance(context: Context) {
        val classNames = listOf(
            "com.amap.api.maps.MapsInitializer",
            "com.amap.api.navi.NaviInitializer"
        )
        for (className in classNames) {
            try {
                val clazz = Class.forName(className)
                // updatePrivacyShow(Context, boolean isContains, boolean isShow)
                try {
                    val showMethod = clazz.getMethod("updatePrivacyShow", Context::class.java, Boolean::class.javaPrimitiveType, Boolean::class.javaPrimitiveType)
                    showMethod.invoke(null, context, true, true)
                    Log.d(TAG, "调用 $className.updatePrivacyShow 成功")
                } catch (_: NoSuchMethodException) {}
                // updatePrivacyAgree(Context, boolean isAgree)
                try {
                    val agreeMethod = clazz.getMethod("updatePrivacyAgree", Context::class.java, Boolean::class.javaPrimitiveType)
                    agreeMethod.invoke(null, context, true)
                    Log.d(TAG, "调用 $className.updatePrivacyAgree 成功")
                } catch (_: NoSuchMethodException) {}
            } catch (_: ClassNotFoundException) {
                continue
            }
        }
    }

    fun startNavigation(lat: Double, lon: Double, poiName: String?, poiId: String?): String {
        val navi = aMapNavi
            ?: return "error: 高德导航 SDK 未初始化${initError?.let { "（$it）" } ?: ""}"
        return try {
            // 起点传 null，SDK 使用当前 GPS 定位作为起点（初始化时已调用 startGPS）
            if (!poiId.isNullOrEmpty()) {
                val endPoi = NaviPoi(poiName ?: "目的地", null, poiId)
                navi.calculateDriveRoute(null, endPoi, null, PathPlanningStrategy.DRIVING_MULTIPLE_ROUTES_DEFAULT)
                Log.d(TAG, "POI 方式计算路线: poiId=$poiId")
            } else {
                val endList = ArrayList<NaviLatLng>().apply { add(NaviLatLng(lat, lon)) }
                navi.calculateDriveRoute(null, endList, null, PathPlanningStrategy.DRIVING_MULTIPLE_ROUTES_DEFAULT)
                Log.d(TAG, "坐标方式计算路线: lat=$lat, lon=$lon")
            }
            "route_calculating"
        } catch (e: Exception) {
            Log.e(TAG, "计算路线失败", e)
            "error: ${e.message}"
        }
    }

    fun stopNavigation(): String {
        return try {
            aMapNavi?.stopNavi()
            isNavigating = false
            "stopped"
        } catch (e: Exception) {
            "error: ${e.message}"
        }
    }

    // ==================== AMapNaviListener (V11.2.100) ====================

    override fun onInitNaviSuccess() {
        Log.d(TAG, "onInitNaviSuccess")
    }

    override fun onInitNaviFailure() {
        Log.e(TAG, "onInitNaviFailure")
        sendEvent(EVENT_ERROR, mapOf("message" to "导航 SDK 初始化失败"))
    }

    override fun onCalculateRouteSuccess(routeIDs: IntArray?) {
        Log.d(TAG, "onCalculateRouteSuccess(IntArray): ${routeIDs?.contentToString()}")
        sendEvent(EVENT_ROUTE_CALC_SUCCESS, null)
        try {
            aMapNavi?.startNavi(NaviType.GPS)
        } catch (e: Exception) {
            Log.e(TAG, "startNavi 失败", e)
            sendEvent(EVENT_ERROR, mapOf("message" to "开始导航失败: ${e.message}"))
        }
    }

    override fun onCalculateRouteSuccess(routeResult: AMapCalcRouteResult?) {
        Log.d(TAG, "onCalculateRouteSuccess(AMapCalcRouteResult)")
        sendEvent(EVENT_ROUTE_CALC_SUCCESS, null)
        try {
            aMapNavi?.startNavi(NaviType.GPS)
        } catch (e: Exception) {
            Log.e(TAG, "startNavi 失败", e)
            sendEvent(EVENT_ERROR, mapOf("message" to "开始导航失败: ${e.message}"))
        }
    }

    override fun onCalculateRouteFailure(errorCode: Int) {
        Log.e(TAG, "onCalculateRouteFailure(Int): $errorCode")
        sendEvent(EVENT_ROUTE_CALC_FAILURE, mapOf("errorCode" to errorCode))
    }

    override fun onCalculateRouteFailure(routeResult: AMapCalcRouteResult?) {
        val errorCode = routeResult?.errorCode ?: -1
        Log.e(TAG, "onCalculateRouteFailure(AMapCalcRouteResult): $errorCode")
        sendEvent(EVENT_ROUTE_CALC_FAILURE, mapOf("errorCode" to errorCode))
    }

    override fun onStartNavi(type: Int) {
        isNavigating = true
        Log.d(TAG, "onStartNavi: type=$type")
        sendEvent(EVENT_START_NAVI, mapOf("type" to type))
    }

    override fun onNaviInfoUpdate(naviInfo: NaviInfo?) {
        naviInfo ?: return
        sendEvent(EVENT_NAVI_INFO, parseNaviInfo(naviInfo))
    }

    override fun onGetNavigationText(type: Int, text: String?) {
        text ?: return
        Log.d(TAG, "导航播报(Int,String): $text")
        sendEvent(EVENT_NAVI_TEXT, mapOf("text" to text))
    }

    override fun onGetNavigationText(text: String?) {
        text ?: return
        Log.d(TAG, "导航播报(String): $text")
        sendEvent(EVENT_NAVI_TEXT, mapOf("text" to text))
    }

    override fun onArriveDestination() {
        isNavigating = false
        Log.d(TAG, "到达目的地")
        sendEvent(EVENT_ARRIVE_DEST, null)
    }

    override fun onEndEmulatorNavi() {
        isNavigating = false
    }

    override fun onLocationChange(location: AMapNaviLocation?) {}

    override fun onReCalculateRouteForYaw() {
        Log.d(TAG, "偏航重算")
    }

    override fun onReCalculateRouteForTrafficJam() {
        Log.d(TAG, "拥堵重算")
    }

    override fun onArrivedWayPoint(wayPointIndex: Int) {}

    override fun onTrafficStatusUpdate() {}

    override fun onGpsOpenStatus(opened: Boolean) {}

    override fun updateCameraInfo(cameraInfos: Array<out AMapNaviCameraInfo>?) {}

    override fun updateIntervalCameraInfo(
        start: AMapNaviCameraInfo?,
        end: AMapNaviCameraInfo?,
        status: Int
    ) {}

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

    private fun sendEvent(eventType: String, data: Map<String, Any?>?) {
        val event = mutableMapOf<String, Any?>("type" to eventType)
        if (data != null) event.putAll(data)
        eventSink?.success(event)
    }

    fun release() {
        try {
            aMapNavi?.removeAMapNaviListener(this)
            aMapNavi?.stopNavi()
            aMapNavi?.stopGPS()
        } catch (_: Exception) {}
        isNavigating = false
        eventSink = null
    }
}
