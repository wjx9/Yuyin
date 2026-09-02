// AppConfig.effectiveStoreUrl 派生 + copyWith 清空语义（纯单元，不依赖平台插件）。
import 'package:flutter_test/flutter_test.dart';
import 'package:moasm_vui/src/config/app_config.dart';

void main() {
  AppConfig cfg({String serverUrl = 'http://10.0.2.2:8000', String? storeUrl}) =>
      AppConfig(serverUrl: serverUrl, sessionId: 's1', storeUrl: storeUrl);

  test('storeUrl 为空 → 由 serverUrl 派生同 host 的 :9000', () {
    expect(cfg(serverUrl: 'http://10.0.2.2:8000').effectiveStoreUrl, 'http://10.0.2.2:9000');
    expect(cfg(serverUrl: 'http://192.168.1.5:8000').effectiveStoreUrl, 'http://192.168.1.5:9000');
  });

  test('serverUrl 缺 scheme → 派生自动补 http://', () {
    expect(cfg(serverUrl: '192.168.1.5:8000').effectiveStoreUrl, 'http://192.168.1.5:9000');
  });

  test('显式 storeUrl 覆盖派生', () {
    expect(cfg(storeUrl: 'http://10.0.2.2:9999').effectiveStoreUrl, 'http://10.0.2.2:9999');
  });

  test('storeUrl 为空白串 → 跟随服务端派生', () {
    expect(cfg(storeUrl: '   ').effectiveStoreUrl, 'http://10.0.2.2:9000');
  });

  test('serverUrl 为空/畸形 → effectiveStoreUrl 返回 null', () {
    expect(cfg(serverUrl: '').effectiveStoreUrl, isNull);
    expect(cfg(serverUrl: '   ').effectiveStoreUrl, isNull);
  });

  test('copyWith(clearStoreUrl:true) 把 storeUrl 清成 null', () {
    final c = cfg(storeUrl: 'http://10.0.2.2:9999');
    expect(c.copyWith(clearStoreUrl: true).effectiveStoreUrl, 'http://10.0.2.2:9000');
  });

  test('copyWith(storeUrl: 新值) 覆盖；不传时保持原值', () {
    final c = cfg(storeUrl: 'http://10.0.2.2:9999');
    expect(c.copyWith(storeUrl: 'http://192.168.1.5:9000').effectiveStoreUrl, 'http://192.168.1.5:9000');
    expect(c.copyWith().effectiveStoreUrl, 'http://10.0.2.2:9999');
  });
}
