// SkillStoreApi：直连商店 :9000 的选购三端点（MockClient 注入，不碰真网）。
import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:moasm_vui/src/data/chat_api.dart' show ApiException;
import 'package:moasm_vui/src/data/skill_store_api.dart';

void main() {
  group('SkillStoreApi', () {
    test('baseUrl 去尾斜杠 + listSkills 解析（字段缺省宽容）', () async {
      final api = SkillStoreApi(
        baseUrl: 'http://10.0.2.2:9000/',
        client: MockClient((request) async {
          expect(request.url.toString(), 'http://10.0.2.2:9000/skills');
          return http.Response(
            jsonEncode({
              'skills': [
                {
                  'skill_id': 'weather-mcp',
                  'name': '天气查询（MCP）',
                  'icon': '🌤️',
                  'description': '查实时天气',
                  'intent': 'weather_mcp',
                  'keywords': ['天气', '天气查询'],
                },
                // 字段缺省：仅 skill_id + name，其余走默认值
                {'skill_id': 'minimal', 'name': '极简'},
              ],
            }),
            200,
            headers: {'content-type': 'application/json; charset=utf-8'},
          );
        }),
      );

      final skills = await api.listSkills();

      expect(skills, hasLength(2));
      final w = skills.first;
      expect(w.skillId, 'weather-mcp');
      expect(w.name, '天气查询（MCP）');
      expect(w.icon, '🌤️');
      expect(w.keywords, ['天气', '天气查询']);
      final m = skills[1];
      expect(m.skillId, 'minimal');
      expect(m.keywords, isEmpty);
      expect(m.tools, isEmpty);
      expect(m.icon, isNull);
      api.dispose();
    });

    test('真实商店 manifest：mcp_server/tools 是对象也不崩，mcpServer 取 url', () async {
      final api = SkillStoreApi(
        baseUrl: 'http://10.0.2.2:9000',
        client: MockClient((request) async {
          return http.Response(
            jsonEncode({
              'skills': [
                {
                  'skill_id': 'weather-mcp',
                  'name': '天气查询（MCP）',
                  'icon': '🌤',
                  'description': '查询指定城市未来几天的天气情况',
                  'intent': 'weather_mcp',
                  'query_slot': 'city',
                  'keywords': ['天气', '气温'],
                  // 真实 seed：mcp_server 是对象，tools 是对象数组
                  'mcp_server': {
                    'transport': 'http',
                    'url': 'http://127.0.0.1:9100/mcp',
                  },
                  'tools': [
                    {
                      'name': 'get_weather',
                      'description': '查询城市天气',
                      'input_schema': {'required': ['city']},
                    },
                  ],
                },
              ],
            }),
            200,
            headers: {'content-type': 'application/json; charset=utf-8'},
          );
        }),
      );

      final skills = await api.listSkills();

      final w = skills.single;
      expect(w.skillId, 'weather-mcp');
      expect(w.icon, '🌤');
      expect(w.mcpServer, 'http://127.0.0.1:9100/mcp'); // 从对象里取 url
      expect(w.keywords, ['天气', '气温']);
      expect(w.querySlot, 'city');
      api.dispose();
    });

    test('getMySkills 传 user_id（URL encode）并解析 已选购+已启用', () async {
      final api = SkillStoreApi(
        baseUrl: 'http://10.0.2.2:9000',
        client: MockClient((request) async {
          expect(request.method, 'GET');
          expect(request.url.path, '/me/skills');
          expect(request.url.queryParameters, {'user_id': 'demo 用户'});
          return http.Response(
            jsonEncode({
              'user_id': 'demo 用户',
              'skill_ids': ['weather-mcp', 'stock-mcp'],
              'enabled': {'weather-mcp': true, 'stock-mcp': false},
            }),
            200,
            headers: {'content-type': 'application/json; charset=utf-8'},
          );
        }),
      );

      final my = await api.getMySkills('demo 用户');

      expect(my.purchased, {'weather-mcp', 'stock-mcp'});
      expect(my.enabled, {'weather-mcp': true, 'stock-mcp': false});
      api.dispose();
    });

    test('setEnabled 是 PUT /me/skills/enabled：JSON 头 + body + version', () async {
      late http.Request captured;
      final api = SkillStoreApi(
        baseUrl: 'http://10.0.2.2:9000',
        client: MockClient((request) async {
          captured = request;
          return http.Response(
            jsonEncode({'user_id': 'demo', 'version': 44}),
            200,
            headers: {'content-type': 'application/json; charset=utf-8'},
          );
        }),
      );

      final version = await api.setEnabled('demo', 'stock-mcp', false);

      expect(captured.method, 'PUT');
      expect(captured.url.path, '/me/skills/enabled');
      expect(captured.headers['Content-Type'], contains('application/json'));
      expect(jsonDecode(captured.body), {
        'user_id': 'demo',
        'skill_id': 'stock-mcp',
        'enabled': false,
      });
      expect(version, 44);
      api.dispose();
    });

    test('removeSkill 是 PUT /me/skills/remove + version', () async {
      late http.Request captured;
      final api = SkillStoreApi(
        baseUrl: 'http://10.0.2.2:9000',
        client: MockClient((request) async {
          captured = request;
          return http.Response(
            jsonEncode({'user_id': 'demo', 'version': 45}),
            200,
            headers: {'content-type': 'application/json; charset=utf-8'},
          );
        }),
      );

      final version = await api.removeSkill('demo', 'stock-mcp');

      expect(captured.method, 'PUT');
      expect(captured.url.path, '/me/skills/remove');
      expect(jsonDecode(captured.body), {'user_id': 'demo', 'skill_id': 'stock-mcp'});
      expect(version, 45);
      api.dispose();
    });

    test('putMySkills 是 PUT + 全量 body + 返回 version', () async {
      late http.Request captured;
      final api = SkillStoreApi(
        baseUrl: 'http://10.0.2.2:9000',
        client: MockClient((request) async {
          captured = request;
          return http.Response(
            jsonEncode({'user_id': 'demo', 'version': 42}),
            200,
            headers: {'content-type': 'application/json; charset=utf-8'},
          );
        }),
      );

      final version = await api.putMySkills('demo', ['weather-mcp']);

      expect(captured.method, 'PUT');
      expect(captured.url.path, '/me/skills');
      // 必须带 JSON 头，否则 FastAPI 把 body 当 dict 校验失败返回 422
      expect(captured.headers['Content-Type'], contains('application/json'));
      expect(jsonDecode(captured.body), {
        'user_id': 'demo',
        'skill_ids': ['weather-mcp'],
      });
      expect(version, 42);
      api.dispose();
    });

    test('非 2xx 抛 ApiException，带状态码与 error 文案', () async {
      final api = SkillStoreApi(
        baseUrl: 'http://10.0.2.2:9000',
        client: MockClient(
          (_) async => http.Response.bytes(
            utf8.encode(jsonEncode({'error': 'intent 撞内置'})),
            409,
          ),
        ),
      );

      expect(
        () => api.putMySkills('demo', ['x']),
        throwsA(isA<ApiException>()
            .having((e) => e.message, 'message', contains('409'))
            .having((e) => e.message, 'message', contains('intent 撞内置'))),
      );
      api.dispose();
    });

    test('Skill.fromJson 解析 credentials（byok schema，宽容缺省）', () async {
      final api = SkillStoreApi(
        baseUrl: 'http://10.0.2.2:9000',
        client: MockClient((request) async {
          return http.Response(
            jsonEncode({
              'skills': [
                {
                  'skill_id': 'region-mcp',
                  'name': '区域天气',
                  'credentials': {
                    'type': 'byok',
                    'schema': [
                      {
                        'key': 'api_key',
                        'label': 'API Key',
                        'type': 'secret',
                        'required': true,
                        'inject': {
                          'where': 'header',
                          'name': 'X-API-Key',
                          'prefix': 'Bearer ',
                        },
                      },
                    ],
                  },
                },
                {'skill_id': 'plain', 'name': '无凭证', 'credentials': {'type': 'none'}},
              ],
            }),
            200,
            headers: {'content-type': 'application/json; charset=utf-8'},
          );
        }),
      );

      final skills = await api.listSkills();

      final byok = skills[0];
      expect(byok.credentials, isNotNull);
      expect(byok.credentials!['type'], 'byok');
      final schema = byok.credentials!['schema'] as List;
      expect(schema, hasLength(1));
      expect((schema.first as Map)['key'], 'api_key');
      // 宽松：credentials 非 Map 也不崩
      expect(skills[1].credentials, {'type': 'none'});
      api.dispose();
    });

    test('getCredentials：GET 传 user_id/skill_id，返回脱敏 values', () async {
      final api = SkillStoreApi(
        baseUrl: 'http://10.0.2.2:9000',
        client: MockClient((request) async {
          expect(request.method, 'GET');
          expect(request.url.path, '/me/credentials');
          expect(request.url.queryParameters, {'user_id': 'demo', 'skill_id': 'region-mcp'});
          return http.Response(
            jsonEncode({
              'configured': true,
              'values': {'api_key': null, 'region': 'cn'},
            }),
            200,
            headers: {'content-type': 'application/json; charset=utf-8'},
          );
        }),
      );

      final g = await api.getCredentials('demo', 'region-mcp');

      expect(g['configured'], isTrue);
      expect(g['values'], {'api_key': null, 'region': 'cn'});
      api.dispose();
    });

    test('putCredentials：PUT body + JSON 头 + version', () async {
      late http.Request captured;
      final api = SkillStoreApi(
        baseUrl: 'http://10.0.2.2:9000',
        client: MockClient((request) async {
          captured = request;
          return http.Response(
            jsonEncode({'user_id': 'demo', 'skill_id': 'region-mcp', 'version': 8}),
            200,
            headers: {'content-type': 'application/json; charset=utf-8'},
          );
        }),
      );

      final version =
          await api.putCredentials('demo', 'region-mcp', {'api_key': 'k', 'region': 'cn'});

      expect(captured.method, 'PUT');
      expect(captured.url.path, '/me/credentials');
      expect(captured.headers['Content-Type'], contains('application/json'));
      expect(jsonDecode(captured.body), {
        'user_id': 'demo',
        'skill_id': 'region-mcp',
        'values': {'api_key': 'k', 'region': 'cn'},
      });
      expect(version, 8);
      api.dispose();
    });

    test('deleteCredentials：DELETE + query 传参 + version', () async {
      late http.Request captured;
      final api = SkillStoreApi(
        baseUrl: 'http://10.0.2.2:9000',
        client: MockClient((request) async {
          captured = request;
          return http.Response(
            jsonEncode({'user_id': 'demo', 'skill_id': 'region-mcp', 'version': 9}),
            200,
            headers: {'content-type': 'application/json; charset=utf-8'},
          );
        }),
      );

      final version = await api.deleteCredentials('demo', 'region-mcp');

      expect(captured.method, 'DELETE');
      expect(captured.url.path, '/me/credentials');
      expect(captured.url.queryParameters, {'user_id': 'demo', 'skill_id': 'region-mcp'});
      expect(version, 9);
      api.dispose();
    });

    test('getMySkillsDetail：GET /me/skills/detail，解析含已下架的详情', () async {
      final api = SkillStoreApi(
        baseUrl: 'http://10.0.2.2:9000',
        client: MockClient((request) async {
          expect(request.method, 'GET');
          expect(request.url.path, '/me/skills/detail');
          expect(request.url.queryParameters, {'user_id': 'demo'});
          return http.Response(
            jsonEncode({
              'user_id': 'demo',
              'version': 7,
              'skills': [
                {
                  'skill_id': 'weather-mcp',
                  'name': '天气查询（MCP）',
                  'icon': '🌤️',
                  'description': '查实时天气',
                  'status': 'active',
                  'enabled': true,
                },
                // 已下架：管理员下架后仍保留在详情里，供渲染「已下架」卡
                {
                  'skill_id': 'region-mcp',
                  'name': '区域天气',
                  'status': 'inactive',
                  'enabled': true,
                },
              ],
            }),
            200,
            headers: {'content-type': 'application/json; charset=utf-8'},
          );
        }),
      );

      final detail = await api.getMySkillsDetail('demo');

      expect(detail, hasLength(2));
      final active = detail[0];
      expect(active.skillId, 'weather-mcp');
      expect(active.status, 'active');
      expect(active.enabled, isTrue);
      expect(active.isOffShelf, isFalse);
      final off = detail[1];
      expect(off.skillId, 'region-mcp');
      expect(off.status, 'inactive');
      expect(off.isOffShelf, isTrue);
      // 缺省字段宽容：icon/description 缺失不崩
      expect(off.icon, '');
      expect(off.description, '');
      api.dispose();
    });

    test('getMySkillsDetail：响应缺 skills 列表 → ApiException', () async {
      final api = SkillStoreApi(
        baseUrl: 'http://10.0.2.2:9000',
        client: MockClient((_) async => http.Response(jsonEncode({'user_id': 'demo'}), 200)),
      );

      expect(
        () => api.getMySkillsDetail('demo'),
        throwsA(isA<ApiException>().having((e) => e.message, 'message', contains('skills 列表'))),
      );
      api.dispose();
    });

    test('连接失败 → ApiException 文案「连接技能商店失败」', () async {
      final api = SkillStoreApi(
        baseUrl: 'http://10.0.2.2:9000',
        client: MockClient((_) async => throw http.ClientException('Connection refused')),
      );

      expect(
        () => api.listSkills(),
        throwsA(isA<ApiException>()
            .having((e) => e.message, 'message', contains('连接技能商店失败'))),
      );
      api.dispose();
    });
  });
}
