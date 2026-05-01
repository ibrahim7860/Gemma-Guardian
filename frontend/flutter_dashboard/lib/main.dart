import 'dart:async';

import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import 'package:web_socket_channel/web_socket_channel.dart';

import 'generated/contract_version.dart' as gen;
import 'generated/topics.dart';
import 'state/mission_state.dart';
import 'widgets/command_panel.dart';
import 'widgets/drone_status_panel.dart';
import 'widgets/findings_panel.dart';
import 'widgets/map_panel.dart';

void main() {
  runApp(const FieldAgentDashboard());
}

class FieldAgentDashboard extends StatelessWidget {
  const FieldAgentDashboard({super.key});

  @override
  Widget build(BuildContext context) {
    return ChangeNotifierProvider(
      create: (_) => MissionState(),
      child: MaterialApp(
        title: "FieldAgent Operator Dashboard",
        theme: ThemeData(useMaterial3: true, colorSchemeSeed: Colors.indigo),
        home: const _DashboardShell(),
      ),
    );
  }
}

class _DashboardShell extends StatefulWidget {
  const _DashboardShell();

  @override
  State<_DashboardShell> createState() => _DashboardShellState();
}

class _DashboardShellState extends State<_DashboardShell> {
  WebSocketChannel? _channel;
  StreamSubscription? _sub;
  Duration _backoff = const Duration(seconds: 1);
  Timer? _retryTimer;
  bool _disposed = false;

  @override
  void initState() {
    super.initState();
    _connect();
  }

  void _connect() {
    if (_disposed) return;
    final mission = context.read<MissionState>();
    mission.setConnectionStatus("connecting");
    try {
      _channel = WebSocketChannel.connect(Uri.parse(Channels.wsEndpoint));
      _sub = _channel!.stream.listen(
        (frame) {
          mission.setConnectionStatus("connected");
          _backoff = const Duration(seconds: 1);
          if (frame is String) {
            mission.applyRawFrame(frame);
          }
        },
        onError: (e) => _scheduleReconnect(),
        onDone: _scheduleReconnect,
        cancelOnError: true,
      );
    } catch (_) {
      _scheduleReconnect();
    }
  }

  void _scheduleReconnect() {
    if (_disposed) return;
    final mission = context.read<MissionState>();
    mission.setConnectionStatus("reconnecting in ${_backoff.inSeconds}s");
    _sub?.cancel();
    _channel?.sink.close();
    _retryTimer?.cancel();
    _retryTimer = Timer(_backoff, _connect);
    final next = _backoff.inSeconds * 2;
    _backoff = Duration(seconds: next > 10 ? 10 : next);
  }

  @override
  void dispose() {
    _disposed = true;
    _retryTimer?.cancel();
    _sub?.cancel();
    _channel?.sink.close();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text("FieldAgent — Operator Dashboard"),
        actions: [
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: 12),
            child: Center(
              child: Consumer<MissionState>(
                builder: (_, m, __) => Text(
                  "v${gen.contractVersion} · ${m.connectionStatus}",
                  style: const TextStyle(fontSize: 12),
                ),
              ),
            ),
          ),
        ],
      ),
      body: const _FourPanelGrid(),
    );
  }
}

class _FourPanelGrid extends StatelessWidget {
  const _FourPanelGrid();

  @override
  Widget build(BuildContext context) {
    return LayoutBuilder(
      builder: (_, c) {
        final w = c.maxWidth / 2;
        final h = c.maxHeight / 2;
        return Column(
          children: [
            Row(children: [
              SizedBox(width: w, height: h, child: const _Panel(child: MapPanel(), title: "Map")),
              SizedBox(width: w, height: h, child: const _Panel(child: DroneStatusPanel(), title: "Drone Status")),
            ]),
            Row(children: [
              SizedBox(width: w, height: h, child: const _Panel(child: FindingsPanel(), title: "Findings")),
              SizedBox(width: w, height: h, child: const _Panel(child: CommandPanel(), title: "Command")),
            ]),
          ],
        );
      },
    );
  }
}

class _Panel extends StatelessWidget {
  final Widget child;
  final String title;
  const _Panel({required this.child, required this.title});
  @override
  Widget build(BuildContext context) {
    return Card(
      margin: const EdgeInsets.all(6),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Container(
            color: Theme.of(context).colorScheme.surfaceContainerHighest,
            padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
            child: Text(title,
                style: Theme.of(context).textTheme.titleSmall?.copyWith(fontWeight: FontWeight.bold)),
          ),
          Expanded(child: child),
        ],
      ),
    );
  }
}
