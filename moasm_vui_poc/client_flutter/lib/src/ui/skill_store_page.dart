/// 技能商店选购页（原生 Flutter，通过主服务 :8000/skill-store 访问）。
///
/// 用户只通过卡片「启用」开关控制能力：ON=启用（未选购时开启即自动选购），
/// OFF=停用（保留用户偏好和凭证）。手机端不展示「退订」按钮，避免删除偏好后
/// 内置技能按默认值再次恢复启用。每次操作 → 商店 version+1 → server 端 ≤30s 重建路由。
/// 保存成功回调 [onSkillsSaved]，由入口页挂上 ChatController.refreshHealth() 尽力同步
/// 能力清单（TTL ≤30s 内仍是旧清单，页面 hint 已覆盖预期）。
///
/// 竞态：_saving 期间禁用全部交互（防连点乱序）；失败回滚到最近成功快照 + SnackBar。
library;

import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../data/chat_api.dart' show ApiException;
import '../data/skill_store_api.dart';
import '../state/settings_controller.dart';
import 'settings_page.dart';

typedef SkillStoreApiFactory = SkillStoreApi Function(String baseUrl);
typedef SkillsSavedCallback = void Function();

SkillStoreApi _defaultApiFactory(String baseUrl) =>
    SkillStoreApi(baseUrl: baseUrl);

class SkillStorePage extends StatefulWidget {
  const SkillStorePage({super.key, this.apiFactory, this.onSkillsSaved});

  /// 注入点：测试用 MockClient 换真实实现。
  final SkillStoreApiFactory? apiFactory;

  /// 保存成功后的回调（入口页挂 refreshHealth）。
  final SkillsSavedCallback? onSkillsSaved;

  @override
  State<SkillStorePage> createState() => _SkillStorePageState();
}

class _SkillStorePageState extends State<SkillStorePage> {
  SkillStoreApi? _api;
  List<Skill> _catalog = [];
  Set<String> _purchased = {}; // 已选购
  Map<String, bool> _enabled = {}; // {skill_id: 是否启用}
  Set<String> _lastPurchased = {}; // 最近成功快照（失败回滚用）
  Map<String, bool> _lastEnabled = {};
  Map<String, bool> _credConfigured = {}; // P4.2：byok 技能凭证是否已配置
  Map<String, Map<String, dynamic>> _credValues = {}; // 脱敏 values（表单预填）
  List<MyPurchasedSkill> _purchasedDetail = []; // 已选购详情（含已下架，渲染「已下架」卡）
  bool _loading = true;
  bool _saving = false;
  String? _error;

  @override
  void initState() {
    super.initState();
    final url = context.read<SettingsController>().config.effectiveStoreUrl;
    if (url == null) {
      // 服务端地址 + 商店地址都取不出 → 去设置里填（务必退出 loading 态，否则永远转圈）
      _error = '未配置商店地址：请先在设置里填写服务端地址（或商店地址）';
      _loading = false;
      return;
    }
    _api = (widget.apiFactory ?? _defaultApiFactory)(url);
    _load();
  }

  @override
  void dispose() {
    _api?.dispose();
    super.dispose();
  }

  Future<void> _load() async {
    final api = _api;
    if (api == null) return;
    setState(() {
      _loading = true;
      _error = null;
    });
    final userId = context.read<SettingsController>().config.userId;
    try {
      // 目录 + 选购状态 + 已选购详情（含已下架）并行拉取。用 Future.wait（监听所有
      // future）避免一路失败时另一路的错误无人 await 而变 unhandled。
      final results = await Future.wait<Object?>([
        api.listSkills(),
        api.getMySkills(userId),
        api.getMySkillsDetail(userId),
      ]);
      final skills = results[0] as List<Skill>;
      final my = results[1] as MySkills;
      final detail = results[2] as List<MyPurchasedSkill>;
      // P4.2：byok 技能逐个拉脱敏凭证状态（POC 技能少，串行可接受）；失败按未配置处理
      final cred = <String, bool>{};
      final vals = <String, Map<String, dynamic>>{};
      for (final s in skills.where((s) => s.credentials?['type'] == 'byok')) {
        try {
          final g = await api.getCredentials(userId, s.skillId);
          cred[s.skillId] = (g['configured'] as bool?) ?? false;
          final v = g['values'];
          if (v is Map<String, dynamic>) vals[s.skillId] = v;
        } on ApiException {
          cred[s.skillId] = false;
        }
      }
      if (!mounted) return;
      setState(() {
        _catalog = skills;
        _purchased = my.purchased;
        _enabled = my.enabled;
        _lastPurchased = Set.of(my.purchased);
        _lastEnabled = Map.of(my.enabled);
        _credConfigured = cred;
        _credValues = vals;
        _purchasedDetail = detail;
        _loading = false;
      });
    } on ApiException catch (e) {
      if (!mounted) return;
      setState(() {
        _error = e.message;
        _loading = false;
      });
    } catch (e) {
      // 兜底：解析等非 ApiException 错误也必须落错误态，不能停在转圈
      if (!mounted) return;
      setState(() {
        _error = '加载技能失败：$e';
        _loading = false;
      });
    }
  }

  Future<void> _onToggleEnable(Skill skill, bool value) async {
    if (_saving) return; // 保存期间禁止再点，避免乱序
    final userId = context.read<SettingsController>().config.userId;
    setState(() {
      _enabled = Map.of(_enabled)..[skill.skillId] = value; // 乐观更新
      _saving = true;
    });
    try {
      final version = await _api!.setEnabled(userId, skill.skillId, value);
      if (!mounted) return;
      setState(() {
        if (value && !_lastPurchased.contains(skill.skillId)) {
          _purchased = Set.of(_purchased)..add(skill.skillId); // 开启即自动选购
        }
        _lastPurchased = Set.of(_purchased);
        _lastEnabled = Map.of(_enabled);
        _saving = false;
      });
      widget.onSkillsSaved?.call();
      // 启用 unconfigured byok 技能 → 立即自动弹凭证表单（填 API KEY 即用；保存/清空逻辑在弹窗内已就绪）
      final needsCred =
          value &&
          skill.credentials?['type'] == 'byok' &&
          !(_credConfigured[skill.skillId] ?? false);
      if (needsCred) {
        _openCredentialDialog(skill);
      }
    } on ApiException catch (e) {
      if (!mounted) return;
      setState(() {
        _purchased = Set.of(_lastPurchased);
        _enabled = Map.of(_lastEnabled);
        _saving = false;
      });
      _snack('保存失败：${e.message}');
    }
  }

  /// 停用「已下架但已选购」的技能：保留选购（仅置 enabled=false），失败回滚。
  /// 已下架技能不能被启用（后端 409），但停用允许，故下架卡只给关闭开关。
  Future<void> _onDisableOffShelf(String skillId) async {
    if (_saving) return;
    final userId = context.read<SettingsController>().config.userId;
    setState(() {
      _enabled = Map.of(_enabled)..[skillId] = false; // 乐观更新
      _saving = true;
    });
    try {
      await _api!.setEnabled(userId, skillId, false);
      if (!mounted) return;
      setState(() {
        _lastEnabled = Map.of(_enabled);
        _saving = false;
      });
    } on ApiException catch (e) {
      if (!mounted) return;
      setState(() {
        _enabled = Map.of(_lastEnabled);
        _saving = false;
      });
      _snack('停用失败：${e.message}');
    }
  }

  void _snack(String msg) {
    ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(msg)));
  }

  /// P4.2：打开 byok 技能凭证表单；保存/清空成功 → 回调 + 刷新状态 + 提示 ≤30s 生效。
  Future<void> _openCredentialDialog(Skill skill) async {
    if (_saving) return;
    final api = _api!;
    final userId = context.read<SettingsController>().config.userId;
    final saved = await showDialog<bool>(
      context: context,
      builder: (_) => _CredentialDialog(
        skill: skill,
        api: api,
        userId: userId,
        maskedValues: _credValues[skill.skillId] ?? const {},
        configured: _credConfigured[skill.skillId] ?? false,
      ),
    );
    if (saved == true && mounted) {
      widget.onSkillsSaved?.call();
      _snack('凭证已保存，语音助手 ≤30s 生效');
      await _load();
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('技能商店')),
      body: _buildBody(context),
    );
  }

  Widget _buildBody(BuildContext context) {
    if (_error != null) return _errorView(context); // 错误优先，避免卡在转圈
    if (_loading) return const Center(child: CircularProgressIndicator());
    // 已下架但已选购：管理员下架期间用户仍能看到并停用/退订（状态隔离，用户行被保留）。
    // 再按 _purchased 过滤：退订（乐观移除）后卡片立即消失；失败回滚后 _purchased 恢复、卡片回来。
    final offShelf = _purchasedDetail
        .where((d) => d.isOffShelf && _purchased.contains(d.skillId))
        .toList();
    if (_catalog.isEmpty && offShelf.isEmpty) {
      return const Center(child: Text('商店里还没有可用技能，去电脑端发布后再来看'));
    }
    return Column(
      children: [
        _hint(context),
        Expanded(
          child: ListView(
            padding: const EdgeInsets.fromLTRB(16, 4, 16, 24),
            children: [
              for (final s in _catalog) _skillCard(context, s),
              if (offShelf.isNotEmpty) ...[
                Padding(
                  padding: const EdgeInsets.only(top: 8, bottom: 4),
                  child: Text(
                    '已下架（已选购 · 管理员下架中，仍可停用/退订）',
                    style: Theme.of(context).textTheme.labelMedium?.copyWith(
                      color: Theme.of(context).colorScheme.onSurfaceVariant,
                    ),
                  ),
                ),
                for (final d in offShelf) _offShelfCard(context, d),
              ],
            ],
          ),
        ),
      ],
    );
  }

  Widget _hint(BuildContext context) {
    final theme = Theme.of(context);
    return Container(
      width: double.infinity,
      color: theme.colorScheme.surfaceContainerHighest,
      padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
      child: Row(
        children: [
          Icon(
            Icons.info_outline,
            size: 16,
            color: theme.colorScheme.onSurfaceVariant,
          ),
          const SizedBox(width: 8),
          const Expanded(
            child: Text(
              '启用/停用即保存 → 商店版本+1 → 语音助手 ≤30s 生效；停用保留选购，退订才移除',
              style: TextStyle(fontSize: 12),
            ),
          ),
          if (_saving) ...[
            const SizedBox(width: 8),
            const SizedBox(
              width: 14,
              height: 14,
              child: CircularProgressIndicator(strokeWidth: 2),
            ),
          ],
        ],
      ),
    );
  }

  Widget _errorView(BuildContext context) {
    final theme = Theme.of(context);
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(32),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(Icons.cloud_off, size: 56, color: theme.colorScheme.error),
            const SizedBox(height: 12),
            Text(_error!, textAlign: TextAlign.center),
            const SizedBox(height: 16),
            FilledButton.icon(
              onPressed: _load,
              icon: const Icon(Icons.refresh),
              label: const Text('重试'),
            ),
            TextButton(
              onPressed: () => Navigator.of(
                context,
              ).push(MaterialPageRoute(builder: (_) => const SettingsPage())),
              child: const Text('去设置'),
            ),
          ],
        ),
      ),
    );
  }

  Widget _skillCard(BuildContext context, Skill skill) {
    final theme = Theme.of(context);
    final purchased = _purchased.contains(skill.skillId);
    final enabled = _enabled[skill.skillId] ?? false;
    return Card.outlined(
      margin: const EdgeInsets.only(bottom: 12),
      child: Padding(
        padding: const EdgeInsets.fromLTRB(12, 12, 8, 4),
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            CircleAvatar(
              radius: 20,
              child: Text(skill.icon?.isNotEmpty == true ? skill.icon! : '🧩'),
            ),
            const SizedBox(width: 12),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Row(
                    children: [
                      Flexible(
                        child: Text(
                          skill.name,
                          style: theme.textTheme.titleSmall,
                        ),
                      ),
                      if (purchased) ...[
                        const SizedBox(width: 8),
                        Chip(
                          label: Text(skill.kind == 'builtin' ? '已接入' : '已选购'),
                          visualDensity: VisualDensity.compact,
                          materialTapTargetSize:
                              MaterialTapTargetSize.shrinkWrap,
                          backgroundColor: theme.colorScheme.secondaryContainer,
                          labelStyle: theme.textTheme.labelSmall,
                        ),
                      ],
                    ],
                  ),
                  if (skill.description.isNotEmpty) ...[
                    const SizedBox(height: 4),
                    Text(skill.description, style: theme.textTheme.bodySmall),
                  ],
                  if (skill.keywords.isNotEmpty) ...[
                    const SizedBox(height: 8),
                    Wrap(
                      spacing: 6,
                      runSpacing: 6,
                      children: [
                        for (final k in skill.keywords)
                          Chip(
                            label: Text(k),
                            visualDensity: VisualDensity.compact,
                            materialTapTargetSize:
                                MaterialTapTargetSize.shrinkWrap,
                          ),
                      ],
                    ),
                  ],
                  // P4.2：byok 技能凭证状态行，点击开动态表单
                  if (skill.credentials?['type'] == 'byok') ...[
                    const SizedBox(height: 6),
                    InkWell(
                      onTap: _saving
                          ? null
                          : () => _openCredentialDialog(skill),
                      child: Row(
                        mainAxisSize: MainAxisSize.min,
                        children: [
                          Icon(
                            (_credConfigured[skill.skillId] ?? false)
                                ? Icons.check_circle_outline
                                : Icons.warning_amber_outlined,
                            size: 16,
                            color: (_credConfigured[skill.skillId] ?? false)
                                ? Colors.green.shade700
                                : Colors.orange.shade800,
                          ),
                          const SizedBox(width: 4),
                          Text(
                            (_credConfigured[skill.skillId] ?? false)
                                ? '凭证已配置'
                                : '需配置凭证',
                            style: TextStyle(
                              fontSize: 13,
                              color: (_credConfigured[skill.skillId] ?? false)
                                  ? Colors.green.shade700
                                  : Colors.orange.shade800,
                            ),
                          ),
                        ],
                      ),
                    ),
                  ],
                  const SizedBox(height: 2),
                  Row(
                    children: [
                      // 内置能力和远程 MCP 都由用户控制启停；kind 只用于展示和凭证逻辑。
                      Text('启用', style: const TextStyle(fontSize: 14)),
                      const Spacer(),
                      Switch(
                        value: enabled,
                        onChanged: _saving
                            ? null
                            : (v) => _onToggleEnable(skill, v),
                      ),
                    ],
                  ),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }

  /// 已下架（已选购）卡：管理员下架期间技能不在目录，但用户行被保留。
  /// 只允许通过开关停用，不能重新启用；不提供退订按钮。
  Widget _offShelfCard(BuildContext context, MyPurchasedSkill d) {
    final theme = Theme.of(context);
    final enabled = _enabled[d.skillId] ?? d.enabled;
    return Card.outlined(
      margin: const EdgeInsets.only(bottom: 12),
      child: Padding(
        padding: const EdgeInsets.fromLTRB(12, 12, 8, 4),
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            CircleAvatar(
              radius: 20,
              child: Text(d.icon.isNotEmpty ? d.icon : '🧩'),
            ),
            const SizedBox(width: 12),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Row(
                    children: [
                      Flexible(
                        child: Text(d.name, style: theme.textTheme.titleSmall),
                      ),
                      const SizedBox(width: 8),
                      Chip(
                        label: const Text('已下架'),
                        visualDensity: VisualDensity.compact,
                        materialTapTargetSize: MaterialTapTargetSize.shrinkWrap,
                        backgroundColor:
                            theme.colorScheme.surfaceContainerHighest,
                        labelStyle: theme.textTheme.labelSmall?.copyWith(
                          color: theme.colorScheme.onSurfaceVariant,
                        ),
                      ),
                    ],
                  ),
                  if (d.description.isNotEmpty) ...[
                    const SizedBox(height: 4),
                    Text(d.description, style: theme.textTheme.bodySmall),
                  ],
                  const SizedBox(height: 4),
                  Row(
                    children: [
                      Expanded(
                        child: Text(
                          enabled ? '当前仍启用中，关闭后不再路由' : '已停用（管理员下架）',
                          style: theme.textTheme.bodySmall?.copyWith(
                            color: theme.colorScheme.onSurfaceVariant,
                          ),
                        ),
                      ),
                      Switch(
                        value: enabled,
                        onChanged: _saving || !enabled
                            ? null
                            : (value) {
                                if (!value) _onDisableOffShelf(d.skillId);
                              },
                      ),
                    ],
                  ),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }
}

/// P4.2 动态凭证表单：按 skill.credentials.schema 渲染 secret/string/number/select/boolean，
/// 非敏感字段用脱敏值预填；保存 → PUT，清空 → DELETE。成功后 pop(true)。
class _CredentialDialog extends StatefulWidget {
  const _CredentialDialog({
    required this.skill,
    required this.api,
    required this.userId,
    required this.maskedValues,
    required this.configured,
  });

  final Skill skill;
  final SkillStoreApi api;
  final String userId;
  final Map<String, dynamic> maskedValues;
  final bool configured;

  @override
  State<_CredentialDialog> createState() => _CredentialDialogState();
}

class _CredentialDialogState extends State<_CredentialDialog> {
  static const _secretTypes = {'secret', 'textarea', 'file'};

  final Map<String, TextEditingController> _text = {};
  final Map<String, String> _selected = {}; // select/boolean 选中值
  final Map<String, bool> _obscure = {};
  late final List<Map<String, dynamic>> _schema;
  bool _busy = false;
  String? _error;

  @override
  void initState() {
    super.initState();
    _schema =
        (widget.skill.credentials?['schema'] as List?)
            ?.whereType<Map<String, dynamic>>()
            .toList() ??
        const [];
    for (final f in _schema) {
      final key = f['key'] as String;
      final type = (f['type'] as String?) ?? 'string';
      if (type == 'select') {
        final options =
            (f['options'] as List?)?.whereType<String>().toList() ?? const [];
        final mv = widget.maskedValues[key];
        _selected[key] = (mv is String && options.contains(mv))
            ? mv
            : (options.isNotEmpty ? options.first : '');
      } else if (type == 'boolean') {
        _selected[key] = widget.maskedValues[key] == true ? 'true' : 'false';
      } else {
        _text[key] = TextEditingController();
        if (type == 'secret') _obscure[key] = true;
      }
    }
  }

  @override
  void dispose() {
    for (final c in _text.values) {
      c.dispose();
    }
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return AlertDialog(
      title: Text('配置「${widget.skill.name}」凭证'),
      content: SizedBox(
        width: double.maxFinite,
        child: SingleChildScrollView(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            mainAxisSize: MainAxisSize.min,
            children: [
              for (final f in _schema) _field(theme, f),
              if (_error != null) ...[
                const SizedBox(height: 8),
                Text(
                  _error!,
                  style: TextStyle(
                    color: theme.colorScheme.error,
                    fontSize: 13,
                  ),
                ),
              ],
            ],
          ),
        ),
      ),
      actions: [
        if (widget.configured)
          TextButton(
            onPressed: _busy ? null : _clear,
            child: const Text('清空凭证'),
          ),
        TextButton(
          onPressed: _busy ? null : () => Navigator.pop(context),
          child: const Text('取消'),
        ),
        FilledButton(onPressed: _busy ? null : _save, child: const Text('保存')),
      ],
    );
  }

  Widget _field(ThemeData theme, Map<String, dynamic> f) {
    final key = f['key'] as String;
    final label = (f['label'] as String?) ?? key;
    final type = (f['type'] as String?) ?? 'string';
    final required = f['required'] == true;
    final help = (f['help'] as String?) ?? '';
    Widget input;
    if (type == 'select') {
      final options =
          (f['options'] as List?)?.whereType<String>().toList() ?? const [];
      input = DropdownButtonFormField<String>(
        initialValue:
            _selected[key] ?? (options.isNotEmpty ? options.first : null),
        decoration: const InputDecoration(isDense: true),
        items: [
          for (final o in options) DropdownMenuItem(value: o, child: Text(o)),
        ],
        onChanged: _busy
            ? null
            : (v) => setState(() {
                if (v != null) _selected[key] = v;
              }),
      );
    } else if (type == 'boolean') {
      input = DropdownButtonFormField<String>(
        initialValue: _selected[key] ?? 'false',
        decoration: const InputDecoration(isDense: true),
        items: const [
          DropdownMenuItem(value: 'true', child: Text('是')),
          DropdownMenuItem(value: 'false', child: Text('否')),
        ],
        onChanged: _busy
            ? null
            : (v) => setState(() {
                if (v != null) _selected[key] = v;
              }),
      );
    } else if (type == 'secret') {
      input = TextField(
        controller: _text[key],
        obscureText: _obscure[key] ?? false,
        decoration: InputDecoration(
          isDense: true,
          hintText: widget.configured ? '已保存则不填以保留' : null,
          suffixIcon: IconButton(
            icon: Icon(
              (_obscure[key] ?? false)
                  ? Icons.visibility
                  : Icons.visibility_off,
              size: 18,
            ),
            onPressed: () =>
                setState(() => _obscure[key] = !(_obscure[key] ?? false)),
          ),
        ),
      );
    } else {
      input = TextField(
        controller: _text[key],
        keyboardType: type == 'number'
            ? TextInputType.number
            : TextInputType.text,
        decoration: const InputDecoration(isDense: true),
      );
    }
    return Padding(
      padding: const EdgeInsets.only(bottom: 10),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            '$label${required ? ' *' : ''}',
            style: theme.textTheme.labelMedium,
          ),
          const SizedBox(height: 4),
          input,
          if (help.isNotEmpty)
            Text(
              help,
              style: theme.textTheme.bodySmall?.copyWith(
                color: theme.colorScheme.outline,
              ),
            ),
        ],
      ),
    );
  }

  Future<void> _save() async {
    setState(() => _busy = true);
    final values = <String, dynamic>{};
    for (final f in _schema) {
      final key = f['key'] as String;
      final type = (f['type'] as String?) ?? 'string';
      if (type == 'boolean') {
        values[key] = _selected[key] == 'true';
      } else if (type == 'select') {
        values[key] = _selected[key] ?? '';
      } else {
        values[key] = _text[key]!.text.trim();
      }
    }
    // 必填校验：已配置的 secret 留空 = 保留旧值（跳过必填拦截），其余留空报错
    for (final f in _schema) {
      if (f['required'] != true) continue;
      final key = f['key'] as String;
      final v = values[key];
      if (v != null && v != '') continue;
      if (_secretTypes.contains(f['type']) && widget.configured) continue;
      if (!mounted) return;
      setState(() {
        _busy = false;
        _error = '「${(f['label'] as String?) ?? key}」必填';
      });
      return;
    }
    try {
      await widget.api.putCredentials(
        widget.userId,
        widget.skill.skillId,
        values,
      );
      if (!mounted) return;
      Navigator.pop(context, true);
    } on ApiException catch (e) {
      if (!mounted) return;
      setState(() {
        _busy = false;
        _error = '保存失败：${e.message}';
      });
    }
  }

  Future<void> _clear() async {
    setState(() => _busy = true);
    try {
      await widget.api.deleteCredentials(widget.userId, widget.skill.skillId);
      if (!mounted) return;
      Navigator.pop(context, true);
    } on ApiException catch (e) {
      if (!mounted) return;
      setState(() {
        _busy = false;
        _error = '清空失败：${e.message}';
      });
    }
  }
}
