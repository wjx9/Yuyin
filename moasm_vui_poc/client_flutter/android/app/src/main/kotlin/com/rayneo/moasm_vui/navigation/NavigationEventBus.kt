package com.rayneo.moasm_vui.navigation

import io.flutter.plugin.common.EventChannel

/**
 * 统一的导航事件桥：把高德导航 SDK（原生自带 UI 模式）的实时事件推送给 Flutter，
 * 供眼镜端 HUD、导航失败回退对话框等消费。
 *
 * 事件通道在 MainActivity 里注册（onListen 时写入 sink），
 * 原生导航页 AmapNaviViewActivity 通过 [push] 推事件，与旧的 AmapNaviManager 无 UI 模式保持同一数据协议。
 */
object NavigationEventBus {

    @Volatile
    var sink: EventChannel.EventSink? = null

    /** 推送一个导航事件；data 可为空。事件格式与既有协议一致：{"type": "...", ...业务字段}。 */
    fun push(type: String, data: Map<String, Any?>? = null) {
        val event = mutableMapOf<String, Any?>("type" to type)
        if (data != null) event.putAll(data)
        sink?.success(event)
    }
}
