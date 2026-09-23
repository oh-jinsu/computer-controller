# Mac Bridge development

- This is ONE standalone repository. `scene_bridge` is its internal video module; never reintroduce an external Scene Bridge installation requirement.
- Read live code and Git state before changing it. Preserve local modifications and user files; do not reset worktrees or overwrite local configuration.
- Never commit `.state`, `.runtime`, `.venv`, `.env`, `input` media, `output` frames, screenshots, logs, API keys or Keychain contents.
- Respect the owner-selected persisted approval mode: ask (default) or always (explicit local CLI choice, no expiry/task scopes). Keep backup/audit/pause/path/PID guardrails in both modes. Do not add per-call MCP consent flags or environment-variable overrides. The mode is not authorization for unrelated actions; do not mislabel mutations as read-only. Preserve owner settings during updates.
- File path checks are guardrails, not a sandbox for approved shell commands. Do not describe them as complete isolation.
- Preserve the existing tunnel ID on migration. Never execute a command loaded from old settings. Keep the venv interpreter path intact; do not resolve its symlink to the system Python.
- Stop old stdio clients before starting a replacement for the same tunnel ID. Do not kill arbitrary user processes.
- Show actual image results only. Generated images, synthetic test frames and a file save are not proof that real Mac capture or rendering was tested.
- Run `python -m unittest discover -s tests -p 'test_*.py' -v`. Real MCP smoke tests are separate processes (`tests/smoke_mac_mcp.py`, `tests/smoke_mcp.py`, `tests/smoke_approval_mcp.py`, `tests/smoke_browser_mcp.py`) and need installed dependencies.
- Record exactly which tests ran. Separate mocked unit tests, real FFmpeg, actual MCP integration, native macOS approval/capture, YouTube access, and ChatGPT tunnel tests.
- Keep launch/update instructions short: first clone and start, then stop / `git pull --ff-only` / start. Do not add a new service or plugin per feature.

- Browser operations use a dedicated profile, never normal Chrome sessions. Keep the child MCP in its single actor task, and close it on pause/shutdown. Never expose arbitrary evaluate/run-code, upload paths or per-call consent flags.
- mac_context summaries are explicit untrusted handoffs, not the entire chat history; preserve expected revisions and old versions, and keep all summaries/profiles out of Git.
