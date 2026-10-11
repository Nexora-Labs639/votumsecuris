import 'package:flutter/material.dart';

class ApprovalDialog extends StatelessWidget {
  final Map<String, dynamic> payload;
  final Function(bool approved) onResult;

  const ApprovalDialog({
    super.key,
    required this.payload,
    required this.onResult,
  });

  @override
  Widget build(BuildContext context) {
    final tool = payload['tool'] ?? '';
    final params = payload['params'] ?? {};
    final reason = payload['reason'] ?? '';

    return AlertDialog(
      title: const Row(
        children: [
          Icon(Icons.warning, color: Colors.orange),
          SizedBox(width: 8),
          Text('高风险操作'),
        ],
      ),
      content: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text('工具: $tool'),
          const SizedBox(height: 8),
          Text('参数: $params'),
          const SizedBox(height: 8),
          Text('原因: $reason', style: const TextStyle(color: Colors.orange)),
        ],
      ),
      actions: [
        TextButton(
          onPressed: () => onResult(false),
          child: const Text('拒绝', style: TextStyle(color: Colors.red)),
        ),
        ElevatedButton(
          onPressed: () => onResult(true),
          child: const Text('允许'),
        ),
      ],
    );
  }
}