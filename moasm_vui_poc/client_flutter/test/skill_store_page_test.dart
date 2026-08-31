// SkillStorePage widget 测试：apiFactory 注入 MockClient + SharedPreferences mock，
// 不碰真网、不依赖 ChatController（onSkillsSaved 由页面自测）。
// 三态语义：已选购（purchased）与已启用（enabled）分开维护。
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:moasm_vui/src/data/skill_store_api.dart';
import 'package:moasm_vui/src/state/settings_controller.dart';
import 'package:moasm_vui/src/ui/skill_store_page.dart';
import 'package:provider/provider.dart';
import 'package:shared_preferences/shared_preferences.dart';

const _jsonHeaders = {'content-type': 'application/json; charset=utf-8'};

List<Map<String, dynamic>> _catalog() => [
      {
        'skill_id': 'weather-mcp',
        'name': '天气查询（MCP）',
        'icon': '🌤️',
        'description': '查实时天气（确定性路由示例）',
        'intent': 'weather_mcp',
        'keywords': ['天气', '天气查询'],
      },
      {
        'skill_id': 'stock-mcp',
        'name': '股票查询（MCP）',
        'description': '查股价（确定性路由示例）',
        'intent': 'stock_mcp',
        'keywords': ['股价'],
      },
    ];

/// 造一个商店 MockClient：目录固定，GET /me/skills 返回 purchased+enabled 双状态，
/// PUT /me/skills/enabled 单技能启/停（开启自动选购），PUT /me/skills/remove 退订。
/// GET /me/skills/detail 返回已选购详情（含 [offShelf] 传入的已下架技能，status=inactive）。
/// P4.2：GET/PUT/DELETE /me/credentials 维护 credState（secret 字段脱敏）。
/// [failOnState] 为 true 时启/停/退订返回 500（测失败回滚）；[failCredentials] 使凭证写返回 500。
MockClient _storeClient({
  List<Map<String, dynamic>>? catalog,
  Set<String> purchased = const {},
  Map<String, bool> enabled = const {},
  List<Map<String, dynamic>> offShelf = const [],
  Map<String, Map<String, dynamic>> credValues = const {},
  bool failOnState = false,
  bool failCredentials = false,
  List<http.Request>? putLog,
  List<http.Request>? credPutLog,
}) {
  final purchasedSet = Set<String>.of(purchased);
  final enabledMap = Map<String, bool>.of(enabled);
  final credState = <String, Map<String, dynamic>>{
    for (final e in credValues.entries) e.key: Map.of(e.value),
  };
  // 从目录 schema 推导敏感字段（secret/textarea/file → 脱敏置 null）
  final secrets = <String>{};
  for (final m in catalog ?? _catalog()) {
    final schema = (m['credentials']?['schema'] as List?) ?? const [];
    for (final f in schema.whereType<Map<String, dynamic>>()) {
      if (const {'secret', 'textarea', 'file'}.contains(f['type'])) {
        secrets.add(f['key'] as String);
      }
    }
  }
  var version = 1;
  return MockClient((request) async {
    final path = request.url.path;
    if (path == '/me/credentials') {
      // GET/DELETE 的 skill_id 在 query，PUT 的在 body —— 分开取，别混
      if (request.method == 'GET' || request.method == 'DELETE') {
        final sid = request.url.queryParameters['skill_id'] ?? '';
        if (request.method == 'GET') {
          final vals = credState[sid] ?? <String, dynamic>{};
          final masked = <String, dynamic>{
            for (final e in vals.entries)
              if (secrets.contains(e.key)) e.key: null else e.key: e.value,
          };
          return http.Response(
            jsonEncode({'configured': vals.isNotEmpty, 'values': masked}),
            200,
            headers: _jsonHeaders,
          );
        }
        credPutLog?.add(request);
        if (failCredentials) {
          return http.Response.bytes(utf8.encode(jsonEncode({'detail': 'store down'})), 500);
        }
        credState.remove(sid);
        version++;
        return http.Response(
          jsonEncode({
            'user_id': request.url.queryParameters['user_id'],
            'skill_id': sid,
            'version': version,
          }),
          200,
          headers: _jsonHeaders,
        );
      }
      if (request.method == 'PUT') {
        credPutLog?.add(request);
        if (failCredentials) {
          return http.Response.bytes(utf8.encode(jsonEncode({'detail': 'store down'})), 500);
        }
        final body = jsonDecode(request.body) as Map<String, dynamic>;
        final sid = body['skill_id'] as String;
        credState[sid] = (body['values'] as Map).cast<String, dynamic>();
        version++;
        return http.Response(
          jsonEncode({'user_id': body['user_id'], 'skill_id': sid, 'version': version}),
          200,
          headers: _jsonHeaders,
        );
      }
    }
    if (request.method == 'PUT') {
      putLog?.add(request);
      if (failOnState) {
        return http.Response.bytes(utf8.encode(jsonEncode({'error': 'store down'})), 500);
      }
      final body = jsonDecode(request.body) as Map<String, dynamic>;
      if (path == '/me/skills/enabled') {
        final sid = body['skill_id'] as String;
        if (body['enabled'] as bool) {
          purchasedSet.add(sid); // 开启即自动选购
          enabledMap[sid] = true;
        } else {
          enabledMap[sid] = false; // 停用保留选购
        }
        version++;
      } else if (path == '/me/skills/remove') {
        purchasedSet.remove(body['skill_id']);
        enabledMap.remove(body['skill_id']);
        version++;
      } else if (path == '/me/skills') {
        // 全量替换（web 契约，页面已不用）
        purchasedSet
          ..clear()
          ..addAll((body['skill_ids'] as List).cast<String>());
        enabledMap
          ..clear()
          ..addEntries(purchasedSet.map((s) => MapEntry(s, true)));
        version++;
      }
      return http.Response(
        jsonEncode({'user_id': body['user_id'], 'version': version}),
        200,
        headers: _jsonHeaders,
      );
    }
    if (path == '/skills') {
      return http.Response(
        jsonEncode({'skills': catalog ?? _catalog()}),
        200,
        headers: _jsonHeaders,
      );
    }
    if (path == '/me/skills/detail') {
      // 已选购详情（含已下架）：目录里的已选购 → active；[offShelf] 传入的 → inactive。
      // enabled 取自 enabledMap（停用保留选购），下架技能默认沿用真实状态。
      final rows = <Map<String, dynamic>>[];
      for (final m in catalog ?? _catalog()) {
        if (purchasedSet.contains(m['skill_id'])) {
          rows.add({
            'skill_id': m['skill_id'],
            'name': m['name'],
            'icon': m['icon'] ?? '',
            'description': m['description'] ?? '',
            'status': 'active',
            'enabled': enabledMap[m['skill_id']] ?? false,
          });
        }
      }
      for (final o in offShelf) {
        rows.add({
          'skill_id': o['skill_id'],
          'name': o['name'],
          'icon': o['icon'] ?? '',
          'description': o['description'] ?? '',
          'status': 'inactive',
          'enabled': enabledMap[o['skill_id']] ?? true,
        });
      }
      return http.Response(
        jsonEncode({
          'user_id': request.url.queryParameters['user_id'],
          'version': version,
          'skills': rows,
        }),
        200,
        headers: _jsonHeaders,
      );
    }
    if (path == '/me/skills') {
      return http.Response(
        jsonEncode({
          'user_id': request.url.queryParameters['user_id'],
          'skill_ids': purchasedSet.toList(),
          'enabled': enabledMap,
        }),
        200,
        headers: _jsonHeaders,
      );
    }
    return http.Response('not found', 404);
  });
}

/// P4.2 byok 演示技能：api_key(secret,必填,header 注入) + region(select,必填,query 注入)。
Map<String, dynamic> _byokSkill() => {
      'skill_id': 'region-mcp',
      'name': '区域天气（MCP）',
      'description': '查区域天气（byok 凭证示例）',
      'intent': 'region_forecast',
      'credentials': {
        'type': 'byok',
        'schema': [
          {
            'key': 'api_key',
            'label': 'API Key',
            'type': 'secret',
            'required': true,
            'inject': {'where': 'header', 'name': 'X-API-Key', 'prefix': 'Bearer '},
          },
          {
            'key': 'region',
            'label': '区域',
            'type': 'select',
            'required': true,
            'options': ['cn', 'us'],
            'inject': {'where': 'query', 'name': 'region'},
          },
        ],
      },
    };

List<Map<String, dynamic>> _withByok(List<Map<String, dynamic>> base) =>
    [...base, _byokSkill()];

Future<void> _pumpStorePage(
  WidgetTester tester, {
  required http.Client client,
  VoidCallback? onSkillsSaved,
  Map<String, String> prefs = const {},
}) async {
  SharedPreferences.setMockInitialValues(prefs);
  final settings = SettingsController();
  await settings.load();
  await tester.pumpWidget(
    MultiProvider(
      providers: [ChangeNotifierProvider.value(value: settings)],
      child: MaterialApp(
        home: SkillStorePage(
          apiFactory: (baseUrl) => SkillStoreApi(baseUrl: baseUrl, client: client),
          onSkillsSaved: onSkillsSaved,
        ),
      ),
    ),
  );
  await tester.pumpAndSettle();
}

void main() {
  testWidgets('渲染目录卡片：图标/名称/描述/关键词/启用开关', (tester) async {
    await _pumpStorePage(tester, client: _storeClient());

    expect(find.text('天气查询（MCP）'), findsOneWidget);
    expect(find.text('股票查询（MCP）'), findsOneWidget);
    expect(find.text('查实时天气（确定性路由示例）'), findsOneWidget);
    expect(find.text('天气'), findsOneWidget);
    expect(find.text('天气查询'), findsOneWidget);
    expect(find.text('股价'), findsOneWidget);
    // 每卡一个「启用」开关 + 顶部 hint
    expect(find.byType(Switch), findsNWidgets(2));
    expect(find.text('启用'), findsNWidgets(2));
    expect(find.textContaining('≤30s 生效'), findsOneWidget);
    // 未选购 → 无「已选购」标签、无退订按钮
    expect(find.text('已选购'), findsNothing);
    expect(find.widgetWithText(TextButton, '退订'), findsNothing);
  });

  testWidgets('开关初值 = 已启用集合；已选购技能带标签', (tester) async {
    await _pumpStorePage(
      tester,
      client: _storeClient(
        purchased: {'weather-mcp', 'stock-mcp'},
        enabled: {'weather-mcp': true, 'stock-mcp': false}, // weather 启用，stock 停用
      ),
    );

    final switches = tester.widgetList<Switch>(find.byType(Switch)).toList();
    expect(switches, hasLength(2));
    expect(switches[0].value, isTrue); // weather 启用
    expect(switches[1].value, isFalse); // stock 停用
    // 两个都已选购 → 两个「已选购」标签 + 两个退订按钮
    expect(find.text('已选购'), findsNWidgets(2));
    expect(find.widgetWithText(TextButton, '退订'), findsNWidgets(2));
  });

  testWidgets('勾启未选购技能 → enabled PUT + 自动选购 + 已选购标签 + onSkillsSaved', (tester) async {
    final putLog = <http.Request>[];
    var savedCalled = false;
    await _pumpStorePage(
      tester,
      client: _storeClient(purchased: {'weather-mcp'}, enabled: {'weather-mcp': true}, putLog: putLog),
      onSkillsSaved: () => savedCalled = true,
    );

    expect(find.text('已选购'), findsOneWidget); // 仅 weather
    await tester.tap(find.byType(Switch).at(1)); // 勾启 stock
    await tester.pumpAndSettle();

    expect(putLog, hasLength(1));
    final body = jsonDecode(putLog.single.body) as Map<String, dynamic>;
    expect(body['skill_id'], 'stock-mcp');
    expect(body['enabled'], isTrue);
    expect(savedCalled, isTrue);
    expect(find.textContaining('已启用'), findsOneWidget);
    // stock 变为已选购 → 两个标签
    expect(find.text('已选购'), findsNWidgets(2));
    final switches = tester.widgetList<Switch>(find.byType(Switch)).toList();
    expect(switches.every((s) => s.value), isTrue);
  });

  testWidgets('停用已选购技能 → enabled PUT false，保留已选购标签', (tester) async {
    final putLog = <http.Request>[];
    await _pumpStorePage(
      tester,
      client: _storeClient(
        purchased: {'weather-mcp'},
        enabled: {'weather-mcp': true},
        putLog: putLog,
      ),
    );

    await tester.tap(find.byType(Switch).at(0)); // 停用 weather
    await tester.pumpAndSettle();

    expect(putLog, hasLength(1));
    final body = jsonDecode(putLog.single.body) as Map<String, dynamic>;
    expect(body['skill_id'], 'weather-mcp');
    expect(body['enabled'], isFalse);
    expect(find.textContaining('已停用'), findsOneWidget);
    // 停用保留选购：标签仍在，开关关
    expect(find.text('已选购'), findsOneWidget);
    final switches = tester.widgetList<Switch>(find.byType(Switch)).toList();
    expect(switches[0].value, isFalse);
    expect(switches[1].value, isFalse);
  });

  testWidgets('退订 → 确认弹窗 → remove PUT → 标签消失、开关复位', (tester) async {
    final putLog = <http.Request>[];
    await _pumpStorePage(
      tester,
      client: _storeClient(
        purchased: {'weather-mcp'},
        enabled: {'weather-mcp': true},
        putLog: putLog,
      ),
    );

    await tester.tap(find.widgetWithText(TextButton, '退订'));
    await tester.pumpAndSettle();
    expect(find.text('退订技能'), findsOneWidget); // 确认弹窗
    await tester.tap(find.widgetWithText(FilledButton, '退订'));
    await tester.pumpAndSettle();

    expect(putLog, hasLength(1));
    expect(putLog.single.url.path, '/me/skills/remove');
    final body = jsonDecode(putLog.single.body) as Map<String, dynamic>;
    expect(body['skill_id'], 'weather-mcp');
    expect(find.textContaining('已退订'), findsOneWidget);
    // 退订后：无标签、开关全关
    expect(find.text('已选购'), findsNothing);
    final switches = tester.widgetList<Switch>(find.byType(Switch)).toList();
    expect(switches.every((s) => s.value), isFalse);
  });

  testWidgets('启/停/退订失败 → 回滚到上次成功状态 + 失败提示', (tester) async {
    await _pumpStorePage(
      tester,
      client: _storeClient(
        purchased: {'weather-mcp'},
        enabled: {'weather-mcp': true},
        failOnState: true,
      ),
    );

    await tester.tap(find.byType(Switch).at(1)); // 尝试勾启 stock → 500
    await tester.pumpAndSettle();

    expect(find.textContaining('保存失败'), findsOneWidget);
    // 回滚：stock 未选购、未启用；weather 仍启用
    expect(find.text('已选购'), findsOneWidget);
    final switches = tester.widgetList<Switch>(find.byType(Switch)).toList();
    expect(switches[0].value, isTrue);
    expect(switches[1].value, isFalse);
  });

  testWidgets('连接失败 → 错误态可重试', (tester) async {
    var calls = 0;
    final client = MockClient((request) async {
      calls++;
      throw http.ClientException('Connection refused');
    });
    await _pumpStorePage(tester, client: client);

    expect(find.textContaining('连接技能商店失败'), findsOneWidget);
    expect(find.text('重试'), findsOneWidget);
    expect(find.text('去设置'), findsOneWidget);
    expect(find.byType(Switch), findsNothing);
    expect(calls, 3); // 一次 _load = listSkills + getMySkills + getMySkillsDetail 三路请求

    await tester.tap(find.text('重试'));
    await tester.pumpAndSettle();
    expect(calls, 6);
    expect(find.text('重试'), findsOneWidget);
  });

  testWidgets('字段类型异常 → 宽容降级渲染，不崩不转圈', (tester) async {
    // icon 类型错（非 String）：解析宽容回退 null，卡片正常渲染、图标回退 🧩
    await _pumpStorePage(
      tester,
      client: _storeClient(catalog: [
        {'skill_id': 'bad', 'name': '坏数据', 'icon': 123},
      ]),
    );

    expect(find.byType(CircularProgressIndicator), findsNothing);
    expect(find.text('坏数据'), findsOneWidget);
    expect(find.text('🧩'), findsOneWidget); // 图标回退
  });

  // ---- P4.2 动态凭证：状态行 + 表单弹窗 + 保存/清空 ----

  testWidgets('byok 技能未配置 → 卡片显示「需配置凭证」，none 技能不显示凭证行', (tester) async {
    await _pumpStorePage(tester, client: _storeClient(catalog: _withByok(_catalog())));

    expect(find.text('需配置凭证'), findsOneWidget);
    expect(find.text('凭证已配置'), findsNothing);
  });

  testWidgets('byok 已配置 → 卡片显示「凭证已配置」', (tester) async {
    await _pumpStorePage(
      tester,
      client: _storeClient(
        catalog: _withByok(_catalog()),
        credValues: {'region-mcp': {'api_key': 'k-123', 'region': 'cn'}},
      ),
    );

    expect(find.text('凭证已配置'), findsOneWidget);
  });

  testWidgets('配置凭证：填 api_key + 选 region → 保存 → PUT + version 提示 + 状态刷新', (tester) async {
    final credPutLog = <http.Request>[];
    await _pumpStorePage(
      tester,
      client: _storeClient(catalog: _withByok(_catalog()), credPutLog: credPutLog),
    );

    await tester.tap(find.text('需配置凭证'));
    await tester.pumpAndSettle();
    expect(find.text('配置「区域天气（MCP）」凭证'), findsOneWidget);

    await tester.enterText(find.byType(TextField).first, 'mock-secret-key-123');
    await tester.tap(find.widgetWithText(FilledButton, '保存')); // region 默认 cn
    await tester.pumpAndSettle();

    expect(credPutLog, hasLength(1));
    final body = jsonDecode(credPutLog.single.body) as Map<String, dynamic>;
    expect(body['skill_id'], 'region-mcp');
    expect(body['values'], {'api_key': 'mock-secret-key-123', 'region': 'cn'});
    expect(find.textContaining('凭证已保存'), findsOneWidget);
    expect(find.text('凭证已配置'), findsOneWidget); // 保存后 reload → 状态刷新
  });

  testWidgets('已配置打开：secret 不预填明文（留空保留旧值 hint），select 预填', (tester) async {
    await _pumpStorePage(
      tester,
      client: _storeClient(
        catalog: _withByok(_catalog()),
        credValues: {'region-mcp': {'api_key': 'k-123', 'region': 'cn'}},
      ),
    );

    await tester.tap(find.text('凭证已配置'));
    await tester.pumpAndSettle();

    final tfs = tester.widgetList<TextField>(find.byType(TextField)).toList();
    expect(tfs, hasLength(1));
    expect(tfs.single.controller!.text, isEmpty); // secret 不回填明文
    expect(find.text('已保存则不填以保留'), findsOneWidget);
    expect(find.text('cn'), findsOneWidget); // select 预填
  });

  testWidgets('必填校验：api_key 留空（未配置）→ 拦截且不发 PUT', (tester) async {
    final credPutLog = <http.Request>[];
    await _pumpStorePage(
      tester,
      client: _storeClient(catalog: _withByok(_catalog()), credPutLog: credPutLog),
    );

    await tester.tap(find.text('需配置凭证'));
    await tester.pumpAndSettle();
    await tester.tap(find.widgetWithText(FilledButton, '保存')); // api_key 空
    await tester.pumpAndSettle();

    expect(find.text('「API Key」必填'), findsOneWidget);
    expect(credPutLog, isEmpty);
    expect(find.text('配置「区域天气（MCP）」凭证'), findsOneWidget); // 弹窗不关
  });

  testWidgets('保存失败 → 弹窗内报错，不关闭', (tester) async {
    await _pumpStorePage(
      tester,
      client: _storeClient(catalog: _withByok(_catalog()), failCredentials: true),
    );

    await tester.tap(find.text('需配置凭证'));
    await tester.pumpAndSettle();
    await tester.enterText(find.byType(TextField).first, 'k');
    await tester.tap(find.widgetWithText(FilledButton, '保存'));
    await tester.pumpAndSettle();

    expect(find.textContaining('保存失败'), findsOneWidget);
    expect(find.text('配置「区域天气（MCP）」凭证'), findsOneWidget);
  });

  testWidgets('已配置 → 清空凭证 → DELETE + 状态刷新为「需配置」', (tester) async {
    final credPutLog = <http.Request>[];
    await _pumpStorePage(
      tester,
      client: _storeClient(
        catalog: _withByok(_catalog()),
        credValues: {'region-mcp': {'api_key': 'k-123', 'region': 'cn'}},
        credPutLog: credPutLog,
      ),
    );

    await tester.tap(find.text('凭证已配置'));
    await tester.pumpAndSettle();
    await tester.tap(find.widgetWithText(TextButton, '清空凭证'));
    await tester.pumpAndSettle();

    expect(credPutLog, hasLength(1));
    expect(credPutLog.single.method, 'DELETE');
    expect(credPutLog.single.url.path, '/me/credentials');
    expect(find.textContaining('凭证已保存'), findsOneWidget);
    expect(find.text('需配置凭证'), findsOneWidget); // reload 后未配置
  });

  testWidgets('启用 unconfigured byok 技能 → 自动弹凭证表单，不叠普通提示', (tester) async {
    final putLog = <http.Request>[];
    await _pumpStorePage(
      tester,
      client: _storeClient(catalog: _withByok(_catalog()), putLog: putLog),
    );

    expect(find.text('需配置凭证'), findsOneWidget);
    await tester.tap(find.byType(Switch).at(2)); // 启用 region-mcp（未选购、未配凭证）
    await tester.pumpAndSettle();

    // enabled PUT 成功 → 立即自动弹凭证表单
    expect(putLog, hasLength(1));
    expect(putLog.single.url.path, '/me/skills/enabled');
    final body = jsonDecode(putLog.single.body) as Map<String, dynamic>;
    expect(body['skill_id'], 'region-mcp');
    expect(body['enabled'], isTrue);
    expect(find.text('配置「区域天气（MCP）」凭证'), findsOneWidget);
    // 弹窗时不叠「已启用」snackbar
    expect(find.textContaining('已启用'), findsNothing);
  });

  // ---- 已下架（已选购）：状态隔离，用户仍可停用/退订 ----

  Map<String, dynamic> offShelfRegion() => {
        'skill_id': 'region-mcp',
        'name': '区域天气',
        'icon': '🌦️',
        'description': '管理员下架的旧技能',
      };

  testWidgets('已下架技能（已选购）渲染在已下架区：停用/退订可点，不在目录、无启用开关', (tester) async {
    await _pumpStorePage(
      tester,
      client: _storeClient(
        purchased: {'weather-mcp', 'region-mcp'},
        enabled: {'weather-mcp': true, 'region-mcp': true},
        offShelf: [offShelfRegion()],
      ),
    );

    expect(find.text('已下架（已选购 · 管理员下架中，仍可停用/退订）'), findsOneWidget);
    expect(find.text('区域天气'), findsOneWidget); // 下架区渲染
    expect(find.text('已下架'), findsOneWidget); // badge
    expect(find.text('天气查询（MCP）'), findsOneWidget); // 目录仍在
    // 目录两张卡（天气+股票）各有启用开关，下架卡不给启用（只有停用/退订）
    expect(find.byType(Switch), findsNWidgets(2));
    expect(find.widgetWithText(TextButton, '停用'), findsOneWidget);
    expect(find.widgetWithText(TextButton, '退订'), findsNWidgets(2)); // 天气 + 区域
  });

  testWidgets('停用已下架技能 → enabled PUT false → 状态文字变为已停用', (tester) async {
    final putLog = <http.Request>[];
    await _pumpStorePage(
      tester,
      client: _storeClient(
        purchased: {'region-mcp'},
        enabled: {'region-mcp': true},
        offShelf: [offShelfRegion()],
        putLog: putLog,
      ),
    );

    expect(find.text('当前仍启用中，停用后不再路由'), findsOneWidget);
    await tester.tap(find.widgetWithText(TextButton, '停用'));
    await tester.pumpAndSettle();

    expect(putLog, hasLength(1));
    expect(putLog.single.url.path, '/me/skills/enabled');
    final body = jsonDecode(putLog.single.body) as Map<String, dynamic>;
    expect(body['skill_id'], 'region-mcp');
    expect(body['enabled'], isFalse);
    expect(find.textContaining('已停用'), findsWidgets); // snack
    expect(find.text('已停用'), findsOneWidget); // 卡片状态文字
  });

  testWidgets('退订已下架技能 → 确认弹窗 → remove PUT → 卡片消失', (tester) async {
    final putLog = <http.Request>[];
    await _pumpStorePage(
      tester,
      client: _storeClient(
        purchased: {'weather-mcp', 'region-mcp'},
        enabled: {'weather-mcp': true, 'region-mcp': true},
        offShelf: [offShelfRegion()],
        putLog: putLog,
      ),
    );

    await tester.tap(find.widgetWithText(TextButton, '退订').at(1)); // 下架区退订
    await tester.pumpAndSettle();
    expect(find.text('退订技能'), findsOneWidget);
    expect(find.text('从「区域天气」退订后将不再保留选购，确定吗？'), findsOneWidget);
    await tester.tap(find.widgetWithText(FilledButton, '退订'));
    await tester.pumpAndSettle();

    expect(putLog, hasLength(1));
    expect(putLog.single.url.path, '/me/skills/remove');
    final body = jsonDecode(putLog.single.body) as Map<String, dynamic>;
    expect(body['skill_id'], 'region-mcp');
    expect(find.textContaining('已退订'), findsOneWidget);
    expect(find.text('区域天气'), findsNothing); // 退订后卡片消失
    expect(find.text('已下架（已选购 · 管理员下架中，仍可停用/退订）'), findsNothing); // 空区隐藏
  });
}
