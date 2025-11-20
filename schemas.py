"""
Database Schemas for Lulu Recipe Hub

Each Pydantic model represents a MongoDB collection. Collection name is the
lowercase of the class name by convention in this project helper.
"""
from __future__ import annotations
from typing import List, Optional, Dict
from pydantic import BaseModel, Field


class Ingredient(BaseModel):
    name: str = Field(..., description="Ingredient name")
    image: Optional[str] = Field(None, description="Image URL for ingredient")
    unit: Optional[str] = Field(None, description="Unit such as g, ml, cup")
    substitutions: List[str] = Field(default_factory=list, description="Alternative ingredients")


class RecipeIngredient(BaseModel):
    name: str
    quantity: Optional[float] = None
    unit: Optional[str] = None
    image: Optional[str] = None
    substitutions: List[str] = Field(default_factory=list)


class Recipe(BaseModel):
    title: str
    description: str
    image: Optional[str] = None
    prep_time_min: int = Field(ge=0, description="Preparation time in minutes")
    age_range: str = Field(..., description="Recommended age range, e.g., '6-9 months'")
    ingredients: List[RecipeIngredient]
    steps: List[str]
    tags: List[str] = Field(default_factory=list)


class Review(BaseModel):
    recipe_id: str
    rating: int = Field(..., ge=1, le=5)
    note: Optional[str] = None


class PantryItem(BaseModel):
    name: str
    quantity: float = 1
    unit: Optional[str] = None
    image: Optional[str] = None


class MealSlot(BaseModel):
    breakfast: Optional[str] = None  # recipe_id
    lunch: Optional[str] = None
    dinner: Optional[str] = None


class MealPlan(BaseModel):
    week_start: str = Field(..., description="ISO date string (Monday)")
    days: Dict[str, MealSlot]  # keys: Mon-Sun


class ShoppingItem(BaseModel):
    name: str
    quantity: float = 1
    unit: Optional[str] = None
    purchased: bool = False


class Reminder(BaseModel):
    title: str
    due_at: str  # ISO datetime string
    type: str = Field("meal", description="meal | shopping | other")
    notes: Optional[str] = None
