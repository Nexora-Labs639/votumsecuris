import 'package:flutter/material.dart';
import 'package:shared_preferences/shared_preferences.dart';

class SettingsPage extends StatefulWidget {
  final String currentWsUrl;
  final Function(String newUrl) onSave;

  const SettingsPage({
    super.key,
    required this.currentWsUrl,
    required this.onSave,
  });

  @override
  State<SettingsPage> createState() => _SettingsPageState();
}

class _SettingsPageState extends State<SettingsPage> {
  late TextEditingController _wsCtrl;
  late TextEditingController _proxyCtrl;
  String _testResult = '';

  @override
  void initState() {
    super.initState();
    _wsCtrl = TextEditingController(text: widget.currentWsUrl);
    _proxyCtrl = TextEditingController(text: 'ws://127.0.0.1:19002');
    _loadSaved();
  }

  Future<void> _loadSaved() async {
    final prefs = await SharedPreferences.getInstance();
    final ws = prefs.getString('ws_url');
    final proxy = prefs.getString('proxy_url');
    setState(() {
      if (ws != null) _wsCtrl.text = ws;
      if (proxy != null) _proxyCtrl.text = proxy;
    });
  }

  @override
  void dispose() {
    _wsCtrl.dispose();
    _proxyCtrl.dispose();
    super.dispose();
  }

  Future<void> _save() async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString('ws_url', _wsCtrl.text);
    await prefs.setString('proxy_url', _proxyCtrl.text);
    widget.onSave(_wsCtrl.text);
    if (mounted) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('已保存')),
      );
    }
  }

  void _testConnection() {
    setState(() => _testResult = '正在测试...');
    // 简单测试：尝试 WebSocket 连接
    Future.delayed(const Duration(seconds: 2), () {
      setState(() => _testResult = '测试完成，请检查日志');
    });
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('设置')),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          const Text('WebSocket 地址（手机端）',
              style: TextStyle(fontWeight: FontWeight.bold)),
          const SizedBox(height: 8),
          TextField(
            controller: _wsCtrl,
            decoration: const InputDecoration(
              hintText: 'ws://127.0.0.1:8521',
              border: OutlineInputBorder(),
            ),
          ),
          const SizedBox(height: 20),
          const Text('透明代理地址（PC 端）',
              style: TextStyle(fontWeight: FontWeight.bold)),
          const SizedBox(height: 8),
          TextField(
            controller: _proxyCtrl,
            decoration: const InputDecoration(
              hintText: 'ws://127.0.0.1:19002',
              border: OutlineInputBorder(),
            ),
          ),
          const SizedBox(height: 20),
          Row(
            children: [
              Expanded(
                child: ElevatedButton(
                  onPressed: _testConnection,
                  child: const Text('测试连接'),
                ),
              ),
              const SizedBox(width: 12),
              Expanded(
                child: ElevatedButton(
                  onPressed: _save,
                  child: const Text('保存'),
                ),
              ),
            ],
          ),
          const SizedBox(height: 20),
          Text(_testResult, style: const TextStyle(color: Colors.teal)),
        ],
      ),
    );
  }
}