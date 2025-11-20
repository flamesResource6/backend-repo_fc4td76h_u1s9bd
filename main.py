import os
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import List, Optional, Any, Dict
from bson import ObjectId
from datetime import datetime

from database import db, create_document, get_documents
from schemas import Todo as TodoSchema

app = FastAPI(title="GenZ Todo Generator API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------- Utils ----------

def to_doc(obj: Dict[str, Any]) -> Dict[str, Any]:
    if not obj:
        return {}
    obj["id"] = str(obj.pop("_id")) if obj.get("_id") else None
    # Convert datetimes to isoformat
    for k in ["created_at", "updated_at"]:
        if isinstance(obj.get(k), (datetime,)):
            obj[k] = obj[k].isoformat()
    return obj


# ---------- Models ----------

class TodoCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)
    vibe: Optional[str] = None
    priority: Optional[str] = Field(None, pattern=r"^(low|medium|high)$")
    completed: bool = False


class TodoUpdate(BaseModel):
    title: Optional[str] = Field(None, min_length=1, max_length=200)
    vibe: Optional[str] = None
    priority: Optional[str] = Field(None, pattern=r"^(low|medium|high)$")
    completed: Optional[bool] = None


class GenerateRequest(BaseModel):
    prompt: str = Field(..., min_length=1, description="Describe what you want to get done")
    vibe: Optional[str] = Field(None, description="Mood or theme for the plan")
    count: int = Field(6, ge=1, le=15)


# ---------- Root & Health ----------

@app.get("/")
def read_root():
    return {"message": "GenZ Todo Generator Backend"}


@app.get("/test")
def test_database():
    response = {
        "backend": "✅ Running",
        "database": "❌ Not Available",
        "database_url": "✅ Set" if os.getenv("DATABASE_URL") else "❌ Not Set",
        "database_name": "✅ Set" if os.getenv("DATABASE_NAME") else "❌ Not Set",
        "connection_status": "Not Connected",
        "collections": []
    }
    try:
        if db is not None:
            response["database"] = "✅ Available"
            response["connection_status"] = "Connected"
            response["collections"] = db.list_collection_names()[:10]
        else:
            response["database"] = "⚠️  Available but not initialized"
    except Exception as e:
        response["database"] = f"❌ Error: {str(e)[:80]}"
    return response


# ---------- Todo Endpoints ----------

@app.get("/api/todos")
def list_todos():
    if db is None:
        raise HTTPException(status_code=500, detail="Database not available")
    docs = db["todo"].find({}).sort("created_at", -1)
    return [to_doc(d) for d in docs]


@app.post("/api/todos", status_code=201)
def create_todo(todo: TodoCreate):
    # Validate using Pydantic schema defined for collection
    _ = TodoSchema(**todo.model_dump())
    inserted_id = create_document("todo", todo.model_dump())
    doc = db["todo"].find_one({"_id": ObjectId(inserted_id)})
    return to_doc(doc)


@app.patch("/api/todos/{todo_id}")
def update_todo(todo_id: str, payload: TodoUpdate):
    if db is None:
        raise HTTPException(status_code=500, detail="Database not available")
    try:
        oid = ObjectId(todo_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid id")

    updates = {k: v for k, v in payload.model_dump(exclude_unset=True).items() if v is not None}
    if not updates:
        return {"ok": True}
    updates["updated_at"] = datetime.utcnow()

    res = db["todo"].update_one({"_id": oid}, {"$set": updates})
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="Todo not found")
    doc = db["todo"].find_one({"_id": oid})
    return to_doc(doc)


@app.delete("/api/todos/{todo_id}")
def delete_todo(todo_id: str):
    if db is None:
        raise HTTPException(status_code=500, detail="Database not available")
    try:
        oid = ObjectId(todo_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid id")

    res = db["todo"].delete_one({"_id": oid})
    if res.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Todo not found")
    return {"ok": True}


# ---------- Generator ----------

VIBE_SNIPPETS = {
    "study": [
        "Skim lecture slides to map topics",
        "Active recall on 20 flashcards",
        "Practice 2 problem sets",
        "Summarize key formulas in 1 page",
        "Pomodoro x4 (25/5)",
    ],
    "gym": [
        "Dynamic warm-up (8 min)",
        "Compound lifts: 5x5",
        "Accessory superset x3",
        "10 min incline walk",
        "Protein + stretch cooldown",
    ],
    "reset": [
        "Quick tidy: desk + floor",
        "Inbox zero sprint (15m)",
        "Laundry + fold",
        "Plan tomorrow in 3 bullets",
        "Long shower + skincare",
    ],
    "deep work": [
        "Block distractions (focus mode)",
        "Define 1 clear outcome",
        "Single-task sprint (45m)",
        "Short walk reset",
        "Review + commit next step",
    ],
    "errands": [
        "Groceries (10 items)",
        "Post office drop",
        "Refill essentials",
        "Wash car quick",
        "Call appointment",
    ],
    "content": [
        "Idea dump (10 hooks)",
        "Outline 1 long-form",
        "Record A-roll",
        "B-roll pickup list",
        "Edit + thumbnail draft",
    ],
}

PRIORITY_ORDER = ["high", "medium", "low"]


def gen_priority(idx: int) -> str:
    return PRIORITY_ORDER[min(idx % 3, 2)]


def generate_tasks(prompt: str, vibe: Optional[str], count: int) -> List[Dict[str, Any]]:
    base = []
    key = (vibe or "").strip().lower()
    if key in VIBE_SNIPPETS:
        base = VIBE_SNIPPETS[key].copy()
    # Blend prompt keywords into tasks
    words = [w for w in prompt.split() if len(w) > 3][:4]
    if words:
        base.insert(0, f"Define goal: {' '.join(words)}")
    if not base:
        base = [
            "Brain dump tasks",
            "Sort by impact",
            "Pick top 3 must-dos",
            "Schedule time blocks",
            "Ship one tiny win",
        ]
    tasks = []
    i = 0
    while len(tasks) < count:
        text = base[i % len(base)]
        if i >= len(base):
            text = f"{text} (round {i // len(base) + 1})"
        tasks.append({
            "title": text,
            "vibe": vibe,
            "completed": False,
            "priority": gen_priority(i)
        })
        i += 1
    return tasks


@app.post("/api/todos/generate")
def generate_todos(req: GenerateRequest):
    if db is None:
        raise HTTPException(status_code=500, detail="Database not available")
    tasks = generate_tasks(req.prompt, req.vibe, req.count)
    inserted_ids = []
    for t in tasks:
        _id = create_document("todo", t)
        inserted_ids.append(ObjectId(_id))
    docs = db["todo"].find({"_id": {"$in": inserted_ids}})
    # Preserve order
    docs_map = {str(d["_id"]): d for d in docs}
    ordered = [to_doc(docs_map[str(i)]) for i in inserted_ids if str(i) in docs_map]
    return {"items": ordered, "count": len(ordered)}


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
