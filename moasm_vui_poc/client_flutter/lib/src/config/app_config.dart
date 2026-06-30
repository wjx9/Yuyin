/// 客户端配置（与 client_py/config.py 对称）：服务端地址 / 鉴权 / 位置 / 会话标识。
///
/// 不可变值对象（类比 Android 里一个 final 字段的 data class）。改配置 = copyWith 出
/// 一个新实例，由 SettingsController 负责持久化与通知，UI 永远拿到一致快照。
class AppConfig {
  /// 服务端地址。Android 模拟器用 10.0.2.2 直达宿主机；真机填 serve.py 打印的局域网 IP。
  final String serverUrl;

  /// 对应服务端 SERVER_AUTH_TOKEN；为空则不带鉴权头。
  final String? authToken;

  /// "经度,纬度"，供高德等基于位置的能力用；为空则服务端用其默认。
  final String? location;

  /// 我方平台账号；服务端据此 mock 取三方凭证。
  final String userId;

  /// 客户端生成并固定，服务端据此隔离多轮历史。
  final String sessionId;

  const AppConfig({
    required this.serverUrl,
    required this.sessionId,
    this.authToken,
    this.location,
    this.userId = 'mock-user',
  });

  bool get hasServer => serverUrl.trim().isNotEmpty;

  AppConfig copyWith({
    String? serverUrl,
    String? authToken,
    String? location,
    String? userId,
    String? sessionId,
    bool clearAuthToken = false,
    bool clearLocation = false,
  }) {
    return AppConfig(
      serverUrl: serverUrl ?? this.serverUrl,
      authToken: clearAuthToken ? null : (authToken ?? this.authToken),
      location: clearLocation ? null : (location ?? this.location),
      userId: userId ?? this.userId,
      sessionId: sessionId ?? this.sessionId,
    );
  }
}
