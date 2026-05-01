import 'package:flutter/material.dart';

class CommandPanel extends StatefulWidget {
  const CommandPanel({super.key});

  @override
  State<CommandPanel> createState() => _CommandPanelState();
}

class _CommandPanelState extends State<CommandPanel> {
  final _controller = TextEditingController();
  String _language = "en";

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.all(16),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Text("Command", style: TextStyle(fontWeight: FontWeight.bold)),
          const SizedBox(height: 8),
          Row(
            children: [
              const Text("Language: "),
              const SizedBox(width: 8),
              DropdownButton<String>(
                value: _language,
                items: const [
                  DropdownMenuItem(value: "en", child: Text("English")),
                  DropdownMenuItem(value: "es", child: Text("Spanish")),
                  DropdownMenuItem(value: "ar", child: Text("Arabic")),
                ],
                onChanged: (v) => setState(() => _language = v ?? "en"),
              ),
            ],
          ),
          const SizedBox(height: 12),
          TextField(
            controller: _controller,
            decoration: const InputDecoration(
              border: OutlineInputBorder(),
              hintText: "Type a command...",
            ),
          ),
          const SizedBox(height: 12),
          Row(
            children: [
              ElevatedButton(
                onPressed: () {
                  // Phase 3 wires this to the WebSocket; Phase 1B is a stub.
                  ScaffoldMessenger.of(context).showSnackBar(
                    const SnackBar(content: Text("Phase 3 will dispatch this to the EGS")),
                  );
                },
                child: const Text("DISPATCH"),
              ),
              const SizedBox(width: 12),
              OutlinedButton(
                onPressed: () => _controller.clear(),
                child: const Text("CLEAR"),
              ),
            ],
          ),
        ],
      ),
    );
  }
}
