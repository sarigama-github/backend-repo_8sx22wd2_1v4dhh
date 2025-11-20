import os
from typing import List, Optional, Dict, Any
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from bson import ObjectId

from database import db, create_document, get_documents
from schemas import Recipe, PantryItem, MealPlan, Reminder, Review

app = FastAPI(title="Lulu Recipe Hub API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class IdModel(BaseModel):
    id: str


# Utility helpers
class PyObjectId(ObjectId):
    @classmethod
    def __get_validators__(cls):
        yield cls.validate

    @classmethod
    def validate(cls, v):
        if not ObjectId.is_valid(v):
            raise ValueError("Invalid ObjectId")
        return ObjectId(v)


def oid_str(doc: Dict[str, Any]) -> Dict[str, Any]:
    if not doc:
        return doc
    d = {**doc}
    if d.get("_id") is not None:
        d["id"] = str(d.pop("_id"))
    # convert nested ObjectIds if any
    for k, v in list(d.items()):
        if isinstance(v, ObjectId):
            d[k] = str(v)
    return d


# Root endpoints
@app.get("/")
def read_root():
    return {"message": "Lulu Recipe Hub API running"}


@app.get("/test")
def test_database():
    res = {
        "backend": "✅ Running",
        "database": "❌ Not Available",
        "database_url": "✅ Set" if os.getenv("DATABASE_URL") else "❌ Not Set",
        "database_name": "✅ Set" if os.getenv("DATABASE_NAME") else "❌ Not Set",
        "connection_status": "Not Connected",
        "collections": [],
    }
    try:
        if db is not None:
            res["database"] = "✅ Connected & Working"
            res["connection_status"] = "Connected"
            res["collections"] = db.list_collection_names()
    except Exception as e:
        res["database"] = f"⚠️ Connected but error: {str(e)[:80]}"
    return res


# ------- Recipes -------
@app.get("/api/recipes")
def list_recipes(include_reviews: bool = False):
    items = list(db["recipe"].find().sort("title"))
    recipes = [oid_str(i) for i in items]
    if include_reviews:
        for r in recipes:
            r_reviews = list(db["review"].find({"recipe_id": r["id"]}))
            r["reviews"] = [oid_str(rv) for rv in r_reviews]
            if r_reviews:
                r["avg_rating"] = round(sum(rv.get("rating", 0) for rv in r_reviews) / len(r_reviews), 2)
            else:
                r["avg_rating"] = None
    return {"recipes": recipes}


@app.post("/api/recipes")
def create_recipe(payload: Recipe):
    new_id = create_document("recipe", payload)
    return {"id": new_id}


@app.get("/api/recipes/{recipe_id}")
def get_recipe(recipe_id: str):
    doc = db["recipe"].find_one({"_id": ObjectId(recipe_id)})
    if not doc:
        raise HTTPException(status_code=404, detail="Recipe not found")
    r = oid_str(doc)
    r_reviews = list(db["review"].find({"recipe_id": recipe_id}))
    r["reviews"] = [oid_str(rv) for rv in r_reviews]
    return r


@app.put("/api/recipes/{recipe_id}")
def update_recipe(recipe_id: str, payload: Recipe):
    data = payload.model_dump()
    data["updated_at"] = __import__("datetime").datetime.utcnow()
    result = db["recipe"].update_one({"_id": ObjectId(recipe_id)}, {"$set": data})
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Recipe not found")
    return {"status": "ok"}


@app.delete("/api/recipes/{recipe_id}")
def delete_recipe(recipe_id: str):
    db["recipe"].delete_one({"_id": ObjectId(recipe_id)})
    db["review"].delete_many({"recipe_id": recipe_id})
    return {"status": "ok"}


# Reviews
@app.get("/api/recipes/{recipe_id}/reviews")
def list_reviews(recipe_id: str):
    reviews = [oid_str(d) for d in db["review"].find({"recipe_id": recipe_id}).sort("_id", -1)]
    return {"reviews": reviews}


@app.post("/api/recipes/{recipe_id}/reviews")
def add_review(recipe_id: str, payload: Review):
    if payload.recipe_id != recipe_id:
        raise HTTPException(status_code=400, detail="recipe_id mismatch")
    rid = create_document("review", payload)
    return {"id": rid}


# Pantry
@app.get("/api/pantry")
def get_pantry():
    items = [oid_str(d) for d in db["pantryitem"].find().sort("name")]
    return {"items": items}


@app.post("/api/pantry")
def add_pantry_item(item: PantryItem):
    # merge if same name+unit
    existing = db["pantryitem"].find_one({"name": item.name, "unit": item.unit})
    if existing:
        db["pantryitem"].update_one({"_id": existing["_id"]}, {"$inc": {"quantity": item.quantity}})
        return {"id": str(existing["_id"]) }
    new_id = create_document("pantryitem", item)
    return {"id": new_id}


class PantryUpdate(BaseModel):
    quantity: Optional[float] = None
    unit: Optional[str] = None


@app.put("/api/pantry/{item_id}")
def update_pantry(item_id: str, update: PantryUpdate):
    upd = {k: v for k, v in update.model_dump().items() if v is not None}
    if not upd:
        return {"status": "noop"}
    db["pantryitem"].update_one({"_id": ObjectId(item_id)}, {"$set": upd})
    return {"status": "ok"}


@app.delete("/api/pantry/{item_id}")
def remove_pantry(item_id: str):
    db["pantryitem"].delete_one({"_id": ObjectId(item_id)})
    return {"status": "ok"}


# Suggestions and can-make
@app.get("/api/suggest")
def suggest_recipes():
    pantry = list(db["pantryitem"].find())
    have = set(i["name"].strip().lower() for i in pantry)
    suggestions = []
    for doc in db["recipe"].find():
        needed = []
        for ing in doc.get("ingredients", []):
            name = (ing.get("name") or "").strip().lower()
            subs = [s.strip().lower() for s in ing.get("substitutions", [])]
            if name in have or any(s in have for s in subs):
                continue
            needed.append(ing.get("name"))
        can_make = len(needed) == 0
        suggestions.append({
            "id": str(doc["_id"]),
            "title": doc.get("title"),
            "image": doc.get("image"),
            "needed": needed,
            "can_make": can_make,
            "missing_count": len(needed),
        })
    suggestions.sort(key=lambda x: (x["missing_count"], x["title"]))
    return {"suggestions": suggestions}


# Meal Plans
@app.get("/api/mealplan/{week_start}")
def get_meal_plan(week_start: str):
    doc = db["mealplan"].find_one({"week_start": week_start})
    if not doc:
        # create empty template
        empty = {
            "week_start": week_start,
            "days": {d: {"breakfast": None, "lunch": None, "dinner": None} for d in [
                "Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"
            ]}
        }
        return empty
    return oid_str(doc)


@app.post("/api/mealplan")
def save_meal_plan(plan: MealPlan):
    existing = db["mealplan"].find_one({"week_start": plan.week_start})
    data = plan.model_dump()
    if existing:
        db["mealplan"].update_one({"_id": existing["_id"]}, {"$set": data})
        return {"id": str(existing["_id"]) }
    new_id = create_document("mealplan", data)
    return {"id": new_id}


@app.post("/api/mealplan/{week_start}/auto-fill")
def auto_fill_mealplan(week_start: str):
    # choose recipes you can make first, then others
    sug = suggest_recipes()["suggestions"]
    can = [s["id"] for s in sug if s["can_make"]]
    others = [s["id"] for s in sug if not s["can_make"]]
    order = can + others
    days = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    slots = ["breakfast", "lunch", "dinner"]
    plan = {d: {s: None for s in slots} for d in days}
    idx = 0
    if not order:
        return {"days": plan}
    for d in days:
        for s in slots:
            plan[d][s] = order[idx % len(order)]
            idx += 1
    existing = db["mealplan"].find_one({"week_start": week_start})
    data = {"week_start": week_start, "days": plan}
    if existing:
        db["mealplan"].update_one({"_id": existing["_id"]}, {"$set": data})
    else:
        create_document("mealplan", data)
    return data


# Shopping list (per week)
@app.get("/api/shopping-list/{week_start}")
def generate_shopping_list(week_start: str):
    plan = db["mealplan"].find_one({"week_start": week_start})
    if not plan:
        return {"items": []}
    recipe_ids = set()
    for d, slots in plan.get("days", {}).items():
        for rid in slots.values():
            if rid:
                recipe_ids.add(rid)
    ingredients_needed: Dict[str, Dict[str, Any]] = {}
    for rid in recipe_ids:
        r = db["recipe"].find_one({"_id": ObjectId(rid)})
        if not r:
            continue
        for ing in r.get("ingredients", []):
            name = ing.get("name")
            unit = ing.get("unit")
            qty = ing.get("quantity") or 1
            key = f"{name}|{unit}"
            if key not in ingredients_needed:
                ingredients_needed[key] = {"name": name, "unit": unit, "quantity": 0}
            ingredients_needed[key]["quantity"] += qty
    pantry = list(db["pantryitem"].find())
    have = {}
    for p in pantry:
        key = f"{p.get('name')}|{p.get('unit')}"
        have[key] = have.get(key, 0) + float(p.get("quantity", 0))
    result = []
    for key, v in ingredients_needed.items():
        missing = v["quantity"] - have.get(key, 0)
        if missing > 0.0001:
            result.append({"name": v["name"], "unit": v["unit"], "quantity": round(missing, 2), "purchased": False})
    result.sort(key=lambda x: x["name"])
    return {"items": result}


# Reminders
@app.get("/api/reminders")
def list_reminders():
    items = [oid_str(d) for d in db["reminder"].find().sort("due_at")]
    return {"reminders": items}


@app.post("/api/reminders")
def create_reminder(rem: Reminder):
    rid = create_document("reminder", rem)
    return {"id": rid}


@app.delete("/api/reminders/{reminder_id}")
def delete_reminder(reminder_id: str):
    db["reminder"].delete_one({"_id": ObjectId(reminder_id)})
    return {"status": "ok"}


# Simple seed endpoint to preload recipes
@app.post("/api/seed")
def seed_recipes():
    count = db["recipe"].count_documents({})
    if count >= 25:
        return {"status": "ok", "message": "Recipes already seeded", "count": count}
    sample_recipes = []
    base_ings = [
        {"name": "Apple", "quantity": 1, "unit": "pc", "substitutions": ["Pear"]},
        {"name": "Banana", "quantity": 1, "unit": "pc", "substitutions": ["Avocado"]},
        {"name": "Oatmeal", "quantity": 30, "unit": "g", "substitutions": ["Rice Cereal"]},
        {"name": "Sweet Potato", "quantity": 100, "unit": "g", "substitutions": ["Pumpkin"]},
        {"name": "Carrot", "quantity": 60, "unit": "g", "substitutions": ["Butternut Squash"]},
        {"name": "Pear", "quantity": 1, "unit": "pc", "substitutions": ["Apple"]},
        {"name": "Avocado", "quantity": 1, "unit": "pc", "substitutions": ["Banana"]},
        {"name": "Peas", "quantity": 60, "unit": "g", "substitutions": ["Green Beans"]},
        {"name": "Chicken", "quantity": 80, "unit": "g", "substitutions": ["Turkey"]},
        {"name": "Rice", "quantity": 30, "unit": "g", "substitutions": ["Quinoa"]},
    ]
    images = [
        "https://images.unsplash.com/photo-1512621776951-a57141f2eefd",
        "https://images.unsplash.com/photo-1490474418585-ba9bad8fd0ea",
        "https://images.unsplash.com/photo-1490818387583-1baba5e638af",
        "https://images.unsplash.com/photo-1505253716362-afaea1d3d1af",
        "https://images.unsplash.com/photo-1512058564366-18510be2db19",
    ]
    for i in range(1, 26):
        ing = [base_ings[i % len(base_ings)], base_ings[(i+3) % len(base_ings)]]
        sample_recipes.append({
            "title": f"Lulu's Yummy Mix #{i}",
            "description": "A gentle, tasty puree perfect for Lulu.",
            "image": images[i % len(images)],
            "prep_time_min": 10 + (i % 15),
            "age_range": "6-12 months",
            "ingredients": ing,
            "steps": [
                "Steam ingredients until soft",
                "Blend to desired consistency",
                "Serve lukewarm"
            ],
            "tags": ["easy", "smooth"],
        })
    db["recipe"].insert_many(sample_recipes)
    return {"status": "ok", "inserted": len(sample_recipes)}


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
