/// flutter drive 宿主侧 driver：把 integration_test 里 takeScreenshot 的截图
/// 存到 client_flutter/screenshots/（联调取证用）。
library;

import 'dart:io';

import 'package:integration_test/integration_test_driver_extended.dart';

Future<void> main() => integrationDriver(
      onScreenshot: (String name, List<int> bytes, [Map<String, Object?>? args]) async {
        final file = File('screenshots/$name.png')..createSync(recursive: true);
        file.writeAsBytesSync(bytes);
        return true;
      },
    );
