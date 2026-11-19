# iterm2-utils

Выборочная **omp-only** интеграция iTerm2 для macOS + zsh, Python **3.11+**.
Обычная вкладка — shell; запуск omp требует явного запроса. Версия агента —
диагностика, не точный pin: нужны возможности выбранной операции.
[Границы совместимости и live-проверок](docs/compatibility.md).

## Быстрый старт

> Настрой мне iTerm2 из https://github.com/YarikMix/iterm2-utils. Прочитай
> skills/iterm2-setup/SKILL.md, уточни только недостающие функции и omp profile,
> покажи план и настрой только выбранное. Ручные шаги и непроверенное перечисли.

Skill можно читать прямо из checkout. Отдельное копирование для последующего
обнаружения не разрешает менять настройки и не включает функции:

```sh
git clone https://github.com/YarikMix/iterm2-utils.git
cd iterm2-utils
python3 --version  # >=3.11
python3 -m iterm2_utils bootstrap-skill --skill iterm2-launch --omp-profile work --dry-run --json
python3 -m iterm2_utils bootstrap-skill --skill iterm2-launch --omp-profile work --json
```

Три независимых bundle: [iterm2-setup](skills/iterm2-setup/SKILL.md) (по умолчанию),
[iterm2-launch](skills/iterm2-launch/SKILL.md),
[iterm2-projects](skills/iterm2-projects/SKILL.md). Каждый копирует только свои
файлы с отдельным receipt. Личные дополнительные файлы сохраняются; изменённые
owned/чужие файлы и symlinks вызывают conflict, не перезаписываются. Повторите
bootstrap после обновления checkout; обнаружение текущей сессии может требовать
refresh. Bootstrap не проверяет SDK/агента и не разворачивает другие зависимости.

`--omp-profile` необязателен: явное значение, затем `OMP_PROFILE`, затем
`PI_PROFILE`. Используется общий native resolver с `PI_CONFIG_DIR` и default-only
`PI_CODING_AGENT_DIR`, а не отдельное соглашение путей. Назначение bundle —
`resolved agent_dir/skills/BUNDLE`. Omp storage profile и iTerm parent/profile —
разные сущности. Не переключайте существующее ownership на другой профиль молча.

## Явный выбор функций

```sh
python3 -m iterm2_utils doctor --json
python3 -m iterm2_utils plan --features status,notifications --omp-profile work --json
python3 -m iterm2_utils install --features status,notifications --omp-profile work --dry-run --json
python3 -m iterm2_utils install --features status,notifications --omp-profile work --json
python3 -m iterm2_utils doctor --json
```

Install меняет реальные выбранные настройки: нужна авторизация именно этих
изменений. Plan/dry-run не применяют изменения. Пустые/неизвестные функции
отклоняются; `--agent`, старые команды/aliases и автоматическая миграция отсутствуют.

| Функция | Граница |
| --- | --- |
| `status` | Native OSC7501 / `terminal.programStatus`, без второго writer |
| `notifications` | Native OSC9 / completion-on, error-off; `--notify-errors` явно |
| `restore` | Native picker и exact-file resume, не latest/restore fallback |
| `clipboard` | Terminal selection + Cmd+C, только выбранный CopySelection |
| `shortcuts` | Явный `--shortcuts CSV`, resume требует `--resume-key`; Ctrl+Q native |
| `mcp` | Один owned server в omp `mcp.json`, чужие server/root keys сохраняются |
| `shell` | Штатная zsh интеграция без перехвата agent command |
| `appearance` | Правила/иконки, cd/reset, main identity + TTY/foreground guards |
| `project-launcher` | Стабильные GUID, shell-кнопки, не неявный запуск omp |

Подробные зависимости/JSON: [features](skills/iterm2-setup/references/features.md).
Appearance впервые требует `--appearance-config ABS_JSON`, launcher —
`--project-launcher-config ABS_JSON`, только вместе с выбранной функцией.
`--parent-profile NAME` выбирает существующий обычный родительский профиль.
Позднее update читает owned копии без исходных JSON/PNG. Личные roots/имена и
содержимое конфигов не публикуйте. [Appearance](docs/repo-appearance.md),
[launcher](docs/project-launcher.md), [notices](THIRD_PARTY_NOTICES.md).

Недостающая capability блокирует свою функцию, не обычный shell. Native
OSC/banner/keyboard/effective settings нельзя считать проверенными по версии,
успешной записи или API connectivity. Нет fallback на hooks/daemon. MCP optional:
`uvx --with 'mcp<2' mcp-server-iterm2==0.1.1`, серверный Python >=3.12 отдельно.
Другие MCP servers и настройки/model/credentials/approval mode сохраняются.
Неизвестный OSC receiver остаётся `pending_ui`: выбранные native настройки можно
подготовить, но это не подтверждает доставку. `it2 --help` не является контрактом
рекламы OSC и не запускается для такой проверки.

## Открытие одной вкладки

Выберите доступный Python3.11+ с официальным SDK `iterm2` и сохраните абсолютный
`sys.executable` без разрешения symlink virtualenv в другой интерпретатор:

```sh
launch_python="$(python3 -c 'import os, sys; p = sys.executable; assert os.path.isabs(p); print(p)')" &&
"$launch_python" -c 'import sys; assert sys.version_info >= (3, 11); import iterm2; print(sys.executable)' &&
"$launch_python" -m iterm2_utils launch-omp --help
```

Каждая внешняя проверка до 10 секунд. Ошибка/отказ API блокирует операцию без
автоустановки SDK, изменения разрешений или обхода другим API. Сохранённый Python
передавайте заново между tool calls; при смене контекста проверяйте тем же Python.

Ровно один режим на запрос (значения — отдельные argv либо корректно quoted):

```sh
"$launch_python" -m iterm2_utils launch-omp --mode shell --window ID --profile NAME --cwd ABS --json
"$launch_python" -m iterm2_utils launch-omp --mode new --window ID --profile iterm2-utils:omp --cwd ABS --omp-profile work --json
"$launch_python" -m iterm2_utils launch-omp --mode handoff --window ID --profile iterm2-utils:omp --cwd ABS --handoff ABS_FILE --omp-profile work --json
"$launch_python" -m iterm2_utils launch-omp --mode resume --window ID --profile iterm2-utils:omp --cwd ABS --resume-file ABS_JSONL --resume-id UUID --omp-profile work --json
```

Для shell используйте обычный login-shell профиль: никакой команды/проверки omp,
Bun, handoff или ack. Omp выбирает dedicated `iterm2-utils:omp` без startup command.
Окно: явный ID, согласованная привязка родителя, иначе единственное окно полного
инвентаря; неоднозначность требует выбора, не фокуса/названия/recency. Перед create
цель/GUID перепроверяются. Нет автоматической подмены исчезнувшего окна.

Новая/handoff сессия использует приватный последний overlay `autoResume:false`,
сохраняя постоянные настройки и размещение истории. Поддержанные literal wrapper
options сохраняются; непрозрачные wrappers блокируются без исполнения. Для задачи
используйте `prepare_handoff(Path(canonical_cwd), task_text)` и уникальные приватные
handoff/отсутствующий ack: [формат](skills/iterm2-launch/references/handoff.md).
Exact resume требует header ID/file/cwd и provenance выбранного omp profile;
missing/changed history не превращается в fresh. [Resume/continuation](skills/iterm2-launch/references/resume.md).

SDK создаёт одну вкладку с полной командой при создании, без terminal typing.
Create+command proof до 30 секунд; handoff ack отдельно до 120. `blocked`/2 — до
создания; `created_unverified` или `unknown`/3 сохраняют известные IDs; `launched`/0
доказывает точную команду/вкладку/профиль, не выполнение задачи. `already_open`/0
возвращает текущий адрес подтверждённого live диалога без создания; дубликат только
по явному `--allow-duplicate` для resume. Никогда не retry/resend/close после
неопределённости. `command`, `identity`, `history`, `ack` независимы; `session_id`
означает iTerm terminal ID. Без history: «команда resume запущена, восстановление
истории не подтверждено». Полный контракт: [omp-launch](docs/omp-launch.md),
[identity](docs/omp-identity.md). Raw argv/prompts/screens/settings не печатаются.

## Обслуживание и ручная проверка

```sh
python3 -m iterm2_utils migrate-omp --dry-run --json
python3 -m iterm2_utils migrate-omp --apply --json
python3 -m iterm2_utils update --dry-run --json
python3 -m iterm2_utils update --json
python3 -m iterm2_utils uninstall --features clipboard --dry-run --json
python3 -m iterm2_utils uninstall --features clipboard --json
```

Миграция по умолчанию preview; `--restore-external` — отдельный видимый opt-in
реактивации доказанной прежней внешней интеграции. Обычные install/update на
историческом receipt требуют явной миграции, не запускают старых агентов.
Ownership/CAS/journal recovery сохраняют changed/foreign записи, inverses,
referenced GUIDs и runtime уже работающих shell. Незавершённая cleanup/source
intent остаётся pending, не считается «полностью очищено». Update/uninstall
сохраняют recorded profile; удаляют только unchanged owned значения, не директории,
историю или whole-config backup. Открытые пользовательские сессии не закрываются.

После install читайте findings/ui. `ready` в плане — не live acceptance. Для
реального pending code: `reconcile --step CODE --json`, затем `doctor --live --json`.
Слова «готово» и installed UI binary не доказывают доступ/проверку. Отсутствие или
отказ UI — ручные шаги, не альтернативная автоматизация; системные диалоги только
человеком. [UI reference](skills/iterm2-setup/references/ui.md),
[maintenance](skills/iterm2-setup/references/troubleshooting.md).

Структурная валидация, isolated fixture tests и agent decision scenarios — три
разных вида evidence, не разрешённая установка или настоящая GUI/TTY приёмка.
Omp live acceptance не заявлена; старые validation документы исторические.

### Явный переход исторической установки на omp

API миграции: `preview_omp_migration(context, runner, restore_external=False)` и
`migrate_to_omp(context, runner, dry_run=True, restore_external=False)`.
Preview не восстанавливает journal, не создаёт lock и не меняет файлы. Apply
сначала восстанавливает journals feature receipt и **всех трёх** независимых skill
receipts, затем повторно проверяет fingerprint receipts и затронутых адресов под
transaction locks. Codex/Claude для этого не нужны и не запускаются.

Удаляются/возвращаются только точные owned settings, отдельные hooks, zsh-блоки,
MCP server addresses и файлы навыков при совпадении с installed. Foreign neighbours,
изменённые значения и неоднозначные hooks сохраняются. Нормализованная историческая
MCP registration без receipted storage address — **conflict**, не разрешение угадать
CODEX_HOME или удалить похожую запись. Общие пригодные appearance/launcher/shell
ресурсы передаются с прежними GUID и исходными inverses, без пересоздания.
Owned PNG в `data/appearance/icons` передаются вместе с appearance rules,
с исходными inverses; изменённый пользователем файл сохраняет retryable conflict.

Ранее отключённые внешние writers по умолчанию **остаются отключёнными**:
исходное значение сохраняется в historical cleanup, а не в обычном uninstall.
Только `restore_external=True` явно восстанавливает записанное внешнее значение;
это не разрешает одновременно включить конфликтующий native writer omp.

`legacy_cleanup` сохраняет полные строгие v1 envelopes с нерешёнными ресурсами
и исходным выбором функций независимо от новой active selection. Старый выбор —
намерение: функция отмечается установленной в omp только после настоящего
lifecycle checkpoint. Успешная часть очистки не маскирует deferred/conflicting
остатки в feature или skill receipts. Старый immutable runtime сохраняется,
пока на него ссылаются перенесённые/текущие shell, appearance или runtime resources,
есть live/minimized/buried sessions либо снимок неполон. Preview и apply проверяют
сессии одним read-only запросом официального SDK через вызывающий Python 3.11+
с установленным `iterm2`, без discovery агента. Схема status bar, её позиция и
профили не участвуют в этом запросе; операции над профилями проверяются строго.
Пустого снимка недостаточно: очистка исторического `current` и его релизов требует
detachment сохранённых ссылок и повторного явного вызова миграции после выхода
из старых shells. Снимок повторно проверяется под блокировками; держите сессии
закрытыми во время разрешённого apply — синхронизация с iTerm не атомарна.
Существующие вкладки не закрываются и не перезапускаются. Новые skill bundles
копируются только в выбранный профиль omp; чужие и изменённые копии не присваиваются.

Пути пакета учитывают абсолютные `ZDOTDIR`, `XDG_CONFIG_HOME`, `XDG_DATA_HOME`,
`XDG_CACHE_HOME`; относительные overrides этих путей игнорируются. Omp storage
разрешается отдельно правилами native profile resolver выше. Исторические пути
извлекаются только из валидированных receipts, не из текущих переменных старых агентов.
Runtime лежит в versioned data/releases со стабильным current; receipts/backups
отделены от cache. `ITERM2_APP` выбирает app bundle; discovery не запускает GUI.

## Проверка исходников и поставка

Task10 выполнил изолированные Python/Bun/zsh, CLI, extraction и actor-проверки;
фактические результаты и ограничения — в [acceptance matrix](docs/superpowers/validation/2026-11-16-omp-only/acceptance.md).
Это не единый повторный green full-suite и не доказательство GUI. Разрешённая
живая миграция пока частична: старый runtime сохранён, native feature cutover
заблокирован; три omp-only bundle установлены. Общая приёмка ещё не завершена.

```sh
python3 -m unittest discover -s tests -t . -v
/bin/zsh tests/test_appearance_shell.zsh
bun test tests/test_omp_config.ts tests/test_omp_identity.ts
python3 tools/check_sources.py
python3 tools/check_skill.py
python3 tools/check_export.py
python3 tools/build_release.py --destination dist
```

Source cutover removes the old active runtime/vendor/tests while retaining strict
historical decode/recovery and receipt-authorized cleanup. The explicit archive
allowlist includes all three bundles, native helpers, YAML distributable and
licenses/artwork. No private SDD, author workspace, auth/settings or old binaries
belong in it. Isolated extraction/bootstrap/installed-helper evidence is recorded
in the acceptance matrix; the earlier archive predates the final source fixes and
is not a current-source release. Installed helper layout is
`current/runtime/omp_config.ts` → `current/vendor/yaml/`.
Native status/banner/keyboard/rendering acceptance remains unverified.
Лицензии: [MIT](LICENSE) и [условия внешних компонентов](THIRD_PARTY_NOTICES.md);
происхождение зависимостей: [sources.lock.json](sources.lock.json).
