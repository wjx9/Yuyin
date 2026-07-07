/// A2uiCardView 渲染测试（真机/模拟器跑：flutter test integration_test -d 设备id）。
///
/// 为什么不放 test/：genui 的传递依赖（jni/objective_c）带 native-assets 构建钩子，
/// 宿主机 flutter_tester 编译路径会卡死；设备上的插件管线正常。
///
/// 注意统一用有界 pump 而非 pumpAndSettle：live binding 下 pumpAndSettle 会因设备端
/// 持续的帧调度不收敛而卡死（实测），静态卡片 pump 两拍足够。
library;

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:integration_test/integration_test.dart';
import 'package:moasm_vui/src/a2ui/a2ui_card_view.dart';
import 'package:moasm_vui/src/a2ui/a2ui_theme.dart';

/// 与 server_py/a2ui 生成的消息同构（news 卡片）。
List<Map<String, dynamic>> _newsMessages() => [
      {
        'version': 'v0.9',
        'createSurface': {
          'surfaceId': 'srf-test1',
          'catalogId': 'https://a2ui.org/specification/v0_9/basic_catalog.json',
        },
      },
      {
        'version': 'v0.9',
        'updateComponents': {
          'surfaceId': 'srf-test1',
          'components': [
            {'id': 'root', 'component': 'Card', 'child': 'col'},
            {
              'id': 'col',
              'component': 'Column',
              'children': ['title', 'sep', 'item0', 'meta0'],
            },
            {'id': 'title', 'component': 'Text', 'text': '搜索「美国」', 'variant': 'h4'},
            {'id': 'sep', 'component': 'Divider'},
            {'id': 'item0', 'component': 'Text', 'text': '某条新闻标题'},
            {
              'id': 'meta0',
              'component': 'Text',
              'text': '封面新闻 · 07-04 07:25',
              'variant': 'caption',
            },
          ],
        },
      },
    ];

Widget _host(Widget child) =>
    MaterialApp(home: Scaffold(body: SingleChildScrollView(child: child)));

Future<void> _pumpTwice(WidgetTester tester) async {
  await tester.pump();
  await tester.pump(const Duration(milliseconds: 400));
}

void main() {
  IntegrationTestWidgetsFlutterBinding.ensureInitialized();

  testWidgets('渲染 Card 根与新闻内容', (tester) async {
    await tester.pumpWidget(_host(A2uiCardView(messages: _newsMessages())));
    await _pumpTwice(tester);

    expect(find.byType(Card), findsOneWidget);
    // Text 组件经 Markdown 渲染，用 textContaining 匹配
    expect(find.textContaining('搜索「美国」'), findsOneWidget);
    expect(find.textContaining('某条新闻标题'), findsOneWidget);
    expect(find.textContaining('封面新闻'), findsOneWidget);
  });

  testWidgets('卡片是黑底绿描边（穿戴主题）', (tester) async {
    await tester.pumpWidget(_host(A2uiCardView(messages: _newsMessages())));
    await _pumpTwice(tester);

    final card = tester.widget<Card>(find.byType(Card));
    expect(card.color, a2uiBlack); // 黑底模拟透明
    final theme = Theme.of(tester.element(find.byType(Card)));
    final side = (theme.cardTheme.shape! as RoundedRectangleBorder).side;
    expect(side.color, a2uiGreen); // 单绿描边
  });

  testWidgets('坏消息不崩、不占位', (tester) async {
    await tester.pumpWidget(_host(A2uiCardView(messages: const [
      {'version': 'v0.9', 'nonsense': {}},
      {'version': 'v0.8'},
    ])));
    await _pumpTwice(tester);

    expect(find.byType(Card), findsNothing);
    expect(tester.takeException(), isNull);
  });
}
