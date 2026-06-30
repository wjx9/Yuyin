/// 文字转语音(TTS) 封装：把助手回复读出来。
///
/// 类比 Android 的 android.speech.tts.TextToSpeech，这里包成 init/speak/stop。
library;

import 'package:flutter_tts/flutter_tts.dart';

class TtsService {
  final FlutterTts _tts = FlutterTts();
  bool _ready = false;

  Future<void> init() async {
    if (_ready) return;
    try {
      await _tts.setLanguage('zh-CN');
      await _tts.setSpeechRate(0.5); // flutter_tts 的 0.5 约等于正常语速
      await _tts.setVolume(1.0);
      await _tts.setPitch(1.0);
      // 让 speak() 等到播报结束再返回，便于上层把状态从"播报中"复位
      await _tts.awaitSpeakCompletion(true);
      _ready = true;
    } catch (_) {
      _ready = false; // TTS 不可用不致命，文字仍在屏幕上
    }
  }

  Future<void> speak(String text) async {
    final t = text.trim();
    if (t.isEmpty) return;
    await init();
    await _tts.stop(); // 打断上一条，避免叠音
    await _tts.speak(t);
  }

  Future<void> stop() => _tts.stop();
}
