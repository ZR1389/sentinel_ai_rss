"""
Vector-based deduplication for alerts using pgvector-compatible operations.
Replaces O(N²) semantic similarity with efficient REAL[1536] vector operations.
Uses the current pgvector-compatible system with cosine similarity.
"""

import logging
import math
from typing import List, Dict, Any, Optional, Tuple
from contextlib import contextmanager

# Import database utilities and embedding functionality
from utils.db_utils import _get_db_connection, fetch_one, fetch_all
from utils.risk_shared import get_embedding, embedding_manager

logger = logging.getLogger(__name__)


class VectorDeduplicator:
    """
    High-performance vector-based deduplication using pgvector-compatible operations.
    
    Uses REAL[1536] arrays with optimized cosine similarity for efficient deduplication.
    Supports both batch and individual alert deduplication with vector indexing.
    """
    
    def __init__(self, similarity_threshold: float = 0.92):
        """
        Initialize vector deduplicator.
        
        Args:
            similarity_threshold: Cosine similarity threshold (0-1) for considering alerts as duplicates
        """
        self.similarity_threshold = similarity_threshold
        self.embedding_dimension = 1536  # OpenAI text-embedding-3-small
        
    def deduplicate_alerts(
        self, 
        new_alerts: List[Dict[str, Any]], 
        openai_client=None,
        batch_size: int = 50
    ) -> List[Dict[str, Any]]:
        """
        Deduplicate new alerts against existing database using vector similarity.
        
        Args:
            new_alerts: List of new alerts to check for duplicates
            openai_client: OpenAI client for embedding generation
            batch_size: Number of alerts to process in each batch
            
        Returns:
            List of alerts that are not duplicates
        """
        if not new_alerts:
            return []
            
        logger.info(f"Vector deduplication starting: {len(new_alerts)} alerts")
        
        unique_alerts = []
        processed = 0
        
        # Process in batches to manage memory and database load
        for i in range(0, len(new_alerts), batch_size):
            batch = new_alerts[i:i + batch_size]
            unique_batch = self._process_batch(batch, openai_client)
            unique_alerts.extend(unique_batch)
            processed += len(batch)
            
            if processed % 100 == 0:
                logger.info(f"Processed {processed}/{len(new_alerts)} alerts")
        
        duplicates_found = len(new_alerts) - len(unique_alerts)
        logger.info(f"Vector deduplication complete: {duplicates_found} duplicates removed, {len(unique_alerts)} unique alerts")
        
        return unique_alerts
    
    def _process_batch(
        self, 
        alerts: List[Dict[str, Any]], 
        openai_client=None
    ) -> List[Dict[str, Any]]:
        """Process a batch of alerts for deduplication."""
        unique_alerts = []
        
        for alert in alerts:
            try:
                if not self._is_duplicate(alert, openai_client):
                    unique_alerts.append(alert)
                else:
                    logger.debug(f"Duplicate alert filtered: {alert.get('uuid', 'unknown')[:8]}...")
                    
            except Exception as e:
                logger.warning(f"Error processing alert {alert.get('uuid', 'unknown')}: {e}")
                # Include alert if we can't determine duplication status
                unique_alerts.append(alert)
        
        return unique_alerts
    
    def _is_duplicate(self, alert: Dict[str, Any], openai_client=None) -> bool:
        """
        Check if alert is a duplicate using vector similarity search.
        
        Args:
            alert: Alert to check for duplicates
            openai_client: OpenAI client for embedding generation
            
        Returns:
            True if alert is a duplicate, False otherwise
        """
        try:
            # Generate embedding for alert content
            content = self._prepare_alert_content(alert)
            embedding = get_embedding(content, openai_client)
            
            # Check for similar alerts in database
            return self._check_database_similarity(embedding)
            
        except Exception as e:
            logger.error(f"Error checking duplicate status: {e}")
            return False  # Assume not duplicate if check fails
    
    def _prepare_alert_content(self, alert: Dict[str, Any]) -> str:
        """
        Prepare alert content for embedding generation.
        
        Args:
            alert: Alert dictionary
            
        Returns:
            Combined text content for embedding
        """
        # Combine title and summary for semantic comparison
        title = alert.get("title", "").strip()
        summary = alert.get("summary", "").strip()
        
        # Prioritize title, fallback to summary if no title
        if title and summary:
            content = f"{title} {summary}"
        elif title:
            content = title
        elif summary:
            content = summary
        else:
            # Fallback to other fields if no title/summary
            content = alert.get("en_snippet", "") or alert.get("link", "")
        
        # Truncate to embedding model limits
        return content[:4096]
    
    def _check_database_similarity(self, embedding: List[float]) -> bool:
        """
        Check database for similar embeddings using pgvector-compatible similarity search.
        
        Args:
            embedding: Query embedding vector (REAL[1536] format)
            
        Returns:
            True if similar alert found, False otherwise
        """
        try:
            # Use pgvector-compatible similarity search with REAL arrays
            query = """
                SELECT COUNT(*) > 0 as has_similar
                FROM find_similar_alerts(%s::REAL[], %s, 1)
            """
            
            result = fetch_one(query, (
                embedding, 
                self.similarity_threshold
            ))
            return result[0] if result else False
            
        except Exception as e:
            logger.error(f"Database similarity check failed: {e}")
            return False
    
    def find_similar_alerts(
        self, 
        alert: Dict[str, Any], 
        openai_client=None,
        max_results: int = 5
    ) -> List[Dict[str, Any]]:
        """
        Find similar alerts for a given alert using pgvector-compatible similarity search.
        
        Args:
            alert: Alert to find similarities for
            openai_client: OpenAI client for embedding
            max_results: Maximum number of similar alerts to return
            
        Returns:
            List of similar alerts with similarity scores
        """
        try:
            content = self._prepare_alert_content(alert)
            embedding = get_embedding(content, openai_client)
            
            # Use pgvector-compatible similarity search with REAL arrays
            query = """
                SELECT alert_uuid, similarity, title
                FROM find_similar_alerts(%s::REAL[], %s, %s)
            """
            
            results = fetch_all(query, (
                embedding, 
                self.similarity_threshold, 
                max_results
            ))
            
            return [
                {
                    "uuid": row["alert_uuid"],
                    "similarity": float(row["similarity"]),
                    "title": row["title"]
                }
                for row in results or []
            ]
            
        except Exception as e:
            logger.error(f"Error finding similar alerts: {e}")
            return []
    
    def store_alert_embedding(
        self, 
        alert_uuid: str, 
        embedding: List[float]
    ) -> bool:
        """
        Store embedding for an alert using the current REAL[1536] vector system.
        
        Args:
            alert_uuid: UUID of the alert
            embedding: Embedding vector to store (REAL[1536] format)
            
        Returns:
            True if successful, False otherwise
        """
        try:
            # Use the current db_utils store_alert_embedding function
            from db_utils import store_alert_embedding as db_store_embedding
            return db_store_embedding(alert_uuid, embedding)
                    
        except Exception as e:
            logger.error(f"Error storing embedding for alert {alert_uuid}: {e}")
            return False
    
    def populate_embeddings_batch(
        self, 
        openai_client=None,
        batch_size: int = 20,
        max_alerts: int = 1000
    ) -> int:
        """
        Populate embeddings for existing alerts that don't have them.
        
        Args:
            openai_client: OpenAI client for embedding generation
            batch_size: Number of alerts to process per batch
            max_alerts: Maximum number of alerts to process
            
        Returns:
            Number of embeddings successfully created
        """
        logger.info("Starting batch embedding population for existing alerts")
        
        try:
            # Get alerts without embeddings (current REAL[] system)
            query = """
                SELECT uuid, title, summary, en_snippet
                FROM alerts 
                WHERE embedding IS NULL
                ORDER BY created_at DESC
                LIMIT %s
            """
            
            alerts = fetch_all(query, (max_alerts,))
            if not alerts:
                logger.info("No alerts found without embeddings")
                return 0
            
            logger.info(f"Found {len(alerts)} alerts without embeddings")
            
            success_count = 0
            
            # Process in batches to respect quota limits
            for i in range(0, len(alerts), batch_size):
                batch = alerts[i:i + batch_size]
                batch_success = self._process_embedding_batch(batch, openai_client)
                success_count += batch_success
                
                logger.info(f"Processed batch {i//batch_size + 1}: {batch_success}/{len(batch)} embeddings created")
                
                # Check quota status
                status = embedding_manager.get_quota_status()
                if status["tokens_remaining"] < 1000:
                    logger.warning("Embedding quota running low, stopping batch processing")
                    break
            
            logger.info(f"Batch embedding population complete: {success_count} embeddings created")
            return success_count
            
        except Exception as e:
            logger.error(f"Error in batch embedding population: {e}")
            return 0
    
    def _process_embedding_batch(
        self, 
        alerts: List[Dict[str, Any]], 
        openai_client=None
    ) -> int:
        """Process a batch of alerts for embedding generation."""
        success_count = 0
        
        for alert in alerts:
            try:
                # Prepare content
                content = self._prepare_alert_content(alert)
                
                # Generate embedding
                embedding = get_embedding(content, openai_client)
                
                # Store in database
                if self.store_alert_embedding(alert["uuid"], embedding):
                    success_count += 1
                else:
                    logger.warning(f"Failed to store embedding for alert {alert['uuid']}")
                    
            except Exception as e:
                logger.error(f"Error processing embedding for alert {alert.get('uuid', 'unknown')}: {e}")
                continue
        
        return success_count
    
    def create_vector_index(self, index_type: str = "gin") -> bool:
        """
        Create vector similarity index for performance using current vector system.
        
        Args:
            index_type: Type of index to create ('gin' for GIN, 'gist' for GiST)
            
        Returns:
            True if successful, False otherwise
        """
        try:
            if index_type == "gin":
                # GIN index for the current vector system
                query = """
                    CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_alerts_embedding_gin 
                    ON alerts USING gin (embedding)
                """
            else:
                # GiST index for the current vector system
                query = """
                    CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_alerts_embedding_gist 
                    ON alerts USING gist (embedding)
                """
            
            with _get_db_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(query)
                    
            logger.info(f"Vector index ({index_type}) created successfully")
            return True
            
        except Exception as e:
            logger.error(f"Error creating vector index: {e}")
            return False
    
    def get_dedup_stats(self) -> Dict[str, Any]:
        """
        Get deduplication and embedding statistics.
        
        Returns:
            Dictionary with statistics
        """
        try:
            query = """
                SELECT * FROM get_embedding_info()
            """
            
            result = fetch_one(query)
            if result:
                return {
                    "total_alerts": int(result[0]),
                    "alerts_with_embeddings": int(result[1]),
                    "embedding_coverage_pct": float(result[2]),
                    "avg_embedding_size": int(result[3]),
                    "similarity_threshold": self.similarity_threshold
                }
            else:
                return {"error": "Unable to fetch statistics"}
                
        except Exception as e:
            logger.error(f"Error getting dedup stats: {e}")
            return {"error": str(e)}


# Global instance for use throughout the application
vector_deduplicator = VectorDeduplicator()


def deduplicate_alerts_vector(
    alerts: List[Dict[str, Any]],
    openai_client=None,
    similarity_threshold: float = 0.92
) -> List[Dict[str, Any]]:
    """
    Drop-in replacement for the O(N²) deduplicate_alerts function.
    
    Args:
        alerts: List of alerts to deduplicate
        openai_client: OpenAI client for embeddings
        similarity_threshold: Similarity threshold for duplicates
        
    Returns:
        List of unique alerts
    """
    deduplicator = VectorDeduplicator(similarity_threshold)
    return deduplicator.deduplicate_alerts(alerts, openai_client)


def populate_missing_embeddings(
    openai_client=None,
    batch_size: int = 20,
    max_alerts: int = 1000
) -> int:
    """
    Utility function to populate embeddings for existing alerts.
    
    Args:
        openai_client: OpenAI client for embedding generation
        batch_size: Alerts to process per batch
        max_alerts: Maximum alerts to process
        
    Returns:
        Number of embeddings created
    """
    return vector_deduplicator.populate_embeddings_batch(
        openai_client, batch_size, max_alerts
    )
