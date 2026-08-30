from datetime import datetime
from typing import Optional, Dict, List, Any
from pydantic import BaseModel, Field, ConfigDict


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


class TokenData(BaseModel):
    username: Optional[str] = None


class UserBase(BaseModel):
    username: str
    is_admin: bool = False

    model_config = ConfigDict(extra="allow")


class UserCreate(UserBase):
    password: str


class UserLogin(BaseModel):
    username: str
    password: str


class UserResponse(UserBase):
    id: int
    created_at: datetime

    class Config:
        from_attributes = True


class UserMeResponse(BaseModel):
    id: int
    username: str
    is_admin: bool
    created_at: datetime

    class Config:
        from_attributes = True


class ProfileBase(BaseModel):
    name: str

    model_config = ConfigDict(extra="allow")


class ProfileCreate(ProfileBase):
    pass


class ProfileUpdate(ProfileBase):
    pass


class ProfileResponse(ProfileBase):
    id: int
    created_at: datetime

    class Config:
        from_attributes = True


class ProfileWithRoutersResponse(ProfileResponse):
    routers: List["RouterResponse"] = []


class RouterBase(BaseModel):
    name: str
    values: Dict[str, Any] = Field(default_factory=dict)

    model_config = ConfigDict(extra="allow")


class RouterCreate(RouterBase):
    pass


class RouterUpdate(RouterBase):
    name: Optional[str] = None
    values: Optional[Dict[str, Any]] = None


class RouterResponse(RouterBase):
    id: int
    profile_id: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class VpnSessionsBase(BaseModel):
    router_id: int
    username: str
    protocol: str
    bytes_in: int = 0
    bytes_out: int = 0
    status: str = "active"

    model_config = ConfigDict(extra="allow")


class VpnSessionsCreate(VpnSessionsBase):
    pass


class VpnSessionsUpdate(BaseModel):
    bytes_in: Optional[int] = None
    bytes_out: Optional[int] = None
    status: Optional[str] = None


class VpnSessionsResponse(VpnSessionsBase):
    id: int
    connected_at: datetime

    class Config:
        from_attributes = True


ProfileWithRoutersResponse.model_rebuild()
