import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../state/chat_controller.dart';
import '../workbuddy_debug/workbuddy_debug_page.dart';
import 'navi_floating_panel.dart';
import 'settings_page.dart';
import 'skill_store_page.dart';
import 'widgets/message_bubble.dart';
import 'widgets/mic_button.dart';

/// 主界面：消息列表 + 实时听写草稿 + 文字输入 + 麦克风按钮。
class ChatPage extends StatefulWidget {
  const ChatPage({super.key});

  @override
  State<ChatPage> createState() => _ChatPageState();
}

class _ChatPageState extends State<ChatPage> {
  final _scroll = ScrollController();
  final _input = TextEditingController();
  int _lastCount = 0;
  NaviFailure? _lastNaviFailure;

  @override
  void dispose() {
    _scroll.dispose();
    _input.dispose();
    super.dispose();
  }

  /// 检查是否有导航失败，有则弹出回退对话框。
  void _checkNaviFailure(ChatController c) {
    final failure = c.naviFailure;
    if (failure != null && failure != _lastNaviFailure) {
      _lastNaviFailure = failure;
      WidgetsBinding.instance.addPostFrameCallback((_) {
        if (!mounted) return;
        showDialog(
          context: context,
          barrierDismissible: false,
          builder: (dialogContext) => AlertDialog(
            title: const Text('导航启动失败'),
            content: Text('内置导航启动失败：${failure.reason}\n\n是否改用高德地图 App 导航？'),
            actions: [
              TextButton(
                onPressed: () {
                  Navigator.of(dialogContext).pop();
                  c.cancelFallback();
                },
                child: const Text('取消'),
              ),
              FilledButton(
                onPressed: () {
                  Navigator.of(dialogContext).pop();
                  c.fallbackToIntent();
                },
                child: const Text('用高德地图打开'),
              ),
            ],
          ),
        );
      });
    }
  }

  void _autoScroll() {
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (_scroll.hasClients) {
        _scroll.animateTo(
          _scroll.position.maxScrollExtent,
          duration: const Duration(milliseconds: 250),
          curve: Curves.easeOut,
        );
      }
    });
  }

  void _submitText(ChatController c) {
    final text = _input.text.trim();
    if (text.isEmpty) return;
    _input.clear();
    c.sendText(text);
  }

  @override
  Widget build(BuildContext context) {
    final c = context.watch<ChatController>();
    if (c.messages.length != _lastCount) {
      _lastCount = c.messages.length;
      _autoScroll();
    }
    // 检查是否有导航失败
    _checkNaviFailure(c);

    return Scaffold(
      appBar: AppBar(
        title: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const Text('语音助手'),
            Text(_statusLabel(c), style: Theme.of(context).textTheme.bodySmall),
          ],
        ),
        actions: [
          if (kDebugMode)
            IconButton(
              tooltip: 'WorkBuddy 调试台',
              icon: const Icon(Icons.account_tree_outlined),
              visualDensity: VisualDensity.compact,
              onPressed: () => Navigator.of(context).push(
                MaterialPageRoute(builder: (_) => const WorkBuddyDebugPage()),
              ),
            ),
          IconButton(
            tooltip: '已启用能力',
            icon: const Icon(Icons.auto_awesome),
            visualDensity: VisualDensity.compact,
            onPressed: () => _showCapabilities(context, c),
          ),
          IconButton(
            tooltip: '技能商店',
            icon: const Icon(Icons.storefront_outlined),
            visualDensity: VisualDensity.compact,
            onPressed: () => Navigator.of(context).push(
              MaterialPageRoute(
                builder: (_) => SkillStorePage(
                  // 选购成功后尽力同步能力清单（TTL ≤30s 内仍是旧清单，页面 hint 覆盖预期）
                  onSkillsSaved: () => context.read<ChatController>().refreshHealth(),
                ),
              ),
            ),
          ),
          IconButton(
            tooltip: '清空对话',
            icon: const Icon(Icons.delete_outline),
            visualDensity: VisualDensity.compact,
            onPressed: c.messages.isEmpty ? null : c.clear,
          ),
          IconButton(
            tooltip: '打开日历',
            icon: const Icon(Icons.calendar_month_outlined),
            visualDensity: VisualDensity.compact,
            onPressed: c.openCalendar,
          ),
          IconButton(
            tooltip: '设置',
            icon: const Icon(Icons.settings),
            visualDensity: VisualDensity.compact,
            onPressed: () => Navigator.of(context).push(
              MaterialPageRoute(builder: (_) => const SettingsPage()),
            ),
          ),
        ],
      ),
      body: Stack(
        children: [
          // 底层：聊天页面（完全可交互）
          Column(
            children: [
              if (c.connectionError != null) _errorBanner(context, c),
              Expanded(
                child: c.messages.isEmpty
                    ? _emptyHint(context)
                    : ListView.builder(
                        controller: _scroll,
                        padding: const EdgeInsets.symmetric(vertical: 12),
                        itemCount: c.messages.length,
                        itemBuilder: (_, i) => MessageBubble(
                          turn: c.messages[i],
                          onOpenMusic: c.openMusic,
                        ),
                      ),
              ),
              if (c.status == AssistantStatus.listening) _partialBar(context, c),
              _inputBar(context, c),
            ],
          ),
          // 悬浮导航面板（叠加在聊天界面之上，可拖拽/最小化/关闭）
          if (c.pendingNavigation != null)
            NaviFloatingPanel(
              lat: c.pendingNavigation!.lat,
              lon: c.pendingNavigation!.lon,
              poiName: c.pendingNavigation!.poiName,
              poiId: c.pendingNavigation!.poiId,
              onClose: c.clearPendingNavigation,
            ),
        ],
      ),
    );
  }

  String _statusLabel(ChatController c) {
    switch (c.status) {
      case AssistantStatus.listening:
        return '正在聆听…';
      case AssistantStatus.thinking:
        return '思考中…';
      case AssistantStatus.speaking:
        return '播报中…';
      case AssistantStatus.idle:
        return c.connectionError == null ? '点击麦克风开始说话' : '未连接服务端';
    }
  }

  Widget _errorBanner(BuildContext context, ChatController c) {
    final theme = Theme.of(context);
    return Material(
      color: theme.colorScheme.errorContainer,
      child: Padding(
        padding: const EdgeInsets.fromLTRB(16, 10, 8, 10),
        child: Row(
          children: [
            Icon(Icons.cloud_off, size: 18, color: theme.colorScheme.onErrorContainer),
            const SizedBox(width: 8),
            Expanded(
              child: Text(c.connectionError!,
                  style: TextStyle(color: theme.colorScheme.onErrorContainer, fontSize: 13)),
            ),
            TextButton(
              onPressed: c.refreshHealth,
              child: const Text('重试'),
            ),
            TextButton(
              onPressed: () => Navigator.of(context).push(
                MaterialPageRoute(builder: (_) => const SettingsPage()),
              ),
              child: const Text('去设置'),
            ),
          ],
        ),
      ),
    );
  }

  Widget _emptyHint(BuildContext context) {
    final theme = Theme.of(context);
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(32),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(Icons.assistant, size: 64, color: theme.hintColor),
            const SizedBox(height: 16),
            Text('点击下方麦克风，或直接打字提问',
                style: theme.textTheme.titleMedium?.copyWith(color: theme.hintColor)),
            const SizedBox(height: 8),
            Text('例如：“深圳到北京怎么最舒服？”“附近好吃的”“看下深圳天气”',
                textAlign: TextAlign.center,
                style: theme.textTheme.bodySmall?.copyWith(color: theme.hintColor)),
          ],
        ),
      ),
    );
  }

  Widget _partialBar(BuildContext context, ChatController c) {
    final theme = Theme.of(context);
    return Container(
      width: double.infinity,
      color: theme.colorScheme.surfaceContainerHighest,
      padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
      child: Text(
        c.partialText.isEmpty ? '（请说话…）' : c.partialText,
        style: theme.textTheme.bodyMedium?.copyWith(
          color: c.partialText.isEmpty ? theme.hintColor : theme.colorScheme.onSurface,
          fontStyle: FontStyle.italic,
        ),
      ),
    );
  }

  Widget _inputBar(BuildContext context, ChatController c) {
    return SafeArea(
      top: false,
      child: Padding(
        padding: const EdgeInsets.fromLTRB(12, 8, 12, 8),
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.end,
          children: [
            Expanded(
              child: TextField(
                controller: _input,
                minLines: 1,
                maxLines: 4,
                textInputAction: TextInputAction.send,
                onSubmitted: (_) => _submitText(c),
                decoration: InputDecoration(
                  hintText: '输入文字，或按右侧麦克风说话',
                  filled: true,
                  contentPadding: const EdgeInsets.symmetric(horizontal: 16, vertical: 10),
                  border: OutlineInputBorder(
                    borderRadius: BorderRadius.circular(24),
                    borderSide: BorderSide.none,
                  ),
                  suffixIcon: IconButton(
                    icon: const Icon(Icons.send),
                    onPressed: c.isBusy ? null : () => _submitText(c),
                  ),
                ),
              ),
            ),
            const SizedBox(width: 10),
            MicButton(status: c.status, onTap: c.toggleListening),
          ],
        ),
      ),
    );
  }

  void _showCapabilities(BuildContext context, ChatController c) {
    showModalBottomSheet(
      context: context,
      builder: (_) => SafeArea(
        child: Padding(
          padding: const EdgeInsets.all(20),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text('服务端已启用能力', style: Theme.of(context).textTheme.titleMedium),
              const SizedBox(height: 12),
              if (c.capabilities.isEmpty)
                Text(c.connectionError ?? '（未获取到，请检查服务端连接）')
              else
                Wrap(
                  spacing: 8,
                  runSpacing: 8,
                  children: c.capabilities.map((e) => Chip(label: Text(e))).toList(),
                ),
            ],
          ),
        ),
      ),
    );
  }
}
