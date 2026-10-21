# Лаба 4 - SLA критического пути под перегрузкой

## Часть 0 - Сервис batch

В начале я создала batch-сервис, который бесконечно грузит CPU и потребляет память (файл - [batch.py](/lab4/batch/batch.py)).

К нему я написала [Dockerfile](/lab4/batch/Dockerfile)

При запуске сервиса наглядно видно, как он начинает поедать ресурсы:

![работа batch](/lab4/screenshots/image1.png)

## Часть 1 - Выбери механизм разнесения

Среди механизмов разнесения выбор стоял между 2 вариантами:

- `podAntiAffinity` - инструмент для разнесения реплик, чтобы они никогда не оказались на одной ноде

- `topologySpreadContaints` - инструмент для равномерного распределения по зонам или нодам

Я выбрала `topologySpreadContaints`, т.к. это более современный вариант с гарантированным распределением и более гибкой реализацией. Жесткое разнесение мне показалось избыточным для работы.

В [values.yaml](/lab4/helm/shop/values.yaml) добавила выбор механизма:

```yaml
spread:
    mechanism: "topologySpreadConstaints"
    topologyKey: "kubernetes.io/hostname"
    maxSkew: 1
    whenUnsatisfiable: "DoNotSchedule"
    affinityType: "required"
```

Также я создала шаблон [_spread.tpl](/lab4/helm/shop/templates/_spread.tpl) для реализации логики, где в зависимости от `mechanism` в `values.yaml` рендерится либо блок `affinity`.`podAntiAffinity`, либо `topologySpreadConstraints`.

Далее добавила в [api-deployment.yaml](/lab4/helm/shop/templates/api-deployment.yaml):

```yaml
spec:
    {{- include "shop.spread" (dict "root" . "component" "api") | nindent 6 }}
```

Проверила, что все корректно сохранилось и рендерится:

![проверка корректности файлов](/lab4/screenshots/image2.png)

## Часть 2 - Тесная площадка

Перед началом части установила все необходимые инструменты (kind и инструменты из предыдущих лабораторных):

```bash
curl -Lo ./kind https://kind.sigs.k8s.io/dl/v0.24.0/kind-linux-amd64
chmod +x ./kind

kubectl create namespace kyverno
helm install kyverno kyverno/kyverno -n kyverno \
    --set admissionController.replicas=1 \
    --set backgroundController.replicas=1 \
    --set cleanupController.replicas=1 \
    --set reportsController.replicas=1

kubectl create namespace cnpg-system
helm install cnpg cnpg/cloudnative-pg -n cnpg-system --set replicaCount=1

kubectl create namespace monitoring 
helm install prometheus prometheus-community/kube-prometheus-stack \
    -n monitoring \
    --set prometheus.prometheusSpec.serviceMonitorSelectorNilUsesHelmValues=false
```

Загрузила правила из предыдущей лабораторной:

```bash
kubectl apply -f ~/lab3/k8s/policies/01-require-resources.yaml
kubectl apply -f ~/lab3/k8s/policies/02-trusted-registry.yaml
kubectl apply -f ~/lab3/k8s/policies/03-require-labels.yaml
kubectl apply -f ~/lab3/k8s/policies/04-no-privileged.yaml
kubectl apply -f ~/lab3/k8s/policies/05-no-latest-tag.yaml
```

После всех этих подготовительных манипуляций я написала файл для конфига [kind-config.yaml](/lab4/kind-config.yaml) на 2 рабочих ноды + 1 ноды control-plane.

Далее я подняла кластер и проверила, что 3 ноды успешно запустились:

![поднятие кластера kind](/lab4/screenshots/image3.png)

И загрузила образы в `kind`:

```bash
kind load docker-image shop-api:v1 --name lab4
kind load docker-image shop-worker:v1 --name lab4
kind load docker-image batch:v1 --name lab4
```

Потом я занялась добавлением `batch` в Chart.

Для этого я написала шаблон [batch-deployment.yaml](/lab4/helm/shop/templates/batch-deployment.yaml).

В `values.yaml` добавила настройку `requests/limits` для `batch`:

```yaml
batch:
    replicas: 1
    image:
        repository: batch
        tag: "v1"
    cpuWorkers: 1
    memStepMb: 10 
    memIntervalS: 5
    memMaxMb: 0
    resources:
        requests:
        cpu: 100m
        memory: 64Mi
        limits:
        cpu: 500m
        memory: 256Mi
```

Во время развертывания подов пришлось столкнуться с рядом проблем (а куда же без них...).

Сначала оказалось, что postgres просит хранилище, которое kind не мог создать ему. Я решила сделать `local-path-storage` для решения этой проблемы. И эту красоту начали блокировать правила, созданные в предыдущей лабораторной.

Из-за этого стал зависать `postgres`, приходилось неоднократно принудительно перезагружать оператора cnpg, кластера и pvc.

Наконец я избавилась от первой волны проблем. После сохранения изменений через `helm upgrade shop . -n shop` проверила, что все успешно встало:

![проверка подов](/lab4/screenshots/image4.png)

## Часть 3 - Реальные числа вместо угадывания

После этого необходимо узнать реально подходящие значения для `resources`. 

Для этого я загрузила `hey` (для нагрузки сервиса) и `krr` (для анализа полученных значений с нагрузки).

```bash
sudo apt-get install hey

curl -Lo krr.zip https://github.com/robusta-dev/krr/releases/download/v.1.28.0/krr-ubinti-latest-v1.28.0.zip
unzip krr.zip
sudo mv krr /usr/local/bin/
sudo chmod +x /usr/local/bin/krr
```

Для запуска нагрузки я включила сервис на порты 8080 и мониторинг с grafana на порт 9090.

```bash
kubectl port-forward -n shop svc/shop-api 8080:8080

kubectl port-forward -n monitoring svc/prometheus-kube-prometheus-prometheus 9090:9090
```

В другом окне терминала я запустила нагрузку на эндпоинт `orders` на 15 минут с помощью `hey`:

```bash
hey -z 15m -q 20 -c 5 http://localhost:8080/orders
```

Результаты показали, что приложение обрабатывает 4 запроса в секунду, 50% запросов выполняются 1,1 секунду, что довольно много. Почти все время (1,23 секунды в среднем) тратится на ожидание ответа от сервера (т.е. на обработку внутри `api` и запросы к базе).

![результат hey](/lab4/screenshots/image5.png)
![результат hey](/lab4/screenshots/image6.png)

Для получения рекомендаций по более правильным значениям resources я запустила `krr`:

```bash
krr simple -n shop -p http://127.0.0.1:9090
```

В результате вышла таблица со значениями:

![таблица от krr](/lab4/screenshots/image7.png)

На CPU krr порекомедовал снизить значения, а на memory наоборот увеличить, что я и сделала (кроме batch, ему не хотелось бы давать много ресурсов из-за его специфики работы).

Итак, я поменяла значения в `values.yaml` и обновила через `helm upgrade shop . -n shop`.

Все поды успешно поднялись без ошибок:

![проверка подов](/lab4/screenshots/image8.png)

## Часть 4 - Разнеси критический сервис

Еще в 1 части в `api-deployment.yaml` я применила механизм `topologySpreadConstraints` для разнесения по нодам.

Я проверила, что поды `api` распределились по двух рабочим нодам. Два пода ушли на lab-worker и один на lab-worker2.

![проверка разнесения](/lab4/screenshots/image9.png)

В случае, если одна нода упадет, то хотя бы одна реплика запустится на другой ноде.

## Часть 5 - Приоритеты и гарантии

Для задания приоритетов я написала шаблон [priorityClass](/lab4/helm/shop/templates/priorityclasses.yaml). В нем я выделила класс под важные api и worker с `value: 100000` и класс под batch с `value: -10`.

Также я добавила `priorityClassName` в деплойменты.

В `api-deployment.yaml` добавила:

```yaml
spec:
    priorityClassName: {{ .Release.Name }}-critical
    {{- include "shop.spread" (dict "root" . "component" "api") | indent 6 }}
```

В [postgres-cluster.yaml](/lab4/helm/shop/templates/postgres-cluster.yaml):

```yaml
spec:
    priorityClassName: {{ .Release.Name }}-critical
    resources:
        {{- toYaml .Values.postgres.resources | nindent 4 }}
```

В `batch-deployment`:

```yaml
spec:
    priorityClassName: {{ .Release.Name }}-batch
```

Потом я создала [PodDisruptionBudget](/lab4/helm/shop/templates/pdb.yaml) для `api` и `postgres` с `minAvailable: 1`.

После создания я проверила, что у подов встали правильные QoS:

![проверка QoS](/lab4/screenshots/image10.png)

Разница `Guaranteed` и `Burstable` заключается в очередности вытеснения. `batch` с типом `Burstable` вытесняется первым, особенно если реальное потребление превышает `requests`. Низкий `PriorityClass` делает его главной жертвой Preemption. `api` и `worker` с типом `Guaranteed` вытесняются последними, они не превышают свои резервы, и kubelet при MemoryPressure будет искать жертв среди других классов.

## Часть 6 - Создай нехватку, поймай preemption

Для того, чтобы создать нехватку, я увеличила количество реплик у `batch` до 10 (пробовала сначала 3 и 5, но не помогало, все запускалось).

При проверке подов видно, что часть batch-подов ушли в Pending:

![Проверка с подами](/lab4/screenshots/image11.png)

Дальше я увеличила количество реплик у `api` до 5, и batch-поды начали исчезать.

Я посмотрела причину вытеснений и к моей радости поймала Preemption. Планировщик Kubernetes увидел, что у api высокий приоритет, и убил поды batch (низкий приоритет), чтобы освободить для него место.

![preemption](/lab4/screenshots/image12.png)

Это доказывает, что высокоприоритетные поды могут жертвовать низкоприоритетными для обеспечения SLA. Планировщик Kubernetes при нехватке ресурсов сначала убивает поды с наименьшим приоритетом.

## Часть 7 - Давление по памяти, порядок жертв

Для создания давления по памяти я увеличила память у `batch`. 

Сначала batch-поды стали уходить в `Pending`, потом появился статус `Evicted`. 

Я даже успела увидеть статус `MemoryPressure: true` при проверке `kubectl describe node`.

Но потом резко виртуальная машина начала сходить с ума и бесконечно вылетать. При чем я долго не могла уменьшить ресурсы для возврата в предыдущее положение, т.к. все перезагружалось обратно сразу при включении.

Поэтому, к сожалению, скриншоты с доказательством я не успела сделать, а после восстановления, когда удалось поймать момент до перезапуска, делать такое еще раз я испугалась :(

Осталось только изображение меня и сходящей с ума виртуалки во время этого:

![состояние](/lab4/screenshots/this-is-fine-fire.gif)

Тем не менее, как я уже отмечала выше, я успела увидеть, что в первую очередь начали изменять статус batch-поды с низким приоритетом. Из-за этого я более чем уверена, что все пошло из-за памяти, т.к. больше я ничего не меняла. 

## Часть 8 - Докажи SLA под нагрузкой

Для просмотра данных о нагрузке системы я создала дашборды в Grafana. По ним видно, что несмотря на схождение с ума batch поды api и worker работали без задержек

График CPU:

![График CPU](/lab4/screenshots/image13.png)

График Memory:

![График Memory](/lab4/screenshots/image14.png)

Также во время увеличения CPU я гоняла `hey` и он показал довольно хорошие результаты - ни один запрос не упал с ошибкой 500.

![hey](/lab4/screenshots/image15.png)

Параллельно снимались графики в Prometheus UI. Изначально PromQL-запросы не возвращали данные, так как в коде api.py метрики экспортируются с префиксом shop_api_. После корректировки запросов (добавления префикса shop_api_ и фильтра exported_endpoint="/orders") графики появились.

## Часть 9 - Мониторинг

В последней части этой лабораторной я добавила в чарт shop шаблон [ServiceMonitor](/lab4/helm/shop/templates/servicemonitor.yaml), использующие стек `kube-prometheus-stack` из Лабы 2. Внутри я добавила 3 новых алерта:

- `ShopApiSlaViolation` (Warning): Срабатывает, если 95-й перцентиль задержки api превышает 1.5 секунды в течение 2 минут

- `ShopApiErrorSpike` (Critical): Срабатывает, если доля 5xx ошибок превышает 1% в течение 2 минут.

- `ShopBatchOOMKilled` (Warning): Срабатывает, если под batch был вытеснен (Evicted) или убит по OOM (OOMKilled) за последние 5 минут.

Новые алерты успешно добавились в Prometheus UI:

![alerts](/lab4/screenshots/image16.png)

Для провокации алерта `ShopApiSlaViolation` я урезала CPU до 10m. Prometheus UI (Alerts) подтверждает, что алерт перешел в статус Firing:

![alert firing](/lab4/screenshots/image17.png)

---
Вот такие пироги

![cat](/lab4/screenshots/cat.gif)
