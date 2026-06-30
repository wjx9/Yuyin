// 冒烟测试：ChatApi 的 URL 规范化与响应解析（纯单元，不依赖平台插件）。
import 'package:flutter_test/flutter_test.dart';
import 'package:moasm_vui/src/data/chat_api.dart';
import 'package:moasm_vui/src/data/models.dart';

void main() {
  test('ChatApi 去掉 baseUrl 末尾多余的斜杠', () {
    final api = ChatApi(baseUrl: 'http://127.0.0.1:8000///');
    expect(api.baseUrl, 'http://127.0.0.1:8000');
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
