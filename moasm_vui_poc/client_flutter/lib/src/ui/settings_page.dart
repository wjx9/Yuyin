import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../state/settings_controller.dart';

/// 设置页：填服务端地址 / 鉴权 token / 位置；可新建会话清空上下文。
class SettingsPage extends StatefulWidget {
  const SettingsPage({super.key});

  @override
  State<SettingsPage> createState() => _SettingsPageState();
}

class _SettingsPageState extends State<SettingsPage> {
  late final TextEditingController _server;
  late final TextEditingController _token;
  late final TextEditingController _location;

  @override
  void initState() {
    super.initState();
    final cfg = context.read<SettingsController>().config;
    _server = TextEditingController(text: cfg.serverUrl);
    _token = TextEditingController(text: cfg.authToken ?? '');
    _location = TextEditingController(text: cfg.location ?? '');
  }

  @override
  void dispose() {
    _server.dispose();
    _token.dispose();
    _location.dispose();
    super.dispose();
  }

  Future<void> _save() async {
    await context.read<SettingsController>().update(
          serverUrl: _server.text.trim(),
          authToken: _token.text.trim(),
          location: _location.text.trim(),
        );
    if (mounted) {
      ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('已保存')));
      Navigator.of(context).pop();
    }
  }

  @override
  Widget build(BuildContext context) {
    final settings = context.watch<SettingsController>();
    return Scaffold(
      appBar: AppBar(title: const Text('设置')),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          TextField(
            controller: _server,
            keyboardType: TextInputType.url,
            autocorrect: false,
            decoration: const InputDecoration(
              labelText: '服务端地址',
              hintText: 'http://192.168.x.x:8000',
              helperText: '电脑上跑 serve.py 后打印的"局域网"地址；模拟器可用 10.0.2.2:8000',
              border: OutlineInputBorder(),
            ),
          ),
          const SizedBox(height: 16),
          TextField(
            controller: _token,
            autocorrect: false,
            decoration: const InputDecoration(
              labelText: 'Bearer 鉴权密钥（可选）',
              hintText: '服务端 --token 开启时填，否则留空',
              border: OutlineInputBorder(),
            ),
          ),
          const SizedBox(height: 16),
          TextField(
            controller: _location,
            autocorrect: false,
            decoration: const InputDecoration(
              labelText: '位置坐标（可选）',
              hintText: '经度,纬度，如 113.92,22.53',
              helperText: '供高德等基于位置的能力使用',
              border: OutlineInputBorder(),
            ),
          ),
          const SizedBox(height: 24),
          FilledButton.icon(
            onPressed: _save,
            icon: const Icon(Icons.save),
            label: const Text('保存'),
          ),
          const Divider(height: 40),
          ListTile(
            contentPadding: EdgeInsets.zero,
            title: const Text('当前会话'),
            subtitle: Text(settings.config.sessionId,
                style: Theme.of(context).textTheme.bodySmall, overflow: TextOverflow.ellipsis),
            trailing: TextButton.icon(
              onPressed: () async {
                await context.read<SettingsController>().newSession();
                if (context.mounted) {
                  ScaffoldMessenger.of(context)
                      .showSnackBar(const SnackBar(content: Text('已新建会话（服务端上下文已重置）')));
                }
              },
              icon: const Icon(Icons.refresh),
              label: const Text('新建'),
            ),
          ),
        ],
      ),
    );
  }
}
