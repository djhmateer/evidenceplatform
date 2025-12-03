from typing import List, Optional, Dict, Any

from pydantic import BaseModel


class HarHeader(BaseModel):
    name: str
    value: str

class HarQueryString(BaseModel):
    name: str
    value: str

class HarCookie(BaseModel):
    name: str
    value: str
    path: Optional[str] = None
    domain: Optional[str] = None
    expires: Optional[str] = None
    httpOnly: Optional[bool] = None
    secure: Optional[bool] = None
    sameSite: Optional[str] = None

class HarPostData(BaseModel):
    mimeType: str
    params: Optional[List[Dict[str, Any]]] = None
    text: Optional[str] = None

class HarRequest(BaseModel):
    method: str
    url: str
    httpVersion: str
    cookies: List[HarCookie]
    headers: List[HarHeader]
    queryString: List[HarQueryString]
    postData: Optional[HarPostData] = None
    headersSize: int
    bodySize: int

class HarContent(BaseModel):
    size: int
    mimeType: str
    text: Optional[str] = None
    encoding: Optional[str] = None

class HarResponse(BaseModel):
    status: int
    statusText: str
    httpVersion: str
    cookies: List[HarCookie]
    headers: List[HarHeader]
    content: HarContent
    redirectURL: str
    headersSize: int
    bodySize: int

class HarTimings(BaseModel):
    blocked: Optional[float] = None
    dns: Optional[float] = None
    connect: Optional[float] = None
    send: float
    wait: float
    receive: float
    ssl: Optional[float] = None

class HarEntry(BaseModel):
    startedDateTime: str
    time: float
    request: HarRequest
    response: HarResponse
    cache: Dict[str, Any]
    timings: HarTimings
    serverIPAddress: Optional[str] = None
    connection: Optional[str] = None
    pageref: Optional[str] = None

class HarLog(BaseModel):
    version: str
    creator: Dict[str, Any]
    browser: Optional[Dict[str, Any]] = None
    pages: Optional[List[Dict[str, Any]]] = None
    entries: List[HarEntry]

class HarFile(BaseModel):
    log: HarLog