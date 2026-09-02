/// moasm_vui · 语音助手 client-server 客户端（Android / iOS）。
///
/// 与 client_py 同一条链路、同一套 HTTP 契约，只是把终端换成手机、把打字换成语音：
///   麦克风(ASR) → POST /chat 给 serve.py → 收到 {text,intent} → 上屏 + TTS 朗读
///
/// 依赖注入用 provider（≈ Android 的 ViewModelProvider）：先 load 配置、初始化服务，
/// 再把两个 ChangeNotifier（Settings / Chat）注入 widget 树。
library;

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:provider/provider.dart';

import 'src/services/speech_service.dart';
import 'src/services/tts_service.dart';
import 'src/services/location_service.dart';
import 'src/state/chat_controller.dart';
import 'src/state/settings_controller.dart';
import 'src/ui/chat_page.dart';

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();

  final settings = SettingsController();
  await settings.load();

  final speech = SpeechService();
  final tts = TtsService();
  final location = LocationService();
  final chat = ChatController(
    settings: settings,
    speech: speech,
    tts: tts,
    location: location,
  );

  // 启动即探活：把服务端已启用能力取回来（连不上则在界面顶部提示去设置）
  chat.refreshHealth();

  // 原生导航页（AmapNaviViewActivity）与语音助手交互：
  // - startListening / stopListening：按下说话、松手结束
  // - sendNaviText：导航页文本输入，直接发送给助手
  const assistantChannel = MethodChannel('com.rayneo.moasm_vui/assistant');
  assistantChannel.setMethodCallHandler((call) async {
    switch (call.method) {
      case 'startListening':
        await chat.startListening();
        break;
      case 'stopListening':
        await chat.stopListening();
        break;
      case 'sendNaviText':
        final text = call.arguments as String? ?? '';
        if (text.isNotEmpty) await chat.sendText(text);
        break;
    }
  });

  runApp(MoasmVuiApp(settings: settings, chat: chat));
}

class MoasmVuiApp extends StatelessWidget {
  final SettingsController settings;
  final ChatController chat;

  const MoasmVuiApp({super.key, required this.settings, required this.chat});

  @override
  Widget build(BuildContext context) {
    return MultiProvider(
      providers: [
        ChangeNotifierProvider.value(value: settings),
        ChangeNotifierProvider.value(value: chat),
      ],
      child: MaterialApp(
        title: '语音助手',
        debugShowCheckedModeBanner: false,
        theme: ThemeData(
          colorScheme: ColorScheme.fromSeed(seedColor: const Color(0xFF2563EB)),
          useMaterial3: true,
        ),
        darkTheme: ThemeData(
          colorScheme: ColorScheme.fromSeed(
            seedColor: const Color(0xFF2563EB),
            brightness: Brightness.dark,
          ),
          useMaterial3: true,
        ),
        home: const ChatPage(),
      ),
    );
  }
}
