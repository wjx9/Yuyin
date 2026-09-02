import 'package:flutter/foundation.dart';
import 'package:flutter/gestures.dart';
import 'package:flutter/material.dart';
import 'package:flutter/rendering.dart';
import 'package:flutter/services.dart';

/// 悬浮导航面板：把高德 AMapNaviView 以 PlatformView（Hybrid Composition）
/// 嵌入可拖拽、可最小化的悬浮面板，叠加在聊天界面之上。
///
/// POC 验证点：
/// - Hybrid Composition（initExpensiveAndroidView）下 SurfaceView 地图是否正常渲染；
/// - 小窗尺寸下导航 UI 是否可读；
/// - 拖拽/最小化/关闭是否流畅。
class NaviFloatingPanel extends StatefulWidget {
  final double lat;
  final double lon;
  final String? poiName;
  final String? poiId;

  /// 关闭面板（停止导航）。
  final VoidCallback onClose;

  /// 与原生端注册的 viewType 一致。
  static const String viewType = 'com.rayneo.moasm_vui/navi_floating_view';

  const NaviFloatingPanel({
    super.key,
    required this.lat,
    required this.lon,
    this.poiName,
    this.poiId,
    required this.onClose,
  });

  @override
  State<NaviFloatingPanel> createState() => _NaviFloatingPanelState();
}

class _NaviFloatingPanelState extends State<NaviFloatingPanel> {
  /// 面板位置（相对于屏幕左上角）。
  double _left = 16;
  double _top = 80;

  /// 面板尺寸。
  static const double _panelWidth = 300;
  static const double _panelHeight = 420;

  /// 最小化状态：只显示一个圆形入口，点击恢复。
  bool _minimized = false;

  /// 拖拽时的起始偏移，用于平滑拖拽。
  double _dragStartX = 0;
  double _dragStartY = 0;
  double _origLeft = 0;
  double _origTop = 0;

  @override
  Widget build(BuildContext context) {
    if (_minimized) {
      return _buildMinimized();
    }
    return _buildExpanded();
  }

  /// 最小化：圆形悬浮入口，可拖拽，点击恢复。
  Widget _buildMinimized() {
    return Positioned(
      left: _left,
      top: _top,
      child: GestureDetector(
        onPanStart: (d) {
          _dragStartX = d.globalPosition.dx;
          _dragStartY = d.globalPosition.dy;
          _origLeft = _left;
          _origTop = _top;
        },
        onPanUpdate: (d) {
          setState(() {
            _left = (_origLeft + d.globalPosition.dx - _dragStartX)
                .clamp(0.0, MediaQuery.of(context).size.width - 60);
            _top = (_origTop + d.globalPosition.dy - _dragStartY)
                .clamp(0.0, MediaQuery.of(context).size.height - 60);
          });
        },
        onTap: () => setState(() => _minimized = false),
        child: Container(
          width: 56,
          height: 56,
          decoration: BoxDecoration(
            color: Colors.blue,
            shape: BoxShape.circle,
            boxShadow: [
              BoxShadow(color: Colors.black26, blurRadius: 8, offset: Offset(0, 2)),
            ],
          ),
          child: Icon(Icons.navigation, color: Colors.white, size: 28),
        ),
      ),
    );
  }

  /// 展开：带标题栏的悬浮面板，内含高德导航 PlatformView。
  Widget _buildExpanded() {
    return Positioned(
      left: _left,
      top: _top,
      width: _panelWidth,
      height: _panelHeight,
      child: GestureDetector(
        onPanStart: (d) {
          _dragStartX = d.globalPosition.dx;
          _dragStartY = d.globalPosition.dy;
          _origLeft = _left;
          _origTop = _top;
        },
        onPanUpdate: (d) {
          final screen = MediaQuery.of(context).size;
          setState(() {
            _left = (_origLeft + d.globalPosition.dx - _dragStartX)
                .clamp(0.0, screen.width - _panelWidth);
            _top = (_origTop + d.globalPosition.dy - _dragStartY)
                .clamp(0.0, screen.height - _panelHeight);
          });
        },
        child: Container(
          decoration: BoxDecoration(
            color: Colors.white,
            borderRadius: BorderRadius.circular(12),
            boxShadow: [
              BoxShadow(color: Colors.black38, blurRadius: 12, offset: Offset(0, 4)),
            ],
          ),
          clipBehavior: Clip.antiAlias,
          child: Column(
            children: [
              // 标题栏：可拖拽区域 + 最小化/关闭按钮
              Container(
                height: 36,
                color: Colors.blue,
                child: Row(
                  children: [
                    Expanded(
                      child: Padding(
                        padding: const EdgeInsets.only(left: 12),
                        child: Text(
                          widget.poiName ?? '导航中',
                          style: TextStyle(
                            color: Colors.white,
                            fontSize: 13,
                            fontWeight: FontWeight.w500,
                          ),
                          overflow: TextOverflow.ellipsis,
                        ),
                      ),
                    ),
                    IconButton(
                      tooltip: '最小化',
                      icon: Icon(Icons.minimize, size: 18, color: Colors.white),
                      padding: EdgeInsets.zero,
                      constraints: BoxConstraints(minWidth: 36, minHeight: 36),
                      onPressed: () => setState(() => _minimized = true),
                    ),
                    IconButton(
                      tooltip: '关闭导航',
                      icon: Icon(Icons.close, size: 18, color: Colors.white),
                      padding: EdgeInsets.zero,
                      constraints: BoxConstraints(minWidth: 36, minHeight: 36),
                      onPressed: widget.onClose,
                    ),
                  ],
                ),
              ),
              // 导航视图：Hybrid Composition 嵌入 AMapNaviView
              Expanded(
                child: PlatformViewLink(
                  viewType: NaviFloatingPanel.viewType,
                  surfaceFactory: (context, controller) {
                    return AndroidViewSurface(
                      controller: controller as AndroidViewController,
                      gestureRecognizers: const <Factory<OneSequenceGestureRecognizer>>{},
                      hitTestBehavior: PlatformViewHitTestBehavior.opaque,
                    );
                  },
                  onCreatePlatformView: (params) {
                    return PlatformViewsService.initExpensiveAndroidView(
                      id: params.id,
                      viewType: NaviFloatingPanel.viewType,
                      layoutDirection: TextDirection.ltr,
                      creationParams: <String, dynamic>{
                        'lat': widget.lat,
                        'lon': widget.lon,
                        'poiName': widget.poiName,
                        'poiId': widget.poiId,
                      },
                      creationParamsCodec: const StandardMessageCodec(),
                    )
                      ..addOnPlatformViewCreatedListener((_) {
                        params.onPlatformViewCreated(params.id);
                      })
                      ..create();
                  },
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}
