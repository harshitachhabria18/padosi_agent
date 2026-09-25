from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from fastapi_app.schemas.auth import LoginRequest, LoginResponse
from fastapi_app.repositories.user_repository import UserRepository
from fastapi_app.repositories.agent_repository import AgentRepository
from fastapi_app.utils.auth import verify_password, generate_and_register_token, get_password_hash
from fastapi_app.config import settings
from datetime import datetime
import time

# Simple in-memory throttle store: {ip: {"attempts": int, "expires_at": float}}
login_attempts_store = {}

# Mirrors apps/agents/views/auth.py: the only agent statuses that deny a session.
BLOCKED_AGENT_STATUSES = ('suspended', 'blacklisted', 'rejected')

def check_login_throttle(ip: str) -> bool:
    record = login_attempts_store.get(ip)
    if record:
        if time.time() > record["expires_at"]:
            login_attempts_store.pop(ip, None)
            return True
        if record["attempts"] >= 6:
            return False
    return True

def record_login_attempt(ip: str):
    record = login_attempts_store.get(ip)
    now = time.time()
    if not record or now > record["expires_at"]:
        login_attempts_store[ip] = {"attempts": 1, "expires_at": now + 60}
    else:
        login_attempts_store[ip]["attempts"] += 1

def clear_login_throttle(ip: str):
    login_attempts_store.pop(ip, None)

class AuthService:
    def __init__(self, user_repo: UserRepository, agent_repo: AgentRepository, db: Session):
        self.user_repo = user_repo
        self.agent_repo = agent_repo
        self.db = db

    def login(self, request: LoginRequest, req: Request) -> JSONResponse:
        # Extract client IP
        # Trusted-proxy rule: a raw X-Forwarded-For let clients reset the
        # login throttle on every attempt.
        from fastapi_app.utils.client_ip import get_client_ip
        ip = get_client_ip(req)

        # Rate Limit check
        if not check_login_throttle(ip):
            return JSONResponse(
                status_code=429,
                content={"success": False, "message": "Too many login attempts. Please try again after 1 minute."}
            )

        # Check for empty credentials
        if not request.email or not request.password:
            record_login_attempt(ip)
            return JSONResponse(
                status_code=400,
                content={"success": False, "message": "Please enter both email and password."}
            )

        # 1. Fetch User by email from primary `users` table
        user = self.user_repo.get_by_email(request.email)
        agent = self.agent_repo.get_by_email(request.email)

        # 2. Verify password against `users` table (bcrypt, same as admin login)
        password_valid = False
        if user and user.password:
            password_valid = verify_password(request.password, user.password)

        # Fallback: check Django `auth_user` table if user is missing or password mismatch in `users` table
        if not password_valid:
            from sqlalchemy import text
            auth_user_row = self.db.execute(
                text("SELECT id, username, email, password, is_active FROM auth_user WHERE LOWER(email) = LOWER(:email)"),
                {"email": request.email}
            ).fetchone()

            if auth_user_row:
                auth_id, auth_username, auth_email, auth_password, auth_is_active = auth_user_row
                if verify_password(request.password, auth_password):
                    password_valid = True
                    if user:
                        # Sync verified password to users table
                        user.password = auth_password
                        try:
                            self.db.commit()
                        except Exception:
                            self.db.rollback()
                    else:
                        # Create missing user entry in users table based on auth_user
                        try:
                            from fastapi_app.models.user import User as UserModel
                            user = UserModel(
                                fullname=auth_username,
                                email=auth_email,
                                password=auth_password,
                                role='agent',
                                status='active' if auth_is_active else 'inactive'
                            )
                            self.db.add(user)
                            self.db.commit()
                        except Exception:
                            self.db.rollback()

        # Orphan incomplete/pending_payment agents may have no users row yet.
        if not password_valid and agent and agent.status in ('incomplete', 'pending_payment'):
            stored = user.password if user and user.password else None
            if not stored and request.password:
                from apps.agents.services.account_auth import default_agent_temp_password

                temp_password = default_agent_temp_password(agent)
                legacy_email_password = (
                    agent.email
                    and request.password.lower() == agent.email.lower()
                )
                if request.password == temp_password or legacy_email_password:
                    password_valid = True
                    if not user:
                        try:
                            from fastapi_app.models.user import UserModel
                            user = UserModel(
                                fullname=agent.fullname or agent.email,
                                email=agent.email,
                                password=get_password_hash(request.password),
                                role='agent',
                                status='active',
                                email_verified_at=datetime.utcnow(),
                            )
                            self.db.add(user)
                            self.db.flush()
                            if not agent.user_id:
                                agent.user_id = user.id
                            self.db.commit()
                        except Exception:
                            self.db.rollback()
                            user = self.user_repo.get_by_email(request.email)

        if not user or not password_valid:
            record_login_attempt(ip)
            return JSONResponse(
                status_code=401,
                content={"success": False, "message": "Please Enter Valid Login Details"}
            )


        # 3. Check role
        if user.role != 'agent':
            record_login_attempt(ip)
            return JSONResponse(
                status_code=401,
                content={"success": False, "message": "Please use the correct login page for your account type."}
            )

        # 4. Check linked agent exists
        agent = self.agent_repo.get_by_email(user.email)
        if not agent:
            record_login_attempt(ip)
            return JSONResponse(
                status_code=200,
                content={"success": False, "message": "Agent profile not found."}
            )

        # 5. Check account status matching Django/Laravel
        if user.status == 'suspended':
            record_login_attempt(ip)
            return JSONResponse(
                status_code=200,
                content={"success": False, "message": "Your account has been suspended."}
            )
            
        if user.status == 'inactive':
            record_login_attempt(ip)
            return JSONResponse(
                status_code=200,
                content={"success": False, "message": "Your account is currently inactive."}
            )

        # Check Agent status specifically matching Django.
        # Django's agent_login only hard-blocks suspended/blacklisted/rejected;
        # `pending_approval` must stay able to sign in because submitting a
        # profile edit puts an otherwise healthy agent into that state.
        if agent.status in BLOCKED_AGENT_STATUSES:
            record_login_attempt(ip)
            return JSONResponse(
                status_code=200,
                content={"success": False, "message": f"Your account is currently {agent.status}."}
            )
        elif agent.status in ('incomplete', 'pending_payment', 'pending_accounts_payment'):
            record_login_attempt(ip)
            return JSONResponse(
                status_code=200,
                content={"success": False, "message": "Please complete plan selection and payment to activate your account."}
            )

        # Clear login throttle on successful auth
        clear_login_throttle(ip)

        # Update last login time
        user.last_login_at = datetime.utcnow()

        # 6. Generate and register unique JWT token in DB transactionally
        try:
            access_token = generate_and_register_token(
                db=self.db,
                email=user.email,
                role=user.role,
                user_id=user.id
            )
            self.db.commit()
        except Exception as e:
            self.db.rollback()
            return JSONResponse(
                status_code=500,
                content={"success": False, "message": "Authentication failed due to database transaction error."}
            )

        return JSONResponse(
            status_code=200,
            content={
                "success": True,
                "message": "Login successful.",
                "access_token": access_token,
                "token_type": "bearer",
                "expires_in": settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
                "agent_status": agent.status
            }
        )
