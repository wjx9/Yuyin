/// ChatController：客户端"大脑外的协调者"（业务大脑在服务端）。
///
/// 串起一轮语音助手的完整链路（与 client_py 的单轮等价，只是多了端侧语音 I/O）：
///   按麦克风 → SpeechService 听写(ASR) → 得到文本 → ChatApi.chat 发给服务端
///   → 收到 {text,intent} → 上屏气泡 → TtsService 朗读
///
/// 类比 Android：ChangeNotifier ≈ ViewModel + LiveData；UI 监听本类的状态重绘。
library;

import 'dart:async';

import 'package:flutter/foundation.dart';
import 'package:flutter/services.dart';
import 'package:url_launcher/url_launcher.dart';

import '../data/chat_api.dart';
import '../data/models.dart';
import '../services/speech_service.dart';
import '../services/tts_service.dart';
import '../services/location_service.dart';
import '../services/calendar_service.dart';
import '../services/reminder_service.dart';
import '../navigation/navi_channel.dart';
import '../navigation/navi_models.dart';
import 'settings_controller.dart';

/// 助手当前状态，驱动 UI（麦克风按钮形态、状态提示语）。
enum AssistantStatus { idle, listening, thinking, speaking }

/// 待开始的导航信息。
class PendingNavigation {
  final double lat;
  final double lon;
  final String poiName;
  final String? poiId;

  const PendingNavigation({
    required this.lat,
    required this.lon,
    required this.poiName,
    this.poiId,
  });
}

/// 导航失败信息，用于弹出回退对话框。
class NaviFailure {
  final String reason;
  final NavCommand command;

  const NaviFailure({required this.reason, required this.command});
}

class ChatController extends ChangeNotifier {
  final SettingsController settings;
  final SpeechService speech;
  final TtsService tts;
  final LocationService location;
  final CalendarService calendar = CalendarService();
  final ReminderService reminder = ReminderService();

  ChatController({
    required this.settings,
    required this.speech,
    required this.tts,
    required this.location,
  }) {
    _api = _buildApi();
    settings.addListener(_onSettingsChanged);
    naviChannel.initialize();
    // 监听导航事件：失败触发回退对话框；结束/到达自动清除悬浮面板
    naviChannel.eventStream.listen((event) {
      if (event.type == NaviEventType.routeCalcFailure ||
          event.type == NaviEventType.error) {
        final reason = event.data['message'] as String? ??
            '错误码: ${event.data['errorCode'] ?? '未知'}';
        // 保存最近一次导航命令用于回退
        if (_lastNavCommand != null) {
          naviFailure = NaviFailure(reason: reason, command: _lastNavCommand!);
          notifyListeners();
        }
      } else if (event.type == NaviEventType.naviEnd ||
          event.type == NaviEventType.arrivedDestination) {
        // 导航结束（用户关闭面板或到达目的地）：自动隐藏悬浮面板
        if (pendingNavigation != null) {
          pendingNavigation = null;
          notifyListeners();
        }
      }
    });
  }

  /// 最近一次导航命令（用于失败后回退）。
  NavCommand? _lastNavCommand;

  Future<void> openCalendar() async {
    if (!await calendar.open()) {
      _pushSystem('无法打开系统日历，请确认手机已安装日历应用。', isError: true);
    }
  }

  // ---- 对外状态（UI 读取） ----
  final List<ChatTurn> messages = [];
  AssistantStatus status = AssistantStatus.idle;
  String partialText = ''; // 听写实时草稿（还没定稿）
  List<String> capabilities = []; // /health 返回的已启用能力
  String? connectionError; // 连不上服务端时的提示

  late ChatApi _api;

  /// 与 Android 原生通信的 Platform Channel，用于执行导航控制指令。
  static const MethodChannel _navChannel = MethodChannel('com.rayneo.moasm_vui/navigation');

  /// 导航管理器（高德导航 SDK 无 UI 模式）。
  final NaviChannel naviChannel = NaviChannel();

  /// 待开始的导航信息（非空时表示需要跳转到导航页面）。
  PendingNavigation? pendingNavigation;

  /// 导航失败信息（非空时表示需要弹出回退对话框）。
  NaviFailure? naviFailure;

  bool get isBusy => status == AssistantStatus.thinking;

  ChatApi _buildApi() => ChatApi(
    baseUrl: settings.config.serverUrl,
    authToken: settings.config.authToken,
    userId: settings.config.userId,
  );

  void _onSettingsChanged() {
    // 服务端地址/鉴权可能变了，重建 api 并重新探活
    _api.dispose();
    _api = _buildApi();
    refreshHealth();
  }

  /// 探活：顺带取回服务端已启用的能力清单。启动时与改设置后调用。
  Future<void> refreshHealth() async {
    if (!settings.config.hasServer) {
      connectionError = '尚未配置服务端地址，请到设置里填写';
      capabilities = [];
      notifyListeners();
      return;
    }
    try {
      final health = await _api.health();
      capabilities = health.capabilities;
      connectionError = null;
    } on ApiException catch (e) {
      connectionError = e.message;
      capabilities = [];
    }
    notifyListeners();
  }

  // ---- 语音输入 ----

  /// 麦克风按钮：未在听就开始听，正在听就停止（停止会触发一次定稿回调）。
  Future<void> toggleListening() async {
    if (status == AssistantStatus.listening) {
      await speech.stop();
      // 停止听写后助手空闲，恢复导航语音
      await _setAssistantActive(false);
      return;
    }
    if (status == AssistantStatus.thinking) return; // 正在等服务端，先不抢麦

    await tts.stop(); // 说话前先把上一条朗读停掉
    final ok = await speech.init(
      onStatus: _onSpeechStatus,
      onError: _onSpeechError,
    );
    if (!ok) {
      _pushSystem('语音识别不可用：请检查麦克风权限，或改用下方文字输入。', isError: true);
      return;
    }
    partialText = '';
    status = AssistantStatus.listening;
    notifyListeners();
    // 助手开始听写：通知原生导航页让导航语音让位
    await _setAssistantActive(true);
    await speech.listen(onResult: _onSpeechResult);
  }

  /// push-to-talk「按下说话」：确保进入听写（已在听则忽略）。
  Future<void> startListening() async {
    if (status == AssistantStatus.listening || status == AssistantStatus.thinking) {
      return;
    }
    await toggleListening();
  }

  /// push-to-talk「松手结束」：停止听写并定稿（触发识别结果发送）。
  Future<void> stopListening() async {
    if (status == AssistantStatus.listening) {
      await toggleListening(); // 停止听写，触发 final → sendText
    }
  }

  void _onSpeechResult(String text, bool isFinal) {
    partialText = text;
    notifyListeners();
    // 导航页实时显示识别文字（无导航页时为 no-op）
    _syncNaviSpeechText(text);
    if (isFinal) {
      // 输入完成：清空导航页显示
      _syncNaviSpeechText('');
      if (text.trim().isNotEmpty) {
        final query = text.trim();
        partialText = '';
        sendText(query);
      }
    }
  }

  void _onSpeechStatus(String s) {
    // 底层听写结束（done/notListening）时，若还停在 listening 态则复位
    if ((s == 'done' || s == 'notListening') &&
        status == AssistantStatus.listening) {
      status = AssistantStatus.idle;
      notifyListeners();
      _setAssistantActive(false);
      _syncNaviSpeechText('');
    }
  }

  void _onSpeechError(String err) {
    if (status == AssistantStatus.listening) {
      status = AssistantStatus.idle;
      partialText = '';
      notifyListeners();
      _setAssistantActive(false);
      _syncNaviSpeechText('');
    }
  }

  // ---- 发送一轮（语音定稿或手动输入都走这里） ----

  Future<void> sendText(String query) async {
    final q = query.trim();
    if (q.isEmpty || status == AssistantStatus.thinking) return;

    // 助手开始处理：导航途中让导航语音让位（文本输入路径也需要）
    await _setAssistantActive(true);

    messages.add(ChatTurn(sender: Sender.user, text: q));
    messages.add(
      const ChatTurn(sender: Sender.assistant, text: '思考中…', pending: true),
    );
    status = AssistantStatus.thinking;
    notifyListeners();

    final pendingIndex = messages.length - 1;
    try {
      String? selectedLocation;
      String locationSource = 'none';
      try {
        final gpsLocation = await location.currentLocation();
        if (gpsLocation != null && gpsLocation.trim().isNotEmpty) {
          selectedLocation = gpsLocation.trim();
          locationSource = 'mobile_gps';
        }
      } catch (error) {
        // GPS 读取失败时继续尝试设置页的固定坐标，不阻塞普通聊天。
        debugPrint('GPS unavailable, fallback to configured location: $error');
      }
      if (selectedLocation == null) {
        final configuredLocation = settings.config.location?.trim();
        if (configuredLocation != null && configuredLocation.isNotEmpty) {
          selectedLocation = configuredLocation;
          locationSource = 'configured_location';
          debugPrint('Using configured location: $selectedLocation');
        }
      }
      final reply = await _api.chat(
        query: q,
        sessionId: settings.config.sessionId,
        location: selectedLocation,
        locationSource: locationSource,
      );
      messages[pendingIndex] = ChatTurn(
        sender: Sender.assistant,
        text: reply.text,
        intent: reply.intent,
        music: reply.music,
        a2ui: reply.a2ui,
      );
      connectionError = null;
      status = AssistantStatus.speaking;
      notifyListeners();

      // step 3.1：命中点歌 → 拉起网易云音乐 app 播放（在线播放不在服务端本机，跳转到官方 app）。
      // 不 await，避免跳转卡住本轮；气泡上也留了按钮可手动重开。
      if (reply.music != null) unawaited(openMusic(reply.music!));
      if (reply.calendarEvent != null) {
        debugPrint(
          'Calendar action received: title=${reply.calendarEvent!.title}, '
          'start=${reply.calendarEvent!.start.toIso8601String()}, '
          'end=${reply.calendarEvent!.end.toIso8601String()}',
        );
        final opened = await calendar.create(reply.calendarEvent!);
        if (!opened) _pushSystem('无法打开日历创建页面，请确认手机已安装日历应用。', isError: true);
      }
      if (reply.scheduleAction != null) {
        final action = reply.scheduleAction!;
        debugPrint(
          'Schedule action received: action=${action.action}, title=${action.title}, '
          'trigger=${action.triggerTime?.toIso8601String()}, duration=${action.durationSeconds}',
        );
        final opened = await reminder.create(action);
        if (!opened) {
          _pushSystem(
            action.action == 'reminder'
                ? '无法打开日历提醒页面，请确认手机已安装日历应用。'
                : '无法打开系统时钟页面，请确认手机支持闹钟或倒计时功能。',
            isError: true,
          );
        }
      }

      // 导航控制指令：服务端下发 nav_command，调用 Android 原生执行真正导航。
      if (reply.navCommand != null) {
        unawaited(_executeNavCommand(reply.navCommand!));
      }

      await tts.speak(reply.text); // awaitSpeakCompletion=true，播完才返回
    } on ApiException catch (e) {
      messages[pendingIndex] = ChatTurn(
        sender: Sender.assistant,
        text: e.message,
        isError: true,
      );
    } finally {
      status = AssistantStatus.idle;
      notifyListeners();
      // 整轮结束：助手回到空闲，恢复导航语音
      _setAssistantActive(false);
    }
  }

  /// step 3.1：优先用 orpheus:// 深链拉起网易云音乐 app；失败则退到网页；再不行给提示。
  Future<void> openMusic(MusicInfo music) async {
    for (final url in [music.deeplink, music.webUrl]) {
      if (url.isEmpty) continue;
      try {
        if (await launchUrl(
          Uri.parse(url),
          mode: LaunchMode.externalApplication,
        )) {
          return;
        }
      } catch (_) {
        // 换下一个 url 兜底
      }
    }
    _pushSystem('没能拉起网易云音乐，请确认已安装该 app（或稍后重试）。', isError: true);
  }

  /// 执行导航控制指令：通过 Platform Channel 调用 Android 原生。
  ///
  /// cmd=4（设置终点/开始导航）：使用高德导航 SDK 无 UI 模式，跳转到自定义导航页面
  /// cmd=2（停止导航）：停止当前导航
  /// 其他指令：透传 amap_execute_json 给 AmapLinkClient（需集成 SDK）
  Future<void> _executeNavCommand(NavCommand cmd) async {
    debugPrint(
      'NavCommand received: cmd=${cmd.cmd} (${cmd.cmdName}), '
      'poi=${cmd.poiName}, lon=${cmd.lon}, lat=${cmd.lat}',
    );

    // cmd=4（开始导航）：使用高德导航 SDK 无 UI 模式，跳转到自定义导航页面
    if (cmd.cmd == 4 && cmd.lon != null && cmd.lat != null) {
      _lastNavCommand = cmd;
      final poiName = cmd.poiName ?? '目的地';
      final poiId = cmd.poiId;

      // 设置待导航信息，UI 层监听后跳转到导航页面
      pendingNavigation = PendingNavigation(
        lat: cmd.lat!,
        lon: cmd.lon!,
        poiName: poiName,
        poiId: poiId,
      );
      notifyListeners();

      // 调用高德导航 SDK 开始导航
      try {
        final result = await naviChannel.startNavigation(
          lat: cmd.lat!,
          lon: cmd.lon!,
          poiName: poiName,
          poiId: poiId,
        );
        debugPrint('导航启动结果: $result');
        if (result.startsWith('error:')) {
          _pushSystem('导航启动失败：${result.substring(6)}', isError: true);
        }
      } catch (e) {
        debugPrint('导航启动失败: $e');
        _pushSystem('导航启动失败：$e', isError: true);
      }
      return;
    }

    // cmd=2（停止导航）：停止导航
    if (cmd.cmd == 2) {
      await naviChannel.stopNavigation();
      pendingNavigation = null;
      notifyListeners();
      return;
    }

    // 其他指令：回退到旧的 executeNavCommand 方式
    await _executeNavCommandLegacy(cmd);
  }

  /// 用户选择回退到 Intent 方式（打开高德地图 App）。
  Future<void> fallbackToIntent() async {
    final cmd = naviFailure?.command;
    naviFailure = null;
    notifyListeners();
    if (cmd != null) {
      await _executeNavCommandLegacy(cmd);
    }
  }

  /// 用户取消回退。
  void cancelFallback() {
    naviFailure = null;
    notifyListeners();
  }

  /// 用户主动关闭悬浮导航面板：清除待导航信息，停止导航。
  /// PlatformView.dispose() 会推送 navi_end 事件，这里先清状态避免面板闪烁。
  Future<void> clearPendingNavigation() async {
    if (pendingNavigation == null) return;
    pendingNavigation = null;
    notifyListeners();
    await naviChannel.stopNavigation();
  }

  /// 旧版导航指令执行（Intent 方式，兼容）。
  Future<void> _executeNavCommandLegacy(NavCommand cmd) async {
    try {
      final result = await _navChannel.invokeMethod<String>('executeNavCommand', {
        'cmd': cmd.cmd,
        'requestId': cmd.requestId,
        'data': cmd.data,
        'amapExecuteJson': cmd.amapExecuteJson,
      });
      debugPrint('NavCommand result: $result');
    } on PlatformException catch (e) {
      debugPrint('NavCommand failed: ${e.code} - ${e.message}');
      _pushSystem(
        '导航执行失败：${e.message ?? e.code}。请确认手机已安装高德地图 App。',
        isError: true,
      );
    } on MissingPluginException {
      debugPrint('NavChannel not implemented on this platform');
    } catch (e) {
      debugPrint('NavCommand unexpected error: $e');
    }
  }

  /// 通知原生导航页：语音助手激活/空闲。激活时让导航语音让位，
  /// 避免与助手的听写/播报冲突；空闲时恢复导航语音。
  Future<void> _setAssistantActive(bool active) async {
    try {
      await _navChannel.invokeMethod('setAssistantActive', active);
    } catch (e) {
      debugPrint('setAssistantActive failed: $e');
    }
  }

  /// 把听写的实时文字同步给导航页显示（无导航页时为 no-op）。
  Future<void> _syncNaviSpeechText(String text) async {
    try {
      await _navChannel.invokeMethod('naviSpeechText', text);
    } catch (e) {
      debugPrint('naviSpeechText failed: $e');
    }
  }

  /// 用户主动打断当前朗读。
  Future<void> stopSpeaking() async {
    await tts.stop();
    if (status == AssistantStatus.speaking) {
      status = AssistantStatus.idle;
      notifyListeners();
    }
  }

  void clear() {
    messages.clear();
    partialText = '';
    notifyListeners();
  }

  void _pushSystem(String text, {bool isError = false}) {
    messages.add(ChatTurn(sender: Sender.system, text: text, isError: isError));
    notifyListeners();
  }

  @override
  void dispose() {
    settings.removeListener(_onSettingsChanged);
    _api.dispose();
    super.dispose();
  }
}
