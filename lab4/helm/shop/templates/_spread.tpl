{{- define "shop.spread" -}}
{{- $root      := .root -}}
{{- $component := .component -}}
{{- $mechanism := $root.Values.spread.mechanism -}}
{{- if eq $mechanism "podAntiAffinity" -}}
affinity:
  podAntiAffinity:
  {{- if eq $root.Values.spread.affinityType "required" -}}
  requiredDuringSchedulingIgnoredDuringExecution:
    - labelSelector:
        matchLabels:
          app.kubernetes.io/component: {{ $component }}
      topologyKey: {{ $root.Values.spread.topologyKey }}
  {{- else -}}
  preferredDuringSchedulingIgnoredDuringExecution:
    - weight: 100
      podAffinityTerm:
        labelSelector:
          matchLabels:
            app.kubernetes.io/component: {{ $component }}
        topologyKey: {{ $root.Values.spread.topologyKey }}
  {{- end -}}
{{- else if eq $mechanism "topologySpreadConstraints" -}}
topologySpreadConstraints:
  - maxSkew: {{ $root.Values.spread.maxSkew }}
    topologyKey: {{ $root.Values.spread.topologyKey }}
    whenUnsatisfiable: {{ $root.Values.spread.whenUnsatisfiable }}
    labelSelector:
      matchLabels:
        app.kubernetes.io/component: {{ $component }}
{{- else -}}
{{- fail (printf "fail name") -}}
{{- end -}}
{{- end -}}