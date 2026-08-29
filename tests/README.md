# V1 Testing Strategy

The first implementation should be testable without a live messaging provider.

## Required tests

- CSV header validation
- CSV row normalization
- duplicate detection
- phone/email validation
- lead score calculation
- SQLite initialization and persistence
- daily limit enforcement
- duplicate outreach protection
- AI JSON schema validation
- malformed AI response handling
- Ollama timeout/unavailable handling
- dry-run never invokes real delivery
- only approved messages can enter the send path
- provider failure is recorded without corrupting other leads
- do-not-contact leads cannot be sent

Use mocks/fakes for Ollama and messaging providers so tests remain deterministic and offline.
