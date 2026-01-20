"""
Async File Downloader - Non-blocking file downloads with streaming support
Prevents blocking the event loop during large file downloads
"""
import asyncio
import httpx
from typing import Optional, Dict, Any
from datetime import datetime
from connection_pool import get_http_client


class AsyncFileDownloader:
    """
    Handles asynchronous file downloads without blocking the event loop.
    Supports streaming for large files and automatic retry logic.
    Uses connection pooling for better performance.
    """
    
    def __init__(
        self,
        timeout: float = 30.0,
        max_retries: int = 3,
        chunk_size: int = 1024 * 1024,  # 1MB chunks
        use_connection_pool: bool = True
    ):
        """
        Initialize the async file downloader.
        
        Args:
            timeout: Request timeout in seconds
            max_retries: Maximum number of retry attempts
            chunk_size: Size of chunks for streaming downloads (bytes)
            use_connection_pool: Whether to use shared connection pool (recommended)
        """
        self.timeout = timeout
        self.max_retries = max_retries
        self.chunk_size = chunk_size
        self.use_connection_pool = use_connection_pool
        self._http_client = None
    
    def _get_client(self) -> httpx.AsyncClient:
        """Get HTTP client - either pooled or standalone"""
        if self.use_connection_pool:
            # Use shared connection pool for better performance
            return get_http_client(timeout=self.timeout)
        else:
            # Create standalone client (not recommended)
            if self._http_client is None or self._http_client.is_closed:
                self._http_client = httpx.AsyncClient(timeout=self.timeout)
            return self._http_client
    
    async def download_file(
        self,
        url: str,
        headers: Optional[Dict[str, str]] = None,
        stream: bool = True
    ) -> Optional[bytes]:
        """
        Download a file asynchronously without blocking the event loop.
        
        Args:
            url: The URL to download from
            headers: Optional HTTP headers
            stream: Whether to use streaming download (recommended for large files)
            
        Returns:
            File content as bytes, or None if download fails
        """
        start_time = datetime.now()
        
        for attempt in range(1, self.max_retries + 1):
            try:
                # Use connection pooled client
                client = self._get_client()
                
                if stream:
                    # Stream download for large files
                    async with client.stream('GET', url, headers=headers) as response:
                        if response.status_code == 200:
                            chunks = []
                            total_size = 0
                            
                            async for chunk in response.aiter_bytes(chunk_size=self.chunk_size):
                                chunks.append(chunk)
                                total_size += len(chunk)
                                # Allow other tasks to run between chunks
                                await asyncio.sleep(0)
                            
                            file_content = b''.join(chunks)
                            elapsed = (datetime.now() - start_time).total_seconds()
                            
                            print(f"✅ Downloaded {total_size / 1024 / 1024:.2f}MB in {elapsed:.2f}s (attempt {attempt})")
                            return file_content
                        else:
                            print(f"⚠️ Download failed: HTTP {response.status_code} (attempt {attempt})")
                            if attempt < self.max_retries:
                                await asyncio.sleep(1 * attempt)  # Exponential backoff
                            continue
                else:
                    # Simple download for small files
                    response = await client.get(url, headers=headers)
                    if response.status_code == 200:
                        elapsed = (datetime.now() - start_time).total_seconds()
                        print(f"✅ Downloaded {len(response.content) / 1024:.2f}KB in {elapsed:.2f}s")
                        return response.content
                    else:
                        print(f"⚠️ Download failed: HTTP {response.status_code} (attempt {attempt})")
                        if attempt < self.max_retries:
                            await asyncio.sleep(1 * attempt)
                        continue
                            
            except httpx.TimeoutException as e:
                print(f"⚠️ Download timeout (attempt {attempt}/{self.max_retries}): {str(e)}")
                if attempt < self.max_retries:
                    await asyncio.sleep(2 * attempt)
                continue
                
            except httpx.HTTPError as e:
                print(f"⚠️ HTTP error (attempt {attempt}/{self.max_retries}): {str(e)}")
                if attempt < self.max_retries:
                    await asyncio.sleep(2 * attempt)
                continue
                
            except Exception as e:
                print(f"❌ Unexpected error during download (attempt {attempt}/{self.max_retries}): {str(e)}")
                if attempt < self.max_retries:
                    await asyncio.sleep(2 * attempt)
                continue
        
        # All retries failed
        elapsed = (datetime.now() - start_time).total_seconds()
        print(f"❌ Failed to download file after {self.max_retries} attempts ({elapsed:.2f}s)")
        return None
    
    async def download_from_supabase_storage(
        self,
        supabase_client,
        bucket_name: str,
        file_path: str
    ) -> Optional[bytes]:
        """
        Download a file from Supabase Storage asynchronously.
        
        Args:
            supabase_client: Supabase client instance
            bucket_name: Name of the storage bucket
            file_path: Path to the file in the bucket
            
        Returns:
            File content as bytes, or None if download fails
        """
        start_time = datetime.now()
        
        try:
            # Get the download URL first (this is fast)
            loop = asyncio.get_event_loop()
            
            # Use run_in_executor for the synchronous Supabase call
            # But limit this to just getting the URL, not downloading the file
            download_response = await loop.run_in_executor(
                None,
                lambda: supabase_client.storage.from_(bucket_name).download(file_path)
            )
            
            if download_response:
                elapsed = (datetime.now() - start_time).total_seconds()
                file_size = len(download_response) / 1024 / 1024
                print(f"✅ Downloaded {file_size:.2f}MB from Supabase storage in {elapsed:.2f}s")
                return download_response
            else:
                print(f"❌ Failed to download from Supabase storage: No response")
                return None
                
        except Exception as e:
            elapsed = (datetime.now() - start_time).total_seconds()
            print(f"❌ Error downloading from Supabase storage ({elapsed:.2f}s): {str(e)}")
            return None
    
    async def download_multiple_files(
        self,
        urls: list[str],
        headers: Optional[Dict[str, str]] = None,
        concurrent_limit: int = 5
    ) -> Dict[str, Optional[bytes]]:
        """
        Download multiple files concurrently without blocking.
        
        Args:
            urls: List of URLs to download
            headers: Optional HTTP headers
            concurrent_limit: Maximum number of concurrent downloads
            
        Returns:
            Dictionary mapping URL to file content (or None if failed)
        """
        semaphore = asyncio.Semaphore(concurrent_limit)
        
        async def download_with_semaphore(url: str) -> tuple[str, Optional[bytes]]:
            async with semaphore:
                content = await self.download_file(url, headers)
                return (url, content)
        
        print(f"📥 Starting concurrent download of {len(urls)} files (max {concurrent_limit} at once)...")
        start_time = datetime.now()
        
        # Download all files concurrently
        results = await asyncio.gather(
            *[download_with_semaphore(url) for url in urls],
            return_exceptions=True
        )
        
        elapsed = (datetime.now() - start_time).total_seconds()
        
        # Process results
        downloads = {}
        success_count = 0
        
        for result in results:
            if isinstance(result, Exception):
                print(f"❌ Download failed with exception: {result}")
                continue
            
            url, content = result
            downloads[url] = content
            if content is not None:
                success_count += 1
        
        print(f"✅ Completed {success_count}/{len(urls)} downloads in {elapsed:.2f}s")
        return downloads


# Global instance for reuse across the application with connection pooling
file_downloader = AsyncFileDownloader(
    timeout=30.0,
    max_retries=3,
    chunk_size=1024 * 1024,  # 1MB chunks
    use_connection_pool=True  # Enable connection pooling for better performance
)
