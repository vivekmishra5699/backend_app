import asyncio
import concurrent.futures
import os
from typing import Optional, Dict, Any
import traceback
from firebase_admin import auth
import firebase_admin
from firebase_admin import credentials
from functools import lru_cache
import time


# Custom exceptions for better error handling
class TokenExpiredError(Exception):
    """Raised when Firebase ID token has expired"""
    pass

class TokenInvalidError(Exception):
    """Raised when Firebase ID token is invalid"""
    pass

class TokenVerificationError(Exception):
    """Raised when Firebase ID token verification fails"""
    pass


class AsyncFirebaseManager:
    def __init__(self):
        # Consider CPU count for better defaults
        max_workers = int(os.getenv("FIREBASE_MAX_WORKERS", min(32, (os.cpu_count() or 1) * 4)))
        self.executor = concurrent.futures.ThreadPoolExecutor(max_workers=max_workers)
    
    async def verify_id_token(self, id_token: str) -> Optional[Dict[str, Any]]:
        """Verify Firebase ID token asynchronously with better error handling"""
        try:
            # Don't use cache for token verification - tokens can expire
            # and we need to handle that properly
            loop = asyncio.get_event_loop()
            decoded_token = await loop.run_in_executor(
                self.executor,
                lambda: auth.verify_id_token(id_token)
            )
            
            return decoded_token
        except auth.ExpiredIdTokenError as e:
            print(f"Token expired: {e}")
            # Don't log full traceback for expired tokens - it's expected
            raise TokenExpiredError("Firebase ID token has expired. Please refresh your token.") from e
        except auth.InvalidIdTokenError as e:
            print(f"Invalid token: {e}")
            raise TokenInvalidError("Invalid Firebase ID token format.") from e
        except Exception as e:
            print(f"Error verifying ID token: {e}")
            print(f"Traceback: {traceback.format_exc()}")
            raise TokenVerificationError(f"Token verification failed: {str(e)}") from e
    
    async def create_user(self, email: str, password: str, display_name: str = None) -> Optional[auth.UserRecord]:
        """Create Firebase user asynchronously"""
        try:
            loop = asyncio.get_event_loop()
            user_record = await loop.run_in_executor(
                self.executor,
                lambda: auth.create_user(
                    email=email,
                    password=password,
                    display_name=display_name
                )
            )
            return user_record
        except Exception as e:
            print(f"Error creating Firebase user: {e}")
            print(f"Traceback: {traceback.format_exc()}")
            # Keep consistent with app.py error handling
            raise e
    
    async def delete_user(self, uid: str) -> bool:
        """Delete Firebase user asynchronously"""
        try:
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(
                self.executor,
                lambda: auth.delete_user(uid)
            )
            return True
        except Exception as e:
            print(f"Error deleting Firebase user: {e}")
            print(f"Traceback: {traceback.format_exc()}")
            return False
    
    async def get_user(self, uid: str) -> Optional[auth.UserRecord]:
        """Get Firebase user asynchronously"""
        try:
            loop = asyncio.get_event_loop()
            user_record = await loop.run_in_executor(
                self.executor,
                lambda: auth.get_user(uid)
            )
            return user_record
        except Exception as e:
            print(f"Error getting Firebase user: {e}")
            print(f"Traceback: {traceback.format_exc()}")
            return None
    
    def __del__(self):
        """Cleanup thread pool executor"""
        if hasattr(self, 'executor'):
            self.executor.shutdown(wait=False)
