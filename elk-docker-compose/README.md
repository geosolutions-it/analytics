Build and startup:
```bash
cd geoserver
sudo docker build -t geoserver:elk-2.22.4 --build-arg GEOSERVER_WEBAPP_SRC="https://sourceforge.net/projects/geoserver/files/GeoServer/2.22.4/geoserver-2.22.4-war.zip/download" --build-arg PLUG_IN_URLS="https://sourceforge.net/projects/geoserver/files/GeoServer/2.22.4/extensions/geoserver-2.22.4-monitor-plugin.zip" .
cd ..
sudo docker compose up
```
