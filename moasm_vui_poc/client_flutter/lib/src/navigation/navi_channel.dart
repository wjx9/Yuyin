/// 导航 Channel：与 Android 端高德导航通信。
///
/// - EventChannel: 接收导航实时数据（转向、距离、时间等）
/// - 导航启停由悬浮面板 PlatformView 自管理（startNavigation/stopNavigation 不调原生）
library;

import 'dart:async';

import 'package:flutter/foundation.dart';
import 'package:flutter/services.dart';

import 'navi_models.dart';

/// 导航管理器：封装 EventChannel（悬浮面板模式下 MethodChannel 仅用于助手状态转发）。
class NaviChannel extends ChangeNotifier {
  static const String _eventChannelName = 'com.rayneo.moasm_vui/navigation_events';

  static const EventChannel _eventChannel = EventChannel(_eventChannelName);

  /// 导航事件流订阅。
  StreamSubscription<dynamic>? _eventSubscription;

  /// 当前导航状态。
  bool _isNavigating = false;
  bool get isNavigating => _isNavigating;

  /// 当前导航信息。
  NaviInfo? _currentNaviInfo;
  NaviInfo? get currentNaviInfo => _currentNaviInfo;

  /// 导航播报文本（用于 TTS）。
  String? _lastNaviText;
  String? get lastNaviText => _lastNaviText;

  /// 错误信息。
  String? _lastError;
  String? get lastError => _lastError;

  /// 导航事件流（外部可监听）。
  final StreamController<NaviEvent> _eventController = StreamController<NaviEvent>.broadcast();
  Stream<NaviEvent> get eventStream => _eventController.stream;

  /// 初始化：开始监听导航事件。
  void initialize() {
    _eventSubscription = _eventChannel.receiveBroadcastStream().listen(
      _onEvent,
      onError: _onError,
      cancelOnError: false,
    );
    debugPrint('NaviChannel 已初始化');
  }

  /// 处理导航事件。
  void _onEvent(dynamic event) {
    if (event is! Map) return;
    final map = Map<String, dynamic>.from(event);
    final naviEvent = NaviEvent.fromMap(map);

    // 更新状态
    switch (naviEvent.type) {
      case NaviEventType.naviInfo:
        _currentNaviInfo = NaviInfo.fromMap(map);
        break;
      case NaviEventType.startNavi:
        _isNavigating = true;
        break;
      case NaviEventType.arrivedDestination:
        _isNavigating = false;
        break;
      case NaviEventType.naviEnd:
        _isNavigating = false;
        _currentNaviInfo = null;
        break;
      case NaviEventType.routeCalcFailure:
        _lastError = '路线计算失败: ${map['errorCode']}';
        break;
      case NaviEventType.naviText:
        _lastNaviText = map['text'] as String?;
        break;
      case NaviEventType.error:
        _lastError = map['message'] as String? ?? '导航错误';
        break;
      default:
        break;
    }

    // 推送事件
    _eventController.add(naviEvent);
    notifyListeners();
  }

  /// 处理事件流错误。
  void _onError(Object error) {
    _lastError = error.toString();
    debugPrint('NaviChannel 事件流错误: $error');
    notifyListeners();
  }

  /// 开始导航（悬浮面板模式）。
  ///
  /// 不再调用原生拉起全屏 Activity；设置导航状态后由 UI 层显示悬浮面板，
  /// 悬浮面板内的 PlatformView（AMapNaviView）自行完成算路与导航。
  /// 导航实时事件仍通过 EventChannel 从原生推回。
  Future<String> startNavigation({
    required double lat,
    required double lon,
    String? poiName,
    String? poiId,
  }) async {
    _isNavigating = true;
    _lastError = null;
    notifyListeners();
    debugPrint('NaviChannel.startNavigation（悬浮模式）: lat=$lat, lon=$lon, poiName=$poiName');
    return 'started';
  }

  /// 停止导航（悬浮面板模式）。
  ///
  /// 清除导航状态；UI 层监听到状态变化后隐藏悬浮面板，
  /// PlatformView.dispose() 会停止导航并推送 navi_end 事件。
  Future<String> stopNavigation() async {
    _isNavigating = false;
    _currentNaviInfo = null;
    notifyListeners();
    debugPrint('NaviChannel.stopNavigation（悬浮模式）');
    return 'stopped';
  }

  /// 释放资源。
  @override
  void dispose() {
    _eventSubscription?.cancel();
    _eventSubscription = null;
    _eventController.close();
    super.dispose();
  }
}
