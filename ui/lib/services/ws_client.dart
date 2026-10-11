/// WebSocket 客户端（自动重连 + 本地缓存）
import 'dart:async';
import 'dart:convert';
import 'package:web_socket_channel/web_socket_channel.dart';
import 'package:shared_preferences/shared_preferences.dart';

class WSClient {
  final String url;
  WebSocketChannel? _channel;
  StreamController<Map<String, dynamic>> _controller =
      StreamController<Map<String, dynamic>>.broadcast();
  Timer? _reconnectTimer;
  bool _manualClose = false;
  int _retryCount = 0;

  WSClient(this.url);

  Stream<Map<String, dynamic>> get stream => _controller.stream;

  Future<void> connect() async {
    _manualClose = false;
    try {
      _channel = WebSocketChannel.connect(Uri.parse(url));
      _retryCount = 0;

      _channel!.stream.listen(
        (data) {
          try {
            final msg = jsonDecode(data);
            _controller.add(msg);
            _cacheLastMessage(msg);
          } catch (_) {}
        },
        onDone: _scheduleReconnect,
        onError: (_) => _scheduleReconnect(),
      );
    } catch (e) {
      _scheduleReconnect();
    }
  }

  void _scheduleReconnect() {
    if (_manualClose) return;
    _retryCount++;
    final delay = Duration(seconds: [1, 2, 4, 8, 16][_retryCount.clamp(0, 4)]);
    _reconnectTimer?.cancel();
    _reconnectTimer = Timer(delay, connect);
  }

  void send(Map<String, dynamic> msg) {
    _channel?.sink.add(jsonEncode(msg));
  }

  void close() {
    _manualClose = true;
    _reconnectTimer?.cancel();
    _channel?.sink.close();
  }

  Future<void> _cacheLastMessage(Map<String, dynamic> msg) async {
    try {
      final prefs = await SharedPreferences.getInstance();
      await prefs.setString('last_msg', jsonEncode(msg));
    } catch (_) {}
  }

  Future<Map<String, dynamic>?> getLastMessage() async {
    try {
      final prefs = await SharedPreferences.getInstance();
      final raw = prefs.getString('last_msg');
      if (raw != null) return jsonDecode(raw);
    } catch (_) {}
    return null;
  }
}