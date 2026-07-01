// 冒烟测试：ChatApi 的 URL 规范化与响应解析（纯单元，不依赖平台插件）。
import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/testing.dart';
import 'package:http/http.dart' as http;
import 'package:moasm_vui/src/data/chat_api.dart';
import 'package:moasm_vui/src/data/models.dart';

void main() {
  test('ChatApi 去掉 baseUrl 末尾多余的斜杠', () {
    final api = ChatApi(baseUrl: 'http://127.0.0.1:8000///');
    expect(api.baseUrl, 'http://127.0.0.1:8000');
  });

  test('移动端固定上报 platform=mobile（/health 查询参数 + /chat 请求体）', () async {
    late Uri healthUri;
    late Map<String, dynamic> chatBody;
    final mock = MockClient((req) async {
      if (req.method == 'GET') {
        healthUri = req.url;
        return http.Response(jsonEncode({'status': 'ok', 'capabilities': []}), 200);
      }
      chatBody = jsonDecode(req.body) as Map<String, dynamic>;
      return http.Response(
        jsonEncode({'text': 'hi', 'intent': 'chitchat', 'session_id': 's1'}),
        200,
      );
    });
    final api = ChatApi(baseUrl: 'http://127.0.0.1:8000', client: mock);

    await api.health();
    expect(healthUri.queryParameters['platform'], 'mobile');

    await api.chat(query: 'hi', sessionId: 's1');
    expect(chatBody['platform'], 'mobile');
  });

  test('HealthInfo.fromJson 解析能力清单', () {
    final h = HealthInfo.fromJson({
      'status': 'ok',
      'capabilities': ['chitchat', 'amap'],
    });
    expect(h.status, 'ok');
    expect(h.capabilities, ['chitchat', 'amap']);
  });

  test('ChatReply.fromJson 解析三字段', () {
    final r = ChatReply.fromJson({'text': '你好', 'intent': 'chitchat', 'session_id': 's1'});
    expect(r.text, '你好');
    expect(r.intent, 'chitchat');
    expect(r.sessionId, 's1');
  });
}
