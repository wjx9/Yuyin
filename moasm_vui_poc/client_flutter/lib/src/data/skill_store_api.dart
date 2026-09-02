/// SkillStoreApi：移动端通过主服务 :8000/skill-store 访问技能商店。
///
/// 选购三端点 + P4.2 动态凭证三端点（管理员功能手机上不做）：
///   GET /skills              目录（active 技能 + 完整 manifest）
///   GET /me/skills?user_id=  用户已选购的 skill_id 列表
///   PUT /me/skills           {user_id, skill_ids} 全量替换 + version+1
///   GET /me/credentials      凭证状态（脱敏，secret 字段值置 null）
///   PUT /me/credentials      {user_id, skill_id, values} 保存凭证 + version+1
///   DELETE /me/credentials   清空凭证 + version+1
library;

import 'dart:convert';

import 'package:http/http.dart' as http;

import 'chat_api.dart' show ApiException;

/// 技能（商店 manifest 的宽松映射：字段缺省/缺 key 都给默认值，不因旧数据崩）。
class Skill {
  final String skillId;
  final String name;
  final String description;
  final String? icon; // 图标：商店存的是 emoji 或图片 URL，空则 UI 回退 🧩
  final String? intent;
  final String kind; // builtin 或 mcp
  final List<String> keywords;
  final String? replaces;
  final String? mcpServer;
  final List<String> tools;
  final String? querySlot;
  final Map<String, dynamic>? credentials; // P4.2：{type, schema}；none 或无则 null

  const Skill({
    required this.skillId,
    required this.name,
    required this.description,
    this.icon,
    this.intent,
    this.kind = 'mcp',
    this.keywords = const [],
    this.replaces,
    this.mcpServer,
    this.tools = const [],
    this.querySlot,
    this.credentials,
  });

  factory Skill.fromJson(Map<String, dynamic> json) {
    String? s(Object? v) => v is String ? v : null;
    List<String> l(Object? v) => v is List ? v.whereType<String>().toList() : const [];
    return Skill(
      skillId: s(json['skill_id']) ?? '',
      name: s(json['name']) ?? '',
      description: s(json['description']) ?? '',
      icon: s(json['icon']),
      intent: s(json['intent']),
      kind: s(json['kind']) ?? 'mcp',
      keywords: l(json['keywords']),
      replaces: s(json['replaces']),
      // 商店 manifest 的 mcp_server 是对象 {'transport','url'}（见 skill_store seed），
      // 老数据也可能存字符串——两种都容忍，取不到 url 就 null。
      mcpServer: _mcpServerUrl(json['mcp_server']),
      tools: l(json['tools']),
      querySlot: s(json['query_slot']),
      // 宽容解析：credentials 不是 Map 时置 null（老数据/手填 manifest 拼错都不崩）
      credentials: json['credentials'] is Map<String, dynamic>
          ? json['credentials'] as Map<String, dynamic>
          : null,
    );
  }

  /// mcp_server 兼容 {transport,url} 对象或裸字符串，都只取 URL。
  static String? _mcpServerUrl(Object? v) {
    if (v is String) return v;
    if (v is Map) {
      final url = v['url'];
      return url is String ? url : null;
    }
    return null;
  }
}

/// 用户选购状态：已选购集合 + 每个已选购技能的启用状态（区分「已选购」与「已启用」）。
class MySkills {
  final Set<String> purchased; // 已选购的 skill_id
  final Map<String, bool> enabled; // {skill_id: 是否启用}，只含已选购

  const MySkills({required this.purchased, required this.enabled});
}

/// 已选购技能的详情（GET /me/skills/detail）：**含已下架**，供渲染「已下架」卡。
///
/// 管理员下架后技能不在目录里，但用户行被保留；靠本模型仍能展示并允许停用/退订。
class MyPurchasedSkill {
  final String skillId;
  final String name;
  final String icon; // 空串表示无图标
  final String description;
  final String status; // 'active' | 'inactive'
  final bool enabled; // 用户当前的启用状态（下架期间被保留）

  const MyPurchasedSkill({
    required this.skillId,
    required this.name,
    this.icon = '',
    this.description = '',
    this.status = 'active',
    this.enabled = false,
  });

  bool get isOffShelf => status != 'active'; // 已下架

  factory MyPurchasedSkill.fromJson(Map<String, dynamic> json) => MyPurchasedSkill(
        skillId: json['skill_id'] is String ? json['skill_id'] as String : '',
        name: json['name'] is String ? json['name'] as String : '',
        icon: json['icon'] is String ? json['icon'] as String : '',
        description: json['description'] is String ? json['description'] as String : '',
        status: json['status'] is String ? json['status'] as String : 'active',
        enabled: json['enabled'] == true,
      );
}

class SkillStoreApi {
  final String baseUrl; // 末尾无 /
  final Duration timeout;
  final http.Client _client;

  SkillStoreApi({
    required String baseUrl,
    this.timeout = const Duration(seconds: 15), // 商店是本地小服务，不用 120s
    http.Client? client,
  })  : baseUrl = baseUrl.trim().replaceAll(RegExp(r'/+$'), ''),
        _client = client ?? http.Client();

  /// 目录：active 技能列表。
  Future<List<Skill>> listSkills() async {
    final json = await _send('GET', '/skills', null);
    final list = json['skills'];
    if (list is! List) throw const ApiException('商店响应缺少 skills 列表');
    return list.whereType<Map<String, dynamic>>().map(Skill.fromJson).toList();
  }

  /// 用户选购状态（已选购集合 + 各技能启用状态）。enabled 字段缺失时宽容为全空。
  Future<MySkills> getMySkills(String userId) async {
    final uid = Uri.encodeQueryComponent(userId);
    final json = await _send('GET', '/me/skills?user_id=$uid', null);
    final ids = json['skill_ids'];
    if (ids is! List) throw const ApiException('商店响应缺少 skill_ids 列表');
    final enabled = <String, bool>{};
    final enabledJson = json['enabled'];
    if (enabledJson is Map) {
      enabledJson.forEach((k, v) {
        if (k is String && v is bool) enabled[k] = v;
      });
    }
    return MySkills(
      purchased: ids.whereType<String>().toSet(),
      enabled: enabled,
    );
  }

  /// 保存选购（全量替换 + version+1，全部启用）。返回新版本号；拿不到版本号返回 -1。
  Future<int> putMySkills(String userId, List<String> skillIds) async {
    final json =
        await _send('PUT', '/me/skills', {'user_id': userId, 'skill_ids': skillIds});
    final version = json['version'];
    return version is int ? version : -1;
  }

  /// 已选购技能详情（**含已下架**）：渲染「已下架」卡用（状态隔离：用户行下架期间被保留）。
  Future<List<MyPurchasedSkill>> getMySkillsDetail(String userId) async {
    final uid = Uri.encodeQueryComponent(userId);
    final json = await _send('GET', '/me/skills/detail?user_id=$uid', null);
    final list = json['skills'];
    if (list is! List) throw const ApiException('商店响应缺少 skills 列表');
    return list.whereType<Map<String, dynamic>>().map(MyPurchasedSkill.fromJson).toList();
  }

  /// 单技能启用/停用（未选购时开启即自动选购）。返回新版本号；拿不到返回 -1。
  Future<int> setEnabled(String userId, String skillId, bool enabled) async {
    final json = await _send('PUT', '/me/skills/enabled', {
      'user_id': userId,
      'skill_id': skillId,
      'enabled': enabled,
    });
    final version = json['version'];
    return version is int ? version : -1;
  }

  /// 退订：移除选购。返回新版本号；拿不到返回 -1。
  Future<int> removeSkill(String userId, String skillId) async {
    final json = await _send('PUT', '/me/skills/remove', {
      'user_id': userId,
      'skill_id': skillId,
    });
    final version = json['version'];
    return version is int ? version : -1;
  }

  /// 凭证状态（脱敏）：secret 字段值置 null，其余返回明文供表单预填。返回 {configured, values}。
  Future<Map<String, dynamic>> getCredentials(String userId, String skillId) async {
    final uid = Uri.encodeQueryComponent(userId);
    final sid = Uri.encodeQueryComponent(skillId);
    return _send('GET', '/me/credentials?user_id=$uid&skill_id=$sid', null);
  }

  /// 保存凭证 → version+1。敏感字段留空 = 保留旧值（商店端处理，见 main.py put_credentials）。
  /// 返回新版本号；拿不到返回 -1。
  Future<int> putCredentials(
      String userId, String skillId, Map<String, dynamic> values) async {
    final json = await _send('PUT', '/me/credentials', {
      'user_id': userId,
      'skill_id': skillId,
      'values': values,
    });
    final version = json['version'];
    return version is int ? version : -1;
  }

  /// 清空凭证 → version+1。返回新版本号；拿不到返回 -1。
  Future<int> deleteCredentials(String userId, String skillId) async {
    final uid = Uri.encodeQueryComponent(userId);
    final sid = Uri.encodeQueryComponent(skillId);
    final json =
        await _send('DELETE', '/me/credentials?user_id=$uid&skill_id=$sid', null);
    final version = json['version'];
    return version is int ? version : -1;
  }

  Future<Map<String, dynamic>> _send(
      String method, String path, Map<String, dynamic>? body) async {
    final uri = Uri.parse('$baseUrl$path');
    // 带 body 的请求必须声明 JSON 头，否则 FastAPI 把 body 当 dict 校验失败返回 422
    const jsonHeaders = {'Content-Type': 'application/json'};
    http.Response resp;
    try {
      final future = switch (method) {
        'GET' => _client.get(uri),
        'POST' => _client.post(uri, headers: jsonHeaders, body: jsonEncode(body)),
        'PUT' => _client.put(uri, headers: jsonHeaders, body: jsonEncode(body)),
        'DELETE' => _client.delete(uri), // 凭证清空：query 传参，无 body
        _ => throw ArgumentError('unsupported method $method'),
      };
      resp = await future.timeout(timeout);
    } catch (e) {
      throw ApiException('连接技能商店失败：$e');
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
      throw ApiException('商店返回 ${resp.statusCode}${detail.isNotEmpty ? '：$detail' : ''}');
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
