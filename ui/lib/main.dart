import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'dart:math';
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

  Agent({required this.id, required this.task, this.status = 'idle'});
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
  final TextEditingController _queryCtrl = TextEditingController();
  final TextEditingController _peerIpCtrl =
      TextEditingController(text: '192.168.10.8');
  List<Map<String, dynamic>> _ragResults = [];
  List<Map<String, dynamic>> _knowledgeFiles = [];

  @override
  void initState() {
    super.initState();
    _detectProjectRoot();
    _log('VotumSecuris（志钺）启动');
    Future.delayed(const Duration(milliseconds: 1200), () {
      if (mounted) _refreshKnowledge();
    });
  }

  @override
  void dispose() {
    _pathCtrl.dispose();
    _queryCtrl.dispose();
    _peerIpCtrl.dispose();
    super.dispose();
  }

  void _detectProjectRoot() {
    try {
      String dir = Directory.current.path;
      for (int i = 0; i < 5; i++) {
        if (dir.endsWith('votumsecuris')) break;
        final parent = Directory(dir).parent.path;
        if (parent == dir) break;
        dir = parent;
      }
      if (!mounted) return;
      setState(() => _projectRoot = dir);
      _log('项目根目录: $dir');
      _pathCtrl.text = '$dir/test_target.txt';
    } catch (e) {
      _log('项目根目录检测失败: $e', level: LogLevel.error);
    }
  }
  
void _log(String msg, {LogLevel level = LogLevel.info}) {
  if (!mounted) return;
  setState(() {
    _logs.add(LogEntry(msg, level: level));
    if (_logs.length > 800) _logs.removeAt(0);
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

String _extractPayload(String out) {
  const prefix = 'RESULT:';
  for (final raw in out.split('\n')) {
    final line = raw.trim();
    if (line.startsWith(prefix)) {
      return line.substring(prefix.length).trim();
    }
  }
  return '';
}

Future<String> _runPython(String code) async {
  final now = DateTime.now().microsecondsSinceEpoch;
  final rand = Random().nextInt(999999);
  final tmpFile =
      File('${Directory.systemTemp.path}/votum_${now}_$rand.py');

  final header = '# -*- coding: utf-8 -*-\n'
      'import sys, io\n'
      'try:\n'
      '    if hasattr(sys.stdout, "buffer"):\n'
      '        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")\n'
      '    if hasattr(sys.stderr, "buffer"):\n'
      '        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")\n'
      'except Exception:\n'
      '    pass\n';

  try {
    await tmpFile.writeAsString(header + code, encoding: utf8);
  } catch (e) {
    return '[TMP_WRITE_ERROR] $e';
  }

  String out = '';
  try {
    final result = await Process.run(
      'python',
      [tmpFile.path],
      workingDirectory: _projectRoot.isEmpty ? null : _projectRoot,
      runInShell: true,
      stdoutEncoding: utf8,
      stderrEncoding: utf8,
      environment: {
        'PYTHONIOENCODING': 'utf-8',
        'PYTHONUTF8': '1',
      },
    ).timeout(const Duration(seconds: 120));
    out = result.stdout.toString();
    final err = result.stderr.toString();
    if (err.isNotEmpty) out += '\n[STDERR]\n' + err;
  } on TimeoutException {
    out = '[TIMEOUT] Python 脚本超过 120 秒未返回';
  } catch (e) {
    out = '[PROCESS_ERROR] $e';
  }

  try {
    if (tmpFile.existsSync()) await tmpFile.delete();
  } catch (_) {}
  return out;
}

  Future<void> _requestDelete(String path,
      {bool userApproved = false}) async {
    if (path.trim().isEmpty) {
      _log('路径为空', level: LogLevel.warn);
      return;
    }
    _log('请求删除: $path  (已审批=$userApproved)');

    final script = '''
import sys, json
sys.path.insert(0, r"$_projectRoot")
try:
    from executor.policy_bridge import request_delete
    result = request_delete("ui-agent", r"$path", user_approved=$userApproved)
    print("RESULT:" + json.dumps(result, ensure_ascii=False))
except Exception as e:
    print("RESULT:" + json.dumps({"status": "error", "reason": str(e)}, ensure_ascii=False))
''';

    try {
      final out = await _runPython(script);
      final payload = _extractPayload(out);
      if (payload.isEmpty) {
        _log('执行失败: 无返回 | $out', level: LogLevel.error);
        return;
      }
      final Map<String, dynamic> r = jsonDecode(payload);
      final status = (r['status'] ?? 'error') as String;
      final reason = (r['reason'] ?? '') as String;

      switch (status) {
        case 'deleted':
          _log('已删除: $path', level: LogLevel.info);
          break;
        case 'denied':
          _log('拒绝删除: $path | $reason', level: LogLevel.critical);
          break;
        case 'need_approval':
          final ok = await _showApprovalDialog(
            path,
            reason,
            (r['severity'] ?? 'warn') as String,
          );
          if (ok) {
            await _requestDelete(path, userApproved: true);
          } else {
            _log('用户取消删除: $path', level: LogLevel.warn);
          }
          break;
        default:
          _log('错误: $reason', level: LogLevel.error);
      }
    } catch (e) {
      _log('异常: $e', level: LogLevel.error);
    }
  }

  Future<bool> _showApprovalDialog(
      String path, String reason, String severity) async {
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
            Icon(
              isCritical ? Icons.dangerous : Icons.warning_amber,
              color: isCritical ? AppTheme.danger : AppTheme.warning,
            ),
            const SizedBox(width: 8),
            Text(isCritical ? '危险操作 · 必须确认' : '高风险操作 · 需要审批'),
          ],
        ),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const Text('文件路径：',
                style: TextStyle(color: AppTheme.textDim)),
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
                path,
                style:
                    const TextStyle(fontFamily: 'monospace', fontSize: 12),
              ),
            ),
            const SizedBox(height: 12),
            Text(reason,
                style: const TextStyle(color: AppTheme.warning)),
          ],
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(ctx, false),
            child:
                const Text('取消', style: TextStyle(color: AppTheme.danger)),
          ),
          ElevatedButton(
            style:
                ElevatedButton.styleFrom(backgroundColor: AppTheme.success),
            onPressed: () => Navigator.pop(ctx, true),
            child: const Text('确认删除'),
          ),
        ],
      ),
    );
    return result == true;
  }
  
  Future<void> _ragSearch(String query) async {
    if (query.trim().isEmpty) return;
    _log('RAG 检索: $query');
    final script = '''
import sys, json
sys.path.insert(0, r"$_projectRoot")
try:
    from memory.rag import search
    print("RESULT:" + json.dumps(search(r"""$query""", top_k=3), ensure_ascii=False))
except Exception as e:
    print("RESULT:" + json.dumps({"error": str(e)}, ensure_ascii=False))
''';
    try {
      final out = await _runPython(script);
      final payload = _extractPayload(out);
      if (payload.isEmpty) {
        _log('检索失败: 无返回 | $out', level: LogLevel.error);
        return;
      }
      final dynamic decoded = jsonDecode(payload);
      if (decoded is List) {
        if (!mounted) return;
        setState(() {
          _ragResults = decoded
              .map((e) => Map<String, dynamic>.from(e as Map))
              .toList();
        });
        _log('RAG 命中 ${decoded.length} 条');
      } else {
        _log('检索返回异常: $decoded', level: LogLevel.error);
      }
    } catch (e) {
      _log('RAG 失败: $e', level: LogLevel.error);
    }
  }

  Future<void> _refreshKnowledge() async {
    final script = '''
import sys, json
sys.path.insert(0, r"$_projectRoot")
try:
    from memory.rag import list_knowledge_files
    print("RESULT:" + json.dumps(list_knowledge_files(), ensure_ascii=False))
except Exception as e:
    print("RESULT:" + json.dumps({"error": str(e)}, ensure_ascii=False))
''';
    try {
      final out = await _runPython(script);
      final payload = _extractPayload(out);
      if (payload.isEmpty) {
        if (mounted) setState(() => _knowledgeFiles = []);
        return;
      }
      final dynamic decoded = jsonDecode(payload);
      if (decoded is List && mounted) {
        setState(() {
          _knowledgeFiles = decoded
              .map((e) => Map<String, dynamic>.from(e as Map))
              .toList();
        });
      }
    } catch (e) {
      if (mounted) _log('刷新知识库失败: $e', level: LogLevel.error);
    }
  }

  Future<void> _scanKnowledge() async {
    _log('扫描知识库...');
    final script = '''
import sys, json
sys.path.insert(0, r"$_projectRoot")
try:
    from memory.rag import scan_knowledge_dir
    print("RESULT:" + json.dumps(scan_knowledge_dir(), ensure_ascii=False))
except Exception as e:
    print("RESULT:" + json.dumps({"error": str(e)}, ensure_ascii=False))
''';
    try {
      final out = await _runPython(script);
      final payload = _extractPayload(out);
      if (payload.isEmpty) {
        _log('扫描失败: 无返回 | $out', level: LogLevel.error);
        return;
      }
      final dynamic decoded = jsonDecode(payload);
      if (decoded is Map) {
        _log('已索引: ${decoded['indexed']}  总块数: ${decoded['total_chunks']}');
      } else {
        _log('扫描返回异常: $decoded', level: LogLevel.error);
      }
      await _refreshKnowledge();
    } catch (e) {
      _log('扫描失败: $e', level: LogLevel.error);
    }
  }

  Future<void> _removeKnowledge(String name) async {
    _log('删除索引: $name');
    final script = '''
import sys
sys.path.insert(0, r"$_projectRoot")
try:
    from memory.rag import remove_from_index
    print("RESULT:" + str(remove_from_index("$name")))
except Exception as e:
    print("RESULT:0")
''';
    try {
      final out = await _runPython(script);
      final payload = _extractPayload(out);
      _log('删除结果: $payload');
      await _refreshKnowledge();
    } catch (e) {
      _log('删除失败: $e', level: LogLevel.error);
    }
  }

  Future<void> _syncPeer() async {
    final ip = _peerIpCtrl.text.trim();
    if (ip.isEmpty) return;
    _log('同步记忆: $ip');
    final script = '''
import sys, json
sys.path.insert(0, r"$_projectRoot")
try:
    from sync.client import sync_both
    print("RESULT:" + json.dumps(sync_both("$ip", "agent-A"), ensure_ascii=False))
except Exception as e:
    print("RESULT:" + json.dumps({"error": str(e)}, ensure_ascii=False))
''';
    try {
      final out = await _runPython(script);
      final payload = _extractPayload(out);
      _log('同步结果: $payload');
    } catch (e) {
      _log('同步失败: $e', level: LogLevel.error);
    }
  }
  
@override
Widget build(BuildContext context) {
  return LayoutBuilder(
    builder: (ctx, constraints) {
      final isWide = constraints.maxWidth >= 900;
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
              onPressed: () {
                if (mounted) setState(() => _logs.clear());
              },
            ),
          ],
        ),
        body: isWide
            ? Row(
                children: [
                  _leftPanel(width: 380),
                  const VerticalDivider(
                      width: 1, color: AppTheme.border),
                  Expanded(child: _logPanel()),
                ],
              )
            : Column(
                children: [
                  SizedBox(height: 400, child: _leftPanel()),
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
            style:
                TextStyle(fontSize: 15, fontWeight: FontWeight.bold)),
        const SizedBox(height: 8),
        TextField(
          controller: _pathCtrl,
          style: const TextStyle(
              fontSize: 11, fontFamily: 'monospace'),
          decoration: const InputDecoration(
            labelText: '文件路径',
            border: OutlineInputBorder(),
            isDense: true,
          ),
        ),
        const SizedBox(height: 6),
        ElevatedButton.icon(
          icon: const Icon(Icons.delete_outline, size: 16),
          label: const Text('删除'),
          onPressed:
              _busy ? null : () => _requestDelete(_pathCtrl.text),
        ),
        const SizedBox(height: 14),
        const Divider(color: AppTheme.border),
        const SizedBox(height: 12),
        const Text('知识库管理',
            style:
                TextStyle(fontSize: 15, fontWeight: FontWeight.bold)),
        const SizedBox(height: 8),
        Row(
          children: [
            Expanded(
              child: ElevatedButton.icon(
                icon: const Icon(Icons.folder_open, size: 16),
                label: const Text('扫描'),
                onPressed: _scanKnowledge,
              ),
            ),
            const SizedBox(width: 6),
            IconButton(
              icon: const Icon(Icons.refresh, size: 18),
              tooltip: '刷新列表',
              onPressed: _refreshKnowledge,
            ),
          ],
        ),
        const SizedBox(height: 8),
        if (_knowledgeFiles.isEmpty)
          const Text('（knowledge/ 目录为空）',
              style:
                  TextStyle(fontSize: 11, color: AppTheme.textDim))
        else
          ..._knowledgeFiles.map((f) => Card(
                color: AppTheme.card,
                margin: const EdgeInsets.only(bottom: 4),
                child: ListTile(
                  dense: true,
                  contentPadding:
                      const EdgeInsets.symmetric(horizontal: 8),
                  title: Text((f['name'] ?? '') as String,
                      style: const TextStyle(fontSize: 12)),
                  subtitle: Text('${f['size'] ?? 0} 字节',
                      style: const TextStyle(
                          fontSize: 10, color: AppTheme.textDim)),
                  trailing: IconButton(
                    icon: const Icon(Icons.delete_sweep,
                        size: 16, color: AppTheme.danger),
                    tooltip: '删除索引',
                    onPressed: () =>
                        _removeKnowledge((f['name'] ?? '') as String),
                  ),
                ),
              )),
        const SizedBox(height: 14),
        const Divider(color: AppTheme.border),
        const SizedBox(height: 12),
        const Text('RAG 知识检索',
            style:
                TextStyle(fontSize: 15, fontWeight: FontWeight.bold)),
        const SizedBox(height: 8),
        TextField(
          controller: _queryCtrl,
          style: const TextStyle(fontSize: 12),
          decoration: const InputDecoration(
            labelText: '查询内容',
            border: OutlineInputBorder(),
            isDense: true,
          ),
          onSubmitted: (v) => _ragSearch(v),
        ),
        const SizedBox(height: 6),
        ElevatedButton.icon(
          icon: const Icon(Icons.search, size: 16),
          label: const Text('检索'),
          onPressed: () => _ragSearch(_queryCtrl.text),
        ),
        if (_ragResults.isNotEmpty) ...[
          const SizedBox(height: 8),
          ..._ragResults.map((r) => Card(
                color: AppTheme.card,
                margin: const EdgeInsets.only(bottom: 6),
                child: Padding(
                  padding: const EdgeInsets.all(8),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                          '相似度 ${r['similarity']} · ${r['source']}',
                          style: const TextStyle(
                              fontSize: 11,
                              color: AppTheme.accent)),
                      const SizedBox(height: 4),
                      Text((r['content'] ?? '') as String,
                          maxLines: 3,
                          overflow: TextOverflow.ellipsis,
                          style: const TextStyle(fontSize: 11)),
                    ],
                  ),
                ),
              )),
        ],
        const SizedBox(height: 14),
        const Divider(color: AppTheme.border),
        const SizedBox(height: 12),
        const Text('局域网同步',
            style:
                TextStyle(fontSize: 15, fontWeight: FontWeight.bold)),
        const SizedBox(height: 8),
        TextField(
          controller: _peerIpCtrl,
          style: const TextStyle(
              fontSize: 12, fontFamily: 'monospace'),
          decoration: const InputDecoration(
            labelText: '对方设备 IP',
            border: OutlineInputBorder(),
            isDense: true,
          ),
        ),
        const SizedBox(height: 6),
        ElevatedButton.icon(
          icon: const Icon(Icons.sync, size: 16),
          label: const Text('同步记忆'),
          onPressed: _syncPeer,
        ),
        const SizedBox(height: 14),
        const Divider(color: AppTheme.border),
        const SizedBox(height: 12),
        const Text('智能体列表',
            style:
                TextStyle(fontSize: 15, fontWeight: FontWeight.bold)),
        const SizedBox(height: 8),
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
      margin: const EdgeInsets.only(bottom: 10),
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(8),
        side: const BorderSide(color: AppTheme.border),
      ),
      child: Padding(
        padding: const EdgeInsets.all(10),
        child: Row(
          children: [
            Container(
              width: 8,
              height: 8,
              decoration:
                  BoxDecoration(color: color, shape: BoxShape.circle),
            ),
            const SizedBox(width: 8),
            Text(a.id,
                style: const TextStyle(
                    fontSize: 13, fontWeight: FontWeight.bold)),
            const Spacer(),
            Text(a.task,
                style: const TextStyle(
                    fontSize: 11, color: AppTheme.textDim)),
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
                style:
                    TextStyle(fontSize: 15, fontWeight: FontWeight.bold)),
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