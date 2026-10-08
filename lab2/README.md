# Лаба 2 - Мониторинг сервиса: метрики, логи, трейсы

## Часть 0 - Свой сервис

Был написан сервис на Python с использованием фреймворка Flask (код представлен в файле [api.py](/lab2/api/api.py)). В сервисе работает 5 эндпоинтов согласно заданию:
- /health - возвращает ok в случае, если все хорошо работает 
- /fail - возвращает ошибку 500 и увеличивает счетчик ошибок
- /slow - отвечает через 1-3 секунды
- /load - делает N запросов к себе
- /metrics - отдает метрики (`api_requests_total` - счётчик запросов, `api_errors_total` - счётчик ошибок, `api_request_duration_seconds` - гистограмма времени ответа)

Сервис пишет структурированные JSON-логи с полями `timestamp`, `level`, `message`, `trace_id`, `span_id`, `service`, `path`, `method`.

Также к сервису созданы [Dockerfile](/lab2/api/Dockerfile), [requirements.txt](/lab2/api/requirements.txt) и [api-deployment.yaml](/lab2/k8s/api-deployment.yaml) для деплоя.

Далее я собрала образ и загрузила его в minikube:

```bash
docker build -t api:latest .
minikube image -t api:latest
``` 

При проверке видно, что сервис успешно запущен

![Проверка запуска сервиса](/lab2/screenshots/image1.png)

Попробовала подергать за эндпоинты, все успешно ответили.

![Проверка работы эндпоинтов](/lab2/screenshots/image2.png)

## Часть 1 — Метрики (Prometheus + Grafana)

Я установила Prometheus и Grafana через Helm:
```bash
helm repo add prometheus-community https://promtheus-community.github.io/helm-charts

helm repo update

kubectl create namespace monitoring

helm install prometheus prometheus-community/kube-prometheus-stack \
--namespace monitoring --set prometheus.prometheusSpec.serviceMonitorSelectorNilUsesHelmValues=false
```

Проверила поды командой `kubectl --namespace monitoring get pods`, все поды успешно запустились:

![Проверка запуска подов](/lab2/screenshots/image3.png)

Далее я написала и добавила файл [api-servicemonitor.yaml](/lab2/k8s/api-servicemonitor.yaml) для настройки Prometheus на правильное взятие данных с сервиса.

После этого я запустила Grafana на порту 3000 командой: 
```bash
kubectl port-forward -n monitoring svc/ptometheus-grafana 3000:80
```

В браузере в Grafana (перейдя по адресу http://localhost:3000) я увидела, что Prometheus автоматически добавился как источник данных в DataSource:

![Prometheus в DataSource](/lab2/screenshots/image4.png)

В Grafana я создала 3 панели:
- интенсивность запросов (Intensity of requests) 

    `sum(rate(api_requests_total[1m])) by (exported_endpoint)`

- доля ошибок (Error rate) - Отношение ошибок к общему числу запросов
    
    `sum(rate(api_errors_total[1m])) by (exported_endpoint) / sum(rate(api_requests_total[1m])) by (exported_endpoint)`

- p95 времени ответа (Latency p95) - 95-й процентиль
    
    `histogram_quantile(0.95, sum(rate(api_request_duration_seconds_bucket[5m])) by (le, exported_endpoint))`

Из особенностей, изначально у меня на графике была только одна линия. Оказалось, что проблема была в том, что я написала `endpoint` вместо окончательного `exported_endpoint`. После исправления все стало хорошо, и графики по всем эндпоинтам корректно отображаются. И при вызове эндпоинтов графики изменяются.

![Grafana RED-дашборады](/lab2/screenshots/image5.png)

## Часть 2 - Логи (Loki + Grafana)

Изначально я пыталась установить loki-stack. Однако с ним стали возникать проблемы. Я начала ощущать себя Тором, у которого Локи постоянно умирает и воскрешает.

![Локи](/lab2/screenshots/mem1.jpg)

Первая ошибка возникла из-за того, что loki-stack автоматически создаёт datasource Loki в Grafana с флагом `isDefault: true`, а в Grafana уже был другой datasource Prometheus тоже с `isDefault: true`. Grafana разрешает только один default-datasource на организацию. Конфликт привёл к тому, что Grafana начала падать с ошибкой:

```bash
Datasource provisioning error: datasource.yaml config is invalid.
Only one datasource per organization can be marked as default
```

Я решила эту проблему, убрав isDefault из настроек Loki, но возникла новая ошибка в логах.

```bash
"error from loki: parse error at line 1, col 1: syntax error: unexpected IDENTIFIER"
```

Порывшись в интернете, я прочитала о том, что loki-stack уже давно не поддерживается, и настоятельно рекомендуется его не использовать. Поэтому я решила подключить Loki другим способом.

Я написала файл [loki-values.yaml](/lab2/k8s/loki-values.yaml) и с его помощью подключила Loki:

```bash
helm upgrade --install loki grafana/loki -n monitoring -f ~/lab2/k8s/values/loki-values.yaml
```

Казалось бы, все должно заработать, но нет. Loki не запускался, крутясь в `CrashLoopBackOff` со следующей ошибков в логах:

```bash
"mkdir /var/loki: read-only file system error initialising module: ruler-storage"
```

Оказалось, что при `deploymentMode: SingleBinary` + `persistence.enabled: true` PVC создаётся, но не монтируется в контейнер. А `containerSecurityContext.readOnlyRootFilesystem: true` запрещает писать куда-либо, кроме смонтированных volumes.

Для решения этой проблемы я пробовала использовать `extraVolumes` и `extraVolumeMounts`, переносить их на верхний уровень. Однако ничего из этого не работало, поля просто игнорировались. 

В результате пришлось прибегунуть к ручной правке StatefulSet через kubectl edit. В volumes я дважды добавила volume loki.

```bash
KUBE_EDITOR=nano kubectl edit statefulset -n monitoring loki
```

После этих правок pod loki-0 перешёл в статус 2/2 Running и больше не падал.

Promtail ставила отдельным релизом:

```bash
helm upgrade --install promtail grafana/promtail -n monitoring --set "config.clients[0].url=http://loki.monitoring.svc.cluster.local:3100/loki/api/v1/push"
```

В Grafana добавила Loki как DataSource и решила сделать запрос на логи для проверки работы. В логах я смогла найти лог с fail, который получился из-за дергания эндпоинта `/fail`.

![Запрос логов](/lab2/screenshots/image6.png)

## Часть 3 - Трейсы (OpenTelemetry + Jaeger)

Следующим этапом я подключила Jaeger.

```bash
helm repo add jaegertracing https://jaegertracing.github.io/helm-charts
helm repo update

helm install jaeger jaegertracing/jaeger -n monitoring --set provisionDataStore.cassandra=false --set allInOne.enabled=true --set storage.type=memory --set agent.enabled=false --set collector.enabled=false --set query.enabled=false
```

Первый запуск сопроводился ошибками в логах

```bash
Transient error StatusCode.UNAVAILABLE encountered while exporting traces 
to jaeger.monitoring:4317, retrying in 1s.
Transient error StatusCode.UNAVAILABLE encountered while exporting traces 
to jaeger.monitoring:4317, retrying in 2s.
```

При этом под был со статусом Running, под присутствовал в namespace `monitoring` и сеть работает.

Проблема решилась, когда я исправила `http://jaeger.monitoring:4317` на `jaeger.monitoring:4317`. gRPC-экспортёр OpenTelemetry не принимает схему `http://` в параметре `endpoint`. Экспортёр пытается интерпретировать её как часть hostname, что приводит к ошибке.

После исправления эндпоинта я все пересобрала и перезапустила. 

При переходе на `http://localhost:16686` меня встретила go-хомячковая страница с разными трейсами.

![Jaeger](/lab2/screenshots/image7.png)

Трейс `/slow` содержит в себе "водопадную" структуру: есть корневой спан GET /slow длительностью 1.1 s и вложенный спан slow-op, который занимает практически все время корневого спана.

![/slow в Jaeger](/lab2/screenshots/image8.png)

Трейс `/fail` со статусом 500.

![/fail в Jaeger](/lab2/screenshots/image9.png)

В Grafana через запрос логов из Loki я выбрала трейс с `/fail` и скопировала его `trace_id`. 

![trace_id в Grafana](/lab2/screenshots/image10.png)

Этот трейс я скопировала в поисковую строку в Jaeger. В результате мне открылся трейс с этим id.

![трейс в Jaeger](/lab2/screenshots/image11.png)

## Часть 4 - Алерты (AlertManager + Karma)

Я создала файл [api-alerts.yaml](/lab2/k8s/api-alerts.yaml) с 3 критичными алертами:

- ServiceDown - сервис не отвечает. Когда сервис полностью недоступен для пользователей, это очень плохо.
- HighErrorRate - высокая доля ошибок 5хх. Это означает, что где-то есть баг, который важно исправить.
- HighLatency - высокое время ответа в течение 5 минут. Когда сервис работает, но отвечает медленно, в системе где-то есть узкий спан, и нужно его устранить.

Я применила все эти алерты командой
```bash
kubectl apply -f ~/lab2/k8s/api-alerts.yaml
```

После этого я зашла в Prometheus в браузере, где критичные алерты сразу отобразились.

![Prometheus UI](/lab2/screenshots/image12.png)

Далее нужно было добавить AlertManager.

Сначала я пробовала создать Secret `alertmanager-prometheus-kube-prometheus-alertmanager` с конфигом и `kubectl apply`. Однако это не получилось, и в браузерном AlertManager был только дефолтный конфиг.

Поэтому я пошла другим путем и написала файл [alertmanager-values.yaml](/lab2/k8s/alertmanager-values.yaml). Далее применила его

```bash
helm upgrade prometheus prometheus-community/kube-prometheus-stack \
  --namespace monitoring \
  --reuse-values \
  -f ~/lab2/k8s/alertmanager-values.yaml
```

Для места получения алертов я выбрала https://webhook.site. Изначально еще пробовала beeceptor, но к нему алерты не доходили (постоянно сбрасывалось соединение).

После подключения (изменила url alertmanager-values.yaml) на сайте все появилось

![webhook.site](/lab2/screenshots/image13.png)

Последним этапом установила Karma. Я не нашла ее в репозиториях prometheus-community, grafana, jaegertracing, поэтому установила через wiremind

```bash
helm repo add wiremind https://wiremind.github.io/wiremind-helm-charts

helm repo update

helm upgrade --install karma wiremind/karma -n monitoring --set env[0].name=ALERTMANAGER_URI --set env[0].value=http://prometheus-kube-prometheus-alertmanager:9093
```

После этого я запустила Karma по адресу `http://localhost:9095`. 
При переходе на страницу в браузере я увидела все активные алерты

![Karma](/lab2/screenshots/image14.png)

Вот такие пироги

![мем](/lab2/screenshots/mem2.gif)
