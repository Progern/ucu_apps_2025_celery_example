import os
import time
import logging
from fastapi import FastAPI, HTTPException, status, Body
from fastapi.responses import JSONResponse
from celery import Celery
from celery.result import AsyncResult
from celery.signals import worker_process_init # Import worker signal
import openai
from pydantic import BaseModel
from dotenv import load_dotenv

# --- Basic Logging Setup ---
logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

# --- Configuration ---
load_dotenv()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

USE_OPENAI = bool(OPENAI_API_KEY) # Flag to determine which model to use
hf_pipeline = None # Placeholder for Hugging Face pipeline

if USE_OPENAI:
    log.info("OPENAI_API_KEY found. Using OpenAI.")
    openai.api_key = OPENAI_API_KEY
else:
    log.warning("OPENAI_API_KEY not found in environment or .env file. Attempting to use local Hugging Face model (distilgpt2).")
    # We will load the model in the Celery worker process init

REDIS_URL = "redis://localhost:6379/0"

# --- Celery Setup ---
celery_app = Celery(
    'tasks',
    broker=REDIS_URL,
    backend=REDIS_URL
)

celery_app.conf.update(
    task_track_started=True,
    result_expires=3600,
    # Ensure tasks are acknowledged only after completion/failure
    task_acks_late=True,
    # Set worker prefetch multiplier to 1 to avoid loading too many tasks if one fails
    worker_prefetch_multiplier=1,
)

# --- Hugging Face Model Loading (Worker Initialization) ---
@worker_process_init.connect(weak=False)
def init_hf_model(**kwargs):
    global hf_pipeline
    if not USE_OPENAI and hf_pipeline is None:
        try:
            log.info("Loading Hugging Face pipeline (distilgpt2)... This might take a while on first run.")
            # Import here to avoid loading heavy libraries in the main API process if not needed
            from transformers import pipeline
            # Using distilgpt2 for a smaller footprint. Replace with 'gpt2' or others if needed.
            hf_pipeline = pipeline("text-generation", model="distilgpt2")
            log.info("Hugging Face pipeline loaded successfully.")
        except Exception as e:
            log.error(f"Failed to load Hugging Face model: {e}", exc_info=True)
            # The worker process might still run, but tasks requiring HF will fail.
            hf_pipeline = None # Ensure it's None if loading failed

# --- FastAPI Setup ---
app = FastAPI(title="OpenAI/HF Task Processor")

class TaskRequest(BaseModel):
    task: str

# --- Celery Task Definition ---
@celery_app.task(bind=True, name='process_llm_request')
def process_llm_request(self, prompt: str):
    self.update_state(state='IN_PROGRESS')
    result = None
    try:
        if USE_OPENAI:
            log.info(f"Task {self.request.id}: Processing with OpenAI...")
            response = openai.chat.completions.create(
                model="gpt-4o",
                messages=[
                    {"role": "system", "content": "You are a helpful assistant."},
                    {"role": "user", "content": prompt}
                ],
                max_tokens=300, # Adjusted token limit slightly
                temperature=0.7,
            )
            result = response.choices[0].message.content.strip()
            log.info(f"Task {self.request.id}: OpenAI processing finished.")

        else:
            log.info(f"Task {self.request.id}: Processing with local Hugging Face model...")
            if hf_pipeline is None:
                 log.error(f"Task {self.request.id}: Hugging Face pipeline not available.")
                 raise RuntimeError("Hugging Face model could not be loaded.")

            # Generate text using the pipeline
            # Adjust max_length and other parameters as needed
            # Note: Simple pipelines might not handle conversational context well.
            # Consider adding context or using more advanced HF techniques if needed.
            outputs = hf_pipeline(prompt, max_length=300, num_return_sequences=1, pad_token_id=hf_pipeline.tokenizer.eos_token_id)
            result = outputs[0]['generated_text']
            # Often the result includes the prompt, remove it if present
            if result.startswith(prompt):
                 result = result[len(prompt):].strip()
            log.info(f"Task {self.request.id}: Hugging Face processing finished.")

        return result

    except openai.APIError as e:
        log.error(f"Task {self.request.id}: OpenAI API Error - {e}", exc_info=True)
        self.update_state(state='FAILED', meta={'exc_type': type(e).__name__, 'exc_message': str(e)})
        return {"error": "OpenAI API Error", "details": str(e)}
    except Exception as e:
        log.error(f"Task {self.request.id}: General Processing Error - {e}", exc_info=True)
        # Use update_state to ensure meta info is stored before raising
        self.update_state(state='FAILED', meta={'exc_type': type(e).__name__, 'exc_message': str(e)})
        # Re-raise the exception so Celery marks the task as FAILED correctly
        # The result backend will store the exception info.
        raise e


# --- FastAPI Endpoints ---
@app.post("/process", status_code=status.HTTP_202_ACCEPTED)
async def submit_task(payload: TaskRequest = Body(...)):
    if not payload.task:
        raise HTTPException(status_code=400, detail="Task prompt cannot be empty.")
    # Use the correct task name defined in @celery_app.task
    task = process_llm_request.delay(payload.task)
    log.info(f"Submitted task {task.id} with prompt: '{payload.task[:50]}...'")
    return JSONResponse({"task_id": task.id, "status": "ACCEPTED"})

@app.get("/status/{task_id}")
async def get_task_status(task_id: str):
    task_result = AsyncResult(task_id, app=celery_app)
    response_status = "PENDING"
    result_data = None # Renamed from 'result' to avoid conflict

    if task_result.state == 'PENDING':
         response_status = "ACCEPTED" # As per requirement after submission
    elif task_result.state == 'STARTED':
        response_status = "IN_PROGRESS"
    elif task_result.state == 'SUCCESS':
        response_status = "FINISHED"
        result_data = task_result.get()
    elif task_result.state == 'FAILURE':
        response_status = "FAILED"
        # Access the exception info stored by Celery
        # task_result.info often holds the exception instance or traceback
        try:
            # Try to get the result, which might contain our custom error dict if returned
            result_data = task_result.get(propagate=False) # Don't re-raise
            if isinstance(result_data, Exception): # If get() returned the raw exception
                 result_data = {"error": type(result_data).__name__, "details": str(result_data)}
            elif result_data is None: # Fallback if result is None on failure
                 result_data = {"error": "Task Failed", "details": str(task_result.info)}
        except Exception as e:
             # Should not happen with propagate=False, but as a safeguard
             log.error(f"Error retrieving result for failed task {task_id}: {e}")
             result_data = {"error": "Result Retrieval Error", "details": str(task_result.info)}

    elif task_result.state == 'RETRY':
        response_status = "RETRYING"
    else:
        response_status = task_result.state # e.g., REVOKED

    log.debug(f"Status check for task {task_id}: State={task_result.state}, ResponseStatus={response_status}")
    return JSONResponse({"task_id": task_id, "status": response_status, "result": result_data})

@app.get("/")
async def root():
    return {"message": f"LLM Task Processor running. Using {'OpenAI' if USE_OPENAI else 'local Hugging Face model'}."}