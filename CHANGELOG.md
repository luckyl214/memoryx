# Changelog

## [1.1.0] - 2026-05-22
### Added
- Bidirectional memory migration: 10 adapters (tencentdb, holographic, hermes, mem0, hindsight, letta, zep, cognee, gbrain, json)
- `restore()` — export memories from memoryx to any supported system
- ModuleRegistry + SystemOrchestrator for lifecycle management
- PalaceEngine (Wing→Room→Drawer hierarchical storage)
- SymbolicIndex (AAAK-style compression)
- MCPServer (6 MCP tools)
- release-check.py + pre-commit hook for security

### Fixed
- Subscriber isolation in EventBus worker loop
- .env.example absolute path → relative placeholder
- deploy scripts hardcoded paths → relative SCRIPT_DIR

## [1.0.0] - 2026-05-22
### Added
- Initial release
- 5-tier automatic hierarchical memory
- Event-driven Hook Layer with DLQ, priority queue, trace_id
- 6-channel hybrid retrieval with intent-aware weighting
- Cross-memory LLM synthesis (ReflectEngine)
- Self-healing engine
- Resource governance for 2C4G VPS
- 33-phase development architecture
