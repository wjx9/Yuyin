import 'package:geolocator/geolocator.dart';
import 'package:flutter/foundation.dart';
import 'coordinate_service.dart';

/// 读取手机前台当前位置，并转换成高德需要的“经度,纬度”字符串。
class LocationService {
  Future<String?> currentLocation() async {
    if (!await Geolocator.isLocationServiceEnabled()) {
      return null;
    }

    var permission = await Geolocator.checkPermission();
    if (permission == LocationPermission.denied) {
      permission = await Geolocator.requestPermission();
    }

    if (permission == LocationPermission.denied ||
        permission == LocationPermission.deniedForever) {
      return null;
    }

    final position = await Geolocator.getCurrentPosition(
      locationSettings: const LocationSettings(
        accuracy: LocationAccuracy.high,
        timeLimit: Duration(seconds: 20),
      ),
    );
    final gcj02 = CoordinateService.wgs84ToGcj02(position.longitude, position.latitude);
    debugPrint(
      'GPS: wgs84=${position.longitude},${position.latitude}; '
      'gcj02=${gcj02.amapText}; '
      'accuracy=${position.accuracy.toStringAsFixed(1)}m, '
      'timestamp=${position.timestamp}, mocked=${position.isMocked}',
    );
    return gcj02.amapText;
  }
}
