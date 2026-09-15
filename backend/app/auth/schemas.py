from pydantic import BaseModel


class LoginRequest(BaseModel):
    username: str
    password: str


class RefreshRequest(BaseModel):
    refresh_token: str


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int


class AccessTokenOnly(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int


class EmployeeIdentity(BaseModel):
    real_name: str
    employee_role: str
