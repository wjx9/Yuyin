import 'package:flutter_test/flutter_test.dart';
import 'package:moasm_vui/src/services/coordinate_service.dart';

void main() {
  test('中国境内 WGS84 坐标转换为 GCJ-02', () {
    final result = CoordinateService.wgs84ToGcj02(113.9217094, 22.5748814);

    expect(result.longitude, closeTo(113.9272, 0.002));
    expect(result.latitude, closeTo(22.5727, 0.002));
  });

  test('中国境外坐标不转换', () {
    final result = CoordinateService.wgs84ToGcj02(-73.9857, 40.7484);

    expect(result.longitude, -73.9857);
    expect(result.latitude, 40.7484);
  });
}
