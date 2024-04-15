{{- define "uber.environment" }}
        - name: UBER_URL_ROOT
          value: "{{ .Values.web.url_root }}"
        - name: VIRTUAL_HOST
          value: "{{ .Values.web.virtual_host }}"
        - name: UBER_LISTEN_PORT
          value: "{{ .Values.web.port }}"
        - name: UBER_LISTEN_HOST
          value: "{{ .Values.web.host }}"
        - name: DB_CONNECTION_STRING
          value: "{{ tpl .Values.db_connection_string . }}"
        - name: SESSION_HOST
          value: "{{ tpl .Values.redis_host . }}"
        - name: SESSION_PREFIX
          value: "ses"
        - name: REDIS_HOST
          value: "{{ tpl .Values.redis_host . }}" 
        - name: REDIS_PREFIX
          value: "red"
        - name: BROKER_HOST
          value: "{{ tpl .Values.redis_host . }}"
        - name: BROKER_PREFIX
          value: "bro"
        - name: BROKER_PORT
          value: "6379"
        - name: BROKER_USER
          value: ""
        - name: BROKER_PASS
          value: ""
        - name: BROKER_PROTOCOL
          value: redis
        - name: BROKER_VHOST
          value: "0"
{{- end }}

{{- define "uber.initContainers" }}
      {{- if or (index .Values "postgresql-ha" "enabled") .Values.redis.enabled }}
      serviceAccountName: init-api-access
      initContainers:
      - name: wait-dependencies
        image: projects.registry.vmware.com/tcx/snapshot/stackanetes/kubernetes-entrypoint:latest
        env:
        - name: DEPENDENCY_SERVICE
          value: {{ if (index .Values "postgresql-ha" "enabled") }}postgres-pgpool{{ end }}{{ if and (index .Values "postgresql-ha" "enabled") .Values.redis.enabled }},{{ end }}{{ if .Values.redis.enabled }}redis-master{{ end }}
      {{- end }}
{{- end }}