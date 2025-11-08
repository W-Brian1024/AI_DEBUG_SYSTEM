# celery_app.py (with centralized configuration)
import os
import sys
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

# Add parent directory to path for imports
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Import configuration management
from check_config.config_manager import get_config

import zai
from zai import ZhipuAiClient

# ---------- Configuration ----------
# Initialize configuration
config_manager = get_config()

# Setup logging
logging_config = config_manager.get_logging_config()
logging.basicConfig(
    level=getattr(logging, logging_config.get('level', 'INFO')),
    format=logging_config.get('format', '%(asctime)s - %(name)s - %(levelname)s - %(message)s')
)
logger = logging.getLogger("celery_app")

# Redis configuration
redis_config = config_manager.get_redis_config()
redis_client = redis.Redis(
    host=redis_config['host'],
    port=redis_config['port'],
    db=redis_config['db_cache'],
    password=redis_config.get('password'),
    max_connections=redis_config['max_connections']
)

# MinIO configuration
minio_config = config_manager.get_minio_config()
minio_client = Minio(
    endpoint=minio_config['endpoint'],
    access_key=minio_config['access_key'],
    secret_key=minio_config['secret_key'],
    secure=minio_config['secure']
)
BUCKET = minio_config['bucket']

logger.info("MinIO configuration - Endpoint: %s, Bucket: %s", minio_config['endpoint'], BUCKET)
logger.info("MinIO Credentials - Access Key: %s, Secret Key: %s",
           minio_config['access_key'],
           minio_config['secret_key'])

# ZhiPu API configuration - delay initialization until needed
def get_ai_client():
    """Get AI client with lazy initialization"""
    global _deepseek_client
    if _deepseek_client is None:
        ZHIPU_API_KEY = os.getenv("ZHIPU_API_KEY")
        if not ZHIPU_API_KEY:
            logger.error("ZHIPU_API_KEY environment variable not set")
            raise ValueError("ZHIPU_API_KEY environment variable is required")
        _deepseek_client = ZhipuAiClient(api_key=ZHIPU_API_KEY)
        logger.info("AI client initialized")
    return _deepseek_client

_deepseek_client = None

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
        deepseek_client = get_ai_client()
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
    Intelligent log content parsing with adaptive chunking strategy

    Args:
        content: Log content
        max_chunk_size: Maximum number of lines per chunk (default, will be dynamically adjusted)
    """
    lines = content.split('\n')
    chunks = []
    current_chunk = []

    # Intelligent adaptive chunking based on file size
    total_lines = len(lines)

    # Optimize for different file sizes
    if total_lines > 2000:
        # Very large files: aggressive parallelization
        chunk_size = 100      # Smaller chunks for better parallelism
        max_workers = 12         # Max workers for very large files
    elif total_lines > 1000:
        # Large files: high parallelization
        chunk_size = 75       # Small chunks for high throughput
        max_workers = 10         # High worker count
    elif total_lines > 500:
        # Medium files: balanced parallelization
        chunk_size = 50       # Medium chunks
        max_workers = 8          # Medium worker count
    elif total_lines > 200:
        # Small files: moderate parallelization
        chunk_size = 25       # Small chunks
        max_workers = 6          # Moderate worker count
    else:
        # Very small files: minimal parallelization to avoid overhead
        chunk_size = max(15, total_lines)  # Very small chunks, but Not too small
        max_workers = min(4, total_lines)  # Few workers to avoid context switching overhead

    logger.info("Smart parsing log file: total_lines=%d, chunk_size=%d, max_workers=%d",
                total_lines, chunk_size, max_workers)

    for line in lines:
        line = line.strip()
        if not line:
            continue

        current_chunk.append(line)

        # Split chunks by optimized size
        if len(current_chunk) >= chunk_size:
            chunks.append('\n'.join(current_chunk))
            current_chunk = []

    # Add the last chunk
    if current_chunk:
        chunks.append('\n'.join(current_chunk))

    logger.info("Smart parsing completed: generated %d chunks, estimated workers: %d", len(chunks), max_workers)
    return chunks

def analyze_log_chunk(chunk_content: str, chunk_id: str) -> Dict[str, Any]:
    """
    Analyze individual ESP32 log chunk with developer-friendly output
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

    # Enhanced Developer-Focused prompt with deep analysis capabilities
    prompt = f"""
You are an expert ESP32 BLE diagnostician. Analyze this log for DEVELOPER-ACTIONABLE issues.

LOG SEGMENT:
{chunk_content}

CRITICAL FOCUS - Do NOT get stuck on "normal" status:
1. Pattern Recognition: Look for RECURRING issues across the log
2. Root Cause Analysis: What's causing the symptoms?
3. Hidden Problems: Issues that aren't obvious but will cause failures
4. Code Quality Issues: Poor practices that lead to instability
5. Resource Management: Memory leaks, handle leaks, inefficient loops
6. Timing Issues: Race conditions, blocking operations, timeout patterns
7. Configuration Problems: Wrong settings that cause intermittent failures
8. Performance Bottlenecks: Inefficient algorithms, unnecessary processing

ADVANCED ANALYSIS REQUIREMENTS:
- NEVER conclude "system working normally" without deep investigation
- Identify PATTERNS, not just individual events
- Look for correlations between different log entries
- Find the UNDERLYING cause, not just symptoms
- Spot code smells and anti-patterns
- Detect resource exhaustion risks
- Identify security vulnerabilities
- Note scalability limitations

DETECTION PATTERNS TO LOOK FOR:
• Memory allocations without corresponding frees
• Error handling that swallows exceptions
• Infinite loops or blocking operations
• Configuration values that are borderline invalid
• Performance degradation patterns
• Connection instability trends
• Resource leaks (handles, buffers, connections)
• Poor error recovery mechanisms

RETURN ENHANCED JSON:
{{
  "status": "critical|warning|normal",
  "confidence": 0.0-1.0,
  "deep_analysis": {{
    "root_causes": ["actual underlying problems"],
    "hidden_issues": ["non-obvious problems"],
    "pattern_detected": "recurring pattern name",
    "risk_assessment": "low|medium|high|critical"
  }},
  "issues": [
    {{
      "type": "memory_leak|connection_drop|crash|performance|configuration|resource_exhaustion|timing_issue|security_vulnerability",
      "severity": "critical|high|medium|low",
      "description": "Specific problem with context",
      "root_cause": "Why this is happening",
      "solution": "Exact fix steps",
      "prevention": "How to avoid recurrence",
      "line_numbers": ["line ranges"],
      "recurring": true/false,
      "impact": "stability|performance|security|usability"
    }}
  ],
  "performance_indicators": {{
    "efficiency_score": 0-100,
    "resource_usage": "optimal|moderate|high|critical",
    "bottlenecks": ["identified bottlenecks"],
    "optimization_opportunities": ["specific improvements"]
  }},
  "summary": "Concise status with key findings",
  "recommendations": ["actionable development improvements"],
  "prevention_measures": ["how to prevent similar issues"]
}}

Remember: DEVELOPERS need concrete, actionable insights - not generic statements.
"""

    try:
        response = call_deepseek_sync(prompt)

        # Try to parse JSON response
        try:
            analysis = json.loads(response)

            # Enhanced structure validation with deep analysis support
            enhanced_issues = analysis.get("issues", [])
            critical_count = sum(1 for issue in enhanced_issues if issue.get("severity") == "critical")

            normalized_analysis = {
                "chunk_id": chunk_id,
                "from_cache": False,
                "status": analysis.get("status", "normal"),
                "confidence": analysis.get("confidence", 0.5),
                "deep_analysis": analysis.get("deep_analysis", {
                    "root_causes": [],
                    "hidden_issues": [],
                    "pattern_detected": "none",
                    "risk_assessment": "low"
                }),
                "issues": enhanced_issues,
                "performance_indicators": analysis.get("performance_indicators", {
                    "efficiency_score": 75,
                    "resource_usage": "moderate",
                    "bottlenecks": [],
                    "optimization_opportunities": []
                }),
                "summary": analysis.get("summary", "System analysis completed"),
                "recommendations": analysis.get("recommendations", []),
                "prevention_measures": analysis.get("prevention_measures", []),
                "metrics": {
                    "total_issues": len(enhanced_issues),
                    "critical_issues": critical_count,
                    "performance_impact": analysis.get("performance_indicators", {}).get("resource_usage", "none")
                }
            }

            # Cache analysis result (12 hours expiration)
            redis_client.setex(cache_key, 43200, json.dumps(normalized_analysis, ensure_ascii=False))
            logger.info("Chunk analysis result cached: %s", chunk_id)
            return normalized_analysis

        except json.JSONDecodeError:
            # If response is not JSON, create structured result
            non_json_analysis = {
                "chunk_id": chunk_id,
                "from_cache": False,
                "status": "warning",
                "issues": [{
                    "type": "configuration",
                    "severity": "medium",
                    "description": "AI analysis response format issue",
                    "solution": "Log AI response format and retry analysis",
                    "line_numbers": []
                }],
                "summary": "Analysis completed but response format needs correction",
                "recommendations": ["Verify AI analysis output format", "Check API response structure"],
                "metrics": {"total_issues": 1, "critical_issues": 0, "performance_impact": "low"}
            }

            # Cache result for investigation
            redis_client.setex(cache_key, 43200, json.dumps(non_json_analysis, ensure_ascii=False))
            return non_json_analysis

    except Exception as e:
        logger.error("Analysis of chunk %s failed: %s", chunk_id, e)
        error_analysis = {
            "chunk_id": chunk_id,
            "from_cache": False,
            "status": "error",
            "issues": [{
                "type": "system",
                "severity": "high",
                "description": f"Analysis system error: {str(e)}",
                "solution": "Check API connectivity and retry analysis",
                "line_numbers": []
            }],
            "summary": f"Chunk {chunk_id} analysis failed",
            "recommendations": ["Check API connection", "Verify API credentials", "Retry analysis"],
            "metrics": {"total_issues": 1, "critical_issues": 0, "performance_impact": "medium"}
        }

        # Cache error result
        redis_client.setex(cache_key, 3600, json.dumps(error_analysis, ensure_ascii=False))
        return error_analysis

def generate_overall_summary(chunks_analysis: List[Dict[str, Any]]) -> str:
    """
    Generate intelligent ESP32 log analysis with deep pattern recognition and root cause analysis
    """
    if not chunks_analysis:
        return "No valid analysis results"

    # Deep analysis: Identify recurring issues, trends, and patterns
    all_issues = []
    critical_issues = []
    performance_issues = []
    memory_issues = []
    connection_issues = []

    successful_chunks = 0
    total_analyzed = 0

    # Collect and analyze all issues
    for chunk in chunks_analysis:
        total_analyzed += 1
        if chunk.get('confidence', 0) > 0.3:
            successful_chunks += 1

        chunk_issues = chunk.get('issues', [])
        for issue in chunk_issues:
            issue_type = issue.get('type', 'unknown')
            severity = issue.get('severity', 'medium')

            # Add to analysis with enhanced tracking
            issue_analysis = {
                'chunk_id': chunk.get('chunk_id'),
                'type': issue_type,
                'severity': severity,
                'description': issue.get('description', 'Unknown issue'),
                'solution': issue.get('solution', 'Investigate logs for details'),
                'timestamp': issue.get('timestamp', 'Unknown'),
                'first_occurrence': issue.get('first_occurrence', False),
                'chunk_content_preview': chunk.get('chunk_content_preview', 'N/A')
            }

            all_issues.append(issue_analysis)

            # Categorize by severity
            if severity == 'critical':
                critical_issues.append(issue_analysis)
            elif issue_type in ['memory_leak', 'performance', 'resource_exhaustion']:
                performance_issues.append(issue_analysis)
            elif issue_type in ['connection_drop', 'timeout', 'pairing_failed']:
                connection_issues.append(issue_analysis)
            elif issue_type == 'memory_leak':
                memory_issues.append(issue_analysis)

    # Enhanced pattern recognition - Mark recurring issues
    mark_recurring_issues(all_issues)

    # Generate comprehensive analysis report
    critical_count = len(critical_issues)
    performance_count = len(performance_issues)
    memory_count = len(memory_issues)
    connection_count = len(connection_issues)

    # Generate actionable summary with root cause focus
    if critical_count > 0:
        summary = generate_critical_system_summary(all_issues, critical_issues)
        main_focus = "Critical system stability issues"
        priority_level = "🔴 CRITICAL"
        urgency = "Fix immediately"

    elif performance_count >= 3 or any(issue.get('severity') == 'high' for issue in performance_issues):
        summary = generate_performance_crisis_summary(all_issues, performance_issues)
        main_focus = "Severe performance degradation"
        priority_level = "⚠️ DEGRADED"
        urgency = "Optimize urgently"

    elif connection_count >= 2:
        summary = generate_connectivity_crisis_summary(all_issues, connection_issues)
        main_focus = "Connection reliability crisis"
        priority_level = "⚠️ DEGRADED"
        urgency = "Stabilize immediately"

    elif memory_count >= 1:
        summary = generate_memory_crisis_summary(all_issues, memory_issues)
        main_focus = "Memory management problems"
        priority_level = "⚠️ CONCERNING"
        urgency = "Investigate soon"

    else:
        if len(all_issues) >= 1:
            summary = generate_warning_summary(all_issues)
            main_focus = "Multiple issues requiring attention"
            priority_level = "⚠️ WARNING"
            urgency = "Address soon"
        else:
            if successful_chunks >= 3:
                summary = generate_system_health_optimization_summary(all_issues)
                main_focus = "System optimization opportunities"
                priority_level = "⚠️ ATTENTION"
                urgency = "Optimize for improvement"
            else:
                summary = generate_healthy_system_summary(all_issues, successful_chunks)
                main_focus = "System health maintenance"
                priority_level = "✅ OPTIMAL"
                urgency = "Maintain standards"

    # Generate actionable summary with trends
    return summary

def generate_critical_system_summary(all_issues, critical_issues):
    """Generate critical system analysis"""
    return f"""🔴 CRITICAL SYSTEM ISSUES DETECTED
Total Critical Problems: {len(critical_issues)}
Immediate Actions Required:
1. Fix system crashes immediately
2. Address security vulnerabilities
3. Implement crash prevention mechanisms
4. Conduct emergency code review

{summarize_issues_critical(critical_issues)}"""

def generate_performance_crisis_summary(all_issues, performance_issues):
    """Generate performance crisis analysis"""
    return f"""⚠️ PERFORMANCE CRISIS IDENTIFIED
Performance Problems: {len(performance_issues)}
System Degradation Detected: High Impact
Urgent Optimizations Required:
1. Optimize CPU usage and resource management
2. Fix memory leaks and buffer overflows
3. Implement performance monitoring
4. Review and optimize critical code paths

{summarize_issues_performance(performance_issues)}"""

def generate_connectivity_crisis_summary(all_issues, connection_issues):
    """Generate connectivity crisis analysis"""
    return f"""⚠️ CONNECTIVITY CRISIS
Connection Stability Issues: {len(connection_issues)}
User Experience Impact: Severe
Stabilization Measures Required:
1. Implement robust connection management
2. Add automatic retry and fallback mechanisms
3. Improve error handling and recovery
4. Enhance network monitoring and diagnostics

{summarize_issues_connectivity(connection_issues)}"""

def generate_memory_crisis_summary(all_issues, memory_issues):
    """Generate memory crisis analysis"""
    return f"""⚠️ MEMORY MANAGEMENT CRISIS
Memory Issues: {len(memory_issues)}
Resource Management Problems: High Impact
Memory Conservation Required:
1. Investigate memory allocation patterns
2. Fix memory leaks and buffer overflows
3. Implement memory usage monitoring
4. Optimize data structures and algorithms

{summarize_issues_memory(memory_issues)}"""

def generate_warning_summary(all_issues):
    """Generate warning level analysis"""
    issue_count = len(all_issues)
    return f"""⚠️ SYSTEM WARNING - MULTIPLE ISSUES DETECTED
Issues Requiring Attention: {issue_count}
Areas of Concern:
• Memory management: {len([i for i in all_issues if i.get('type') == 'memory_leak'])}
• Performance: {len([i for i in all_issues if i.get('type') in ['memory_leak', 'performance']])}
• Connectivity: {len([i for i in all_issues if i.get('type') in ['connection_drop', 'timeout']])}

{summarize_all_issues(all_issues)}

Address Within: {issue_count * 2} Days

System Stability: {generate_stability_assessment(issue_count)}"""

def generate_system_health_optimization_summary(all_issues, successful_chunks):
    """Generate system optimization recommendations"""
    return f"""⚠️ SYSTEM OPTIMIZATION OPPORTUNITIES
Optimization Areas Identified: {len(all_issues)}
Performance Enhancement:
1. Implement performance monitoring and metrics
2. Optimize critical code paths
3. Add caching strategies
4. Review resource usage patterns

Efficiency Gains Expected: 25-40% Improvement
Recommendation:
- Focus on high-impact optimization areas
- Implement continuous performance monitoring

{summarize_issues_optimization(all_issues)}"""

def generate_healthy_system_summary(all_issues, successful_chunks):
    """Generate healthy system maintenance summary"""
    performance_score = calculate_performance_score(all_issues, successful_chunks)
    return f"""✅ SYSTEM HEALTHY - OPERATING NORMALLY
System Status: {generate_stability_assessment(len(all_issues))}
Performance Score: {performance_score}/100

Analysis Results:
• Successfully analyzed: {successful_chunks} chunks
• System issues found: {len(all_issues)} minor issues
• Overall health: EXCELLENT

Continuous Improvement:
1. Maintain current best practices
2. Monitor system metrics
3. Regular performance reviews

Recommendations:
• Continue current high-quality standards
• Consider adding automated testing
• Monitor for emerging issues over time"""

def calculate_performance_score(issues, chunks_analyzed):
    """Calculate system performance score"""
    if not issues:
        return chunks_analyzed * 10  # Perfect score for no issues
    else:
        # Subtract penalty points for issues
        penalty = 0
        for issue in issues:
            severity = issue.get('severity', 'medium')
            if severity == 'critical':
                penalty += 50
            elif severity == 'high':
                penalty += 25
            elif severity == 'medium':
                penalty += 10
            elif severity == 'low':
                penalty += 5
        return max(0, chunks_analyzed * 10 - penalty)

def generate_stability_assessment(issue_count):
    """Generate system stability assessment"""
    if issue_count == 0:
        return "STABLE - No issues detected"
    elif issue_count <= 2:
        return "MOSTLY STABLE - Minor issues"
    elif issue_count <= 5:
        return "MODERATELY STABLE - Multiple issues"
    else:
        return "NEEDS ATTENTION - Many issues"

def summarize_issues_critical(issues):
    """Summarize critical issues for detailed display"""
    if not issues:
        return "No critical issues detected"

    return '\n'.join([
        f"• {i.get('description', 'Critical issue')} (Line: {i.get('line_numbers', 'N/A')})"
        for i in issues[:5]  # Show top 5 critical issues
    ])

def summarize_issues_performance(issues):
    """Summarize performance issues for detailed display"""
    if not issues:
        return "No performance issues detected"

    return '\n'.join([
        f"• {i.get('description', 'Performance problem')} ({i.get('type')}) (Severity: {i.get('severity')})"
        for i in issues[:5]  # Show top 5 performance issues
    ])

def summarize_issues_memory(issues):
    """Summarize memory issues for detailed display"""
    if not issues:
        return "No memory issues detected"

    return '\n'.join([
        f"• {i.get('description', 'Memory issue')} (Pattern: {i.get('pattern_detected', 'Unknown')})"
        for i in issues[:5]  # Show top 5 memory issues
    ])

def summarize_issues_connectivity(issues):
    """Summarize connectivity issues for detailed display"""
    if not issues:
        return "No connectivity issues detected"

    return '\n'.join([
        f"• {i.get('description', 'Connection issue')} (Frequency: {i.get('frequency', 'Unknown')})"
        for i in issues[:5]  # Show top 5 connectivity issues
    ])

def summarize_issues_optimization(issues):
    """Summarize optimization opportunities"""
    if not issues:
        return "No optimization opportunities detected"

    return '\n'.join([
        f"• {i.get('description', 'Optimization area')} (Impact: {i.get('impact', 'Medium')})"
        for i in issues[:5]
    ])

def summarize_all_issues(issues):
    """Summarize all issues for comprehensive overview"""
    if not issues:
        return "No issues found in this analysis"

    issue_types = {}
    for issue in issues:
        issue_type = issue.get('type', 'unknown')
        issue_types[issue_type] = issue_types.get(issue_type, 0) + 1

    return '\n'.join([
        f"Total Issues: {len(issues)}",
        f"By Type: {dict(issue_types)}",
        f"• Memory: {issue_types.get('memory_leak', 0)}",
        f"• Performance: {issue_types.get('performance', 0)}",
        f"• Connectivity: {issue_types.get('connection_drop', 0)}",
        f"• Configuration: {issue_types.get('configuration', 0)}"
    ])

def mark_recurring_issues(all_issues):
    """Identify and mark recurring issues"""
    issue_counts = {}

    for issue in all_issues:
        issue_type = issue.get('type', 'unknown')
        description = issue.get('description', 'Unknown issue')
        issue_key = f"{issue_type}:{description}"

        issue_counts[issue_key] = issue_counts.get(issue_key, 0) + 1

        # Mark as recurring if seen 3+ times
        if issue_counts[issue_key] >= 3:
            # Mark as recurring and add to existing issue
            for i, existing_issue in enumerate(all_issues):
                if (i != existing_issue and
                    existing_issue.get('type') == issue_type and
                    existing_issue.get('description') == description):
                    # Mark both as recurring
                    all_issues[i]['first_occurrence'] = True
                    all_issues[existing_issue]['recurring'] = True
                    issue['recurring'] = True

def generate_overall_summary(chunks_analysis):
    """
    Generate developer-friendly overall summary with actionable insights
    """
    if not chunks_analysis:
        return "No valid analysis results"

    # Collect and categorize issues
    all_issues = []
    critical_issues = []
    performance_issues = []
    memory_issues = []
    connection_issues = []

    successful_chunks = 0
    total_analyzed = 0

    for chunk in chunks_analysis:
        total_analyzed += 1
        if chunk.get('confidence', 0) > 0.3:
            successful_chunks += 1

        # Categorize issues from all chunks
        chunk_issues = chunk.get('issues', [])
        for issue in chunk_issues:
            issue_type = issue.get('type', 'unknown')
            severity = issue.get('severity', 'medium')

            # Add to categorized list
            issue_summary = {
                'chunk_id': chunk.get('chunk_id'),
                'type': issue_type,
                'severity': severity,
                'description': issue.get('description', 'Unknown issue'),
                'solution': issue.get('solution', 'Check logs for details')
            }

            all_issues.append(issue_summary)

            # Categorize by severity
            if severity == 'critical':
                critical_issues.append(issue_summary)
            elif issue_type in ['memory_leak', 'performance']:
                performance_issues.append(issue_summary)
            elif issue_type in ['connection_drop']:
                connection_issues.append(issue_summary)
            elif 'memory_leak':
                memory_issues.append(issue_summary)

    # Generate actionable summary
    if critical_issues:
        priority_level = "🔴 CRITICAL"
        action_urgency = "Immediate action required"
        main_focus = "Fix critical bugs"
    elif performance_issues:
        priority_level = "⚠️ PERFORMANCE"
        action_urgency = "Optimization recommended"
        main_focus = "Improve system performance"
    elif memory_issues:
        priority_level = "⚠️ MEMORY"
        action_urgency = "Memory leak investigation"
        main_focus = "Check memory allocation"
    elif connection_issues:
        priority_level = "⚠️ CONNECTIVITY"
        action_urgency = "Connection stability check"
        main_focus = "Improve connection reliability"
    elif all_issues:
        priority_level = "⚠️ CONFIGURATION"
        action_urgency = "Configuration review needed"
        main_focus = "Review system settings"
    else:
        priority_level = "✅ HEALTHY"
        action_urgency = "Continue monitoring"
        main_focus = "System operating normally"

    # Create structured summary
    summary = f"""
=== ESP32 Log Analysis Summary ===

Priority Level: {priority_level}
Main Focus: {main_focus}

📊 Analysis Statistics:
- Total chunks analyzed: {total_analyzed}
- Successfully analyzed: {successful_chunks}
- Issues found: {len(all_issues)}
- Critical issues: {len(critical_issues)}
- Performance issues: {len(performance_issues)}
- Memory issues: {len(memory_issues)}
- Connection issues: {len(connection_issues)}

🎯 Top Recommendations:
"""

    if critical_issues:
        summary += "1. Fix critical bugs immediately\n"
        summary += "   - Address system crashes or security vulnerabilities\n"

    if performance_issues:
        summary += "2. Optimize performance\n"
        summary += "   - Review CPU usage and optimize loops\n"
        summary += "   - Check for memory leaks in long-running operations\n"

    if memory_issues:
        summary += "3. Investigate memory usage\n"
        summary += "   - Check for proper memory deallocation\n"
        summary += "   - Monitor memory growth over time\n"

    if connection_issues:
        summary += "4. Improve connection stability\n"
        summary += "   - Implement better error handling\n"
        summary += "   - Add connection retry mechanisms\n"

    if not all_issues and successful_chunks > 0:
        summary += "5. Continue current operations\n"
        summary += "   - System appears stable and functional\n"
        summary += "   - Monitor for emerging issues\n"

    summary += f"\nAction Urgency: {action_urgency}\n"

    return summary

def call_deepseek_with_fallback(prompt: str, max_retries: int = 3) -> str:
    """
    Call AI API with retry mechanism for better reliability
    """
    for attempt in range(max_retries):
        try:
            response = call_deepseek_sync(prompt)
            logger.info("AI analysis successful on attempt %d", attempt + 1)
            return response
        except Exception as e:
            logger.warning("AI analysis attempt %d failed: %s", attempt + 1, e)
            if attempt < max_retries - 1:
                logger.info("Retrying AI analysis, attempts remaining: %d", max_retries - attempt - 1)
                time.sleep(2 ** attempt)  # Exponential backoff
            else:
                logger.error("All AI analysis attempts failed")
                raise e

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
        
        # Re-calculate optimal workers for this specific file
        total_lines = len(content.split('\n'))
        if total_lines > 2000:
            optimal_workers = 12
        elif total_lines > 1000:
            optimal_workers = 10
        elif total_lines > 500:
            optimal_workers = 8
        elif total_lines > 200:
            optimal_workers = 6
        else:
            optimal_workers = min(4, len(chunks))

        max_workers = min(optimal_workers, len(chunks))  # Ensure we don't exceed chunk count
        logger.info("Starting optimized parallel analysis: %d chunks, %d workers", len(chunks), max_workers)

        # Process chunks - either through ThreadPoolExecutor or sequentially if only 1 chunk
        if len(chunks) == 1:
            # Handle single chunk case directly to avoid threading issues with cache
            chunk_id = "chunk_1"
            chunk_content = chunks[0]

            try:
                analysis = analyze_log_chunk(chunk_content, chunk_id)
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
        else:
            # Use ThreadPoolExecutor for multiple chunks
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

                        # Ensure analysis always has the required fields for the summary generation
                        if 'confidence' not in analysis:
                            analysis['confidence'] = 0.5
                        if 'from_cache' not in analysis:
                            analysis['from_cache'] = False

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
