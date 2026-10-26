# Лаба 8 - Автоматизация devops-процесса с n8n + AI

## Часть 1 - Придумай кейс

В качестве кейса я решила выбрать процесс онбординга нового сотрудника. 

Я сама недавно начала работать (разработчиком). Поэтому я искренне считаю, что в компаниях была бы полезна штука, которая могла бы помочь новому сотруднику разобраться с устройством системы и порядками команды, куда он пришел.

Потому что сейчас это все выливается в огромное количество вопросов наставнику первые недели. И даже после получения быстрых ответов новенький может чувствовать себя потеряно среди большой системы и бурной деятельности.

**Компания:** пусть это будет абстрактная крупная ИТ-компания, занимающаяся разработкой сервиса для аналитики, давно находящаяся на рынке и имеющая уже большой объем базы.

**Кому это помогает?** Новым сотрудникам, которые выходят на проект и постоянно задают одни и те же вопросы: "как получить доступ", "где логи", "как запустить локально". И их наставникам, которым обычно надо тратить много времени для ответа на такие вопросы.

**Какая проблема проблема решается?** База знаний существует в виде разрозненных файлов и сообщений. Новый сотрудник не знает, где искать, и идёт спрашивать людей. Люди отвлекаются от работы.

**Что делает автоматизация?** Система запускается вручную, MCP Filesystem читает файлы из папки, AI-агент анализирует содержимое и формулирует ответ на вопрос сотрудника, MCP Filesystem записывает ответ в md-файл, и в результате создается файл с ответом, который сотрудник может прочитать или скопировать.

## Часть 2 - Реализация

Итак, для своего workflow я сделала:

- **Триггер**, с которого процесс запускается - в данном случае я использовала `Manual Trigger` (нода "When clicking 'Execute workflow'"). В реальной системе можно сделать триггером обращение (тык) пользователя

- **И AI-, и не-AI-шаги** - AI-шаг представлен на workflow через узел `Agent AI` в выполняет роль анализатора файлов проекта, а не-AI-шаги представлены `MCP Client`-узлами

- **MCP-серверы** - я создала 2 MCP-сервера: один для чтения файлов, другой для хранения ответов агента, чтобы не повторяться и не затрачивать ресурсы на одни и те же ответы при условии неизмененности файлов

- **AI toolkit на 3–5 инструментов** - я сделала 3 toolkit: `list_directory` возвращает список файлов в папке, `read_file` читает содержимое файла, `write_file` записывает файл с результатом

- **Описанные skills** - Агент действует по инструкции (System Message): сначала делает `list_directory`, затем читает README.md и файлы в директориях, после чего формирует структурированный текст и сохраняет его.

- **Конкретный результат** - файл с ответом в виде описания проекта сохраняются в `onboarding-guide.md`

## Часть 3 - Запусти локально

Я создала 4 директории для работы: `config` с конфигурацией окружения, `docs` с документацией, `scripts` со вспомогательными скриптами и `src` с кодом приложения. Внутри этих папок я подготовила необходимые файлы. Все находится внутри директории [onboarding-assistant](/lab7/onboarding-assistant).

![структура работы](/lab7/screenshots/image1.png)

Далее я запустила `n8n` в docker:

```bash
docker run -it --rm --name n8n --network mcp-net -p 5678:5678 \
  --add-host=host.docker.internal:host-gateway \
  -e N8N_COMMUNITY_PACKAGES_ALLOW_TOOL_USAGE=true \
  -e N8N_METRICS=true \
  -v n8n_data:/home/node/.n8n \
  docker.n8n.io/n8nio/n8n
```

Далее я хотела добавить `MCP Server` на свой Workflow, однако они выдавались в неподходящем виде. У них вход и выход были http, а мне нужны были stdin и stdout. Я пробовала брать встроенные, добавлять скачанные, но все равно http не уходило.

Я долго рылась на просторах интернета в поисках решения, и в итоге решила обернуть свои stdin stdout в этот такой желанный (для n8n) http.

Чтобы n8n и MCP-серверы видели друг друга по именам, создала общую сеть

```bash
docker network create mcp-net
```

Далее я запустила `Filesystem MCP` - сервер для чтения файлов из директории проекта:

```bash
docker run -d --name mcp-filesystem --network mcp-net -p 8081:8000 \
  -v /home/taisiya/onboarding-assistant:/data \
  supercorp/supergateway \
  --stdio "npx -y @modelcontextprotocol/server-filesystem /data" \
  --outputTransport streamableHttp --port 8000
```

Затем запустила `Memory MCP` - сервер для сохранения результатов работы агента:

```bash
docker run -d --name mcp-memory --network mcp-net -p 8082:8000 \
  supercorp/supergateway \
  --stdio "npx -y @modelcontextprotocol/server-memory" \
  --outputTransport streamableHttp --port 8000
```

Проверила, все запустилось:

![проверка mcp client](/lab7/screenshots/image2.png)

Далее я подключила запущенные MCP-сервисы.

Запущенный `Filesystem MCP`:

![Filesystem MCP](/lab7/screenshots/image3.png)

Запущенный `Memory MCP`:

![Memory MCP](/lab7/screenshots/image4.png)

Следующим этапом нужно было добавить AI-агента. Для этого я установила Ollama и скачала оттуда модель `llama3.2:latest` (пробовала еще qwen2.5 в качестве еще более легковесного варианта, но с ней результаты были совсем плохонькие):

```bash
curl -fsSL https://ollama.com/install.sh | sh

sudo systemctl start ollama
sudo systemctl status ollama

ollama pull llama3.2
```

Внутри `n8n` я добавила 2 узла - `AI Agent` и `Ollama Chat Model`.

В `Ollama Chat Model` я добавила URL для локального доступа к модели:

![ollama chat model](/lab7/screenshots/image6.png)

В `AI Agent` я ввела promt, system message и включила настройку `Force Tool Call on First Iteration`, потому что сначала я споткнулась на том, что агент вообще не хотел залезать в файлы и писать отсебятину.

![ai agent](/lab7/screenshots/image7.png)

Полный `System Message`:

![system message](/lab7/screenshots/image8.png)

После первого запуска агент отдавал ответ в виде `json` с техническими результатами работы и не создавал новый файл с ответом. Чтобы решить эту проблему, был создан новый `MCP Client`, который сохранял результат в md-файл:

![mcp client](/lab7/screenshots/image9.png)

Получившаяся структура `workflow` выглядит так:

![Итоговая структура workflow](/lab7/screenshots/image5.png)

## Часть 4 - Мониторинг

Для мониторинга системы я использовала стек `Prometheus` + `Grafana`. `n8n` запускала с флагом `N8N_METRICS=true`, что позволило Prometheus собирать метрики с эндпоинта `/metrics`.

Я создала 3 дашборда:

- Общее количество запусков - показывает, сколько времени агент тратит на анализ файлов и генерацию ответа.
 
  Запрос для дашборда: 

  `rate(n8n_workflow_execution_duration_seconds_sum[5m]) / rate(n8n_workflow_execution_duration_seconds_count[5m])`

- Количество ошибок в секунду - показывает количество упавших запусков (например, из-за недоступности MCP-сервера)

  Запрос для дашборда: 

  `rate(n8n_workflow_execution_duration_seconds_count{status="failed"}[5m])`

- Средняя длительность выполнения workflow - показывает общую нагрузку на инстанс n8n.

  `rate(n8n_workflow_execution_duration_seconds_count[5m])`

![дашборды](/lab7/screenshots/image10.png)

Также я сделала алерты. Решила для разнообразия сделать их через Grafana:

- n8n Workflow Errors - ловит падение workflow

  `rate(n8n_workflow_execution_duration_seconds_count{status="failed"}[5m])`

- Средняя длительность выполнения - ловит, ассистент отвечает новичку дольше 2 минут

  `rate(n8n_workflow_execution_duration_seconds_sum{status="success"}[5m]) / rate(n8n_workflow_execution_duration_seconds_count{status="success"}[5m])`

- Аномальный всплеск запусков - ловит, workflow запускают слишком часто

  `rate(n8n_workflow_execution_duration_seconds_count[5m])`

![Алерты](/lab7/screenshots/image11.png)

---

Вот такие пироги

![кот](/lab7/screenshots/cat.gif)
