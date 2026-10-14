import 'package:flutter/material.dart';
import 'services/ws_client.dart';
import 'pages/task_list.dart';
import 'pages/new_task.dart';
import 'pages/approval.dart';
import 'pages/settings.dart';

void main() {
  runApp(const VotumApp());
}

class VotumApp extends StatelessWidget {
  const VotumApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'VotumSecuris',
      debugShowCheckedModeBanner: false,
      theme: ThemeData(
        brightness: Brightness.dark,
        primarySwatch: Colors.teal,
        scaffoldBackgroundColor: const Color(0xFF0D1117),
        useMaterial3: true,
      ),
      home: const HomePage(),
    );
  }
}

class HomePage extends StatefulWidget {
  const HomePage({super.key});

  @override
  State<HomePage> createState() => _HomePageState();
}

class _HomePageState extends State<HomePage> {
  late WSClient _client;
  String _wsUrl = 'ws://127.0.0.1:8521';
  final List<Map<String, dynamic>> _tasks = [];
  final List<String> _logs = [];
  Map<String, dynamic>? _pendingApproval;
  int _tabIndex = 0;

  @override
  void initState() {
    super.initState();
    _client = WSClient(_wsUrl);
    _client.stream.listen(_onMessage);
    _client.connect();
  }

  @override
  void dispose() {
    _client.close();
    super.dispose();
  }

  void _onMessage(Map<String, dynamic> msg) {
    final type = msg['type'];
    final payload = msg['payload'] ?? {};

    if (!mounted) return;
    setState(() {
      if (type == 'task_list') {
        _tasks.clear();
        _tasks.addAll((payload['tasks'] as List).cast<Map<String, dynamic>>());
      } else if (type == 'task_update') {
        final idx = _tasks.indexWhere((t) => t['id'] == payload['id']);
        if (idx >= 0) {
          _tasks[idx] = Map<String, dynamic>.from(payload);
        } else {
          _tasks.add(Map<String, dynamic>.from(payload));
        }
      } else if (type == 'log') {
        _logs.add(payload['text']?.toString() ?? '');
      } else if (type == 'approval_request') {
        _pendingApproval = Map<String, dynamic>.from(payload);
        _showApproval();
      } else if (type == 'chat_reply') {
        _logs.add('回复: ${payload['reply']}');
      }
    });
  }

  void _showApproval() {
    if (_pendingApproval == null) return;
    showDialog(
      context: context,
      barrierDismissible: false,
      builder: (ctx) => ApprovalDialog(
        payload: _pendingApproval!,
        onResult: (approved) {
          Navigator.pop(ctx);
          final id = _pendingApproval?['approval_id'];
          if (id != null) {
            _client.send({
              'type': approved ? 'approve' : 'reject',
              'payload': {'approval_id': id},
            });
          }
          setState(() => _pendingApproval = null);
        },
      ),
    );
  }

  void _sendTask(String content) {
    _client.send({
      'type': 'chat',
      'payload': {'text': content},
    });
    setState(() => _logs.add('发送: $content'));
  }

  void _refresh() {
    _client.send({'type': 'query_tasks', 'payload': {}});
  }

  void _updateWsUrl(String newUrl) {
    _client.close();
    _wsUrl = newUrl;
    _client = WSClient(_wsUrl);
    _client.stream.listen(_onMessage);
    _client.connect();
  }

  @override
  Widget build(BuildContext context) {
    return LayoutBuilder(
      builder: (ctx, constraints) {
        final isWide = constraints.maxWidth >= 900;
        if (isWide) {
          return _desktopLayout();
        }
        return _mobileLayout();
      },
    );
  }

  Widget _mobileLayout() {
    return Scaffold(
      body: IndexedStack(
        index: _tabIndex,
        children: [
          TaskListPage(tasks: _tasks, onRefresh: _refresh, onApprove: (_, __) {}),
          NewTaskPage(onSubmit: _sendTask),
          _logPage(),
          SettingsPage(currentWsUrl: _wsUrl, onSave: _updateWsUrl),
        ],
      ),
      bottomNavigationBar: BottomNavigationBar(
        currentIndex: _tabIndex,
        onTap: (i) => setState(() => _tabIndex = i),
        items: const [
          BottomNavigationBarItem(icon: Icon(Icons.list), label: '任务'),
          BottomNavigationBarItem(icon: Icon(Icons.add), label: '发任务'),
          BottomNavigationBarItem(icon: Icon(Icons.terminal), label: '日志'),
          BottomNavigationBarItem(icon: Icon(Icons.settings), label: '设置'),
        ],
      ),
    );
  }

  Widget _desktopLayout() {
    return Scaffold(
      body: Row(
        children: [
          // 左栏：任务列表
          SizedBox(
            width: 320,
            child: TaskListPage(tasks: _tasks, onRefresh: _refresh, onApprove: (_, __) {}),
          ),
          const VerticalDivider(width: 1),
          // 中栏：发任务
          Expanded(
            flex: 2,
            child: NewTaskPage(onSubmit: _sendTask),
          ),
          const VerticalDivider(width: 1),
          // 右栏：日志
          Expanded(
            flex: 3,
            child: _logPage(),
          ),
          const VerticalDivider(width: 1),
          // 最右：设置
          SizedBox(
            width: 300,
            child: SettingsPage(currentWsUrl: _wsUrl, onSave: _updateWsUrl),
          ),
        ],
      ),
    );
  }

  Widget _logPage() {
    return Scaffold(
      appBar: AppBar(title: const Text('实时日志')),
      body: ListView.builder(
        itemCount: _logs.length,
        itemBuilder: (ctx, i) => Padding(
          padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 4),
          child: Text(
            _logs[i],
            style: const TextStyle(fontFamily: 'monospace', fontSize: 12),
          ),
        ),
      ),
    );
  }
}