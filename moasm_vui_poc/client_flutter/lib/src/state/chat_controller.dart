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
import 'package:url_launcher/url_launcher.dart';

import '../data/chat_api.dart';
import '../data/models.dart';
import '../services/speech_service.dart';
import '../services/tts_service.dart';
import '../services/location_service.dart';
import '../services/calendar_service.dart';
import '../services/reminder_service.dart';
import 'settings_controller.dart';

/// 助手当前状态，驱动 UI（麦克风按钮形态、状态提示语）。
enum AssistantStatus { idle, listening, thinking, speaking }

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
  }

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
      return;
    }
    if (status == AssistantStatus.thinking) return; // 正在等服务端，先不抢麦

    await tts.stop(); // 说话前先把上一条朗读停掉
    final ok = await speech.init(onStatus: _onSpeechStatus, onError: _onSpeechError);
    if (!ok) {
      _pushSystem('语音识别不可用：请检查麦克风权限，或改用下方文字输入。', isError: true);
      return;
    }
    partialText = '';
    status = AssistantStatus.listening;
    notifyListeners();
    await speech.listen(onResult: _onSpeechResult);
  }

  void _onSpeechResult(String text, bool isFinal) {
    partialText = text;
    notifyListeners();
    if (isFinal && text.trim().isNotEmpty) {
      final query = text.trim();
      partialText = '';
      sendText(query);
    }
  }

  void _onSpeechStatus(String s) {
    // 底层听写结束（done/notListening）时，若还停在 listening 态则复位
    if ((s == 'done' || s == 'notListening') && status == AssistantStatus.listening) {
      status = AssistantStatus.idle;
      notifyListeners();
    }
  }

  void _onSpeechError(String err) {
    if (status == AssistantStatus.listening) {
      status = AssistantStatus.idle;
      partialText = '';
      notifyListeners();
    }
  }

  // ---- 发送一轮（语音定稿或手动输入都走这里） ----

  Future<void> sendText(String query) async {
    final q = query.trim();
    if (q.isEmpty || status == AssistantStatus.thinking) return;

    messages.add(ChatTurn(sender: Sender.user, text: q));
    messages.add(const ChatTurn(sender: Sender.assistant, text: '思考中…', pending: true));
    status = AssistantStatus.thinking;
    notifyListeners();

    final pendingIndex = messages.length - 1;
    try {
      String? currentLocation;
      try {
        currentLocation = await location.currentLocation();
      } catch (_) {
        // 定位不可用时继续使用设置页中的固定坐标，不阻塞普通聊天。
        currentLocation = null;
      }

      final locationSource = currentLocation == null ? 'configured_location' : 'mobile_gps';
      final reply = await _api.chat(
        query: q,
        sessionId: settings.config.sessionId,
        location: currentLocation ?? settings.config.location,
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
    }
  }

  /// step 3.1：优先用 orpheus:// 深链拉起网易云音乐 app；失败则退到网页；再不行给提示。
  Future<void> openMusic(MusicInfo music) async {
    for (final url in [music.deeplink, music.webUrl]) {
      if (url.isEmpty) continue;
      try {
        if (await launchUrl(Uri.parse(url), mode: LaunchMode.externalApplication)) return;
      } catch (_) {
        // 换下一个 url 兜底
      }
    }
    _pushSystem('没能拉起网易云音乐，请确认已安装该 app（或稍后重试）。', isError: true);
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
