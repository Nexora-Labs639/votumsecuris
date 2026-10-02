import 'dart:async';
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

enum LogLevel { info, warn, error }

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

  @override
  void initState() {
    super.initState();
    _detectProjectRoot();
    _log('VotumSecuris（志钺）启动');
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
    }
  }
  
Future<void> _triggerAgent(String agentId) async {
  if (_busy) {
    _log('已有任务在执行，请等待', level: LogLevel.warn);
    return;
  }
  setState(() => _busy = true);

  final idx = _agents.indexWhere((a) => a.id == agentId);
  if (idx < 0) return;

  setState(() {
    _agents[idx].status = 'running';
    _agents[idx].progress = 0;
  });
  _log('触发 $agentId 执行任务: ${_agents[idx].task}');

  try {
    final result = await Process.run(
      'python',
      ['-m', 'executor.multi_agent'],
      workingDirectory: _projectRoot,
      runInShell: true,
    );

    final lines = result.stdout.toString().split('\n');
    for (final line in lines) {
      if (line.trim().isEmpty) continue;
      _log(line);
      if (line.contains('第')) {
        final m = RegExp(r'第 (\d+) 步').firstMatch(line);
        if (m != null) {
          final step = int.parse(m.group(1)!);
          setState(() => _agents[idx].progress = step / 3);
        }
      }
    }

    if (result.stderr.toString().isNotEmpty) {
      _log('[stderr] ${result.stderr}', level: LogLevel.warn);
    }

    setState(() => _agents[idx].status = 'idle');
    setState(() => _agents[idx].progress = 1.0);
    _log('$agentId 执行完成', level: LogLevel.info);
  } catch (e) {
    setState(() => _agents[idx].status = 'error');
    _log('$agentId 执行失败: $e', level: LogLevel.error);
  } finally {
    setState(() => _busy = false);
  }
}

Future<void> _showApprovalDialog(
    String toolName, Map<String, dynamic> params, String risk) async {
  final result = await showDialog<bool>(
    context: context,
    barrierDismissible: false,
    builder: (ctx) => AlertDialog(
      backgroundColor: AppTheme.panel,
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(8),
        side: const BorderSide(color: AppTheme.warning, width: 1),
      ),
      title: Row(
        children: [
          const Icon(Icons.warning_amber, color: AppTheme.warning),
          const SizedBox(width: 8),
          const Text('高风险操作 · 需要审批'),
        ],
      ),
      content: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          _kv('工具', toolName),
          _kv('风险', risk),
          const SizedBox(height: 8),
          const Text('参数：', style: TextStyle(color: AppTheme.textDim)),
          const SizedBox(height: 4),
          Container(
            width: double.infinity,
            padding: const EdgeInsets.all(8),
            decoration: BoxDecoration(
              color: AppTheme.bg,
              borderRadius: BorderRadius.circular(4),
              border: Border.all(color: AppTheme.border),
            ),
            child: Text(
              params.toString(),
              style: const TextStyle(fontFamily: 'monospace', fontSize: 12),
            ),
          ),
          const SizedBox(height: 12),
          const Text('该操作不可撤销，是否允许执行？',
              style: TextStyle(color: AppTheme.warning)),
        ],
      ),
      actions: [
        TextButton(
          onPressed: () => Navigator.pop(ctx, false),
          child: const Text('拒绝', style: TextStyle(color: AppTheme.danger)),
        ),
        ElevatedButton(
          style: ElevatedButton.styleFrom(backgroundColor: AppTheme.success),
          onPressed: () => Navigator.pop(ctx, true),
          child: const Text('允许'),
        ),
      ],
    ),
  );

  if (result == true) {
    _log('审批通过: $toolName', level: LogLevel.info);
  } else {
    _log('审批拒绝: $toolName', level: LogLevel.warn);
  }
}

Widget _kv(String k, String v) {
  return Padding(
    padding: const EdgeInsets.symmetric(vertical: 2),
    child: Row(
      children: [
        SizedBox(
          width: 60,
          child: Text(k, style: const TextStyle(color: AppTheme.textDim)),
        ),
        Text(v, style: const TextStyle(fontWeight: FontWeight.bold)),
      ],
    ),
  );
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
              icon: const Icon(Icons.warning_amber, color: AppTheme.warning),
              tooltip: '模拟高风险操作（弹审批窗）',
              onPressed: () => _showApprovalDialog(
                'run_shell',
                {'command': 'rm -rf /tmp/test'},
                'high',
              ),
            ),
            IconButton(
              icon: const Icon(Icons.delete_outline),
              tooltip: '清空日志',
              onPressed: () => setState(() => _logs.clear()),
            ),
          ],
        ),
        body: isWide
            ? Row(
                children: [
                  _agentPanel(width: 300),
                  const VerticalDivider(width: 1, color: AppTheme.border),
                  Expanded(child: _logPanel()),
                ],
              )
            : Column(
                children: [
                  _agentPanel(height: 240),
                  const Divider(height: 1, color: AppTheme.border),
                  Expanded(child: _logPanel()),
                ],
              ),
      );
    },
  );
}

  Widget _agentPanel({double? width, double? height}) {
    return Container(
      width: width,
      height: height,
      color: AppTheme.panel,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Padding(
            padding: EdgeInsets.all(12),
            child: Text('智能体列表',
                style: TextStyle(fontSize: 16, fontWeight: FontWeight.bold)),
          ),
          const Divider(height: 1, color: AppTheme.border),
          Expanded(
            child: ListView(
              padding: const EdgeInsets.all(12),
              children: _agents.map(_agentCard).toList(),
            ),
          ),
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
                  width: 10,
                  height: 10,
                  decoration: BoxDecoration(color: color, shape: BoxShape.circle),
                ),
                const SizedBox(width: 8),
                Text(a.id,
                    style: const TextStyle(
                        fontSize: 14, fontWeight: FontWeight.bold)),
                const Spacer(),
                Text(a.status,
                    style: TextStyle(fontSize: 11, color: color)),
              ],
            ),
            const SizedBox(height: 8),
            Text('任务: ${a.task}',
                style: const TextStyle(fontSize: 12, color: AppTheme.textDim)),
            const SizedBox(height: 8),
            LinearProgressIndicator(
              value: a.progress,
              backgroundColor: AppTheme.bg,
              valueColor: AlwaysStoppedAnimation(color),
              minHeight: 4,
            ),
            const SizedBox(height: 10),
            SizedBox(
              width: double.infinity,
              child: ElevatedButton(
                onPressed: a.status == 'running' || _busy
                    ? null
                    : () => _triggerAgent(a.id),
                child: Text(a.status == 'running' ? '执行中...' : '触发任务'),
              ),
            ),
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