import 'package:flutter/material.dart';

import '../../a2ui/a2ui_card_view.dart';
import '../../data/models.dart';

/// 一条聊天气泡：用户靠右(蓝)、助手靠左(浅灰)、系统居中(提示)。
/// 带 A2UI 卡片的助手消息不走气泡容器，直接渲染穿戴风格卡片（黑底即"透明"）。
class MessageBubble extends StatelessWidget {
  final ChatTurn turn;

  /// 音乐气泡「用网易云音乐打开」按钮的回调（step 3.1）。
  final void Function(MusicInfo music)? onOpenMusic;

  const MessageBubble({super.key, required this.turn, this.onOpenMusic});

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);

    // A2UI 卡片消息：不套气泡（卡片自带黑底+绿描边），嵌入位置与助手气泡一致。
    // 渲染细节全部在 a2ui 模块内，这里只负责"摆在消息流哪里"——后续做独立显示区
    // 时，卡片组件可原样挪走。
    if (turn.sender == Sender.assistant && !turn.pending && turn.a2ui != null) {
      return Align(
        alignment: Alignment.centerLeft,
        child: Container(
          margin: const EdgeInsets.symmetric(vertical: 4, horizontal: 12),
          constraints: BoxConstraints(maxWidth: MediaQuery.of(context).size.width * 0.9),
          child: A2uiCardView(messages: turn.a2ui!),
        ),
      );
    }

    if (turn.sender == Sender.system) {
      return Padding(
        padding: const EdgeInsets.symmetric(vertical: 6, horizontal: 24),
        child: Center(
          child: Text(
            turn.text,
            textAlign: TextAlign.center,
            style: theme.textTheme.bodySmall?.copyWith(
              color: turn.isError ? theme.colorScheme.error : theme.hintColor,
            ),
          ),
        ),
      );
    }

    final isUser = turn.sender == Sender.user;
    final bg = turn.isError
        ? theme.colorScheme.errorContainer
        : isUser
            ? theme.colorScheme.primary
            : theme.colorScheme.surfaceContainerHighest;
    final fg = turn.isError
        ? theme.colorScheme.onErrorContainer
        : isUser
            ? theme.colorScheme.onPrimary
            : theme.colorScheme.onSurface;

    return Align(
      alignment: isUser ? Alignment.centerRight : Alignment.centerLeft,
      child: Container(
        margin: const EdgeInsets.symmetric(vertical: 4, horizontal: 12),
        padding: const EdgeInsets.symmetric(vertical: 10, horizontal: 14),
        constraints: BoxConstraints(maxWidth: MediaQuery.of(context).size.width * 0.78),
        decoration: BoxDecoration(
          color: bg,
          borderRadius: BorderRadius.only(
            topLeft: const Radius.circular(16),
            topRight: const Radius.circular(16),
            bottomLeft: Radius.circular(isUser ? 16 : 4),
            bottomRight: Radius.circular(isUser ? 4 : 16),
          ),
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            if (!isUser && turn.intent != null && turn.intent!.isNotEmpty)
              Padding(
                padding: const EdgeInsets.only(bottom: 4),
                child: Text(
                  turn.intent!,
                  style: theme.textTheme.labelSmall?.copyWith(
                    color: fg.withValues(alpha: 0.6),
                    fontWeight: FontWeight.w600,
                  ),
                ),
              ),
            if (turn.pending)
              Row(
                mainAxisSize: MainAxisSize.min,
                children: [
                  SizedBox(
                    width: 14,
                    height: 14,
                    child: CircularProgressIndicator(strokeWidth: 2, color: fg),
                  ),
                  const SizedBox(width: 10),
                  Text(turn.text, style: TextStyle(color: fg)),
                ],
              )
            else
              SelectableText(turn.text, style: TextStyle(color: fg, height: 1.35)),
            if (turn.music != null && onOpenMusic != null)
              Padding(
                padding: const EdgeInsets.only(top: 8),
                child: FilledButton.tonalIcon(
                  onPressed: () => onOpenMusic!(turn.music!),
                  icon: const Icon(Icons.music_note, size: 18),
                  label: const Text('用网易云音乐打开'),
                  style: FilledButton.styleFrom(
                    visualDensity: VisualDensity.compact,
                    padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 4),
                  ),
                ),
              ),
          ],
        ),
      ),
    );
  }
}
