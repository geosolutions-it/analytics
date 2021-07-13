# Analytics

## Log injection Diagram

    **Filebeat => Logstash => Elasticsearch <= Kibana**

## Configuring Kibana

On AWS you need to upload `kibana.json` manually in the kibana gui of the managed AWS ES. 
## Logstash configuration examples

Here you can find some examples to configure logstash in a way to normalize GeoServer logs and audits correctly.
Inside `logstash.conf` configure input and output stanzas as needed

```bash
    cp logstash/conf.d/logstash.conf /etc/logstash/conf.d/logstash.conf
    mkdir /etc/logstash/patterns
    cp logstash/patterns/* /etc/logstash/patterns
```

Configuring logstash.yml is out of the scope of the logstash filters for Geoserver, for kubernetes you can probably go fine with the default provided.

## Filebeat configuration examples

For default filebeat installation you should just need to copy files in place and restart filebeat:

```bash
    cp filebeat/conf.d/{geoserver-audit,geoserver-log} /etc/filebeat/conf.d/
    cp filebeat.yml /etc/filebeat/filebeat.yml
```

## Logstash configuration debug

The official [logstash](https://www.elastic.co/guide/en/logstash/current/docker.html) Docker image may be used to test for logstash configuration compliance. You may want to remove options `"--debug --config.debug"` from the command if you are testing it automatically dropping un-needed verbosity.

```bash
    docker run --rm -v $HOME/Development/analytics/logstash/pipelines:/checkvolume docker.elastic.co/logstash/logstash:7.1.2 logstash --debug --config.debug --config.test_and_exit -f /checkvolume/logstash.conf
```

## Grok Debuggers

- <https://grokconstructor.appspot.com/>
- <https://grokdebug.herokuapp.com/>
- Embedded Kibana Grok Debugger
