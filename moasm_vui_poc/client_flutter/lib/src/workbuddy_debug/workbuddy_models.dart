import 'dart:convert';

enum WorkBuddyTaskPhase {
  creating,
  ready,
  connecting,
  connected,
  working,
  waitingUser,
  completed,
  failed,
  disconnected,
}

class WorkBuddyTaskSnapshot {
  final String taskId;
  final String name;
  final String status;
  final String? link;
  final String? taskTicket;
  final int? taskTicketExpiresAt;
  final Map<String, dynamic> raw;

  const WorkBuddyTaskSnapshot({
    required this.taskId,
    required this.name,
    required this.status,
    required this.raw,
    this.link,
    this.taskTicket,
    this.taskTicketExpiresAt,
  });

  bool get canConnect =>
      link != null &&
      link!.isNotEmpty &&
      taskTicket != null &&
      taskTicket!.isNotEmpty;

  factory WorkBuddyTaskSnapshot.fromJson(Map<String, dynamic> json) {
    final payload = json['data'] is Map
        ? Map<String, dynamic>.from(json['data'] as Map)
        : json;
    final taskId = _firstString(payload, const ['task_id', 'id', 'session_id']);
    if (taskId == null || taskId.isEmpty) {
      throw const FormatException('响应缺少 task_id/id');
    }
    return WorkBuddyTaskSnapshot(
      taskId: taskId,
      name: _firstString(payload, const ['name']) ?? '未命名任务',
      status: _firstString(payload, const ['status']) ?? 'unknown',
      link: _firstString(payload, const ['link', 'acp_link']),
      taskTicket: _firstString(payload, const ['task_ticket', 'token']),
      taskTicketExpiresAt: _asInt(
        payload['task_ticket_expires_at'] ?? payload['token_expires_at'],
      ),
      raw: Map<String, dynamic>.from(payload),
    );
  }

  WorkBuddyTaskSnapshot merge(WorkBuddyTaskSnapshot newer) =>
      WorkBuddyTaskSnapshot(
        taskId: newer.taskId,
        name: newer.name,
        status: newer.status,
        link: newer.link ?? link,
        taskTicket: newer.taskTicket ?? taskTicket,
        taskTicketExpiresAt: newer.taskTicketExpiresAt ?? taskTicketExpiresAt,
        raw: newer.raw,
      );

  static String? _firstString(Map<String, dynamic> json, List<String> keys) {
    for (final key in keys) {
      final value = json[key];
      if (value is String && value.isNotEmpty) return value;
      if (value is num) return value.toString();
    }
    return null;
  }

  static int? _asInt(Object? value) {
    if (value is int) return value;
    return int.tryParse(value?.toString() ?? '');
  }
}

class WorkBuddyTaskPage {
  final List<WorkBuddyTaskSnapshot> tasks;
  final int total;

  const WorkBuddyTaskPage({required this.tasks, required this.total});

  factory WorkBuddyTaskPage.fromJson(Map<String, dynamic> json) {
    final rawTasks = json['tasks'];
    if (rawTasks is! List) {
      throw const FormatException('响应缺少 tasks 数组');
    }
    final pagination = json['pagination'];
    final total =
        json['total'] ?? (pagination is Map ? pagination['total'] : null);
    return WorkBuddyTaskPage(
      tasks: rawTasks
          .whereType<Map>()
          .map(
            (item) =>
                WorkBuddyTaskSnapshot.fromJson(Map<String, dynamic>.from(item)),
          )
          .toList(),
      total: WorkBuddyTaskSnapshot._asInt(total) ?? rawTasks.length,
    );
  }
}

class WorkBuddyArtifactEntry {
  final String event;
  final String uri;
  final String type;
  final String title;
  final String? mimeType;
  final String? url;
  final Map<String, dynamic> raw;

  const WorkBuddyArtifactEntry({
    required this.event,
    required this.uri,
    required this.type,
    required this.title,
    required this.raw,
    this.mimeType,
    this.url,
  });

  factory WorkBuddyArtifactEntry.fromJson(Map<String, dynamic> json) {
    final artifact = json['artifact'] is Map
        ? Map<String, dynamic>.from(json['artifact'] as Map)
        : json;
    final uri = artifact['uri']?.toString() ?? '';
    if (uri.isEmpty) throw const FormatException('产物缺少 artifact.uri');
    return WorkBuddyArtifactEntry(
      event: (json['event'] ?? 'updated').toString(),
      uri: uri,
      type: (artifact['type'] ?? 'unknown').toString(),
      title: (artifact['title'] ?? artifact['name'] ?? uri).toString(),
      mimeType: artifact['mimeType']?.toString(),
      url: json['url']?.toString(),
      raw: Map<String, dynamic>.from(json),
    );
  }
}

enum WorkBuddyMessageRole { user, assistant, system }

class WorkBuddyMessage {
  final WorkBuddyMessageRole role;
  final String text;
  final DateTime timestamp;

  const WorkBuddyMessage({
    required this.role,
    required this.text,
    required this.timestamp,
  });

  WorkBuddyMessage append(String chunk) =>
      WorkBuddyMessage(role: role, text: '$text$chunk', timestamp: timestamp);
}

class WorkBuddyEvent {
  final DateTime timestamp;
  final String type;
  final String summary;
  final Object? raw;

  const WorkBuddyEvent({
    required this.timestamp,
    required this.type,
    required this.summary,
    this.raw,
  });

  String get prettyRaw {
    if (raw == null) return '';
    try {
      return const JsonEncoder.withIndent('  ').convert(raw);
    } catch (_) {
      return raw.toString();
    }
  }
}

class WorkBuddyPermissionOption {
  final String optionId;
  final String name;
  final String kind;

  const WorkBuddyPermissionOption({
    required this.optionId,
    required this.name,
    required this.kind,
  });

  factory WorkBuddyPermissionOption.fromJson(Map<String, dynamic> json) =>
      WorkBuddyPermissionOption(
        optionId: (json['optionId'] ?? '').toString(),
        name: (json['name'] ?? json['optionId'] ?? '').toString(),
        kind: (json['kind'] ?? '').toString(),
      );
}

class WorkBuddyPermissionRequest {
  final Object rpcId;
  final String title;
  final String description;
  final List<WorkBuddyPermissionOption> options;
  final Map<String, dynamic> raw;

  const WorkBuddyPermissionRequest({
    required this.rpcId,
    required this.title,
    required this.description,
    required this.options,
    required this.raw,
  });

  factory WorkBuddyPermissionRequest.fromJson(Map<String, dynamic> json) {
    final params = json['params'] is Map
        ? Map<String, dynamic>.from(json['params'] as Map)
        : const <String, dynamic>{};
    final toolCall = params['toolCall'] is Map
        ? Map<String, dynamic>.from(params['toolCall'] as Map)
        : const <String, dynamic>{};
    final rawInput = toolCall['rawInput'];
    var description = '';
    if (rawInput is Map && rawInput['questions'] is List) {
      description = (rawInput['questions'] as List)
          .whereType<Map>()
          .map((item) => item['question']?.toString() ?? '')
          .where((text) => text.isNotEmpty)
          .join('\n');
    }
    return WorkBuddyPermissionRequest(
      rpcId: json['id'] ?? 0,
      title: (toolCall['title'] ?? '需要用户确认').toString(),
      description: description.isNotEmpty
          ? description
          : (toolCall['rawInput'] ?? '').toString(),
      options: (params['options'] as List? ?? const [])
          .whereType<Map>()
          .map(
            (item) => WorkBuddyPermissionOption.fromJson(
              Map<String, dynamic>.from(item),
            ),
          )
          .where((item) => item.optionId.isNotEmpty)
          .toList(),
      raw: json,
    );
  }
}
