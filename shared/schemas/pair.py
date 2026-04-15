"""Schemas for MarketPair and PairClassificationCache JSONB fields."""

from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel

from shared.schemas.market import ResolutionVector


class ConstraintMatrix(BaseModel):
    """MarketPair.constraint_matrix — feasibility matrix with metadata.

    Built by ``build_constraint_matrix()`` or
    ``build_constraint_matrix_from_vectors()`` in the detector.
    Consumed by the optimizer to define the feasible joint-outcome space.
    """
    type: str
    outcomes_a: list[str]
    outcomes_b: list[str]
    matrix: list[list[int]]
    profit_bound: float
    correlation: Optional[str] = None
    implication_direction: Optional[str] = None
    classification_source: Optional[str] = None


class ClassificationResult(BaseModel):
    """PairClassificationCache.classification — LLM / rule-based output.

    Produced by ``classify_pair()`` or ``classify_llm_resolution()`` in the
    detector.  Stored in the classification cache and used to build pairs.
    """
    dependency_type: str
    confidence: float
    reasoning: str = ""
    correlation: Optional[str] = None
    implication_direction: Optional[str] = None
    valid_outcomes: Optional[List[ResolutionVector]] = None
    classification_source: Optional[str] = None
    prompt_version: Optional[str] = None
    prompt_adapter: Optional[str] = None
