/// A2uiCardView：把服务端下发的 A2UI v0.9 消息渲染成穿戴风格卡片。
///
/// 定位与解耦（对应"先嵌聊天、后独立显示区"的要求）：
///   - 本模块只依赖 genui 与 a2ui_theme，不认识聊天页/ChatTurn/ChatApi；
///     入参就是原始消息 List<Map>。今后要做独立显示区（或搬到眼镜端工程），
///     整个 a2ui/ 目录原样拿走即可。
///   - 渲染完全交给 genui（SurfaceController + Surface），本文件不自绘组件：
///     服务端消息 → A2uiMessage.fromJson → controller.handleMessage → Surface。
///
/// 每个实例持有自己的 SurfaceController：卡片间互不影响，跟随 widget 生命周期
/// 释放（类比 Android：每张卡自带一个小型 ViewModel，onDestroy 时释放）。
library;

import 'package:flutter/material.dart';
import 'package:genui/genui.dart';

import 'a2ui_theme.dart';

class A2uiCardView extends StatefulWidget {
  /// A2UI v0.9 消息列表（createSurface / updateComponents / ...），时间正序。
  final List<Map<String, dynamic>> messages;

  const A2uiCardView({super.key, required this.messages});

  @override
  State<A2uiCardView> createState() => _A2uiCardViewState();
}

class _A2uiCardViewState extends State<A2uiCardView> {
  late final SurfaceController _controller;
  final List<String> _surfaceIds = [];
  bool _failed = false;

  @override
  void initState() {
    super.initState();
    _controller = SurfaceController(catalogs: [BasicCatalogItems.asCatalog()]);
    _feed();
  }

  /// 把消息按序喂给 genui；坏消息只丢弃该卡（置 _failed），不让异常穿透到聊天页。
  void _feed() {
    for (final raw in widget.messages) {
      try {
        final msg = A2uiMessage.fromJson(raw);
        _controller.handleMessage(msg);
        if (msg is CreateSurface) _surfaceIds.add(msg.surfaceId);
      } catch (e) {
        debugPrint('A2uiCardView: 消息解析失败，跳过该卡: $e');
        _failed = true;
      }
    }
    if (_surfaceIds.isEmpty) _failed = true;
  }

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    if (_failed && _surfaceIds.isEmpty) {
      // 卡片坏了不占位：上层（气泡）仍有完整 text 兜底展示
      return const SizedBox.shrink();
    }
    final theme = a2uiWearableTheme();
    return Theme(
      data: theme,
      // genui 的 Text(body) 走 DefaultTextStyle，需在此兜底成主题色
      child: DefaultTextStyle.merge(
        style: theme.textTheme.bodyMedium!,
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            for (final id in _surfaceIds)
              Padding(
                padding: const EdgeInsets.symmetric(vertical: 2),
                child: Surface(surfaceContext: _controller.contextFor(id)),
              ),
          ],
        ),
      ),
    );
  }
}
