/// SettingsController：持有并持久化 AppConfig（类比 ViewModel + SharedPreferences）。
///
/// 改配置后 notifyListeners()，ChatController 与 UI 都会收到更新。session_id 首启生成、
/// 之后固定（除非用户手动新建会话），保证服务端按它隔离多轮历史。
library;

import 'package:flutter/foundation.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:uuid/uuid.dart';

import '../config/app_config.dart';

class SettingsController extends ChangeNotifier {
  static const _kServerUrl = 'server_url';
  static const _kAuthToken = 'auth_token';
  static const _kLocation = 'location';
  static const _kUserId = 'user_id';
  static const _kSessionId = 'session_id';

  // Android 模拟器用 10.0.2.2 直达宿主机的 serve.py；真机请在设置里改成局域网 IP
  static const _defaultServerUrl = 'http://10.0.2.2:8000';
  static const _defaultLocation = '113.92,22.53'; // 深圳南山，供高德用

  SharedPreferences? _prefs;
  AppConfig _config = const AppConfig(serverUrl: _defaultServerUrl, sessionId: '');

  AppConfig get config => _config;

  Future<void> load() async {
    final prefs = _prefs = await SharedPreferences.getInstance();
    var sessionId = prefs.getString(_kSessionId);
    if (sessionId == null || sessionId.isEmpty) {
      sessionId = const Uuid().v4();
      await prefs.setString(_kSessionId, sessionId);
    }
    _config = AppConfig(
      serverUrl: prefs.getString(_kServerUrl) ?? _defaultServerUrl,
      authToken: _nullIfEmpty(prefs.getString(_kAuthToken)),
      location: prefs.getString(_kLocation) ?? _defaultLocation,
      userId: _nullIfEmpty(prefs.getString(_kUserId)) ?? 'mock-user',
      sessionId: sessionId,
    );
    notifyListeners();
  }

  /// 更新设置页可改的字段（留空的字段保持不变；显式清空用 clearXxx）。
  Future<void> update({
    String? serverUrl,
    String? authToken,
    String? location,
  }) async {
    _config = _config.copyWith(
      serverUrl: serverUrl,
      authToken: authToken,
      location: location,
      clearAuthToken: authToken != null && authToken.isEmpty,
      clearLocation: location != null && location.isEmpty,
    );
    final prefs = _prefs;
    if (prefs != null) {
      if (serverUrl != null) await prefs.setString(_kServerUrl, serverUrl);
      if (authToken != null) await prefs.setString(_kAuthToken, authToken);
      if (location != null) await prefs.setString(_kLocation, location);
    }
    notifyListeners();
  }

  /// 新建会话：换一个 session_id，相当于清空服务端侧的多轮上下文。
  Future<void> newSession() async {
    final sessionId = const Uuid().v4();
    _config = _config.copyWith(sessionId: sessionId);
    await _prefs?.setString(_kSessionId, sessionId);
    notifyListeners();
  }

  static String? _nullIfEmpty(String? s) => (s == null || s.isEmpty) ? null : s;
}
