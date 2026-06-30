import 'package:flutter/material.dart';

import '../../state/chat_controller.dart';

/// 主交互按钮：点一下开始听写，听写中变红并脉冲；思考中禁用并转圈。
class MicButton extends StatefulWidget {
  final AssistantStatus status;
  final VoidCallback onTap;
  const MicButton({super.key, required this.status, required this.onTap});

  @override
  State<MicButton> createState() => _MicButtonState();
}

class _MicButtonState extends State<MicButton> with SingleTickerProviderStateMixin {
  late final AnimationController _pulse =
      AnimationController(vsync: this, duration: const Duration(milliseconds: 900))..repeat(reverse: true);

  @override
  void dispose() {
    _pulse.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final listening = widget.status == AssistantStatus.listening;
    final thinking = widget.status == AssistantStatus.thinking;

    final color = listening ? theme.colorScheme.error : theme.colorScheme.primary;

    return GestureDetector(
      onTap: thinking ? null : widget.onTap,
      child: AnimatedBuilder(
        animation: _pulse,
        builder: (context, child) {
          final scale = listening ? 1.0 + _pulse.value * 0.12 : 1.0;
          return Transform.scale(scale: scale, child: child);
        },
        child: Container(
          width: 72,
          height: 72,
          decoration: BoxDecoration(
            shape: BoxShape.circle,
            color: thinking ? theme.disabledColor : color,
            boxShadow: [
              BoxShadow(
                color: color.withValues(alpha: listening ? 0.45 : 0.25),
                blurRadius: listening ? 20 : 10,
                spreadRadius: listening ? 4 : 1,
              ),
            ],
          ),
          child: thinking
              ? const Padding(
                  padding: EdgeInsets.all(22),
                  child: CircularProgressIndicator(strokeWidth: 3, color: Colors.white),
                )
              : Icon(listening ? Icons.stop_rounded : Icons.mic_rounded,
                  color: Colors.white, size: 34),
        ),
      ),
    );
  }
}
