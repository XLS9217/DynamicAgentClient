from typing import Literal
from pydantic import BaseModel


class ClientInvokeMessage(BaseModel):
    type: Literal["invoke"] = "invoke"
    text: str