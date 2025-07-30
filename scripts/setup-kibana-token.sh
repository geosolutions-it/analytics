#!/bin/bash

# Wait for Elasticsearch to be ready
echo "Waiting for Elasticsearch to be ready..."
until curl -s -u elastic:changeme http://localhost:9201/_cluster/health | grep -q '"status":"green\|yellow"'; do
  sleep 2
done

echo "Creating Kibana service account token..."

# Create service account token for Kibana
TOKEN_RESPONSE=$(curl -s -X POST -u elastic:changeme \
  http://localhost:9201/_security/service/elastic/kibana/credential/token/kibana-token)

# Extract the token value
TOKEN=$(echo $TOKEN_RESPONSE | jq -r '.token.value')

if [ "$TOKEN" != "null" ] && [ ! -z "$TOKEN" ]; then
  echo "Service account token created successfully!"
  echo "Token: $TOKEN"
  echo ""
  echo "Add this to your kibana.yml:"
  echo "elasticsearch.serviceAccountToken: \"$TOKEN\""
  echo ""
  echo "Remove these lines from kibana.yml:"
  echo "# elasticsearch.username: elastic"
  echo "# elasticsearch.password: changeme"
else
  echo "Failed to create service account token"
  echo "Response: $TOKEN_RESPONSE"
fi
