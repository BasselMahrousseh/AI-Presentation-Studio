import uvicorn
import argparse
from api.main import app

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run the FastAPI server")
    parser.add_argument(
        "--port", type=int, required=True, help="Port number to run the server on"
    )
    parser.add_argument(
        "--host",
        type=str,
        default="127.0.0.1",
        help="Interface to bind (0.0.0.0 inside a container)",
    )
    parser.add_argument(
        "--reload", type=str, default="false", help="Reload the server on code changes"
    )
    parser.add_argument(
        "--log-level",
        type=str,
        default="info",
        help="Uvicorn log level",
    )
    args = parser.parse_args()
    reload = args.reload == "true"

    uvicorn.run(
        "api.main:app",
        host=args.host,
        port=args.port,
        log_level=args.log_level,
        reload=reload,
    )
