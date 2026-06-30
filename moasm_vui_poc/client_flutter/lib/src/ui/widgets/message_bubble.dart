import 'package:flutter/material.dart';

import '../../data/models.dart';

/// 一条聊天气泡：用户靠右(蓝)、助手靠左(浅灰)、系统居中(提示)。
class MessageBubble extends StatelessWidget {
  final ChatTurn turn;
  const MessageBubble({super.key, required this.turn});

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);

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
          ],
        ),
      ),
    );
  }
}
