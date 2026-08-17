import 'dart:async';

import 'package:flutter/material.dart';

import 'workbuddy_api.dart';
import 'workbuddy_models.dart';

/// Debug-only WorkBuddy console. Credentials live only for this route's lifetime.
class WorkBuddyDebugPage extends StatefulWidget {
  const WorkBuddyDebugPage({super.key});

  @override
  State<WorkBuddyDebugPage> createState() => _WorkBuddyDebugPageState();
}

class _WorkBuddyDebugPageState extends State<WorkBuddyDebugPage> {
  final _baseUrl = TextEditingController(text: 'https://www.workbuddy.cn');
  final _apiKey = TextEditingController();
  final _accessToken = TextEditingController();
  final _taskName = TextEditingController(text: '雷鸟 WorkBuddy 联调');
  final _prompt = TextEditingController(text: '请介绍一下你可以完成哪些任务');
  final List<WorkBuddyTaskSession> _tasks = [];
  bool _showSecrets = false;
  bool _autoPrepare = true;
  bool _loadingTasks = false;
  int _creatingCount = 0;

  @override
  void dispose() {
    _baseUrl.dispose();
    _apiKey.dispose();
    _accessToken.dispose();
    _taskName.dispose();
    _prompt.dispose();
    for (final task in _tasks) {
      task.dispose();
    }
    super.dispose();
  }

  Future<void> _createTask() async {
    final accessToken = _accessToken.text.trim();
    final prompt = _prompt.text.trim();
    if (accessToken.isEmpty || prompt.isEmpty) {
      _toast('请填写 OAuth access_token 和初始 Prompt');
      return;
    }
    final api = _newApi();
    setState(() => _creatingCount++);
    try {
      final snapshot = await api.createTask(
        prompt: prompt,
        name: _taskName.text,
      );
      if (!mounted) {
        api.dispose();
        return;
      }
      final session = WorkBuddyTaskSession(task: snapshot, taskApi: api);
      setState(() => _tasks.insert(0, session));
      if (_autoPrepare) unawaited(_prepare(session));
    } catch (error) {
      api.dispose();
      _toast('创建失败：$error');
    } finally {
      if (mounted) setState(() => _creatingCount--);
    }
  }

  Future<void> _loadRecentTasks() async {
    if (_accessToken.text.trim().isEmpty) {
      _toast('请先填写 OAuth access_token');
      return;
    }
    final listApi = _newApi();
    setState(() => _loadingTasks = true);
    try {
      final page = await listApi.listTasks();
      if (!mounted) return;
      final existing = _tasks.map((item) => item.task.taskId).toSet();
      final added = <WorkBuddyTaskSession>[];
      for (final task in page.tasks) {
        if (existing.add(task.taskId)) {
          added.add(WorkBuddyTaskSession(task: task, taskApi: _newApi()));
        }
      }
      setState(() => _tasks.addAll(added));
      _toast('读取 ${page.tasks.length} 个任务，新增 ${added.length} 个');
      if (_autoPrepare) {
        for (final session in added) {
          unawaited(_prepare(session));
        }
      }
    } catch (error) {
      _toast('读取任务列表失败：$error');
    } finally {
      listApi.dispose();
      if (mounted) setState(() => _loadingTasks = false);
    }
  }

  WorkBuddyTaskApi _newApi() => WorkBuddyTaskApi(
    baseUrl: _baseUrl.text,
    accessToken: _accessToken.text.trim(),
    legacyApiKey: _apiKey.text.trim().isEmpty ? null : _apiKey.text.trim(),
  );

  Future<void> _prepare(WorkBuddyTaskSession session) async {
    try {
      if (!session.task.canConnect) await session.refreshTask();
      if (!session.task.canConnect) return;
      await session.connect();
      await session.initializeAndLoad();
    } catch (error) {
      if (mounted) _toast(error.toString());
    }
  }

  void _removeTask(WorkBuddyTaskSession session) {
    setState(() => _tasks.remove(session));
    session.dispose();
  }

  void _clearSecrets() {
    _apiKey.clear();
    _accessToken.clear();
    setState(() {});
  }

  void _toast(String message) {
    if (!mounted) return;
    ScaffoldMessenger.of(context)
      ..hideCurrentSnackBar()
      ..showSnackBar(SnackBar(content: Text(message)));
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('WorkBuddy 调试台'),
        actions: [
          if (_tasks.isNotEmpty)
            IconButton(
              tooltip: '清空本地任务卡片',
              onPressed: () {
                final old = List<WorkBuddyTaskSession>.from(_tasks);
                setState(_tasks.clear);
                for (final item in old) {
                  item.dispose();
                }
              },
              icon: const Icon(Icons.layers_clear_outlined),
            ),
        ],
      ),
      body: ListView(
        padding: const EdgeInsets.fromLTRB(12, 8, 12, 24),
        children: [
          _buildCredentials(context),
          const SizedBox(height: 12),
          _buildComposer(context),
          const SizedBox(height: 16),
          _buildSummary(context),
          const SizedBox(height: 8),
          if (_tasks.isEmpty) _buildEmpty(context),
          for (final task in _tasks)
            Padding(
              padding: const EdgeInsets.only(bottom: 10),
              child: _TaskCard(
                key: ValueKey(task.task.taskId),
                session: task,
                onRemove: () => _removeTask(task),
                onError: _toast,
              ),
            ),
        ],
      ),
    );
  }

  Widget _buildCredentials(BuildContext context) {
    return Card.outlined(
      child: ExpansionTile(
        initiallyExpanded: true,
        leading: const Icon(Icons.key_outlined),
        title: const Text('连接配置'),
        subtitle: const Text('凭证仅保存在当前页面内存，不落盘'),
        childrenPadding: const EdgeInsets.fromLTRB(16, 0, 16, 16),
        children: [
          TextField(
            controller: _baseUrl,
            keyboardType: TextInputType.url,
            autocorrect: false,
            decoration: const InputDecoration(
              labelText: 'Task API Base URL',
              border: OutlineInputBorder(),
            ),
          ),
          const SizedBox(height: 12),
          TextField(
            controller: _accessToken,
            obscureText: !_showSecrets,
            autocorrect: false,
            enableSuggestions: false,
            decoration: const InputDecoration(
              labelText: 'OAuth access_token · Bearer',
              helperText:
                  '由雷鸟云使用 authorization_code + client_secret 换取；文档示例有效期 3600 秒',
              border: OutlineInputBorder(),
            ),
          ),
          const SizedBox(height: 12),
          TextField(
            controller: _apiKey,
            obscureText: !_showSecrets,
            autocorrect: false,
            enableSuggestions: false,
            decoration: const InputDecoration(
              labelText: '旧版 API Key · X-Api-Key（可选）',
              helperText: '仅用于兼容旧 Task API 文档；新开发者文档未要求该请求头',
              border: OutlineInputBorder(),
            ),
          ),
          Row(
            children: [
              Checkbox(
                value: _showSecrets,
                onChanged: (value) =>
                    setState(() => _showSecrets = value ?? false),
              ),
              const Text('显示凭证'),
              const Spacer(),
              TextButton.icon(
                onPressed: _clearSecrets,
                icon: const Icon(Icons.backspace_outlined),
                label: const Text('清除'),
              ),
            ],
          ),
        ],
      ),
    );
  }

  Widget _buildComposer(BuildContext context) {
    return Card.outlined(
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Text('创建异步任务', style: Theme.of(context).textTheme.titleMedium),
            const SizedBox(height: 12),
            TextField(
              controller: _taskName,
              decoration: const InputDecoration(
                labelText: '任务名称（可选）',
                border: OutlineInputBorder(),
              ),
            ),
            const SizedBox(height: 12),
            TextField(
              controller: _prompt,
              minLines: 2,
              maxLines: 5,
              decoration: const InputDecoration(
                labelText: '初始 Prompt',
                border: OutlineInputBorder(),
              ),
            ),
            SwitchListTile.adaptive(
              contentPadding: EdgeInsets.zero,
              value: _autoPrepare,
              onChanged: (value) => setState(() => _autoPrepare = value),
              title: const Text('创建后自动建联'),
              subtitle: const Text('依次执行 ACP GET、initialize、session/load'),
            ),
            Wrap(
              spacing: 8,
              runSpacing: 8,
              children: [
                FilledButton.icon(
                  onPressed: _createTask,
                  icon: const Icon(Icons.add_task),
                  label: Text(
                    _creatingCount == 0
                        ? '创建任务'
                        : '创建任务（$_creatingCount 个请求进行中）',
                  ),
                ),
                OutlinedButton.icon(
                  onPressed: _loadingTasks ? null : _loadRecentTasks,
                  icon: const Icon(Icons.cloud_download_outlined),
                  label: Text(_loadingTasks ? '读取中…' : '读取最近任务'),
                ),
              ],
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildSummary(BuildContext context) {
    final working = _tasks
        .where(
          (task) =>
              task.phase == WorkBuddyTaskPhase.working ||
              task.phase == WorkBuddyTaskPhase.connecting,
        )
        .length;
    final waiting = _tasks
        .where((task) => task.phase == WorkBuddyTaskPhase.waitingUser)
        .length;
    final failed = _tasks
        .where((task) => task.phase == WorkBuddyTaskPhase.failed)
        .length;
    return Wrap(
      spacing: 8,
      runSpacing: 8,
      children: [
        _MetricChip(label: '任务', value: _tasks.length, color: Colors.blue),
        _MetricChip(label: '执行中', value: working, color: Colors.orange),
        _MetricChip(label: '待确认', value: waiting, color: Colors.purple),
        _MetricChip(label: '异常', value: failed, color: Colors.red),
      ],
    );
  }

  Widget _buildEmpty(BuildContext context) => Padding(
    padding: const EdgeInsets.symmetric(vertical: 36),
    child: Column(
      children: [
        Icon(
          Icons.account_tree_outlined,
          size: 52,
          color: Theme.of(context).colorScheme.outline,
        ),
        const SizedBox(height: 12),
        const Text('尚无任务。可连续点击创建，验证多个任务并行执行。'),
      ],
    ),
  );
}

class _MetricChip extends StatelessWidget {
  final String label;
  final int value;
  final Color color;

  const _MetricChip({
    required this.label,
    required this.value,
    required this.color,
  });

  @override
  Widget build(BuildContext context) => Chip(
    avatar: CircleAvatar(
      backgroundColor: color,
      foregroundColor: Colors.white,
      child: Text('$value'),
    ),
    label: Text(label),
  );
}

class _TaskCard extends StatefulWidget {
  final WorkBuddyTaskSession session;
  final VoidCallback onRemove;
  final ValueChanged<String> onError;

  const _TaskCard({
    super.key,
    required this.session,
    required this.onRemove,
    required this.onError,
  });

  @override
  State<_TaskCard> createState() => _TaskCardState();
}

class _TaskCardState extends State<_TaskCard> {
  final _prompt = TextEditingController();
  bool _expanded = true;

  @override
  void dispose() {
    _prompt.dispose();
    super.dispose();
  }

  Future<void> _run(Future<void> Function() action) async {
    try {
      await action();
    } catch (error) {
      widget.onError(error.toString());
    }
  }

  Future<void> _send() async {
    final text = _prompt.text.trim();
    if (text.isEmpty) return;
    _prompt.clear();
    await _run(() => widget.session.sendPrompt(text));
  }

  @override
  Widget build(BuildContext context) {
    return AnimatedBuilder(
      animation: widget.session,
      builder: (context, _) {
        final session = widget.session;
        return Card(
          clipBehavior: Clip.antiAlias,
          child: Column(
            children: [
              ListTile(
                onTap: () => setState(() => _expanded = !_expanded),
                leading: _PhaseBadge(phase: session.phase),
                title: Text(session.task.name),
                subtitle: Text(
                  '${session.task.taskId} · ${_phaseLabel(session.phase)}'
                  '${session.stopReason == null ? '' : ' · ${session.stopReason}'}',
                  maxLines: 2,
                  overflow: TextOverflow.ellipsis,
                ),
                trailing: Row(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    IconButton(
                      tooltip: '删除本地卡片（不删除云端任务）',
                      onPressed: widget.onRemove,
                      icon: const Icon(Icons.close),
                    ),
                    Icon(_expanded ? Icons.expand_less : Icons.expand_more),
                  ],
                ),
              ),
              if (_expanded) ...[
                const Divider(height: 1),
                Padding(
                  padding: const EdgeInsets.all(12),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.stretch,
                    children: [
                      if (session.error != null)
                        _errorBox(context, session.error!),
                      _actions(session),
                      if (session.permission != null) ...[
                        const SizedBox(height: 10),
                        _permissionCard(context, session),
                      ],
                      const SizedBox(height: 10),
                      _conversation(context, session),
                      if (session.artifacts.isNotEmpty) ...[
                        const SizedBox(height: 4),
                        _artifacts(session),
                      ],
                      const SizedBox(height: 10),
                      _promptBar(session),
                      const SizedBox(height: 4),
                      _eventLog(context, session),
                    ],
                  ),
                ),
              ],
            ],
          ),
        );
      },
    );
  }

  Widget _actions(WorkBuddyTaskSession session) => Wrap(
    spacing: 8,
    runSpacing: 8,
    children: [
      OutlinedButton.icon(
        onPressed: () => _run(session.refreshTask),
        icon: const Icon(Icons.refresh),
        label: const Text('刷新任务'),
      ),
      OutlinedButton.icon(
        onPressed: session.isConnected ? null : () => _run(session.connect),
        icon: const Icon(Icons.cable),
        label: const Text('建联'),
      ),
      OutlinedButton.icon(
        onPressed: session.isConnected
            ? () => _run(session.initializeAndLoad)
            : null,
        icon: const Icon(Icons.playlist_add_check),
        label: const Text('初始化/加载'),
      ),
      OutlinedButton.icon(
        onPressed: session.task.canConnect
            ? () => _run(session.fetchArtifacts)
            : null,
        icon: const Icon(Icons.inventory_2_outlined),
        label: Text('产物 ${session.artifacts.length}'),
      ),
      OutlinedButton.icon(
        onPressed: session.isConnected ? () => _run(session.disconnect) : null,
        icon: const Icon(Icons.link_off),
        label: const Text('断开'),
      ),
    ],
  );

  Widget _artifacts(WorkBuddyTaskSession session) => ExpansionTile(
    tilePadding: EdgeInsets.zero,
    title: Text('会话产物 · ${session.artifacts.length}'),
    subtitle: const Text('REST 全量 + SSE 增量，以 artifact.uri 合并'),
    children: [
      for (final artifact in session.artifacts.values)
        ListTile(
          dense: true,
          leading: Icon(switch (artifact.type) {
            'plan' => Icons.description_outlined,
            'tasks' => Icons.checklist,
            'media' => Icons.perm_media_outlined,
            'overview' => Icons.summarize_outlined,
            _ => Icons.insert_drive_file_outlined,
          }),
          title: Text(artifact.title),
          subtitle: SelectableText(
            '${artifact.type} · ${artifact.mimeType ?? artifact.uri}'
            '${artifact.url == null ? '' : '\n${artifact.url}'}',
          ),
        ),
    ],
  );

  Widget _conversation(BuildContext context, WorkBuddyTaskSession session) {
    if (session.messages.isEmpty) {
      return Container(
        padding: const EdgeInsets.all(16),
        decoration: BoxDecoration(
          color: Theme.of(context).colorScheme.surfaceContainerLow,
          borderRadius: BorderRadius.circular(12),
        ),
        child: const Text('ACP 建联并加载后，在下方发送下一轮 Prompt。'),
      );
    }
    return Container(
      constraints: const BoxConstraints(maxHeight: 320),
      decoration: BoxDecoration(
        color: Theme.of(context).colorScheme.surfaceContainerLow,
        borderRadius: BorderRadius.circular(12),
      ),
      child: ListView.builder(
        shrinkWrap: true,
        padding: const EdgeInsets.all(10),
        itemCount: session.messages.length,
        itemBuilder: (context, index) {
          final message = session.messages[index];
          final isUser = message.role == WorkBuddyMessageRole.user;
          return Align(
            alignment: isUser ? Alignment.centerRight : Alignment.centerLeft,
            child: Container(
              margin: const EdgeInsets.symmetric(vertical: 4),
              padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
              constraints: const BoxConstraints(maxWidth: 560),
              decoration: BoxDecoration(
                color: isUser
                    ? Theme.of(context).colorScheme.primaryContainer
                    : Theme.of(context).colorScheme.surfaceContainerHighest,
                borderRadius: BorderRadius.circular(12),
              ),
              child: SelectableText(message.text),
            ),
          );
        },
      ),
    );
  }

  Widget _promptBar(WorkBuddyTaskSession session) => Row(
    crossAxisAlignment: CrossAxisAlignment.end,
    children: [
      Expanded(
        child: TextField(
          controller: _prompt,
          minLines: 1,
          maxLines: 4,
          onSubmitted: session.canSend ? (_) => _send() : null,
          decoration: const InputDecoration(
            labelText: '下一轮 Prompt',
            border: OutlineInputBorder(),
          ),
        ),
      ),
      const SizedBox(width: 8),
      IconButton.filled(
        tooltip: '发送',
        onPressed: session.canSend ? _send : null,
        icon: const Icon(Icons.send),
      ),
      IconButton(
        tooltip: '停止当前轮',
        onPressed: session.isConnected ? () => _run(session.cancel) : null,
        icon: const Icon(Icons.stop_circle_outlined),
      ),
    ],
  );

  Widget _permissionCard(BuildContext context, WorkBuddyTaskSession session) {
    final permission = session.permission!;
    return Card.filled(
      color: Theme.of(context).colorScheme.tertiaryContainer,
      child: Padding(
        padding: const EdgeInsets.all(12),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Text(
              permission.title,
              style: Theme.of(context).textTheme.titleSmall,
            ),
            if (permission.description.isNotEmpty) ...[
              const SizedBox(height: 6),
              Text(permission.description),
            ],
            const SizedBox(height: 10),
            Wrap(
              spacing: 8,
              runSpacing: 8,
              children: [
                for (final option in permission.options)
                  FilledButton.tonal(
                    onPressed: () =>
                        _run(() => session.answerPermission(option.optionId)),
                    child: Text(option.name),
                  ),
                TextButton(
                  onPressed: () => _run(() => session.answerPermission(null)),
                  child: const Text('取消'),
                ),
              ],
            ),
          ],
        ),
      ),
    );
  }

  Widget _eventLog(BuildContext context, WorkBuddyTaskSession session) {
    return ExpansionTile(
      tilePadding: EdgeInsets.zero,
      title: Text('协议事件 · ${session.events.length}'),
      subtitle: Text(
        session.connectionId == null
            ? '未连接'
            : 'connection ${_mask(session.connectionId!)}',
      ),
      children: [
        if (session.events.isEmpty)
          const ListTile(title: Text('暂无事件'))
        else
          ConstrainedBox(
            constraints: const BoxConstraints(maxHeight: 360),
            child: ListView.builder(
              shrinkWrap: true,
              itemCount: session.events.length,
              itemBuilder: (context, index) {
                final event = session.events[index];
                return ExpansionTile(
                  dense: true,
                  title: Text('${_time(event.timestamp)}  ${event.type}'),
                  subtitle: Text(event.summary),
                  childrenPadding: const EdgeInsets.fromLTRB(16, 0, 8, 12),
                  children: [
                    if (event.prettyRaw.isNotEmpty)
                      SizedBox(
                        width: double.infinity,
                        child: SelectableText(
                          event.prettyRaw,
                          style: const TextStyle(
                            fontFamily: 'monospace',
                            fontSize: 12,
                          ),
                        ),
                      ),
                  ],
                );
              },
            ),
          ),
      ],
    );
  }

  Widget _errorBox(BuildContext context, String message) => Container(
    margin: const EdgeInsets.only(bottom: 10),
    padding: const EdgeInsets.all(10),
    decoration: BoxDecoration(
      color: Theme.of(context).colorScheme.errorContainer,
      borderRadius: BorderRadius.circular(10),
    ),
    child: Text(message),
  );

  static String _phaseLabel(WorkBuddyTaskPhase phase) => switch (phase) {
    WorkBuddyTaskPhase.creating => '创建中',
    WorkBuddyTaskPhase.ready => '待建联',
    WorkBuddyTaskPhase.connecting => '建联中',
    WorkBuddyTaskPhase.connected => '已连接',
    WorkBuddyTaskPhase.working => '执行中',
    WorkBuddyTaskPhase.waitingUser => '等待确认',
    WorkBuddyTaskPhase.completed => '本轮完成',
    WorkBuddyTaskPhase.failed => '异常',
    WorkBuddyTaskPhase.disconnected => '已断开',
  };

  static String _mask(String value) => value.length <= 8
      ? '***'
      : '${value.substring(0, 4)}…${value.substring(value.length - 4)}';

  static String _time(DateTime time) =>
      '${time.hour.toString().padLeft(2, '0')}:'
      '${time.minute.toString().padLeft(2, '0')}:'
      '${time.second.toString().padLeft(2, '0')}';
}

class _PhaseBadge extends StatelessWidget {
  final WorkBuddyTaskPhase phase;

  const _PhaseBadge({required this.phase});

  @override
  Widget build(BuildContext context) {
    final color = switch (phase) {
      WorkBuddyTaskPhase.working ||
      WorkBuddyTaskPhase.connecting => Colors.orange,
      WorkBuddyTaskPhase.waitingUser => Colors.purple,
      WorkBuddyTaskPhase.completed ||
      WorkBuddyTaskPhase.connected => Colors.green,
      WorkBuddyTaskPhase.failed => Colors.red,
      _ => Colors.blueGrey,
    };
    return CircleAvatar(
      backgroundColor: color.withValues(alpha: 0.15),
      foregroundColor: color,
      child: Icon(switch (phase) {
        WorkBuddyTaskPhase.working ||
        WorkBuddyTaskPhase.connecting => Icons.sync,
        WorkBuddyTaskPhase.waitingUser => Icons.help_outline,
        WorkBuddyTaskPhase.completed => Icons.check,
        WorkBuddyTaskPhase.failed => Icons.error_outline,
        WorkBuddyTaskPhase.connected => Icons.link,
        _ => Icons.task_alt,
      }),
    );
  }
}
