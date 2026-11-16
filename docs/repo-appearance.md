# Оформление вкладки по репозиторию

`appearance` — восьмая opt-in функция, для основной TUI-сессии omp в macOS/zsh. Она назначает
цвет и одну составную иконку своей сессии iTerm2 при старте интерактивной shell,
обычном `cd` и интерактивном запуске omp, включая resume и branch.
Используется физическая папка вызывающей shell, а не аргумент `--cwd` или текст
разговора. Вход в корень или подкаталог назначает пару, переход между корнями
меняет её. Выход из всех зарегистрированных корней отключает Tab Color и скрывает
custom icon: use-color=false для base/light/dark, mode Icon=0 и пустой path,
без назначения конкретного «дефолтного» RGB. Недоступные корни не совпадают.
Служебные команды (`--help`, `--version`, `--mode rpc`, `--print`) оформление не меняют. Ошибка API
не отменяет успешный `cd` или запуск omp и не меняет его код выхода. Это новое
поведение существующего `appearance`, без нового флага или схемы JSON.

Штатный zsh `chpwd` hook регистрируется один раз и сохраняет чужие hooks и функцию
`chpwd`; повторный source не дублирует регистрацию. Он обновляет только собственную
интерактивную zsh в iTerm2. Неинтерактивные shell и subprocess-команды модели
вкладку не перекрашивают; tmux не поддерживается. Старт shell и каждый `cd` ждут
завершения назначения или сброса, прежде чем вернуть управление. Поэтому быстрые
A → B → outside и запуск свежей вложенной interactive shell не оставляют
незавершённое назначение родителя, которое могло бы вернуть старую пару.
Обычно это короткое ожидание API; недоступные API или файловая система могут
задержать старт/каждый `cd` примерно на существующий бюджет 2.8 секунды.
Успешный `cd` сохраняет код 0 даже при ошибке оформления. Асинхронный observer
запуска/возврата omp отменяется с ожиданием очистки перед следующим helper.

Перед любой записью helper сверяет фактическое устройство терминала shell с `tty`
явно указанной сессии iTerm2. UUID из окружения сам по себе запись не разрешает:
другой PTY с унаследованными ID не изменяет родителя. Алиасы пути одного устройства
допустимы. Терминал фиксируется в shell до перенаправления потоков; pipes
supervisor не мешают своей интерактивной или вложенной shell в том же терминале.
При отсутствии/несовпадении tty, конфликте ID, закрытой сессии или ошибке API
helper безопасно пропускает назначение, сброс и любые изменения snapshot, включая
отложенную очистку. Read-only probe проверяет доступ и не разрешает запись.
Нет fallback на активную вкладку; это защита от ошибочного наследования контекста,
а не от вредоносного процесса с доступом к тому же пользовательскому API.

Generated startup передаёт приватный identity registry установленному runtime.
`preexec` запускает observer без ожидания SDK/API, а `precmd` отменяет и reap-ит
его перед отдельным неблокирующим observer возврата/обновления baseline.
Нативный launch явно вызывает `_iterm2_utils_appearance_arm` перед `exec`: только
этот согласованный путь может ждать захвата исходного оформления, до 2.8 секунды.
Обычная prompt-команда не ждёт API; её worker ждёт actual publication в течение
этой команды. Завершение/следующая команда отменяет его через lifetime/cancel fence;
выход shell дополнительно отслеживается Darwin kqueue, без polling и нового демона.
Имя executable, `jobName`, Bun и read-only API probe не являются разрешением записи.
Только совпадение приватного registry с независимо наблюдаемыми SDK-адресами,
`user.iterm2_utils_omp`, generation, точным kernel birth и foreground process-group
основного процесса на своём TTY разрешает назначение. Источник identity —
установленное расширение только `tui`/`main`;
subagents, RPC, help и обычные команды без такой identity не перекрашивают вкладку.
Snapshot сохраняется для возврата только после подтверждения этой identity.

Нужна новая shell для загрузки обновлённых hooks; установщик не перезапускает и
не закрывает пользовательские вкладки. Установленный release содержит соседний
`terminal_identity.py`: checkout и Python-пакет не нужны для runtime.

Создайте локальный JSON (не добавляйте личные пути в публичный checkout):

```json
{"projects": [{"root": "/path/to/repo", "color": "#65A85A", "icon": "android-mail"}]}
```

Корневое поле только `projects`, список непустой. Каждое правило содержит ровно
три строки: абсолютный `root`, `color` вида `#RRGGBB`, `icon` — встроенное имя либо
абсолютный путь к своему `.png`. Девять встроенных имён: `ios`, `android`, `kotlett`,
`ios-mail`, `ios-cloud`, `android-mail`, `android-cloud`, `chrome-mail`, `chrome-cloud`.
`ios` использует светлый Apple `#E6F4FF` с листом и выемкой; `ios-mail`
и `ios-cloud` используют тот же знак с прежними сервисными бейджами. Базовые
`android`, `kotlett` и остальные пары сохранены. Четыре мобильные пары сохраняют
прежние имена и фирменные знаки сервисов. Две веб-пары используют официальный цветной знак Chrome;
отдельного встроенного имени `chrome` нет.

Вариант B: платформа крупнее, квадратный значок сервиса расположен справа снизу.
Почта — белая `@` на синем; Облако — фирменный белый контур на синем. Каждая
согласованная пара SVG/прозрачной PNG 128×128 поставляется офлайн; iTerm2 получает
один составной custom icon. В [notices](../THIRD_PARTY_NOTICES.md) указаны публичные
источники, преобразования и владельцы брендов. MIT для кода и оригинальных
иллюстраций пакета не означает MIT-лицензию сторонней брендовой графики.

Корень совпадает с собой и подкаталогами; похожие соседние имена не совпадают.
Для вложенных правил выигрывает самый длинный физический корень. Симлинки
нормализуются; доступные корни и предки сравниваются по device/inode, поэтому
регистровые алиасы case-insensitive APFS совпадают, а дубли физического корня
отклоняются. Case-sensitive тома сохраняют различие имён. Недоступный target не
создаётся и не сканируется. Свой PNG должен быть доступен при install: до 16 MiB,
до 4096 пикселей по каждой стороне, до 128 MiB decoded scanlines; структура и
пиксельный поток проверяются до записи. SVG/URL вместо своего PNG не принимаются.

Выберите существующий Python **3.11+ с модулем `iterm2` именно в нём**. Для
нестандартного интерпретатора задайте абсолютный `ITERM2_UTILS_PYTHON` на всех
CLI-командах настройки. Discovery проверяет импорт SDK, но не открывает API.
Пакет не выполняет pip и не загружает картинки при старте shell.

```sh
python3 -m iterm2_utils plan --features appearance --appearance-config /path/to/rules.json --json
python3 -m iterm2_utils install --features appearance --appearance-config /path/to/rules.json --dry-run --json
python3 -m iterm2_utils install --features appearance --appearance-config /path/to/rules.json --json
python3 -m iterm2_utils doctor --json
```

Plan/dry-run ничего не пишут, не запускают API, GUI или shell startup. Install
копирует нормализованные правила в config `appearance.json`, свои PNG — в data
`appearance/icons/<sha256>.png`, встроенные — в `data/current/assets/appearance`.
Исходные JSON/PNG и checkout после установки runtime не нужны. Путь исходного
JSON в receipt не сохраняется. Bootstrap skill не выбирает функции.

`appearance_api` остаётся pending после записи файлов. В iTerm2 Settings →
General → Magic включите Enable Python API и подтвердите запрос авторизации
человеком. Затем из обычной собственной сессии iTerm2 выполните:

```sh
python3 -m iterm2_utils doctor --live --json
python3 -m iterm2_utils reconcile --step appearance_api --json
```

Это ограниченная read-only проверка API для явного UUID сессии; doctor не снимает
pending, reconcile снимает его только после успешной проверки. Проверка не
доказывает визуальное применение или переходы Automatic Profile Switching (APS).
Противоречащие ID и tmux отклоняются; активная вкладка не используется как запасной
вариант. Разрешения/TCC остаются действиями человека; отказ не обходится.

Обновление использует установленный набор, без исходного JSON/PNG. Для CLI
maintenance нужен новый checkout/release пакета:

```sh
python3 -m iterm2_utils update --dry-run --json
python3 -m iterm2_utils update --json
python3 -m iterm2_utils uninstall --features appearance --dry-run --json
python3 -m iterm2_utils uninstall --features appearance --json
```

Повторный install без `--appearance-config` использует установленные правила;
первый без них завершается conflict до записи. Новый JSON при plan/install
явно заменяет собственный набор. Изменённые пользователем owned файлы и чужие
поля сохраняются с conflict. Старые hash-копии своих PNG остаются owned до
uninstall. Удаление убирает только неизменённые owned ресурсы appearance, общие
shell/runtime сохраняются для других функций; generic JSON engine может оставить
пустой `{}`. Новый generated startup больше не подключает appearance source;
уже работающие shell удалённо не изменяются. Уже открытые вкладки не сбрасываются
и не перезапускаются.

Helper меняет только сессионные Tab Color/use color и Custom Icon Path/mode,
учитывая base/light/dark при назначении и сбросе и сохраняя профиль, фон, Default
и заголовок. Event-driven observer отслеживает actual identity и profileName для
APS; cold SDK startup supervisor ограничен 2.8 секунды, каждая API-операция — 2.2.
Окно APS в 1.5 секунды начинается после подтверждённой публикации main identity,
а не перед выполнением команды; задержка wrapper/startup/publication не расходует его.
PID/kernel birth/terminal задают владельца запуска отдельно от текущей generation:
валидные session_switch/branch того же процесса допустимы, замена процесса — нет.
Возврат требует положительного ухода прежнего foreground-владельца и собственного
shell TTY; временный разрыв variable/registry при публикации не означает shell return.
Ctrl+Z сохраняет живую dialog binding, но снимает foreground authority оформления.
Операции snapshot и назначения защищены native transaction, launch token и TTY.

В той же native snapshot-переменной хранится последняя положительно наблюдённая
shell-baseline: allowlisted цвет/иконка, physical cwd, terminal/TTY device,
shell PID/kernel birth и kernel executable path. После обычной команды refresh не блокирует prompt и
принимает только тот же фактический shell executable в foreground; agent-era APS
не становится original. Без доверенной baseline generic launch ничего не выдумывает:
явно вооружённый native launch может захватить её до exec. Смена root/cd назначает
новую пару/reset и обновляет baseline, не перенося старый original через новый запуск.
Другой cwd не переиспользует старый original даже при незавершённом API reset.
Pending claim прежнего запуска не позволяет записать его APS-значения как новую
baseline: сначала нужен подтверждённый owned return write; проверка claim/token
повторяется внутри native transaction. До этого сохраняется прежний trusted original.
Это граница последнего подтверждённого наблюдения shell, не атомарная гарантия для
ручной правки после него и непосредственно перед APS. Обычные ручные правки входят
в последующий положительно проверенный shell refresh. Foreign/newer snapshots и
чужие свойства не восстанавливаются поверх текущих.

Нет демона, polling, MCP или доверия к имени процесса. Поздний APS вне короткого
окна остаётся ограничением; недоступность identity/API безопасно пропускает запись,
не блокируя shell/omp и не меняя argv/exit status. Исторические визуальные проверки
предыдущего агента не доказывают omp-поведение. Новые offline suites и реальная
матрица cd/reset, rapid cd, APS и light/dark остаются очередью Task10; здесь tests
и native UI не запускались. Личные корни, JSON и снимки не публикуются.
