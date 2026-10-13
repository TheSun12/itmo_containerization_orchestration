# Лаба 3 - Собери платформу для shop

## Часть 0 - Сервисы

В первую очередь я закодила HTTP-сервис [`api`](/lab3/shop-api/api.py) на Python с эндпоинтами:

- `GET /health` - возвращает `ok`, но при `HEALTH_FAIL = true` срабатывает ошибка 500,
- `POST /order` - пишет заказ в postgres,
- `GET /orders` - читает и отдает список заказов.

К нему дописала [requirements.txt](/lab3/shop-api/requirements.txt) и [Dockerfile](/lab3/shop-api/Dockerfile).

После этого я закодила [worker](/lab3/shop-worker/worker.py), который читает файлы из postgres и помечает их обработанными. К нему аналогично написала [requirements.txt](/lab3/shop-worker/requirements.txt) и [Dockerfile](/lab3/shop-worker/Dockerfile).

Далее я собрала образы и загрузила их в minikube:

```bash
docker build -t shop-api:latest .
docker build -t shop-worker:latest .

minikube image load shop-api:latest
minikube image load shop-worker:latest
```

Проверила, что образы успешно загрузились:

![Проверка загрузки образов](/lab3/screenshots/image1.png)

## Часть 1 - Ограждения на кластер

Для создания политик я выбрала движок Kyverno, т.к. для меня он показался более удобным: язык политик - YAML (в отличие от Rego в OPA/Gatekeeper), разработан специально для Kubernetes, привычные инструменты для работы, которые использовались в предыдущих лабораторных.

Установка Kyverno:

```bash
helm repo add kyverno https://kyverno.github.io/kyverno/
helm install kyverno kyverno/kyverno -n kyverno --create-namespace \
  --set admissionController.replicas=1 \
  --set backgroundController.replicas=1 \
  --set cleanupController.replicas=1 \
  --set reportsController.replicas=1
```

После установки проверила, что все успешно заработало:

![Проверка установки Kyverno](/lab3/screenshots/image2.png)

Далее я составила 5 правил для всего кластера:

- Обязательные лимиты ресурсов (resource limits)
  
  Зачем нужно: если разработчик задеплоит сервис без requests и limits, то при утечке памяти или внезапном всплеске нагрузки сервис может съесть всю RAM или CPU, сервис будет падать, и будет сложно найти причину

  Что вводит правило: любой Pod в кластере обязан явно указать requests.memory, requests.cpu, limits.memory и limits.cpu. Без этого создание отклонится

  Для правила создала файл [01-require-resources.yaml](/lab3/k8s/policies/01-require-resources.yaml).

  Применила правило командой

  ```bash
  kubectl apply -f ~/lab3/k8s/policies/01-require-resources.yaml
  ```

  Протестировала правило на [плохом](/lab3/k8s/policies/test-bad-01.yaml):

  ![Плохой тест 1 правила](/lab3/screenshots/image3.png) 
  
  И [хорошем](/lab3/k8s/policies/test-good-01.yaml) тесте:

  ![Хороший тест 1 правила](/lab3/screenshots/image4.png)

- Доверенный реестр образов
  
  Зачем нужно: если брать в проект образ из непроверенного источника, можно попасть на вредоносный код, уязвимость или секреты из другого проекта.

  Что вводит правило: все образы в кластере принимаются только из доверенного реестра, все остальные отклоняются.

  Я выбрала в качестве доверенных источников `docker.io`, `ghcr.io`, `registry.k8s.io` и `quay.io`. 

  Для правила создала файл [02-trusted-registry.yaml](/lab3/k8s/policies/02-trusted-registry.yaml).

  Применила правило командой

  ```bash
  kubectl apply -f ~/lab3/k8s/policies/02-trusted-registry.yaml
  ```

  Протестировала правило на [плохом](/lab3/k8s/policies/test-bad-02.yaml) и [хорошем](/lab3/k8s/policies/test-good-02.yaml) тесте:

  ![Плохой и хороший тест 2 правила](/lab3/screenshots/image5.png)

- Обязательные метки
  
  Зачем нужно: когда поды в кластере без единого стандарта меток, могут возникнуть проблемы с каталогизацией и управлением подами.

  Что вводит правило: все поды должны иметь обязательный набор меток.

  Для правила создала файл [03-require-labels.yaml](/lab3/k8s/policies/03-require-labels.yaml).

  Применила правило командой

  ```bash
  kubectl apply -f ~/lab3/k8s/policies/03-require-labels.yaml
  ```

  Протестировала правило на [плохом](/lab3/k8s/policies/test-bad-03.yaml) и [хорошем](/lab3/k8s/policies/test-good-03.yaml) тесте:

  ![Плохой и хороший тест 3 правила](/lab3/screenshots/image6.png)

- Запрет privileged-контейнеров

  Зачем нужно: такой контейнер не имеет изоляции и получает полный доступ к ядру, может подмонтировать файловую систему ноды, обойти `kernel namespaces` и получает все `capabilities`.

  Что вводит правило: любой под с `privileged: true` в `securityContent` отклоняется.

  Для правила создала файл [04-no-privileged.yaml](/lab3/k8s/policies/04-no-privileged.yaml).

  Применила правило командой

  ```bash
  kubectl apply -f ~/lab3/k8s/policies/04-no-privileged.yaml
  ```

  Протестировала правило на [плохом](/lab3/k8s/policies/test-bad-04.yaml):

  ![Плохой тест 4 правила](/lab3/screenshots/image7.png) 
  
  И [хорошем](/lab3/k8s/policies/test-good-04.yaml) тесте:

  ![Хороший тест 4 правила](/lab3/screenshots/image8.png)

- Запрет :latest-тега
  
  Зачем нужно: если образы в кластере не будут иметь фиксированный тег, то его версия может неожиданно измениться - с новым поведением, уязвимостями или сломанным конфигом.

  Что вводит правило: все образы в кластере имеют фиксированный тег - конкретную версию. 

  Для правила создала файл [05-no-latest-tag.yaml](/lab3/k8s/policies/05-no-latest-tag.yaml).

  Применила правило командой

  ```bash
  kubectl apply -f ~/lab3/k8s/policies/05-no-latest-tag.yaml
  ```

  Протестировала правило на [плохом](/lab3/k8s/policies/test-bad-05.yaml) и [хорошем](/lab3/k8s/policies/test-good-05.yaml) тесте:

  ![Плохой и хороший тест 1 правила](/lab3/screenshots/image10.png)

Проверила, что все правила активны:

![Проверка активности правил](/lab3/screenshots/image9.png)

## Часть 2 - Чарт api и worker

Сначала я написала [Chart.yaml](/lab3/helm/shop/Chart.yaml), [values.yaml](/lab3/helm/shop/values.yaml), [_helpers.tpl](/lab3/helm/shop/templates/_helpers.tpl) с общими метками и шаблоны [api-deployment.yaml](/lab3/helm/shop/templates/api-deployment.yaml), [api-service.yaml](/lab3/helm/shop/templates/api-service.yaml) и [worker-deployment.yaml](/lab3/helm/shop/templates/worker-deployment.yaml).

Когда я все создала, то вспомнила, что мои образы собирались с тегом `:latest`, что противоречит созданному 5 правилу. Поэтому я пересобрала образы:

```bash
cd ~/lab3/shop-api && docker build -t shop-api:v1 .
cd ~/lab3/worker-api && docker build -t worker-api:v1 .

minikube image load shop-api:v1
minikube image load shop-worker:v1
```

Еще я заметила, что развертывание базы данных идет в следующей части. И, чтобы не получать ошибки подключения к базе данных, я сделала заглушку, которую потом перед 3 частью убрала:

```bash
kubectl create secret generic shop-postgres-app \
   --namespace shop --from-literal=username=shop --from-literal=password=fake-password
```

После этого я поставила чарт и проверила, что поды запустились.

```bash
helm install shop shop/ --namespace shop --wait --timeout 3m
```

![Проверка подов](/lab3/screenshots/image11.png)

После я перешла к проверке работы:

- Проверка `reconciliation` (возвращение пода при удалении)
  
  Я посмотрела имя одного из подов и удалила его. Сразу после удаления Deployment создал новый под:

  ![Reconciliation](/lab3/screenshots/image12.png)

- Проверка `scale up/down` через `values.yaml`

  Для проверка я изменила значение `replicas` с 3 на 4 и применила изменения через `helm upgrade shop shop/ -n shop`.

  При проверке я увидела, что запустилось 4 пода.

  ![Проверка подов](/lab3/screenshots/image13.png)

  Потом я вернула обратно количество реплик на 3, и при перезапуске снова стало 3 пода.

  ![Проверка подов](/lab3/screenshots/image14.png)

- Проверка `rolling update` - обновление без `downtime`

  Для проверки я запустила цикличный curl:

  ```bash
    for i in $(seq 1 500); do
        code=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:8080/health)
        echo "$i $code" >> ~/lab3/rolling-test.log
        sleep 0.2
    done
  ```

  В `values.yaml` я изменила версию с v1 на v2 и собрала образы с новой версией.

  Запустила rolling update:

  ```bash
  helm upgrade shop shop/ -n shop
  kubectl get pods -n shop -l app.kubernetes.io/component=api -w
  ```

  Старые и новые поды сосуществуют - старые удаляются только после того, как новые пройдут readiness:

  ![Проверка подов](/lab3/screenshots/image15.png)

  Проверка результатов curl:

  ```bash
  cat ~/lab3/rolling-test.log | grep -v "200$"
  ```

  Все запросы со статусом `200`, ничего не падало.

  ![Проверка статуса](/lab3/screenshots/image16.png)

- Проверка сломанной версии + rollback

  Снова я запустила цикличный curl. 

  В `values.yaml` добавляем `healthFail: true`.

  Проверяем работу подов. Старые поды остаются, т.к. новые не могут включиться. Это защита от сломанных обновлений. Kubernetes не удаляет рабочие поды, пока новые не готовы.

  ![Проверка подов](/lab3/screenshots/image17.png)

  Проверяем curl. Все запросы curl - 200. Значит, ничего не падало.

  ![Проверка статуса](/lab3/screenshots/image18.png)

## Часть 3 - Postgres через оператора

Перед установкой убрала заглушку из 2 части:

```bash
kubectl delete secret -n shop shop-postgres-app
```

В качестве оператора БД я выбрала CloudNativePG. Установка оператора:

```bash
helm repo add cnpg https://cloudnative-pg.github.io/charts
helm repo update

kubectl create namespace cnpg-system

helm install cnpg cnpg/cloudnative-pg -n cnpg-system --set replicaCount=1
```

Установка заблокировалась 3 правилом (реестр доверенных источников). Для более легкой установки добавила `namespace` в исключение из правил.

Также я создала шаблон для объекта оператора [postgres-cluster.yaml](/lab3/helm/shop/templates/postgres-cluster.yaml).

Проверка работы Reconciliation оператора:
  
Для проверки я удалила под и посмотрела, что происходит в кластере после этого:

 ```bash
  kubectl delete pod -n shop shop-postgres-1
  kubectl get pods -n shop -l cnpg.io/cluster=shop-postgres -w
```

Под сразу вернулся обратно:

![Проверка reconciliation](/lab3/screenshots/image19.png)

Заказы тоже не потерялись и остались в том же виде на месте:

![Проверка, что таблица сохранила данные](/lab3/screenshots/image20.png)

Разница между controller-manager и оператором заключается в том, что первый может просто перезапустить под, а оператор знает специфику postgres и может повысить реплику до primary, бэкапнуть, делать репликацию, обновление паролей и т.д.

## Часть 4 - Падение control plane

Для проверки поведения при падении control plane я решила, что перемещу `kube-apiserver` во временную папку:

```bash
sudo mv /etc/kubernetes/manifests/kube-apiserver.yaml /tmp/kube-apiserver.yaml.bak
```

При проверке видно, что нода недоступна. Ничего изменить в ней нельзя, т.к. изменения просто не пройдут.

![Пропажа ноды](/lab3/screenshots/image23.png)

При этом, если обратиться по `curl`, сервис отвечает.

![Ответ по curl](/lab3/screenshots/image21.png)

Потом я вернула `kube-apiserver` на место, и нода вернулась.

![Возвращение ноды](/lab3/screenshots/image22.png)

## Часть 5 - Мониторинг

Для мониторинга я добавила в чарт [servicemonitor.yaml](/lab3/helm/shop/templates/servicemonitor.yaml) и [prometheusrule.yaml](/lab3/helm/shop/templates/prometheusrule.yaml). 

Дальше я применила чарты и запустила Prometheus.

В Prometheus я нашла `shop-api` сервис со статусом `UP`, что означает, что все 3 реплики успешно подключились. 

![shop-api в Prometheus](/lab3/screenshots/image24.png)

Алерты я оставила со 2 лабораторной, т.к. считаю их подходящими.

![алерты](/lab3/screenshots/image25.png)

Чтобы спровоцировать срабатывание алерта `ServiceDown` (падение сервиса) я уменьшила количество реплик до 0 командой

```bash
kubectl scale deployment shop-api -n shop --replicas=0
```

Сначала алерт совсем не хотел срабатывать. Правило `up{job="shop-api"} == 0` не работало, поэтому я немного заменила логику на проверку существования метрики `absent(up{job="shop-api"})`. После этого все заработало.

В Prometheus статус алерта изменился на `FIRING`:

![firing alert](/lab3/screenshots/image26.png)

В Alertmanager `ServiceDown` появился в списке:

![Alertmanager](/lab3/screenshots/image27.png)

В Karma `ServiceDown` появился в дашборде:

![Karma](/lab3/screenshots/image28.png)

Следовательно, алерты в системе корректно работают.

Вот такие пироги

![котик](/lab3/screenshots/cat.gif)
