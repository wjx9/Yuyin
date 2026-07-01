/// ChatApi：客户端唯一懂 HTTP 契约的地方（与 client_py/client.py、server/http_server.py 对称）。
///
/// 契约（README §8.10）：
///   GET  /health?platform=mobile -> { status, capabilities }
///   POST /chat   { query, session_id, user_id?, location?, platform } -> { text, intent, session_id }
///   鉴权(可选)    `Authorization: Bearer <token>`
///
/// 本客户端固定声明 platform=mobile：服务端据此屏蔽 PC-only 能力（如 music_control——
/// 那是控服务端本机 mpv 的，移动端走"点歌→深链拉起网易云 app"，控制指令对它无意义）。
/// 于是 /health 的 capabilities 不含 music_control，/chat 也永不路由到它。
///
/// 上层（ChatController）只调 health()/chat()，拿到的是普通 Dart 对象，不碰传输细节。
library;

import 'dart:convert';

import 'package:http/http.dart' as http;

import 'models.dart';

/// 与服务端通信失败：网络错误 / 非 2xx / 响应体不合法。message 已是面向用户的中文。
class ApiException implements Exception {
  final String message;
  const ApiException(this.message);
  @override
  String toString() => message;
}

class ChatApi {
  final String baseUrl; // 末尾无 /
  final String? authToken;
  final String userId;
  final Duration timeout;
  final http.Client _client;

  /// 本客户端的发起端类型，随每次请求上报给服务端用于按端过滤能力。移动端固定 "mobile"。
  static const String platform = 'mobile';

  ChatApi({
    required String baseUrl,
    this.authToken,
    this.userId = 'mock-user',
    this.timeout = const Duration(seconds: 120), // 单轮服务端真发网络，给足超时
    http.Client? client,
  })  : baseUrl = baseUrl.trim().replaceAll(RegExp(r'/+$'), ''),
        _client = client ?? http.Client();

  Map<String, String> get _headers => {
        'Content-Type': 'application/json',
        if (authToken != null && authToken!.isNotEmpty) 'Authorization': 'Bearer $authToken',
      };

  Future<HealthInfo> health() async {
    final json = await _send('GET', '/health?platform=$platform', null);
    return HealthInfo.fromJson(json);
  }

  Future<ChatReply> chat({
    required String query,
    required String sessionId,
    String? location,
  }) async {
    final payload = <String, dynamic>{
      'query': query,
      'session_id': sessionId,
      'user_id': userId,
      'platform': platform,
      if (location != null && location.isNotEmpty) 'location': location,
    };
    final json = await _send('POST', '/chat', payload);
    return ChatReply.fromJson(json);
  }

  Future<Map<String, dynamic>> _send(String method, String path, Map<String, dynamic>? body) async {
    final uri = Uri.parse('$baseUrl$path');
    http.Response resp;
    try {
      final future = method == 'GET'
          ? _client.get(uri, headers: _headers)
          : _client.post(uri, headers: _headers, body: jsonEncode(body));
      resp = await future.timeout(timeout);
    } catch (e) {
      throw ApiException('连接服务端失败：$e');
    }

    // 用 bodyBytes + utf8 解码，确保中文不乱码（不依赖响应头 charset）
    final text = utf8.decode(resp.bodyBytes, allowMalformed: true);
    if (resp.statusCode >= 400) {
      String detail = '';
      try {
        final err = jsonDecode(text);
        if (err is Map && err['error'] is String) detail = err['error'] as String;
      } catch (_) {
        detail = text.trim();
      }
      throw ApiException('服务端返回 ${resp.statusCode}${detail.isNotEmpty ? '：$detail' : ''}');
    }
    try {
      final decoded = jsonDecode(text);
      if (decoded is! Map<String, dynamic>) {
        throw const ApiException('响应不是 JSON 对象');
      }
      return decoded;
    } on FormatException catch (e) {
      throw ApiException('响应非 JSON：$e');
    }
  }

  void dispose() => _client.close();
}
