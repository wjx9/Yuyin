/// 端侧语音识别(ASR) 封装：把 speech_to_text 插件的细节挡在外面。
///
/// 类比 Android：相当于把 SpeechRecognizer + RecognitionListener 包成一个简单的
/// start/stop 接口，上层 Controller 只关心"开始听 / 识别到文字 / 听完了"。
library;

import 'package:speech_to_text/speech_to_text.dart';

class SpeechService {
  final SpeechToText _stt = SpeechToText();
  bool _initialized = false;
  String? _zhLocaleId; // 选中的中文识别 locale（设备支持时）

  bool get isListening => _stt.isListening;
  bool get isAvailable => _stt.isAvailable;

  /// 首次使用前初始化（会触发麦克风/语音识别权限申请）。返回是否可用。
  /// onStatus 透传底层状态（listening / notListening / done），供 UI 复位按钮。
  Future<bool> init({
    void Function(String status)? onStatus,
    void Function(String error)? onError,
  }) async {
    if (_initialized) return _stt.isAvailable;
    _initialized = await _stt.initialize(
      onStatus: (s) => onStatus?.call(s),
      onError: (e) => onError?.call(e.errorMsg),
    );
    if (_initialized) {
      await _pickChineseLocale();
    }
    return _initialized;
  }

  Future<void> _pickChineseLocale() async {
    try {
      final locales = await _stt.locales();
      final zh = locales.where((l) => l.localeId.toLowerCase().startsWith('zh'));
      if (zh.isNotEmpty) {
        // 优先简体（zh_CN / zh-Hans），否则取第一个中文
        final cn = zh.firstWhere(
          (l) => l.localeId.toLowerCase().contains('cn') || l.localeId.toLowerCase().contains('hans'),
          orElse: () => zh.first,
        );
        _zhLocaleId = cn.localeId;
      }
    } catch (_) {
      _zhLocaleId = null; // 拿不到就用系统默认 locale
    }
  }

  /// 开始一次听写。partial=true 时 onResult 会在识别过程中多次回调（实时草稿）。
  Future<void> listen({
    required void Function(String text, bool isFinal) onResult,
  }) async {
    await _stt.listen(
      onResult: (r) => onResult(r.recognizedWords, r.finalResult),
      listenOptions: SpeechListenOptions(
        partialResults: true,
        cancelOnError: true,
        listenMode: ListenMode.dictation,
        localeId: _zhLocaleId,
        listenFor: const Duration(seconds: 30),
        pauseFor: const Duration(seconds: 3), // 停顿 3 秒判定一句结束
      ),
    );
  }

  Future<void> stop() => _stt.stop();
  Future<void> cancel() => _stt.cancel();
}
