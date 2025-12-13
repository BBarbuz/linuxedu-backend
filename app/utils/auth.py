# """
# Authentication utilities and dependency injection
# """
# from fastapi import Depends, HTTPException, status, Request
# from fastapi.security import HTTPBearer
# from sqlalchemy.ext.asyncio import AsyncSession
# from sqlalchemy.future import select
# from app.database import get_db
# from app.models.user import User
# from app.security import verify_token

# security = HTTPBearer()

# async def get_current_user(
#     request: Request = None,
#     token: str = Depends(security),
#     db: AsyncSession = Depends(get_db)
# ) -> User:
#     """Get current user from JWT token (header or cookie)"""
    
#     # Spróbuj z headera Authorization
#     if token and token.credentials:
#         token_str = token.credentials
#     else:
#         # Spróbuj z cookies
#         token_str = request.cookies.get("access_token")
    
#     if not token_str:
#         raise HTTPException(
#             status_code=status.HTTP_401_UNAUTHORIZED,
#             detail="No token provided"
#         )
    
#     payload = verify_token(token_str)
#     if not payload:
#         raise HTTPException(
#             status_code=status.HTTP_401_UNAUTHORIZED,
#             detail="Invalid token"
#         )
    
#     user_id = payload.get("sub")
#     if not user_id:
#         raise HTTPException(
#             status_code=status.HTTP_401_UNAUTHORIZED,
#             detail="Invalid token"
#         )
    
#     result = await db.execute(select(User).where(User.id == int(user_id)))
#     user = result.scalar_one_or_none()
    
#     if not user:
#         raise HTTPException(
#             status_code=status.HTTP_401_UNAUTHORIZED,
#             detail="User not found"
#         )
    
#     if not user.is_active:
#         raise HTTPException(
#             status_code=status.HTTP_403_FORBIDDEN,
#             detail="User account is inactive"
#         )
    
#     return user

# def require_role(role: str):
#     """Dependency to check user role"""
#     async def role_checker(current_user: User = Depends(get_current_user)) -> User:
#         if current_user.role != role:
#             raise HTTPException(
#                 status_code=status.HTTP_403_FORBIDDEN,
#                 detail="Insufficient permissions"
#             )
#         return current_user
#     return role_checker


# # from fastapi import Depends, HTTPException, status, Request
# # from fastapi.security import HTTPBearer
# # from sqlalchemy.ext.asyncio import AsyncSession
# # from sqlalchemy.future import select
# # from app.database import get_db
# # from app.models.user import User
# # from app.security import verify_token

# # # NIE rzuca automatycznie 403 gdy brak headera
# # security = HTTPBearer(auto_error=False)

# # async def get_current_user(
# #     request: Request,
# #     token = Depends(security),
# #     db: AsyncSession = Depends(get_db)
# # ) -> User:
# #     """Get current user from JWT token (header OR cookie)"""

# #     token_str = None

# #     # 1. Spróbuj z Authorization: Bearer ...
# #     if token and token.credentials:
# #         token_str = token.credentials
# #     else:
# #         # 2. Spróbuj z cookies
# #         token_str = request.cookies.get("access_token")

# #     if not token_str:
# #         raise HTTPException(
# #             status_code=status.HTTP_401_UNAUTHORIZED,
# #             detail="No token provided"
# #         )

# #     payload = verify_token(token_str)
# #     if not payload:
# #         raise HTTPException(
# #             status_code=status.HTTP_401_UNAUTHORIZED,
# #             detail="Invalid token"
# #         )

# #     user_id = payload.get("sub")
# #     if not user_id:
# #         raise HTTPException(
# #             status_code=status.HTTP_401_UNAUTHORIZED,
# #             detail="Invalid token"
# #         )

# #     result = await db.execute(select(User).where(User.id == int(user_id)))
# #     user = result.scalar_one_or_none()

# #     if not user:
# #         raise HTTPException(
# #             status_code=status.HTTP_401_UNAUTHORIZED,
# #             detail="User not found"
# #         )

# #     if not user.is_active:
# #         raise HTTPException(
# #             status_code=status.HTTP_403_FORBIDDEN,
# #             detail="User account is inactive"
# #         )

# #     return user

# # def require_role(role: str):
# #     async def role_checker(current_user: User = Depends(get_current_user)) -> User:
# #         if current_user.role != role:
# #             raise HTTPException(
# #                 status_code=status.HTTP_403_FORBIDDEN,
# #                 detail="Insufficient permissions"
# #             )
# #         return current_user
# #     return role

"""
Authentication utilities and dependency injection
"""
from fastapi import Depends, HTTPException, status, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from app.database import get_db
from app.models.user import User
from app.security import verify_token

security = HTTPBearer(auto_error=False)  # ← Nie rzuca 401 automatycznie

async def get_current_user(
    request: Request,
    token: HTTPAuthorizationCredentials = Depends(security),
    db: AsyncSession = Depends(get_db)
) -> User:
    """Get current user from JWT token (header or cookie)"""
    
    token_str = None
    
    # 1. Spróbuj z headera Authorization: Bearer ...
    if token and token.credentials:
        token_str = token.credentials
    
    # 2. Spróbuj z cookies (fallback dla HTTP localhost)
    if not token_str:
        token_str = request.cookies.get("accesstoken")  # ← javascript-cookie używa lowercase
    
    if not token_str:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="No token provided"
        )
    
    payload = verify_token(token_str)
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token"
        )
    
    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token"
        )
    
    result = await db.execute(select(User).where(User.id == int(user_id)))
    user = result.scalar_one_or_none()
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found"
        )
    
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account is inactive"
        )
    
    return user

def require_role(role: str):
    """Dependency to check user role"""
    async def role_checker(current_user: User = Depends(get_current_user)) -> User:
        if current_user.role != role:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Insufficient permissions"
            )
        return current_user
    return role_checker