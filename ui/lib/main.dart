import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'package:flutter/material.dart';

void main() {
  runApp(const VotumSecurisApp());
}

class AppTheme {
  static const bg = Color(0xFF0D1117);
  static const panel = Color(0xFF161B22);
  static const card = Color(0xFF21262D);
  static const border = Color(0xFF30363D);
  static const accent = Color(0xFF58A6FF);
  static const success = Color(0xFF3FB950);
  static const warning = Color(0xFFD29922);
  static const danger = Color(0xFFF85149);
  static const textDim = Color(0xFF8B949E);
}

class VotumSecurisApp extends StatelessWidget {
  const VotumSecurisApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'VotumSecuris（志钺）',
      debugShowCheckedModeBanner: false,
      theme: ThemeData(
        brightness: Brightness.dark,
        scaffoldBackgroundColor: AppTheme.bg,
        colorScheme: const ColorScheme.dark(
          primary: AppTheme.accent,
          surface: AppTheme.panel,
        ),
        useMaterial3: true,
      ),
      home: const AgentDashboard(),
    );
  }
}

enum LogLevel { info, warn, error, critical }

class LogEntry {
  final String ts;
  final String msg;
  final LogLevel level;
  LogEntry(this.msg, {this.level = LogLevel.info})
      : ts = DateTime.now().toIso8601String().substring(11, 19);
}

class Agent {
  String id;
  String task;
  String status;
  double progress;
  Agent({required this.id, required this.task, this.status = 'idle', this.progress = 0});
}

class AgentDashboard extends StatefulWidget {
  const AgentDashboard({super.key});

  @override
  State<AgentDashboard> createState() => _AgentDashboardState();
}

class _AgentDashboardState extends State<AgentDashboard> {
  String _projectRoot = '';
  final List<LogEntry> _logs = [];
  final List<Agent> _agents = [
    Agent(id: 'agent-A', task: '整理文件'),
    Agent(id: 'agent-B', task: '审核日志'),
  ];
  bool _busy = false;
  final TextEditingController _pathCtrl = TextEditingController();

  @override
  void initState() {
    super.initState();
    _detectProjectRoot();
    _log('VotumSecuris（志钺）启动');
  }

  @override
  void dispose() {
    _pathCtrl.dispose();
    super.dispose();
  }
  
void _detectProjectRoot() {
  String dir = Directory.current.path;
  for (int i = 0; i < 5; i++) {
    if (dir.endsWith('votumsecuris')) break;
    final parent = Directory(dir).parent.path;
    if (parent == dir) break;
    dir = parent;
  }
  setState(() => _projectRoot = dir);
  _log('项目根目录: $dir');
  _pathCtrl.text = '$dir/test_target.txt';
}

void _log(String msg, {LogLevel level = LogLevel.info}) {
  setState(() {
    _logs.add(LogEntry(msg, level: level));
    if (_logs.length > 500) _logs.removeAt(0);
  });
}

Color _levelColor(LogLevel l) {
  switch (l) {
    case LogLevel.info:
      return AppTheme.success;
    case LogLevel.warn:
      return AppTheme.warning;
    case LogLevel.error:
      return AppTheme.danger;
    case LogLevel.critical:
      return AppTheme.danger;
  }
}

  Future<void> _requestDelete(String path, {bool userApproved = false}) async {
    _log('请求删除: $path  (用户已审批=$userApproved)');

    final script = '''
import sys, json
sys.path.insert(0, r"$_projectRoot")
from executor.policy_bridge import request_delete
result = request_delete("ui-agent", r"$path", user_approved=$userApproved)
print(json.dumps(result, ensure_ascii=False))
''';

    try {
      final result = await Process.run(
        'python',
        ['-c', script],
        workingDirectory: _projectRoot,
        runInShell: true,
      );

      final out = result.stdout.toString().trim();
      if (out.isEmpty) {
        _log('执行失败: ${result.stderr}', level: LogLevel.error);
        return;
      }

      final lastLine = out.split('\n').last;
      final Map<String, dynamic> r = jsonDecode(lastLine);
      final status = r['status'] as String;
      final reason = r['reason'] as String? ?? '';

      switch (status) {
        case 'deleted':
          _log('已删除: $path | 回收站: ${r['trash_path']}', level: LogLevel.info);
          break;
        case 'denied':
          _log('拒绝删除: $path | 原因: $reason', level: LogLevel.critical);
          break;
        case 'need_approval':
          _log('需要审批: $path | 原因: $reason', level: LogLevel.warn);
          final ok = await _showApprovalDialog(path, reason, r['severity'] as String? ?? 'warn');
          if (ok) {
            await _requestDelete(path, userApproved: true);
          } else {
            _log('用户拒绝删除: $path', level: LogLevel.warn);
          }
          break;
        case 'error':
          _log('执行失败: $reason', level: LogLevel.error);
          break;
      }
    } catch (e) {
      _log('异常: $e', level: LogLevel.error);
    }
  }

  Future<bool> _showApprovalDialog(String path, String reason, String severity) async {
    final isCritical = severity == 'critical';
    final result = await showDialog<bool>(
      context: context,
      barrierDismissible: false,
      builder: (ctx) => AlertDialog(
        backgroundColor: AppTheme.panel,
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(8),
          side: BorderSide(
            color: isCritical ? AppTheme.danger : AppTheme.warning,
            width: 2,
          ),
        ),
        title: Row(
          children: [
            Icon(isCritical ? Icons.dangerous : Icons.warning_amber,
                color: isCritical ? AppTheme.danger : AppTheme.warning),
            const SizedBox(width: 8),
            Text(isCritical ? '危险操作 · 必须确认' : '高风险操作 · 需要审批'),
          ],
        ),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const Text('文件路径：', style: TextStyle(color: AppTheme.textDim)),
            const SizedBox(height: 4),
            Container(
              width: double.infinity,
              padding: const EdgeInsets.all(8),
              decoration: BoxDecoration(
                color: AppTheme.bg,
                borderRadius: BorderRadius.circular(4),
                border: Border.all(color: AppTheme.border),
              ),
              child: Text(path,
                  style: const TextStyle(fontFamily: 'monospace', fontSize: 12)),
            ),
            const SizedBox(height: 12),
            const Text('原因：', style: TextStyle(color: AppTheme.textDim)),
            const SizedBox(height: 4),
            Text(reason, style: TextStyle(color: AppTheme.warning)),
            const SizedBox(height: 12),
            const Text('删除后可从回收站恢复。是否确认？',
                style: TextStyle(color: AppTheme.textDim, fontSize: 12)),
          ],
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(ctx, false),
            child: const Text('取消', style: TextStyle(color: AppTheme.danger)),
          ),
          ElevatedButton(
            style: ElevatedButton.styleFrom(backgroundColor: AppTheme.success),
            onPressed: () => Navigator.pop(ctx, true),
            child: const Text('确认删除'),
          ),
        ],
      ),
    );
    return result == true;
  }
  
@override
Widget build(BuildContext context) {
  return LayoutBuilder(
    builder: (ctx, constraints) {
      final isWide = constraints.maxWidth >= 800;
      return Scaffold(
        appBar: AppBar(
          title: const Row(
            children: [
              Icon(Icons.shield, color: AppTheme.accent),
              SizedBox(width: 8),
              Text('VotumSecuris（志钺） — Agent 监控面板'),
            ],
          ),
          backgroundColor: AppTheme.panel,
          actions: [
            IconButton(
              icon: const Icon(Icons.clear_all),
              tooltip: '清空日志',
              onPressed: () => setState(() => _logs.clear()),
            ),
          ],
        ),
        body: isWide
            ? Row(
                children: [
                  _leftPanel(width: 340),
                  const VerticalDivider(width: 1, color: AppTheme.border),
                  Expanded(child: _logPanel()),
                ],
              )
            : Column(
                children: [
                  SizedBox(height: 300, child: _leftPanel()),
                  const Divider(height: 1, color: AppTheme.border),
                  Expanded(child: _logPanel()),
                ],
              ),
      );
    },
  );
}

Widget _leftPanel({double? width}) {
  return Container(
    width: width,
    color: AppTheme.panel,
    child: ListView(
      padding: const EdgeInsets.all(12),
      children: [
        const Text('删除测试',
            style: TextStyle(fontSize: 16, fontWeight: FontWeight.bold)),
        const SizedBox(height: 12),
        TextField(
          controller: _pathCtrl,
          style: const TextStyle(fontSize: 12, fontFamily: 'monospace'),
          decoration: const InputDecoration(
            labelText: '文件路径',
            border: OutlineInputBorder(),
            isDense: true,
          ),
        ),
        const SizedBox(height: 8),
        Row(
          children: [
            Expanded(
              child: ElevatedButton.icon(
                icon: const Icon(Icons.delete_outline, size: 16),
                label: const Text('删除'),
                onPressed: _busy
                    ? null
                    : () => _requestDelete(_pathCtrl.text),
              ),
            ),
          ],
        ),
        const SizedBox(height: 12),
        const Divider(color: AppTheme.border),
        const SizedBox(height: 12),
        const Text('智能体列表',
            style: TextStyle(fontSize: 16, fontWeight: FontWeight.bold)),
        const SizedBox(height: 12),
        ..._agents.map(_agentCard),
      ],
    ),
  );
}

Widget _agentCard(Agent a) {
  final color = a.status == 'running'
      ? AppTheme.success
      : a.status == 'error'
          ? AppTheme.danger
          : AppTheme.textDim;
  return Card(
    color: AppTheme.card,
    margin: const EdgeInsets.only(bottom: 12),
    shape: RoundedRectangleBorder(
      borderRadius: BorderRadius.circular(8),
      side: const BorderSide(color: AppTheme.border),
    ),
    child: Padding(
      padding: const EdgeInsets.all(12),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Container(
                width: 10, height: 10,
                decoration: BoxDecoration(color: color, shape: BoxShape.circle),
              ),
              const SizedBox(width: 8),
              Text(a.id,
                  style: const TextStyle(fontSize: 14, fontWeight: FontWeight.bold)),
              const Spacer(),
              Text(a.status, style: TextStyle(fontSize: 11, color: color)),
            ],
          ),
          const SizedBox(height: 8),
          Text('任务: ${a.task}',
              style: const TextStyle(fontSize: 12, color: AppTheme.textDim)),
        ],
      ),
    ),
  );
}

  Widget _logPanel() {
    return Container(
      color: AppTheme.bg,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Padding(
            padding: EdgeInsets.all(12),
            child: Text('实时日志',
                style: TextStyle(fontSize: 16, fontWeight: FontWeight.bold)),
          ),
          const Divider(height: 1, color: AppTheme.border),
          Expanded(
            child: ListView.builder(
              padding: const EdgeInsets.all(12),
              itemCount: _logs.length,
              itemBuilder: (ctx, i) {
                final e = _logs[i];
                return Padding(
                  padding: const EdgeInsets.symmetric(vertical: 2),
                  child: Row(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text('[${e.ts}] ',
                          style: const TextStyle(
                              fontFamily: 'monospace',
                              fontSize: 12,
                              color: AppTheme.textDim)),
                      Expanded(
                        child: Text(
                          e.msg,
                          style: TextStyle(
                            fontFamily: 'monospace',
                            fontSize: 12,
                            color: _levelColor(e.level),
                          ),
                        ),
                      ),
                    ],
                  ),
                );
              },
            ),
          ),
        ],
      ),
    );
  }
}