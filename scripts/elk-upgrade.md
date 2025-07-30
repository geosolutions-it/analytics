# ELK Stack 7.6 → 8.18.3 Upgrade Process Summary


## Overview

The upgrade uses a parallel deployment approach where both ELK 7.6 and 8.18.3 environments run simultaneously on different ports, allowing for safe testing and easy rollback if needed.

## Phase 1: Baseline Testing and Backup

### 1.0 Prerequisites
- Install required Python packages: `pip install -r scripts/requirements.txt`

### 1.1 Initial Production Testing
- Run test suite against current production environment
- Record baseline results for comparison

### 1.2 Environment Backup
- Stop current docker-elk containers
- Create compressed backup of Elasticsearch volume
- Restart docker-elk containers
- Verify backup integrity

### 1.3 Backup Verification Testing
- Run test suite again
- Compare results with initial baseline to ensure consistency

## Phase 2: Blue-Green Environment Setup

### 2.1 Create Parallel Environment
- Clone `docker-elk` directory to `docker-elk-8`
- Update `docker-compose.yml` in new environment:
  - Change ports (9200→9201, 5601→5602, etc.)
  - Update volume names to avoid conflicts
- Create new Docker volume and restore from backup

### 2.2 Initial Deployment Test
- Start new environment with docker-compose
- Run test suite against new environment
- Compare results with baseline

## Phase 3: Two-Step Upgrade Process

### 3.1 Intermediate Upgrade (7.6 → 7.17.28)
- Stop containers in blue-green environment
- Update `.env` file to set ELK version to 7.17.28
- Rebuild containers with `--no-cache` flag
- Start containers and test connectivity
- Run test suite and compare results with baseline

### 3.2 Final Upgrade (7.17.28 → 8.18.3)
- Stop containers
- Update `.env` file to set ELK version to 8.18.3
- Rebuild with `--no-cache`
- Start only Elasticsearch container initially

### 3.3 Kibana Configuration for v8.x
- Check current password for elastic user and update `setup-kibana-token.sh`
- Run `setup-kibana-token.sh` script to generate service account token
- Update `kibana/config/kibana.yml` with:
  - Service account token configuration
  - Required encryption keys
  - Updated server host settings
- Start Kibana and Logstash containers

### 3.4 Final Validation
- Run test suite
- Compare results with previous baselines
- Verify all functionality is working correctly

## Environment Access

| Service | ELK 7.6 (Production) | ELK 8.x (Blue-Green) |
|---------|---------------------|----------------------|
| Elasticsearch | localhost:9200 | localhost:9201 |
| Kibana | localhost:5601 | localhost:5602 |
| Logstash | localhost:5000 | localhost:5001 |

## Rollback Strategy

If issues arise during testing:
1. Stop ELK 8.x environment (`docker-compose down` in docker-elk-8)
2. Ensure ELK 7.6 environment is running
3. Optionally clean up ELK 8.x volumes
