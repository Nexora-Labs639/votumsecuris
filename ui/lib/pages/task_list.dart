import 'package:flutter/material.dart';

class TaskListPage extends StatelessWidget {
  final List<Map<String, dynamic>> tasks;
  final VoidCallback onRefresh;
  final Function(String taskId, bool approved) onApprove;

  const TaskListPage({
    super.key,
    required this.tasks,
    required this.onRefresh,
    required this.onApprove,
  });

  Color _statusColor(String status) {
    switch (status) {
      case 'running':
        return Colors.green;
      case 'done':
        return Colors.blue;
      case 'failed':
        return Colors.red;
      case 'need_approval':
        return Colors.orange;
      default:
        return Colors.grey;
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('任务列表'),
        actions: [
          IconButton(icon: const Icon(Icons.refresh), onPressed: onRefresh),
        ],
      ),
      body: tasks.isEmpty
          ? const Center(child: Text('暂无任务'))
          : ListView.builder(
              itemCount: tasks.length,
              itemBuilder: (ctx, i) {
                final t = tasks[i];
                final status = t['status'] ?? 'pending';
                return Card(
                  margin: const EdgeInsets.all(8),
                  child: ListTile(
                    leading: CircleAvatar(
                      backgroundColor: _statusColor(status),
                      child: const Icon(Icons.task, color: Colors.white),
                    ),
                    title: Text(t['content'] ?? ''),
                    subtitle: Text('状态: $status\\\\nID: ${t['id'] ?? ''}'),
                    isThreeLine: true,
                  ),
                );
              },
            ),
    );
  }
}