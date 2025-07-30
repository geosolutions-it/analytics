#!/usr/bin/env python3
"""
Comprehensive ELK Stack Test Suite
Tests essential aspects of Elasticsearch, Logstash, and Kibana with configurable modes
Supports ~10GB dataset testing with 3 test modes:
- Basic: Essential checks (5 minutes)
- Advanced: Comprehensive tests (15 minutes) 
- Performance: Full stress testing (20 minutes)
Compatible with ES 7.6 and ES 8.x for upgrade comparison
"""

import json
import time
import requests
import statistics
from datetime import datetime, timedelta
from elasticsearch import Elasticsearch
from concurrent.futures import ThreadPoolExecutor, as_completed
import logging
import sys
import threading
from collections import defaultdict
import os
import argparse



# Configuration variables
ES_HOST = 'localhost'
ES_PORT = '9200'
KIBANA_HOST = 'localhost'
KIBANA_PORT = '5601'

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(f'elk_test_results_{datetime.now().strftime("%Y%m%d_%H%M%S")}.log')
    ]
)
logger = logging.getLogger(__name__)

class ELKTestSuite:
    def __init__(self, es_hosts=[f'{ES_HOST}:{ES_PORT}'], username=None, password=None, kibana_url=f'http://{KIBANA_HOST}:{KIBANA_PORT}', test_mode='basic'):
        """Initialize ELK test suite"""
        self.es_hosts = es_hosts
        self.kibana_url = kibana_url
        self.username = username  
        self.password = password
        self.results = {}
        self.start_time = None
        self.test_mode = test_mode
        
        # Test mode configurations
        self.test_mode_configs = {
            'basic': {
                'duration_minutes': 5,
                'description': 'Essential connectivity and health checks',
                'tests': ['connectivity', 'cluster_health', 'basic_search']
            },
            'advanced': {
                'duration_minutes': 15, 
                'description': 'Comprehensive functionality and performance tests',
                'tests': ['connectivity', 'cluster_health', 'index_management', 'search_performance', 'data_integrity', 'indexing_performance', 'resilience']
            },
            'performance': {
                'duration_minutes': 20,
                'description': 'Full stress testing and performance validation',
                'tests': ['connectivity', 'cluster_health', 'index_management', 'search_performance', 'data_integrity', 'indexing_performance', 'resilience', 'stress_tests']
            }
        }
        
        # Set duration based on test mode
        self.estimated_total_duration = self.test_mode_configs[test_mode]['duration_minutes'] * 60
        
        # Initialize Elasticsearch connection
        es_config = {'hosts': es_hosts, 'timeout': 30, 'retry_on_timeout': True}
        if username and password:
            es_config['http_auth'] = (username, password)
        print(f'Username and password: ---------->>>>> {username} {password}')
        self.es = Elasticsearch(**es_config)
        
        # Initialize indices (will be discovered dynamically)
        self.test_indices = []
        self.discovered_indices = {}
        self.common_fields = {}
        
        # Discover indices and analyze their structure
        self._discover_indices()
        
        # Performance baselines
        self.performance_targets = {
            'search_latency_ms': 100,      # < 100ms for simple queries
            'complex_query_ms': 500,       # < 500ms for complex aggregations
            'bulk_index_rate': 1000,       # > 1000 docs/sec
            'cluster_health_time': 5,      # < 5s to get cluster health
            'index_creation_time': 10,     # < 10s to create index
            'large_scan_ms': 5000,         # < 5s for large data scans
            'concurrent_stress_ms': 10000, # < 10s for concurrent stress
            'memory_scan_ms': 15000        # < 15s for memory-intensive scans
        }
    
    def log_test_result(self, test_name, result, duration=None, details=None):
        """Log and store test results"""
        self.results[test_name] = {
            'result': result,
            'duration': duration,
            'details': details,
            'timestamp': datetime.now().isoformat()
        }
        
        status = "✓ PASS" if result else "✗ FAIL"
        duration_str = f" ({duration:.2f}s)" if duration else ""
        logger.info(f"{status} {test_name}{duration_str}")
        if details:
            logger.info(f"    Details: {details}")
    
    def timer_decorator(self, func):
        """Decorator to time test execution"""
        def wrapper(*args, **kwargs):
            start = time.time()
            result = func(*args, **kwargs)
            duration = time.time() - start
            return result, duration
        return wrapper
    
    def _discover_indices(self):
        """Dynamically discover indices and analyze their structure"""
        try:
            logger.info("Discovering indices in the cluster...")
            
            # Get all indices
            cat_indices = self.es.cat.indices(format='json', h='index,docs.count,store.size')
            
            # Filter out system indices and small indices
            filtered_indices = []
            for idx in cat_indices:
                index_name = idx['index']
                doc_count = int(idx.get('docs.count', 0))
                
                # Skip system indices and very small indices
                if (not index_name.startswith('.') and 
                    not index_name.startswith('kibana') and
                    not index_name.startswith('logstash') and
                    doc_count > 100):  # Only indices with substantial data
                    filtered_indices.append({
                        'name': index_name,
                        'doc_count': doc_count,
                        'size': idx.get('store.size', '0b')
                    })
            
            # Sort by document count (largest first) and take top indices
            filtered_indices.sort(key=lambda x: x['doc_count'], reverse=True)
            
            # Limit to reasonable number for testing (max 10 indices)
            max_indices = min(10, len(filtered_indices))
            selected_indices = filtered_indices[:max_indices]
            
            logger.info(f"Found {len(filtered_indices)} suitable indices, testing top {max_indices}")
            
            # Analyze each selected index
            for idx_info in selected_indices:
                index_name = idx_info['name']
                self.test_indices.append(index_name)
                
                try:
                    # Get mapping to understand field structure
                    mapping = self.es.indices.get_mapping(index=index_name)
                    properties = mapping[index_name]['mappings'].get('properties', {})
                    
                    # Analyze common field patterns
                    fields = {
                        'timestamp_fields': [],
                        'text_fields': [],
                        'keyword_fields': [],
                        'numeric_fields': [],
                        'nested_fields': []
                    }
                    
                    for field_name, field_config in properties.items():
                        field_type = field_config.get('type', 'object')
                        
                        if field_type == 'date' or '@timestamp' in field_name or 'time' in field_name.lower():
                            fields['timestamp_fields'].append(field_name)
                        elif field_type == 'text':
                            fields['text_fields'].append(field_name)
                        elif field_type == 'keyword':
                            fields['keyword_fields'].append(field_name)
                        elif field_type in ['long', 'integer', 'double', 'float']:
                            fields['numeric_fields'].append(field_name)
                        elif field_type == 'nested' or field_type == 'object':
                            fields['nested_fields'].append(field_name)
                    
                    self.discovered_indices[index_name] = {
                        'doc_count': idx_info['doc_count'],
                        'size': idx_info['size'],
                        'fields': fields,
                        'mapping': properties
                    }
                    
                    logger.info(f"  {index_name}: {idx_info['doc_count']:,} docs, {idx_info['size']}")
                    
                except Exception as e:
                    logger.warning(f"Failed to analyze index {index_name}: {e}")
                    continue
            
            # Identify common field patterns across indices
            self._identify_common_patterns()
            
            if not self.test_indices:
                logger.warning("No suitable indices found for testing!")
                # Fallback to basic indices if none found
                self.test_indices = ['*']  # Test all indices as fallback
                
        except Exception as e:
            logger.error(f"Index discovery failed: {e}")
            # Fallback to wildcard
            self.test_indices = ['*']
    
    def _identify_common_patterns(self):
        """Identify common field patterns across discovered indices"""
        # Find most common field names across indices
        field_frequency = {}
        
        for index_info in self.discovered_indices.values():
            for field_type, fields in index_info['fields'].items():
                for field in fields:
                    if field not in field_frequency:
                        field_frequency[field] = {'count': 0, 'type': field_type}
                    field_frequency[field]['count'] += 1
        
        # Identify commonly available fields for testing
        total_indices = len(self.discovered_indices)
        self.common_fields = {
            'timestamp': [],
            'text': [],
            'keyword': [],
            'numeric': []
        }
        
        for field, info in field_frequency.items():
            # Include fields present in at least 30% of indices
            if info['count'] >= max(1, total_indices * 0.3):
                field_type = info['type']
                if 'timestamp' in field_type:
                    self.common_fields['timestamp'].append(field)
                elif 'text' in field_type:
                    self.common_fields['text'].append(field)
                elif 'keyword' in field_type:
                    self.common_fields['keyword'].append(field)
                elif 'numeric' in field_type:
                    self.common_fields['numeric'].append(field)
        
        logger.info(f"Common fields identified: {dict(self.common_fields)}")

    # =================== BASIC CONNECTIVITY TESTS ===================
    
    def test_elasticsearch_connection(self):
        """Test basic Elasticsearch connectivity"""
        try:
            start = time.time()
            info = self.es.info()
            duration = time.time() - start
            
            version = info['version']['number']
            cluster_name = info['cluster_name']
            
            self.log_test_result(
                "Elasticsearch Connection",
                True,
                duration,
                f"Version: {version}, Cluster: {cluster_name}"
            )
            return True
        except Exception as e:
            self.log_test_result("Elasticsearch Connection", False, details=str(e))
            return False
    
    def test_kibana_connection(self):
        """Test Kibana connectivity"""
        try:
            start = time.time()
            auth = (self.username, self.password) 
            response = requests.get(f"{self.kibana_url}/api/status", timeout=10, auth=auth)
            duration = time.time() - start
            
            if response.status_code == 200:
                status_data = response.json()
                version = status_data.get('version', {}).get('number', 'unknown')
                self.log_test_result(
                    "Kibana Connection",
                    True,
                    duration,
                    f"Version: {version}, Status: {response.status_code}"
                )
                return True
            else:
                self.log_test_result("Kibana Connection", False, details=f"Status: {response.status_code}")
                return False
        except Exception as e:
            self.log_test_result("Kibana Connection", False, details=str(e))
            return False
    
    # =================== CLUSTER HEALTH TESTS ===================
    
    def test_cluster_health(self):
        """Test cluster health and performance"""
        try:
            start = time.time()
            health = self.es.cluster.health()
            duration = time.time() - start
            
            status = health['status']
            nodes = health['number_of_nodes']
            active_shards = health['active_shards']
            
            is_healthy = status in ['green', 'yellow']
            performance_ok = duration < self.performance_targets['cluster_health_time']
            
            self.log_test_result(
                "Cluster Health",
                is_healthy and performance_ok,
                duration,
                f"Status: {status}, Nodes: {nodes}, Shards: {active_shards}"
            )
            return is_healthy
        except Exception as e:
            self.log_test_result("Cluster Health", False, details=str(e))
            return False
    
    def test_node_stats(self):
        """Test node statistics and resource usage"""
        try:
            start = time.time()
            stats = self.es.nodes.stats()
            duration = time.time() - start
            
            node_info = []
            total_heap_used = 0
            total_heap_max = 0
            
            for node_id, node in stats['nodes'].items():
                jvm = node['jvm']
                heap_used_percent = jvm['mem']['heap_used_percent']
                heap_used = jvm['mem']['heap_used_in_bytes']
                heap_max = jvm['mem']['heap_max_in_bytes']
                
                total_heap_used += heap_used
                total_heap_max += heap_max
                
                node_info.append(f"Node {node_id[:8]}: {heap_used_percent}% heap")
            
            overall_heap_percent = (total_heap_used / total_heap_max) * 100 if total_heap_max > 0 else 0
            memory_healthy = overall_heap_percent < 85  # Less than 85% heap usage
            
            self.log_test_result(
                "Node Statistics",
                memory_healthy,
                duration,
                f"Heap usage: {overall_heap_percent:.1f}%, Nodes: {len(node_info)}"
            )
            return memory_healthy
        except Exception as e:
            self.log_test_result("Node Statistics", False, details=str(e))
            return False
    
    # =================== INDEX MANAGEMENT TESTS ===================
    
    def test_index_existence(self):
        """Test that discovered indices exist and are accessible"""
        try:
            start = time.time()
            accessible_indices = []
            inaccessible_indices = []
            total_docs = 0
            
            for index in self.test_indices:
                try:
                    if self.es.indices.exists(index=index):
                        count = self.es.count(index=index)['count']
                        accessible_indices.append({'name': index, 'docs': count})
                        total_docs += count
                    else:
                        inaccessible_indices.append(index)
                except Exception as e:
                    inaccessible_indices.append(f"{index} (error: {str(e)[:50]})")
            
            duration = time.time() - start
            all_accessible = len(inaccessible_indices) == 0
            
            details = f"Accessible: {len(accessible_indices)} indices with {total_docs:,} total docs"
            if inaccessible_indices:
                details += f", Inaccessible: {len(inaccessible_indices)} indices"
            
            self.log_test_result("Index Existence", all_accessible, duration, details)
            return all_accessible
        except Exception as e:
            self.log_test_result("Index Existence", False, details=str(e))
            return False
    
    def test_index_mappings(self):
        """Test index mappings and field types for discovered indices"""
        try:
            start = time.time()
            mapping_issues = []
            analyzed_indices = 0
            total_fields = 0
            
            for index in self.test_indices:
                if not self.es.indices.exists(index=index):
                    continue
                    
                try:
                    mapping = self.es.indices.get_mapping(index=index)
                    properties = mapping[index]['mappings'].get('properties', {})
                    total_fields += len(properties)
                    analyzed_indices += 1
                    
                    # Check for basic timestamp field (most indices should have one)
                    timestamp_fields = [f for f in properties.keys() 
                                     if '@timestamp' in f or 'timestamp' in f.lower() or 'time' in f.lower()]
                    
                    if not timestamp_fields:
                        mapping_issues.append(f"{index}: no timestamp field found")
                    
                    # Check for field type consistency
                    problematic_fields = []
                    for field_name, field_config in properties.items():
                        field_type = field_config.get('type', 'object')
                        if field_type is None:
                            problematic_fields.append(field_name)
                    
                    if problematic_fields:
                        mapping_issues.append(f"{index}: {len(problematic_fields)} fields with undefined types")
                        
                except Exception as e:
                    mapping_issues.append(f"{index}: mapping analysis failed - {str(e)[:50]}")
            
            duration = time.time() - start
            mappings_ok = len(mapping_issues) == 0
            
            details = f"Analyzed {analyzed_indices} indices with {total_fields} total fields"
            if mapping_issues:
                details += f", Issues: {len(mapping_issues)} found"
            
            self.log_test_result("Index Mappings", mappings_ok, duration, details)
            return mappings_ok
        except Exception as e:
            self.log_test_result("Index Mappings", False, details=str(e))
            return False
    
    def test_index_settings_analysis(self):
        """Test index settings and shard distribution analysis (read-only)"""
        try:
            start = time.time()
            settings_issues = []
            total_shards = 0
            total_indices = 0
            
            for index in self.test_indices:
                if not self.es.indices.exists(index=index):
                    continue
                    
                try:
                    # Get index settings (read-only)
                    settings = self.es.indices.get_settings(index=index)
                    index_settings = settings[index]['settings']['index']
                    
                    total_indices += 1
                    
                    # Analyze shard configuration
                    shards = int(index_settings.get('number_of_shards', 1))
                    replicas = int(index_settings.get('number_of_replicas', 0))
                    total_shards += shards * (replicas + 1)
                    
                    # Check for potential issues
                    if shards > 5:
                        settings_issues.append(f"{index}: high shard count ({shards})")
                    
                    if replicas > 2:
                        settings_issues.append(f"{index}: high replica count ({replicas})")
                    
                except Exception as e:
                    settings_issues.append(f"{index}: settings read failed - {str(e)[:50]}")
            
            duration = time.time() - start
            settings_ok = len(settings_issues) == 0
            
            avg_shards_per_index = total_shards / total_indices if total_indices > 0 else 0
            details = f"Analyzed {total_indices} indices, {total_shards} total shards, avg {avg_shards_per_index:.1f} per index"
            if settings_issues:
                details += f", Issues: {len(settings_issues)} found"
            
            self.log_test_result("Index Settings Analysis", settings_ok, duration, details)
            return settings_ok
            
        except Exception as e:
            self.log_test_result("Index Settings Analysis", False, details=str(e))
            return False
    
    # =================== SEARCH PERFORMANCE TESTS ===================
    
    def test_basic_search_performance(self):
        """Test basic search query performance with dynamic field detection"""
        # Build queries dynamically based on discovered fields
        base_queries = [{"match_all": {}}]
        
        # Add queries based on common fields
        if self.common_fields['timestamp']:
            timestamp_field = self.common_fields['timestamp'][0]
            base_queries.append({"range": {timestamp_field: {"gte": "now-1d"}}})
        
        if self.common_fields['keyword']:
            # Try common keyword field patterns
            for keyword_field in self.common_fields['keyword'][:2]:  # Test top 2 keyword fields
                if 'level' in keyword_field.lower():
                    base_queries.append({"terms": {keyword_field: ["ERROR", "error", "WARN", "warn"]}})
                elif 'status' in keyword_field.lower():
                    base_queries.append({"terms": {keyword_field: ["200", "404", "500"]}})
                else:
                    base_queries.append({"exists": {"field": keyword_field}})
        
        if self.common_fields['text']:
            # Add wildcard search on text fields
            text_field = self.common_fields['text'][0]
            base_queries.extend([
                {"wildcard": {text_field: "*error*"}},
                {"wildcard": {text_field: "*user*"}}
            ])
        
        if self.common_fields['numeric']:
            # Add range query on numeric fields
            numeric_field = self.common_fields['numeric'][0]
            base_queries.append({"range": {numeric_field: {"gte": 0}}})
        
        # Fallback queries if no common fields found
        if len(base_queries) == 1:  # Only match_all
            base_queries.extend([
                {"wildcard": {"message": "*error*"}},
                {"wildcard": {"log": "*user*"}},
                {"exists": {"field": "@timestamp"}},
                {"exists": {"field": "timestamp"}}
            ])
        
        queries = base_queries
        
        total_tests = 0
        passed_tests = 0
        response_times = []
        
        for index in self.test_indices:
            if not self.es.indices.exists(index=index):
                continue
                
            for i, query in enumerate(queries):
                try:
                    start = time.time()
                    response = self.es.search(
                        index=index,
                        body={"query": query, "size": 1000},
                        timeout="30s"
                    )
                    duration = time.time() - start
                    
                    response_times.append(duration * 1000)  # Convert to ms
                    total_tests += 1
                    
                    if duration * 1000 < self.performance_targets['search_latency_ms']:
                        passed_tests += 1
                
                except Exception as e:
                    total_tests += 1
                    logger.warning(f"Search query {i} failed on {index}: {e}")
        
        avg_response_time = statistics.mean(response_times) if response_times else float('inf')
        success_rate = (passed_tests / total_tests) * 100 if total_tests > 0 else 0
        
        performance_ok = success_rate >= 80 and avg_response_time < self.performance_targets['search_latency_ms']
        
        self.log_test_result(
            "Basic Search Performance",
            performance_ok,
            avg_response_time / 1000,
            f"Success rate: {success_rate:.1f}%, Avg: {avg_response_time:.1f}ms"
        )
        return performance_ok
    
    def test_complex_aggregation_performance(self):
        """Test complex aggregation query performance with dynamic fields"""
        # Build aggregation dynamically based on discovered fields
        aggs = {}
        
        # Add timestamp histogram if timestamp field exists
        if self.common_fields['timestamp']:
            timestamp_field = self.common_fields['timestamp'][0]
            aggs["timestamp_histogram"] = {
                "date_histogram": {
                    "field": timestamp_field,
                    "calendar_interval": "1h"
                }
            }
        
        # Add terms aggregation on keyword fields
        if self.common_fields['keyword']:
            keyword_field = self.common_fields['keyword'][0]
            aggs["top_terms"] = {
                "terms": {"field": keyword_field, "size": 10}
            }
            
            # Nested aggregation if we have timestamp
            if self.common_fields['timestamp']:
                timestamp_field = self.common_fields['timestamp'][0]
                aggs["top_terms"]["aggs"] = {
                    "hourly": {
                        "date_histogram": {
                            "field": timestamp_field,
                            "calendar_interval": "1h"
                        }
                    }
                }
        
        # Add numeric aggregations if numeric fields exist
        if self.common_fields['numeric']:
            numeric_field = self.common_fields['numeric'][0]
            aggs["numeric_stats"] = {
                "extended_stats": {"field": numeric_field}
            }
            aggs["percentiles"] = {
                "percentiles": {"field": numeric_field}
            }
        
        # Add cardinality aggregations for high-cardinality fields
        if len(self.common_fields['keyword']) > 1:
            aggs["cardinality_check"] = {
                "cardinality": {"field": self.common_fields['keyword'][1]}
            }
        
        # Fallback aggregation if no fields discovered
        if not aggs:
            aggs = {
                "sample_agg": {
                    "terms": {"field": "_index", "size": 5}
                }
            }
        
        aggregation_query = {
            "size": 0,
            "aggs": aggs
        }
        
        response_times = []
        successful_queries = 0
        
        for index in self.test_indices:
            if not self.es.indices.exists(index=index):
                continue
                
            try:
                start = time.time()
                response = self.es.search(
                    index=index,
                    body=aggregation_query,
                    timeout="60s"
                )
                duration = time.time() - start
                
                response_times.append(duration * 1000)
                successful_queries += 1
                
            except Exception as e:
                logger.warning(f"Complex aggregation failed on {index}: {e}")
        
        avg_response_time = statistics.mean(response_times) if response_times else float('inf')
        performance_ok = (
            successful_queries > 0 and 
            avg_response_time < self.performance_targets['complex_query_ms']
        )
        
        self.log_test_result(
            "Complex Aggregation Performance",
            performance_ok,
            avg_response_time / 1000,
            f"Successful: {successful_queries}/{len(self.test_indices)}, Avg: {avg_response_time:.1f}ms"
        )
        return performance_ok
    
    def test_concurrent_search_performance(self):
        """Test concurrent search performance"""
        def run_search(index, query_id):
            try:
                start = time.time()
                response = self.es.search(
                    index=index,
                    body={
                        "query": {"match_all": {}},
                        "size": 5000,
                        "sort": [{"@timestamp": {"order": "desc"}}]
                    },
                    timeout="30s"
                )
                duration = time.time() - start
                return query_id, duration, True, response['hits']['total']['value']
            except Exception as e:
                return query_id, 0, False, str(e)
        
        # Run concurrent searches
        concurrent_queries = 10
        results = []
        
        start_time = time.time()
        with ThreadPoolExecutor(max_workers=5) as executor:
            futures = []
            for i in range(concurrent_queries):
                index = self.test_indices[i % len(self.test_indices)]
                if self.es.indices.exists(index=index):
                    future = executor.submit(run_search, index, i)
                    futures.append(future)
            
            for future in as_completed(futures):
                results.append(future.result())
        
        total_duration = time.time() - start_time
        
        successful = [r for r in results if r[2]]
        avg_query_time = statistics.mean([r[1] for r in successful]) if successful else float('inf')
        success_rate = len(successful) / len(results) * 100 if results else 0
        
        performance_ok = success_rate >= 90 and avg_query_time < 1.0
        
        self.log_test_result(
            "Concurrent Search Performance",
            performance_ok,
            total_duration,
            f"Success: {success_rate:.1f}%, Avg query: {avg_query_time*1000:.1f}ms"
        )
        return performance_ok
    
    # =================== DATA INTEGRITY TESTS ===================
    
    def test_data_integrity(self):
        """Test data integrity and consistency"""
        integrity_issues = []
        total_docs = 0
        
        for index in self.test_indices:
            if not self.es.indices.exists(index=index):
                continue
                
            try:
                # Check document count consistency
                count1 = self.es.count(index=index)['count']
                time.sleep(0.1)  # Small delay
                count2 = self.es.count(index=index)['count']
                
                if count1 != count2:
                    integrity_issues.append(f"{index}: count inconsistency ({count1} vs {count2})")
                
                total_docs += count1
                
                # Check for required fields based on discovered structure
                sample = self.es.search(
                    index=index,
                    body={"query": {"match_all": {}}, "size": 100}
                )
                
                # Check for timestamp fields
                missing_timestamp = 0
                timestamp_fields = []
                if index in self.discovered_indices:
                    timestamp_fields = self.discovered_indices[index]['fields']['timestamp_fields']
                
                # Fallback to common timestamp field names
                if not timestamp_fields:
                    timestamp_fields = ['@timestamp', 'timestamp', 'time', 'created_at', 'updated_at']
                
                for hit in sample['hits']['hits']:
                    source = hit['_source']
                    has_timestamp = any(ts_field in source for ts_field in timestamp_fields)
                    if not has_timestamp:
                        missing_timestamp += 1
                
                if missing_timestamp > 10:  # Allow some flexibility
                    integrity_issues.append(f"{index}: {missing_timestamp}/100 docs missing timestamp fields")
                
                # Check for field consistency across documents
                field_consistency = {}
                for hit in sample['hits']['hits']:
                    for field in hit['_source'].keys():
                        if field not in field_consistency:
                            field_consistency[field] = 0
                        field_consistency[field] += 1
                
                # Identify fields that should be consistent but aren't
                inconsistent_fields = []
                for field, count in field_consistency.items():
                    if count < len(sample['hits']['hits']) * 0.8:  # Present in less than 80% of docs
                        if field in ['id', 'level', 'status', 'type']:  # Core fields that should be consistent
                            inconsistent_fields.append(field)
                
                if inconsistent_fields:
                    integrity_issues.append(f"{index}: inconsistent fields {inconsistent_fields[:3]}")
                
            except Exception as e:
                integrity_issues.append(f"{index}: {str(e)}")
        
        integrity_ok = len(integrity_issues) == 0
        details = f"Total docs: {total_docs}"
        if integrity_issues:
            details += f", Issues: {integrity_issues[:3]}"  # Show first 3 issues
        
        self.log_test_result("Data Integrity", integrity_ok, details=details)
        return integrity_ok
    
    def test_edge_case_handling(self):
        """Test handling of edge cases in data with discovered fields"""
        # Build edge case tests dynamically based on available fields
        edge_case_tests = {}
        
        # Test for special characters in text fields
        if self.common_fields['text']:
            text_field = self.common_fields['text'][0]
            edge_case_tests["Special Characters"] = {"wildcard": {text_field: "*@*"}}
            edge_case_tests["Unicode Content"] = {"wildcard": {text_field: "*\\u*"}}
        
        # Test for nested objects
        if self.common_fields.get('nested'):
            nested_field = self.common_fields['nested'][0]
            edge_case_tests["Nested Objects"] = {"exists": {"field": nested_field}}
        
        # Test numeric field edge cases
        if self.common_fields['numeric']:
            numeric_field = self.common_fields['numeric'][0]
            edge_case_tests["Zero Values"] = {"term": {numeric_field: 0}}
            edge_case_tests["Negative Values"] = {"range": {numeric_field: {"lt": 0}}}
        
        # Test keyword field variations
        if self.common_fields['keyword']:
            keyword_field = self.common_fields['keyword'][0]
            edge_case_tests["Empty Keywords"] = {"term": {keyword_field: ""}}
            edge_case_tests["Missing Keywords"] = {"bool": {"must_not": {"exists": {"field": keyword_field}}}}
        
        # Test timestamp edge cases
        if self.common_fields['timestamp']:
            timestamp_field = self.common_fields['timestamp'][0]
            edge_case_tests["Old Timestamps"] = {"range": {timestamp_field: {"lt": "2020-01-01"}}}
            edge_case_tests["Future Timestamps"] = {"range": {timestamp_field: {"gt": "2030-01-01"}}}
        
        # Fallback tests if no specific fields found
        if not edge_case_tests:
            edge_case_tests = {
                "Large Documents": {"script": {"script": "_source.toString().length() > 10000"}},
                "Empty Documents": {"bool": {"must_not": {"exists": {"field": "*"}}}},
                "System Fields": {"exists": {"field": "_type"}},
                "Metadata Fields": {"wildcard": {"_*": "*"}}
            }
        
        edge_cases_found = {}
        
        for test_name, query in edge_case_tests.items():
            total_hits = 0
            for index in self.test_indices:
                if not self.es.indices.exists(index=index):
                    continue
                    
                try:
                    response = self.es.search(
                        index=index,
                        body={"query": query, "size": 0}
                    )
                    hits = response['hits']['total']['value']
                    total_hits += hits
                except:
                    pass  # Some queries may not work on all indices
            
            edge_cases_found[test_name] = total_hits
        
        # Check if we found edge cases (should have some for comprehensive testing)
        found_cases = sum(1 for count in edge_cases_found.values() if count > 0)
        edge_cases_ok = found_cases >= 3  # At least 3 types of edge cases
        
        self.log_test_result(
            "Edge Case Handling",
            edge_cases_ok,
            details=f"Found {found_cases}/5 edge case types: {edge_cases_found}"
        )
        return edge_cases_ok
    
    # =================== INDEXING PERFORMANCE TESTS ===================
    
    def test_index_stats_performance(self):
        """Test index statistics and document distribution analysis (read-only)"""
        try:
            start = time.time()
            performance_issues = []
            total_docs = 0
            total_size_bytes = 0
            
            for index in self.test_indices:
                if not self.es.indices.exists(index=index):
                    continue
                    
                try:
                    # Get index stats (read-only)
                    stats = self.es.indices.stats(index=index)
                    index_stats = stats['indices'][index]
                    
                    # Analyze document count and size
                    doc_count = index_stats['total']['docs']['count']
                    size_bytes = index_stats['total']['store']['size_in_bytes']
                    
                    total_docs += doc_count
                    total_size_bytes += size_bytes
                    
                    # Calculate metrics
                    if doc_count > 0:
                        avg_doc_size = size_bytes / doc_count
                        docs_per_mb = doc_count / (size_bytes / 1024 / 1024) if size_bytes > 0 else 0
                        
                        # Check for potential performance issues
                        if avg_doc_size > 100000:  # > 100KB per doc
                            performance_issues.append(f"{index}: large avg doc size ({avg_doc_size/1024:.1f}KB)")
                        
                        if doc_count > 10000000:  # > 10M docs
                            performance_issues.append(f"{index}: very large index ({doc_count:,} docs)")
                    
                except Exception as e:
                    performance_issues.append(f"{index}: stats read failed - {str(e)[:50]}")
            
            duration = time.time() - start
            
            # Calculate overall metrics
            avg_doc_size = total_size_bytes / total_docs if total_docs > 0 else 0
            total_size_mb = total_size_bytes / 1024 / 1024
            
            performance_ok = len(performance_issues) == 0 and duration < 10  # Should be fast read operation
            
            details = f"Analyzed {len(self.test_indices)} indices: {total_docs:,} docs, {total_size_mb:.1f}MB, avg {avg_doc_size:.0f}B/doc"
            if performance_issues:
                details += f", Issues: {len(performance_issues)} found"
            
            self.log_test_result("Index Stats Performance", performance_ok, duration, details)
            return performance_ok
            
        except Exception as e:
            self.log_test_result("Index Stats Performance", False, details=str(e))
            return False
    
    # =================== RESILIENCE TESTS ===================
    
    def test_query_timeout_handling(self):
        """Test query timeout handling"""
        timeout_query = {
            "size": 0,
            "aggs": {
                "complex_nested": {
                    "terms": {"field": "level.keyword", "size": 1000},
                    "aggs": {
                        "nested_terms": {
                            "terms": {"field": "service.name.keyword", "size": 1000},
                            "aggs": {
                                "deep_nested": {
                                    "date_histogram": {
                                        "field": "@timestamp",
                                        "calendar_interval": "1m"
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
        
        timeout_handled = 0
        total_tests = 0
        
        for index in self.test_indices:
            if not self.es.indices.exists(index=index):
                continue
                
            total_tests += 1
            try:
                # Use very short timeout to force timeout
                response = self.es.search(
                    index=index,
                    body=timeout_query,
                    timeout="1ms"  # Very short timeout
                )
                # If it completes, that's also fine
                timeout_handled += 1
            except Exception as e:
                if "timeout" in str(e).lower():
                    timeout_handled += 1  # Properly handled timeout
                else:
                    logger.warning(f"Unexpected error in timeout test: {e}")
        
        resilience_ok = timeout_handled == total_tests
        
        self.log_test_result(
            "Query Timeout Handling",
            resilience_ok,
            details=f"Handled: {timeout_handled}/{total_tests}"
        )
        return resilience_ok
    
    # =================== STRESS TESTS ===================
    
    def test_large_dataset_scan(self):
        """Stress test: Scan through large portions of data"""
        try:
            total_scanned = 0
            scan_times = []
            
            for index in self.test_indices:
                if not self.es.indices.exists(index=index):
                    continue
                
                start = time.time()
                
                # Use scroll to scan through large amounts of data
                response = self.es.search(
                    index=index,
                    scroll='2m',
                    size=10000,
                    body={
                        "query": {"match_all": {}},
                        "sort": [{"@timestamp": {"order": "desc"}}]
                    }
                )
                
                scroll_id = response['_scroll_id']
                hits = response['hits']['hits']
                total_scanned += len(hits)
                
                # Continue scrolling for up to 5 iterations (50k docs max per index)
                scroll_count = 0
                while hits and scroll_count < 5:
                    try:
                        response = self.es.scroll(
                            scroll_id=scroll_id,
                            scroll='2m'
                        )
                        hits = response['hits']['hits']
                        total_scanned += len(hits)
                        scroll_count += 1
                    except Exception:
                        break
                
                # Clear scroll
                try:
                    self.es.clear_scroll(scroll_id=scroll_id)
                except:
                    pass
                
                duration = time.time() - start
                scan_times.append(duration * 1000)
            
            avg_scan_time = statistics.mean(scan_times) if scan_times else float('inf')
            performance_ok = avg_scan_time < self.performance_targets['large_scan_ms']
            
            self.log_test_result(
                "Large Dataset Scan",
                performance_ok,
                avg_scan_time / 1000,
                f"Scanned {total_scanned:,} docs, Avg: {avg_scan_time:.1f}ms per index"
            )
            return performance_ok
            
        except Exception as e:
            self.log_test_result("Large Dataset Scan", False, details=str(e))
            return False
    
    def test_memory_intensive_aggregations(self):
        """Stress test: Memory-intensive aggregations across large datasets"""
        try:
            heavy_agg_query = {
                "size": 0,
                "aggs": {
                    "timestamp_histogram": {
                        "date_histogram": {
                            "field": "@timestamp",
                            "calendar_interval": "1m"
                        },
                        "aggs": {
                            "level_terms": {
                                "terms": {
                                    "field": "level.keyword",
                                    "size": 100
                                },
                                "aggs": {
                                    "service_terms": {
                                        "terms": {
                                            "field": "service.name.keyword",
                                            "size": 50
                                        },
                                        "aggs": {
                                            "response_stats": {
                                                "extended_stats": {
                                                    "field": "response.duration_ms"
                                                }
                                            },
                                            "percentiles": {
                                                "percentiles": {
                                                    "field": "response.duration_ms",
                                                    "percents": [50, 75, 90, 95, 99]
                                                }
                                            }
                                        }
                                    }
                                }
                            }
                        }
                    },
                    "cardinality_user": {
                        "cardinality": {
                            "field": "user.id"
                        }
                    },
                    "cardinality_ip": {
                        "cardinality": {
                            "field": "user.ip_address"
                        }
                    }
                }
            }
            
            response_times = []
            successful_queries = 0
            
            for index in self.test_indices:
                if not self.es.indices.exists(index=index):
                    continue
                
                try:
                    start = time.time()
                    response = self.es.search(
                        index=index,
                        body=heavy_agg_query,
                        timeout="120s"
                    )
                    duration = time.time() - start
                    
                    response_times.append(duration * 1000)
                    successful_queries += 1
                    
                except Exception as e:
                    logger.warning(f"Memory-intensive aggregation failed on {index}: {e}")
            
            avg_response_time = statistics.mean(response_times) if response_times else float('inf')
            performance_ok = (
                successful_queries > 0 and 
                avg_response_time < self.performance_targets['memory_scan_ms']
            )
            
            self.log_test_result(
                "Memory Intensive Aggregations",
                performance_ok,
                avg_response_time / 1000,
                f"Successful: {successful_queries}/{len(self.test_indices)}, Avg: {avg_response_time:.1f}ms"
            )
            return performance_ok
            
        except Exception as e:
            self.log_test_result("Memory Intensive Aggregations", False, details=str(e))
            return False
    
    def test_concurrent_stress_load(self):
        """Stress test: High concurrent load with complex queries"""
        def stress_query(index, query_type, query_id):
            queries = {
                'heavy_search': {
                    "query": {
                        "bool": {
                            "must": [
                                {"range": {"@timestamp": {"gte": "now-30d"}}},
                                {"wildcard": {"message": "*error*"}}
                            ]
                        }
                    },
                    "size": 2000,
                    "sort": [{"@timestamp": {"order": "desc"}}]
                },
                'complex_agg': {
                    "size": 0,
                    "aggs": {
                        "levels": {
                            "terms": {"field": "level.keyword", "size": 50},
                            "aggs": {
                                "hourly": {
                                    "date_histogram": {
                                        "field": "@timestamp",
                                        "calendar_interval": "1h"
                                    }
                                }
                            }
                        }
                    }
                },
                'full_text_search': {
                    "query": {
                        "multi_match": {
                            "query": "authentication login user",
                            "fields": ["message", "logger", "error.message"]
                        }
                    },
                    "size": 1000
                }
            }
            
            try:
                start = time.time()
                response = self.es.search(
                    index=index,
                    body=queries[query_type],
                    timeout="60s"
                )
                duration = time.time() - start
                
                doc_count = response['hits']['total']['value'] if 'hits' in response else 0
                return query_id, duration, True, doc_count, query_type
            except Exception as e:
                return query_id, 0, False, str(e), query_type
        
        # Run high concurrent load - 30 queries across 10 workers
        concurrent_queries = 30
        max_workers = 10
        results = []
        
        start_time = time.time()
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = []
            
            for i in range(concurrent_queries):
                index = self.test_indices[i % len(self.test_indices)]
                query_types = ['heavy_search', 'complex_agg', 'full_text_search']
                query_type = query_types[i % len(query_types)]
                
                if self.es.indices.exists(index=index):
                    future = executor.submit(stress_query, index, query_type, i)
                    futures.append(future)
            
            for future in as_completed(futures):
                results.append(future.result())
        
        total_duration = time.time() - start_time
        
        successful = [r for r in results if r[2]]
        failed = [r for r in results if not r[2]]
        
        if successful:
            avg_query_time = statistics.mean([r[1] for r in successful]) * 1000
            success_rate = len(successful) / len(results) * 100
        else:
            avg_query_time = float('inf')
            success_rate = 0
        
        performance_ok = (
            success_rate >= 80 and 
            total_duration * 1000 < self.performance_targets['concurrent_stress_ms']
        )
        
        self.log_test_result(
            "Concurrent Stress Load",
            performance_ok,
            total_duration,
            f"Success: {success_rate:.1f}%, Total: {total_duration:.1f}s, Avg query: {avg_query_time:.1f}ms"
        )
        return performance_ok
    
    def test_large_result_set_handling(self):
        """Stress test: Handle large result sets and deep pagination"""
        try:
            large_result_times = []
            total_docs_retrieved = 0
            
            for index in self.test_indices:
                if not self.es.indices.exists(index=index):
                    continue
                
                try:
                    # Test large result set retrieval
                    start = time.time()
                    response = self.es.search(
                        index=index,
                        body={
                            "query": {"match_all": {}},
                            "size": 10000,  # Large result set
                            "sort": [{"@timestamp": {"order": "desc"}}]
                        },
                        timeout="60s"
                    )
                    duration = time.time() - start
                    
                    docs_retrieved = len(response['hits']['hits'])
                    total_docs_retrieved += docs_retrieved
                    large_result_times.append(duration * 1000)
                    
                    # Test deep pagination
                    if docs_retrieved > 0:
                        start = time.time()
                        deep_response = self.es.search(
                            index=index,
                            body={
                                "query": {"match_all": {}},
                                "size": 1000,
                                "from": 50000,  # Deep pagination
                                "sort": [{"@timestamp": {"order": "desc"}}]
                            },
                            timeout="60s"
                        )
                        duration = time.time() - start
                        large_result_times.append(duration * 1000)
                    
                except Exception as e:
                    logger.warning(f"Large result set test failed on {index}: {e}")
            
            avg_time = statistics.mean(large_result_times) if large_result_times else float('inf')
            performance_ok = avg_time < self.performance_targets['large_scan_ms']
            
            self.log_test_result(
                "Large Result Set Handling",
                performance_ok,
                avg_time / 1000,
                f"Retrieved {total_docs_retrieved:,} docs, Avg: {avg_time:.1f}ms"
            )
            return performance_ok
            
        except Exception as e:
            self.log_test_result("Large Result Set Handling", False, details=str(e))
            return False
    
    def test_sustained_load_endurance(self):
        """Stress test: Sustained load over extended period"""
        try:
            endurance_duration = 300  # 5 minutes of sustained load
            query_interval = 2  # Query every 2 seconds
            
            queries = [
                {"match_all": {}},
                {"range": {"@timestamp": {"gte": "now-24h"}}},
                {"term": {"level.keyword": "ERROR"}},
                {"wildcard": {"message": "*user*"}},
                {"exists": {"field": "response.duration_ms"}}
            ]
            
            start_time = time.time()
            query_count = 0
            success_count = 0
            response_times = []
            
            logger.info(f"Starting {endurance_duration}s sustained load test...")
            
            while (time.time() - start_time) < endurance_duration:
                for index in self.test_indices:
                    if not self.es.indices.exists(index=index):
                        continue
                    
                    query = queries[query_count % len(queries)]
                    
                    try:
                        query_start = time.time()
                        response = self.es.search(
                            index=index,
                            body={
                                "query": query,
                                "size": 500,
                                "timeout": "30s"
                            }
                        )
                        query_duration = time.time() - query_start
                        
                        response_times.append(query_duration * 1000)
                        success_count += 1
                        
                    except Exception as e:
                        logger.warning(f"Sustained load query failed: {e}")
                    
                    query_count += 1
                    
                    # Check if we should continue
                    if (time.time() - start_time) >= endurance_duration:
                        break
                
                time.sleep(query_interval)
            
            total_duration = time.time() - start_time
            success_rate = (success_count / query_count) * 100 if query_count > 0 else 0
            avg_response_time = statistics.mean(response_times) if response_times else float('inf')
            
            performance_ok = success_rate >= 90 and avg_response_time < 1000
            
            self.log_test_result(
                "Sustained Load Endurance",
                performance_ok,
                total_duration,
                f"Duration: {total_duration:.1f}s, Queries: {query_count}, Success: {success_rate:.1f}%, Avg: {avg_response_time:.1f}ms"
            )
            return performance_ok
            
        except Exception as e:
            self.log_test_result("Sustained Load Endurance", False, details=str(e))
            return False
    
    # =================== MAIN TEST EXECUTION ===================
    
    def run_comprehensive_test_suite(self):
        """Run the test suite based on selected mode"""
        self.start_time = time.time()
        
        mode_config = self.test_mode_configs[self.test_mode]
        
        logger.info("="*80)
        logger.info(f"STARTING ELK STACK TEST SUITE - {self.test_mode.upper()} MODE")
        logger.info("="*80)
        logger.info(f"Mode: {mode_config['description']}")
        logger.info(f"Estimated duration: {mode_config['duration_minutes']} minutes")
        logger.info(f"Started at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        logger.info("="*80)
        
        # Define all test categories
        all_test_categories = {
            "connectivity": ("Basic Connectivity", [
                self.test_elasticsearch_connection,
                self.test_kibana_connection
            ]),
            "cluster_health": ("Cluster Health", [
                self.test_cluster_health,
                self.test_node_stats
            ]),
            "index_management": ("Index Management", [
                self.test_index_existence,
                self.test_index_mappings,
                self.test_index_settings_analysis
            ]),
            "search_performance": ("Search Performance", [
                self.test_basic_search_performance,
                self.test_complex_aggregation_performance,
                self.test_concurrent_search_performance
            ]),
            "data_integrity": ("Data Integrity", [
                self.test_data_integrity,
                self.test_edge_case_handling
            ]),
            "indexing_performance": ("Index Statistics", [
                self.test_index_stats_performance
            ]),
            "resilience": ("Resilience", [
                self.test_query_timeout_handling
            ]),
            "stress_tests": ("Stress Tests", [
                self.test_large_dataset_scan,
                self.test_memory_intensive_aggregations,
                self.test_concurrent_stress_load,
                self.test_large_result_set_handling,
                self.test_sustained_load_endurance
            ])
        }
        
        # Special handling for basic_search mode
        if self.test_mode == 'basic':
            all_test_categories["basic_search"] = ("Basic Search", [
                self.test_basic_search_performance
            ])
        
        # Filter test categories based on mode
        test_categories = []
        for test_key in mode_config['tests']:
            if test_key in all_test_categories:
                test_categories.append(all_test_categories[test_key])
        
        total_tests = sum(len(tests) for _, tests in test_categories)
        current_test = 0
        max_duration = mode_config['duration_minutes'] * 60  # Convert to seconds
        
        for category_name, tests in test_categories:
            # Check if we've exceeded time limit
            elapsed_time = time.time() - self.start_time
            if elapsed_time >= max_duration:
                logger.warning(f"Time limit ({mode_config['duration_minutes']} minutes) exceeded. Stopping tests.")
                break
            logger.info(f"\n--- {category_name.upper()} TESTS ---")
            
            for test_func in tests:
                # Check time limit before each test
                elapsed_time = time.time() - self.start_time
                if elapsed_time >= max_duration:
                    logger.warning(f"Time limit ({mode_config['duration_minutes']} minutes) exceeded. Stopping tests.")
                    break
                    
                current_test += 1
                progress = (current_test / total_tests) * 100
                
                # Calculate elapsed time
                elapsed_time = time.time() - self.start_time
                elapsed_hours = int(elapsed_time // 3600)
                elapsed_minutes = int((elapsed_time % 3600) // 60)
                elapsed_seconds = int(elapsed_time % 60)
                
                if elapsed_hours > 0:
                    elapsed_str = f"{elapsed_hours}h {elapsed_minutes}m {elapsed_seconds}s"
                elif elapsed_minutes > 0:
                    elapsed_str = f"{elapsed_minutes}m {elapsed_seconds}s"
                else:
                    elapsed_str = f"{elapsed_seconds}s"
                
                # Calculate estimated remaining time
                if progress > 0:
                    estimated_total = (elapsed_time / progress) * 100
                    remaining_time = max(0, estimated_total - elapsed_time)
                    
                    remaining_hours = int(remaining_time // 3600)
                    remaining_minutes = int((remaining_time % 3600) // 60)
                    remaining_seconds = int(remaining_time % 60)
                    
                    if remaining_hours > 0:
                        eta_str = f"{remaining_hours}h {remaining_minutes}m {remaining_seconds}s"
                    elif remaining_minutes > 0:
                        eta_str = f"{remaining_minutes}m {remaining_seconds}s"
                    else:
                        eta_str = f"{remaining_seconds}s"
                else:
                    eta_str = "calculating..."
                
                # Format total estimated time
                est_total_hours = int(self.estimated_total_duration // 3600)
                est_total_minutes = int((self.estimated_total_duration % 3600) // 60)
                
                if est_total_hours > 0:
                    total_str = f"{est_total_hours}h {est_total_minutes}m"
                else:
                    total_str = f"{est_total_minutes}m"
                
                logger.info(f"[{progress:.1f}%] [{elapsed_str} / ~{total_str}] [ETA: {eta_str}] Running {test_func.__name__}...")
                
                try:
                    test_func()
                except Exception as e:
                    logger.error(f"Test {test_func.__name__} crashed: {e}")
                    self.log_test_result(test_func.__name__, False, details=f"Test crashed: {e}")
        
        self.generate_summary_report()
    
    def generate_summary_report(self):
        """Generate comprehensive summary report"""
        total_duration = time.time() - self.start_time
        
        # Categorize results
        passed = [name for name, result in self.results.items() if result['result']]
        failed = [name for name, result in self.results.items() if not result['result']]
        
        success_rate = (len(passed) / len(self.results)) * 100 if self.results else 0
        
        logger.info("\n" + "="*80)
        logger.info(f"TEST SUITE SUMMARY REPORT - {self.test_mode.upper()} MODE")
        logger.info("="*80)
        logger.info(f"Test Mode: {self.test_mode_configs[self.test_mode]['description']}")
        logger.info(f"Total Duration: {total_duration:.1f} seconds")
        logger.info(f"Target Duration: {self.test_mode_configs[self.test_mode]['duration_minutes']} minutes")
        logger.info(f"Tests Run: {len(self.results)}")
        logger.info(f"Passed: {len(passed)} ({success_rate:.1f}%)")
        logger.info(f"Failed: {len(failed)}")
        
        # Individual test results summary
        logger.info(f"\nINDIVIDUAL TEST RESULTS:")
        logger.info("-" * 80)
        for test_name, result in self.results.items():
            status = "✓ PASS" if result['result'] else "✗ FAIL"
            duration = result.get('duration', 0)
            duration_str = f"{duration:.2f}s" if duration else "N/A"
            logger.info(f"{status:<8} {test_name:<40} {duration_str:>8}")
        
        if failed:
            logger.info(f"\nFAILED TEST DETAILS:")
            for test_name in failed:
                result = self.results[test_name]
                logger.info(f"  ✗ {test_name}: {result.get('details', 'No details')}")
        
        # Performance metrics summary
        logger.info(f"\nPERFORMance METRICS:")
        performance_tests = [
            'Basic Search Performance',
            'Complex Aggregation Performance', 
            'Index Stats Performance',
            'Index Settings Analysis'
        ]
        
        for test in performance_tests:
            if test in self.results:
                result = self.results[test]
                duration = result.get('duration', 0)
                status = "✓" if result['result'] else "✗"
                logger.info(f"  {status} {test}: {duration*1000:.1f}ms")
        
        # Overall assessment
        if success_rate >= 90:
            assessment = "EXCELLENT - ELK stack is performing optimally"
        elif success_rate >= 75:
            assessment = "GOOD - Minor issues detected, investigate failed tests"
        elif success_rate >= 50:
            assessment = "FAIR - Multiple issues detected, review configuration"
        else:
            assessment = "POOR - Major issues detected, immediate attention required"
        
        logger.info(f"\nOVERALL ASSESSMENT: {assessment}")
        
        # Recommendations
        logger.info(f"\nRECOMMENDATIONS:")
        if len(failed) == 0:
            logger.info("  • ELK stack is ready for production workloads")
            logger.info("  • Consider running this test suite after ES 8.x upgrade")
        else:
            logger.info("  • Review and fix failed tests before upgrade")
            logger.info("  • Run test suite again after fixes")
            logger.info("  • Use this baseline for ES 8.x comparison")
        
        # Save detailed results to JSON
        results_file = f'elk_test_results_{datetime.now().strftime("%Y%m%d_%H%M%S")}.json'
        try:
            results_data = {
                'summary': {
                    'test_mode': self.test_mode,
                    'test_mode_description': self.test_mode_configs[self.test_mode]['description'],
                    'target_duration_minutes': self.test_mode_configs[self.test_mode]['duration_minutes'],
                    'total_duration': total_duration,
                    'tests_run': len(self.results),
                    'passed': len(passed),
                    'failed': len(failed),
                    'success_rate': success_rate,
                    'assessment': assessment,
                    'timestamp': datetime.now().isoformat()
                },
                'detailed_results': self.results,
                'performance_targets': self.performance_targets,
                'test_environment': {
                    'elasticsearch_hosts': self.es_hosts,
                    'kibana_url': self.kibana_url,
                    'test_indices': self.test_indices
                }
            }
            
            with open(results_file, 'w') as f:
                json.dump(results_data, f, indent=2)
            
            logger.info(f"\nDetailed results saved to: {results_file}")
        except Exception as e:
            logger.warning(f"Failed to save JSON results: {e}")
            logger.info("Test completed but results file not saved")
        
        logger.info(f"\nDetailed results saved to: {results_file}")
        
        # Final execution summary
        hours = int(total_duration // 3600)
        minutes = int((total_duration % 3600) // 60)
        seconds = int(total_duration % 60)
        
        if hours > 0:
            duration_formatted = f"{hours}h {minutes}m {seconds}s"
        elif minutes > 0:
            duration_formatted = f"{minutes}m {seconds}s"
        else:
            duration_formatted = f"{seconds}s"
        
        logger.info(f"\n🏁 TEST SUITE COMPLETED")
        logger.info(f"📊 Total Tests: {len(self.results)} | ✅ Passed: {len(passed)} | ❌ Failed: {len(failed)}")
        logger.info(f"⏱️  Total Time: {duration_formatted} | 🎯 Success Rate: {success_rate:.1f}%")
        logger.info("="*80)

def main():
    """Main execution function"""
    # Parse command line arguments
    parser = argparse.ArgumentParser(
        description='ELK Stack Comprehensive Test Suite',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Test Modes:
  basic      - Essential connectivity and health checks (5 minutes)
  advanced   - Comprehensive functionality and performance tests (15 minutes)  
  performance - Full stress testing and performance validation (20 minutes)

Examples:
  python test_suite.py --mode basic
  python test_suite.py --mode advanced --username elastic --password changeme
  python test_suite.py --mode performance --es-host localhost:9200
        """
    )
    
    parser.add_argument(
        '--mode', 
        choices=['basic', 'advanced', 'performance'],
        default='basic',
        help='Test mode to run (default: basic)'
    )
    
    parser.add_argument(
        '--es-host',
        default=f'{ES_HOST}:{ES_PORT}',
        help=f'Elasticsearch host:port (default: {ES_HOST}:{ES_PORT})'
    )
    
    parser.add_argument(
        '--kibana-host',
        default=f'{KIBANA_HOST}:{KIBANA_PORT}',
        help=f'Kibana host:port (default: {KIBANA_HOST}:{KIBANA_PORT})'
    )
    
    parser.add_argument(
        '--username',
        default='elastic',
        help='Elasticsearch username (default: elastic)'
    )
    
    parser.add_argument(
        '--password', 
        default='changeme',
        help='Elasticsearch password (default: changeme)'
    )
    
    args = parser.parse_args()
    
    # Configuration from arguments
    ES_HOSTS = [args.es_host]
    ES_USERNAME = args.username
    ES_PASSWORD = args.password
    KIBANA_URL = f'http://{args.kibana_host}'
    
    mode_descriptions = {
        'basic': ('Essential connectivity and health checks', '5 minutes'),
        'advanced': ('Comprehensive functionality and performance tests', '15 minutes'),
        'performance': ('Full stress testing and performance validation', '20 minutes')
    }
    
    desc, duration = mode_descriptions[args.mode]
    
    print(f"ELK Stack Test Suite - {args.mode.upper()} Mode")
    print("=" * 60)
    print(f"Mode: {desc}")
    print(f"Estimated duration: {duration}")
    print(f"Testing with ~10GB dataset for ELK stack validation")
    print("=" * 60)
    
    # Initialize test suite
    try:
        test_suite = ELKTestSuite(
            es_hosts=ES_HOSTS,
            username=ES_USERNAME,
            password=ES_PASSWORD,
            kibana_url=KIBANA_URL,
            test_mode=args.mode
        )
    except Exception as e:
        logger.error(f"Failed to initialize test suite: {e}")
        sys.exit(1)
    
    # Run comprehensive tests
    test_suite.run_comprehensive_test_suite()
    
    # Return exit code based on results
    total_tests = len(test_suite.results)
    passed_tests = sum(1 for result in test_suite.results.values() if result['result'])
    success_rate = (passed_tests / total_tests) * 100 if total_tests > 0 else 0
    
    if success_rate >= 90:
        sys.exit(0)  # Excellent
    elif success_rate >= 75:
        sys.exit(1)  # Good but has issues
    else:
        sys.exit(2)  # Poor performance

if __name__ == "__main__":
    main()
