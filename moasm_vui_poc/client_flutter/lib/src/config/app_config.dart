/// 客户端配置（与 client_py/config.py 对称）：服务端地址 / 鉴权 / 位置 / 会话标识。
///
/// 不可变值对象（类比 Android 里一个 final 字段的 data class）。改配置 = copyWith 出
/// 一个新实例，由 SettingsController 负责持久化与通知，UI 永远拿到一致快照。
class AppConfig {
  /// 服务端地址。Android 模拟器用 10.0.2.2 直达宿主机；真机填 serve.py 打印的局域网 IP。
  final String serverUrl;

  /// 技能商店地址。null/空 = 跟随服务端，通过 8000 的 `/skill-store` 代理访问。
  final String? storeUrl;

  /// 对应服务端 SERVER_AUTH_TOKEN；为空则不带鉴权头。
  final String? authToken;

  /// "经度,纬度"，供高德等基于位置的能力用；为空则服务端用其默认。
  final String? location;

  /// 我方平台账号；服务端据此 mock 取三方凭证，也决定商店按用户装配的技能（P3）。
  /// 默认 'demo' 对齐商店演示用户（web 页 uid、serve 的 SKILL_STORE_USER、seed）；
  /// 与它们不一致时，网页勾选的技能对 App 不生效。
  final String userId;

  /// 客户端生成并固定，服务端据此隔离多轮历史。
  final String sessionId;

  const AppConfig({
    required this.serverUrl,
    required this.sessionId,
    this.storeUrl,
    this.authToken,
    this.location,
    this.userId = 'demo',
  });

  bool get hasServer => serverUrl.trim().isNotEmpty;

  /// 实际商店地址：显式 [storeUrl] 优先；否则由 [serverUrl] 派生到 `/skill-store`。
  /// 两者都取不出合法地址（serverUrl 为空/畸形）时返回 null，页面据此提示去设置里配置。
  String? get effectiveStoreUrl {
    final explicit = storeUrl?.trim();
    if (explicit != null && explicit.isNotEmpty) return _ensureScheme(explicit);
    return deriveStoreUrl(serverUrl);
  }

  /// 由服务端地址派生商店地址：同 scheme+host，路径换成 `/skill-store`。
  static String? deriveStoreUrl(String serverUrl) {
    final withScheme = _ensureScheme(serverUrl.trim());
    if (withScheme == null) return null;
    final uri = Uri.tryParse(withScheme);
    if (uri == null || uri.host.isEmpty) return null;
    final port = uri.hasPort ? ':${uri.port}' : '';
    return '${uri.scheme}://${uri.host}$port/skill-store';
  }

  static String? _ensureScheme(String raw) {
    if (raw.isEmpty) return null;
    return raw.contains('://') ? raw : 'http://$raw';
  }

  AppConfig copyWith({
    String? serverUrl,
    String? storeUrl,
    String? authToken,
    String? location,
    String? userId,
    String? sessionId,
    bool clearAuthToken = false,
    bool clearLocation = false,
    bool clearStoreUrl = false,
  }) {
    return AppConfig(
      serverUrl: serverUrl ?? this.serverUrl,
      storeUrl: clearStoreUrl ? null : (storeUrl ?? this.storeUrl),
      authToken: clearAuthToken ? null : (authToken ?? this.authToken),
      location: clearLocation ? null : (location ?? this.location),
      userId: userId ?? this.userId,
      sessionId: sessionId ?? this.sessionId,
    );
  }
}
