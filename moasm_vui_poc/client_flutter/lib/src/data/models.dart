/// 传输与 UI 共用的数据模型。
library;

/// 一条聊天气泡的来源。
enum Sender { user, assistant, system }

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

  const ChatTurn({
    required this.sender,
    required this.text,
    this.intent,
    this.pending = false,
    this.isError = false,
  });

  ChatTurn copyWith({String? text, String? intent, bool? pending, bool? isError}) {
    return ChatTurn(
      sender: sender,
      text: text ?? this.text,
      intent: intent ?? this.intent,
      pending: pending ?? this.pending,
      isError: isError ?? this.isError,
    );
  }
}

/// POST /chat 的响应：{ text, intent, session_id }。
class ChatReply {
  final String text;
  final String intent;
  final String sessionId;

  const ChatReply({required this.text, required this.intent, required this.sessionId});

  factory ChatReply.fromJson(Map<String, dynamic> json) {
    return ChatReply(
      text: (json['text'] ?? '') as String,
      intent: (json['intent'] ?? '') as String,
      sessionId: (json['session_id'] ?? '') as String,
    );
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
