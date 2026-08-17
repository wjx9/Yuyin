import 'dart:async';
import 'dart:convert';

import 'package:flutter/foundation.dart';
import 'package:http/http.dart' as http;

import 'workbuddy_models.dart';

class WorkBuddyApiException implements Exception {
  final String message;
  final int? statusCode;

  const WorkBuddyApiException(this.message, {this.statusCode});

  @override
  String toString() => message;
}

class WorkBuddyTaskApi {
  final String baseUrl;
  final String accessToken;
  final String? legacyApiKey;
  final Duration timeout;
  final http.Client _client;

  WorkBuddyTaskApi({
    required String baseUrl,
    required this.accessToken,
    this.legacyApiKey,
    this.timeout = const Duration(seconds: 30),
    http.Client? client,
  }) : baseUrl = baseUrl.trim().replaceAll(RegExp(r'/+$'), ''),
       _client = client ?? http.Client();

  Map<String, String> get _headers => {
    'Accept': 'application/json',
    'Content-Type': 'application/json',
    'Authorization': 'Bearer $accessToken',
    if (legacyApiKey != null && legacyApiKey!.isNotEmpty)
      'X-Api-Key': legacyApiKey!,
  };

  Future<WorkBuddyTaskSnapshot> createTask({
    required String prompt,
    String? name,
  }) async {
    final response = await _client
        .post(
          Uri.parse('$baseUrl/openapi/v2/tasks'),
          headers: _headers,
          body: jsonEncode({
            'prompt': prompt,
            if (name != null && name.trim().isNotEmpty) 'name': name.trim(),
          }),
        )
        .timeout(timeout);
    return _parseTask(response, expectedStatus: const {200, 201});
  }

  Future<WorkBuddyTaskSnapshot> getTask(String taskId) async {
    final response = await _client
        .get(
          Uri.parse('$baseUrl/openapi/v2/tasks/${Uri.encodeComponent(taskId)}'),
          headers: _headers,
        )
        .timeout(timeout);
    return _parseTask(response, expectedStatus: const {200});
  }

  Future<WorkBuddyTaskPage> listTasks({int page = 1, int size = 20}) async {
    final uri = Uri.parse(
      '$baseUrl/openapi/v2/tasks',
    ).replace(queryParameters: {'page': '$page', 'size': '$size'});
    final response = await _client.get(uri, headers: _headers).timeout(timeout);
    final decoded = _decodeResponse(response, expectedStatus: const {200});
    try {
      return WorkBuddyTaskPage.fromJson(decoded);
    } on FormatException catch (error) {
      throw WorkBuddyApiException('任务列表响应字段不完整：${error.message}');
    }
  }

  WorkBuddyTaskSnapshot _parseTask(
    http.Response response, {
    required Set<int> expectedStatus,
  }) {
    final decoded = _decodeResponse(response, expectedStatus: expectedStatus);
    try {
      return WorkBuddyTaskSnapshot.fromJson(decoded);
    } on FormatException catch (error) {
      throw WorkBuddyApiException('任务响应字段不完整：${error.message}');
    }
  }

  Map<String, dynamic> _decodeResponse(
    http.Response response, {
    required Set<int> expectedStatus,
  }) {
    final text = utf8.decode(response.bodyBytes, allowMalformed: true);
    Object? decoded;
    try {
      decoded = jsonDecode(text);
    } catch (_) {
      throw WorkBuddyApiException(
        'HTTP ${response.statusCode}：响应不是 JSON${text.isEmpty ? '' : '，$text'}',
        statusCode: response.statusCode,
      );
    }
    if (!expectedStatus.contains(response.statusCode)) {
      throw WorkBuddyApiException(
        'HTTP ${response.statusCode}：${_errorMessage(decoded)}',
        statusCode: response.statusCode,
      );
    }
    if (decoded is! Map) {
      throw const WorkBuddyApiException('任务响应不是 JSON 对象');
    }
    return Map<String, dynamic>.from(decoded);
  }

  static String _errorMessage(Object? decoded) {
    if (decoded is Map) {
      final error = decoded['error'];
      if (error is Map) {
        return (error['message'] ?? error['status'] ?? error).toString();
      }
      if (error != null) return error.toString();
      if (decoded['message'] != null) return decoded['message'].toString();
    }
    return decoded?.toString() ?? '未知错误';
  }

  void dispose() => _client.close();
}

/// 单个任务独占一个 ACP 通道。多个实例可并行工作，彼此的 SSE、RPC id、权限请求不串线。
class WorkBuddyTaskSession extends ChangeNotifier {
  WorkBuddyTaskSnapshot task;
  final WorkBuddyTaskApi taskApi;
  final http.Client _sseClient;
  final http.Client _rpcClient;

  WorkBuddyTaskPhase phase = WorkBuddyTaskPhase.ready;
  String? connectionId;
  String? error;
  String? stopReason;
  WorkBuddyPermissionRequest? permission;
  final List<WorkBuddyMessage> messages = [];
  final List<WorkBuddyEvent> events = [];
  final Map<String, WorkBuddyArtifactEntry> artifacts = {};

  StreamSubscription<Map<String, dynamic>>? _sseSubscription;
  int _rpcId = 0;
  int? _streamingAssistantIndex;
  String? _streamingMessageId;
  final Set<Object> _promptRequestIds = {};
  bool _disposed = false;

  WorkBuddyTaskSession({
    required this.task,
    required this.taskApi,
    http.Client? sseClient,
    http.Client? rpcClient,
  }) : _sseClient = sseClient ?? http.Client(),
       _rpcClient = rpcClient ?? http.Client();

  bool get isConnected => connectionId != null && _sseSubscription != null;
  bool get canSend =>
      isConnected &&
      phase != WorkBuddyTaskPhase.connecting &&
      phase != WorkBuddyTaskPhase.waitingUser;

  Future<void> refreshTask() async {
    await _guard('刷新任务', () async {
      task = task.merge(await taskApi.getTask(task.taskId));
      _event(
        'task/refresh',
        '${task.status} · ACP ${task.canConnect ? '已就绪' : '未就绪'}',
        _redact(task.raw),
      );
    });
  }

  Future<void> connect() async {
    if (isConnected) return;
    if (!task.canConnect) {
      throw const WorkBuddyApiException('任务还没有返回 ACP link/task_ticket，请先刷新任务');
    }
    phase = WorkBuddyTaskPhase.connecting;
    error = null;
    _notify();
    try {
      final request = http.Request('GET', Uri.parse(task.link!));
      request.headers.addAll({
        'Authorization': 'Bearer ${task.taskTicket}',
        'Accept': 'text/event-stream',
        'Cache-Control': 'no-cache',
      });
      final response = await _sseClient
          .send(request)
          .timeout(const Duration(seconds: 30));
      if (response.statusCode < 200 || response.statusCode >= 300) {
        final body = await response.stream.bytesToString();
        throw WorkBuddyApiException(
          'ACP GET HTTP ${response.statusCode}：$body',
          statusCode: response.statusCode,
        );
      }
      connectionId = response.headers['acp-connection-id'];
      if (connectionId == null || connectionId!.isEmpty) {
        throw const WorkBuddyApiException('ACP 响应缺少 acp-connection-id');
      }
      phase = WorkBuddyTaskPhase.connected;
      _event('transport/connected', 'SSE 已连接 · ${_masked(connectionId!)}');
      _sseSubscription = _decodeSse(response.stream).listen(
        _onRpcMessage,
        onError: (Object cause) {
          error = 'SSE 异常：$cause';
          phase = WorkBuddyTaskPhase.failed;
          _event('transport/error', error!);
          _notify();
        },
        onDone: () {
          connectionId = null;
          _sseSubscription = null;
          if (phase != WorkBuddyTaskPhase.failed) {
            phase = WorkBuddyTaskPhase.disconnected;
          }
          _event('transport/closed', 'SSE 已断开');
          _notify();
        },
      );
      _notify();
    } catch (cause) {
      connectionId = null;
      phase = WorkBuddyTaskPhase.failed;
      error = '建联失败：$cause';
      _event('transport/error', error!);
      _notify();
      rethrow;
    }
  }

  Future<void> initializeAndLoad() async {
    await _guard('初始化 ACP', () async {
      await _postRpc(
        id: _nextRpcId(),
        method: 'initialize',
        params: const {
          'protocolVersion': 1,
          'clientCapabilities': {
            'fs': {'readTextFile': false, 'writeTextFile': false},
          },
        },
      );
      await _postRpc(
        id: _nextRpcId(),
        method: 'session/load',
        params: {
          'sessionId': task.taskId,
          'cwd': '/workspace',
          'mcpServers': const [],
        },
      );
      _event('session/ready', 'initialize + session/load 已发送');
    });
  }

  Future<void> sendPrompt(String text) async {
    final prompt = text.trim();
    if (prompt.isEmpty) return;
    await _guard('发送提问', () async {
      final id = _nextRpcId();
      _promptRequestIds.add(id);
      _streamingAssistantIndex = null;
      _streamingMessageId = null;
      stopReason = null;
      phase = WorkBuddyTaskPhase.working;
      messages.add(
        WorkBuddyMessage(
          role: WorkBuddyMessageRole.user,
          text: prompt,
          timestamp: DateTime.now(),
        ),
      );
      _notify();
      await _postRpc(
        id: id,
        method: 'session/prompt',
        params: {
          'sessionId': task.taskId,
          'prompt': [
            {'type': 'text', 'text': prompt},
          ],
        },
      );
    });
  }

  Future<void> cancel() async {
    await _guard('取消任务', () async {
      final pending = permission;
      if (pending != null) {
        await _postRaw({
          'jsonrpc': '2.0',
          'id': pending.rpcId,
          'result': {
            'outcome': {'outcome': 'cancelled'},
          },
        });
        permission = null;
      }
      await _postRpc(
        method: 'session/cancel',
        params: {'sessionId': task.taskId},
      );
      stopReason = 'cancelling';
      _event('session/cancel', '已请求停止，等待 session/prompt 最终响应');
    });
  }

  Future<void> answerPermission(String? optionId) async {
    final pending = permission;
    if (pending == null) return;
    await _guard('回复授权', () async {
      await _postRaw({
        'jsonrpc': '2.0',
        'id': pending.rpcId,
        'result': {
          'outcome': optionId == null
              ? {'outcome': 'cancelled'}
              : {'outcome': 'selected', 'optionId': optionId},
        },
      });
      permission = null;
      phase = WorkBuddyTaskPhase.working;
    });
  }

  Future<void> fetchArtifacts({String? type}) async {
    if (!task.canConnect) {
      throw const WorkBuddyApiException('任务还没有返回 ACP link/task_ticket');
    }
    await _guard('拉取产物', () async {
      final link = Uri.parse(task.link!);
      var basePath = link.path;
      if (basePath.endsWith('/acp')) {
        basePath = basePath.substring(0, basePath.length - 4);
      }
      final uri = link.replace(
        path: '$basePath/api/session/artifacts',
        queryParameters: {
          'sessionId': task.taskId,
          if (type != null && type.isNotEmpty) 'type': type,
        },
      );
      final response = await _rpcClient
          .get(
            uri,
            headers: {
              'Authorization': 'Bearer ${task.taskTicket}',
              'Accept': 'application/json',
            },
          )
          .timeout(const Duration(seconds: 30));
      final body = utf8.decode(response.bodyBytes, allowMalformed: true);
      if (response.statusCode < 200 || response.statusCode >= 300) {
        throw WorkBuddyApiException(
          '产物 API HTTP ${response.statusCode}${body.isEmpty ? '' : '：$body'}',
          statusCode: response.statusCode,
        );
      }
      final decoded = jsonDecode(body);
      if (decoded is! Map) throw const WorkBuddyApiException('产物响应不是 JSON 对象');
      if (decoded['code'] != null && decoded['code'] != 0) {
        throw WorkBuddyApiException(
          '产物接口业务错误：${decoded['msg'] ?? decoded['code']}',
        );
      }
      if (decoded['data'] is! Map) {
        throw const WorkBuddyApiException('产物响应缺少 data');
      }
      final data = decoded['data'] as Map;
      final rawArtifacts = data['artifacts'];
      if (rawArtifacts is! List) {
        throw const WorkBuddyApiException('产物响应缺少 data.artifacts');
      }
      for (final raw in rawArtifacts.whereType<Map>()) {
        _applyArtifact(
          WorkBuddyArtifactEntry.fromJson(Map<String, dynamic>.from(raw)),
        );
      }
      _event('artifact/list', '已拉取 ${rawArtifacts.length} 条产物');
    });
  }

  Future<void> disconnect() async {
    await _sseSubscription?.cancel();
    _sseSubscription = null;
    connectionId = null;
    phase = WorkBuddyTaskPhase.disconnected;
    _event('transport/closed', '客户端主动断开');
    _notify();
  }

  Future<void> _postRpc({
    Object? id,
    required String method,
    required Map<String, dynamic> params,
  }) {
    final payload = <String, dynamic>{
      'jsonrpc': '2.0',
      'method': method,
      'params': params,
    };
    if (id != null) payload['id'] = id;
    return _postRaw(payload);
  }

  Future<void> _postRaw(Map<String, dynamic> payload) async {
    if (!isConnected) {
      throw const WorkBuddyApiException('ACP 尚未建联');
    }
    final response = await _rpcClient
        .post(
          Uri.parse(task.link!),
          headers: {
            'Authorization': 'Bearer ${task.taskTicket}',
            'Accept': 'application/json, text/event-stream',
            'Content-Type': 'application/json',
            'Acp-Connection-Id': connectionId!,
          },
          body: jsonEncode(payload),
        )
        .timeout(const Duration(seconds: 30));
    final body = utf8.decode(response.bodyBytes, allowMalformed: true);
    if (response.statusCode < 200 || response.statusCode >= 300) {
      throw WorkBuddyApiException(
        'ACP POST HTTP ${response.statusCode}${body.isEmpty ? '' : '：$body'}',
        statusCode: response.statusCode,
      );
    }
    _event(
      'rpc/up',
      (payload['method'] ?? 'response').toString(),
      _redact(payload),
    );
    if (body.trim().isNotEmpty) {
      try {
        final decoded = jsonDecode(body);
        if (decoded is Map) {
          _onRpcMessage(Map<String, dynamic>.from(decoded));
        }
      } catch (_) {
        _event('rpc/http-response', body);
      }
    }
  }

  Future<void> _guard(String operation, Future<void> Function() action) async {
    error = null;
    try {
      await action();
    } catch (cause) {
      error = '$operation失败：$cause';
      phase = WorkBuddyTaskPhase.failed;
      _event('error', error!);
      rethrow;
    } finally {
      _notify();
    }
  }

  void _onRpcMessage(Map<String, dynamic> message) {
    _event('rpc/down', _rpcSummary(message), _redact(message));
    final method = message['method'];
    if (method == 'session/update') {
      _handleSessionUpdate(message['params']);
    } else if (method == '_codebuddy.ai/artifact') {
      final params = message['params'];
      if (params is Map) {
        try {
          _applyArtifact(
            WorkBuddyArtifactEntry.fromJson(Map<String, dynamic>.from(params)),
          );
        } on FormatException catch (cause) {
          _event('artifact/error', cause.message, _redact(params));
        }
      }
    } else if (method == 'session/request_permission' &&
        message['id'] != null) {
      permission = WorkBuddyPermissionRequest.fromJson(message);
      phase = WorkBuddyTaskPhase.waitingUser;
    } else if (message['id'] != null &&
        _promptRequestIds.remove(message['id'])) {
      _streamingAssistantIndex = null;
      _streamingMessageId = null;
      if (message['error'] != null) {
        phase = WorkBuddyTaskPhase.failed;
        error = 'Prompt RPC 错误：${message['error']}';
      } else {
        final result = message['result'];
        stopReason = result is Map ? result['stopReason']?.toString() : null;
        phase = WorkBuddyTaskPhase.completed;
      }
    }
    _notify();
  }

  void _handleSessionUpdate(Object? rawParams) {
    if (rawParams is! Map) return;
    final params = Map<String, dynamic>.from(rawParams);
    final rawUpdate = params['update'];
    final update = rawUpdate is Map
        ? Map<String, dynamic>.from(rawUpdate)
        : params;
    final kind = update['sessionUpdate']?.toString();
    if (kind == 'agent_message_chunk') {
      final text = _contentText(update['content']);
      if (text.isNotEmpty) {
        _appendAssistantChunk(text, update['messageId']?.toString());
      }
    } else if (kind == 'session_info_update') {
      final meta = update['_meta'];
      if (meta is Map && meta['codebuddy.ai'] is Map) {
        final codeBuddy = meta['codebuddy.ai'] as Map;
        final status = codeBuddy['status']?.toString();
        phase = switch (status) {
          'planning' || 'working' => WorkBuddyTaskPhase.working,
          'pending' => WorkBuddyTaskPhase.waitingUser,
          'completed' => WorkBuddyTaskPhase.completed,
          'failed' => WorkBuddyTaskPhase.failed,
          _ => phase,
        };
      }
    }
  }

  void _appendAssistantChunk(String chunk, String? messageId) {
    final index = _streamingAssistantIndex;
    final startsNewMessage =
        messageId != null && messageId != _streamingMessageId;
    if (index == null || index >= messages.length || startsNewMessage) {
      messages.add(
        WorkBuddyMessage(
          role: WorkBuddyMessageRole.assistant,
          text: chunk,
          timestamp: DateTime.now(),
        ),
      );
      _streamingAssistantIndex = messages.length - 1;
      _streamingMessageId = messageId;
    } else {
      messages[index] = messages[index].append(chunk);
    }
  }

  void _applyArtifact(WorkBuddyArtifactEntry entry) {
    if (entry.event == 'deleted') {
      artifacts.remove(entry.uri);
    } else {
      artifacts[entry.uri] = entry;
    }
  }

  int _nextRpcId() => ++_rpcId;

  void _event(String type, String summary, [Object? raw]) {
    events.insert(
      0,
      WorkBuddyEvent(
        timestamp: DateTime.now(),
        type: type,
        summary: summary,
        raw: raw,
      ),
    );
    if (events.length > 300) events.removeRange(300, events.length);
  }

  void _notify() {
    if (!_disposed) notifyListeners();
  }

  static String _contentText(Object? content) {
    if (content is String) return content;
    if (content is Map) {
      if (content['type'] == 'text') return content['text']?.toString() ?? '';
      if (content['text'] != null) return content['text'].toString();
    }
    return '';
  }

  static String _rpcSummary(Map<String, dynamic> message) {
    if (message['method'] != null) return message['method'].toString();
    if (message['error'] != null) return 'response error · id=${message['id']}';
    final stopReason = message['result'] is Map
        ? (message['result'] as Map)['stopReason']
        : null;
    return 'response · id=${message['id']}${stopReason == null ? '' : ' · $stopReason'}';
  }

  static Object? _redact(Object? value) {
    if (value is List) return value.map(_redact).toList();
    if (value is Map) {
      return Map.fromEntries(
        value.entries.map((entry) {
          final key = entry.key.toString();
          if (RegExp(
            r'token|ticket|authorization|api.?key',
            caseSensitive: false,
          ).hasMatch(key)) {
            return MapEntry(key, '***');
          }
          return MapEntry(key, _redact(entry.value));
        }),
      );
    }
    return value;
  }

  static String _masked(String value) {
    if (value.length <= 8) return '***';
    return '${value.substring(0, 4)}…${value.substring(value.length - 4)}';
  }

  static Stream<Map<String, dynamic>> _decodeSse(
    Stream<List<int>> byteStream,
  ) async* {
    final dataLines = <String>[];
    await for (final line
        in byteStream.transform(utf8.decoder).transform(const LineSplitter())) {
      if (line.isEmpty) {
        if (dataLines.isNotEmpty) {
          final data = dataLines.join('\n');
          dataLines.clear();
          try {
            final decoded = jsonDecode(data);
            if (decoded is Map) yield Map<String, dynamic>.from(decoded);
          } catch (_) {
            // 非 JSON SSE 心跳或服务端诊断文本不进入 RPC 分发。
          }
        }
      } else if (line.startsWith('data:')) {
        dataLines.add(line.substring(5).trimLeft());
      }
    }
    if (dataLines.isNotEmpty) {
      try {
        final decoded = jsonDecode(dataLines.join('\n'));
        if (decoded is Map) yield Map<String, dynamic>.from(decoded);
      } catch (_) {
        // 连接断开时的半包直接丢弃。
      }
    }
  }

  @override
  void dispose() {
    _disposed = true;
    _sseSubscription?.cancel();
    _sseClient.close();
    _rpcClient.close();
    taskApi.dispose();
    super.dispose();
  }
}
