set "max_age=14"

set "geoserver_audits_base_path=C:\Program Files\Apache Software Foundation\Tomcat 9.0\webapps\geoserver\data\audit"
set "geoserver_logs_base_path=C:\Program Files\Apache Software Foundation\Tomcat 9.0\webapps\geoserver\data\logs"
set "tomcat_logs_base_path=C:\Program Files\Apache Software Foundation\Tomcat 9.0\logs"

rem deleting old GeoServer log files
for %%G in (.log, .out, .txt) do (
  forfiles /p "%geoserver_logs_base_path%" /m *%%G /d -"%max_age%" /c "cmd /c del @path"
)

rem deleting old GeoServer audit files
for %%G in (.log) do (
  forfiles /p "%geoserver_audits_base_path%" /m *%%G /d -"%max_age%" /c "cmd /c del @path"
)

rem deleting old Tomcat log files
for %%G in (.log, .out, .txt) do (
  forfiles /p "%tomcat_logs_base_path%" /m *%%G /d -"%max_age%" /c "cmd /c del @path"
)

