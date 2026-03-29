"""Lyra Model Downloader"""
class ModelDownloader:
    async def download(self, model_id, **kw): return {"status": "error", "message": "Use manual download"}
downloader = ModelDownloader()
