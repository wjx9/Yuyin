/// 中国大陆坐标系转换：手机通常返回 WGS84，高德 Web 服务使用 GCJ-02。
library;

import 'dart:math' as math;

class Coordinate {
  final double longitude;
  final double latitude;

  const Coordinate(this.longitude, this.latitude);

  String get amapText => '${longitude.toStringAsFixed(6)},${latitude.toStringAsFixed(6)}';
}

class CoordinateService {
  static const double _pi = math.pi;
  static const double _axis = 6378245.0;
  static const double _ee = 0.00669342162296594323;

  static Coordinate wgs84ToGcj02(double longitude, double latitude) {
    if (_outOfChina(longitude, latitude)) return Coordinate(longitude, latitude);
    final dLat = _transformLatitude(longitude - 105.0, latitude - 35.0);
    final dLon = _transformLongitude(longitude - 105.0, latitude - 35.0);
    final radLat = latitude / 180.0 * _pi;
    var magic = math.sin(radLat);
    magic = 1 - _ee * magic * magic;
    final sqrtMagic = math.sqrt(magic);
    final mgLat = latitude + (dLat * 180.0) /
        ((_axis * (1 - _ee)) / (magic * sqrtMagic) * _pi);
    final mgLon = longitude + (dLon * 180.0) /
        (_axis / sqrtMagic * math.cos(radLat) * _pi);
    return Coordinate(mgLon, mgLat);
  }

  static bool _outOfChina(double lon, double lat) =>
      lon < 72.004 || lon > 137.8347 || lat < 0.8293 || lat > 55.8271;

  static double _transformLatitude(double x, double y) {
    var ret = -100.0 + 2.0 * x + 3.0 * y + 0.2 * y * y +
        0.1 * x * y + 0.2 * math.sqrt(x.abs());
    ret += (20.0 * math.sin(6.0 * x * _pi) + 20.0 * math.sin(2.0 * x * _pi)) * 2.0 / 3.0;
    ret += (20.0 * math.sin(y * _pi) + 40.0 * math.sin(y / 3.0 * _pi)) * 2.0 / 3.0;
    ret += (160.0 * math.sin(y / 12.0 * _pi) + 320.0 * math.sin(y * _pi / 30.0)) * 2.0 / 3.0;
    return ret;
  }

  static double _transformLongitude(double x, double y) {
    var ret = 300.0 + x + 2.0 * y + 0.1 * x * x +
        0.1 * x * y + 0.1 * math.sqrt(x.abs());
    ret += (20.0 * math.sin(6.0 * x * _pi) + 20.0 * math.sin(2.0 * x * _pi)) * 2.0 / 3.0;
    ret += (20.0 * math.sin(x * _pi) + 40.0 * math.sin(x / 3.0 * _pi)) * 2.0 / 3.0;
    ret += (150.0 * math.sin(x / 12.0 * _pi) + 300.0 * math.sin(x * _pi / 30.0)) * 2.0 / 3.0;
    return ret;
  }
}
