import os
import time
import logging
from fastapi import FastAPI, HTTPException, status, Body
from fastapi.responses import JSONResponse
from celery import Celery
from celery.result import AsyncResult
# No longer need worker_process_init
import openai
from pydantic import BaseModel
from dotenv import load_dotenv

# --- Basic Logging Setup ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
log = logging.getLogger(__name__)

# --- Configuration ---
load_dotenv()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

USE_OPENAI = bool(OPENAI_API_KEY)
# No longer need hf_pipeline placeholder

# Define the fallback answer
FALLBACK_ANSWER = "This is a pre-generated fallback answer because no OpenAI API key was provided. Processing was simulated with a delay."

if USE_OPENAI:
    log.info("OPENAI_API_KEY found. Using OpenAI.")
    openai.api_key = OPENAI_API_KEY
else:
    # Update log message for the new fallback
    log.warning("OPENAI_API_KEY not found. Using simple fallback: wait 10s and return pre-generated answer.")

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
    task_acks_late=True,
    worker_prefetch_multiplier=1,
)

# --- Removed Hugging Face Model Loading ---
# The init_hf_model function and its decorator are removed.

# --- FastAPI Setup ---
app = FastAPI(title="OpenAI/Fallback Task Processor")

class TaskRequest(BaseModel):
    task: str

# --- Celery Task Definition ---
@celery_app.task(bind=True, name='process_llm_request')
def process_llm_request(self, prompt: str):
    self.update_state(state='IN_PROGRESS')
    result = None
    task_id = self.request.id # Get task ID for logging
    try:
        if USE_OPENAI:
            log.info(f"Task {task_id}: Processing with OpenAI...")
            response = openai.chat.completions.create(
                model="gpt-4o",
                messages=[
                    {"role": "system", "content": "You are a helpful assistant."},
                    {"role": "user", "content": prompt}
                ],
                max_tokens=300,
                temperature=0.7,
            )
            result = response.choices[0].message.content.strip()
            log.info(f"Task {task_id}: OpenAI processing finished.")

        else:
            # Simple fallback logic
            log.info(f"Task {task_id}: Using fallback - waiting 10 seconds...")
            time.sleep(10) # Simulate work / delay
            result = f"Your prompt was: '{prompt}'. {FALLBACK_ANSWER}"
            log.info(f"Task {task_id}: Fallback processing finished.")

        return result

    except openai.APIError as e:
        # This error handling is only relevant if USE_OPENAI is True
        log.error(f"Task {task_id}: OpenAI API Error - {e}", exc_info=True)
        self.update_state(state='FAILED', meta={'exc_type': type(e).__name__, 'exc_message': str(e)})
        return {"error": "OpenAI API Error", "details": str(e)}
    except Exception as e:
        # General error handling for both cases
        log.error(f"Task {task_id}: General Processing Error - {e}", exc_info=True)
        self.update_state(state='FAILED', meta={'exc_type': type(e).__name__, 'exc_message': str(e)})
        # Re-raise for Celery to mark as FAILED
        raise e


# --- FastAPI Endpoints ---
@app.post("/process", status_code=status.HTTP_202_ACCEPTED)
async def submit_task(payload: TaskRequest = Body(...)):
    if not payload.task:
        raise HTTPException(status_code=400, detail="Task prompt cannot be empty.")
    task = process_llm_request.delay(payload.task)
    log.info(f"Submitted task {task.id} using {'OpenAI' if USE_OPENAI else 'Simple Fallback'}. Prompt: '{payload.task[:50]}...'")
    return JSONResponse({"task_id": task.id, "status": "ACCEPTED"})

@app.get("/status/{task_id}")
async def get_task_status(task_id: str):
    task_result = AsyncResult(task_id, app=celery_app)
    response_status = "PENDING"
    result_data = None

    log.debug(f"Checking status for task {task_id}. Current Celery state: {task_result.state}")

    if task_result.state == 'PENDING':
         response_status = "ACCEPTED"
    elif task_result.state == 'STARTED':
        response_status = "IN_PROGRESS"
    elif task_result.state == 'SUCCESS':
        response_status = "FINISHED"
        result_data = task_result.get()
    elif task_result.state == 'FAILURE':
        response_status = "FAILED"
        try:
            # Retrieve exception info stored by Celery
            exc_info = task_result.info
            if isinstance(exc_info, Exception):
                 result_data = {"error": type(exc_info).__name__, "details": str(exc_info)}
            elif isinstance(exc_info, dict) and "error" in exc_info: # Handle case where task returned error dict
                 result_data = exc_info
            else:
                 result_data = {"error": "Task Failed", "details": str(exc_info) if exc_info else "No specific error details available."}
            log.warning(f"Task {task_id} failed. Result info: {result_data}")
        except Exception as e:
             log.error(f"Error retrieving result/info for failed task {task_id}: {e}")
             result_data = {"error": "Result Retrieval Error", "details": "Could not retrieve failure details."}

    elif task_result.state == 'RETRY':
        response_status = "RETRYING"
    else:
        response_status = task_result.state

    return JSONResponse({"task_id": task_id, "status": response_status, "result": result_data})

@app.get("/")
async def root():
    # Update root message to reflect the simple fallback
    mode = "OpenAI" if USE_OPENAI else "Simple Fallback (10s delay + fixed response)"
    return {"message": f"LLM Task Processor running. Using {mode}."}