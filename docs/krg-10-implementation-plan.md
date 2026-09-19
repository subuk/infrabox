# KRG-10 — план реализации конфигурации серверов

Подготовлен 2026-09-19. Реализация и приёмка на testbox завершены; результаты — в [IMPLEMENTATION_STATUS](../IMPLEMENTATION_STATUS.md).
Уточнение оператора: NetBox должен получать Platform-репозиторий напрямую из Gitea,
без локального Git-зеркала и bind mount репозитория.

Источники: [KRG-10](https://linear.app/krglv/issue/KRG-10/add-netbox-config-context-driven-server-configuration),
[принятый ADR](https://linear.app/krglv/document/adr-platform-repository-configuration-model-12ea6f55acf7),
текущие исходники Core и соседнего `infrabox-platform`.

## Результат и границы

NetBox задаёт желаемое состояние через Config Context. Динамический inventory
сохраняет `config_context: true` и `flatten_config_context: true`. Доверенный
Platform-репозиторий содержит роли, схему и общий `site.yml`; workflow `configure`
является единственным поддерживаемым способом исполнения этого playbook.

Первый набор: `packages`, `chrony`, `sshd`. Роли firewalld, SELinux, мониторинга,
сертификатов, зависимости между ролями и универсальный semantic-validation framework
не входят в задачу. `discover` сохраняет сбор фактов и KRG-21 reconciliation.
OpenClaw не получает инструмента редактирования или произвольного запуска Ansible.
Изменения Config Context через него по-прежнему требуют конкретного подтверждения.

## Что уже есть и что мешает прямому добавлению workflow

- В Platform уже есть inventory, приватная выдача SSH/NetBox credentials из OpenBao,
  постоянный `known_hosts`, очистка job workspace и публикация результатов.
- В Platform пока нет `site.yml`, каталога конфигурационных ролей, JSON Schema и
  `AGENTS.md`. Глобальный stdout callback предназначен только для discovery.
- Core в `roles/platform/files/manage.py` выставляет `has_pull_requests: false`;
  permissions команд не включают отдельный доступ к PR. Исполняемую ветку
  синхронизирует Core из выбранного source/ref.
- Discovery проверяет точное совпадение SHA checkout и `/opt/platform/REVISION`.
  Этот контракт нельзя механически перенести на PR с новым SHA или просто удалить.
- Runner выполняет один job за раз и имеет доступ к рабочим credentials.
  Ansible check mode не является изоляцией произвольного кода из PR.
- Названные в AGENTS хосты разрешены для KRG-21 discovery. Это не разрешение
  менять на них sshd, пакеты или время в рамках KRG-10.

## 1. Сначала подготовить доверенный PR-поток

В Core включить PR, задать соответствующие права Developers/Readers/Operators,
сохранив защиту исполняемой ветки и независимые identities. Предлагаемый первый
вариант: PR внутри локального Gitea Platform-репозитория от доверенных разработчиков;
недоверенные fork PR не исполнять на runner с credentials.

Зафиксировать отдельно policy продвижения проверенного кода: пока сохранить
существующую синхронизацию выбранного source/ref через Core, без автоматического
merge/apply и без расширения права push в защищённую ветку. Документировать, как
проверенная PR-ревизия попадает в канонический source, чтобы следующий Core rerun
не заменял её старым кодом.

Первым интеграционным этапом проверить на закреплённых Gitea/runner: PR event,
head/base SHA, checkout именно проверяемого head, доступность base history,
workflow-dispatch inputs и отображение failed status на PR. Не предполагать полную
совместимость с GitHub Actions. Доверенный вход должен определять mode по событию,
а manual apply разрешаться только для одобренной исполняемой ревизии.

Для configure разделить code SHA и совместимость runtime. Защищённый runtime
проверяет manifest/fingerprint Containerfile, Python/collection pins и обязательных
runtime-компонентов. Role-only PR работает на совместимом runtime. Изменение
runtime/dependencies требует отдельной подготовки соответствующего candidate
runtime через Core и затем повторного PR check; несовместимый job явно падает.
Discovery сохраняет нынешнюю проверку SHA. Не разрешать сборку через host socket.

## 2. Описать контракт данных и ролей

В Platform добавить `schemas/config-context.schema.json` и автономный `AGENTS.md`.

- `infrabox_roles` — mapping `role: {enabled: boolean}`; отсутствующий mapping
  трактовать как отсутствие назначенных ролей. Неизвестное имя, в том числе
  отключённое, и неверный тип — ошибка.
- Реализованные имена получать из `roles/*`; короткий repository-owned список
  задаёт порядок `packages → chrony → sshd`. Проверять согласованность списка
  и каталога; порядок ключей Config Context не влияет на исполнение.
- `enabled: false` означает пропуск; никаких неявных uninstall/rollback.
- Публичные inputs находятся в prefixed `defaults/main.yml`; runtime/register
  используют отдельные `<role>_runtime*` имена. Не переписывать inputs через facts.
- JSON Schema допускает частичные contexts, но отвергает неизвестные ключи
  принадлежащих Platform/ролям пространств, например `chrony_severs`.
  Существующие native Ansible connection variables и независимые контексты
  сохраняются; схема не становится whitelist всех Ansible hostvars.
- Явно отделить публичные `infrabox_*` inputs от внутренних orchestration variables,
  которые Config Context не должен подменять.

В `AGENTS.md` перенести все обязательные правила KRG-10 и ADR, включая отсутствие
скрытых зависимостей, идемпотентность, meaningful check mode, реальный NetBox target
для каждой изменённой роли и запрет прямого ad-hoc apply. Добавить checklist:
роль → defaults → schema → registry/order → назначение target → локальные проверки
→ configure PR check. Внешний ADR не должен быть необходим для работы агента.

## 3. Inventory snapshot и preflight

Добавить небольшой `scripts/configure.py`: загрузить обычный NetBox inventory,
разрешить выбранный scope средствами Ansible и сохранить приватный effective
snapshot на время job. Impact, preflight и исполнение используют один snapshot
и один набор хостов, чтобы правка NetBox между этапами не расширила apply.
Snapshot не публиковать, удалить при завершении/ошибке.

Центральный preflight проверяет registry, типы, schema, identities, scope и
наличие targets. Обязательные inputs и смысловые ограничения проверяют
`roles/<role>/tasks/validate.yml` с обычными `assert`.

`site.yml` сначала проводит validation для всех выбранных хостов и включённых
ролей, затем исполняет роли в фиксированном порядке. Ошибка любого preflight
останавливает весь запуск до первой конфигурационной операции на любом хосте.
Это должен быть общий барьер, а не последовательность «validate/apply» для
каждой роли. Проверки, требующие фактов, собирают только необходимые сведения.
Отключённые роли не требуют своих обязательных inputs.

## 4. Детерминированный impact helper

Добавить `scripts/impact.py` без анализа Ansible task graph и Jinja.

1. Получить diff PR относительно merge-base с его base (`git diff --name-only`,
   с NUL-разделением и учётом старых/новых путей при rename/delete).
2. Из путей `roles/<role>/...` собрать все изменённые роли.
3. До запуска `site.yml` проверить наличие хотя бы одного реального managed host
   с каждой такой ролью `enabled: true`. Одна роль без targets проваливает весь job.
   Проверка действует и при одновременных глобальных изменениях со scope `all`.
4. Если все значимые пути относятся только к ролям — взять объединение их hosts.
5. `site.yml`, inventory, schema, shared helpers/plugins, dependencies, runtime,
   workflow и любой неоднозначный путь → `all`. Ошибка получения diff — ошибка
   validation, а не пустой успешный scope.
6. Исключения для documentation-only путей перечислить явно и узко. Нет targets
   при необходимом check — явный failure; synthetic hosts не создавать.

Финальный `--limit` строить из проверенного множества inventory hosts, исключив
расширение scope через pattern-метасимволы в именах. Пользовательские manual
patterns предварительно разрешать через обычную семантику Ansible; внешние
`@file`, произвольные CLI-флаги и пустой результат отвергать.

## 5. Минимальные роли

Первую поддержку предлагается ограничить AlmaLinux 10; остальные ОС явно
отклонять для включённой роли до изменений. Расширение матрицы ОС — отдельное
проверяемое изменение, а не неявная универсальность.

- **packages:** явный список пакетов и ограниченный state-контракт, без полного
  обновления ОС, wildcard-команд и неявного удаления. Проверять структуру inputs;
  использовать state-based package module. Начать с установки `present`.
- **chrony:** собственная установка пакета, prefixed inputs для NTP servers и
  необходимых параметров, шаблон конфигурации и handler только при изменении.
  Не зависеть от private variables роли packages.
- **sshd:** небольшой typed набор настроек и управляемый файл/drop-in, проверка
  полной эффективной конфигурации через `sshd -t`, reload только после успеха.
  Сохранять доступ действующего automation account/key; смену connection port
  и другие переходы доступа не включать без отдельного сценария.

У каждой роли — локальный validate, lifecycle tags, идемпотентные задачи и
осмысленный check/diff. Отдельно обработать первый check, когда пакет или service
ещё не существует: не запускать apply через `check_mode: false` ради проверки
и не заявлять выполненную валидацию отсутствующим бинарником. Предсказанные
изменения и недоступные проверки показывать явно.

## 6. Единый configure workflow

Добавить `.gitea/workflows/configure.yml` рядом с discover.

| Событие | Scope | Mode |
| --- | --- | --- |
| PR | Вычисляет impact | Всегда `check=true`, `diff=true` |
| Manual | Валидированный `limit`, default `all` | Default `check=true`; apply только при явном `false` |

Boolean inputs разбирать строго, учитывая строковое представление Gitea; `diff`
по умолчанию включать при check. Не добавлять `extra_args`, alternate inventory,
playbook, extra-vars или skip-tags. Команду собирать argv-массивом.

Для configure выбрать отдельный stdout/result путь: существующий discovery
callback не показывает обычные role changes. Публиковать head/base/executed SHA,
runtime fingerprint, mode, причину scope, hosts/roles, preflight result, bounded
diff и per-host changed/failed/unreachable. Сохранять `no_log`, не публиковать
credentials, snapshot или полный Config Context. Failure и upload failure должны
оставаться failures; cleanup выполняется и при ошибках/отмене, насколько позволяет
жизненный цикл runner. Результаты configure не должны портить discovery metrics.

## 7. NetBox Config Context Profile и Core

Core provisioner, а не runtime runner, создаёт/обновляет Config Context Profile
из schema выбранной одобренной Platform-ревизии. Сначала проверить API и модель
установленного NetBox 4.7.0: поддержку Git Data Source/DataFile и правила привязки
profile к contexts/local context. Если нативная синхронизация поддерживается,
использовать её; иначе идемпотентно загружать schema через provisioner API.

PR-схема участвует в preflight данного PR, но не заменяет production profile до
продвижения ревизии. Для source, требующего Git-доступа, подготовить отдельный
read-only credential; не выдавать NetBox root или provisioning PAT runner.
Существующие contexts не перепривязывать и не менять массово: сначала проверить
совместимость и показать конкретные необходимые изменения оператору.

## 8. Проверки и порядок приёмки

Локально: syntax/schema и focused tests для inventory flatten/merge, defaults,
registry/order, input/runtime separation, role-only/global/rename/delete impact,
нескольких ролей с одной без target, malformed inputs и запрета PR apply.
Отдельно проверить общий preflight barrier, совпадение snapshot/scope и сохранение
полезного diff без `no_log`/секретов. Тестовые данные допустимы для unit tests;
они не заменяют реальные NetBox hosts в PR pipeline.

Live после выбора разрешённых KRG-10 targets и конкретных desired settings:

1. Compatibility gate Gitea PR/dispatch/runtime без apply.
2. Реальное назначение всех трёх ролей через подтверждённые NetBox изменения.
3. Role-only PR ограничивает hosts; общий путь выбирает весь effective inventory.
   Global check выполнять только если весь этот набор разрешён для проверки.
4. Unknown role/type, missing inputs, одна роль без targets, empty scope и
   несовместимый runtime дают failure до исполнения конфигурационных ролей.
5. PR выполняет только check/diff; реальные конфигурации остаются прежними.
6. Manual configure с явным apply на согласованном canary; повторный apply
   даёт `changed=0`, финальный check не показывает изменений. Отдельно проверить
   SSH-доступ, NTP configuration/service и нужные packages.
7. Отключённая роль ничего не удаляет; discover и reconciliation продолжают
   работать; Core rerun сохраняет credentials и согласованную ревизию.

Прямой Ansible на managed hosts для обхода workflow не использовать. Перезагрузка,
expiry tests и полный bootstrap не нужны. Sanitized evidence и реальные SHA/run
URLs сохранить в Core artifacts, фактический результат — в IMPLEMENTATION_STATUS.
Обновить Platform README и Core README/docs/platform.md/docs index.

## Последовательность реализации и решения перед live

Рекомендуемые части: (1) PR/runtime compatibility и Core permissions;
(2) schema/AGENTS/registry/preflight/impact; (3) три роли и configure;
(4) NetBox profile provisioning и документация; (5) pipeline acceptance.
Первую часть проверить до большого объёма role-кода, поскольку нынешний контракт
runtime и отключённые PR непосредственно блокируют новый путь.

До live нужны решения: подтвердить место PR и способ продвижения ревизии;
выбрать targets, OS scope, package/NTP/sshd inputs и разрешение на apply.
Для подготовки кода можно исходить из локального Gitea, прежнего Core sync и
AlmaLinux 10. Ни пользовательский запрос «подготовь план», ни старые разрешения
на discovery не означают разрешение на этот live apply.
