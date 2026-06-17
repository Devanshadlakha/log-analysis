# Starts Kafka + Zookeeper + Elasticsearch + Kibana + MongoDB containers.
# Skips the backend / ai-service / frontend services in docker-compose.yml
# because their Dockerfiles don't exist — we run them on the host.
docker compose up -d zookeeper kafka elasticsearch kibana mongodb
docker ps --format 'table {{.Names}}\t{{.Status}}'
