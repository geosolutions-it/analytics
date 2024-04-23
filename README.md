# Analytics

## Log injection Diagram

    **Filebeat => Logstash => Elasticsearch <= Kibana**

## Configuring Kibana

Having a dashboard in place before starting data injection is advisable: so congiguring kibana should the first step.
This should be done with the provided bash script which also will correctly set up the dashboard in kibana:

```bash
    cd kibana
    chmod +x ./install-dashboard.sh
    ./install-dashboard.sh -h=https://localhost:5601 -n=MyCompany -u=elastic -s=geoserver-space
```

## Contribute to Kibana dashboard

To make a default.ndjson file compatibile with `install-dashboard.sh` all you need to do is:

- export from kibana the dashboard with all its related objects, save it as `default.ndjson`.

- if you changed CustomerNamePlaceHolder to MyCompany with the `install-dashboard.sh` script explained [here](#Configuring-Kibana) issue:
  `sed -i "s/PubliAcqua/CustomerNamePlaceHolder/g" default.ndjson`

- test it making a new empty space (i.e. "geoserver-test-space") in kibana, upload your default.ndjson, checking that index pattern and each other dashobard objects, including the ones added/modified are working:

    `./install-dashboard.sh -h=https://localhost:5601 -n=MyCompany -u=elastic -s=geoserver-test-space`

- Once everything looks fine you may share your `default.ndjson` making a PR

## Logstash configuration examples

Here you can find some examples to configure logstash in a way to normalize GeoServer logs and audits correctly.
Inside `logstash.conf` configure input and output stanzas as needed

```bash
    logstash/pipelines/logstash.conf
    logstash/patterns/{geoserver-audit,geoserver-log}
```

Configuring logstash.yml is out of the scope of the logstash filters for Geoserver, for kubernetes you can probably go fine with the default provided.

## Filebeat configuration examples

For default filebeat installation you should just need to copy files in place and restart filebeat:

```bash
    cp filebeat/conf.d/{geoserver-audit,geoserver-log} /etc/filebeat/conf.d/
```

## Logstash configuration debug

The official [logstash](https://www.elastic.co/guide/en/logstash/current/docker.html) Docker image may be used to test for logstash configuration compliance. You may want to remove options `"--debug --config.debug"` from the command if you are testing it automatically dropping unneeded verbosity.

```bash
    docker run --rm -v $HOME/Development/analytics/logstash/pipelines:/checkvolume docker.elastic.co/logstash/logstash:7.8.1 logstash --debug --config.debug --config.test_and_exit -f /checkvolume/logstash.conf
```

## Grok Debuggers

- <https://grokconstructor.appspot.com/>
- <https://grokdebug.herokuapp.com/>
- Embedded Kibana Grok Debugger

## Kubernetes

Tip for a nicely formatted configmap (applying this config map may produce a single liner in the logstash.conf: section of the yaml) you may treasure this for any config map using configuration files:
```bash
    kubectl get -o yaml cm [YOUR CONFIGMAP NAME] | sed -E 's/[[:space:]]+\\n/\\n/g' | kubectl apply -f -
```
Example config map for logstash 7.8.x deployed in kubernetes:

```yaml
    apiVersion: v1
    kind: ConfigMap
    data:
    geoserver-audit: |
        LAYERS (?:[\w\s:,-]+)
        USERNAME (?:[\w]+)
        ERRORMESSAGE (?:[\w]+)
        SERVICEVERSION (?:[\d\.]+)
        QUERYSTRING (?:[-A-Za-z0-9 &='.,;:_/+#]+)
        BBOX %{NUMBER:BBox1:float},%{NUMBER:BBox2:float},%{NUMBER:BBox3:float},%{NUMBER:BBox4:float}
        GEOSERVER_AUDIT (%{INT:RequestId})?,(%{IPORHOST:ServerHost})?,(%{WORD:Service})?,(%{SERVICEVERSION:ServiceVersion})?,(%{WORD:Operation})?,(%{WORD:SubOperation})?,(\"%{LAYERS:Layers}\")?,(\"%{BBOX:BBox}\")?,(\"%{URIPATH:RequestPath}\")?,(\"%{QUERYSTRING:QueryString}\")?,\"(%{DATA:RequestBody})?\",(%{WORD:RequestMethod})?,(\"%{TIMESTAMP_ISO8601:StartTime}\")?,(\"%{TIMESTAMP_ISO8601:EndTime}\")?,(%{POSINT:ResponseTime:int})?,(\"(%{IPORHOST:ClientAddress})?(:)?(%{NUMBER:ClientPort})?\")?,(\")?(%{USERNAME:User})?(\")?,(%{QS:UserAgent})?,(%{POSINT:ResponseHTTPStatus:int})?,(%{POSINT:ResponseLength:int})?,(%{QS:ResponseContentType})?,(\"%{WORD:Error}\")?,(\"%{ERRORMESSAGE:ErrorMessage}\")?
    geoserver-log: |
        TIMESTAMP_GSLOG %{YEAR}-%{MONTHNUM}-%{MONTHDAY} %{HOUR}:%{MINUTE}:%{SECOND},%{INT}?
        GSLOG %{TIMESTAMP_GSLOG} %{WORD:LogLevel} %{GREEDYDATA:logMessage}

    logstash.conf: |
        input {
        beats {
            port => 5044
        }
        }
        output {
        elasticsearch {
            index => "%{[@metadata][beat]}-%{[@metadata][version]}-%{+YYYY.MM}"
            hosts => [ "${ES_HOSTS}" ]
            user => "${ES_USER}"
            password => "${ES_PASSWORD}"
            cacert => '/etc/logstash/certificates/ca.crt'
        }
        }

        filter {
        mutate {
            add_field => { "client_name" => "ProjectName"  }
        }
        if "geoserver-audit" in [type] {
            grok {
        patterns_dir => ["/usr/share/logstash/patterns/"]
                match => { "message" => "%{INT:RequestId},%{IPORHOST:ServerHost},(%{WORD:Service})?,((?<ServiceVersion>[\d\.]+))?,(%{WORD:Operation})?,(%{WORD:SubOperation})?,\"((?<Layers>[-\w\s:,]+))?\",(\"%{BASE10NUM:BBox1:float},%{BASE10NUM:BBox2:float},%{BASE10NUM:BBox3:float},%{BASE10NUM:BBox4:float}\")?,\"(%{URIPATH:RequestPath})?\",\"((?<QueryString>[-?A-Za-z0-9&='<> ().,;:_/+#]+))?\",\"(%{DATA:RequestBody})?\",%{WORD:RequestMethod},\"%{TIMESTAMP_ISO8601:StartTime}\",\"%{TIMESTAMP_ISO8601:EndTime}\",(%{NUMBER:ResponseTime:int})?,\"%{IPORHOST:ClientAddress}(:)?(%{NUMBER:ClientPort})?\",%{QS:remoteUser},%{QS:UserAgent},%{NUMBER:ResponseHTTPStatus:int},%{NUMBER:ResponseLength:int},%{QS:ResponseContentType},\"(%{WORD:geowebcache-cache-result})?\",(%{QS:geowebcache-cache-miss-reason})?,\"(%{WORD:Error})?\",(%{QS:ErrorMessage})?"
                }
        add_tag => [ "grokked"]
            }
            kv {
                source => "QueryString"
                field_split => "&"
                transform_key => "uppercase"
            }
            mutate {
            lowercase => [ "Error"]
            uppercase => [ "Service"]
            rename => [ "Service", "SERVICE"]
            convert => { "RequestId" => "integer"}
            convert => { "WIDTH" => "integer"}
            convert => { "HEIGHT" => "integer"}
            convert => { "Error" => "boolean"}
            add_tag => [ "geoserver", "audit", "geoserver-audit" ]
            }
            if ![TILED] {
            mutate { add_field => { "TILED" => "false" } }
            }
            mutate {
            convert => { "TILED" => "boolean"}
            }
            date {
            match => ["StartTime", "ISO8601"]
            target => "@timestamp"
            add_tag => ["dated"]
            }
            geoip {
            source => "ClientAddress"
                target => "geoip"
                add_field => [ "[geoip][coordinates]", "%{[geoip][longitude]}" ]
                add_field => [ "[geoip][coordinates]", "%{[geoip][latitude]}"  ]
            }
        }
        else if "geoserver-logs" in [type] {
            mutate {
            add_tag => [ "geoserver", "log", "geoserver-logs", "geoserver-log"]
            }
            grok {
            patterns_dir => [ "/usr/share/logstash/patterns/" ]
            match => {
            "message" =>[ "%{GSLOG}" ]
            }
            add_tag => ["grokked"]
            }
            if "DEBUG" in [logLevel] or "TRACE" in [logLevel] or "INFO" in [logLevel] {
            drop { }
            }
        }
        }
    logstash.yml: |
        http.host: "0.0.0.0"
        path.config: /usr/share/logstash/pipeline
```

## Create Users in Elasticsearch

In case there is the need of a dedicated user for the dashboard one can create them by issuing this json code to elasticsearch, first declare a role change `geoserver-space` accordigly on how you installed the dashboard:

```json
   PUT /api/security/role/kibana_ro_role
   {
     "elasticsearch": {
       "cluster" : [ ],
       "indices" : [ ]
     },
     "kibana": [
       {
         "base": [],
         "feature": {
           "visualize": ["all"],
           "dashboard": ["read", "url_create"]
         },
         "spaces": ["geoserver-space"]
       }
     ]
   }
```

Create an user with kibana role

```json
   POST /_security/user/jacknich
   {
      "password" : "j@rV1s",
      "roles" : [ "kibana_ro_role" ],
      "full_name" : "Jack Nicholson",
      "email" : "jacknich@example.com"
   }
```

Test user login

```bash
   curl -u jacknich:j@rV1s http://localhost:9200/_cluster/health
```
