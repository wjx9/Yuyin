/// ChatApi：客户端唯一懂 HTTP 契约的地方（与 client_py/client.py、server/http_server.py 对称）。
///
/// 契约（README §8.10）：
///   GET  /health -> { status, capabilities }
///   POST /chat   { query, session_id, user_id?, location? } -> { text, intent, session_id }
///   鉴权(可选)    `Authorization: Bearer <token>`
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
    final json = await _send('GET', '/health', null);
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
