from pydantic import BaseModel
from typing import List

class Option(BaseModel):
    option_id: str
    title: str
    agent_id: str
    asset_id: int

class OptionsList(BaseModel):
    options: List[Option]
