package com.rayneo.moasm_vui.navigation

import android.app.Activity
import android.app.AlertDialog
import android.content.Context
import android.content.Intent
import android.media.AudioManager
import android.media.ToneGenerator
import android.os.Build
import android.os.Bundle
import android.os.VibrationEffect
import android.os.Vibrator
import android.util.Log
import android.view.MotionEvent
import android.view.View
import android.view.inputmethod.InputMethodManager
import android.widget.EditText
import android.widget.ImageButton
import android.widget.TextView
import android.widget.Toast
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
import com.rayneo.moasm_vui.R
import io.flutter.embedding.engine.FlutterEngineCache
import io.flutter.plugin.common.MethodChannel

/**
 * 高德导航自带界面（AMapNaviView）承载页。
 *
 * 手机端用高德原生导航界面替代 Flutter 自绘导航 UI；
 * 导航实时事件（转向/距离/时间/播报/到达/失败）仍通过 [NavigationEventBus] 推送给 Flutter，
 * 保证眼镜端 HUD 与失败回退对话框的数据通道不中断。
 *
 * 数据流：Flutter startNavigation → MainActivity 启动本页 → AMapNaviView 自带 UI 渲染手机端；
 * AMapNaviListener 回调 → NavigationEventBus → Flutter NaviChannel（EventChannel）。
 */
class AmapNaviViewActivity : Activity(), AMapNaviViewListener, AMapNaviListener {

    companion object {
        private const val TAG = "AmapNaviViewActivity"

        /** 与 MainActivity 缓存 FlutterEngine 用的同一 ID。 */
        const val ENGINE_ID = "moasm_vui_engine"

        /** native→Flutter 通道：唤起语音助手。 */
        private const val ASSISTANT_CHANNEL = "com.rayneo.moasm_vui/assistant"

        const val EXTRA_LAT = "extra_lat"
        const val EXTRA_LON = "extra_lon"
        const val EXTRA_POI_NAME = "extra_poi_name"
        const val EXTRA_POI_ID = "extra_poi_id"

        /** 当前打开的原生导航页（供 Flutter 端"停止导航"时关闭它）。 */
        @Volatile
        var current: AmapNaviViewActivity? = null

        /** 构造启动 Intent。 */
        fun launchIntent(
            context: Context,
            lat: Double,
            lon: Double,
            poiName: String?,
            poiId: String?
        ): Intent = Intent(context, AmapNaviViewActivity::class.java).apply {
            putExtra(EXTRA_LAT, lat)
            putExtra(EXTRA_LON, lon)
            putExtra(EXTRA_POI_NAME, poiName)
            putExtra(EXTRA_POI_ID, poiId)
        }
    }

    private lateinit var naviView: AMapNaviView
    private var aMapNavi: AMapNavi? = null
    private lateinit var micButton: ImageButton
    private lateinit var naviSpeechText: TextView
    private lateinit var naviInput: EditText
    private lateinit var sendButton: ImageButton

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        current = this
        callPrivacyCompliance(applicationContext)
        setContentView(R.layout.activity_amap_navi_view)

        naviView = findViewById(R.id.navi_view)
        naviView.onCreate(savedInstanceState)
        naviView.setAMapNaviViewListener(this)

        aMapNavi = AMapNavi.getInstance(this)
        aMapNavi?.addAMapNaviListener(this)
        aMapNavi?.startGPS()

        // 底部输入栏：文本输入（可靠）+ 麦克风（按下说话，可选）+ 发送
        naviInput = findViewById(R.id.navi_input)
        micButton = findViewById(R.id.mic_button)
        sendButton = findViewById(R.id.send_button)
        naviSpeechText = findViewById(R.id.navi_speech_text)

        // 麦克风：按下说话、松手结束
        micButton.setOnTouchListener { _, event ->
            when (event.action) {
                MotionEvent.ACTION_DOWN -> { startPushToTalk(); true }
                MotionEvent.ACTION_UP, MotionEvent.ACTION_CANCEL -> { stopPushToTalk(); true }
                else -> true
            }
        }

        // 发送按钮：把输入框文字发给语音助手
        sendButton.setOnClickListener { sendInputText() }

        // 键盘"发送"键也触发发送
        naviInput.setOnEditorActionListener { _, actionId, _ ->
            if (actionId == android.view.inputmethod.EditorInfo.IME_ACTION_SEND) {
                sendInputText()
                true
            } else false
        }
    }

    /** 发送输入框文字给语音助手（导航途中可靠的交互方式）。 */
    private fun sendInputText() {
        val text = naviInput.text.toString().trim()
        if (text.isEmpty()) return
        naviInput.setText("")
        hideKeyboard()
        invokeAssistantWithText("sendNaviText", text)
    }

    /** 收起软键盘。 */
    private fun hideKeyboard() {
        try {
            val imm = getSystemService(Context.INPUT_METHOD_SERVICE) as? InputMethodManager
            imm?.hideSoftInputFromWindow(naviInput.windowToken, 0)
        } catch (e: Exception) {
            Log.d(TAG, "hideKeyboard: ${e.message}")
        }
    }

    /** 按下说话：即时反馈（高亮/震动/提示音），静音导航语音，并开始听写。 */
    private fun startPushToTalk() {
        setAssistantActive(true)
        // 即时反馈：按钮高亮 + 震动 + 提示音
        micButton.setBackgroundResource(R.drawable.mic_circle_active)
        vibrate(40)
        beep()
        invokeAssistant("startListening")
    }

    /** 松手结束：停止听写并定稿。 */
    private fun stopPushToTalk() {
        invokeAssistant("stopListening")
    }

    /** 向 Flutter 语音助手发送指令；引擎不可用时给提示并复位。 */
    private fun invokeAssistant(method: String) {
        invokeAssistantWithText(method, null)
    }

    /** 向 Flutter 语音助手发送带文本的指令（如 sendNaviText）。 */
    private fun invokeAssistantWithText(method: String, text: String?) {
        try {
            val engine = FlutterEngineCache.getInstance().get(ENGINE_ID)
            val messenger = engine?.dartExecutor?.binaryMessenger
            if (messenger == null) {
                Log.w(TAG, "Flutter 引擎不可用，无法唤起语音助手")
                Toast.makeText(this, "语音助手不可用，请返回主界面", Toast.LENGTH_SHORT).show()
                setAssistantActive(false)
                resetMicUi()
                return
            }
            MethodChannel(messenger, ASSISTANT_CHANNEL).invokeMethod(method, text)
        } catch (e: Exception) {
            Log.e(TAG, "唤起语音助手失败", e)
            Toast.makeText(this, "唤起语音助手失败", Toast.LENGTH_SHORT).show()
            setAssistantActive(false)
            resetMicUi()
        }
    }

    /**
     * 显示语音识别的实时文字（由 Flutter 在听写过程中回传）。
     * text 为空/空串时隐藏并复位按钮为待命状态。
     */
    fun showSpeechText(text: String?) {
        runOnUiThread {
            val hasText = !text.isNullOrBlank()
            if (hasText) {
                naviSpeechText.text = text
                naviSpeechText.visibility = View.VISIBLE
                micButton.setBackgroundResource(R.drawable.mic_circle_active)
            } else {
                naviSpeechText.text = ""
                naviSpeechText.visibility = View.GONE
                resetMicUi()
            }
        }
    }

    /** 复位麦克风按钮为待命样式。 */
    private fun resetMicUi() {
        micButton.setBackgroundResource(R.drawable.mic_circle)
    }

    /** 短震动反馈（兼容不同系统版本）。 */
    private fun vibrate(ms: Long) {
        try {
            val vibrator = getSystemService(Context.VIBRATOR_SERVICE) as? Vibrator ?: return
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                vibrator.vibrate(VibrationEffect.createOneShot(ms, VibrationEffect.DEFAULT_AMPLITUDE))
            } else {
                @Suppress("DEPRECATION")
                vibrator.vibrate(ms)
            }
        } catch (e: Exception) {
            Log.d(TAG, "震动不可用: ${e.message}")
        }
    }

    /** 提示音反馈：提示用户语音已开始听写。 */
    private fun beep() {
        try {
            val tone = ToneGenerator(AudioManager.STREAM_MUSIC, 80)
            tone.startTone(ToneGenerator.TONE_PROP_BEEP, 150)
            // 短促提示音，播完即释放
            android.os.Handler(mainLooper).postDelayed({ tone.release() }, 200)
        } catch (e: Exception) {
            Log.d(TAG, "提示音不可用: ${e.message}")
        }
    }

    /**
     * 助手激活状态：激活时让导航语音让位（停止并关闭内置播报），
     * 避免与助手的听写/播报冲突；助手空闲时恢复导航语音。
     */
    fun setAssistantActive(active: Boolean) {
        runOnUiThread {
            try {
                if (active) {
                    aMapNavi?.stopSpeak()
                }
                aMapNavi?.setUseInnerVoice(!active)
            } catch (e: Exception) {
                Log.e(TAG, "setAssistantActive 失败", e)
            }
        }
    }

    /**
     * 离开导航界面前的确认：询问是否结束本次导航，
     * 防止误触返回/误触发语音导致导航被意外结束。
     */
    fun confirmExitNavigation() {
        if (isFinishing || isDestroyed) return
        runOnUiThread {
            AlertDialog.Builder(this)
                .setTitle("结束导航")
                .setMessage("是否结束本次导航？")
                .setPositiveButton("结束导航") { _, _ -> finishNavigation() }
                .setNegativeButton("继续导航", null)
                .setCancelable(true)
                .show()
        }
    }

    /** 真正结束导航：通知 Flutter 并关闭页面（onDestroy 会停止导航）。 */
    private fun finishNavigation() {
        NavigationEventBus.push("navi_end", null)
        finish()
    }

    override fun onResume() {
        super.onResume()
        naviView.onResume()
    }

    override fun onPause() {
        super.onPause()
        naviView.onPause()
    }

    override fun onDestroy() {
        current = null
        // 退出导航状态：停止播报与导航、移除监听，避免导航在后台继续运行
        try { aMapNavi?.stopSpeak() } catch (e: Exception) { Log.d(TAG, "stopSpeak: ${e.message}") }
        try { aMapNavi?.stopNavi() } catch (e: Exception) { Log.d(TAG, "stopNavi: ${e.message}") }
        try { aMapNavi?.removeAMapNaviListener(this) } catch (e: Exception) { Log.d(TAG, "removeListener: ${e.message}") }
        naviView.onDestroy()
        aMapNavi = null
        super.onDestroy()
    }

    /** 系统返回键：也走"是否结束本次导航"确认，避免误触结束导航。 */
    override fun onBackPressed() {
        confirmExitNavigation()
    }

    /** 隐私合规（与 AmapNaviManager 一致，用反射兼容不同 SDK 版本）。 */
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
                    Log.d(TAG, "调用 $className.updatePrivacyShow 成功")
                } catch (_: NoSuchMethodException) {}
                try {
                    clazz.getMethod(
                        "updatePrivacyAgree",
                        Context::class.java,
                        Boolean::class.javaPrimitiveType
                    ).invoke(null, context, true)
                    Log.d(TAG, "调用 $className.updatePrivacyAgree 成功")
                } catch (_: NoSuchMethodException) {}
            } catch (_: ClassNotFoundException) {
                // ignore
            }
        }
    }

    // ==================== AMapNaviViewListener ====================

    /** 导航视图加载完成后，开始算路并启动导航。 */
    override fun onNaviViewLoaded() {
        Log.d(TAG, "onNaviViewLoaded")
        val lat = intent.getDoubleExtra(EXTRA_LAT, 0.0)
        val lon = intent.getDoubleExtra(EXTRA_LON, 0.0)
        val poiName = intent.getStringExtra(EXTRA_POI_NAME)
        val poiId = intent.getStringExtra(EXTRA_POI_ID)
        val navi = aMapNavi ?: return
        if (!poiId.isNullOrEmpty()) {
            navi.calculateDriveRoute(
                null,
                NaviPoi(poiName ?: "目的地", null, poiId),
                null,
                PathPlanningStrategy.DRIVING_MULTIPLE_ROUTES_DEFAULT
            )
            Log.d(TAG, "POI 方式计算路线: poiId=$poiId")
        } else {
            val end = ArrayList<NaviLatLng>().apply { add(NaviLatLng(lat, lon)) }
            navi.calculateDriveRoute(null, end, null, PathPlanningStrategy.DRIVING_MULTIPLE_ROUTES_DEFAULT)
            Log.d(TAG, "坐标方式计算路线: lat=$lat, lon=$lon")
        }
    }

    override fun onNaviSetting() {}
    override fun onNaviCancel() { confirmExitNavigation() }
    override fun onNaviBackClick(): Boolean { confirmExitNavigation(); return true }
    override fun onNaviMapMode(mode: Int) {}
    override fun onNaviTurnClick() {}
    override fun onNextRoadClick() {}
    override fun onScanViewButtonClick() {}
    override fun onLockMap(isLock: Boolean) {}
    override fun onMapTypeChanged(type: Int) {}
    override fun onNaviViewShowMode(mode: Int) {}
    override fun onStopSpeaking() {}
    override fun onViewTypeChanged(type: AmapPageType) {}
    override fun onAMapNaviViewExit() { confirmExitNavigation() }
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
        try {
            aMapNavi?.startNavi(NaviType.GPS)
        } catch (e: Exception) {
            Log.e(TAG, "startNavi 失败", e)
            NavigationEventBus.push("error", mapOf("message" to "开始导航失败: ${e.message}"))
        }
    }

    override fun onCalculateRouteSuccess(routeResult: AMapCalcRouteResult?) {
        Log.d(TAG, "onCalculateRouteSuccess(AMapCalcRouteResult)")
        NavigationEventBus.push("route_calc_success", null)
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
        Log.d(TAG, "导航播报(Int,String): $text")
        NavigationEventBus.push("navi_text", mapOf("text" to text))
    }

    override fun onGetNavigationText(text: String?) {
        text ?: return
        Log.d(TAG, "导航播报(String): $text")
        NavigationEventBus.push("navi_text", mapOf("text" to text))
    }

    override fun onArriveDestination() {
        Log.d(TAG, "到达目的地")
        NavigationEventBus.push("arrive_destination", null)
        finish()
    }

    override fun onEndEmulatorNavi() {}

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
}
