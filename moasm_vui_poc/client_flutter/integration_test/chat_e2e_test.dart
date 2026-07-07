/// 真机端到端：真实 app + 真实服务端，验证"问新闻 → A2UI 卡片上屏"。
///
/// 前置条件（由联调脚本保证）：
///   - PC 上 serve.py 已启动；
///   - adb reverse 已把设备 8000 端口映射到 PC 服务端口（本项目手机访问 PC
///     只能走 adb reverse，见项目记忆）；
///   - 设备上该 app 的 shared_preferences 里 server_url=http://127.0.0.1:8000。
///
/// 跑法（flutter drive 才会把截图存到宿主机）：
///   flutter drive --driver=test_driver/integration_test.dart \
///     --target=integration_test/chat_e2e_test.dart -d 设备id
library;

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:integration_test/integration_test.dart';
import 'package:moasm_vui/main.dart' as app;
import 'package:moasm_vui/src/a2ui/a2ui_card_view.dart';

/// 有界轮询直到 finder 命中（live binding 禁用 pumpAndSettle，见组件测试注释）。
Future<bool> _waitFor(
  WidgetTester tester,
  Finder finder, {
  Duration timeout = const Duration(seconds: 90),
}) async {
  final deadline = DateTime.now().add(timeout);
  while (DateTime.now().isBefore(deadline)) {
    await tester.pump(const Duration(milliseconds: 500));
    if (finder.evaluate().isNotEmpty) return true;
  }
  return false;
}

void main() {
  final binding = IntegrationTestWidgetsFlutterBinding.ensureInitialized();

  testWidgets('问"来3条美国的新闻"，A2UI 新闻卡片上屏', (tester) async {
    app.main();
    // 等主界面出现（配置加载 + /health 探活是异步的）
    expect(await _waitFor(tester, find.byType(TextField)), isTrue,
        reason: '主界面未出现');

    // Android 截图需先把 Flutter surface 转成可读图像（官方要求，只做一次）
    await binding.convertFlutterSurfaceToImage();
    await tester.pump();

    await tester.enterText(find.byType(TextField), '来3条美国的新闻');
    await tester.pump();
    await tester.tap(find.byIcon(Icons.send));

    // 服务端链路：Gemini 分类+抽槽 → 腾讯新闻 CLI → a2ui 生成，整程数秒
    expect(await _waitFor(tester, find.byType(A2uiCardView)), isTrue,
        reason: '90s 内未等到 A2UI 卡片');

    // 卡片内容：Card 根已渲出、含新闻标题头（服务端 title 组件）
    expect(find.byType(Card), findsWidgets);
    expect(find.textContaining('美国'), findsWidgets);

    await tester.pump(const Duration(seconds: 1));
    await binding.takeScreenshot('a2ui_news_card_on_device');
  });
}
