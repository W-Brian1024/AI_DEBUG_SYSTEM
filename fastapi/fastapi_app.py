
# fastapi_app.py (with centralized configuration)
import os
import sys
import uuid
import logging
import json
import io
import asyncio
import time
import re
import argparse
from typing import Optional, Dict, Any, List, Union

from fastapi import FastAPI, UploadFile, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse
from fastapi.middleware.cors import CORSMiddleware
from celery.result import AsyncResult
from minio import Minio
from openai import OpenAI
import redis

# Add parent directory to path for imports
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Import configuration management
from check_config.config_manager import get_config, ConfigManager

# Import tasks and celery app from celery_app
from celery_app import preprocess_file, celery  # type: ignore

# ---------- Configuration ----------
# Initialize configuration
config_manager = get_config()
config = config_manager.get_all_config()

# Setup logging
logging_config = config_manager.get_logging_config()
logging.basicConfig(
    level=getattr(logging, logging_config.get('level', 'INFO')),
    format=logging_config.get('format', '%(asctime)s - %(name)s - %(levelname)s - %(message)s')
)
logger = logging.getLogger("fastapi_app")

# Validate configuration on startup
if not config_manager.validate_config():
    logger.error("Configuration validation failed. Please check your environment variables.")
    sys.exit(1)

# Initialize FastAPI app
server_config = config_manager.get_server_config()
app = FastAPI(
    title="ESP32 Log Upload & LLM Analysis",
    debug=server_config.get('debug', False)
)

# Add CORS middleware
cors_origins = server_config.get('cors_origins', ["*"])
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_methods=["*"],
    allow_headers=["*"]
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

# Redis configuration
redis_config = config_manager.get_redis_config()
redis_client = redis.Redis(
    host=redis_config['host'],
    port=redis_config['port'],
    db=redis_config['db_cache'],
    password=redis_config.get('password'),
    max_connections=redis_config['max_connections']
)

# AI API configuration
ai_config = config_manager.get_ai_config()
if ai_config['provider'] == 'zhipu':
    from zai import ZhipuAiClient
    if not ai_config.get('api_key'):
        logger.error("ZHIPU_API_KEY environment variable not set")
        raise ValueError("ZHIPU_API_KEY environment variable is required")
    deepseek_client = ZhipuAiClient(api_key=ai_config['api_key'])
    logger.info("Using ZhiPu AI with model: %s", ai_config['model'])
else:
    logger.error("Unsupported AI provider: %s", ai_config['provider'])
    raise ValueError(f"Unsupported AI provider: {ai_config['provider']}")

# Global context - use dictionary to store multiple contexts, with event_id as key
llm_contexts: Dict[str, Dict[str, Any]] = {}
latest_event_id: Optional[str] = None

# Conversation history - store all conversation history
conversation_history: List[Dict[str, Any]] = []
MAX_HISTORY_SIZE = 200  # Maximum history size

# Ensure bucket exists
try:
    if not minio_client.bucket_exists(BUCKET):
        minio_client.make_bucket(BUCKET)
    logger.info("MinIO bucket verified: %s", BUCKET)
except Exception as e:
    logger.warning("MinIO connection/make_bucket may have failed: %s", e)

# ---------- HTML Frontend ----------
INDEX_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>ESP32 Log Analysis System</title>
    <link href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0/css/all.min.css" rel="stylesheet">
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap" rel="stylesheet">
    <style>
        :root {
            --primary: #2563eb;
            --primary-dark: #1d4ed8;
            --secondary: #64748b;
            --success: #10b981;
            --warning: #f59e0b;
            --danger: #ef4444;
            --light: #f8fafc;
            --dark: #1e293b;
            --gray: #94a3b8;
            --card-shadow: 0 10px 25px -5px rgba(0, 0, 0, 0.1);
        }
        
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }
        
        body {
            font-family: system-ui, -apple-system, sans-serif;
            background: #f8fafc;
            margin: 0;
            padding: 20px;
            color: #334155;
        }
        
        .container {
            max-width: 1200px;
            margin: 0 auto;
        }
        
        .header {
            background: white;
            padding: 20px;
            text-align: center;
            border-radius: 8px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
            margin-bottom: 20px;
        }

        .header h1 {
            font-size: 24px;
            font-weight: 600;
            margin-bottom: 8px;
            color: #1e293b;
        }

        .header p {
            font-size: 14px;
            color: #64748b;
        }
        
        .content {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 20px;
        }
        
        @media (max-width: 768px) {
            .content {
                grid-template-columns: 1fr;
            }
        }
        
        .card {
            background: white;
            border-radius: 8px;
            padding: 20px;
            border: 1px solid #e2e8f0;
        }
        
        .card-title {
            font-size: 16px;
            font-weight: 600;
            color: #374151;
            margin-bottom: 15px;
            display: flex;
            align-items: center;
            justify-content: space-between;
        }

        .card-title i {
            color: #3b82f6;
        }
        
        .upload-section {
            border: 2px dashed #cbd5e1;
            border-radius: 8px;
            padding: 20px;
            text-align: center;
            margin-bottom: 20px;
        }
        
        .upload-section:hover {
            border-color: var(--primary);
        }
        
        .file-input {
            display: none;
        }
        
        .file-label {
            display: inline-block;
            padding: 12px 24px;
            background: #3b82f6;
            color: white;
            border-radius: 6px;
            cursor: pointer;
            font-weight: 500;
        }

        .file-label:hover {
            background: #2563eb;
        }
        
        .metadata-input {
            width: 100%;
            padding: 12px;
            border: 2px solid #e2e8f0;
            border-radius: 8px;
            font-size: 14px;
            margin: 15px 0;
            transition: border-color 0.3s ease;
        }
        
        .metadata-input:focus {
            outline: none;
            border-color: var(--primary);
        }
        
        .btn {
            padding: 12px 24px;
            border: none;
            border-radius: 8px;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.3s ease;
            font-size: 14px;
        }
        
        .btn-primary {
            background: var(--primary);
            color: white;
        }
        
        .btn-primary:hover {
            background: var(--primary-dark);
            transform: translateY(-2px);
        }
        
        .progress-container {
            margin: 20px 0;
        }
        
        .progress-bar {
            width: 100%;
            height: 12px;
            background: #e2e8f0;
            border-radius: 6px;
            overflow: hidden;
        }
        
        .progress-fill {
            height: 100%;
            background: linear-gradient(90deg, var(--primary) 0%, var(--success) 100%);
            border-radius: 6px;
            transition: width 0.3s ease;
            position: relative;
        }
        
        .progress-text {
            text-align: center;
            font-size: 14px;
            color: var(--secondary);
            margin-top: 8px;
        }
        
        .status-card {
            background: #f8fafc;
            border-left: 4px solid var(--primary);
            padding: 20px;
            border-radius: 8px;
            margin: 20px 0;
            font-family: 'Monaco', 'Menlo', monospace;
            font-size: 12px;
            max-height: 200px;
            overflow-y: auto;
        }
        
        .chat-container {
            display: flex;
            gap: 12px;
            margin-top: 20px;
        }
        
        .chat-input {
            flex: 1;
            padding: 12px;
            border: 2px solid #e2e8f0;
            border-radius: 8px;
            font-size: 14px;
        }
        
        .chat-input:focus {
            outline: none;
            border-color: var(--primary);
        }
        
        .history-container {
            background: #f8fafc;
            border-radius: 12px;
            padding: 20px;
            max-height: 400px;
            overflow-y: auto;
            margin-top: 20px;
        }
        
        .message {
            margin-bottom: 15px;
            padding: 15px;
            border-radius: 12px;
            line-height: 1.5;
        }
        
        .message-question {
            background: white;
            border: 1px solid #e2e8f0;
            margin-left: 40px;
        }
        
        .message-answer {
            background: linear-gradient(135deg, #dbeafe 0%, #bfdbfe 100%);
            margin-right: 40px;
        }
        
        .highlight {
            padding: 8px 12px;
            border-radius: 6px;
            margin: 8px 0;
            font-size: 13px;
        }
        
        .highlight-evidence {
            background: #fffbeb;
            border-left: 3px solid var(--warning);
        }
        
        .highlight-action {
            background: #f0fdf4;
            border-left: 3px solid var(--success);
        }
        
        .chunk-card {
            background: white;
            border: 1px solid #e2e8f0;
            border-radius: 8px;
            padding: 15px;
            margin: 10px 0;
        }
        
        .loading {
            display: inline-block;
            width: 20px;
            height: 20px;
            border: 3px solid #f3f3f3;
            border-top: 3px solid var(--primary);
            border-radius: 50%;
            animation: spin 1s linear infinite;
        }
        
        @keyframes spin {
            0% { transform: rotate(0deg); }
            100% { transform: rotate(360deg); }
        }
        
        .success-badge {
            background: var(--success);
            color: white;
            padding: 4px 12px;
            border-radius: 20px;
            font-size: 12px;
            font-weight: 600;
        }
        
        .error-badge {
            background: var(--danger);
            color: white;
            padding: 4px 12px;
            border-radius: 20px;
            font-size: 12px;
            font-weight: 600;
        }
        
        .analysis-result {
            max-height: 500px;
            overflow-y: auto;
        }
        
        .current-file {
            background: #f0f9ff;
            padding: 10px;
            border-radius: 8px;
            margin-bottom: 15px;
            border-left: 4px solid var(--primary);
        }
        
        .file-selector {
            background: #f8fafc;
            padding: 15px;
            border-radius: 8px;
            margin-bottom: 15px;
            border: 1px solid #e2e8f0;
        }
        
        .file-selector select {
            width: 100%;
            padding: 10px;
            border: 2px solid #e2e8f0;
            border-radius: 6px;
            font-size: 14px;
            background: white;
        }
        
        .file-selector select:focus {
            outline: none;
            border-color: var(--primary);
        }
        
        .context-badge {
            background: var(--warning);
            color: white;
            padding: 4px 12px;
            border-radius: 20px;
            font-size: 12px;
            font-weight: 600;
            margin-left: 10px;
        }
    </style>
</head>
<body>
    <div class="container">
        <!-- Header -->
        <div class="header">
            <div style="display: flex; justify-content: space-between; align-items: center;">
                <div>
                    <h1>ESP32 Log Analysis System</h1>
                    <p>AI-powered log analysis and problem diagnosis</p>
                </div>
                <button id="langBtn" onclick="switchLanguage()" class="btn btn-secondary" style="padding: 8px 16px;">
                    EN
                </button>
            </div>
        </div>
        
        <!-- Content Area -->
        <div class="content">
            <!-- Left Panel: File Upload and Analysis -->
            <div class="left-panel">
                <div class="card">
                    <div class="card-title">
                        Log File Upload
                    </div>
                    
                    <div class="upload-section">
                        <input type="file" id="fileInput" class="file-input" accept=".log,.txt,.bin">
                        <label for="fileInput" class="file-label">
                            Select Log File
                        </label>
                        <p id="fileName" style="margin-top: 15px; color: var(--secondary); font-size: 14px;"></p>
                    </div>
                    
                    <textarea 
                        id="metadata" 
                        class="metadata-input" 
                        placeholder='{"device": "ESP32", "firmware": "v1.0", "project": "BLE_Project"}'
                    ></textarea>
                    
                    <button onclick="uploadFile()" class="btn btn-primary" style="width: 100%;">
Start Analysis
                    </button>
                </div>
                
                <div class="progress-container">
                    <div class="progress-bar">
                        <div id="progress" class="progress-fill" style="width: 0%"></div>
                    </div>
                    <div class="progress-text" id="progressText">等待上传...</div>
                </div>
                
                <div class="card">
                    <div class="card-title">
                        Task Status
                    </div>
                    <div id="status" class="status-card">
                        等待任务开始...
                    </div>
                </div>
            </div>
            
            <!-- Right Panel: Analysis and Q&A -->
            <div class="right-panel">
                <div class="card">
                    <div class="card-title">
                        Analysis Results
                        <span id="currentFileBadge" class="success-badge" style="display: none;">Current File</span>
                        <button onclick="loadConversationHistory()" class="btn btn-secondary" style="width: auto; padding: 8px 16px; font-size: 12px;">
                            Load History
                        </button>
                    </div>
                      <div id="currentFileInfo" class="current-file" style="display: none;">
                        Current file: <span id="currentFileName"></span>
                    </div>
                    <div id="analysisResult" class="analysis-result">
                        <div style="text-align: center; color: #6b7280; padding: 40px;">
                            <p>Upload log files to begin analysis</p>
                        </div>
                    </div>
                </div>
                
                <div class="card">
                    <div class="card-title">
                        Ask Questions
                    </div>
                    <div class="chat-container">
                        <input 
                            type="text" 
                            id="question" 
                            class="chat-input" 
                            placeholder="What questions do you have about this log?"
                            onkeypress="if(event.key === 'Enter') askLLM()"
                        >
                        <button onclick="askLLM()" class="btn btn-primary">
                            Ask
                        </button>
                    </div>
                    
                    <div id="llmHistory" class="history-container">
                        <div style="text-align: center; color: #6b7280; padding: 20px;">
                            <p>No questions yet. Ask something above!</p>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    </div>

    <script>
    // Global variables
    let eventId = null;
    let taskId = null;
    let currentProgress = 0;
    let currentFileName = '';
    
    // Simulate backend context data (will be fetched from backend API)
    let llm_contexts = {};
    let latest_event_id = null;
    
    // Language translations
    const translations = {
        'zh': {
            title: 'ESP32 日志分析系统',
            subtitle: '基于AI的日志分析和问题诊断',
            upload_file: '日志文件上传',
            select_file: '选择日志文件',
            start_analysis: '开始分析',
            task_status: '任务状态',
            analysis_results: '分析结果',
            ask_questions: '提问',
            load_history: '加载历史',
            current_file: '当前文件',
            upload_placeholder: '上传日志文件开始分析',
            no_questions: '还没有问题，在上面提问吧！',
            ask_button: '提问',
            waiting_upload: '等待上传...',
            preparing_upload: '准备上传...',
            analysis_complete: '分析完成！',
            task_completed: '✅ 分析任务完成'
        },
        'en': {
            title: 'ESP32 Log Analysis System',
            subtitle: 'AI-powered log analysis and problem diagnosis',
            upload_file: 'Log File Upload',
            select_file: 'Select Log File',
            start_analysis: 'Start Analysis',
            task_status: 'Task Status',
            analysis_results: 'Analysis Results',
            ask_questions: 'Ask Questions',
            load_history: 'Load History',
            current_file: 'Current file',
            upload_placeholder: 'Upload log files to begin analysis',
            no_questions: 'No questions yet. Ask something above!',
            ask_button: 'Ask',
            waiting_upload: 'Waiting for upload...',
            preparing_upload: 'Preparing to upload...',
            analysis_complete: 'Analysis complete!',
            task_completed: '✅ Analysis task completed'
        }
    };

    let currentLang = localStorage.getItem('language') || 'zh';

    function switchLanguage() {
        currentLang = currentLang === 'zh' ? 'en' : 'zh';
        localStorage.setItem('language', currentLang);
        updateLanguage();
    }

    function updateLanguage() {
        const t = translations[currentLang];

        // Update header
        document.querySelector('.header h1').textContent = t.title;
        document.querySelector('.header p').textContent = t.subtitle;

        // Update card titles
        const uploadCard = document.querySelector('.left-panel .card-title');
        if (uploadCard) uploadCard.firstChild.textContent = t.upload_file;

        const statusCard = document.querySelector('.left-panel .card:nth-child(3) .card-title');
        if (statusCard) statusCard.firstChild.textContent = t.task_status;

        const analysisCard = document.querySelector('.right-panel .card:first-child .card-title');
        if (analysisCard) analysisCard.firstChild.textContent = t.analysis_results;

        const qaCard = document.querySelector('.right-panel .card:last-child .card-title');
        if (qaCard) qaCard.firstChild.textContent = t.ask_questions;

        // Update buttons and labels
        const fileLabel = document.getElementById('fileInput')?.nextElementSibling;
        if (fileLabel && fileLabel.tagName === 'LABEL') {
            fileLabel.textContent = t.select_file;
        }

        const analysisBtn = document.querySelector('button[onclick="uploadFile()"]');
        if (analysisBtn) analysisBtn.textContent = t.start_analysis;

        const historyBtn = document.querySelector('button[onclick="loadConversationHistory()"]');
        if (historyBtn) historyBtn.textContent = t.load_history;

        const askBtn = document.querySelector('button[onclick="askLLM()"]');
        if (askBtn) askBtn.textContent = t.ask_button;

        // Update placeholder text
        const questionInput = document.getElementById('question');
        if (questionInput) questionInput.placeholder = currentLang === 'zh' ? '您对此日志有什么疑问？' : 'What questions do you have about this log?';

        // Update static text
        const uploadPlaceholder = document.querySelector('.analysis-result div[style*="text-align: center"]');
        if (uploadPlaceholder && uploadPlaceholder.textContent.includes('Upload') || uploadPlaceholder.textContent.includes('上传')) {
            uploadPlaceholder.querySelector('p').textContent = t.upload_placeholder;
        }

        const noQuestionsText = document.querySelector('#llmHistory div[style*="text-align: center"]');
        if (noQuestionsText && (noQuestionsText.textContent.includes('No questions') || noQuestionsText.textContent.includes('还没有问题'))) {
            noQuestionsText.querySelector('p').textContent = t.no_questions;
        }

        // Update language button
        const langBtn = document.getElementById('langBtn');
        if (langBtn) langBtn.textContent = currentLang === 'zh' ? 'EN' : '中文';
    }

    // Sync backend context data
    function syncContextsFromBackend() {
        fetch('/debug/contexts')
        .then(res => res.json())
        .then(data => {
            llm_contexts = data.contexts || {};
            latest_event_id = data.latest_event_id;
            console.log('Context data sync successful:', llm_contexts);
        })
        .catch(err => {
            console.error('Context data sync failed:', err);
        });
    }
    
    // Sync data once on page load
    window.addEventListener('load', function() {
        syncContextsFromBackend();
        updateLanguage();
    });

    // File selection display filename
    document.getElementById('fileInput').addEventListener('change', function(e) {
        const file = e.target.files[0];
        if (file) {
            currentFileName = file.name;
            const t = translations[currentLang];
            document.getElementById('fileName').textContent = (currentLang === 'zh' ? '已选择: ' : 'Selected: ') + currentFileName;
            document.getElementById('progressText').textContent = t.preparing_upload;
            document.getElementById('progress').style.width = '0%';
        }
    });

    function updateProgress(progress, text) {
        currentProgress = progress;
        document.getElementById('progress').style.width = progress + '%';
        document.getElementById('progressText').textContent = text;
    }

    function updateStatus(message, isError = false) {
        const statusDiv = document.getElementById('status');
        const timestamp = new Date().toLocaleTimeString();
        statusDiv.innerHTML += `[${timestamp}] ${message}\\n`;
        statusDiv.scrollTop = statusDiv.scrollHeight;
        
        if (isError) {
            statusDiv.style.borderLeftColor = 'var(--danger)';
        } else {
            statusDiv.style.borderLeftColor = 'var(--primary)';
        }
    }

    function uploadFile() {
        const file = document.getElementById("fileInput").files[0];
        const metadata = document.getElementById("metadata").value || "{}";
        
        if (!file) {
            alert("Please select a log file first");
            return;
        }

        // Reset UI state
        resetUIForNewFile(file.name);

        updateProgress(10, "Uploading...");
        updateStatus("Starting file upload...");

        const formData = new FormData();
        formData.append("file", file);
        formData.append("metadata", metadata);

        fetch("/upload", {method:"POST", body: formData})
        .then(res => res.json())
        .then(data => {
            if(data.error){
                updateStatus("Upload failed: " + JSON.stringify(data.error), true);
                updateProgress(0, "Upload failed");
                return;
            }
            eventId = data.event_id;
            taskId = data.task_id;
            updateStatus(`File uploaded successfully! Event ID: ${eventId}`);
            updateStatus(`Task ID: ${taskId}`);
            updateProgress(30, "Task queued...");
            
            // Display current file info
            const t = translations[currentLang];
            document.getElementById('currentFileInfo').style.display = 'block';
            document.getElementById('currentFileName').textContent = currentFileName;
            document.getElementById('currentFileBadge').style.display = 'inline-block';

            // Update current file text
            const currentFileDiv = document.getElementById('currentFileInfo');
            if (currentFileDiv) {
                currentFileDiv.innerHTML = `${t.current_file}: <span id="currentFileName">${currentFileName}</span>`;
            }
            
            setTimeout(() => pollStatus(eventId), 1000);
        })
        .catch(err=> {
            console.error('Upload error details:', err);
            const errorMsg = err.message || err.toString() || "Unknown upload error";
            updateStatus("Upload error: " + errorMsg, true);
            updateProgress(0, "Upload failed");
        });
    }

    function resetUIForNewFile(fileName) {
        // Reset analysis results area
        document.getElementById('analysisResult').innerHTML = `
            <div style="text-align: center; color: var(--gray); padding: 40px;">
                <div class="loading" style="margin: 0 auto 15px; width: 40px; height: 40px;"></div>
                <p>Preparing to analyze file: ${fileName}</p>
            </div>
        `;
        
        // Reset conversation history
        document.getElementById("llmHistory").innerHTML = `
            <div style="text-align: center; color: var(--gray); padding: 20px;">
                <i class="fas fa-comment-dots" style="font-size: 2rem;"></i>
                <p>Start a new conversation!</p>
            </div>
        `;
        
        // Reset status area
        const t = translations[currentLang];
        document.getElementById("status").innerHTML = t.waiting_upload;
        document.getElementById("status").style.borderLeftColor = "var(--primary)";

        // Reset progress
        updateProgress(0, t.preparing_upload);
    }

    function pollStatus(currentEventId) {
        if (!taskId) return;
        
        fetch(`/status/${taskId}?event_id=${currentEventId}`)
        .then(res => res.json())
        .then(data => {
            console.log('Status response:', data);
            
            // Update progress
            if (data.info && data.info.progress) {
                updateProgress(data.info.progress, `Processing: ${data.info.stage || 'Analyzing'}...`);
            } else if (data.progress) {
                updateProgress(data.progress, `Processing...`);
            }
            
            // Update status
            let statusText = `Status: ${data.state}\n`;
            if (data.stage) statusText += `Stage: ${data.stage}\n`;
            if (data.progress) statusText += `Progress: ${data.progress}%\n`;
            
            updateStatus(statusText);
            
            if (data.state === "SUCCESS") {
                const t = translations[currentLang];
                updateProgress(100, t.analysis_complete);
                updateStatus(t.task_completed);
                
                let resultData = data.result || data.llm_output || data;
                console.log('Original result data:', resultData);
                
                if (typeof resultData === 'string') {
                    try {
                        resultData = JSON.parse(resultData);
                    } catch (e) {
                        console.error('Result parsing failed:', e);
                        resultData = { summary: resultData };
                    }
                }
                
                console.log('Processed result data:', resultData);
                renderAnalysisResult(resultData);
                
            } else if (data.state === "FAILURE") {
                updateProgress(0, "Analysis failed");
                updateStatus("❌ Task failed: " + (data.error || "Unknown error"), true);
                renderAnalysisResult({ 
                    summary: "Analysis failed: " + (data.error || "Unknown error"),
                    error: true 
                });
            } else {
                setTimeout(() => pollStatus(currentEventId), 2000);
            }
        })
        .catch(err => {
            console.error('Status query error:', err);
            const errorMsg = err.message || err.toString() || "Network connection error";
            updateStatus("Status query error: " + errorMsg, true);
            updateProgress(0, "Connection failed");
        });
    }

    function renderAnalysisResult(result) {
        const analysisDiv = document.getElementById('analysisResult');
        analysisDiv.innerHTML = '';
        
        console.log('Rendering analysis results:', result);
        
        if (!result || (result.error)) {
            analysisDiv.innerHTML = `
                <div style="text-align: center; color: var(--danger); padding: 40px;">
                    <i class="fas fa-exclamation-triangle" style="font-size: 3rem; margin-bottom: 15px;"></i>
                    <p>${result && result.summary ? result.summary : 'No analysis result data'}</p>
                </div>
            `;
            return;
        }
        
        let html = '';
        
        // Render summary
        if (result.summary) {
            html += `
                <div style="margin-bottom: 20px;">
                    <h3 style="color: var(--primary); margin-bottom: 10px;">
                        <i class="fas fa-star"></i> Analysis Summary
                    </h3>
                    <p style="background: #f8fafc; padding: 15px; border-radius: 8px; border-left: 4px solid var(--primary);">
                        ${result.summary}
                    </p>
                </div>
            `;
        }
        
        // Render statistics
        if (result.total_chunks_processed || result.successful_chunks) {
            html += `
                <div style="display: flex; gap: 15px; margin-bottom: 20px; flex-wrap: wrap;">
                    ${result.total_chunks_processed ? `
                        <div style="background: #f0f9ff; padding: 12px; border-radius: 8px; min-width: 120px; text-align: center;">
                            <div style="font-size: 1.5rem; color: var(--primary); font-weight: bold;">${result.total_chunks_processed}</div>
                            <div style="font-size: 0.8rem; color: var(--secondary);">Total Chunks</div>
                        </div>
                    ` : ''}
                    ${result.successful_chunks ? `
                        <div style="background: #f0fdf4; padding: 12px; border-radius: 8px; min-width: 120px; text-align: center;">
                            <div style="font-size: 1.5rem; color: var(--success); font-weight: bold;">${result.successful_chunks}</div>
                            <div style="font-size: 0.8rem; color: var(--secondary);">Successful Chunks</div>
                        </div>
                    ` : ''}
                </div>
            `;
        }
        
          
        analysisDiv.innerHTML = html;
    }

    
    function switchContext(selectedEventId) {
        if (!selectedEventId) {
            // If empty value selected, restore to current file
            if (eventId) {
                document.getElementById('contextBadge').style.display = 'none';
                loadCurrentAnalysis();
            }
            return;
        }

        // Switch to selected context
        eventId = selectedEventId;
        
        // Prioritize using locally synced context data
        if (llm_contexts && llm_contexts[selectedEventId]) {
            const context = llm_contexts[selectedEventId];
            console.log('Switching using local context data:', context);
            
            if (context) {
                document.getElementById('currentFileName').textContent = context.filename || 'Unknown file';
                document.getElementById('currentFileInfo').style.display = 'block';
                document.getElementById('contextBadge').style.display = 'inline-block';
                
                // Display multi-file context prompt
                const historyDiv = document.getElementById('llmHistory');
                if (historyDiv.innerHTML.includes('Start a new conversation!') ||
                    historyDiv.innerHTML.includes('Start the conversation!') ||
                    historyDiv.innerHTML.includes('Continue the conversation!')) {
                    historyDiv.innerHTML = `
                        <div style="text-align: center; color: var(--primary); padding: 20px;">
                            <i class="fas fa-exchange-alt" style="font-size: 2rem; margin-bottom: 10px;"></i>
                            <p>Switched to file: ${context.filename || 'Unknown file'}</p>
                            <p style="font-size: 14px; color: var(--secondary); margin-top: 10px;">
                                You can now ask questions based on this file's log content
                            </p>
                        </div>
                    `;
                }
                
                // Load analysis results for selected file
                loadCurrentAnalysis();
            }
        } else {
            // If no local data, fetch from backend
            console.log('No local data, fetching context from backend');
            fetch('/debug/contexts')
            .then(res => res.json())
            .then(data => {
                // Update local data
                llm_contexts = data.contexts || {};
                latest_event_id = data.latest_event_id;
                
                const context = llm_contexts[selectedEventId];
                if (context) {
                    document.getElementById('currentFileName').textContent = context.filename || 'Unknown file';
                    document.getElementById('currentFileInfo').style.display = 'block';
                    document.getElementById('contextBadge').style.display = 'inline-block';
                    
                    // Display multi-file context prompt
                    const historyDiv = document.getElementById('llmHistory');
                    if (historyDiv.innerHTML.includes('Start a new conversation!') ||
                        historyDiv.innerHTML.includes('Start the conversation!') ||
                        historyDiv.innerHTML.includes('Continue the conversation!')) {
                        historyDiv.innerHTML = `
                            <div style="text-align: center; color: var(--primary); padding: 20px;">
                                <i class="fas fa-exchange-alt" style="font-size: 2rem; margin-bottom: 10px;"></i>
                                <p>Switched to file: ${context.filename || 'Unknown file'}</p>
                                <p style="font-size: 14px; color: var(--secondary); margin-top: 10px;">
                                    You can now ask questions based on this file's log content
                                </p>
                            </div>
                        `;
                    }
                    
                    // Load analysis results for selected file
                    loadCurrentAnalysis();
                }
            })
            .catch(err => {
                console.error('Failed to switch context from backend:', err);
                // Display error prompt
                const historyDiv = document.getElementById('llmHistory');
                if (historyDiv.innerHTML.includes('Start a new conversation!') ||
                    historyDiv.innerHTML.includes('Start the conversation!') ||
                    historyDiv.innerHTML.includes('Continue the conversation!')) {
                    historyDiv.innerHTML = `
                        <div style="text-align: center; color: var(--danger); padding: 20px;">
                            <i class="fas fa-exclamation-triangle" style="font-size: 2rem; margin-bottom: 10px;"></i>
                            <p>File switch failed, please try again</p>
                        </div>
                    `;
                }
            });
        }
    }

    function loadCurrentAnalysis() {
        if (!eventId) return;
        
        // Prioritize using locally synced context data
        if (llm_contexts && llm_contexts[eventId]) {
            const context = llm_contexts[eventId];
            console.log('Loading analysis results using local context data:', context);
            
            if (context && (context.summary || context.chunks && context.chunks.length > 0)) {
                // If there are analysis results, display them
                renderAnalysisResult(context);
            } else {
                // If no analysis results, show waiting status
                document.getElementById('analysisResult').innerHTML = `
                    <div style="text-align: center; color: var(--gray); padding: 40px;">
                        <div class="loading" style="margin: 0 auto 15px;"></div>
                        <p>Loading analysis results...</p>
                    </div>
                `;
            }
        } else {
            // If no local data, fetch from backend
            console.log('No local data, fetching analysis results from backend');
            fetch('/debug/contexts')
            .then(res => res.json())
            .then(data => {
                // Update local data
                llm_contexts = data.contexts || {};
                latest_event_id = data.latest_event_id;
                
                const context = llm_contexts[eventId];
                if (context && (context.summary || context.chunks && context.chunks.length > 0)) {
                    // If there are analysis results, display them
                    renderAnalysisResult(context);
                } else {
                    // If no analysis results, show waiting status
                    document.getElementById('analysisResult').innerHTML = `
                        <div style="text-align: center; color: var(--gray); padding: 40px;">
                            <div class="loading" style="margin: 0 auto 15px;"></div>
                            <p>Loading analysis results...</p>
                        </div>
                    `;
                }
            })
            .catch(err => {
                console.error('Failed to load analysis results from backend:', err);
                // Display error status
                document.getElementById('analysisResult').innerHTML = `
                    <div style="text-align: center; color: var(--danger); padding: 40px;">
                        <i class="fas fa-exclamation-triangle" style="font-size: 3rem; margin-bottom: 15px;"></i>
                        <p>Failed to load analysis results</p>
                    </div>
                `;
            });
        }
    }

    function loadConversationHistory() {
        fetch('/conversation/history?limit=10')
        .then(res => res.json())
        .then(data => {
            if (data.success && data.history && data.history.length > 0) {
                const historyDiv = document.getElementById('llmHistory');
                historyDiv.innerHTML = `
                    <div style="text-align: center; color: var(--primary); padding: 15px; margin-bottom: 15px; border-bottom: 1px solid #e2e8f0;">
                        <i class="fas fa-history"></i> Recent Conversation History (${data.history.length} items)
                    </div>
                `;
                
                data.history.forEach(conv => {
                    const timeStr = new Date(conv.timestamp * 1000).toLocaleString();
                    historyDiv.innerHTML += `
                        <div style="margin-bottom: 15px; padding: 10px; background: #f8fafc; border-radius: 8px;">
                            <div style="font-size: 12px; color: var(--secondary); margin-bottom: 5px;">
                                <i class="fas fa-clock"></i> ${timeStr} | ${conv.filename}
                            </div>
                            <div class="message message-question" style="margin: 5px 0;">
                                <strong>Q:</strong> ${conv.question}
                            </div>
                            <div class="message message-answer" style="margin: 5px 0;">
                                <strong>A:</strong> ${conv.answer}
                            </div>
                        </div>
                    `;
                });
                
                historyDiv.innerHTML += `
                    <div style="text-align: center; color: var(--gray); padding: 15px; border-top: 1px solid #e2e8f0;">
                        <i class="fas fa-comment-dots"></i> Continue the conversation!
                    </div>
                `;
                
                historyDiv.scrollTop = historyDiv.scrollHeight;
            } else {
                // If no history records, show prompt
                const historyDiv = document.getElementById('llmHistory');
                historyDiv.innerHTML = `
                    <div style="text-align: center; color: var(--gray); padding: 40px;">
                        <i class="fas fa-inbox" style="font-size: 2rem; margin-bottom: 15px;"></i>
                        <p>No conversation history records</p>
                    </div>
                `;
            }
        })
        .catch(err => {
            console.error('Failed to load conversation history:', err);
            const historyDiv = document.getElementById('llmHistory');
            historyDiv.innerHTML = `
                <div style="text-align: center; color: var(--danger); padding: 40px;">
                    <i class="fas fa-exclamation-triangle" style="font-size: 2rem; margin-bottom: 15px;"></i>
                    <p>Failed to load conversation history</p>
                </div>
            `;
        });
    }

    function askLLM() {
        const question = document.getElementById("question").value.trim();
        if (!question) { 
            alert("Please enter a question"); 
            return; 
        }

        // Sync latest context data before asking question
        syncContextsFromBackend();
        
        const historyDiv = document.getElementById("llmHistory");
        // Clear initial prompts
        if (historyDiv.innerHTML.includes('Start a new conversation!') ||
            historyDiv.innerHTML.includes('Start the conversation!') ||
            historyDiv.innerHTML.includes('Continue the conversation!')) {
            historyDiv.innerHTML = '';
        }
        
        historyDiv.innerHTML += `
            <div class="message message-question">
                <strong>Q:</strong> ${question}
            </div>
            <div class="message message-answer" id="loadingMessage">
                <div class="loading"></div> Thinking...
            </div>
        `;
        historyDiv.scrollTop = historyDiv.scrollHeight;
        
        document.getElementById("question").value = "";

        fetch(`/query_llm/followup`, {
            method: "POST",
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({
                question: question,
                event_id: eventId  // Pass current event_id
            })
        })
        .then(res => {
            if (!res.ok) {
                throw new Error(`HTTP error! Status code: ${res.status}`);
            }
            return res.text();
        })
        .then(text => {
            const loadingMsg = document.getElementById("loadingMessage");
            if (loadingMsg) loadingMsg.remove();
            
            historyDiv.innerHTML += `
                <div class="message message-answer">
                    <strong>A:</strong> ${text}
                </div>
            `;
            historyDiv.scrollTop = historyDiv.scrollHeight;
        })
        .catch(err=> {
            console.error('Q&A request failed:', err);
            const loadingMsg = document.getElementById("loadingMessage");
            if (loadingMsg) loadingMsg.remove();

            const errorMsg = err.message || err.toString() || "Network request failed";
            historyDiv.innerHTML += `
                <div class="message message-answer" style="color: var(--danger);">
                    <strong>Error:</strong> ${errorMsg}
                </div>
            `;
        });
    }
    </script>
</body>
</html>
"""

# ---------- Helper Functions ----------

def call_deepseek_sync(prompt: str) -> str:
    """Synchronous call to ZhiPu AI API"""
    try:
        response = deepseek_client.chat.completions.create(
            model="glm-4-plus",
            messages=[{"role": "user", "content": prompt}],
            stream=False
        )

        # Check response type and handle correctly
        if hasattr(response, 'choices') and response.choices:
            return response.choices[0].message.content
        elif hasattr(response, 'content'):
            return response.content
        else:
            # If response format doesn't match expectations, try converting to string
            logger.warning("Unexpected response format: %s", type(response))
            return str(response)
    except Exception as e:
        logger.error("ZhiPu AI API call failed: %s", e)
        return f"API call failed: {str(e)}"

def add_conversation_to_history(event_id: str, question: str, answer: str, filename: str = ""):
    """Add conversation to history"""
    global conversation_history, MAX_HISTORY_SIZE
    
    conversation_entry = {
        "timestamp": time.time(),
        "event_id": event_id,
        "filename": filename,
        "question": question,
        "answer": answer
    }
    
    conversation_history.append(conversation_entry)
    
    # If history exceeds maximum limit, delete oldest records
    if len(conversation_history) > MAX_HISTORY_SIZE:
        conversation_history.pop(0)
    
    logger.info("Added conversation to history: event_id=%s, filename=%s", event_id, filename)

def get_conversation_history(limit: int = 20) -> List[Dict[str, Any]]:
    """Get conversation history records"""
    global conversation_history
    # Return the most recent 'limit' records
    return conversation_history[-limit:] if conversation_history else []

def clear_conversation_history():
    """Clear conversation history"""
    global conversation_history
    conversation_history.clear()
    logger.info("Cleared conversation history")

# ---------- Route Implementation ----------

@app.get("/", response_class=HTMLResponse)
async def root():
    return HTMLResponse(INDEX_HTML)

@app.get("/health")
async def health_check():
    """Health check endpoint"""
    try:
        redis_client.ping()
        minio_client.bucket_exists(BUCKET)
        celery.control.inspect().ping()
        
        return JSONResponse({
            "status": "healthy", 
            "services": ["redis", "minio", "celery"],
            "timestamp": time.time(),
            "contexts_count": len(llm_contexts),
            "latest_event_id": latest_event_id
        })
    except Exception as e:
        logger.error("Health check failed: %s", e)
        raise HTTPException(status_code=500, detail=f"Service unhealthy: {e}")

@app.post("/upload")
async def upload_log(file: UploadFile, metadata: str = Form("{}")):
    event_id = str(uuid.uuid4())
    filename = file.filename or "upload.log"
    minio_path = f"{event_id}_{filename}"

    try:
        content = await file.read()
        file_like = io.BytesIO(content)
        minio_client.put_object(
            bucket_name=BUCKET,
            object_name=minio_path,
            data=file_like,
            length=len(content),
            content_type="text/plain"
        )
        logger.info("Uploaded file to MinIO: %s -> %s", filename, minio_path)
    except Exception as e:
        logger.exception("Failed to upload file to MinIO")
        raise HTTPException(status_code=500, detail=f"MinIO upload failed: {e}")

    try:
        task = preprocess_file.apply_async(args=[event_id, minio_path])
        logger.info("Queued preprocess task: %s for event %s", task.id, event_id)
        
        # Initialize context
        llm_contexts[event_id] = {
            "event_id": event_id,
            "filename": filename,
            "upload_time": time.time(),
            "summary": "",
            "chunks": []
        }
        
        return JSONResponse({
            "event_id": event_id, 
            "task_id": task.id, 
            "minio_path": minio_path,
            "filename": filename
        })
    except Exception as e:
        logger.exception("Failed to queue Celery task")
        raise HTTPException(status_code=500, detail=f"Failed to queue task: {e}")

@app.get("/status/{task_id}")
async def get_status(task_id: str, event_id: Optional[str] = None):
    try:
        task_result = AsyncResult(task_id, app=celery)
        resp: Dict[str, Any] = {"task_id": task_id, "state": task_result.state}
        info = getattr(task_result, "info", None)

        if info and isinstance(info, dict):
            if "llm_output" in info:
                resp["llm_output"] = info["llm_output"]
            elif "result" in info and isinstance(info["result"], dict):
                resp.update(info["result"])
            if "progress" in info:
                resp["progress"] = info["progress"]
            if "stage" in info:
                resp["stage"] = info["stage"]

        if task_result.state == "SUCCESS":
            result = getattr(task_result, "result", {})
            logger.info("Task %s completed with result type: %s", task_id, type(result))
            
            if isinstance(result, dict):
                # Update corresponding context
                if event_id and event_id in llm_contexts:
                    llm_contexts[event_id].update(result)
                    # Update latest event ID
                    global latest_event_id
                    latest_event_id = event_id
                    logger.info("Updated context for event: %s", event_id)
                
                resp["result"] = result

        elif task_result.state == "FAILURE":
            resp["error"] = str(task_result.result or task_result.info)

        return JSONResponse(resp)
    except Exception as e:
        logger.exception("status query failed")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/query_llm/{event_id}")
async def get_llm_result(event_id: str):
    try:
        result = redis_client.get(f"llm_result:{event_id}")
        if result:
            context = json.loads(result)
            return JSONResponse({
                "event_id": event_id,
                "status": "done",
                "llm_output": context
            })
        else:
            return JSONResponse({
                "event_id": event_id,
                "status": "processing",
                "message": "Results not yet generated or expired"
            })
    except Exception as e:
        logger.exception("query_llm error")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/query_llm/followup")
async def query_llm_followup(payload: Dict[str, Any]):
    """User follow-up Q&A interface"""
    question = payload.get("question", "").strip()
    event_id = payload.get("event_id") or latest_event_id
    
    if not question:
        return PlainTextResponse("Please provide question content")
    
    if not event_id or event_id not in llm_contexts:
        return PlainTextResponse("No available log analysis, please upload file first")

    context = llm_contexts[event_id]
    
    if not context.get("summary"):
        return PlainTextResponse("Log analysis not yet completed, please try again later")

    # Get recent conversation history (up to 5 items)
    recent_history = get_conversation_history(limit=5)
    history_text = ""
    if recent_history:
        history_text = "\n\nRecent conversation history:\n"
        for conv in recent_history:
            history_text += f"Q: {conv['question']}\nA: {conv['answer']}\n\n"

    # Construct prompt
    chunks_text = ""
    if context.get("chunks"):
        for ch in context["chunks"]:
            analysis = ch.get("analysis", {})
            summary = analysis.get("summary", "")
            if summary:
                chunks_text += f"{ch.get('chunk_id', '')}: {summary}\n"

    prompt_for_llm = f"""
User question: {question}

Current log file: {context.get('filename', 'Unknown file')}
Log summary: {context.get('summary')}
{history_text}Log chunk summary:
{chunks_text}

Please answer the question based on the above log content and conversation history, generating a concise and clear text answer.
If the question is related to previous conversations, please maintain consistency in your response.
"""

    try:
        llm_output = await asyncio.to_thread(call_deepseek_sync, prompt_for_llm)
        
        # Add conversation to history
        add_conversation_to_history(
            event_id=event_id,
            question=question,
            answer=llm_output,
            filename=context.get("filename", "")
        )
        
        return PlainTextResponse(llm_output)
    except Exception as e:
        logger.error("DeepSeek call failed: %s", e)
        return PlainTextResponse("Sorry, analysis service is temporarily unavailable")

@app.get("/debug/contexts")
async def debug_contexts():
    """Debug endpoint: view all contexts"""
    return JSONResponse({
        "latest_event_id": latest_event_id,
        "contexts_count": len(llm_contexts),
        "contexts": {
            event_id: {
                "filename": ctx.get("filename"),
                "has_summary": bool(ctx.get("summary")),
                "chunks_count": len(ctx.get("chunks", [])),
                "upload_time": ctx.get("upload_time")
            }
            for event_id, ctx in llm_contexts.items()
        }
    })

@app.get("/conversation/history")
async def get_conversation_history_api(limit: int = 20):
    """Get conversation history API"""
    try:
        history = get_conversation_history(limit)
        return JSONResponse({
            "success": True,
            "count": len(history),
            "history": history
        })
    except Exception as e:
        logger.exception("Failed to get conversation history")
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/conversation/history")
async def clear_conversation_history_api():
    """Clear conversation history API"""
    try:
        old_count = len(conversation_history)
        clear_conversation_history()
        return JSONResponse({
            "success": True,
            "message": f"Cleared {old_count} conversation history records"
        })
    except Exception as e:
        logger.exception("Failed to clear conversation history")
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
