# {{LAB_TITLE}}

{{LAB_MISSION}}

Начните с [START_HERE.md](START_HERE.md).
Самостоятельная лаборатория; область: {{LAB_AREAS}}.
Создана {{LAB_CREATED_DATE}} из шаблона {{LAB_TEMPLATE_VERSION}}.

Исходные события и версии: `research/archive/`.
Производная навигация: `knowledge/` и `research/views/`.
История методов: `methods/` и связанные события архива.
Первичные входы: `00_INBOX_TO_ANALYZE/`; не загружайте их все автоматически.

Данные открыты: JSON, UTF-8 Markdown и объекты SHA-256. Для работы достаточно
Python 3.9+ и обычного чтения файлов. Облачный сервис и старый UI не требуются.

<!-- claude-terminal-default:v1 -->
## Optional Claude workflow

The local switch is `config/integrations.json`; Claude is disabled by default.
An explicit request to use Claude lets Codex configure the adapter and prepare
that work. Follow `workflows/claude_terminal_protocol.md` for launch, resume and
collection. Preserve a bound session's original runner and sealed inputs.
Installation alone starts no research, retries no quota and authorizes no
private disclosure or paid usage change.

When discussing this workflow, name the executor of the next step: **Codex** or
**Claude**. Keep the two closing status lines short; say that no run is needed
when appropriate.
<!-- /claude-terminal-default:v1 -->
