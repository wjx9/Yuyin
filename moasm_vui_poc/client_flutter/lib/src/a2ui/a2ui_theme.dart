/// A2UI 卡片的穿戴设备主题：单绿 + 灰度辅助信息 + 黑底模拟透明。
///
/// 为什么在客户端做主题而不是让服务端下发颜色：
///   目标设备是单色绿光显示的智能穿戴（AR 眼镜等），"长什么样"由端上硬件特性
///   决定；服务端只下发语义组件（标题/条目/分隔线），同一份 A2UI 在手机上
///   按此主题预览，在眼镜端换一份主题即可，卡片内容零改动。
///
/// 黑底=透明：眼镜光学显示上黑色即不发光（透明），手机上用纯黑背景模拟该效果。
library;

import 'package:flutter/material.dart';

/// 主色：单绿（模拟绿光 microLED）。
const Color a2uiGreen = Color(0xFF00FF66);

/// 辅助信息灰度（来源/时间等 caption）。
const Color a2uiGrey = Color(0xFF9E9E9E);

/// 黑底（模拟眼镜端的透明/不发光）。
const Color a2uiBlack = Colors.black;

/// 生成 A2UI 卡片专用 ThemeData。
///
/// genui 的组件从 Theme 取色：Card 用 colorScheme.surface、Text 各 variant 用
/// textTheme（body 走 DefaultTextStyle，由 [A2uiCardView] 里的 DefaultTextStyle
/// 包裹兜底）、Divider 用 dividerTheme。
ThemeData a2uiWearableTheme() {
  final base = ThemeData(brightness: Brightness.dark, useMaterial3: true);
  const green = a2uiGreen;
  const grey = a2uiGrey;

  TextStyle? paint(TextStyle? s, Color c, {FontWeight? w}) =>
      s?.copyWith(color: c, fontWeight: w);

  final text = base.textTheme;
  return base.copyWith(
    colorScheme: base.colorScheme.copyWith(
      surface: a2uiBlack, // Card 背景 = 黑（模拟透明）
      onSurface: green,
      primary: green,
      onPrimary: a2uiBlack,
      secondary: grey,
      outline: green,
    ),
    scaffoldBackgroundColor: a2uiBlack,
    textTheme: text.copyWith(
      headlineLarge: paint(text.headlineLarge, green, w: FontWeight.w600), // h1
      headlineMedium: paint(text.headlineMedium, green, w: FontWeight.w600), // h2
      headlineSmall: paint(text.headlineSmall, green, w: FontWeight.w600), // h3
      titleLarge: paint(text.titleLarge, green, w: FontWeight.w600), // h4（卡片标题）
      titleMedium: paint(text.titleMedium, green, w: FontWeight.w600), // h5
      bodyLarge: paint(text.bodyLarge, green),
      bodyMedium: paint(text.bodyMedium, green), // body / markdown 正文
      bodySmall: paint(text.bodySmall, grey), // caption → 灰度
      labelLarge: paint(text.labelLarge, green),
    ),
    cardTheme: base.cardTheme.copyWith(
      color: a2uiBlack,
      elevation: 0, // 黑底上无意义的阴影，去掉
      margin: EdgeInsets.zero,
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(12),
        side: const BorderSide(color: green, width: 1), // 绿色描边界定卡片
      ),
    ),
    dividerTheme: DividerThemeData(
      color: green.withValues(alpha: 0.35),
      thickness: 1,
      space: 12,
    ),
  );
}
