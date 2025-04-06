# FastAPI + Celery + Redis + OpenAI Example (with Simple Fallback)

This application demonstrates processing potentially long-running OpenAI API tasks asynchronously using FastAPI, Celery, and Redis. It prioritizes using the OpenAI API but includes a simple fallback mechanism if the `OPENAI_API_KEY` is not provided.

## Functionality

This application processes text prompts asynchronously using Celery.

*   **If an `OPENAI_API_KEY` is provided** (via a `.env` file or environment variable):
    *   The prompt is sent to the OpenAI API (using `gpt-3.5-turbo` by default in the provided code).
    *   The actual response from OpenAI is returned once the task is finished.
*   **If no `OPENAI_API_KEY` is found:**
    *   The application enters a **simple fallback mode**.
    *   The task simulates processing by waiting for 10 seconds (`time.sleep(10)`).
    *   A fixed, pre-defined string is returned, prepended with the original user prompt. This avoids errors related to local model loading and serves as a basic placeholder for demonstrating the async flow.

## Prerequisites

1.  **Python:** Version 3.12 recommended (or 3.8+).
2.  **Redis:** A running Redis server instance.
3.  **OpenAI API Key (Optional):** Required only if you want to use the OpenAI service. If not provided, the app will use the simple fallback mode.

## Installation

1.  **Clone the repository (or save the files):**
    ```bash
    # If you have a git repo:
    # git clone <your-repo-url>
    # cd <your-repo-directory>

    # Otherwise, just create a directory and save app.py, requirements.txt,
    # and this README.md file in it.
    mkdir celery-openai-fastapi
    cd celery-openai-fastapi
    # <Save files here>
    ```

2.  **Create and activate a virtual environment:**
    ```bash
    python -m venv venv
    # On Windows:
    # .\venv\Scripts\activate
    # On macOS/Linux:
    source venv/bin/activate
    ```
    *(Adjust `venv` name if preferred, e.g., `ucu_apps_2025_celery_example`)*

    Alternatively using pyenv:
    ```bash
    # On macOS/Linux
    # pyenv virtualenv 3.12 <your_env_name>
    # pyenv activate <your_env_name>
    ```

3.  **Install Python dependencies:**
    ```bash
    pip install -r requirements.txt
    ```
    *(Note: This version has fewer dependencies as the local model fallback has been removed.)*

4.  **Install and Start Redis:**

    *   **macOS (using Homebrew):**
        ```bash
        brew install redis
        brew services start redis
        ```
        (Or run `redis-server` directly in a separate terminal)

    *   **Linux (Debian/Ubuntu):**
        ```bash
        sudo apt update
        sudo apt install redis-server
        sudo systemctl start redis-server
        sudo systemctl enable redis-server
        ```

    *   **Linux (Fedora/CentOS):**
        ```bash
        sudo dnf install redis
        sudo systemctl start redis
        sudo systemctl enable redis
        ```

    *Verify Redis is running:*
    ```bash
    redis-cli ping
    # Expected output: PONG
    ```
    You might also see Redis server logs in the console if running it directly.

5.  **Set up OpenAI API Key (Optional):**
    *   **To use OpenAI:** Create a file named `.env` in the project root directory (the same directory as `app.py`). Add your OpenAI API key to this file:
        ```plaintext
        # .env
        OPENAI_API_KEY=your_actual_openai_api_key_here
        ```
        **Important:** Ensure this `.env` file is added to your `.gitignore` if you are using Git.
    *   **To use the simple fallback:** Simply **do not** create the `.env` file or ensure the `OPENAI_API_KEY` variable is not set in your environment.

## Running the Application

You need to run three components, typically in separate terminal windows/tabs (make sure your virtual environment is activated in each):

1.  **Start the Redis Server:** (Ensure it's running as per installation steps).

2.  **Start the Celery Worker:**
    (From the project root directory where `app.py` is located)
    ```bash
    celery -A app.celery_app worker --loglevel=info
    ```
    *   `-A app.celery_app`: Points Celery to the `celery_app` instance inside `app.py`.
    *   `worker`: Starts the worker process.
    *   `--loglevel=info`: Sets the logging level.

3.  **Start the FastAPI Application:**
    (From the project root directory)
    ```bash
    uvicorn app:app --reload --port 8000
    ```
    *   `app:app`: Points Uvicorn to the `app` instance (FastAPI app) inside `app.py`.
    *   `--reload`: Enables auto-reloading for development (optional).
    *   `--port 8000`: Specifies the port (default is 8000).

## Usage

1.  **Check which mode is active:**
    Visit `http://localhost:8000/` in your browser or use curl:
    ```bash
    curl http://localhost:8000/
    ```
    The response message will indicate whether OpenAI or the "Simple Fallback" mode is active.

2.  **Submit a Task:**
    Send a POST request to the `/process` endpoint with your prompt in the `task` field.

    ```bash
    curl -X POST http://localhost:8000/process \
    -H "Content-Type: application/json" \
    -d '{
      "task": "Tell me five interesting facts about the Universe and space."
    }'
    ```

    The response will be immediate:
    ```json
    {
      "task_id": "some-unique-task-id-generated-by-celery",
      "status": "ACCEPTED"
    }
    ```
    Note down the `task_id`.

3.  **Check Task Status:**
    Send a GET request to the `/status/{task_id}` endpoint.

    ```bash
    curl http://localhost:8000/status/some-unique-task-id-generated-by-celery
    ```

    Possible responses:

    *   **While processing:**
        ```json
        {
          "task_id": "some-unique-task-id-generated-by-celery",
          "status": "IN_PROGRESS",
          "result": null
        }
        ```
    *   **After successful completion (OpenAI):**
        ```json
        {
          "task_id": "some-unique-task-id-generated-by-celery",
          "status": "FINISHED",
          "result": "1. The observable universe is about 93 billion light-years in diameter..." // (Actual output from OpenAI)
        }
        ```
    *   **After successful completion (Simple Fallback):**
        ```json
        {
            "task_id": "some-unique-task-id-generated-by-celery",
            "status": "FINISHED",
            "result": "Your prompt was: 'Tell me five interesting facts about the Universe and space.'. This is a pre-generated fallback answer because no OpenAI API key was provided. Processing was simulated with a delay."
        }
        ```
    *   **If failed (e.g., OpenAI API error):**
        ```json
        {
            "task_id": "some-unique-task-id-generated-by-celery",
            "status": "FAILED",
            "result": {
                "error": "OpenAI API Error", // Or other error type
                "details": "Specific error message..."
            }
        }
        ```

## Example Prompts for Longer Processing (10-15 seconds with OpenAI)

These prompts are designed to potentially take longer for the OpenAI API to process. In the simple fallback mode, the processing time is fixed at 10 seconds regardless of the prompt.

1.  **Detailed Explanation:**
    ```bash
    curl -X POST http://localhost:8000/process -H "Content-Type: application/json" -d '{ "task": "Explain the concept of quantum entanglement in detail, using analogies suitable for a high school student, covering its history, implications, and potential applications. Ensure the explanation is at least 400 words long." }'
    ```

2.  **Creative Writing with Constraints:**
    ```bash
    curl -X POST http://localhost:8000/process -H "Content-Type: application/json" -d '{ "task": "Write a detailed scene (around 500 words) for a fantasy novel where a young apprentice mage accidentally summons a mischievous elemental spirit made of pure moonlight during their final exam. Describe the setting, the summoning ritual going wrong, the appearance and personality of the spirit, and the immediate chaotic aftermath." }'
    ```

3.  **Code Generation and Explanation:**
    ```bash
    curl -X POST http://localhost:8000/process -H "Content-Type: application/json" -d '{ "task": "Generate a Python script that uses the `requests` library to fetch data from a public JSON API (e.g., JSONPlaceholder posts endpoint), processes the data to count the occurrences of each userId, and then prints the counts in descending order. Include comments in the code explaining each major step and add a brief explanation below the code on how it works." }'
    ```

Keep polling the `/status/{task_id}` endpoint for these tasks to observe the `IN_PROGRESS` state before they transition to `FINISHED` or `FAILED`.