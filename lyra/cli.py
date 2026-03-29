"""Lyra CLI"""
def main():
    import uvicorn, os
    port = int(os.environ.get("LYRA_PORT", 8080))
    host = os.environ.get("LYRA_HOST", "0.0.0.0")
    print(f"Starting Lyra at http://{host}:{port}")
    uvicorn.run("lyra.main:app", host=host, port=port, reload=False)
