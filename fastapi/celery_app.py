# celery_app.py (fixed version)
import os
import logging
import json
import time
import asyncio
import hashlib
from typing import Dict, Any, List
from concurrent.futures import ThreadPoolExecutor, as_completed

from celery import Celery
from minio import Minio
from openai import OpenAI
import redis

import zai

from zai import ZhipuAiClient

# ---------- Configuration ----------
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("celery_app")

# Redis configuration
redis_client = redis.Redis(host='localhost', port=6379, db=2)

# MinIO configuration
minio_client = Minio(
    endpoint="localhost:9000",
    access_key=os.getenv("MINIO_ACCESS_KEY", "minioadmin"),
    secret_key=os.getenv("MINIO_SECRET_KEY", "minioadmin"),
    secure=False
)
BUCKET = "ble1"

#ZhiPu API configuration
deepseek_client = ZhipuAiClient(api_key="your_api_key")

# Celery configuration
celery = Celery(
    'esp32_analysis',
    broker='redis://localhost:6379/0',
    backend='redis://localhost:6379/1'
)

celery.conf.update(
    task_serializer='json',
    accept_content=['json'],
    result_serializer='json',
    timezone='Asia/Shanghai',
    enable_utc=True,
)

# ---------- Helper Functions ----------

def call_deepseek_sync(prompt: str) -> str:
    """Synchronous call to DeepSeek API"""
    try:
        # Generate cache key
        cache_key = f"llm_cache:{hashlib.md5(prompt.encode('utf-8')).hexdigest()}"
        
        # Try to get result from cache
        cached_result = redis_client.get(cache_key)
        if cached_result:
            logger.info("Using cached AI analysis result")
            return json.loads(cached_result)
        
        # Call API
        response = deepseek_client.chat.completions.create(
            model="glm-4.5",
            messages=[{"role": "user", "content": prompt}],
            stream=False
        )
        result = response.choices[0].message.content
        
        # Cache result (24 hours expiration)
        redis_client.setex(cache_key, 86400, json.dumps(result, ensure_ascii=False))
        logger.info("AI analysis result cached")
        
        return result
    except Exception as e:
        logger.error("DeepSeek API call failed: %s", e)
        return f"API call failed: {str(e)}"

def parse_log_content(content: str, max_chunk_size: int = 150) -> List[str]:
    """
    Parse log content, split into multiple chunks (optimized for large file processing)

    Args:
        content: Log content
        max_chunk_size: Maximum number of lines per chunk
    """
    lines = content.split('\n')
    chunks = []
    current_chunk = []
    
    # Dynamically adjust chunk size: for large files, increase chunk size
    total_lines = len(lines)
    if total_lines > 1000:
        max_chunk_size = 200  # Large files use larger chunks
    elif total_lines > 500:
        max_chunk_size = 150  # Medium files
    elif total_lines > 200:
        max_chunk_size = 100  # Smaller files
    elif total_lines > 100:
        max_chunk_size = 75   # Small files
    
    logger.info("Parsing log file, total lines: %d, using chunk size: %d", total_lines, max_chunk_size)
    
    for line in lines:
        line = line.strip()
        if not line:
            continue
            
        current_chunk.append(line)
        
        # Split chunks by dynamic size
        if len(current_chunk) >= max_chunk_size:
            chunks.append('\n'.join(current_chunk))
            current_chunk = []
    
    # Add the last chunk
    if current_chunk:
        chunks.append('\n'.join(current_chunk))
    
    logger.info("Log parsing completed, generated %d chunks", len(chunks))
    return chunks

def analyze_log_chunk(chunk_content: str, chunk_id: str) -> Dict[str, Any]:
    """
    Analyze individual log chunk (optimized version)
    """
    # Generate chunk hash value for caching
    chunk_hash = hashlib.md5(chunk_content.encode('utf-8')).hexdigest()
    cache_key = f"chunk_analysis:{chunk_hash}"
    
    # Try to get analysis result from cache
    cached_analysis = redis_client.get(cache_key)
    if cached_analysis:
        logger.info("Using cached chunk analysis result: %s", chunk_id)
        analysis = json.loads(cached_analysis)
        analysis['chunk_id'] = chunk_id
        analysis['from_cache'] = True
        return analysis
    
    prompt = f"""
Please analyze the following ESP32 BLE log segment, identify potential issues and provide solutions:

Log content:
{chunk_content}

Please return analysis results in JSON format, including the following fields:
- summary: Brief summary
- evidence: List of evidence (specific information extracted from logs)
- actions: Recommended action list
- confidence: Confidence level (between 0-1)

If no issues are found, please return analysis in normal state.
"""
    
    try:
        response = call_deepseek_sync(prompt)
        
        # Try to parse JSON response
        try:
            analysis = json.loads(response)
            # Validate required fields
            if 'summary' not in analysis:
                analysis['summary'] = "Analysis completed, but format is abnormal"
            if 'evidence' not in analysis:
                analysis['evidence'] = []
            if 'actions' not in analysis:
                analysis['actions'] = []
            if 'confidence' not in analysis:
                analysis['confidence'] = 0.5
                
            analysis['from_cache'] = False
            
            # Cache analysis result (12 hours expiration)
            redis_client.setex(cache_key, 43200, json.dumps(analysis, ensure_ascii=False))
            logger.info("Chunk analysis result cached: %s", chunk_id)
                
            return analysis
        except json.JSONDecodeError:
            # If response is not JSON, create default analysis result
            analysis = {
                "summary": f"Chunk {chunk_id} analysis completed",
                "evidence": [response[:200] + "..."],
                "actions": ["Check log format", "Verify analysis result"],
                "confidence": 0.5,
                "raw_response": response,
                "from_cache": False
            }
            # Cache default result
            redis_client.setex(cache_key, 43200, json.dumps(analysis, ensure_ascii=False))
            return analysis
            
    except Exception as e:
        logger.error("Analysis of chunk %s failed: %s", chunk_id, e)
        error_analysis = {
            "summary": f"Chunk {chunk_id} analysis failed",
            "evidence": [f"Analysis error: {str(e)}"],
            "actions": ["Check API connection", "Retry analysis"],
            "confidence": 0.0,
            "error": str(e),
            "from_cache": False
        }
        # Cache error result (shorter time)
        redis_client.setex(cache_key, 3600, json.dumps(error_analysis, ensure_ascii=False))
        return error_analysis

def generate_overall_summary(chunks_analysis: List[Dict[str, Any]]) -> str:
    """
    Generate overall summary
    """
    if not chunks_analysis:
        return "No valid analysis results"
    
    successful_analysis = [chunk for chunk in chunks_analysis if chunk.get('confidence', 0) > 0.3]
    
    if not successful_analysis:
        return "All analysis blocks failed or confidence is too low"
    
    # Extract all summaries for generating overall summary
    summaries = [chunk.get('summary', '') for chunk in successful_analysis]
    
    prompt = f"""
Based on the analysis summaries of each log block below, please generate an overall problem diagnosis summary:

Analysis summary of each block:
{chr(10).join([f"- {summary}" for summary in summaries if summary])}

Please provide:
1. Main problem identification
2. Key evidence summary
3. Overall recommendations

Please answer in concise and clear English.
"""
    
    try:
        return call_deepseek_sync(prompt)
    except Exception as e:
        logger.error("Failed to generate overall summary: %s", e)
        return f"Overall summary generation failed: {str(e)}"

# ---------- Celery Tasks ----------

@celery.task(bind=True)
def preprocess_file(self, event_id: str, minio_path: str):
    """
    Process uploaded log files (performance optimized version)
    """
    start_time = time.time()
    logger.info("Starting to process file: %s, event ID: %s", minio_path, event_id)
    
    try:
        # Stage 1: Download file
        self.update_state(
            state='PROGRESS',
            meta={
                'progress': 10, 
                'stage': 'Downloading file...',
                'event_id': event_id
            }
        )
        
        try:
            file_data = minio_client.get_object(BUCKET, minio_path)
            content = file_data.read().decode('utf-8')
            logger.info("File downloaded successfully, size: %d characters", len(content))
        except Exception as e:
            logger.error("File download failed: %s", e)
            raise Exception(f"File download failed: {str(e)}")

        # Stage 2: Parse logs
        self.update_state(
            state='PROGRESS', 
            meta={
                'progress': 30, 
                'stage': 'Parsing logs...',
                'event_id': event_id
            }
        )
        
        chunks = parse_log_content(content)
        logger.info("Log parsing completed, total %d chunks", len(chunks))
        
        if not chunks:
            raise Exception("Log file is empty or format is incorrect")

        # Stage 3: Parallel analysis of chunks
        chunks_analysis = []
        successful_chunks = 0
        cached_chunks = 0
        
        # Use thread pool for parallel processing
        max_workers = min(8, len(chunks))  # Maximum 8 concurrent, avoid API limits
        logger.info("Starting parallel analysis of %d chunks, using %d worker threads", len(chunks), max_workers)
        
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            # Submit all tasks
            future_to_chunk = {
                executor.submit(analyze_log_chunk, chunk, f"chunk_{i+1}"): (i, chunk)
                for i, chunk in enumerate(chunks)
            }
            
            # Collect results
            completed_count = 0
            for future in as_completed(future_to_chunk):
                chunk_index, chunk_content = future_to_chunk[future]
                chunk_id = f"chunk_{chunk_index + 1}"
                
                try:
                    analysis = future.result()
                    analysis['chunk_id'] = chunk_id
                    chunks_analysis.append({
                        'chunk_id': chunk_id,
                        'analysis': analysis
                    })
                    
                    if analysis.get('confidence', 0) > 0.3:
                        successful_chunks += 1
                    
                    if analysis.get('from_cache', False):
                        cached_chunks += 1
                    
                    logger.info("Chunk %s analysis completed, confidence: %.2f, cached: %s",
                              chunk_id, analysis.get('confidence', 0),
                              "Yes" if analysis.get('from_cache', False) else "No")
                    
                except Exception as e:
                    logger.error("Analysis of chunk %s failed: %s", chunk_id, e)
                    chunks_analysis.append({
                        'chunk_id': chunk_id,
                        'analysis': {
                            'summary': f'Chunk {chunk_id} analysis failed',
                            'error': str(e),
                            'confidence': 0.0
                        }
                    })
                
                completed_count += 1
                # Update progress
                progress = 30 + int(40 * (completed_count / len(chunks)))
                self.update_state(
                    state='PROGRESS',
                    meta={
                        'progress': progress,
                        'stage': f'Parallel analyzing chunk {completed_count}/{len(chunks)}...',
                        'event_id': event_id,
                        'successful_chunks': successful_chunks,
                        'cached_chunks': cached_chunks
                    }
                )
        
        logger.info("Parallel analysis completed, successful: %d, cache hits: %d", successful_chunks, cached_chunks)

        # Stage 4: Generate overall summary
        self.update_state(
            state='PROGRESS',
            meta={
                'progress': 80,
                'stage': 'Generating overall summary...',
                'event_id': event_id
            }
        )
        
        overall_summary = generate_overall_summary(
            [chunk['analysis'] for chunk in chunks_analysis]
        )
        
        # Build final result
        result = {
            'event_id': event_id,
            'summary': overall_summary,
            'chunks': chunks_analysis,
            'total_chunks_processed': len(chunks),
            'successful_chunks': successful_chunks,
            'cached_chunks': cached_chunks,
            'analysis_time': time.time(),
            'filename': minio_path.split('_', 1)[1] if '_' in minio_path else minio_path,
            'performance_metrics': {
                'parallel_processing': True,
                'max_workers': max_workers,
                'cache_hit_rate': cached_chunks / len(chunks) if chunks else 0,
                'total_analysis_time': time.time() - start_time
            }
        }
        
        logger.info("Analysis completed, performance metrics: parallel_processing=%s, cache_hit_rate=%.2f%%, total_time=%.2f seconds",
                  True, (cached_chunks / len(chunks) * 100) if chunks else 0,
                  time.time() - start_time)
        
        # Save results to Redis (for subsequent queries)
        try:
            redis_client.setex(
                f"llm_result:{event_id}", 
                3600,  # 1 hour expiration
                json.dumps(result, ensure_ascii=False)
            )
            logger.info("Results saved to Redis: llm_result:%s", event_id)
        except Exception as e:
            logger.error("Failed to save results to Redis: %s", e)
        
        # Stage 5: Complete
        self.update_state(
            state='PROGRESS',
            meta={
                'progress': 100,
                'stage': 'Analysis completed',
                'event_id': event_id
            }
        )
        
        logger.info("File processing completed: %s, successful chunks: %d/%d",
                   minio_path, successful_chunks, len(chunks))
        
        return result
        
    except Exception as e:
        logger.error("File processing failed: %s", e)
        
        # Return error result
        error_result = {
            'event_id': event_id,
            'summary': f'Analysis failed: {str(e)}',
            'chunks': [],
            'total_chunks_processed': 0,
            'successful_chunks': 0,
            'error': str(e),
            'analysis_time': time.time()
        }
        
        # Save error result to Redis
        try:
            redis_client.setex(
                f"llm_result:{event_id}", 
                3600,
                json.dumps(error_result, ensure_ascii=False)
            )
        except Exception as e2:
            logger.error("Failed to save error result to Redis: %s", e2)
        
        raise self.retry(exc=e, countdown=60, max_retries=3)

@celery.task
def test_task():
    """Test task"""
    return {"status": "success", "message": "Celery worker is working"}

if __name__ == "__main__":
    # Start Celery worker
    celery.start()
