from pydantic import BaseModel, Field


class ChatQueryRequest(BaseModel):
    

    question: str = Field(
        ...,
        min_length=1,
        description="Formula 1 question",
    )

    season: int | None = None

    round_number: int | None = None


class SourceRecord(BaseModel):
    

    id: str

    source: str

    season: int | None = None

    round: int | None = None


class ChatQueryResponse(BaseModel):
    

    answer: str

    supporting_facts: list[str]

    sources: list[SourceRecord]

    confidence: str

    limitations: list[str]