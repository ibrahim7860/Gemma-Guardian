import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../state/mission_state.dart';

class CommandPanel extends StatefulWidget {
  const CommandPanel({super.key});

  @override
  State<CommandPanel> createState() => _CommandPanelState();
}

class _CommandPanelState extends State<CommandPanel> {
  final _controller = TextEditingController();
  String _language = "en";

  @override
  void initState() {
    super.initState();
    _controller.addListener(() => setState(() {}));
  }

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  void _onTranslate(MissionState state) {
    final raw = _controller.text.trim();
    if (raw.isEmpty) return;
    state.submitOperatorCommand(rawText: raw, language: _language);
  }

  void _onDispatch(MissionState state) {
    state.dispatchActiveCommand();
    // Clear the input only on dispatch (per spec §6.2 input retention rule).
    _controller.clear();
  }

  void _onRephrase(MissionState state) {
    state.rephraseActiveCommand();
    // Keep raw text in input — operator may want to edit and resubmit.
  }

  /// Feature B: quick-select fills the input and fires TRANSLATE so the
  /// judge sees the multilingual path light up with one click.
  void _quickFill(MissionState state, String text, String lang) {
    setState(() {
      _controller.text = text;
      _language = lang;
    });
    state.submitOperatorCommand(rawText: text, language: lang);
  }

  @override
  Widget build(BuildContext context) {
    return Consumer<MissionState>(
      builder: (_, state, _) {
        final cid = state.activeCommandId;
        final cs = cid != null ? state.commandState(cid) : null;
        final translation = cid != null ? state.commandTranslation(cid) : null;
        final connected = state.connectionStatus == "connected";
        final inputEnabled =
            cs == null ||
            cs == CommandState.failed ||
            cs == CommandState.dispatched;
        final translateEnabled =
            connected &&
            _controller.text.trim().isNotEmpty &&
            (cs == null || cs == CommandState.failed);

        return SingleChildScrollView(
          padding: const EdgeInsets.all(16),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              const Text(
                "Command",
                style: TextStyle(fontWeight: FontWeight.bold),
              ),
              const SizedBox(height: 8),
              Row(
                children: [
                  const Text("Reply in: "),
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
              // Feature B: multilingual quick-select. One-click pre-fills
              // the textbox with a representative command in the operator's
              // language so judges can see Gemma 4 E4B translate live
              // without typing. Each chip auto-fires TRANSLATE after fill.
              Wrap(
                spacing: 6,
                runSpacing: 4,
                children: [
                  _QuickCmdChip(
                    label: "EN: Recall drone 2",
                    text: "Recall drone 2 to base",
                    lang: "en",
                    onFill: (text, lang) => _quickFill(state, text, lang),
                  ),
                  _QuickCmdChip(
                    label: "ES: Llama el dron 2",
                    text: "Llama el dron 2 de regreso a la base",
                    lang: "es",
                    onFill: (text, lang) => _quickFill(state, text, lang),
                  ),
                  _QuickCmdChip(
                    label: "AR: استدع الطائرة 2",
                    text: "استدع الطائرة 2 إلى القاعدة",
                    lang: "ar",
                    onFill: (text, lang) => _quickFill(state, text, lang),
                  ),
                ],
              ),
              const SizedBox(height: 10),
              TextField(
                controller: _controller,
                enabled: inputEnabled,
                decoration: const InputDecoration(
                  border: OutlineInputBorder(),
                  hintText: "Type a command...",
                ),
              ),
              const SizedBox(height: 12),
              if (cs == CommandState.sending || cs == CommandState.translating)
                const _StatusLine(
                  text: "Translating with Gemma 4 E4B…",
                  showSpinner: true,
                ),
              if (cs == CommandState.ready && translation != null)
                _Preview(translation: translation),
              if (cs == CommandState.dispatching && translation != null) ...[
                _Preview(translation: translation),
                const SizedBox(height: 4),
                const _StatusLine(text: "Dispatching…", showSpinner: true),
              ],
              if (cs == CommandState.dispatched)
                const _StatusLine(text: "Dispatched ✓", showSpinner: false),
              if (cs == CommandState.failed)
                const _StatusLine(
                  text: "Translation failed — retry",
                  showSpinner: false,
                  error: true,
                ),
              const SizedBox(height: 12),
              Row(
                children: [
                  ElevatedButton(
                    onPressed: translateEnabled
                        ? () => _onTranslate(state)
                        : null,
                    child: const Text("TRANSLATE"),
                  ),
                  const SizedBox(width: 12),
                  if (cs == CommandState.ready)
                    Tooltip(
                      message: translation?["valid"] == true
                          ? "Send the structured command to the swarm"
                          : "Command not understood — rephrase",
                      child: ElevatedButton(
                        onPressed: translation?["valid"] == true
                            ? () => _onDispatch(state)
                            : null,
                        child: const Text("DISPATCH"),
                      ),
                    ),
                  if (cs == CommandState.dispatching)
                    const ElevatedButton(
                      onPressed: null,
                      child: Text("DISPATCHING…"),
                    ),
                  if (cs == CommandState.ready ||
                      cs == CommandState.dispatching)
                    const SizedBox(width: 12),
                  if (cs == CommandState.ready || cs == CommandState.failed)
                    OutlinedButton(
                      onPressed: () => _onRephrase(state),
                      child: const Text("REPHRASE"),
                    ),
                  if (cs == CommandState.dispatched) ...[
                    const SizedBox(width: 12),
                    OutlinedButton(
                      // "NEW COMMAND" per spec §6.2: clears the input AND
                      // resets activeCommandId so TRANSLATE re-enables. Without
                      // the rephrase call, the panel stays parked on the
                      // dispatched cid and TRANSLATE never re-enables.
                      onPressed: () {
                        _controller.clear();
                        state.rephraseActiveCommand();
                      },
                      child: const Text("NEW COMMAND"),
                    ),
                  ],
                  if (cs == null) ...[
                    const SizedBox(width: 12),
                    OutlinedButton(
                      onPressed: () => _controller.clear(),
                      child: const Text("CLEAR"),
                    ),
                  ],
                ],
              ),
            ],
          ),
        );
      },
    );
  }
}

class _StatusLine extends StatelessWidget {
  final String text;
  final bool showSpinner;
  final bool error;
  const _StatusLine({
    required this.text,
    required this.showSpinner,
    this.error = false,
  });
  @override
  Widget build(BuildContext context) {
    return Row(
      children: [
        if (showSpinner)
          const SizedBox(
            width: 16,
            height: 16,
            child: CircularProgressIndicator(strokeWidth: 2),
          ),
        if (showSpinner) const SizedBox(width: 8),
        Text(
          text,
          style: TextStyle(color: error ? Colors.red[700] : Colors.black87),
        ),
      ],
    );
  }
}

class _Preview extends StatelessWidget {
  final Map<String, dynamic> translation;
  const _Preview({required this.translation});
  @override
  Widget build(BuildContext context) {
    final preview = translation["preview_text"] ?? "";
    final localPreview = translation["preview_text_in_operator_language"] ?? "";
    final valid = translation["valid"] == true;
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(8),
      decoration: BoxDecoration(
        border: Border.all(
          color: valid ? Colors.green[700]! : Colors.orange[700]!,
        ),
        borderRadius: BorderRadius.circular(4),
        color: (valid ? Colors.green : Colors.orange).withValues(alpha: 0.05),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(preview, style: const TextStyle(fontWeight: FontWeight.w600)),
          if (localPreview != preview) ...[
            const SizedBox(height: 4),
            Text(
              localPreview,
              style: const TextStyle(fontStyle: FontStyle.italic),
            ),
          ],
        ],
      ),
    );
  }
}

/// Feature B: one-click multilingual command chip. Pre-fills the operator
/// input with a representative phrase in the chip's language and fires
/// TRANSLATE so the Gemma 4 E4B path lights up for the judge instantly.
class _QuickCmdChip extends StatelessWidget {
  final String label;
  final String text;
  final String lang;
  final void Function(String text, String lang) onFill;
  const _QuickCmdChip({
    required this.label,
    required this.text,
    required this.lang,
    required this.onFill,
  });
  @override
  Widget build(BuildContext context) {
    return Material(
      color: const Color(0xFF0E1117),
      borderRadius: BorderRadius.circular(14),
      child: InkWell(
        borderRadius: BorderRadius.circular(14),
        onTap: () => onFill(text, lang),
        child: Container(
          padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 5),
          decoration: BoxDecoration(
            borderRadius: BorderRadius.circular(14),
            border: Border.all(color: const Color(0xFF7AD9C8), width: 0.8),
          ),
          child: Text(
            label,
            style: const TextStyle(
              color: Color(0xFF7AD9C8),
              fontSize: 11,
              fontWeight: FontWeight.w700,
            ),
          ),
        ),
      ),
    );
  }
}
