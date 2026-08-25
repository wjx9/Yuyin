/// 传输与 UI 共用的数据模型。
library;

/// 一条聊天气泡的来源。
enum Sender { user, assistant, system }

/// music_play 命中时，服务端在 data 里回传的可播放信息（step 3.1：端侧拉起网易云 app）。
///
/// 服务端 data 形如：
///   {"kind":"music","name":"晴天","artist":"周杰伦",
///    "deeplink":"orpheus://song/{id}","webUrl":"https://music.163.com/#/song?id={id}"}
class MusicInfo {
  final String name;
  final String artist;
  final String deeplink; // 网易云 app 的 URL scheme（首选）
  final String webUrl; // 网页兜底（app 未安装时）

  const MusicInfo({
    required this.name,
    required this.artist,
    required this.deeplink,
    required this.webUrl,
  });

  String get label => artist.isEmpty ? name : '$name - $artist';

  /// 从 /chat 响应的 data 段解析；非音乐或无深链则返回 null。
  static MusicInfo? tryFrom(Object? data) {
    if (data is! Map || data['kind'] != 'music') return null;
    final deeplink = (data['deeplink'] ?? '') as String;
    final webUrl = (data['webUrl'] ?? '') as String;
    if (deeplink.isEmpty && webUrl.isEmpty) return null;
    return MusicInfo(
      name: (data['name'] ?? '') as String,
      artist: (data['artist'] ?? '') as String,
      deeplink: deeplink,
      webUrl: webUrl,
    );
  }
}

class CalendarEvent {
  final String title;
  final DateTime start;
  final DateTime end;
  final String location;
  final String description;

  const CalendarEvent({
    required this.title,
    required this.start,
    required this.end,
    this.location = '',
    this.description = '',
  });

  static CalendarEvent? tryFrom(Object? data) {
    if (data is! Map || data['kind'] != 'calendar_event') return null;
    try {
      final title = data['title'];
      final start = data['start_time'];
      final end = data['end_time'];
      if (title is! String || title.trim().isEmpty || start is! String || end is! String) return null;
      return CalendarEvent(
        title: title,
        start: DateTime.parse(start),
        end: DateTime.parse(end),
        location: data['location'] is String ? data['location'] as String : '',
        description: data['description'] is String ? data['description'] as String : '',
      );
    } on FormatException {
      return null;
    }
  }
}

class ScheduleAction {
  final String action;
  final String title;
  final DateTime? triggerTime;
  final DateTime? endTime;
  final int? durationSeconds;
  final String description;

  const ScheduleAction({
    required this.action,
    required this.title,
    this.triggerTime,
    this.endTime,
    this.durationSeconds,
    this.description = '',
  });

  static ScheduleAction? tryFrom(Object? data) {
    if (data is! Map || data['kind'] != 'schedule_action') return null;
    final action = data['action'];
    final title = data['title'];
    if (action is! String || title is! String || action.isEmpty || title.isEmpty) return null;
    try {
      final triggerRaw = data['trigger_time'];
      final endRaw = data['end_time'];
      final durationRaw = data['duration_seconds'];
      return ScheduleAction(
        action: action,
        title: title,
        triggerTime: triggerRaw is String ? DateTime.parse(triggerRaw) : null,
        endTime: endRaw is String ? DateTime.parse(endRaw) : null,
        durationSeconds: durationRaw is int ? durationRaw : null,
        description: data['description'] is String ? data['description'] as String : '',
      );
    } on FormatException {
      return null;
    }
  }
}

/// UI 层一条消息（聊天气泡）。assistant 在等服务端时先放一条 pending 占位。
class ChatTurn {
  final Sender sender;
  final String text;

  /// 仅 assistant：本轮命中的意图 id（如 amap / tripnow_public），用于在气泡上标注。
  final String? intent;

  /// assistant 占位中（"思考中…"）；收到回复后替换成正式内容。
  final bool pending;

  /// 标记错误气泡，UI 可用不同配色。
  final bool isError;

  /// 仅 assistant 且命中 music_play：可播放信息，气泡上给「用网易云音乐打开」按钮。
  final MusicInfo? music;

  /// 仅 assistant：服务端下发的 A2UI 卡片消息（新闻/行程/天气等技能结果）。
  /// 非空时气泡渲染卡片（由 a2ui 模块负责），text 仍用于 TTS 朗读。
  final List<Map<String, dynamic>>? a2ui;

  const ChatTurn({
    required this.sender,
    required this.text,
    this.intent,
    this.pending = false,
    this.isError = false,
    this.music,
    this.a2ui,
  });

  ChatTurn copyWith({String? text, String? intent, bool? pending, bool? isError, MusicInfo? music}) {
    return ChatTurn(
      sender: sender,
      text: text ?? this.text,
      intent: intent ?? this.intent,
      pending: pending ?? this.pending,
      isError: isError ?? this.isError,
      music: music ?? this.music,
      a2ui: a2ui,
    );
  }
}

/// POST /chat 的响应：{ text, intent, session_id, data?, a2ui? }。
/// data 目前仅音乐能力下发（供端侧拉起 app）；
/// a2ui 是 A2UI v0.9 消息列表（服务端仅对 platform=mobile 且可卡片化的意图下发）。
class ChatReply {
  final String text;
  final String intent;
  final String sessionId;
  final MusicInfo? music;
  final CalendarEvent? calendarEvent;
  final ScheduleAction? scheduleAction;
  final List<Map<String, dynamic>>? a2ui;

  const ChatReply({
    required this.text,
    required this.intent,
    required this.sessionId,
    this.music,
    this.calendarEvent,
    this.scheduleAction,
    this.a2ui,
  });

  factory ChatReply.fromJson(Map<String, dynamic> json) {
    return ChatReply(
      text: (json['text'] ?? '') as String,
      intent: (json['intent'] ?? '') as String,
      sessionId: (json['session_id'] ?? '') as String,
      music: MusicInfo.tryFrom(json['data']),
      calendarEvent: CalendarEvent.tryFrom(json['data']),
      scheduleAction: ScheduleAction.tryFrom(json['data']),
      a2ui: _a2uiFrom(json['a2ui']),
    );
  }

  /// 宽容解析 a2ui 段：非 List/元素非 Map 一律忽略（老服务端/异常数据不致崩）。
  static List<Map<String, dynamic>>? _a2uiFrom(Object? raw) {
    if (raw is! List) return null;
    final msgs = raw
        .whereType<Map>()
        .map((m) => Map<String, dynamic>.from(m))
        .toList();
    return msgs.isEmpty ? null : msgs;
  }
}

/// GET /health 的响应：{ status, capabilities }。
class HealthInfo {
  final String status;
  final List<String> capabilities;

  const HealthInfo({required this.status, required this.capabilities});

  factory HealthInfo.fromJson(Map<String, dynamic> json) {
    final caps = (json['capabilities'] as List?)?.cast<String>() ?? const <String>[];
    return HealthInfo(status: (json['status'] ?? '') as String, capabilities: caps);
  }
}
