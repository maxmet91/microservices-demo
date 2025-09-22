from numpy import short
from pydantic import BaseModel

class Option(BaseModel):
    option_id: str
    title: str
    agent_id: str
    asset_id: str
    short_description: str = ""
    
