#!/usr/bin/env bash


function usage {

 echo "usage:"
 echo "$1 [-u|--user <username>] [-p|--password <password>] -n|--project-name <name> -h|--kibana-host <host_url>"
 exit 0
}

function arg_parse {
    echo $1 | sed 's/[-a-zA-Z0-9]*=//'
}

for i in "$@"; do
    case $i in
        -u=*|--user=*)
        ELASTIC_USER=$(arg_parse $i)
        ;;
        -p=*|--password=*)
        ELASTIC_PASSWORD=$(arg_parse $i)
        ;;
        -n=*|--project-name=*)
        PROJECT_NAME=$(arg_parse $i)
        ;;
        -h=*|--kibana-host=*)
        KIBANA_HOST=$(arg_parse $i)
        ;;
        *)
        usage $0
        ;;
    esac
done
[ -z "$KIBANA_HOST" ] && usage $0
[ -z "$PROJECT_NAME" ] && usage $0

KDB_DEST_DIR="./build"
mkdir -p $KDB_DEST_DIR
CURLARGS="-k -X POST $KIBANA_HOST/api/saved_objects/_import -H kbn-xsrf:true --form file=@$KDB_DEST_DIR/$PROJECT_NAME.ndjson"
cp ./default.ndjson $KDB_DEST_DIR/$PROJECT_NAME.ndjson
sed -i "s/CustomerNamePlaceHolder/$PROJECT_NAME/g" $KDB_DEST_DIR/$PROJECT_NAME.ndjson    
[ "$ELASTIC_USER" != "" ] && [ "$ELASTIC_PASSWORD" == "" ] && curl -u$ELASTIC_USER \
$CURLARGS
[ "$ELASTIC_USER" != "" ] && [ "$ELASTIC_PASSWORD" != "" ] && curl -u$ELASTIC_USER:$ELASTIC_PASSWORD \
$CURLARGS
[ "$ELASTIC_USER" == "" ] && [ "$ELASTIC_PASSWORD" == "" ] && curl \
$CURLARGS
